"""The fixed Russian and English texts of the service: notices, what is spoken
about them. No model call. Only an enum value, a
category name, or a number is filled into a text; the one exception is the
refusal reason, which is appended to the shown text and never spoken.

The language rule is the one of `confirmation_texts`."""

from __future__ import annotations

from enum import Enum

from jarvis.personal_proxy.confirmation_texts import is_english, offer_text
from jarvis.personal_proxy.findings import Finding, GateCategory
from jarvis.personal_proxy.service_blocks import NoticeBlock, NoticeKind

SPOKEN_KINDS = frozenset(
    {
        NoticeKind.REFUSED,
        NoticeKind.SANITIZE_FAILED,
        NoticeKind.NOT_SENT,
        NoticeKind.GATE_BLOCKED,
        NoticeKind.ANSWER_INCOMPLETE,
        NoticeKind.INTERNAL_ERROR,
    }
)

FORCEABLE_KINDS = frozenset({NoticeKind.REFUSED, NoticeKind.SANITIZE_FAILED})

_RU = {
    "no_speech": "Нечего отправлять: речь или текст не распознаны.",
    "bad_audio": "Запись не удалось прочитать. Ничего не отправлено.",
    "refused": "Запрос отклонён, ничего не отправлено.",
    "force_hint": "Чтобы отправить как есть, начните сообщение с /force.",
    "refused.spoken": "Запрос отклонён. Ничего не отправлено.",
    "sanitize_failed": "Не удалось подготовить запрос. Ничего не отправлено.",
    "sanitize_failed.spoken": "Не удалось подготовить запрос. Ничего не отправлено.",
    "gate_blocked": "Заблокировано проверкой, ничего не отправлено: {findings}.",
    "gate_blocked.spoken": "Заблокировано, ничего не отправлено. Найдено: {findings}.",
    "answer_incomplete": "Ответ неполный: показанные предложения остаются.",
    "answer_incomplete.spoken": "Ответ неполный.",
    "speech_failed": "Озвучивание не удалось, дальше только текст.",
    "microphone_failed": "Микрофон не удалось включить обратно.",
    "internal_error": (
        "Внутренняя ошибка остановила запрос. В чате видно, что и было ли отправлено."
    ),
    "internal_error.spoken": "Внутренняя ошибка остановила запрос.",
    "busy": "Очередь запросов заполнена, запрос пропущен.",
    "interrupted": "Запрос прерван.",
    "unknown_command": (
        "Неизвестная команда, ничего не отправлено. "
        "Известная команда: /force (или /f). "
        "Чтобы отправить текст как обычный, поставьте слово перед косой чертой."
    ),
    "empty_command": "После команды нет текста, ничего не отправлено.",
    "gate_position": "сообщение {message}, символы {start}-{end}",
    "gate_stage": "этап {stage}",
    "category.email": "адрес почты",
    "category.phone": "телефон",
    "category.payment_card": "номер карты",
    "category.iban": "IBAN",
    "category.digit_run": "длинное число",
    "category.api_key": "ключ доступа",
    "category.password": "пароль",
    "category.street_address": "адрес",
    "category.mapping_original": "исходное значение",
    "category.topic_text": "текст из файла тем",
    "category.gate_error": "ошибка проверки",
}
_EN = {
    "no_speech": "Nothing to send: no speech or text was recognized.",
    "bad_audio": "The recording could not be read. Nothing was sent.",
    "refused": "The request was refused, nothing was sent.",
    "force_hint": "To send it as is, start the message with /force.",
    "refused.spoken": "The request was refused. Nothing was sent.",
    "sanitize_failed": "The request could not be prepared. Nothing was sent.",
    "sanitize_failed.spoken": "The request could not be prepared. Nothing was sent.",
    "gate_blocked": "Blocked by the check, nothing was sent: {findings}.",
    "gate_blocked.spoken": "Blocked, nothing was sent. Found: {findings}.",
    "answer_incomplete": "The answer is incomplete: the sentences shown stay.",
    "answer_incomplete.spoken": "The answer is incomplete.",
    "speech_failed": "Speech failed, text only from here.",
    "microphone_failed": "The microphone could not be turned back on.",
    "internal_error": (
        "An internal error stopped the request. "
        "See the chat for what, if anything, was sent."
    ),
    "internal_error.spoken": "An internal error stopped the request.",
    "busy": "The request queue is full, the request was skipped.",
    "interrupted": "The request was interrupted.",
    "unknown_command": (
        "Unknown command, nothing was sent. The known command is /force (or /f). "
        "To send the text as plain text, put a word before the slash."
    ),
    "empty_command": "There is no text after the command, nothing was sent.",
    "gate_position": "message {message}, characters {start}-{end}",
    "gate_stage": "stage {stage}",
    "category.email": "an e-mail address",
    "category.phone": "a phone number",
    "category.payment_card": "a card number",
    "category.iban": "an IBAN",
    "category.digit_run": "a long number",
    "category.api_key": "an access key",
    "category.password": "a password",
    "category.street_address": "an address",
    "category.mapping_original": "an original value",
    "category.topic_text": "text from the topics file",
    "category.gate_error": "a check error",
}


def _words(language: str | None) -> dict[str, str]:
    return _EN if is_english(language) else _RU


def _category(category: GateCategory, words: dict[str, str]) -> str:
    return words[f"category.{category.value}"]


def _finding_shown(finding: Finding, words: dict[str, str]) -> str:
    name = _category(finding.category, words)
    if finding.stage is not None:
        return f"{name} ({words['gate_stage'].format(stage=finding.stage.value)})"
    where = words["gate_position"].format(
        message=finding.message_index + 1, start=finding.start, end=finding.end
    )
    return f"{name} ({where})"


def _findings(block: NoticeBlock) -> tuple[Finding, ...]:
    detail = block.detail
    return detail if isinstance(detail, tuple) else ()


def _shown_gate(block: NoticeBlock, words: dict[str, str]) -> str:
    shown = "; ".join(_finding_shown(item, words) for item in _findings(block))
    return words["gate_blocked"].format(findings=shown)


def _spoken_gate(block: NoticeBlock, words: dict[str, str]) -> str:
    names = dict.fromkeys(_category(item.category, words) for item in _findings(block))
    return words["gate_blocked.spoken"].format(findings=", ".join(names))


def notice_text(block: NoticeBlock, language: str | None) -> str:
    if block.kind is NoticeKind.NOT_SENT:
        return offer_text(language)
    words = _words(language)
    if block.kind is NoticeKind.GATE_BLOCKED:
        return _shown_gate(block, words)
    return _with_force_hint(_shown_plain(block, words), block, words)


def _shown_plain(block: NoticeBlock, words: dict[str, str]) -> str:
    text = words[block.kind.value]
    if block.kind is NoticeKind.REFUSED and block.reason:
        return f"{text} {block.reason}"
    if isinstance(block.detail, Enum):
        return f"{text} ({block.detail.value})"
    return text


def _with_force_hint(text: str, block: NoticeBlock, words: dict[str, str]) -> str:
    if block.forceable and block.kind in FORCEABLE_KINDS:
        return f"{text} {words['force_hint']}"
    return text


def spoken_notice(block: NoticeBlock, language: str | None) -> str | None:
    if block.kind not in SPOKEN_KINDS:
        return None
    if block.kind is NoticeKind.NOT_SENT:
        return offer_text(language)
    words = _words(language)
    if block.kind is NoticeKind.GATE_BLOCKED:
        return _spoken_gate(block, words)
    return words[f"{block.kind.value}.spoken"]
