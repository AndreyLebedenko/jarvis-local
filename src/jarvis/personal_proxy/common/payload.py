"""The one place an outbound chat request is built.

The inputs are a closed set: the system prompt and the sanitized request.
Nothing else (images, history, journal, memory, MCP text) has a parameter to
travel through. The payload types refuse construction outside this module, so
the builder is the only way to obtain one, and their text forms do not show the
content.
"""

from __future__ import annotations

from jarvis.personal_proxy.common.response_mode import VOICE_MODE

DEFAULT_SYSTEM_PROMPT = (
    "Answer in the language of the request. "
    "Keep placeholders such as <PERSON_1> exactly as written."
)

VOICE_SYSTEM_PROMPT = (
    DEFAULT_SYSTEM_PROMPT + " The answer will be read aloud: write plain prose "
    "without Markdown, lists, tables, headings or emphasis, and write "
    "abbreviations, units and symbols as full words."
)

_CONSTRUCTION_TOKEN = object()


def system_prompt_for(response_mode: str) -> str:
    return VOICE_SYSTEM_PROMPT if response_mode == VOICE_MODE else DEFAULT_SYSTEM_PROMPT


def _require_token(token: object, type_name: str) -> None:
    if token is not _CONSTRUCTION_TOKEN:
        raise TypeError(f"{type_name} is created only by build_outbound_payload")


class OutboundMessage:
    __slots__ = ("_content", "_role")

    def __init__(self, role: str, content: str, *, _token: object = None) -> None:
        _require_token(_token, "OutboundMessage")
        self._role = role
        self._content = content

    @property
    def role(self) -> str:
        return self._role

    @property
    def content(self) -> str:
        return self._content

    def __repr__(self) -> str:
        return f"OutboundMessage(role={self._role!r}, content=<hidden>)"


class OutboundPayload:
    __slots__ = ("_messages",)

    def __init__(
        self, messages: tuple[OutboundMessage, ...], *, _token: object = None
    ) -> None:
        _require_token(_token, "OutboundPayload")
        self._messages = tuple(messages)

    @property
    def messages(self) -> tuple[OutboundMessage, ...]:
        return self._messages

    def to_chat_messages(self) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in self._messages
        ]

    def __repr__(self) -> str:
        return f"OutboundPayload(messages={len(self._messages)}, content=<hidden>)"


def build_outbound_payload(
    system_prompt: str, sanitized_request: str
) -> OutboundPayload:
    for text in (system_prompt, sanitized_request):
        if not isinstance(text, str):
            raise TypeError("outbound payload texts must be str")
    return OutboundPayload(
        (
            OutboundMessage("system", system_prompt, _token=_CONSTRUCTION_TOKEN),
            OutboundMessage("user", sanitized_request, _token=_CONSTRUCTION_TOKEN),
        ),
        _token=_CONSTRUCTION_TOKEN,
    )
