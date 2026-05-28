#!/usr/bin/env python3
"""Popularité : métriques datasets (get_metrics) + proxy pour APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass

_STOP = frozenset({
    "api", "des", "les", "une", "pour", "donnees", "données", "data", "open", "france",
})


@dataclass
class MetricRow:
    id: str
    title: str
    organization: str
    tags: str
    visits: int
    downloads: int


def _tokens(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9àâäéèêëïîôùûüç]{3,}", text.lower())
        if t not in _STOP
    }


class DatasetMetricsIndex:
    """Index des métriques datasets pour estimer la popularité des APIs."""

    def __init__(self) -> None:
        self._rows: list[MetricRow] = []

    def add(self, row: MetricRow) -> None:
        if row.visits or row.downloads:
            self._rows.append(row)

    def proxy_for_api(self, title: str, organization: str, tags: str) -> tuple[int, int, str]:
        if not self._rows:
            return 0, 0, "aucun dataset de référence"
        org_l = organization.lower().strip()
        api_t = _tokens(f"{title} {tags}")
        best_score = -1
        best: MetricRow | None = None
        for row in self._rows:
            score = 0
            if org_l and org_l in row.organization.lower():
                score += 4
            overlap = len(api_t & _tokens(f"{row.title} {row.tags}"))
            score += overlap * 2
            if score > best_score or (score == best_score and best and row.downloads > best.downloads):
                best_score = score
                best = row
        if best and best_score > 0:
            return (
                best.visits,
                best.downloads,
                f"proxy dataset « {best.title[:50]} »",
            )
        # même organisation sans tokens communs
        if org_l:
            same_org = [r for r in self._rows if org_l in r.organization.lower()]
            if same_org:
                top = max(same_org, key=lambda r: r.downloads + r.visits)
                return top.visits, top.downloads, f"proxy org « {top.title[:50]} »"
        top = max(self._rows, key=lambda r: r.downloads + r.visits)
        return (
            int(top.visits * 0.15),
            int(top.downloads * 0.15),
            "proxy marché (15% du dataset le plus consulté)",
        )
