"""Launch the reviewed DDGS backend set with DuckDuckGo forced to HTTP GET."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol


class SearchEngine(Protocol):
    search_method: str


EngineRegistry = Mapping[str, Mapping[str, SearchEngine]]
StdioRunner = Callable[[], Awaitable[None]]
DDGS_TEXT_BACKENDS = (
    "duckduckgo",
    "wikipedia",
    "brave",
    "mojeek",
    "yahoo",
    "yandex",
)
DDGS_BACKEND_ARGUMENT = ",".join(DDGS_TEXT_BACKENDS)


def configure_duckduckgo_get(engines: EngineRegistry) -> None:
    try:
        text_engines = engines["text"]
        engine = text_engines["duckduckgo"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("DDGS text backend 'duckduckgo' is unavailable") from exc

    missing = sorted(set(DDGS_TEXT_BACKENDS) - set(text_engines))
    if missing:
        raise RuntimeError(f"DDGS text backends are unavailable: {', '.join(missing)}")

    search_method = getattr(engine, "search_method", None)
    if search_method not in {"GET", "POST"}:
        raise RuntimeError(
            f"DDGS DuckDuckGo search method {search_method!r} is unsupported"
        )
    engine.search_method = "GET"


async def run_ddgs_mcp(
    engines: EngineRegistry,
    run_stdio: StdioRunner,
) -> None:
    configure_duckduckgo_get(engines)
    await run_stdio()


def main() -> None:
    from ddgs.api_server.mcp import mcp as mcp_server
    from ddgs.engines import ENGINES

    asyncio.run(run_ddgs_mcp(ENGINES, mcp_server.run_stdio_async))


if __name__ == "__main__":
    main()
