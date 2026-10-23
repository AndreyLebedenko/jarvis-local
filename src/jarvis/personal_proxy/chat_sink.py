"""The chat sink of the proxy: every chat block becomes one transient
`proxy_block` delta of the Status Console transport, which drops it while the
window is Hidden. The blocks meant for persistence only are not drawn."""

from __future__ import annotations

from typing import Protocol

from jarvis.personal_proxy.block_payload import JsonObject, block_payload
from jarvis.personal_proxy.service_blocks import (
    AnswerCompleteBlock,
    RequestSourceBlock,
    ServiceBlock,
)
from jarvis.personal_proxy.service_ports import LanguageProvider


class ProxyBlockPublisher(Protocol):
    def publish_proxy_block(self, payload: JsonObject) -> None: ...


class TransportChatSink:
    def __init__(
        self, publisher: ProxyBlockPublisher, language: LanguageProvider
    ) -> None:
        self._publisher = publisher
        self._language = language

    async def post(self, block: ServiceBlock) -> None:
        if isinstance(block, RequestSourceBlock | AnswerCompleteBlock):
            return
        self._publisher.publish_proxy_block(block_payload(block, self._language()))
