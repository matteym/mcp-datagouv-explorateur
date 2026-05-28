#!/usr/bin/env python3
"""Boucle SEARCH_TERMS × pages — dataset/ + api/."""

import re
import sys
import time

from script.env import Env, Mcp, ROOT
from script.metrics import DatasetMetricsIndex, MetricRow

_ENTRY_ID = re.compile(r"^\s+ID:\s+(\S+)", re.M)
_ENTRY_TITLE = re.compile(r"^\d+\.\s+(.+)$", re.M)
_ENTRY_ORG = re.compile(r"^\s+Organization:\s*(.*)$", re.M)
_ENTRY_TAGS = re.compile(r"^\s+Tags:\s*(.*)$", re.M)
_METRICS_TOTAL = re.compile(r"Total\s+([\d,]+)\s+([\d,]+)", re.I)
_PAGE_PREFIX = re.compile(r"(?s)^((?:Found\b|Page\b).+?\n\n)")
_GEO = re.compile(r"geojson|geopackage|gpkg|kml|géolocalisation|geolocalisation|coordinates", re.I)
_JSON = re.compile(r"\bjson\b|application/json", re.I)


class MetricsEnricher:
    def __init__(self, mcp: Mcp) -> None:
        self.mcp = mcp
        self._cache: dict[str, tuple[int, int, str]] = {}
        self._dataset_index = DatasetMetricsIndex()

    def totals(self, item_id: str, req_tag: str) -> tuple[int, int, str]:
        if item_id in self._cache:
            return self._cache[item_id]
        raw = self.mcp.tool("get_metrics", {"dataset_id": item_id, "limit": 12}, req_tag)
        m = _METRICS_TOTAL.search(raw)
        visits = downloads = 0
        if m:
            visits = int(m.group(1).replace(",", ""))
            downloads = int(m.group(2).replace(",", ""))
        self._cache[item_id] = (visits, downloads, raw)
        time.sleep(1)
        return visits, downloads, raw

    @staticmethod
    def _parse_block_fields(part: str) -> tuple[str, str, str]:
        title = (_ENTRY_TITLE.search(part) or [None, ""])[1].strip()
        org = (_ENTRY_ORG.search(part) or [None, ""])[1].strip()
        tags = (_ENTRY_TAGS.search(part) or [None, ""])[1].strip()
        return title, org, tags

    def enrich(self, text: str, req_prefix: str, *, kind: str = "dataset") -> str:
        m = _PAGE_PREFIX.match(text)
        if not m:
            return text
        prefix, body = m.group(1), text[len(m.group(1)) :]
        rows: list[dict] = []
        for part in re.split(r"(?m)(?=^\d+\.\s)", body):
            part = part.strip()
            if not part or not re.match(r"^\d+\.\s", part):
                continue
            if not (mid := _ENTRY_ID.search(part)):
                continue
            item_id = mid.group(1)
            title, org, tags = self._parse_block_fields(part)
            if kind == "dataset":
                visits, downloads, metrics_raw = self.totals(item_id, f"{req_prefix}-m-{item_id[:8]}")
                self._dataset_index.add(
                    MetricRow(item_id, title, org, tags, visits, downloads)
                )
                label = "total"
            else:
                visits, downloads, label = self._dataset_index.proxy_for_api(title, org, tags)
                metrics_raw = f"(popularité estimée — {label})"
            rows.append({
                "block": part,
                "visits": visits,
                "downloads": downloads,
                "metrics": metrics_raw,
                "label": label,
            })
        rows.sort(key=lambda r: (r["downloads"], r["visits"]), reverse=True)
        out = prefix
        for i, row in enumerate(rows, 1):
            block = re.sub(r"^\d+\.", f"{i}.", row["block"], count=1)
            out += block.rstrip()
            out += (
                f"\n   Métriques popularité: {row['visits']} visites, "
                f"{row['downloads']} téléchargements ({row['label']})\n"
                f"--- Détail téléchargements / visites ---\n{row['metrics']}\n\n"
            )
        return out


class ResultStore:
    @staticmethod
    def slug(thing: str) -> str:
        return re.sub(r"\s+", "_", thing.strip()).replace("/", "_")

    @classmethod
    def save(cls, folder: str, thing: str, page: int, content: str) -> str:
        kind = "geospatial" if _GEO.search(content) else "json" if _JSON.search(content) else "other"
        dest = ROOT / folder
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"result_{cls.slug(thing)}_{kind}.txt"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n========== {thing} | page {page} ==========\n{content}\n")
        return str(path)


class Fetch:
    def __init__(self) -> None:
        self.cfg = Env.load()
        self.mcp = Mcp(self.cfg)
        self.metrics = MetricsEnricher(self.mcp)

    def _fetch(self, folder: str, tool_name: str, *, kind: str) -> None:
        pages, page_size = 20, 5
        for thing in self.cfg.search_terms:
            slug = ResultStore.slug(thing)
            for page in range(1, pages + 1):
                print(f"📥 [{folder}] {thing} p{page}/{pages}", file=sys.stderr)
                text = self.mcp.tool(
                    tool_name,
                    {"query": thing, "page": page, "page_size": page_size},
                    f"{folder}-{slug}-{page}",
                )
                text = self.metrics.enrich(text, f"{folder}-{slug}-p{page}", kind=kind)
                path = ResultStore.save(folder, thing, page, text)
                print(f"   → {path}", file=sys.stderr)
                time.sleep(1)

    def get_datasets(self) -> None:
        self._fetch("dataset", "search_datasets", kind="dataset")

    def get_api(self) -> None:
        self._fetch("api", "search_dataservices", kind="api")

    def run(self) -> None:
        if not self.cfg.search_terms:
            sys.exit("SEARCH_TERMS manquant dans .env")
        print(f"Termes: {', '.join(self.cfg.search_terms)}", file=sys.stderr)
        self.get_datasets()
        self.get_api()
        print("✅ Terminé", file=sys.stderr)


if __name__ == "__main__":
    Fetch().run()
