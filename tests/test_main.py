import asyncio
import base64

from audio_in import UtteranceChunk
from backend import LatencyMetrics, ResponseComplete, ResponseToken
from capture import ScreenshotCaptured
from config import Settings, VadSettings
from bus import EventBus
from main import (
    SYSTEM_PROMPT,
    App,
    ConversationHistory,
    Orchestrator,
    _on_full_response_complete,
    build_app,
    is_elevated,
    run_until_shutdown,
    unwire,
    wire,
)
from sound_cues import SoundCuePlayer


class _FakeBackend:
    def __init__(self, chat_impl=None) -> None:
        self.calls: list[tuple[list[dict], list[str] | None]] = []
        self._chat_impl = chat_impl

    async def chat(self, messages, images_b64=None) -> None:
        self.calls.append((messages, images_b64))
        if self._chat_impl is not None:
            await self._chat_impl()


class _FakeSoundCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play(self, cue: str) -> None:
        self.played.append(cue)


def _complete_event() -> ResponseComplete:
    return ResponseComplete(
        metrics=LatencyMetrics(load_seconds=0, prompt_eval_seconds=0, eval_seconds=0, eval_count=0)
    )


# --- system prompt -----------------------------------------------------


def test_system_prompt_includes_russian_and_short_answer_directives():
    assert "по-русски" in SYSTEM_PROMPT
    assert "коротко" in SYSTEM_PROMPT


# --- ConversationHistory (text-only, extensible) ------------------------


def test_history_messages_are_text_only_by_default():
    history = ConversationHistory()
    history.add("user", "привет")
    history.add("assistant", "привет!")

    messages = history.as_messages()

    assert messages == [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "привет!"},
    ]
    assert all("images" not in m for m in messages)


def test_history_messages_include_media_when_provided():
    """v1.0 never calls add() with media_b64, but the mechanism already
    works - a later release extending history to carry media doesn't
    need to restructure this class."""
    history = ConversationHistory()
    history.add("user", "смотри", media_b64=("base64data",))

    [message] = history.as_messages()

    assert message["images"] == ["base64data"]


# --- Orchestrator --------------------------------------------------------


def _orchestrator(chat_impl=None) -> tuple[Orchestrator, _FakeBackend, _FakeSoundCues]:
    backend = _FakeBackend(chat_impl)
    sound_cues = _FakeSoundCues()
    orchestrator = Orchestrator(backend, ConversationHistory(), sound_cues)
    return orchestrator, backend, sound_cues


async def test_on_utterance_sends_media_and_plays_thinking_cue():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_screenshot(ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1))
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1))

    assert sound_cues.played == ["thinking"]
    [(messages, media)] = backend.calls
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[-1] == {"role": "user", "content": "[голосовое сообщение]"}
    # audio first, then the pending screenshot
    assert media == [base64.b64encode(b"wav").decode(), base64.b64encode(b"png").decode()]


async def test_on_utterance_without_screenshot_sends_only_audio():
    orchestrator, backend, sound_cues = _orchestrator()

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1))

    [(_messages, media)] = backend.calls
    assert len(media) == 1


async def test_screenshot_is_consumed_once_not_resent_on_next_utterance():
    orchestrator, backend, _ = _orchestrator()

    await orchestrator.on_screenshot(ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1))
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav1", start_seconds=0, end_seconds=1))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()  # normally called after wait_for_pending() - see wire()
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"wav2", start_seconds=0, end_seconds=1))

    assert len(backend.calls[0][1]) == 2  # first turn: audio + screenshot
    assert len(backend.calls[1][1]) == 1  # second turn: audio only


async def test_on_response_token_plays_speaking_cue_only_once():
    orchestrator, _backend, sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_token(ResponseToken(text=", мир"))

    assert sound_cues.played.count("speaking") == 1


async def test_on_response_complete_records_history():
    orchestrator, _backend, _sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_token(ResponseToken(text=", мир"))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert messages[-2] == {"role": "user", "content": "[голосовое сообщение]"}
    assert messages[-1] == {"role": "assistant", "content": "Привет, мир"}


async def test_busy_utterance_is_ignored_until_previous_turn_completes():
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    )
    await asyncio.sleep(0)  # let the first call start and set _busy
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))

    assert len(backend.calls) == 1  # second utterance was ignored while busy

    still_busy.set()
    await first


async def test_finish_turn_cooldown_rejects_a_self_heard_echo():
    """Regression test for a real bug: after Jarvis stops speaking,
    audio_in.py can still be sitting on a self-heard "utterance" (its own
    voice picked up by the mic - no echo cancellation in v1.0) for up to
    request_end_pause_seconds before it publishes it. If busy had already
    cleared by then, that echo was accepted and answered as if it were a
    genuine new question - Jarvis talking to itself. finish_turn()'s
    cooldown keeps busy True for that whole window."""
    orchestrator, backend, _sound_cues = _orchestrator()
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    await orchestrator.on_response_complete(_complete_event())

    finish_task = asyncio.create_task(orchestrator.finish_turn(cooldown_seconds=0.05))
    await asyncio.sleep(0)  # let finish_turn() start its cooldown sleep

    # still within the cooldown: a self-heard echo must be rejected, same as mid-turn
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"echo", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 1

    await finish_task  # cooldown elapses, busy clears

    # a genuine new utterance after the cooldown is accepted
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 2


async def test_error_during_chat_plays_error_cue_and_clears_busy():
    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=failing_chat)

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))

    assert sound_cues.played == ["thinking", "error"]

    # busy was cleared, so a subsequent utterance is not ignored
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 2


# --- wiring --------------------------------------------------------------


class _FakeAudioInput:
    pass


class _FakeTtsOutput:
    async def on_token(self, event) -> None:
        pass

    async def on_response_complete(self, event) -> None:
        pass

    async def wait_for_pending(self) -> None:
        return None


class _FakeCaptureInput:
    pass


def _settings() -> Settings:
    return Settings()


def _fake_app() -> App:
    """build_app() with fakes for every hardware-touching module, plus a
    fake backend so a bug in unwire()/shutdown can never trigger a real
    network call - not just "shouldn't happen if the code is correct"."""
    return build_app(
        _settings(),
        backend=_FakeBackend(),
        audio_input=_FakeAudioInput(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )


def test_wire_registers_expected_subscriptions():
    app = _fake_app()

    subscriptions = wire(app)
    event_types = [event_type for event_type, _handler in subscriptions]

    assert event_types.count(UtteranceChunk) == 1
    assert event_types.count(ScreenshotCaptured) == 1
    assert event_types.count(ResponseToken) == 2  # tts_output + orchestrator
    # A single coordinating handler, not three concurrent subscribers -
    # see _on_full_response_complete's docstring for why that mattered.
    assert event_types.count(ResponseComplete) == 1

    handlers = [handler for _event_type, handler in subscriptions]
    assert app.orchestrator.on_utterance in handlers
    assert app.orchestrator.on_screenshot in handlers


async def test_unwire_removes_all_subscriptions():
    app = _fake_app()
    subscriptions = wire(app)

    unwire(app, subscriptions)

    # the orchestrator's own handler should no longer be subscribed - if
    # it were, backend.chat() would have been called
    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    assert app.backend.calls == []


# --- shutdown --------------------------------------------------------------


async def test_run_until_shutdown_cancels_tasks_and_unsubscribes():
    app = _fake_app()
    subscriptions = wire(app)
    shutdown_event = asyncio.Event()
    background_tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]

    shutdown_event.set()
    await asyncio.wait_for(
        run_until_shutdown(app, subscriptions, shutdown_event, background_tasks),
        timeout=2,
    )

    assert all(task.cancelled() for task in background_tasks)

    # confirm unsubscribed: publishing no longer reaches the orchestrator
    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    assert app.backend.calls == []


# --- elevation check -------------------------------------------------------


def test_is_elevated_returns_a_bool():
    assert isinstance(is_elevated(), bool)


# --- ResponseComplete ordering (review finding) -----------------------------


async def test_on_full_response_complete_plays_listening_only_after_trailing_speech():
    """Regression test for a real bug: an earlier version subscribed
    tts_output, orchestrator, and a "replay listening cue" closure
    separately to ResponseComplete. bus.py delivers same-event subscribers
    concurrently (asyncio.gather), so the listening cue could play before
    a trailing sentence (scheduled by on_response_complete, without
    final punctuation) had even started, let alone finished, playing.
    _on_full_response_complete does all of this in one coroutine instead;
    this test simulates a delayed trailing-speech task and asserts the
    listening cue is provably last.
    """
    events: list[str] = []

    class _FakeTts:
        def __init__(self) -> None:
            self._task: asyncio.Task | None = None

        async def on_response_complete(self, event) -> None:
            events.append("trailing_sentence_scheduled")
            self._task = asyncio.create_task(self._delayed_finish())

        async def _delayed_finish(self) -> None:
            await asyncio.sleep(0)  # yield once, like real synthesis would
            events.append("trailing_speech_finished")

        async def wait_for_pending(self) -> None:
            if self._task is not None:
                await self._task

    class _FakeOrchestrator:
        async def on_response_complete(self, event) -> None:
            events.append("history_recorded")

        async def finish_turn(self, cooldown_seconds: float = 0.0) -> None:
            events.append("busy_cleared")

    class _FakeSoundCuesForOrdering:
        async def play(self, cue: str) -> None:
            events.append(f"cue:{cue}")

    app = App(
        bus=EventBus(),
        backend=None,
        audio_input=None,
        tts_output=_FakeTts(),
        capture_input=None,
        orchestrator=_FakeOrchestrator(),
        sound_cues=_FakeSoundCuesForOrdering(),
        settings=_settings(),
    )

    await _on_full_response_complete(app, _complete_event())

    assert events == [
        "trailing_sentence_scheduled",
        "history_recorded",
        "trailing_speech_finished",
        "busy_cleared",
        "cue:listening",
    ]


async def test_on_full_response_complete_clears_busy_and_plays_error_when_tts_fails():
    """Regression test for a real bug: without try/finally around the
    finish sequence, an exception from tts_output.on_response_complete()
    or wait_for_pending() (model/cache/audio-device failure) skipped
    orchestrator.finish_turn() entirely. Since bus.py only logs a
    subscriber's exception (it does not retry or restart the handler),
    the orchestrator stayed permanently busy - every later utterance
    ignored as "previous request still in flight" forever, wedging the
    whole process on a single failed turn."""
    orchestrator, backend, sound_cues = _orchestrator()

    class _FailingTts:
        async def on_response_complete(self, event) -> None:
            pass

        async def wait_for_pending(self) -> None:
            raise RuntimeError("audio device failure")

    app = App(
        bus=EventBus(),
        backend=backend,
        audio_input=None,
        tts_output=_FailingTts(),
        capture_input=None,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        # negligible cooldown - keeps this test fast; the real default
        # (2.0 s) is exercised by design, not by this test's timing
        settings=Settings(vad=VadSettings(request_end_pause_seconds=0.001)),
    )

    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1))
    await _on_full_response_complete(app, _complete_event())

    assert sound_cues.played[-1] == "error"

    # busy was cleared despite the failure - a subsequent utterance is not ignored
    await orchestrator.on_utterance(UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1))
    assert len(backend.calls) == 2


# --- shared playback lock (prevents device-contention crackling) -----------


def test_build_app_shares_one_playback_lock_between_tts_and_sound_cues():
    app = build_app(_settings(), backend=_FakeBackend())

    assert app.tts_output._playback_lock is app.sound_cues._playback_lock


async def test_shared_playback_lock_prevents_overlapping_device_access(tmp_path, monkeypatch):
    """Exercises the real TtsOutput._default_play and
    SoundCuePlayer._default_play_file with sounddevice/soundfile mocked
    out, sharing one lock - asserts the underlying device is never
    accessed by both at once, which is what caused the audible
    crackling/tempo artifacts reported live."""
    import sound_cues as sound_cues_module
    import tts as tts_module
    from config import SoundCueSettings, TtsSettings
    from tts import TtsOutput

    currently_playing = False

    def fake_play(_data, _sample_rate) -> None:
        nonlocal currently_playing
        assert not currently_playing, "overlapping device access detected"
        currently_playing = True

    def fake_wait() -> None:
        nonlocal currently_playing
        import time

        time.sleep(0.02)
        currently_playing = False

    monkeypatch.setattr(tts_module.sd, "play", fake_play)
    monkeypatch.setattr(tts_module.sd, "wait", fake_wait)
    monkeypatch.setattr(tts_module.sf, "read", lambda *a, **k: (b"samples", 48000))
    monkeypatch.setattr(sound_cues_module.sf, "read", lambda *a, **k: (b"samples", 22050))

    cue_path = tmp_path / "thinking.wav"
    cue_path.write_bytes(b"dummy")

    lock = asyncio.Lock()
    tts_output = TtsOutput(TtsSettings(), playback_lock=lock)
    sound_cues = SoundCuePlayer(
        SoundCueSettings(thinking=str(cue_path)), playback_lock=lock
    )

    await asyncio.gather(
        tts_output._default_play(b"wav-bytes-placeholder"),
        sound_cues._default_play_file(str(cue_path)),
    )
