"""Deterministic test of whether the check rewrote the transcript instead of
correcting it. The check model has invented an address and translated a request
at every temperature tried, so this does not depend on how it is sampled.

Known limit, kept fail-safe: a legitimate Latin repair of a spoken login or name
in a very short utterance can trip alphabet_switch."""

from __future__ import annotations

import re

from jarvis.personal_proxy.check.check_result import FallbackReason

ADDRESS_MARKERS = ("собак", "sobak", "@")
CYRILLIC_SHARE_DROP = 0.5

_LETTER = re.compile(r"[A-Za-zА-яЁё]")
_CYRILLIC = re.compile(r"[А-яЁё]")


def detect_rewrite(whisper_text: str, checked_text: str) -> FallbackReason | None:
    if _invented_address(whisper_text, checked_text):
        return FallbackReason.INVENTED_ADDRESS
    if _switched_alphabet(whisper_text, checked_text):
        return FallbackReason.ALPHABET_SWITCH
    return None


def _invented_address(whisper_text: str, checked_text: str) -> bool:
    lowered = whisper_text.lower()
    markers = sum(lowered.count(marker) for marker in ADDRESS_MARKERS)
    return checked_text.count("@") > markers


def _switched_alphabet(whisper_text: str, checked_text: str) -> bool:
    before = _cyrillic_share(whisper_text)
    after = _cyrillic_share(checked_text)
    if before is None or after is None:
        return False
    return after < CYRILLIC_SHARE_DROP * before


def _cyrillic_share(text: str) -> float | None:
    """None when no letters remain to judge the alphabet by."""
    # An address is Latin however it was spoken, so it says nothing about the
    # language of the request.
    prose = " ".join(token for token in text.split() if "@" not in token)
    letters = _LETTER.findall(prose)
    if not letters:
        return None
    return len(_CYRILLIC.findall(prose)) / len(letters)
