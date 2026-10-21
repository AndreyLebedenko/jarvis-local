"""The sanitize pass's model-facing text, promoted unchanged in substance from
the v2.1.0 spikes (manual/personal_proxy/prompts.py). The text is English; the
sanitized text it asks for stays in the language of the request."""

from __future__ import annotations

from typing import Any

PLACEHOLDER_TYPES = (
    "PERSON",
    "ORG",
    "PHONE",
    "EMAIL",
    "ADDRESS",
    "CARD",
    "ACCOUNT",
    "DATE",
    "AMOUNT",
    "SECRET",
    "GOV_ID",
    "OTHER",
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
RULES = _RULES_TEMPLATE.replace("{types}", ", ".join(PLACEHOLDER_TYPES))

TEXT_FORMAT = (
    "Reply with one JSON object and nothing else, with exactly these fields:\n"
    '{"verdict": "send" or "refuse", "reason": string, "sanitized_text": '
    'string, "mapping": {placeholder: original value}}'
)

TEXT_USER_PREFIX = "Transcript of the user's request:\n"

TEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["send", "refuse"]},
        "reason": {"type": "string"},
        "sanitized_text": {"type": "string"},
        "mapping": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["verdict", "reason", "sanitized_text", "mapping"],
}


def sanitize_system_prompt(topics: str) -> str:
    rules = RULES.replace("{topics}", topics.strip())
    return f"{rules}\n{TEXT_FORMAT}"


def sanitize_user_prompt(transcript: str) -> str:
    return f"{TEXT_USER_PREFIX}{transcript}"
