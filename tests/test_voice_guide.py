"""VoiceGuideService: queue, guide pass, speech, journal. Uses the real
ReplayPlayer over a fake synthesis engine and a gated play callable, so cancel
and completion behave as they do in the app; no Ollama, no audio device."""

import asyncio
import gc
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from jarvis.audio.replay import ReplayOutcome, ReplayPlayer, TextReply
from jarvis.audio.speech_language import TtsLanguageMode
from jarvis.audio.tts_mute import TtsMuteState
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    GenerationOptions,
    GenerationProfile,
    GenerationSettings,
    ResponseSettings,
    TtsSettings,
)
from jarvis.dialog.backend import LENGTH_CAP_DONE_REASON
from jarvis.dialog.canvas_speech import GUIDANCE_SECTION_LABEL
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.dialog.voice_guide import (
    VoiceGuideAccepted,
    VoiceGuidePhase,
    VoiceGuideQueueChanged,
    VoiceGuideRejected,
    VoiceGuideRejection,
    VoiceGuideRequest,
    VoiceGuideService,
)
from jarvis.journal.external_canvas import (
    ExternalCanvasCaller,
    SpeechOrigin,
    SpeechStatus,
)

_HANG = object()
_STOP_TIMEOUT_SECONDS = 0.5

_RESPONSE_SETTINGS = ResponseSettings(
    speech_language_ru="speak russian",
    speech_language_en="speak english",
    speech_language_request="speak the question's language",
)
_VOICE_GUIDE_OPTIONS = GenerationOptions(temperature=0.3, num_predict=256)


def _generation() -> GenerationSettings:
    profiles = dict(GenerationSettings().profiles)
    profiles["voice_guide"] = GenerationProfile(
        options=_VOICE_GUIDE_OPTIONS, prompt="guide prompt", reasoning="off"
    )
    return GenerationSettings(
        defaults=GenerationOptions(num_predict=111), profiles=profiles
    )


def _guide(text: str, done_reason: str = "stop") -> list[object]:
    return [
        {"message": {"content": text}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": done_reason},
    ]


@dataclass
class _BackendCall:
    messages: list[dict[str, object]]
    reasoning_level: ReasoningLevel
    tools: object
    options: GenerationOptions


class _FakeBackend:
    """Replays one script per iter_chat call: chunks, an Exception to raise, or
    _HANG to stall until the consumer is cancelled."""

    def __init__(self, *scripts: list[object]) -> None:
        self._scripts = deque(scripts)
        self.calls: list[_BackendCall] = []

    async def iter_chat(
        self,
        messages,
        images_b64=None,
        reasoning_level=ReasoningLevel.OFF,
        tools=None,
        *,
        options,
    ):
        self.calls.append(_BackendCall(list(messages), reasoning_level, tools, options))
        for step in self._scripts.popleft():
            if isinstance(step, Exception):
                raise step
            if step is _HANG:
                await asyncio.Event().wait()
            yield step


class _FakeEngine:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        self.seen.append((text, language))
        return text.encode()


class _GatedPlay:
    """Records each clip when it starts. While held, a clip plays until
    release_one() lets it finish."""

    def __init__(self, *, held: bool) -> None:
        self.held = held
        self.clips: list[str] = []
        self.finished: list[str] = []
        self.fail_next: Exception | None = None
        self._turnstile = asyncio.Semaphore(0)

    async def __call__(self, audio: bytes) -> None:
        self.clips.append(audio.decode())
        if self.held:
            await self._turnstile.acquire()
        if self.fail_next is not None:
            failure, self.fail_next = self.fail_next, None
            raise failure
        self.finished.append(audio.decode())

    def release_one(self) -> None:
        self._turnstile.release()


class _FakeRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.failures_left = 0
        self.on_record: Callable[[], None] | None = None

    async def record_external_canvas(self, canvas: str, **metadata: object) -> None:
        if self.on_record is not None:
            self.on_record()
        if self.failures_left:
            self.failures_left -= 1
            raise OSError("journal unavailable")
        self.calls.append({"canvas": canvas, **metadata})

    @property
    def statuses(self) -> list[SpeechStatus]:
        return [call["speech_status"] for call in self.calls]

    @property
    def canvases(self) -> list[str]:
        return [call["canvas"] for call in self.calls]


async def _until(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


@dataclass
class _Rig:
    service: VoiceGuideService
    backend: _FakeBackend
    recorder: _FakeRecorder
    engine: _FakeEngine
    play: _GatedPlay
    player: ReplayPlayer
    error_cues: list[str]
    queue_events: list[VoiceGuideQueueChanged]
    language_mode: list[TtsLanguageMode]
    bus: EventBus

    @property
    def worker(self) -> asyncio.Task:
        worker = self.service._worker
        assert worker is not None
        return worker

    async def stop(self) -> None:
        """Closes the service in the calling task, so close() begins before the
        worker has had a step, and fails rather than hangs when it never
        ends."""
        try:
            async with asyncio.timeout(_STOP_TIMEOUT_SECONDS):
                await self.service.close()
        except TimeoutError:
            if self.service._worker is not None:
                self.service._worker.cancel()
            pytest.fail("close() did not finish")

    async def settled(self, journaled: int) -> None:
        await _until(
            lambda: len(self.recorder.calls) == journaled
            and self.service.queue_length == 0
        )


@pytest.fixture
async def make_rig():
    rigs: list[_Rig] = []

    def make(
        *scripts: list[object],
        capacity: int = 8,
        origin: SpeechOrigin = SpeechOrigin.DERIVATIVE,
        held: bool = False,
        muted: bool = False,
        mode: TtsLanguageMode = TtsLanguageMode.DYNAMIC,
        started: bool = True,
        backend: object | None = None,
    ) -> _Rig:
        bus = EventBus()
        queue_events: list[VoiceGuideQueueChanged] = []

        async def collect(event: VoiceGuideQueueChanged) -> None:
            queue_events.append(event)

        bus.subscribe(VoiceGuideQueueChanged, collect)
        engine = _FakeEngine()
        play = _GatedPlay(held=held)
        player = ReplayPlayer(
            TtsSettings(),
            engine,
            play=play,
            mute_state=TtsMuteState(bus, enabled=not muted),
        )
        backend = backend or _FakeBackend(*scripts)
        recorder = _FakeRecorder()
        error_cues: list[str] = []
        language_mode = [mode]

        async def on_error() -> None:
            error_cues.append("error")

        service = VoiceGuideService(
            backend=backend,
            player=player,
            recorder=recorder,
            bus=bus,
            generation_settings=_generation(),
            response_settings=_RESPONSE_SETTINGS,
            language_mode=lambda: language_mode[0],
            canvas_only_origin=origin,
            on_error=on_error,
            capacity=capacity,
        )
        rig = _Rig(
            service,
            backend,
            recorder,
            engine,
            play,
            player,
            error_cues,
            queue_events,
            language_mode,
            bus,
        )
        if started:
            service.start()
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        await rig.stop()


# --- origins ---------------------------------------------------------------


async def test_spoken_text_from_the_caller_is_spoken_without_a_model_call(make_rig):
    rig = make_rig()

    rig.service.enqueue(VoiceGuideRequest("A long canvas.", spoken_text="Short one."))
    await rig.settled(1)

    assert rig.backend.calls == []
    assert rig.play.clips == ["Short one."]
    assert rig.recorder.calls[0]["speech_origin"] is SpeechOrigin.CALLER


async def test_spoken_text_from_the_caller_is_journaled_as_the_derivative(make_rig):
    rig = make_rig()

    rig.service.enqueue(VoiceGuideRequest("A long canvas.", spoken_text="Short one."))
    await rig.settled(1)

    assert rig.recorder.calls[0]["spoken_derivative"] == "Short one."
    assert rig.recorder.calls[0]["canvas"] == "A long canvas."


async def test_verbatim_canvas_is_spoken_as_is_without_a_model_call(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)

    rig.service.enqueue(VoiceGuideRequest("Say this."))
    await rig.settled(1)

    assert rig.backend.calls == []
    assert rig.play.clips == ["Say this."]


async def test_verbatim_canvas_journals_no_derivative(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)

    rig.service.enqueue(VoiceGuideRequest("Say this."))
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["speech_origin"] is SpeechOrigin.VERBATIM
    assert call["spoken_derivative"] is None


async def test_canvas_only_request_runs_one_guide_pass_and_speaks_its_text(make_rig):
    rig = make_rig(_guide("The gist."))

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    assert len(rig.backend.calls) == 1
    assert rig.play.clips == ["The gist."]
    call = rig.recorder.calls[0]
    assert call["speech_origin"] is SpeechOrigin.DERIVATIVE
    assert call["spoken_derivative"] == "The gist."
    assert call["canvas"] == "The whole answer."


async def test_guide_pass_has_no_tools_and_uses_the_voice_guide_profile(make_rig):
    rig = make_rig(_guide("The gist."))

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    backend_call = rig.backend.calls[0]
    assert backend_call.tools is None
    assert backend_call.reasoning_level is ReasoningLevel.OFF
    assert backend_call.options == GenerationOptions(temperature=0.3, num_predict=256)


async def test_guide_pass_sends_the_profile_prompt_and_the_exact_canvas(make_rig):
    rig = make_rig(_guide("The gist."))

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    assert rig.backend.calls[0].messages == [
        {"role": "system", "content": "guide prompt"},
        {"role": "user", "content": "The whole answer."},
    ]


async def test_guidance_is_its_own_system_section_and_not_part_of_the_canvas(
    make_rig,
):
    rig = make_rig(_guide("The gist."))

    rig.service.enqueue(VoiceGuideRequest("The whole answer.", guidance="the risks"))
    await rig.settled(1)

    system, user = rig.backend.calls[0].messages
    assert system["content"] == f"guide prompt\n\n{GUIDANCE_SECTION_LABEL}\nthe risks"
    assert user["content"] == "The whole answer."


async def test_guidance_is_journaled_with_a_derivative_request(make_rig):
    rig = make_rig(_guide("The gist."))

    rig.service.enqueue(VoiceGuideRequest("The whole answer.", guidance="the risks"))
    await rig.settled(1)

    assert rig.recorder.calls[0]["guidance"] == "the risks"


async def test_guidance_is_ignored_for_caller_spoken_text_but_still_journaled(
    make_rig,
):
    rig = make_rig()

    rig.service.enqueue(
        VoiceGuideRequest("Canvas.", spoken_text="Short one.", guidance="the risks")
    )
    await rig.settled(1)

    assert rig.backend.calls == []
    assert rig.recorder.calls[0]["guidance"] == "the risks"


async def test_caller_identity_is_journaled(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    caller = ExternalCanvasCaller(name="claude-code", version="1.0")

    rig.service.enqueue(VoiceGuideRequest("Say this.", caller=caller))
    await rig.settled(1)

    assert rig.recorder.calls[0]["caller"] == caller


async def test_fixed_language_mode_tells_the_guide_pass_the_language(make_rig):
    rig = make_rig(_guide("The gist."), mode=TtsLanguageMode.RUSSIAN)

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    assert rig.backend.calls[0].messages[0]["content"] == (
        "guide prompt\n\nspeak russian"
    )


async def test_request_mode_tells_the_guide_pass_the_canvas_language(make_rig):
    rig = make_rig(_guide("Суть."), mode=TtsLanguageMode.REQUEST)

    rig.service.enqueue(VoiceGuideRequest("Ответ на русском языке."))
    await rig.settled(1)

    assert rig.backend.calls[0].messages[0]["content"] == (
        "guide prompt\n\nspeak russian"
    )


async def test_language_mode_is_read_again_for_every_item(make_rig):
    rig = make_rig(_guide("One."), _guide("Two."), mode=TtsLanguageMode.RUSSIAN)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)

    rig.language_mode[0] = TtsLanguageMode.ENGLISH
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await rig.settled(2)

    contracts = [call.messages[0]["content"] for call in rig.backend.calls]
    assert contracts == [
        "guide prompt\n\nspeak russian",
        "guide prompt\n\nspeak english",
    ]


# --- order, capacity, queue ------------------------------------------------


async def test_items_are_spoken_one_at_a_time_in_order(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    for canvas in ("First.", "Second.", "Third."):
        rig.service.enqueue(VoiceGuideRequest(canvas))

    await _until(lambda: rig.play.clips == ["First."])
    rig.play.release_one()
    await _until(lambda: rig.play.clips == ["First.", "Second."])
    assert rig.play.finished == ["First."]
    rig.play.release_one()
    rig.play.release_one()
    await rig.settled(3)

    assert rig.play.clips == ["First.", "Second.", "Third."]
    assert rig.recorder.canvases == ["First.", "Second.", "Third."]


async def test_enqueue_during_playback_does_not_stop_the_current_item(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])

    rig.service.enqueue(VoiceGuideRequest("Second."))
    await asyncio.sleep(0)

    assert rig.player.is_active
    assert rig.recorder.calls == []
    rig.play.release_one()
    rig.play.release_one()
    await rig.settled(2)
    assert rig.recorder.statuses == [SpeechStatus.SPOKEN, SpeechStatus.SPOKEN]


async def test_enqueue_reports_a_one_based_position_behind_what_is_pending(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)

    positions = [
        rig.service.enqueue(VoiceGuideRequest(canvas))
        for canvas in ("First.", "Second.", "Third.")
    ]

    assert positions == [
        VoiceGuideAccepted(position, SpeechOrigin.VERBATIM) for position in (1, 2, 3)
    ]


@pytest.mark.parametrize(
    "canvas_only_origin", [SpeechOrigin.DERIVATIVE, SpeechOrigin.VERBATIM]
)
async def test_enqueue_reports_the_configured_origin_for_a_canvas_only_request(
    make_rig, canvas_only_origin
):
    rig = make_rig(origin=canvas_only_origin, held=True)

    result = rig.service.enqueue(VoiceGuideRequest("An answer."))

    assert result == VoiceGuideAccepted(1, canvas_only_origin)


async def test_enqueue_reports_the_caller_origin_when_spoken_text_is_given(make_rig):
    rig = make_rig(origin=SpeechOrigin.DERIVATIVE, held=True)

    result = rig.service.enqueue(
        VoiceGuideRequest("An answer.", spoken_text="Read this.")
    )

    assert result == VoiceGuideAccepted(1, SpeechOrigin.CALLER)


async def test_enqueue_beyond_capacity_is_rejected_as_queue_full(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True, capacity=2)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))

    result = rig.service.enqueue(VoiceGuideRequest("Third."))

    assert result == VoiceGuideRejected(VoiceGuideRejection.QUEUE_FULL)


async def test_a_rejected_enqueue_leaves_the_queue_unchanged(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True, capacity=2)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))

    rig.service.enqueue(VoiceGuideRequest("Third."))
    rig.play.release_one()
    rig.play.release_one()
    await rig.settled(2)

    assert rig.service.queue_length == 0
    assert rig.recorder.canvases == ["First.", "Second."]


async def test_capacity_frees_up_as_items_finish(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, capacity=1)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)

    result = rig.service.enqueue(VoiceGuideRequest("Second."))

    assert result == VoiceGuideAccepted(1, SpeechOrigin.VERBATIM)


async def test_queue_length_counts_the_item_in_flight(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First."])

    assert rig.service.queue_length == 2


async def test_bus_event_follows_every_queue_change(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)

    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)
    await _until(lambda: len(rig.queue_events) == 4)

    assert rig.queue_events == [
        VoiceGuideQueueChanged(length=1),
        VoiceGuideQueueChanged(length=1, phase=VoiceGuidePhase.PREPARING),
        VoiceGuideQueueChanged(length=1, phase=VoiceGuidePhase.SPEAKING),
        VoiceGuideQueueChanged(length=0),
    ]


async def test_a_derivative_item_reports_preparing_then_speaking(make_rig):
    rig = make_rig(_guide("Short guide."), origin=SpeechOrigin.DERIVATIVE, held=True)

    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["Short guide."])
    await _until(lambda: len(rig.queue_events) == 3)

    assert [event.phase for event in rig.queue_events] == [
        VoiceGuidePhase.IDLE,
        VoiceGuidePhase.PREPARING,
        VoiceGuidePhase.SPEAKING,
    ]


async def test_a_verbatim_item_reports_preparing_while_the_player_waits(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)

    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])
    await _until(lambda: len(rig.queue_events) == 3)

    assert [event.phase for event in rig.queue_events] == [
        VoiceGuidePhase.IDLE,
        VoiceGuidePhase.PREPARING,
        VoiceGuidePhase.SPEAKING,
    ]


async def test_a_muted_guide_never_reports_speaking(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, muted=True)

    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)
    await _until(lambda: len(rig.queue_events) == 3)

    assert [event.phase for event in rig.queue_events] == [
        VoiceGuidePhase.IDLE,
        VoiceGuidePhase.PREPARING,
        VoiceGuidePhase.IDLE,
    ]


async def test_interrupt_publishes_the_emptied_queue(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First."])

    rig.service.interrupt()
    await rig.settled(2)
    await _until(lambda: rig.queue_events[-1].length == 0)

    assert rig.queue_events[-1] == VoiceGuideQueueChanged(length=0)


# --- interrupt -------------------------------------------------------------


async def test_interrupt_stops_the_spoken_item_and_skips_the_queued_ones(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    for canvas in ("First.", "Second.", "Third."):
        rig.service.enqueue(VoiceGuideRequest(canvas))
    await _until(lambda: rig.play.clips == ["First."])

    rig.service.interrupt()
    await rig.settled(3)

    assert rig.recorder.canvases == ["First.", "Second.", "Third."]
    assert rig.recorder.statuses == [
        SpeechStatus.INTERRUPTED,
        SpeechStatus.SKIPPED,
        SpeechStatus.SKIPPED,
    ]
    assert rig.play.clips == ["First."]


async def test_interrupt_stops_the_audio_it_started(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])

    rig.service.interrupt()
    await rig.settled(1)

    assert not rig.player.is_active
    assert rig.play.finished == []


async def test_worker_serves_items_enqueued_after_an_interrupt(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])
    rig.service.interrupt()
    await rig.settled(1)

    rig.service.enqueue(VoiceGuideRequest("After."))
    await _until(lambda: rig.play.clips == ["First.", "After."])
    rig.play.release_one()
    await rig.settled(2)

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED, SpeechStatus.SPOKEN]


async def test_interrupt_while_idle_does_nothing(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)

    rig.service.interrupt()
    await asyncio.sleep(0)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]


async def test_skipped_caller_item_keeps_its_spoken_text_in_the_journal(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Canvas.", spoken_text="Short one."))
    await _until(lambda: rig.play.clips == ["First."])

    rig.service.interrupt()
    await rig.settled(2)

    skipped = rig.recorder.calls[1]
    assert skipped["speech_status"] is SpeechStatus.SKIPPED
    assert skipped["speech_origin"] is SpeechOrigin.CALLER
    assert skipped["spoken_derivative"] == "Short one."


async def test_skipped_derivative_item_has_no_derivative(make_rig):
    rig = make_rig(_guide("First gist."), held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First gist."])

    rig.service.interrupt()
    await rig.settled(2)

    skipped = rig.recorder.calls[1]
    assert skipped["speech_origin"] is SpeechOrigin.DERIVATIVE
    assert skipped["spoken_derivative"] is None


async def test_interrupt_during_the_guide_pass_journals_no_derivative_yet(make_rig):
    rig = make_rig([_HANG])
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _until(lambda: len(rig.backend.calls) == 1)

    rig.service.interrupt()
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.INTERRUPTED
    assert call["spoken_derivative"] is None
    assert call["spoken_derivative_truncated"] is False
    assert rig.play.clips == []


async def test_interrupt_during_the_guide_pass_keeps_the_text_produced_so_far(
    make_rig,
):
    partial = {"message": {"content": "Half a gist"}, "done": False}
    rig = make_rig([partial, _HANG])
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _until(lambda: len(rig.backend.calls) == 1)
    await asyncio.sleep(0)

    rig.service.interrupt()
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.INTERRUPTED
    assert call["spoken_derivative"] == "Half a gist"


async def test_interrupted_spoken_derivative_is_journaled_whole(make_rig):
    rig = make_rig(_guide("The gist."), held=True)
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _until(lambda: rig.play.clips == ["The gist."])

    rig.service.interrupt()
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.INTERRUPTED
    assert call["spoken_derivative"] == "The gist."


async def test_playback_cancelled_from_outside_interrupts_only_the_current_item(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First."])

    rig.player.cancel()
    await _until(lambda: rig.play.clips == ["First.", "Second."])
    rig.play.release_one()
    await rig.settled(2)

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED, SpeechStatus.SPOKEN]


async def test_a_playback_that_finishes_by_itself_is_spoken_not_interrupted(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)

    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]


# --- mute, busy player, failure, truncation ---------------------------------


async def test_muted_item_is_not_played_and_is_journaled_muted(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, muted=True)

    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)

    assert rig.play.clips == []
    assert rig.recorder.statuses == [SpeechStatus.MUTED]


async def test_muted_derivative_is_still_generated_and_journaled(make_rig):
    rig = make_rig(_guide("The gist."), muted=True)

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    assert rig.play.clips == []
    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.MUTED
    assert call["spoken_derivative"] == "The gist."


async def test_user_replay_in_progress_delays_the_item_until_it_ends(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])

    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert rig.play.clips == ["User replay."]
    rig.play.release_one()
    await _until(lambda: rig.play.clips == ["User replay.", "Guide item."])
    rig.play.release_one()
    await rig.settled(1)
    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]


async def test_user_replay_is_never_cancelled_by_the_worker(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)

    rig.service.interrupt()
    await rig.settled(1)

    assert rig.player.is_active
    rig.play.release_one()
    await _until(lambda: rig.play.finished == ["User replay."])


async def test_closing_while_the_item_waits_leaves_the_user_replay_playing(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)

    await rig.stop()

    assert rig.player.is_active
    rig.play.release_one()
    await _until(lambda: rig.play.finished == ["User replay."])


async def test_closing_mid_playback_stops_its_audio(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])

    await rig.stop()

    assert not rig.player.is_active
    assert rig.play.finished == []


# Owner review of task v2.0-3, 2026-09-30: a run is identified by its own
# handle, never by the player's shared state.
async def test_outside_cancelled_playback_is_interrupted_despite_a_new_user_replay(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.player.cancel()
    await _until(lambda: not rig.player.is_active)
    started = await rig.player.replay(TextReply("User replay."))
    await _until(lambda: len(rig.recorder.calls) == 1)

    assert started is ReplayOutcome.STARTED
    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED]


# Owner review of task v2.0-3, 2026-09-30: the guide must not cancel a replay
# it did not start.
async def test_interrupt_never_cancels_a_user_replay_started_as_the_guide_ends(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    started = await rig.player.replay(TextReply("User replay."))
    rig.service.interrupt()
    await _until(lambda: len(rig.recorder.calls) == 1)
    rig.play.release_one()
    await _until(lambda: "User replay." in rig.play.finished)

    assert started is ReplayOutcome.STARTED
    assert rig.play.finished == ["Guide item.", "User replay."]


# Owner review of task v2.0-3, 2026-09-30: the guide finishes speaking, a
# Journal replay starts, then interrupt is pressed.
async def test_guide_that_finished_speaking_stays_spoken_when_interrupt_hits_a_replay(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    await rig.player.replay(TextReply("User replay."))
    rig.service.interrupt()
    await _until(lambda: len(rig.recorder.calls) == 1)

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]
    assert rig.player.is_active


async def test_interrupt_after_the_run_completed_but_before_it_was_observed_is_spoken(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    rig.service.interrupt()
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]


async def test_run_that_failed_before_an_interrupt_is_failed_with_an_error_cue(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.play.fail_next = RuntimeError("the output device is gone")
    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    rig.service.interrupt()
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.FAILED]
    assert rig.error_cues == ["error"]


async def test_run_failure_seen_by_the_service_is_never_left_unretrieved(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    unreported: list[str] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: unreported.append(context["message"])
    )
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])
    rig.play.fail_next = RuntimeError("the output device is gone")
    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    rig.service.interrupt()
    await rig.settled(1)

    await rig.player.replay(TextReply("Replaces the failed run."))
    gc.collect()
    await asyncio.sleep(0)

    assert unreported == []


async def test_failing_user_replay_is_not_the_guides_failure(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)

    rig.play.fail_next = RuntimeError("the user's replay broke")
    rig.play.release_one()
    await _until(lambda: rig.play.clips == ["User replay.", "Guide item."])
    rig.play.release_one()
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]
    assert rig.error_cues == []


async def test_interrupt_while_waiting_on_a_user_replay_interrupts_the_item_at_once(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)

    rig.service.interrupt()
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED]
    assert rig.player.is_active
    assert rig.play.clips == ["User replay."]


async def test_guide_pass_that_fails_while_being_stopped_is_interrupted_not_failed(
    make_rig,
):
    waiting: list[str] = []

    class BackendFailingOnClose:
        async def iter_chat(self, messages, *args, **kwargs):
            try:
                yield {"message": {"content": "Half a gist"}, "done": False}
                waiting.append("waiting")
                await asyncio.Event().wait()
            finally:
                raise RuntimeError("closing the stream failed")

    rig = make_rig(backend=BackendFailingOnClose())
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _until(lambda: waiting)

    rig.service.interrupt()
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED]
    assert rig.error_cues == []


class _GuidePassFailingOnSignal:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.fail = asyncio.Event()

    async def iter_chat(self, messages, *args, **kwargs):
        yield {"message": {"content": "Half a gist"}, "done": False}
        self.started.set()
        await self.fail.wait()
        raise RuntimeError("ollama is down")


async def _fail_the_guide_pass_before_the_worker_sees_it(
    rig: _Rig, backend: _GuidePassFailingOnSignal
) -> None:
    await _until(backend.started.is_set)
    guide_pass = next(
        task
        for task in asyncio.all_tasks()
        if task.get_coro().__qualname__.endswith("_guide_pass")
    )
    backend.fail.set()
    await _until(guide_pass.done)
    assert rig.recorder.calls == []


async def test_guide_pass_that_failed_just_before_an_interrupt_is_failed_with_a_cue(
    make_rig,
):
    backend = _GuidePassFailingOnSignal()
    rig = make_rig(backend=backend)
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _fail_the_guide_pass_before_the_worker_sees_it(rig, backend)

    rig.service.interrupt()
    await rig.settled(1)

    assert rig.recorder.statuses == [SpeechStatus.FAILED]
    assert rig.error_cues == ["error"]


async def test_guide_pass_that_failed_just_before_close_is_failed_with_a_cue(
    make_rig,
):
    backend = _GuidePassFailingOnSignal()
    rig = make_rig(backend=backend)
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _fail_the_guide_pass_before_the_worker_sees_it(rig, backend)

    await rig.stop()

    assert rig.recorder.statuses == [SpeechStatus.FAILED]
    assert rig.error_cues == ["error"]


async def test_interrupt_while_waiting_on_a_user_replay_leaves_no_waiter_task(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    unreported: list[str] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: unreported.append(context["message"])
    )
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)

    rig.service.interrupt()
    await rig.settled(1)
    await asyncio.sleep(0)

    waiters = [
        task
        for task in asyncio.all_tasks()
        if task.get_coro().__qualname__.endswith("_other_run_ended")
    ]
    assert waiters == []
    assert rig.player.is_active
    rig.play.fail_next = RuntimeError("the user's replay broke")
    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    gc.collect()
    await asyncio.sleep(0)
    assert unreported == []


async def test_item_enqueued_after_an_interrupted_wait_is_spoken_after_the_user_replay(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Dropped."))
    await asyncio.sleep(0)
    rig.service.interrupt()
    await rig.settled(1)

    rig.service.enqueue(VoiceGuideRequest("Next."))
    rig.play.release_one()
    await _until(lambda: rig.play.clips == ["User replay.", "Next."])
    rig.play.release_one()
    await rig.settled(2)

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED, SpeechStatus.SPOKEN]


# --- close ------------------------------------------------------------------


async def test_close_mid_item_journals_it_interrupted_and_the_queue_skipped(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    for canvas in ("First.", "Second.", "Third."):
        rig.service.enqueue(VoiceGuideRequest(canvas))
    await _until(lambda: rig.play.clips == ["First."])

    await rig.stop()

    assert rig.recorder.canvases == ["First.", "Second.", "Third."]
    assert rig.recorder.statuses == [
        SpeechStatus.INTERRUPTED,
        SpeechStatus.SKIPPED,
        SpeechStatus.SKIPPED,
    ]


async def test_close_ends_the_worker_without_cancelling_it(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])

    await rig.stop()

    assert rig.worker.done() and not rig.worker.cancelled()
    assert len(rig.recorder.calls) == 1


async def test_close_during_the_guide_pass_keeps_the_text_produced_so_far(
    make_rig,
):
    partial = {"message": {"content": "Half a gist"}, "done": False}
    rig = make_rig([partial, _HANG])
    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await _until(lambda: len(rig.backend.calls) == 1)
    await asyncio.sleep(0)

    await rig.stop()

    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.INTERRUPTED
    assert call["spoken_derivative"] == "Half a gist"


async def test_interrupt_followed_at_once_by_close_journals_each_canvas_once(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    for canvas in ("First.", "Second.", "Third."):
        rig.service.enqueue(VoiceGuideRequest(canvas))
    await _until(lambda: rig.play.clips == ["First."])

    rig.service.interrupt()
    await rig.stop()

    assert rig.recorder.canvases == ["First.", "Second.", "Third."]
    assert rig.recorder.statuses == [
        SpeechStatus.INTERRUPTED,
        SpeechStatus.SKIPPED,
        SpeechStatus.SKIPPED,
    ]


async def test_close_while_waiting_on_a_user_replay_interrupts_the_item(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    await rig.player.replay(TextReply("User replay."))
    await _until(lambda: rig.play.clips == ["User replay."])
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await asyncio.sleep(0)

    await rig.stop()

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED]
    assert rig.player.is_active


async def test_close_after_the_run_completed_but_before_it_was_observed_is_spoken(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    await rig.stop()

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]


async def test_close_after_the_run_failed_before_it_was_observed_cues_an_error(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("Guide item."))
    await _until(lambda: rig.play.clips == ["Guide item."])

    rig.play.fail_next = RuntimeError("the output device is gone")
    rig.play.release_one()
    await _until(lambda: not rig.player.is_active)
    await rig.stop()

    assert rig.recorder.statuses == [SpeechStatus.FAILED]
    assert rig.error_cues == ["error"]


async def test_close_before_start_journals_every_accepted_request_skipped(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, started=False)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))

    await rig.stop()

    assert rig.recorder.canvases == ["First.", "Second."]
    assert rig.recorder.statuses == [SpeechStatus.SKIPPED, SpeechStatus.SKIPPED]
    assert rig.play.clips == []


async def test_close_before_the_worker_ran_a_step_journals_every_request_skipped(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))

    await rig.stop()

    assert rig.recorder.canvases == ["First.", "Second."]
    assert rig.recorder.statuses == [SpeechStatus.SKIPPED, SpeechStatus.SKIPPED]
    assert rig.play.clips == []


async def test_enqueue_after_close_is_rejected_as_closed_and_journals_nothing(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    await rig.stop()

    result = rig.service.enqueue(VoiceGuideRequest("Too late."))
    await asyncio.sleep(0)

    assert result == VoiceGuideRejected(VoiceGuideRejection.CLOSED)
    assert rig.recorder.calls == []
    assert rig.service.queue_length == 0


async def test_enqueue_while_close_is_journaling_is_rejected_as_closed(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])
    late_results = []

    def enqueue_once_late() -> None:
        if not late_results:
            late_results.append(rig.service.enqueue(VoiceGuideRequest("Too late.")))

    rig.recorder.on_record = enqueue_once_late

    await rig.stop()

    assert late_results == [VoiceGuideRejected(VoiceGuideRejection.CLOSED)]
    assert rig.recorder.canvases == ["First."]


async def test_interrupt_after_close_does_nothing(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    await rig.stop()
    events_after_close = list(rig.queue_events)

    rig.service.interrupt()
    for _ in range(10):
        await asyncio.sleep(0)

    assert rig.recorder.calls == []
    assert rig.queue_events == events_after_close


async def test_close_while_idle_journals_nothing_more(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await rig.settled(1)

    await rig.stop()

    assert rig.recorder.statuses == [SpeechStatus.SPOKEN]


async def test_close_is_idempotent_and_journals_each_request_once(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First."])

    await asyncio.gather(rig.stop(), rig.stop())
    await rig.stop()

    assert rig.recorder.canvases == ["First.", "Second."]


async def test_close_survives_a_caller_that_is_cancelled_inside_it(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First."])
    caller = asyncio.create_task(rig.service.close())
    await asyncio.sleep(0)

    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await rig.stop()

    assert rig.recorder.statuses == [SpeechStatus.INTERRUPTED, SpeechStatus.SKIPPED]


async def test_close_publishes_a_final_empty_queue_event(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await _until(lambda: rig.play.clips == ["First."])

    await rig.stop()

    assert rig.queue_events[-1] == VoiceGuideQueueChanged(length=0)


async def test_close_returns_only_after_a_slow_subscriber_got_every_queue_event(
    make_rig,
):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    delivered: list[VoiceGuideQueueChanged] = []

    async def slow_subscriber(event: VoiceGuideQueueChanged) -> None:
        await asyncio.sleep(0.01)
        delivered.append(event)

    rig.bus.subscribe(VoiceGuideQueueChanged, slow_subscriber)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])

    await rig.stop()

    assert delivered == rig.queue_events
    assert delivered[-1] == VoiceGuideQueueChanged(length=0)


async def test_start_twice_is_an_error(make_rig):
    rig = make_rig()

    with pytest.raises(RuntimeError, match="already started"):
        rig.service.start()


async def test_start_after_close_is_an_error(make_rig):
    rig = make_rig(started=False)
    await rig.stop()

    with pytest.raises(RuntimeError, match="closed"):
        rig.service.start()


async def test_a_worker_that_ended_without_close_rejects_new_requests(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    rig.worker.cancel()
    await asyncio.wait({rig.worker})

    result = rig.service.enqueue(VoiceGuideRequest("Too late."))

    assert result == VoiceGuideRejected(VoiceGuideRejection.CLOSED)


async def test_close_after_the_worker_died_mid_item_publishes_an_empty_queue(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])
    rig.worker.cancel()
    await asyncio.wait({rig.worker})

    await rig.stop()

    assert rig.queue_events[-1] == VoiceGuideQueueChanged(length=0)


# --- failure, truncation --------------------------------------------------


async def test_a_failing_bus_publish_is_logged_not_left_unretrieved(make_rig, caplog):
    rig = make_rig(origin=SpeechOrigin.VERBATIM, held=True)
    unreported: list[str] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: unreported.append(context["message"])
    )

    async def broken_publish(*_args: object) -> None:
        raise RuntimeError("the bus is broken")

    rig.bus.publish = broken_publish
    rig.service.enqueue(VoiceGuideRequest("First."))
    await _until(lambda: rig.play.clips == ["First."])

    await rig.stop()
    gc.collect()
    await asyncio.sleep(0)

    assert unreported == []
    assert "background task failed" in caplog.text


async def test_backend_failure_is_journaled_failed_and_cues_an_error(make_rig):
    rig = make_rig([RuntimeError("ollama is down")])

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.FAILED
    assert call["spoken_derivative"] is None
    assert rig.error_cues == ["error"]
    assert rig.play.clips == []


async def test_worker_serves_the_next_item_after_a_failure(make_rig):
    rig = make_rig([RuntimeError("ollama is down")], _guide("Second gist."))

    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await rig.settled(2)

    assert rig.recorder.statuses == [SpeechStatus.FAILED, SpeechStatus.SPOKEN]
    assert rig.play.clips == ["Second gist."]


async def test_a_guide_pass_that_says_nothing_is_a_failure(make_rig):
    rig = make_rig(_guide("  "))

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["speech_status"] is SpeechStatus.FAILED
    assert call["spoken_derivative"] is None
    assert rig.error_cues == ["error"]


async def test_journal_failure_does_not_stop_the_worker(make_rig):
    rig = make_rig(origin=SpeechOrigin.VERBATIM)
    rig.recorder.failures_left = 1

    rig.service.enqueue(VoiceGuideRequest("First."))
    rig.service.enqueue(VoiceGuideRequest("Second."))
    await rig.settled(1)

    assert rig.recorder.canvases == ["Second."]


async def test_length_capped_guide_pass_is_journaled_truncated(make_rig):
    rig = make_rig(_guide("Cut off gi", done_reason=LENGTH_CAP_DONE_REASON))

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    call = rig.recorder.calls[0]
    assert call["spoken_derivative"] == "Cut off gi"
    assert call["spoken_derivative_truncated"] is True


async def test_a_guide_pass_that_finished_normally_is_not_truncated(make_rig):
    rig = make_rig(_guide("The gist."))

    rig.service.enqueue(VoiceGuideRequest("The whole answer."))
    await rig.settled(1)

    assert rig.recorder.calls[0]["spoken_derivative_truncated"] is False


# --- construction ----------------------------------------------------------


def test_canvas_only_origin_cannot_be_caller():
    with pytest.raises(ValueError, match="canvas_only_origin"):
        _service_with(canvas_only_origin=SpeechOrigin.CALLER)


def test_capacity_must_be_positive():
    with pytest.raises(ValueError, match="capacity"):
        _service_with(capacity=0)


def _service_with(**overrides) -> VoiceGuideService:
    arguments = {
        "backend": _FakeBackend(),
        "player": object(),
        "recorder": _FakeRecorder(),
        "bus": EventBus(),
        "generation_settings": _generation(),
        "response_settings": _RESPONSE_SETTINGS,
        "language_mode": lambda: TtsLanguageMode.DYNAMIC,
        "canvas_only_origin": SpeechOrigin.VERBATIM,
        "on_error": None,
        "capacity": 1,
    }
    return VoiceGuideService(**(arguments | overrides))
