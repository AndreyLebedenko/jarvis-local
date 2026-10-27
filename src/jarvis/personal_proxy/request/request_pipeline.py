"""One request, from the inbox item to the presented answer. Fail closed: every
step that does not clearly say "go on" ends the request with a notice, and the
payload is built, gated, and sent in this one place, as one object."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from jarvis.personal_proxy.answer.answer_presenter import AnswerPresenter
from jarvis.personal_proxy.answer.answer_reporter import Reporter
from jarvis.personal_proxy.answer.speech_preparation import speech_preparation_of
from jarvis.personal_proxy.check.check_result import CheckedTranscript
from jarvis.personal_proxy.common.findings import (
    Finding,
    GateCategory,
    GateResult,
    GateStage,
)
from jarvis.personal_proxy.common.locality import LocalityReporter
from jarvis.personal_proxy.common.payload import (
    OutboundPayload,
    build_outbound_payload,
    system_prompt_for,
)
from jarvis.personal_proxy.common.response_mode import (
    ResponseModeGetter,
    always_text,
)
from jarvis.personal_proxy.common.visible_text import has_visible_text
from jarvis.personal_proxy.confirmation.confirmation_blocks import (
    HeardDecision,
    heard_block_of,
    sent_block_of,
)
from jarvis.personal_proxy.confirmation.confirmation_outcome import ExchangeOutcome
from jarvis.personal_proxy.confirmation.confirmation_policy import should_ask
from jarvis.personal_proxy.external.external_error import error_kind_of
from jarvis.personal_proxy.external.external_scope import external_deltas
from jarvis.personal_proxy.gate.gate_context import GateContext
from jarvis.personal_proxy.reporting.service_blocks import (
    DryRunBlock,
    NoticeKind,
    RequestSourceBlock,
)
from jarvis.personal_proxy.request.pipeline_stages import PipelineStages
from jarvis.personal_proxy.request.proxy_inbox import InboxItem, TypedText, Utterance
from jarvis.personal_proxy.request.request_intake import Heard, RequestIntake
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)
from jarvis.personal_proxy.sanitize.verbatim_result import verbatim_result

Confirm = Callable[[CheckedTranscript], Awaitable[ExchangeOutcome]]

_UNKNOWN_GATE_ERROR = GateResult(
    (Finding(GateCategory.GATE_ERROR, -1, 0, 0, GateStage.UNKNOWN),)
)


@dataclass(frozen=True)
class PipelineParts:
    stages: PipelineStages
    reporter: Reporter
    presenter: AnswerPresenter
    confirm: Confirm
    locality: LocalityReporter
    topics_text: str = field(repr=False)
    dry_run: bool
    response_mode: ResponseModeGetter = always_text


class RequestPipeline:
    def __init__(self, parts: PipelineParts) -> None:
        self._parts = parts
        self._stages = parts.stages
        self._reporter = parts.reporter
        self._intake = RequestIntake(parts.stages, parts.reporter)

    async def run(self, item: InboxItem) -> None:
        response_mode = self._parts.response_mode()
        heard = await self._intake.hear(item)
        if heard is None:
            return
        sanitized = await self._sanitized_or_verbatim(
            heard, forceable=isinstance(item, TypedText)
        )
        if sanitized is None:
            return
        if not self._parts.dry_run and not await self._confirmed(
            item, heard, response_mode
        ):
            return
        payload = build_outbound_payload(
            system_prompt_for(response_mode), sanitized.sanitized_text
        )
        gate = await self._gated(payload, sanitized)
        if gate is None:
            return
        if self._parts.dry_run:
            await self._stop_at_dry_run(heard, sanitized, payload, gate)
        else:
            await self._send(
                payload, sanitized, forced=heard.forced, response_mode=response_mode
            )

    async def _sanitized_or_verbatim(
        self, heard: Heard, *, forceable: bool
    ) -> SanitizeResult | None:
        if heard.forced:
            return verbatim_result(heard.checked.text)
        return await self._sanitized(heard.checked, forceable)

    async def _sanitized(
        self, checked: CheckedTranscript, forceable: bool
    ) -> SanitizeResult | None:
        result = await self._stages.sanitize(checked)
        if isinstance(result, SanitizeResult):
            return await self._sendable(result, forceable)
        failure = result.failure if isinstance(result, SanitizeFailure) else None
        await self._reporter.notice(
            NoticeKind.SANITIZE_FAILED, failure, forceable=forceable
        )
        return None

    async def _sendable(
        self, result: SanitizeResult, forceable: bool
    ) -> SanitizeResult | None:
        if result.verdict is SanitizeVerdict.REFUSE:
            await self._reporter.notice(
                NoticeKind.REFUSED, reason=result.reason, forceable=forceable
            )
            return None
        if result.verdict is SanitizeVerdict.SEND and has_visible_text(
            result.sanitized_text
        ):
            return result
        await self._reporter.notice(
            NoticeKind.SANITIZE_FAILED,
            SanitizeFailureClass.EMPTY_SANITIZED_TEXT,
            forceable=forceable,
        )
        return None

    async def _confirmed(
        self, item: InboxItem, heard: Heard, response_mode: str
    ) -> bool:
        checked = heard.checked
        await self._reporter.post(_request_source_of(item, heard, response_mode))
        if heard.forced or not should_ask(checked):
            heard = heard_block_of(checked, HeardDecision.SEND_WITHOUT_QUESTION)
            await self._reporter.post(heard)
            return True
        outcome = await self._parts.confirm(checked)
        if outcome.leads_to_send:
            return True
        await self._reporter.notice(NoticeKind.NOT_SENT, outcome)
        return False

    async def _gated(
        self, payload: OutboundPayload, sanitized: SanitizeResult
    ) -> GateResult | None:
        context = GateContext(sanitized.mapping, self._parts.topics_text)
        result = self._stages.gate(payload, context)
        if isinstance(result, GateResult) and result.allowed:
            return result
        findings = result.findings if isinstance(result, GateResult) else ()
        blocked = findings or _UNKNOWN_GATE_ERROR.findings
        await self._reporter.notice(NoticeKind.GATE_BLOCKED, blocked)
        return None

    async def _stop_at_dry_run(
        self,
        heard: Heard,
        sanitized: SanitizeResult,
        payload: OutboundPayload,
        gate: GateResult,
    ) -> None:
        block = DryRunBlock(
            whisper_text=heard.whisper_text,
            checked_text=heard.checked.text,
            doubts=heard.checked.doubts,
            would_ask=should_ask(heard.checked),
            sanitized_text=sanitized.sanitized_text,
            mapping=sanitized.mapping,
            verdict=sanitized.verdict,
            reason=sanitized.reason,
            gate_findings=gate.findings,
            messages=sent_block_of(payload).messages,
            forced=heard.forced,
        )
        await self._reporter.post(block)

    async def _send(
        self,
        payload: OutboundPayload,
        sanitized: SanitizeResult,
        *,
        forced: bool,
        response_mode: str,
    ) -> None:
        await self._reporter.post(sent_block_of(payload, forced=forced))
        deltas = None
        try:
            stream = self._stages.open_stream(payload)
            deltas = external_deltas(stream, self._parts.locality)
            sentences = self._stages.restore(deltas, sanitized.mapping)
            await self._parts.presenter.present(
                sentences, speech_preparation_of(response_mode)
            )
        except Exception as error:
            await self._reporter.quiet_notice(
                NoticeKind.ANSWER_INCOMPLETE, error_kind_of(error)
            )
        finally:
            if deltas is not None:
                with suppress(Exception):
                    await deltas.aclose()


def _request_source_of(
    item: InboxItem, heard: Heard, response_mode: str
) -> RequestSourceBlock:
    if isinstance(item, Utterance):
        return RequestSourceBlock(item.wav, heard.whisper_text, response_mode)
    return RequestSourceBlock(None, None, response_mode)
