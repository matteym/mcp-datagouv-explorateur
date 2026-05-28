#!/usr/bin/env python3
"""Serveur MCP Cursor — collecte + analyse (scores dans dataset/ et api/)."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from mcp.server.fastmcp import FastMCP

from script.analyze import RelevanceAnalyzer
from script.fetch import Fetch
from script.setup import Setup

mcp = FastMCP(
    "datagouv-enhanced",
    instructions=(
        "Pipeline data.gouv.fr :\n"
        "1) datagouv_fetch — collecte selon SEARCH_TERMS (.env à la racine du projet).\n"
        "2) datagouv_analyze — scoring + top 10.\n"
        "Si l'utilisateur précise une zone géographique, passez sa demande dans user_request "
        "(ex. « sport en priorité IDF »). Sans user_request : France entière > région, sans pénalité."
    ),
)


def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        out = fn(*args, **kwargs)
    text = buf.getvalue()
    if isinstance(out, str) and out.strip():
        if text and not text.endswith("\n"):
            text += "\n"
        return text + out
    return text.strip() or "(terminé)"


@mcp.tool()
def datagouv_setup() -> str:
    """Teste la connexion MCP data.gouv.fr (initialize + recherches exemple)."""
    return _capture(Setup().run)


@mcp.tool()
def datagouv_fetch() -> str:
    """Collecte datasets et APIs selon SEARCH_TERMS (.env) dans dataset/ et api/."""
    return _capture(Fetch().run)


@mcp.tool()
def datagouv_fetch_datasets() -> str:
    """Collecte uniquement les datasets dans dataset/."""
    return _capture(Fetch().get_datasets)


@mcp.tool()
def datagouv_fetch_api() -> str:
    """Collecte uniquement les APIs dans api/."""
    return _capture(Fetch().get_api)


@mcp.tool()
def datagouv_analyze(user_request: str = "") -> str:
    """
    Analyse les résultats : relevance_scores.json (dataset/ + api/) + top 10.
    user_request est la seule entrée runtime (zone/priorité/contrainte éventuelle).
    """
    return RelevanceAnalyzer(user_request=user_request).run()


if __name__ == "__main__":
    mcp.run(transport="stdio")
