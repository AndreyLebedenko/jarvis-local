import asyncio
import base64

from _support_from_test_main import (
    _FakeJournalRecorder,
    _FakeSoundCues,
    _orchestrator,
)

import jarvis.app as main_module
from jarvis.app import (
    VOICE_PLACEHOLDER_TEXT,
    ConversationHistory,
    Orchestrator,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    PromptSettings,
)
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeChanged,
    ResponseModeState,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.journal import (
    TurnOutcome,
)

# --- voice intent probe (story-v1.9.0, task 4) ------------------------------
#
# A voice turn with [prompts].voice_intent_directive configured runs a
# non-dialog probe pass over the same audio - through the backend's
# streaming iterator directly (iter_chat), never the ResponseToken-
# publishing chat(), so probe chatter cannot reach TTS or the runtime orb.
# Only the exact SWITCH_RESPONSE_MODE=<mode> marker (parsed by
# jarvis.dialog.voice_intent) routes into set_mode(source="VOICE") and
# suppresses the turn; everything else - the default (no directive),
# empty, verbose, a probe failure - fails safe to a normal request,
# byte-identical to today.


class _FakeVoiceIntentBackend:
    """iter_chat-only backend: records probe calls, replays the
    preconfigured probe reply text. chat() raises, proving the probe
    never travels the ResponseToken-publishing path."""

    def __init__(
        self, probe_reply: str | None = None, probe_error=None, probe_hang=None
    ) -> None:
        self.iter_calls: list[tuple[list[dict], list[str] | None, ReasoningLevel]] = []
        self._probe_reply = probe_reply
        self._probe_error = probe_error
        self._probe_hang = probe_hang

    async def iter_chat(
        self,
        messages,
        images_b64=None,
        reasoning_level=ReasoningLevel.OFF,
        tools=None,
    ):
        self.iter_calls.append((list(messages), images_b64, reasoning_level))
        if self._probe_error is not None:
            raise self._probe_error
        if self._probe_hang is not None:
            yield {"message": {"content": ""}, "done": False}
            await self._probe_hang.wait()
        if self._probe_reply:
            yield {"message": {"content": self._probe_reply}, "done": True}
        else:
            yield {"message": {"content": ""}, "done": True}

    async def chat(self, messages, images_b64=None, reasoning_level=ReasoningLevel.OFF):
        self.chat_recorded = list(messages)


class _ForwardingBackend:
    """Dispatches iter_chat to the voice-intent fake and records ordinary
    chat() calls - the seam that distinguishes "probe only" from "the
    request also ran" in the tests below."""

    def __init__(self, iter_backend) -> None:
        self._iter_backend = iter_backend
        self.chat_calls: list[list[dict]] = []

    async def iter_chat(self, *args, **kwargs):
        async for chunk in self._iter_backend.iter_chat(*args, **kwargs):
            yield chunk

    async def chat(self, messages, images_b64=None, reasoning_level=ReasoningLevel.OFF):
        self.chat_calls.append(list(messages))


def _voice_intent_orchestrator(
    directive: str | None, *, journal_recorder=None, bus=None
):
    prompts = PromptSettings(voice_intent_directive=directive)
    state = ResponseModeState(bus=EventBus())
    voice_backend = _FakeVoiceIntentBackend()
    forwarding = _ForwardingBackend(voice_backend)
    sound_cues = _FakeSoundCues()
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        sound_cues,
        response_mode=state,
        reasoning_prompt_settings=prompts,
        bus=bus,
        journal_recorder=journal_recorder,
    )
    orchestrator._system_prompt = "base prompt"
    return orchestrator, voice_backend, forwarding, sound_cues, state


async def test_voice_turn_with_no_directive_is_byte_identical_to_today():
    """The feature is off by default (PromptSettings.voice_intent_directive
    is None): no probe pass, one ordinary dispatch - the card's default-
    unchanged boundary."""
    prompts = PromptSettings()
    assert prompts.voice_intent_directive is None

    orchestrator, backend, _sound_cues = _orchestrator()
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert len(backend.calls) == 1
    assert backend.calls[0][0][0] == {"role": "system", "content": "base prompt"}


async def test_voice_turn_with_directive_runs_a_probe_pass_over_the_audio():
    backend = _FakeVoiceIntentBackend(probe_reply="not a marker")
    forwarding = _ForwardingBackend(backend)
    prompts = PromptSettings(voice_intent_directive="intent rules")
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=ResponseModeState(bus=EventBus()),
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    # The probe ran through iter_chat and the ordinary dispatch followed.
    assert len(backend.iter_calls) == 1
    probe_messages, probe_images, probe_reasoning = backend.iter_calls[0]
    assert probe_messages[0] == {"role": "system", "content": "intent rules"}
    # The turn's own audio rides the verified images field on the probe too.
    assert probe_images == [base64.b64encode(b"a").decode()]
    assert probe_reasoning is ReasoningLevel.OFF
    assert len(forwarding.chat_calls) == 1


async def test_recognized_marker_switches_mode_with_voice_source_and_skips_the_turn():
    bus = EventBus()
    changed: list[ResponseModeChanged] = []

    async def on_event(event: ResponseModeChanged) -> None:
        changed.append(event)

    bus.subscribe(ResponseModeChanged, on_event)
    backend = _FakeVoiceIntentBackend(probe_reply="SWITCH_RESPONSE_MODE=voice")
    forwarding = _ForwardingBackend(backend)
    journal_recorder = _FakeJournalRecorder()
    prompts = PromptSettings(voice_intent_directive="intent rules")
    state = ResponseModeState(bus=bus)
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=state,
        reasoning_prompt_settings=prompts,
        bus=bus,
        journal_recorder=journal_recorder,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert state.mode is ResponseMode.VOICE
    assert changed == [ResponseModeChanged(mode=ResponseMode.VOICE, source="VOICE")]
    # The probe only - no ordinary dispatch for a recognized command.
    assert forwarding.chat_calls == []
    # The suppressed turn's teardown: busy cleared, command journaled with
    # its own outcome (an obeyed command is neither interrupted nor failed).
    assert orchestrator.is_busy is False
    assert journal_recorder.voice_wavs == [b"a"]
    assert journal_recorder.assistant_texts == [""]
    assert journal_recorder.assistant_outcomes == [TurnOutcome.MODE_SWITCHED]


async def test_suppressed_command_history_keeps_the_mode_switch_note():
    backend = _FakeVoiceIntentBackend(probe_reply="SWITCH_RESPONSE_MODE=text_voice")
    forwarding = _ForwardingBackend(backend)
    prompts = PromptSettings(voice_intent_directive="intent rules")
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=ResponseModeState(bus=EventBus()),
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert orchestrator._history.as_messages() == [
        {"role": "user", "content": VOICE_PLACEHOLDER_TEXT},
        {"role": "system", "content": main_module._MODE_SWITCH_HISTORY_NOTE},
    ]


async def test_probe_failure_fails_safe_to_a_normal_request():
    backend = _FakeVoiceIntentBackend(probe_error=RuntimeError("probe backend down"))
    forwarding = _ForwardingBackend(backend)
    prompts = PromptSettings(voice_intent_directive="intent rules")
    state = ResponseModeState(bus=EventBus())
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=state,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    # The ordinary dispatch ran after the failed probe; mode unchanged.
    assert len(forwarding.chat_calls) == 1
    assert state.mode is ResponseMode.TEXT


async def test_non_marker_probe_reply_passes_through_as_a_normal_request():
    """Content mentioning modes ("read me the switch statement out loud")
    - and any other non-marker probe answer - flows through unchanged."""
    backend = _FakeVoiceIntentBackend(
        probe_reply="Отвечу подробно: это обычный запрос про modes."
    )
    forwarding = _ForwardingBackend(backend)
    prompts = PromptSettings(voice_intent_directive="intent rules")
    state = ResponseModeState(bus=EventBus())
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=state,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert state.mode is ResponseMode.TEXT
    assert len(forwarding.chat_calls) == 1


async def test_near_miss_marker_reply_passes_through_as_a_normal_request():
    """A chatty wrapper around the marker text is not the one accepted
    shape - fail safe to request."""
    backend = _FakeVoiceIntentBackend(
        probe_reply="Готово: SWITCH_RESPONSE_MODE=voice - переключил!"
    )
    forwarding = _ForwardingBackend(backend)
    prompts = PromptSettings(voice_intent_directive="intent rules")
    state = ResponseModeState(bus=EventBus())
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=state,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert state.mode is ResponseMode.TEXT
    assert len(forwarding.chat_calls) == 1


async def test_interrupt_during_the_probe_prevents_a_late_mode_switch():
    """story-v1.9.0 task 4 review finding: the probe runs outside
    _active_chat_task, so cancel_active_turn() cannot cancel it directly -
    the gate must re-check interrupt_requested after the probe and before
    set_mode(), or a late marker would mutate the mode and publish a
    command-style completion for a turn _cancel_current_turn() already
    recorded as interrupted."""
    probe_hang = asyncio.Event()
    backend = _FakeVoiceIntentBackend(
        probe_reply="SWITCH_RESPONSE_MODE=voice", probe_hang=probe_hang
    )
    forwarding = _ForwardingBackend(backend)
    prompts = PromptSettings(voice_intent_directive="intent rules")
    bus = EventBus()
    state = ResponseModeState(bus=bus)
    orchestrator = Orchestrator(
        forwarding,
        ConversationHistory(),
        _FakeSoundCues(),
        response_mode=state,
        reasoning_prompt_settings=prompts,
        bus=bus,
    )
    orchestrator._system_prompt = "base prompt"

    turn = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # let the probe's iter_chat reach its hang point
    assert len(backend.iter_calls) == 1

    orchestrator._interrupt_requested.set()
    probe_hang.set()  # let the probe finish - but the interrupt is already set
    await turn

    assert state.mode is ResponseMode.TEXT
    assert forwarding.chat_calls == []
