"""Vocabulary for the exchange of the personal proxy as the Journal keeps it.

A request that was heard and sent is stored as separate events of one session:
what was heard (role ``user``), what went out (role ``system``), the answer as
shown and spoken (role ``assistant``) and content-free notices (role
``system``). Each has its own source, so none can be taken for the user's own
turn or for an MCP canvas. This module is pure and dependency-light so the
recorder, provenance, fork and tool layers can share it without cycles."""

from __future__ import annotations

PROXY_HEARD_SOURCE = "proxy_heard"
PROXY_SENT_SOURCE = "proxy_sent"
PROXY_ANSWER_SOURCE = "proxy_answer"
PROXY_NOTICE_SOURCE = "proxy_notice"

PROXY_SOURCES = frozenset(
    {
        PROXY_HEARD_SOURCE,
        PROXY_SENT_SOURCE,
        PROXY_ANSWER_SOURCE,
        PROXY_NOTICE_SOURCE,
    }
)

ORIGIN_METADATA_KEY = "origin"
DECISION_METADATA_KEY = "decision"
DOUBT_KINDS_METADATA_KEY = "doubt_kinds"
RAW_TRANSCRIPT_METADATA_KEY = "raw_transcript"
INCOMPLETE_METADATA_KEY = "incomplete"
METHODS_METADATA_KEY = "methods"
UNRESOLVED_METADATA_KEY = "unresolved_placeholders"
NOTICE_KIND_METADATA_KEY = "notice_kind"
NOTICE_DETAIL_METADATA_KEY = "notice_detail"
FORCED_METADATA_KEY = "forced"

ORIGIN_VOICE = "voice"
ORIGIN_TYPED = "typed"
