"""A notice as a content-free JSON value, for the Journal and the Status
Console. It holds the kind and the enum, int, or position detail of the notice,
and never the refusal reason, which is text of the model."""

from __future__ import annotations

from enum import Enum

from jarvis.journal.events import JSONValue
from jarvis.personal_proxy.findings import Finding
from jarvis.personal_proxy.service_blocks import NoticeBlock, NoticeDetail, NoticeKind

BLOCKING_KINDS = frozenset(
    {
        NoticeKind.REFUSED,
        NoticeKind.SANITIZE_FAILED,
        NoticeKind.NOT_SENT,
        NoticeKind.GATE_BLOCKED,
    }
)


def notice_class(block: NoticeBlock) -> dict[str, JSONValue]:
    return {"kind": block.kind.value, "detail": _detail(block.detail)}


def _detail(detail: NoticeDetail) -> JSONValue:
    if detail is None:
        return None
    if isinstance(detail, Enum):
        return str(detail.value)
    if isinstance(detail, int):
        return detail
    return [_finding(finding) for finding in detail]


def _finding(finding: Finding) -> JSONValue:
    return {
        "category": finding.category.value,
        "message_index": finding.message_index,
        "start": finding.start,
        "end": finding.end,
        "stage": finding.stage.value if finding.stage is not None else None,
    }
