"""Frozen prompts and output schemas of the personal-proxy spike.

Model-facing text, so English (the verbatim-transcription precedent: English
instruction wording was the only one measured to work on this model). The
sanitized text itself stays in the language of the request. Frozen after owner
review; the harness records a hash of everything here in run_meta.json.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from manual.personal_proxy_corpus import topics_text

PLACEHOLDER_TYPES = (
    "PERSON, ORG, PHONE, EMAIL, ADDRESS, CARD, ACCOUNT, DATE, AMOUNT, SECRET, "
    "GOV_ID, OTHER"
)

_RULES_TEMPLATE = (
    "You are a privacy filter that prepares a spoken request for an external "
    "assistant. Work on the user's request only. Never answer it.\n"
    "\n"
    "1. Replace every item of the kinds below with a typed placeholder <TYPE_N>, "
    "where N counts from 1 separately for each type. Types: {types}.\n"
    "   PERSON: names of people. ORG: companies, institutions, projects. "
    "ADDRESS: street, house, apartment, and any place detail narrower than a "
    "city. DATE: a date of birth or another identifying date. AMOUNT: an exact "
    "money amount belonging to the user. SECRET: passwords, codes, keys. "
    "GOV_ID: passport, tax, or other government identifiers. OTHER: any other "
    "detail that points to one specific person, such as a rare job at a named "
    "place.\n"
    "2. The same entity gets the same placeholder everywhere in one request.\n"
    "3. Keep every other word exactly as it was said, in the same language. Do "
    "not paraphrase, summarize, translate, shorten, or answer.\n"
    "4. The sanitized text must not contain any original value.\n"
    "5. mapping lists each placeholder with its original value in base form: "
    "for a person, the full name in the nominative case; for a number, the "
    "digits as spoken.\n"
    "6. If the whole request is mainly about one of the sensitive topics listed "
    'below, do not clean it up: set verdict to "refuse", name the topic in '
    "reason, and leave sanitized_text empty.\n"
    '7. If there is no intelligible speech, set verdict to "refuse", reason to '
    '"no speech", and leave the texts empty.\n'
    'Otherwise verdict is "send" and reason is empty.\n'
    "\n"
    "Sensitive topics:\n"
    "{topics}\n"
)
RULES = _RULES_TEMPLATE.replace("{types}", PLACEHOLDER_TYPES)

_REPLY_INTRO = (
    "Reply with one JSON object and nothing else, with exactly these fields:\n"
)
COMBINED_FORMAT = (
    _REPLY_INTRO
    + '{"verdict": "send" or "refuse", "reason": string, "raw_transcript": '
    'string, "sanitized_text": string, "mapping": {placeholder: original '
    "value}}\n"
    "raw_transcript is what was spoken, word for word, before any change."
)

TEXT_FORMAT = (
    _REPLY_INTRO
    + '{"verdict": "send" or "refuse", "reason": string, "sanitized_text": '
    'string, "mapping": {placeholder: original value}}'
)

COMBINED_USER_SUFFIX = "The user's spoken request is in the attached audio recording."
COMBINED_SYSTEM_USER_TURN = "Process the attached audio recording."
TEXT_USER_PREFIX = "Transcript of the user's request:\n"

_MAPPING_SCHEMA = {"type": "object", "additionalProperties": {"type": "string"}}


def _schema(*, with_raw_transcript: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "verdict": {"type": "string", "enum": ["send", "refuse"]},
        "reason": {"type": "string"},
        "sanitized_text": {"type": "string"},
        "mapping": _MAPPING_SCHEMA,
    }
    required = ["verdict", "reason", "sanitized_text", "mapping"]
    if with_raw_transcript:
        properties["raw_transcript"] = {"type": "string"}
        required.append("raw_transcript")
    return {"type": "object", "properties": properties, "required": required}


COMBINED_SCHEMA = _schema(with_raw_transcript=True)
TEXT_SCHEMA = _schema(with_raw_transcript=False)


def _rules(topics: str) -> str:
    return RULES.replace("{topics}", topics.strip())


def combined_user_messages(topics: str | None = None) -> list[dict[str, str]]:
    body = _rules(topics_text() if topics is None else topics)
    content = f"{body}\n{COMBINED_FORMAT}\n\n{COMBINED_USER_SUFFIX}"
    return [{"role": "user", "content": content}]


def combined_system_messages(topics: str | None = None) -> list[dict[str, str]]:
    body = _rules(topics_text() if topics is None else topics)
    return [
        {"role": "system", "content": f"{body}\n{COMBINED_FORMAT}"},
        {"role": "user", "content": COMBINED_SYSTEM_USER_TURN},
    ]


def sanitize_text_messages(
    transcript: str, topics: str | None = None
) -> list[dict[str, str]]:
    body = _rules(topics_text() if topics is None else topics)
    return [
        {"role": "system", "content": f"{body}\n{TEXT_FORMAT}"},
        {"role": "user", "content": f"{TEXT_USER_PREFIX}{transcript}"},
    ]


def prompts_fingerprint() -> str:
    payload = {
        "rules": RULES,
        "combined_format": COMBINED_FORMAT,
        "text_format": TEXT_FORMAT,
        "combined_user_suffix": COMBINED_USER_SUFFIX,
        "combined_system_user_turn": COMBINED_SYSTEM_USER_TURN,
        "text_user_prefix": TEXT_USER_PREFIX,
        "combined_schema": COMBINED_SCHEMA,
        "text_schema": TEXT_SCHEMA,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
