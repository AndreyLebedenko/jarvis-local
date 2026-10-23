"""A chat block as the JSON object the Status Console draws.

The payload holds the personal text the block holds, for the local window only:
it is never logged and never stored. A notice is rendered here from the fixed
texts of the service, so the page keeps no copy of them."""

from __future__ import annotations

from typing import cast

from jarvis.personal_proxy.check_result import Doubt
from jarvis.personal_proxy.confirmation_blocks import HeardBlock, SentBlock
from jarvis.personal_proxy.findings import Finding
from jarvis.personal_proxy.sent_view import has_default_system_prompt
from jarvis.personal_proxy.service_blocks import (
    AnswerBlock,
    DryRunBlock,
    NoticeBlock,
    ServiceBlock,
)
from jarvis.personal_proxy.service_texts import notice_text

JsonObject = dict[str, object]


def block_payload(block: ServiceBlock, language: str | None) -> JsonObject:
    if isinstance(block, NoticeBlock):
        return {
            "type": "notice",
            "kind": block.kind.value,
            "text": notice_text(block, language),
        }
    if isinstance(block, HeardBlock):
        return {
            "type": "heard",
            "text": block.heard_text,
            "doubts": [_doubt(doubt) for doubt in block.doubts],
            "decision": block.decision.value,
        }
    if isinstance(block, SentBlock):
        return {
            "type": "sent",
            "messages": _messages(block.messages),
            "system_is_default": has_default_system_prompt(block.messages),
            "forced": block.forced,
        }
    if isinstance(block, AnswerBlock):
        return {
            "type": "answer",
            "text": block.text,
            "method": block.method.value,
            "unresolved": block.unresolved_placeholders,
        }
    if isinstance(block, DryRunBlock):
        return _dry_run(block)
    raise TypeError("not a chat block of the personal proxy")


def _doubt(doubt: Doubt) -> JsonObject:
    return {"kind": doubt.kind.value, "fragment": doubt.fragment}


def _messages(messages: tuple[tuple[str, str], ...]) -> list[JsonObject]:
    return [{"role": role, "content": content} for role, content in messages]


def _finding(finding: Finding) -> JsonObject:
    return {
        "category": finding.category.value,
        "message_index": finding.message_index,
        "start": finding.start,
        "end": finding.end,
        "stage": finding.stage.value if finding.stage is not None else None,
    }


def _dry_run(block: DryRunBlock) -> JsonObject:
    return {
        "type": "dry_run",
        "whisper_text": block.whisper_text,
        "checked_text": block.checked_text,
        "doubts": [_doubt(doubt) for doubt in block.doubts],
        "would_ask": block.would_ask,
        "sanitized_text": block.sanitized_text,
        "mapping": cast(JsonObject, dict(block.mapping)),
        "verdict": block.verdict.value,
        "reason": block.reason,
        "gate_findings": [_finding(finding) for finding in block.gate_findings],
        "messages": _messages(block.messages),
        "forced": block.forced,
    }
