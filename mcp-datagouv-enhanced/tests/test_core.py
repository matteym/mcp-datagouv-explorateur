import json

import pytest

from script.analyze import RelevanceAnalyzer
from script.env import Env, Mcp
from script.rank import CatalogEntry


def test_env_load_reads_terms_and_strips_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'SEARCH_TERMS="sport|equipements"\nUSE_CASE=cartographie sportive\n',
        encoding="utf-8",
    )

    config = Env.load(env_file)

    assert config.search_terms == ("sport", "equipements")
    assert config.use_case == "cartographie sportive"
    assert config.mcp_url == "https://mcp.data.gouv.fr/mcp"


def test_mcp_text_extracts_sse_text_and_errors():
    payload = {"result": {"content": [{"type": "text", "text": "resultat"}]}}
    raw = f"event: message\ndata: {json.dumps(payload)}\n\n"

    assert Mcp._text(raw) == "resultat"

    error = {"error": {"code": -1, "message": "echec"}}
    with pytest.raises(RuntimeError, match="echec"):
        Mcp._text(f"data: {json.dumps(error)}")


def test_relevance_prioritizes_requested_zone_and_national_scope():
    config = Env(
        search_terms=("sport",),
        use_case="application de cartographie sportive",
        mcp_url="https://example.test/mcp",
    )
    analyzer = RelevanceAnalyzer(config, "sport en Bretagne")
    national = CatalogEntry(
        kind="dataset",
        id="national",
        title="Equipements sportifs en France",
        organization="Etat",
        url="",
        tags="sport france",
        description="",
        visits=0,
        downloads=0,
        file_kind="other",
        source_file="",
    )
    regional = CatalogEntry(
        kind="dataset",
        id="regional",
        title="Equipements sportifs en Bretagne",
        organization="Region Bretagne",
        url="",
        tags="sport bretagne",
        description="",
        visits=0,
        downloads=0,
        file_kind="other",
        source_file="",
    )

    national_score, _ = analyzer.score(national)
    regional_score, _ = analyzer.score(regional)

    assert national_score > regional_score
    assert regional_score > 0
