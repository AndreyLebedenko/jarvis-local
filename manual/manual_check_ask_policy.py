#!/usr/bin/env python3
"""Offline analysis of when to ask the owner for confirmation (follow-up of spike
v2.1.0-9, tasks/done/spike-v2.1.0-10-ask-policy.md). Reads the recorded data of the
two corpora; runs nothing live.

  python -m manual.manual_check_ask_policy --v1-out DIR --v2-out DIR
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from statistics import mean

from manual.manual_check_confidence_signals import (
    DEFAULT_OUT,
    CorpusSetup,
    _load_judges,
    _load_samples,
    _signals_for,
    read_words,
    setup_for,
    word_pairs,
)
from manual.personal_proxy.address_labels import base_id
from manual.personal_proxy.ask_policy import (
    MAX_ASK_RATE,
    WRONG_FRAGMENT_KEYS,
    covers,
    differing_items,
    evaluate_candidates,
    weak_words,
)
from manual.personal_proxy.confidence import LabelRule, projection
from manual.personal_proxy.confidence_report import (
    BASE_KEY,
    SAMPLE_KEYS,
    Signals,
)

LABEL_RULE = LabelRule.ADDRESSES_ASSEMBLED
SOURCES = ("judge", "samples", "whisper", "union")


def doubts_of(out: Path, subject_id: str) -> dict[str, list[str]]:
    judges = _load_judges(out, subject_id)
    base = judges[BASE_KEY]
    samples = _load_samples(out, subject_id)
    projections = [projection(samples[k], literal_emails=True) for k in SAMPLE_KEYS]
    found = {
        "judge": list(base.fragments) if base else [],
        "samples": differing_items(projections),
        "whisper": weak_words(word_pairs(read_words(out, subject_id))),
    }
    found["union"] = [d for source in found.values() for d in source]
    return found


def load_all(
    outs: dict[str, Path],
) -> tuple[list[Signals], dict[str, dict[str, list[str]]]]:
    recordings: list[Signals] = []
    doubts: dict[str, dict[str, list[str]]] = {}
    for corpus, out in outs.items():
        scoped = argparse.Namespace(corpus=corpus, out=out, label_rule=LABEL_RULE)
        setup: CorpusSetup = setup_for(scoped)
        for utterance in setup.utterances:
            if not utterance.spans:
                continue
            signals, _ = _signals_for(utterance.utterance_id, scoped, setup)
            recordings.append(signals)
            doubts[utterance.utterance_id] = doubts_of(out, utterance.utterance_id)
    return recordings, doubts


def render(recordings: list[Signals], doubts: dict[str, dict[str, list[str]]]) -> str:
    bad = [r for r in recordings if r.bad]
    lines = [
        "# Ask policy on the recorded data",
        "",
        f"Sensitive recordings (with labeled spans): {len(recordings)}, real errors "
        f"(label `{LABEL_RULE.value}`): {len(bad)}. Ask budget: "
        f"{MAX_ASK_RATE:.0%} of requests.",
        "",
        "| rule | asked | ask rate | within budget | errors covered | missed |",
        "|---|---|---|---|---|---|",
    ]
    for r in evaluate_candidates(recordings):
        lines.append(
            f"| {r.name} | {r.asked}/{r.total} | {r.ask_rate:.2f} | "
            f"{'yes' if r.within_budget else 'no'} | {r.caught}/{r.bad} | "
            f"{', '.join(r.missed) or '-'} |"
        )
    lines += ["", "## Is the wrong fragment named in the doubts? (real errors)", ""]
    lines.append("| recording | " + " | ".join(SOURCES) + " |")
    lines.append("|---|" + "---|" * len(SOURCES))
    for r in bad:
        cells = []
        for source in SOURCES:
            items = doubts[r.subject_id][source]
            mark = "yes" if covers(items, base_id(r.subject_id)) else "no"
            cells.append(f"{mark} ({len(items)})")
        lines.append(f"| {r.subject_id} | " + " | ".join(cells) + " |")
    lines += ["", "Cells: whether a listed doubt quotes the wrong fragment, and the "]
    lines += ["number of listed items. Wrong-fragment keys:", ""]
    for key, words in WRONG_FRAGMENT_KEYS.items():
        lines.append(f"- {key}: {', '.join(words)}")
    lines += ["", "## Length of the doubt list on the recordings asked about", ""]
    for source in SOURCES:
        sizes = [
            len(doubts[r.subject_id][source])
            for r in recordings
            if doubts[r.subject_id][source]
        ]
        if sizes:
            lines.append(
                f"- {source}: non-empty on {len(sizes)} of {len(recordings)} "
                f"recordings, mean {mean(sizes):.1f} items, max {max(sizes)}"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--v2-out", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    recordings, doubts = load_all({"v1": args.v1_out, "v2": args.v2_out})
    report = render(recordings, doubts)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
