"""Tells the Status Console why the last request was stopped.

A tee over the chat sink: the block goes to the real sink first, then a notice
that says the request was stopped before anything was sent becomes the "last
block reason". It holds the kind and the position of the finding, never a
value, and the next request that goes out (or reaches the dry-run stop) clears
it. It never raises into the service."""

from __future__ import annotations

import logging
from typing import Protocol

from jarvis.personal_proxy.confirmation.confirmation_blocks import SentBlock
from jarvis.personal_proxy.reporting.block_payload import JsonObject
from jarvis.personal_proxy.reporting.notice_class import BLOCKING_KINDS, notice_class
from jarvis.personal_proxy.reporting.service_blocks import (
    DryRunBlock,
    NoticeBlock,
    ServiceBlock,
)
from jarvis.personal_proxy.reporting.service_ports import ProxyChatSink


class ProxyStatusPublisher(Protocol):
    def set_proxy_last_block(self, reason: JsonObject | None) -> object: ...


class ProxyStatusSink:
    def __init__(
        self,
        inner: ProxyChatSink,
        publisher: ProxyStatusPublisher,
        logger: logging.Logger | None = None,
    ) -> None:
        self._inner = inner
        self._publisher = publisher
        self._logger = logger or logging.getLogger(__name__)

    async def post(self, block: ServiceBlock) -> None:
        await self._inner.post(block)
        try:
            self._track(block)
        except Exception as error:
            self._logger.warning("Status update failed: %s", type(error).__name__)

    def _track(self, block: ServiceBlock) -> None:
        if isinstance(block, NoticeBlock) and block.kind in BLOCKING_KINDS:
            self._publisher.set_proxy_last_block(dict(notice_class(block)))
        elif isinstance(block, SentBlock | DryRunBlock):
            self._publisher.set_proxy_last_block(None)
