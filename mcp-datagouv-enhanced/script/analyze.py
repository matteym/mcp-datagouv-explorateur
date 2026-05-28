#!/usr/bin/env python3
"""Analyse pertinence (SEARCH_TERMS + USE_CASE) — scores dans dataset/ et api/."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from script.env import Env, ROOT
from script.rank import CatalogEntry, ResultRanker

DATASET_DIR = ROOT / "dataset"
API_DIR = ROOT / "api"
SCORES_DATASET = DATASET_DIR / "relevance_scores.json"
SCORES_API = API_DIR / "relevance_scores.json"

_TOKEN = re.compile(r"[a-z0-9àâäéèêëïîôùûüç]{3,}", re.I)
_STOP = frozenset({
    "application", "donnees", "données", "pour", "avec", "dans", "des", "les",
    "une", "par", "sur", "temps", "reel", "réel", "depuis", "data", "open", "api",
    "uniquement", "seulement", "exclure", "penaliser", "pénaliser", "zone", "zones",
})
_ADMIN_API = re.compile(
    r"bouquet\s+api\s+entreprise|sirene|cotisation|certificat|qualiopi|rcs\b|tva\b|"
    r"eori|subvention|association|bilan\s+annuel|mandataires?\s+sociaux|liasses?\s+fiscales|"
    r"attestation\s+(fiscale|de\s+vigilance)|immatriculation\s+eori",
    re.I,
)

# Périmètre géographique (boost par défaut : France > région > local)
_NATIONAL = frozenset({
    "france", "national", "nationale", "metropole", "metropolitain", "interregional",
    "territoires", "hexagone", "ministeres", "ministere", "republique",
})
_REGIONAL = frozenset({
    "ile", "paris", "idf", "francilien", "francilienne", "region", "regional",
    "yvelines", "seine", "marne", "essonne", "oise", "val", "hauts",
    "bretagne", "normandie", "provence", "occitanie", "aquitaine", "corse", "alsace",
    "lorraine", "champagne", "bourgogne", "rennes", "marseille", "lyon", "lille",
    "bordeaux", "toulouse", "nantes", "strasbourg", "montpellier", "dijon", "tours",
})
# Départements / commune hors grande région (niveau le plus fin)
_LOCAL = frozenset({
    "departement", "departementale", "commune", "communal", "arrondissement",
    "centre", "loire", "poitou", "limousin", "auvergne", "guadeloupe", "martinique",
    "reunion", "mayotte", "guyane", "poitiers", "loir", "cher", "niort", "angers",
})
# Zones nommées détectables dans user_request / geo_filter (plusieurs zones = OU)
_ZONE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("idf", ("ile-de-france", "ile de france", "idf", "paris", "francilien")),
    ("bretagne", ("bretagne", "breton", "rennes")),
    ("normandie", ("normandie", "caen", "rouen")),
    ("provence", ("provence", "paca", "marseille")),
    ("occitanie", ("occitanie", "toulouse", "montpellier")),
    ("aquitaine", ("aquitaine", "bordeaux")),
    ("grand_est", ("alsace", "lorraine", "champagne", "strasbourg")),
]
_GEO_INTENT_MARKERS = (
    "bretagne", "idf", "ile-de-france", "ile de france", "normandie", "provence",
    "occitanie", "aquitaine", "uniquement", "seulement", "exclure", "penal", "region",
    "regions", "zone", "zones", " ou ",
)


def _normalize(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _tokens(text: str, *, min_len: int = 3) -> set[str]:
    raw = {_normalize(m.group()) for m in _TOKEN.finditer(text)}
    return {t for t in raw if len(t) >= min_len and t not in _STOP}


class RelevanceAnalyzer:
    """
    Pertinence 0–1 depuis SEARCH_TERMS + USE_CASE.
    Géo : France entière toujours au-dessus des régions dans le score de pertinence.
    Filtre par zone (user_request) : pénalise hors-zone ; les régions demandées restent sous le national.
    """

    def __init__(
        self,
        cfg: Env | None = None,
        user_request: str = "",
    ) -> None:
        self.cfg = cfg or Env.load()
        if not self.cfg.use_case:
            raise ValueError("USE_CASE manquant dans .env")
        if not self.cfg.search_terms:
            raise ValueError("SEARCH_TERMS manquant dans .env")
        self.user_request = user_request.strip()
        # Source de vérité runtime unique: user_request
        self._apply_geo_penalties = self._detect_geo_intent(self.user_request)
        self._allowed_zones = self._parse_allowed_zones(self.user_request)
        self._filter_tokens = _tokens(self.user_request, min_len=2) if self._apply_geo_penalties else set()
        self._search_terms = list(self.cfg.search_terms)
        self._search_tokens: set[str] = set()
        for term in self._search_terms:
            self._search_tokens |= _tokens(term, min_len=2)
            self._search_tokens.add(_normalize(term.strip()))
        self._use_case_tokens = _tokens(self.cfg.use_case)
        self._context_tokens = self._search_tokens | self._use_case_tokens

    def _overlap_ratio(self, entry_tokens: set[str], query_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        return len(entry_tokens & query_tokens) / len(query_tokens)

    def _matched_search_phrases(self, text_norm: str) -> list[str]:
        return [t for t in self._search_terms if _normalize(t) in text_norm]

    @staticmethod
    def _detect_geo_intent(text: str) -> bool:
        if not text.strip():
            return False
        norm = _normalize(text)
        return any(marker in norm for marker in _GEO_INTENT_MARKERS)

    @staticmethod
    def _parse_allowed_zones(text: str) -> frozenset[str]:
        norm = _normalize(text)
        found = {zone for zone, hints in _ZONE_HINTS if any(h in norm for h in hints)}
        return frozenset(found)

    def _entry_zone_tags(self, entry_tokens: set[str], text_norm: str) -> set[str]:
        tags: set[str] = set()
        norm = text_norm
        for zone, hints in _ZONE_HINTS:
            if any(h in norm for h in hints) or any(_normalize(h) in entry_tokens for h in hints):
                tags.add(zone)
        if entry_tokens & _REGIONAL and "idf" not in tags:
            if "ile-de-france" in norm or "ile de france" in norm:
                tags.add("idf")
            elif entry_tokens & {"yvelines", "seine", "marne", "essonne", "oise", "val", "hauts", "paris"}:
                tags.add("idf")
        if entry_tokens & {"bretagne", "rennes"}:
            tags.add("bretagne")
        return tags

    @staticmethod
    def _scope_level(entry_tokens: set[str], text_norm: str) -> int:
        """
        3 = France / national (meilleur par défaut)
        2 = régional
        1 = local / département / autre région nommée
        """
        regional = entry_tokens & _REGIONAL
        local = entry_tokens & _LOCAL
        national = entry_tokens & _NATIONAL
        if "france" in text_norm and not regional and not local:
            return 3
        if national and not regional and not local:
            return 3
        if regional:
            return 2
        if local:
            return 1
        return 3

    def _is_national_scope(self, entry_tokens: set[str], text_norm: str) -> bool:
        return self._scope_level(entry_tokens, text_norm) >= 3

    def _apply_scope_weighting(self, rel: float, text_norm: str) -> tuple[float, str]:
        """
        Hiérarchie toujours active : France entière > région (même si l'utilisateur cible une zone).
        """
        entry_t = _tokens(text_norm)
        entry_zones = self._entry_zone_tags(entry_t, text_norm)
        allowed = set(self._allowed_zones)
        national = self._is_national_scope(entry_t, text_norm)
        in_requested = bool(allowed and entry_zones & allowed)

        if allowed:
            if entry_zones - allowed:
                other = ", ".join(sorted(entry_zones - allowed))
                return max(0.0, rel * 0.5), f"hors zones demandées ({other})"
            if not national and not in_requested and entry_t & _LOCAL:
                return max(0.0, rel * 0.55), "département hors zones demandées"

        if national:
            return min(1.0, rel + 0.12), "France entière (prioritaire sur toute région)"

        if in_requested:
            names = ", ".join(sorted(entry_zones & allowed))
            return min(0.88, rel + 0.05), f"région demandée ({names}), pondéré sous France"

        if self._scope_level(entry_t, text_norm) == 2:
            return min(0.92, rel + 0.04), "périmètre régional (sous France nationale)"

        if entry_t & _LOCAL:
            return rel, "périmètre local"
        return min(1.0, rel + 0.08), "couverture large (équivalent national)"

    @staticmethod
    def _is_admin_api(entry: CatalogEntry) -> bool:
        blob = f"{entry.title} {entry.tags} {entry.description}"
        return entry.kind == "api" and bool(_ADMIN_API.search(blob))

    def score(self, entry: CatalogEntry) -> tuple[float, str]:
        blob = f"{entry.title} {entry.tags} {entry.description}"
        text_norm = _normalize(blob)
        entry_tokens = _tokens(blob)
        phrases = self._matched_search_phrases(text_norm)
        search_ratio = self._overlap_ratio(entry_tokens, self._search_tokens)
        uc_ratio = self._overlap_ratio(entry_tokens, self._use_case_tokens)
        ctx_ratio = self._overlap_ratio(entry_tokens, self._context_tokens)
        notes: list[str] = []

        if self._is_admin_api(entry):
            rel, reason = 0.05, "API administrative sans lien avec la recherche"
        elif phrases:
            rel = min(1.0, 0.9 + uc_ratio * 0.08)
            reason = f"Correspond au terme « {phrases[0]} »"
            if len(phrases) > 1:
                reason += f" (+ {len(phrases) - 1} autre(s))"
        elif search_ratio >= 0.45:
            rel = min(1.0, 0.82 + uc_ratio * 0.1)
            reason = f"Fort lien avec {', '.join(self._search_terms)}"
        elif search_ratio >= 0.2 or (search_ratio > 0 and uc_ratio >= 0.25):
            rel = min(1.0, 0.62 + search_ratio * 0.2 + uc_ratio * 0.12)
            reason = "Aligné recherche et cas d'usage"
        elif uc_ratio >= 0.3:
            rel = min(1.0, 0.55 + uc_ratio * 0.25)
            reason = "Aligné avec le cas d'usage"
        elif ctx_ratio >= 0.15:
            rel = min(1.0, 0.28 + ctx_ratio * 0.35)
            reason = "Lien partiel avec le contexte"
        elif search_ratio > 0:
            rel = min(1.0, 0.22 + search_ratio * 0.25)
            reason = "Faible lien avec le terme de recherche"
        else:
            rel = 0.08
            reason = "Hors sujet (recherche et cas d'usage)"

        rel, scope_note = self._apply_scope_weighting(rel, text_norm)
        notes.append(scope_note)

        if entry.kind == "api" and rel > 0.15 and search_ratio < 0.1 and not phrases:
            rel = min(rel, 0.35)
            notes.append("API peu liée au terme")

        if notes:
            reason += f" ({'; '.join(notes)})"
        return round(max(0.0, min(1.0, rel)), 3), reason

    def scores_for_entries(self, entries: list[CatalogEntry]) -> list[dict]:
        return [
            {
                "id": e.id,
                "title": e.title,
                "relevance": rel,
                "reason": reason,
            }
            for e in entries
            for rel, reason in [self.score(e)]
        ]

    def _write_scores(self, path: Path, kind: str, scores: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "search_terms": list(self._search_terms),
                    "use_case": self.cfg.use_case,
                    "user_request": self.user_request or None,
                    "allowed_zones": sorted(self._allowed_zones) if self._allowed_zones else None,
                    "geo_mode": (
                        f"zones={','.join(sorted(self._allowed_zones))}"
                        if self._allowed_zones
                        else (
                            "penalites_sans_zone_precise"
                            if self._apply_geo_penalties
                            else "defaut_france_gt_region_gt_local"
                        )
                    ),
                    "kind": kind,
                    "scores": scores,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def generate_scores(self, ranker: ResultRanker) -> tuple[int, int]:
        ds = ranker.load_by_kind("dataset")
        api = ranker.load_by_kind("api", datasets_for_proxy=ds)
        ds_scores = self.scores_for_entries(ds)
        api_scores = self.scores_for_entries(api)
        self._write_scores(SCORES_DATASET, "dataset", ds_scores)
        self._write_scores(SCORES_API, "api", api_scores)
        return len(ds_scores), len(api_scores)

    def run(self) -> str:
        ranker = ResultRanker(self.cfg)
        n_ds, n_api = self.generate_scores(ranker)
        report = ranker.run()
        terms = ", ".join(self._search_terms)
        if self._allowed_zones:
            geo_line = f"Zones demandées : {', '.join(sorted(self._allowed_zones))} (OU)\n"
        elif self._apply_geo_penalties:
            geo_line = f"Filtre géo actif : {self.user_request}\n"
        else:
            geo_line = "Géo : défaut (France > région > local, sans pénalité)\n"
        return (
            f"Analyse terminée — recherche: {terms}\n"
            f"USE_CASE: {self.cfg.use_case}\n"
            f"{geo_line}"
            f"  dataset/relevance_scores.json ({n_ds} entrées)\n"
            f"  api/relevance_scores.json ({n_api} entrées)\n\n"
            f"{report}"
        )
