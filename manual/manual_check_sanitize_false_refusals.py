#!/usr/bin/env python3
"""Human-run measurement of task v2.1.0-10e: how often the local sanitize model
refuses or breaks a harmless request, with the one retry on and off.

  python -m manual.manual_check_sanitize_false_refusals run [--config PATH]
      [--repeats N] [--no-topics] [--no-public-names] [--only H01,H02] [--out DIR]

Needs the live local Ollama endpoint, so the human runs it. The steps are in
manual/sanitize-false-refusals-handoff.md. It calls the production sanitize
stage on the production backend with the production settings; the retry is a
parameter of the stage function, never a setting. The report holds identifiers
and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from jarvis.core.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from jarvis.personal_proxy.check.check_backend import ChatRequest
from jarvis.personal_proxy.check.ollama_check_backend import OllamaCheckBackend
from jarvis.personal_proxy.common.visible_text import has_visible_text
from jarvis.personal_proxy.request.typed_transcript import typed_checked_transcript
from jarvis.personal_proxy.sanitize.sanitize import (
    SANITIZE_RETRIES,
    sanitize_with_retries,
)
from jarvis.personal_proxy.startup.proxy_assembly import local_check_client
from jarvis.personal_proxy.startup.startup_checks import read_public_names, read_topics
from manual.personal_proxy.false_refusals import (
    ARM_OFF,
    ARM_ON,
    CORPUS,
    Item,
    Trial,
    outcome_label,
    render_report,
)

DEFAULT_REPEATS = 2
DEFAULT_OUT = Path("manual_check_sanitize_false_refusals_out")
REPORT_NAME = "report.md"
ARM_RETRIES = {ARM_ON: SANITIZE_RETRIES, ARM_OFF: 0}


class CountingBackend:
    def __init__(self, inner: OllamaCheckBackend) -> None:
        self._inner = inner
        self.calls = 0

    async def complete(self, request: ChatRequest) -> str:
        self.calls += 1
        return await self._inner.complete(request)


async def measure(
    settings: Settings,
    topics: str,
    public_names: str,
    items: Sequence[Item],
    repeats: int,
) -> list[Trial]:
    proxy = settings.personal_proxy
    client = local_check_client(settings.backend)
    trials = []
    try:
        for repeat in range(repeats):
            for item in items:
                for arm, retries in ARM_RETRIES.items():
                    backend = CountingBackend(
                        OllamaCheckBackend(settings.backend, proxy, client)
                    )
                    result = await sanitize_with_retries(
                        typed_checked_transcript(item.text),
                        topics,
                        backend,
                        proxy,
                        retries,
                        public_names,
                    )
                    outcome = outcome_label(result)
                    trials.append(Trial(item.item_id, arm, backend.calls, outcome))
                    print(f"repeat {repeat + 1} {item.item_id} {arm}: {outcome}")
    finally:
        await client.aclose()
    return trials


def selected_items(only: str | None) -> list[Item]:
    if not only:
        return list(CORPUS)
    wanted = {part.strip() for part in only.split(",") if part.strip()}
    chosen = [item for item in CORPUS if item.item_id in wanted]
    unknown = wanted - {item.item_id for item in chosen}
    if unknown:
        raise SystemExit(f"unknown ids: {', '.join(sorted(unknown))}")
    return chosen


def command_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    topics = "" if args.no_topics else read_topics(settings.personal_proxy)
    public_names = (
        "" if args.no_public_names else read_public_names(settings.personal_proxy)
    )
    items = selected_items(args.only)
    trials = asyncio.run(measure(settings, topics, public_names, items, args.repeats))
    report = render_report(trials, topics_present=has_visible_text(topics))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print()
    print(report)
    return 0


def command_show(args: argparse.Namespace) -> int:
    for item in selected_items(args.only):
        print(f"{item.item_id}: {item.text}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="call the live local model")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    run.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    run.add_argument("--no-topics", action="store_true")
    run.add_argument("--no-public-names", action="store_true")
    run.add_argument("--only", default=None)
    run.add_argument("--out", type=Path, default=DEFAULT_OUT)
    run.set_defaults(handler=command_run)
    show = commands.add_parser("show", help="print request texts by id, no model call")
    show.add_argument("--only", required=True)
    show.set_defaults(handler=command_show)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
