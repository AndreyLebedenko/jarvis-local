import pytest

from examples.mcp.ddgs_get_mcp import (
    DDGS_TEXT_BACKENDS,
    configure_duckduckgo_get,
    run_ddgs_mcp,
)


def _engine(search_method="POST"):
    return type("Engine", (), {"search_method": search_method})


def _engines(duckduckgo=None):
    registry = {name: _engine("GET") for name in DDGS_TEXT_BACKENDS}
    registry["duckduckgo"] = duckduckgo or _engine()
    return {"text": registry}


def test_configure_duckduckgo_get_changes_the_known_post_contract():
    engine = _engine()

    configure_duckduckgo_get(_engines(engine))

    assert engine.search_method == "GET"


def test_configure_duckduckgo_get_accepts_an_upstream_get_fix():
    engine = _engine("GET")

    configure_duckduckgo_get(_engines(engine))

    assert engine.search_method == "GET"


def test_configure_duckduckgo_get_rejects_a_missing_reviewed_backend():
    engines = {"text": {"duckduckgo": _engine()}}

    with pytest.raises(
        RuntimeError,
        match=(
            "DDGS text backends are unavailable: "
            "brave, mojeek, wikipedia, yahoo, yandex"
        ),
    ):
        configure_duckduckgo_get(engines)


@pytest.mark.parametrize(
    ("engines", "message"),
    [
        ({}, "DDGS text backend 'duckduckgo' is unavailable"),
        (
            _engines(object()),
            "DDGS DuckDuckGo search method None is unsupported",
        ),
    ],
)
def test_configure_duckduckgo_get_rejects_an_unknown_upstream_contract(
    engines, message
):
    with pytest.raises(RuntimeError, match=message):
        configure_duckduckgo_get(engines)


@pytest.mark.asyncio
async def test_run_ddgs_mcp_configures_get_before_starting_stdio():
    engine = _engine()
    observed_methods = []

    async def run_stdio():
        observed_methods.append(engine.search_method)

    await run_ddgs_mcp(_engines(engine), run_stdio)

    assert observed_methods == ["GET"]
