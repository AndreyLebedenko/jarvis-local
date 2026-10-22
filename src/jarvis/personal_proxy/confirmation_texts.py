"""The fixed Russian and English texts of the confirmation exchange. No model
call: only the heard text and the fragments are filled into a text.

English is `en`, `EN`, `en-US`, `en_GB`, `English` (case and surrounding spaces
ignored); any other language, and none, gets Russian."""

from __future__ import annotations

from jarvis.personal_proxy.check_result import Doubt, DoubtKind
from jarvis.personal_proxy.speech_tags import strip_speech_control_tags

MAX_SPOKEN_ITEMS = 3
MAX_SPOKEN_FRAGMENT_CHARS = 60

_RU = {
    "shown": (
        "Я услышал:\n{heard}\n\n{check}\n"
        "Отправить? Ответьте «да» или «нет», голосом или текстом."
    ),
    "spoken": "{check} Отправить? Скажите да или нет.",
    "check": "Проверьте: {doubts}.",
    "check_generic": "Проверьте услышанный текст.",
    "offer": (
        "Ничего не отправлено. Можно исправить текст, набрав его, "
        "или продиктовать заново."
    ),
    DoubtKind.FRAGMENT: "фрагмент",
    DoubtKind.REWRITE: "формулировка могла измениться",
    DoubtKind.CHECK_FAILED: "проверка не завершилась",
}
_EN = {
    "shown": (
        "I heard:\n{heard}\n\n{check}\n"
        'Send it? Answer "yes" or "no", by voice or by typing.'
    ),
    "spoken": "{check} Send it? Say yes or no.",
    "check": "Please check: {doubts}.",
    "check_generic": "Please check what I heard.",
    "offer": (
        "Nothing was sent. You can correct the text by typing it, or dictate it again."
    ),
    DoubtKind.FRAGMENT: "a fragment",
    DoubtKind.REWRITE: "the wording may have changed",
    DoubtKind.CHECK_FAILED: "the check did not complete",
}


def is_english(language: str | None) -> bool:
    if not isinstance(language, str):
        return False
    code = language.strip().casefold()
    return code in ("en", "english") or code.startswith(("en-", "en_"))


def _words(language: str | None) -> dict:
    return _EN if is_english(language) else _RU


def _named(doubts: tuple[Doubt, ...], words: dict) -> list[str]:
    """What each doubt is called; a blank fragment names nothing and is skipped."""
    named = []
    for doubt in doubts:
        if doubt.fragment is None:
            named.append(words[doubt.kind])
        elif doubt.fragment.strip():
            named.append(doubt.fragment)
    return named


def _check_sentence(named: list[str], words: dict) -> str:
    if not named:
        return words["check_generic"]
    return words["check"].format(doubts="; ".join(named))


def shown_question(
    language: str | None, heard_text: str, doubts: tuple[Doubt, ...]
) -> str:
    words = _words(language)
    check = _check_sentence(_named(doubts, words), words)
    return words["shown"].format(heard=heard_text, check=check)


def spoken_question(language: str | None, doubts: tuple[Doubt, ...]) -> str:
    words = _words(language)
    named = [
        strip_speech_control_tags(item)[:MAX_SPOKEN_FRAGMENT_CHARS].rstrip()
        for item in _named(doubts, words)[:MAX_SPOKEN_ITEMS]
    ]
    return words["spoken"].format(check=_check_sentence(named, words))


def offer_text(language: str | None) -> str:
    return _words(language)["offer"]
