import json

from manual.manual_check_generation_profiles import (
    ExchangeSummary,
    summarize_exchanges,
)


def _exchange(timestamp: str, think: object, options: dict, content: str) -> str:
    return json.dumps(
        {
            "kind": "exchange",
            "timestamp": timestamp,
            "request": {
                "think": think,
                "options": options,
                "messages": [{"role": "system", "content": content}],
            },
            "response": {},
        },
        ensure_ascii=False,
    )


def test_summarizes_only_exchanges_at_or_after_since():
    lines = [
        _exchange("2026-09-26T20:59:59", False, {"num_ctx": 1}, "old run"),
        json.dumps({"kind": "utterance", "timestamp": "2026-09-26T21:00:01"}),
        "",
        _exchange("2026-09-26T21:00:00", "medium", {"temperature": 0.6}, "new"),
    ]

    assert summarize_exchanges(lines, "2026-09-26T21:00:00") == [
        ExchangeSummary(
            timestamp="2026-09-26T21:00:00",
            think="medium",
            options={"temperature": 0.6},
            first_message="system: new",
        )
    ]


def test_first_message_preview_is_single_line_and_bounded():
    lines = [_exchange("2026-09-26T21:00:00", False, {}, "line one\nline two " * 20)]

    [summary] = summarize_exchanges(lines, "2026-09-26T21:00:00")

    assert "\n" not in summary.first_message
    assert len(summary.first_message) == 60
