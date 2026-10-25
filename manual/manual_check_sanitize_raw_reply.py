#!/usr/bin/env python3
"""Human-run diagnosis of one sanitize failure: prints the raw reply of the
live local model for one request text and how the production parser classifies
it.

  python -m manual.manual_check_sanitize_raw_reply "request text"
      [--config PATH] [--no-topics] [--repeats N]

Needs the live local Ollama endpoint, so the human runs it. The raw reply holds
the request text and its originals, so it is printed to the console only and is
never written to a file or to the application log.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from jarvis.core.config import DEFAULT_CONFIG_PATH, load_settings
from jarvis.personal_proxy.check.ollama_check_backend import OllamaCheckBackend
from jarvis.personal_proxy.sanitize.sanitize_parsing import parse_sanitize_output
from jarvis.personal_proxy.sanitize.sanitize_requests import build_sanitize_request
from jarvis.personal_proxy.sanitize.sanitize_result import SanitizeFailure
from jarvis.personal_proxy.startup.proxy_assembly import local_check_client
from jarvis.personal_proxy.startup.startup_checks import read_topics

DEFAULT_REPEATS = 1


async def show_replies(config: Path, text: str, no_topics: bool, repeats: int) -> None:
    settings = load_settings(config)
    proxy = settings.personal_proxy
    topics = "" if no_topics else read_topics(proxy)
    request = build_sanitize_request(text, topics, proxy.check_temperature)
    client = local_check_client(settings.backend)
    try:
        backend = OllamaCheckBackend(settings.backend, proxy, client)
        for attempt in range(1, repeats + 1):
            reply = await backend.complete(request)
            outcome = parse_sanitize_output(reply)
            label = (
                f"failure: {outcome.failure.value}"
                if isinstance(outcome, SanitizeFailure)
                else f"accepted: {outcome.verdict.value}"
            )
            print(f"--- attempt {attempt}: {label}")
            print(reply)
    finally:
        await client.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--no-topics", action="store_true")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    asyncio.run(show_replies(args.config, args.text, args.no_topics, args.repeats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
