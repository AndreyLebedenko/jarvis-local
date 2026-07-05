"""Process entry point: wires every module together via bus.py, authors
the system prompt, and drives sound cues for state transitions -
PROJECT.md's "hotkeys + sound cues only, no GUI" interaction model.

History (v1.0 decision, see PROJECT.md's Open questions section):
text-only. Media (audio, screenshot) is attached only to the current
turn's message, never resent in history. ConversationHistory's Turn
already carries a media_b64 field so a later release can start passing
media into history without restructuring anything here - v1.0 code
simply never populates it.

Warm-up (task-07 backlog note from task-03): a throwaway request runs
BEFORE wire() subscribes tts_output/orchestrator to the bus, so its
response tokens are published to zero subscribers (bus.py: publishing
with no subscribers is a no-op) rather than spoken aloud or recorded
into history.

Malformed stream line policy (task-07 backlog note from task-03):
backend.py's chat() lets a json.loads failure on a malformed line raise
uncaught. Resolved here, not in backend.py: Orchestrator.on_utterance's
try/except around backend.chat() already catches any such exception,
plays the error cue, and lets the process keep running - no backend.py
change needed.
"""

import asyncio
import base64
import ctypes
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from audio_in import (
    AudioInput,
    MicSleepToggled,
    UtteranceChunk,
    VadChunker,
)
from audio_in import run_hotkey_listener as run_mic_sleep_hotkey_listener
from backend import OllamaBackend, ResponseComplete, ResponseToken
from bus import EventBus
from capture import CaptureEngine, CaptureInput, ScreenshotCaptured
from capture import run_hotkey_listener as run_capture_hotkey_listener
from clipboard_input import ClipboardSubmitted
from clipboard_input import run_hotkey_listener as run_clipboard_hotkey_listener
from config import Settings, load_settings
from sound_cues import SoundCuePlayer, ensure_generated
from tts import TtsOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты - Джарвис, локальный голосовой ассистент пользователя. Отвечай "
    "по-русски, если пользователь явно не попросил другой язык. Отвечай "
    "коротко и по существу: одно-два предложения, если не попросили "
    "подробностей - чем длиннее ответ, тем дольше пользователь ждёт, пока "
    "он прозвучит. Если вместе с голосовым сообщением пришёл скриншот "
    "экрана пользователя, отвечай с учётом того, что на нём видно."
)


def is_elevated() -> bool:
    """Windows-only: True if the process has Administrator privileges.
    Global hotkeys (capture.py, the shutdown hotkey here) only work
    system-wide when elevated - verified live, see PROJECT.md's Verified
    facts. Not elevated is not fatal; hotkeys just degrade to only firing
    while this process's own window has focus.
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


@dataclass(frozen=True)
class Turn:
    role: str
    text: str
    media_b64: tuple[str, ...] = ()  # always empty in v1.0 - see module docstring


class ConversationHistory:
    """Text-only for v1.0. Turn already carries media_b64 so a later
    release can extend this without restructuring anything - see module
    docstring."""

    def __init__(self) -> None:
        self._turns: list[Turn] = []

    def add(self, role: str, text: str, media_b64: tuple[str, ...] = ()) -> None:
        self._turns.append(Turn(role=role, text=text, media_b64=media_b64))

    def as_messages(self) -> list[dict[str, object]]:
        messages = []
        for turn in self._turns:
            message: dict[str, object] = {"role": turn.role, "content": turn.text}
            if turn.media_b64:
                message["images"] = list(turn.media_b64)
            messages.append(message)
        return messages


VOICE_PLACEHOLDER_TEXT = "[голосовое сообщение]"


class Orchestrator:
    """Owns the per-turn state machine: correlates the latest screenshot
    with the next utterance, calls backend.chat(), builds history, and
    drives the thinking/speaking/error sound cues (listening is driven
    separately, once TTS finishes speaking - see wire()).

    _start_turn() is the one shared turn-start path (busy-guard, thinking
    cue, message assembly, backend.chat(), error handling) used by every
    kind of user turn. on_utterance() and on_clipboard() are thin adapters
    onto it (task-08): audio turns attach wav+pending-screenshot media and
    a fixed history placeholder (no transcript exists in v1.0); clipboard
    turns attach the real submitted text and no media at all. Duplicating
    this logic per input source instead of sharing it is exactly the kind
    of split that caused the ResponseComplete concurrency bugs found
    during task-07's review - it must not happen again for the same
    reason.

    Echo mitigation (task-10, layered on top of finish_turn()'s existing
    busy-cooldown - see PROJECT.md's Verified facts): if audio_input is
    given, audio_input.auto_pause_for_speech()/auto_resume_after_speech()
    are called unconditionally around this turn's speech (first response
    token through finish_turn()'s cooldown). Unlike an earlier version of
    this feature, this class no longer has to track whether it "owns" the
    pause to avoid overriding a user privacy sleep - that composition
    (user-requested sleep vs this internal auto-pause, ANDed into the
    actual capture state) now lives in AudioInput itself, which is the
    right owner of its own state (see its module docstring for the bug
    this fixed: a single is_awake bit could not represent both facts
    independently, so a hotkey press during this auto-pause could wake
    the mic against the user's actual intent).
    """

    def __init__(
        self,
        backend: OllamaBackend,
        history: ConversationHistory,
        sound_cues: SoundCuePlayer,
        system_prompt: str = SYSTEM_PROMPT,
        audio_input: AudioInput | None = None,
    ) -> None:
        self._backend = backend
        self._history = history
        self._sound_cues = sound_cues
        self._system_prompt = system_prompt
        self._audio_input = audio_input
        self._pending_screenshot_b64: str | None = None
        self._response_tokens: list[str] = []
        self._spoke_this_turn = False
        self._busy = False
        self._current_turn_history_text: str = VOICE_PLACEHOLDER_TEXT

    async def on_screenshot(self, event: ScreenshotCaptured) -> None:
        self._pending_screenshot_b64 = base64.b64encode(event.png_bytes).decode()

    async def on_utterance(self, event: UtteranceChunk) -> None:
        if self._busy:
            logger.info("Ignoring utterance: previous request still in flight")
            return
        # Must check busy before touching _pending_screenshot_b64: consuming
        # it here and then having _start_turn() reject the turn would lose
        # a screenshot that was meant for the next *accepted* turn.
        media = [base64.b64encode(event.wav_bytes).decode()]
        if self._pending_screenshot_b64 is not None:
            media.append(self._pending_screenshot_b64)
            self._pending_screenshot_b64 = None
        await self._start_turn(VOICE_PLACEHOLDER_TEXT, media)

    async def on_clipboard(self, event: ClipboardSubmitted) -> None:
        if event.is_empty:
            # Not turn-state-dependent: there is nothing to submit either
            # way, so this plays regardless of busy.
            await self._sound_cues.play("input_error")
            return
        if self._busy:
            logger.info("Ignoring clipboard submission: previous request still in flight")
            return
        # Must check busy before playing the ack/warning cue: playing it
        # and then having _start_turn() silently reject the turn would
        # tell the user their input was received when it was not.
        await self._sound_cues.play("input_error" if event.truncated else "clipboard")
        await self._start_turn(event.text, None)

    async def _start_turn(
        self, history_text: str, media_b64: list[str] | None
    ) -> None:
        # Defensive re-check: on_utterance()/on_clipboard() already gate on
        # busy before doing their own turn-specific setup above, with no
        # `await` in between - so this can only fire for a caller that
        # forgets to pre-check, not for the two above in normal operation.
        if self._busy:
            logger.info("Ignoring new turn: previous request still in flight")
            return
        self._busy = True
        await self._sound_cues.play("thinking")

        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(self._history.as_messages())
        messages.append({"role": "user", "content": history_text})

        self._current_turn_history_text = history_text
        self._response_tokens = []
        self._spoke_this_turn = False
        try:
            await self._backend.chat(messages, images_b64=media_b64)
        except Exception:
            logger.exception("Request failed")
            await self._sound_cues.play("error")
            self._busy = False

    async def on_response_token(self, event: ResponseToken) -> None:
        self._response_tokens.append(event.text)
        if not self._spoke_this_turn:
            self._spoke_this_turn = True
            await self._sound_cues.play("speaking")
            if self._audio_input is not None:
                await self._audio_input.auto_pause_for_speech()

    async def on_response_complete(self, event: ResponseComplete) -> None:
        """Records this turn's history. Does not clear the busy flag -
        see finish_turn(), which must run only once all of this turn's
        speech has actually finished playing (see wire()'s
        on_full_response_complete)."""
        full_text = "".join(self._response_tokens)
        self._history.add("user", self._current_turn_history_text)
        self._history.add("assistant", full_text)

    async def finish_turn(self, cooldown_seconds: float = 0.0) -> None:
        """Clears the busy flag, optionally after a cooldown.

        Verified live: after Jarvis stops speaking, audio_in.py's own
        VAD/merge pipeline has been continuously buffering the whole
        time it was talking (it has no notion of "busy" at all - it
        just watches the microphone). If the mic picks up Jarvis's own
        voice from the speakers (no echo cancellation - not attempted in
        v1.0), audio_in.py needs its own request_end_pause_seconds of
        silence after Jarvis stops before it decides that "utterance" is
        finished and publishes it. If busy had already cleared by then
        (which it does almost immediately once wait_for_pending()
        returns), that self-heard chunk is accepted as a genuine new
        utterance and answered - the process is talking to itself. The
        cooldown keeps busy True for roughly as long as audio_in.py's own
        confirmation delay, so that self-heard tail is rejected by the
        same busy-guard that already ignores utterances mid-turn, rather
        than needing echo cancellation or a cross-module mute signal
        into audio_in.py.

        Task-10 layers a second mitigation on top: the mic is resumed
        from its auto-pause (see on_response_token()) here, after the
        same cooldown - see this class's docstring for why this no
        longer needs to track whether it "owns" the pause.
        """
        if cooldown_seconds > 0:
            await asyncio.sleep(cooldown_seconds)
        if self._audio_input is not None:
            await self._audio_input.auto_resume_after_speech()
        self._busy = False


@dataclass
class App:
    bus: EventBus
    backend: OllamaBackend
    audio_input: AudioInput
    tts_output: TtsOutput
    capture_input: CaptureInput
    orchestrator: Orchestrator
    sound_cues: SoundCuePlayer
    settings: Settings


def build_app(
    settings: Settings,
    bus: EventBus | None = None,
    backend: OllamaBackend | None = None,
    audio_input: AudioInput | None = None,
    tts_output: TtsOutput | None = None,
    capture_input: CaptureInput | None = None,
) -> App:
    """Constructs every module. Does not subscribe anything to the bus -
    see wire(). Hardware-touching modules (audio_input, tts_output,
    capture_input) are injectable so tests can substitute fakes."""
    bus = bus or EventBus()
    backend = backend or OllamaBackend(bus, settings.backend)
    audio_input = audio_input or AudioInput(bus, VadChunker(settings.vad))
    # Shared so a sound cue and a spoken sentence can never physically
    # overlap on the output device - see tts.py/sound_cues.py docstrings
    # for why (sounddevice's play()/wait() share one implicit stream per
    # process; concurrent calls stop/replace each other, not mix).
    playback_lock = asyncio.Lock()
    tts_output = tts_output or TtsOutput(settings.tts, playback_lock=playback_lock)
    capture_input = capture_input or CaptureInput(bus, CaptureEngine())
    sound_cues = SoundCuePlayer(settings.sound_cues, playback_lock=playback_lock)
    orchestrator = Orchestrator(backend, ConversationHistory(), sound_cues, audio_input=audio_input)
    return App(
        bus=bus,
        backend=backend,
        audio_input=audio_input,
        tts_output=tts_output,
        capture_input=capture_input,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        settings=settings,
    )


Subscription = tuple[type, Callable]


async def _on_full_response_complete(app: App, event: ResponseComplete) -> None:
    """The single handler for ResponseComplete - deliberately NOT split
    across separate concurrent bus subscribers (bus.py delivers
    subscribers of the same event via asyncio.gather, concurrently, not
    in sequence). An earlier version subscribed tts_output, orchestrator,
    and a "replay listening cue" closure separately to ResponseComplete;
    that let the listening cue play before the flushed trailing sentence
    had actually finished (or even started) playing - and, worse, let a
    new turn's "thinking" cue start while the previous turn's trailing
    speech was still on the speaker, corrupting playback (verified live:
    audible crackling/tempo artifacts from two sd.play() calls landing on
    the shared device at once). Doing all four steps in order, in one
    coroutine, makes both bugs structurally impossible.

    finish_turn() runs in a finally block: if flushing the trailing
    sentence or waiting for pending speech raises (model/cache/audio-
    device failure), the busy flag must still clear - otherwise every
    later utterance is ignored as "previous request still in flight"
    forever, wedging the process on a single failed turn (exactly what
    task-07's top-level error handling requirement rules out; bus.py
    only logs a subscriber's exception, it does not restart or retry
    this handler).

    finish_turn() also gets a cooldown equal to
    config.vad.request_end_pause_seconds - see its docstring for why:
    audio_in.py can still be sitting on a self-heard "utterance"
    (Jarvis's own voice, picked up by the mic with no echo cancellation)
    for up to that long after Jarvis stops talking.
    """
    try:
        await app.tts_output.on_response_complete(event)  # flushes trailing sentence
        await app.orchestrator.on_response_complete(event)  # records history
        await app.tts_output.wait_for_pending()  # waits for ALL of this turn's speech
    except Exception:
        logger.exception("Response completion failed")
        await app.sound_cues.play("error")
        return
    finally:
        await app.orchestrator.finish_turn(
            cooldown_seconds=app.settings.vad.request_end_pause_seconds
        )
    await app.sound_cues.play("listening")


async def _on_mic_sleep_toggled(app: App, event: MicSleepToggled) -> None:
    """Plays the sleep/wake sound cue - the only feedback for this
    privacy toggle, per the "hotkeys + sound cues only" interaction
    model. Mirrors _on_full_response_complete's split: audio_in.py only
    publishes what happened, main.py decides what to do about it."""
    logger.info("Microphone %s", "awake" if event.is_awake else "asleep")
    await app.sound_cues.play("mic_wake" if event.is_awake else "mic_sleep")


def wire(app: App) -> list[Subscription]:
    """Subscribes every module to the bus events it consumes. Returns the
    (event_type, handler) pairs so shutdown can unsubscribe them - see
    unwire()."""

    async def on_full_response_complete(event: ResponseComplete) -> None:
        await _on_full_response_complete(app, event)

    async def on_mic_sleep_toggled(event: MicSleepToggled) -> None:
        await _on_mic_sleep_toggled(app, event)

    subscriptions: list[Subscription] = [
        (UtteranceChunk, app.orchestrator.on_utterance),
        (ScreenshotCaptured, app.orchestrator.on_screenshot),
        (ClipboardSubmitted, app.orchestrator.on_clipboard),
        (ResponseToken, app.tts_output.on_token),
        (ResponseToken, app.orchestrator.on_response_token),
        (ResponseComplete, on_full_response_complete),
        (MicSleepToggled, on_mic_sleep_toggled),
    ]
    for event_type, handler in subscriptions:
        app.bus.subscribe(event_type, handler)
    return subscriptions


def unwire(app: App, subscriptions: list[Subscription]) -> None:
    for event_type, handler in subscriptions:
        app.bus.unsubscribe(event_type, handler)


async def warm_up(backend: OllamaBackend) -> None:
    """Fires a throwaway request before the process signals it is ready
    to listen, so the first real user turn doesn't pay Ollama's cold-load
    penalty (measured 4.2 s vs 0.3 s warm - task-07 backlog note from
    task-03). Must run before wire() - see module docstring.
    """
    try:
        await backend.chat([{"role": "user", "content": "Привет"}])
    except Exception:
        logger.exception("Warm-up request failed; continuing anyway")


async def run_until_shutdown(
    app: App,
    subscriptions: list[Subscription],
    shutdown_event: asyncio.Event,
    background_tasks: list[asyncio.Task],
) -> None:
    """Waits for shutdown_event, then cancels background_tasks, lets any
    in-flight speech finish, and unsubscribes everything. Testable in
    isolation with fake background tasks instead of real mic/hotkey
    hardware."""
    try:
        await shutdown_event.wait()
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await app.tts_output.wait_for_pending()
        await app.sound_cues.wait_for_pending()
        unwire(app, subscriptions)


async def run(settings: Settings | None = None) -> None:
    # No logging was configured anywhere in the process before this (verified:
    # grep found no basicConfig/setLevel calls), so every existing INFO-level
    # log call (e.g. the busy-guard "ignoring ..." messages) was silently
    # dropped - Python's logging module only auto-prints WARNING+ without
    # configuration. Human-reported during task-10 manual testing: sound cue
    # playback for input_error seemed to not fire, with no way to confirm
    # from the console whether it was even attempted. INFO with a timestamp
    # makes every such internal event observable without re-instrumenting
    # each one at WARNING level, which would misrepresent normal events as
    # warnings.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = settings or load_settings()
    ensure_generated(settings.sound_cues)

    if not is_elevated():
        print(
            "WARNING: not running as Administrator - global hotkeys will "
            "only work while this window has focus, not from other "
            "applications. See PROJECT.md's Verified facts."
        )

    app = build_app(settings)
    await warm_up(app.backend)
    subscriptions = wire(app)

    import keyboard

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_shutdown_hotkey() -> None:
        loop.call_soon_threadsafe(shutdown_event.set)

    shutdown_handle = keyboard.add_hotkey(settings.hotkeys.shutdown, on_shutdown_hotkey)

    background_tasks = [
        asyncio.create_task(app.audio_input.run_microphone_loop()),
        asyncio.create_task(run_capture_hotkey_listener(app.capture_input, settings.hotkeys)),
        asyncio.create_task(
            run_clipboard_hotkey_listener(app.bus, settings.hotkeys, settings.clipboard)
        ),
        asyncio.create_task(run_mic_sleep_hotkey_listener(app.audio_input, settings.hotkeys)),
    ]

    await app.sound_cues.play("listening")
    print("Jarvis is running. Press the shutdown hotkey or Ctrl+C to stop.")

    try:
        await run_until_shutdown(app, subscriptions, shutdown_event, background_tasks)
    finally:
        keyboard.remove_hotkey(shutdown_handle)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
