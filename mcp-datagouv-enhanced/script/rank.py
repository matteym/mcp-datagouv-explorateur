#!/usr/bin/env python3
"""Parse result_*.txt, pertinence (fichiers dataset/ api/), popularité, top 10."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from script.env import Env, ROOT
from script.fetch import ResultStore
from script.metrics import DatasetMetricsIndex, MetricRow

DATASET_DIR = ROOT / "dataset"
API_DIR = ROOT / "api"
SCORES_DATASET = DATASET_DIR / "relevance_scores.json"
SCORES_API = API_DIR / "relevance_scores.json"

_ENTRY = re.compile(
    r"(?ms)^\d+\.\s+(?P<title>.+?)\n"
    r"\s+ID:\s+(?P<id>\S+)(?P<body>.*?)(?=\n\d+\.\s|\Z)"
)
_METRICS = re.compile(
    r"Métriques popularité:\s*([\d,]+)\s*visites,\s*([\d,]+)\s*téléchargements",
    re.I,
)
_FIELD = re.compile(r"^\s+(Organization|Tags|URL|Base API URL|Description):\s*(.*)", re.M)


@dataclass(frozen=True)
class RelevanceScore:
    id: str
    relevance: float
    reason: str


@dataclass
class CatalogEntry:
    kind: str
    id: str
    title: str
    organization: str
    url: str
    tags: str
    description: str
    visits: int
    downloads: int
    file_kind: str
    source_file: str
    relevance: float = 0.0
    popularity: float = 0.0
    score: float = 0.0
    note: str = ""


@dataclass
class RankReport:
    use_case: str
    weights: tuple[float, float]
    relevance_source: str
    datasets: list[CatalogEntry] = field(default_factory=list)
    apis: list[CatalogEntry] = field(default_factory=list)


class ResultRanker:
    def __init__(self, cfg: Env | None = None) -> None:
        self.cfg = cfg or Env.load()
        if not self.cfg.use_case:
            raise ValueError("USE_CASE manquant dans .env")
        wr, wp = 0.45, 0.55
        self.w_rel, self.w_pop = wr / (wr + wp), wp / (wr + wp)

    @staticmethod
    def _int(raw: str) -> int:
        return int(raw.replace(",", "").replace(" ", ""))

    @staticmethod
    def _pct(value: float) -> str:
        return f"{round(value * 100)}%"

    def _parse_file(self, path: Path, kind: str) -> list[CatalogEntry]:
        text = path.read_text(encoding="utf-8")
        m = re.search(r"result_[^_]+_(.+)\.txt$", path.name)
        file_kind = m.group(1) if m else "unknown"
        entries: list[CatalogEntry] = []
        for match in _ENTRY.finditer(text):
            body = match.group("body")
            visits, downloads = 0, 0
            if mm := _METRICS.search(body):
                visits, downloads = self._int(mm.group(1)), self._int(mm.group(2))
            fields = {k: v.strip() for k, v in _FIELD.findall(body)}
            entries.append(CatalogEntry(
                kind=kind,
                id=match.group("id"),
                title=match.group("title").strip(),
                organization=fields.get("Organization", ""),
                url=fields.get("URL", fields.get("Base API URL", "")),
                tags=fields.get("Tags", ""),
                description=fields.get("Description", ""),
                visits=visits,
                downloads=downloads,
                file_kind=file_kind,
                source_file=str(path),
            ))
        return entries

    def _apply_api_popularity_proxy(
        self, apis: list[CatalogEntry], datasets: list[CatalogEntry]
    ) -> None:
        index = DatasetMetricsIndex()
        for d in datasets:
            index.add(MetricRow(d.id, d.title, d.organization, d.tags, d.visits, d.downloads))
        for api in apis:
            if api.visits or api.downloads:
                continue
            v, dl, label = index.proxy_for_api(api.title, api.organization, api.tags)
            if v or dl:
                api.visits, api.downloads = v, dl
                if api.note:
                    api.note += f" | {label}"
                else:
                    api.note = label

    def _result_files(self, folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        slugs = {ResultStore.slug(t) for t in self.cfg.search_terms}
        paths = [
            p
            for slug in slugs
            for p in sorted(folder.glob(f"result_{slug}_*.txt"))
        ]
        return paths or sorted(folder.glob("result_*.txt"))

    def load_by_kind(self, kind: str, datasets_for_proxy: list[CatalogEntry] | None = None) -> list[CatalogEntry]:
        folder = DATASET_DIR if kind == "dataset" else API_DIR
        seen: set[str] = set()
        out: list[CatalogEntry] = []
        for path in self._result_files(folder):
            for entry in self._parse_file(path, kind):
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                out.append(entry)
        if kind == "api" and datasets_for_proxy is not None:
            self._apply_api_popularity_proxy(out, datasets_for_proxy)
        return out

    def load_all(self) -> list[CatalogEntry]:
        ds = self.load_by_kind("dataset")
        return ds + self.load_by_kind("api", datasets_for_proxy=ds)

    @staticmethod
    def _raw_popularity(entry: CatalogEntry) -> float:
        if entry.downloads == 0 and entry.visits == 0:
            return 0.0
        return math.log1p(entry.downloads) * 0.65 + math.log1p(entry.visits) * 0.35

    @staticmethod
    def _scores_path(kind: str) -> Path:
        return SCORES_DATASET if kind == "dataset" else SCORES_API

    def _load_scores(self, kind: str) -> dict[str, RelevanceScore]:
        path = self._scores_path(kind)
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("scores", [])
        return {
            str(r["id"]): RelevanceScore(
                id=str(r["id"]),
                relevance=max(0.0, min(1.0, float(r["relevance"]))),
                reason=str(r.get("reason", "")),
            )
            for r in items
        }

    def score_entries(self, entries: list[CatalogEntry], kind: str) -> tuple[list[CatalogEntry], str]:
        if not entries:
            return [], "aucune entrée"
        path = self._scores_path(kind)
        if not path.is_file():
            raise FileNotFoundError(
                f"{path.relative_to(ROOT)} absent — lancez datagouv_analyze (MCP)."
            )
        scores = self._load_scores(kind)
        pool = [e for e in entries if e.kind == kind] or entries
        raw_vals = [self._raw_popularity(e) for e in pool]
        max_pop = max(raw_vals) if raw_vals else 0.0
        for e in entries:
            sc = scores.get(e.id)
            e.relevance = sc.relevance if sc else 0.0
            reason = sc.reason if sc else "non scoré"
            if e.note and e.note not in reason:
                e.note = f"{reason} | {e.note}"
            else:
                e.note = reason
        if max_pop > 0:
            for e in pool:
                e.popularity = self._raw_popularity(e) / max_pop
        else:
            ordered = sorted(pool, key=lambda x: x.downloads + x.visits, reverse=True)
            n = len(ordered)
            for i, e in enumerate(ordered):
                e.popularity = 1.0 - (i / max(n - 1, 1)) * 0.4
        for e in pool:
            e.score = self.w_rel * e.relevance + self.w_pop * e.popularity
        return entries, str(path.relative_to(ROOT))

    def _rank_pool(self, entries: list[CatalogEntry], kind: str) -> list[CatalogEntry]:
        pool = [e for e in entries if e.kind == kind]
        pool.sort(key=lambda e: (e.score, e.relevance, e.popularity, e.downloads), reverse=True)
        return pool[:10]

    def _report_section(self, title: str, entries: list[CatalogEntry], source: str) -> str:
        wr, wp = self.w_rel, self.w_pop
        lines = [
            f"# Top 10 — {title}",
            f"Pertinence : {source}",
            f"Score = {self._pct(wr)}×pertinence + {self._pct(wp)}×popularité\n",
        ]
        for i, e in enumerate(entries, 1):
            lines.append(self._line(i, e))
        return "\n".join(lines)

    def build_report(self) -> RankReport:
        ds = self.load_by_kind("dataset")
        api = self.load_by_kind("api", datasets_for_proxy=ds)
        self.score_entries(ds, "dataset")
        self.score_entries(api, "api")
        return RankReport(
            use_case=self.cfg.use_case,
            weights=(self.w_rel, self.w_pop),
            relevance_source="dataset/relevance_scores.json + api/relevance_scores.json",
            datasets=self._rank_pool(ds, "dataset"),
            apis=self._rank_pool(api, "api"),
        )

    @staticmethod
    def _line(i: int, e: CatalogEntry) -> str:
        return (
            f"{i}. **{e.title}** (`{e.id}`)\n"
            f"   - Score **{ResultRanker._pct(e.score)}** "
            f"(pertinence {ResultRanker._pct(e.relevance)} + popularité {ResultRanker._pct(e.popularity)})\n"
            f"   - {e.downloads} téléchargements, {e.visits} visites | {e.file_kind}\n"
            f"   - {e.organization} | {e.note}\n"
            f"   - {e.url}\n"
        )

    def to_markdown(self) -> str:
        r = self.build_report()
        return (
            self._report_section(r.use_case, r.datasets, "dataset/relevance_scores.json")
            + "\n\n---\n\n"
            + self._report_section("APIs — " + r.use_case, r.apis, "api/relevance_scores.json")
        )

    def to_json(self) -> str:
        r = self.build_report()
        return json.dumps({
            "use_case": r.use_case,
            "relevance_source": r.relevance_source,
            "weights": {"relevance": r.weights[0], "popularity": r.weights[1]},
            "datasets": [asdict(e) for e in r.datasets],
            "apis": [asdict(e) for e in r.apis],
        }, ensure_ascii=False, indent=2)

    def run(self) -> str:
        r = self.build_report()
        ds_md = self._report_section(r.use_case, r.datasets, "dataset/relevance_scores.json")
        api_md = self._report_section("APIs — " + r.use_case, r.apis, "api/relevance_scores.json")
        combined = self.to_markdown()

        (DATASET_DIR / "ranking_report.md").write_text(ds_md, encoding="utf-8")
        (API_DIR / "ranking_report.md").write_text(api_md, encoding="utf-8")
        (ROOT / "ranking_report.md").write_text(combined, encoding="utf-8")
        (ROOT / "ranking_report.json").write_text(self.to_json(), encoding="utf-8")

        return (
            combined
            + f"\n\n-> {DATASET_DIR / 'ranking_report.md'}"
            + f"\n-> {API_DIR / 'ranking_report.md'}"
            + f"\n-> {ROOT / 'ranking_report.md'}"
        )
