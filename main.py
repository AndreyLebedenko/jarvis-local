"""Process entry point and module wiring."""

import asyncio
import argparse
import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass

from audio_in import (
    AudioInput,
    MicSleepToggled,
    UtteranceChunk,
    VadChunker,
    stream_factory_for_device,
)
from audio_in import run_hotkey_listener as run_mic_sleep_hotkey_listener
from jarvis.core.bus import EventBus
from jarvis.core.config import PromptSettings, Settings, load_settings
from jarvis.core.system_log import publish_system_event
from jarvis.dialog.backend import OllamaBackend, ResponseComplete, ResponseToken
from jarvis.dialog.thinking_mode import ThinkingModeState, ThinkingModeToggled
from jarvis.dialog.thinking_mode import run_hotkey_listener as run_thinking_hotkey_listener
from capture import CaptureEngine, CaptureInput, ScreenshotCaptured
from capture import run_hotkey_listener as run_capture_hotkey_listener
from clipboard_input import ClipboardSubmitted
from clipboard_input import run_hotkey_listener as run_clipboard_hotkey_listener
from hotkey_provider import HotkeyProvider, WindowsHotkeyProvider
from sound_cues import SoundCuePlayer, ensure_generated
from status_console import (
    StatusConsoleApi,
    StatusConsoleWindow,
    TouchstripWindow,
)
from tts import TtsOutput
from ui_contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
)
from ui_text import ui_text
from ui_transport import UiStateStore, UiTransportInfo, UiTransportServer
from visibility_mode import VisibilityModeState

logger = logging.getLogger(__name__)

# Dialog prompts live in config.py's PromptSettings ([prompts] section,
# task-v1.2.12-external-prompt-config.md); this alias keeps the historical
# name for the built-in default.
SYSTEM_PROMPT = PromptSettings().system


@dataclass(frozen=True)
class Turn:
    role: str
    text: str
    media_b64: tuple[str, ...] = ()  # always empty in v1.0 - see module docstring


class ConversationHistory:
    """Text-first history with optional media fields for future retention."""

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

    def clear(self) -> None:
        """Drops recorded conversation turns."""
        self._turns = []


VOICE_PLACEHOLDER_TEXT = "[голосовое сообщение]"


class Orchestrator:
    """Owns per-turn orchestration across input, backend, history, and cues."""

    def __init__(
        self,
        backend: OllamaBackend,
        history: ConversationHistory,
        sound_cues: SoundCuePlayer,
        system_prompt: str = SYSTEM_PROMPT,
        audio_input: AudioInput | None = None,
        thinking_mode: ThinkingModeState | None = None,
    ) -> None:
        self._backend = backend
        self._history = history
        self._sound_cues = sound_cues
        self._system_prompt = system_prompt
        self._audio_input = audio_input
        self._thinking_mode = thinking_mode
        self._pending_screenshot_b64: str | None = None
        self._response_tokens: list[str] = []
        self._spoke_this_turn = False
        self._busy = False
        self._current_turn_history_text: str = VOICE_PLACEHOLDER_TEXT

    @property
    def is_busy(self) -> bool:
        return self._busy

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
        # Sampled here, synchronously, with no `await` before it reaches
        # backend.chat()'s argument list: a hotkey toggle that lands while
        # this turn's request is already in flight cannot retroactively
        # change what was already passed - see thinking_mode.py and the
        # story's "sampled at turn start, not the live stream" decision.
        thinking_enabled = self._thinking_mode.is_enabled if self._thinking_mode else False
        try:
            await self._backend.chat(
                messages, images_b64=media_b64, thinking_enabled=thinking_enabled
            )
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
        """Clears the busy flag, optionally after a cooldown, and resumes
        the mic from its auto-pause (see on_response_token()).

        Historical note: the cooldown originally had to mirror
        vad.request_end_pause_seconds (2.0 s), because audio_in.py's
        buffer kept whatever the mic heard while Jarvis was speaking, and
        only the busy-guard stopped a self-heard tail from being answered.
        Since the stale-buffer-replay fix (see
        tasks/bug_reports/stale-audio-buffer-replay-after-mic-stall.md),
        entering auto-pause stops the stream and invalidates the buffer,
        so nothing heard during a turn can be published after resume. The
        cooldown is now just a short grace period before capture resumes,
        configurable as vad.resume_cooldown_seconds (default 1.0 s).
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
    thinking_mode: ThinkingModeState
    settings: Settings
    visibility_mode: VisibilityModeState | None = None
    history: ConversationHistory | None = None


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
    audio_input = audio_input or AudioInput(
        bus,
        VadChunker(settings.vad),
        stream_factory=stream_factory_for_device(settings.microphone.device),
    )
    # Shared so a sound cue and a spoken sentence can never physically
    # overlap on the output device - see tts.py/sound_cues.py docstrings
    # for why (sounddevice's play()/wait() share one implicit stream per
    # process; concurrent calls stop/replace each other, not mix).
    playback_lock = asyncio.Lock()
    tts_output = tts_output or TtsOutput(settings.tts, playback_lock=playback_lock)
    capture_input = capture_input or CaptureInput(bus, CaptureEngine())
    sound_cues = SoundCuePlayer(settings.sound_cues, playback_lock=playback_lock)
    thinking_mode = ThinkingModeState(bus)
    visibility_mode = VisibilityModeState(bus)
    history = ConversationHistory()
    orchestrator = Orchestrator(
        backend,
        history,
        sound_cues,
        system_prompt=settings.prompts.system,
        audio_input=audio_input,
        thinking_mode=thinking_mode,
    )
    return App(
        bus=bus,
        backend=backend,
        audio_input=audio_input,
        tts_output=tts_output,
        capture_input=capture_input,
        orchestrator=orchestrator,
        sound_cues=sound_cues,
        thinking_mode=thinking_mode,
        visibility_mode=visibility_mode,
        history=history,
        settings=settings,
    )


Subscription = tuple[type, Callable]


@dataclass
class LiveStatusConsole:
    console: StatusConsoleWindow
    touchstrip: TouchstripWindow | None
    api: StatusConsoleApi
    transport: UiTransportServer | None = None

    def create_windows(self) -> None:
        self.console.create(on_closed=self.api.request_shutdown)
        if self.touchstrip is not None:
            self.touchstrip.create()

    def load_transport_urls(self, transport_info: UiTransportInfo) -> None:
        self.console.load_url(transport_info.url)
        if self.touchstrip is not None:
            self.touchstrip.load_url(transport_info.touchstrip_url)

    def close(self) -> None:
        surfaces: list[StatusConsoleWindow] = [self.console]
        if self.touchstrip is not None:
            surfaces.append(self.touchstrip)
        for surface in reversed(surfaces):
            surface.close()


def _push_runtime_state(
    live_console: LiveStatusConsole, state: RuntimeState, substatus: str | None = None
) -> None:
    if live_console.transport is None:
        return
    live_console.transport.set_runtime_state(state, substatus)


def _microphone_health(is_awake: bool, language: str) -> ModuleHealth:
    return ModuleHealth(
        module=ModuleId.MICROPHONE,
        status=HealthStatus.OK if is_awake else HealthStatus.UNAVAILABLE,
        detail=ui_text(
            "mic_detail_listening" if is_awake else "mic_detail_muted", language
        ),
    )


def create_live_status_console(
    app: App,
    *,
    include_touchstrip: bool = True,
    console: StatusConsoleWindow | None = None,
    touchstrip: TouchstripWindow | None = None,
) -> LiveStatusConsole:
    if app.visibility_mode is None or app.history is None:
        raise RuntimeError("live Status Console requires an App created by build_app()")
    api = StatusConsoleApi(
        thinking_mode=app.thinking_mode,
        history=app.history,
        bus=app.bus,
        logger=logger,
        visibility_mode=app.visibility_mode,
        settings=app.settings,
    )
    console = console or StatusConsoleWindow()
    if include_touchstrip:
        touchstrip = touchstrip or TouchstripWindow()
    else:
        touchstrip = None
    live_console = LiveStatusConsole(console=console, touchstrip=touchstrip, api=api)
    return live_console


def wire_status_console(
    app: App,
    live_console: LiveStatusConsole,
    loop: asyncio.AbstractEventLoop,
) -> list[Subscription]:
    """Seeds the transport snapshot from authoritative engine state."""
    live_console.api.set_loop(loop)
    if app.visibility_mode is None or live_console.transport is None:
        raise RuntimeError("live Status Console requires an App created by build_app()")
    live_console.transport.set_model_label(app.settings.backend.model)
    live_console.transport.set_data_locality(DataLocality.LOCAL)
    live_console.transport.set_thinking_mode(app.thinking_mode.is_enabled)
    live_console.transport.set_visibility_mode(app.visibility_mode.mode)
    live_console.transport.set_module_health(
        _microphone_health(app.audio_input.is_awake, app.settings.ui.language)
    )
    _push_runtime_state(
        live_console,
        RuntimeState.WARMING,
        ui_text("warming_model", app.settings.ui.language),
    )
    return []


async def _on_full_response_complete(app: App, event: ResponseComplete) -> None:
    """Finishes a response in the order required by the audio pipeline."""
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
            cooldown_seconds=app.settings.vad.resume_cooldown_seconds
        )
    await app.sound_cues.play("listening")


async def _on_mic_sleep_toggled(app: App, event: MicSleepToggled) -> None:
    """Publishes UI/log feedback and plays the sleep/wake cue."""
    awake = event.is_awake
    await publish_system_event(
        app.bus,
        logger,
        source="HOTKEY",
        level=EventLevel.INFO,
        log_message=f"Microphone {'awake' if awake else 'asleep'}",
        ui_message=ui_text(
            "mic_awake" if awake else "mic_asleep", app.settings.ui.language
        ),
    )
    await app.sound_cues.play("mic_wake" if awake else "mic_sleep")


async def _on_thinking_mode_toggled(app: App, event: ThinkingModeToggled) -> None:
    """Publishes UI/log feedback and plays the thinking-mode cue."""
    enabled = event.is_enabled
    await publish_system_event(
        app.bus,
        logger,
        source="HOTKEY",
        level=EventLevel.INFO,
        log_message=f"Thinking mode {'enabled' if enabled else 'disabled'}",
        ui_message=ui_text(
            "thinking_enabled" if enabled else "thinking_disabled",
            app.settings.ui.language,
        ),
    )
    await app.sound_cues.play("thinking_on" if enabled else "thinking_off")


def wire(app: App, live_console: LiveStatusConsole | None = None) -> list[Subscription]:
    """Subscribes every module to the bus events it consumes. Returns the
    (event_type, handler) pairs so shutdown can unsubscribe them - see
    unwire()."""

    async def on_full_response_complete(event: ResponseComplete) -> None:
        await _on_full_response_complete(app, event)
        if live_console is not None:
            _push_runtime_state(
                live_console,
                RuntimeState.LISTENING,
                ui_text("ready_to_listen", app.settings.ui.language),
            )

    async def on_mic_sleep_toggled(event: MicSleepToggled) -> None:
        await _on_mic_sleep_toggled(app, event)

    async def on_thinking_mode_toggled(event: ThinkingModeToggled) -> None:
        await _on_thinking_mode_toggled(app, event)

    async def on_utterance(event: UtteranceChunk) -> None:
        if live_console is not None and not app.orchestrator.is_busy:
            _push_runtime_state(
                live_console,
                RuntimeState.THINKING,
                ui_text("processing_voice", app.settings.ui.language),
            )
        await app.orchestrator.on_utterance(event)

    async def on_clipboard(event: ClipboardSubmitted) -> None:
        if live_console is not None and not app.orchestrator.is_busy and not event.is_empty:
            _push_runtime_state(
                live_console,
                RuntimeState.THINKING,
                ui_text("processing_text", app.settings.ui.language),
            )
        await app.orchestrator.on_clipboard(event)

    utterance_handler = on_utterance if live_console is not None else app.orchestrator.on_utterance
    clipboard_handler = on_clipboard if live_console is not None else app.orchestrator.on_clipboard

    subscriptions: list[Subscription] = [
        (UtteranceChunk, utterance_handler),
        (ScreenshotCaptured, app.orchestrator.on_screenshot),
        (ClipboardSubmitted, clipboard_handler),
        (ResponseToken, app.tts_output.on_token),
        (ResponseToken, app.orchestrator.on_response_token),
        (ResponseComplete, on_full_response_complete),
        (MicSleepToggled, on_mic_sleep_toggled),
        (ThinkingModeToggled, on_thinking_mode_toggled),
    ]
    for event_type, handler in subscriptions:
        app.bus.subscribe(event_type, handler)
    return subscriptions


def unwire(app: App, subscriptions: list[Subscription]) -> None:
    for event_type, handler in subscriptions:
        app.bus.unsubscribe(event_type, handler)


async def warm_up(
    backend: OllamaBackend,
    bus: EventBus,
    ui_language: str = "en",
    warmup_prompt: str = PromptSettings().warmup,
) -> None:
    """Runs a throwaway backend request before user input is accepted.

    The warm-up prompt is dialog data configured via [prompts].warmup,
    independent of ui_language, which governs UI text only."""
    try:
        await backend.chat([{"role": "user", "content": warmup_prompt}])
    except Exception:
        logger.exception("Warm-up request failed; continuing anyway")
        await publish_system_event(
            bus,
            logger,
            source="WARMUP",
            level=EventLevel.WARN,
            log_message="Warm-up request failed; continuing anyway",
            ui_message=ui_text("warmup_failed", ui_language),
        )
    else:
        await publish_system_event(
            bus,
            logger,
            source="WARMUP",
            level=EventLevel.INFO,
            log_message="Warm-up request succeeded",
            ui_message=ui_text("warmup_succeeded", ui_language),
        )


async def run_until_shutdown(
    app: App,
    subscriptions: list[Subscription],
    shutdown_event: asyncio.Event,
    background_tasks: list[asyncio.Task],
) -> None:
    """Runs the clean shutdown sequence after shutdown_event is set."""
    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutdown: stopping microphone capture")
        # Cancelling a task awaiting a running executor future cannot stop
        # the underlying blocking read; the microphone loop needs its own
        # cooperative stop before we await all background tasks.
        await app.audio_input.stop()
        logger.info("Shutdown: cancelling %d background task(s)", len(background_tasks))
        for task in background_tasks:
            task.cancel()
        results = await asyncio.gather(*background_tasks, return_exceptions=True)
        for task, result in zip(background_tasks, results):
            if isinstance(result, Exception):
                logger.error(
                    "Shutdown: background task %s raised instead of exiting cleanly",
                    task.get_name(),
                    exc_info=result,
                )
        logger.info("Shutdown: background tasks finished, flushing pending TTS")
        await app.tts_output.wait_for_pending()
        logger.info("Shutdown: flushing pending sound cues")
        await app.sound_cues.wait_for_pending()
        logger.info("Shutdown: unwiring bus subscriptions")
        unwire(app, subscriptions)
        logger.info("Shutdown: teardown complete")


async def run(
    settings: Settings | None = None,
    app: App | None = None,
    live_console: LiveStatusConsole | None = None,
    shutdown_provider: HotkeyProvider | None = None,
) -> None:
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

    app = app or build_app(settings)
    # One shutdown signal feeds both the hotkey and the Status Console.
    shutdown_event = asyncio.Event()
    if live_console is not None:
        live_console.api.set_shutdown_event(shutdown_event)
        status_console_subscriptions = wire_status_console(
            app, live_console, asyncio.get_running_loop()
        )
    else:
        status_console_subscriptions = []
    await warm_up(
        app.backend, app.bus, settings.ui.language, settings.prompts.warmup
    )
    if live_console is not None:
        _push_runtime_state(
            live_console,
            RuntimeState.LISTENING,
            ui_text("ready_to_listen", settings.ui.language),
        )
    subscriptions = [*status_console_subscriptions, *wire(app, live_console)]

    loop = asyncio.get_running_loop()

    def on_shutdown_hotkey() -> None:
        loop.call_soon_threadsafe(shutdown_event.set)

    shutdown_provider = shutdown_provider or WindowsHotkeyProvider()
    shutdown_provider.register(settings.hotkeys.shutdown, on_shutdown_hotkey)
    shutdown_provider.start()

    background_tasks = [
        asyncio.create_task(app.audio_input.run_microphone_loop()),
        asyncio.create_task(run_capture_hotkey_listener(app.capture_input, settings.hotkeys)),
        asyncio.create_task(
            run_clipboard_hotkey_listener(app.bus, settings.hotkeys, settings.clipboard)
        ),
        asyncio.create_task(run_mic_sleep_hotkey_listener(app.audio_input, settings.hotkeys)),
        asyncio.create_task(run_thinking_hotkey_listener(app.thinking_mode, settings.hotkeys)),
    ]

    await app.sound_cues.play("listening")
    print("Jarvis is running. Press the shutdown hotkey or Ctrl+C to stop.")

    try:
        await run_until_shutdown(app, subscriptions, shutdown_event, background_tasks)
    finally:
        try:
            shutdown_provider.stop()
        finally:
            if live_console is not None:
                if live_console.transport is not None:
                    await live_console.transport.stop()
                live_console.close()


def run_with_status_console(
    settings: Settings | None = None, *, include_touchstrip: bool = True
) -> None:
    settings = settings or load_settings()
    app = build_app(settings)
    live_console = create_live_status_console(app, include_touchstrip=include_touchstrip)
    live_console.transport = UiTransportServer(
        app.bus,
        live_console.api,
        state=UiStateStore(
            model_label=settings.backend.model,
            thinking_enabled=app.thinking_mode.is_enabled,
            visibility_mode=app.visibility_mode.mode,
            language=settings.ui.language,
        ),
        logger=logger,
    )
    live_console.create_windows()

    def start_jarvis() -> None:
        async def start() -> None:
            if live_console.transport is None:
                raise RuntimeError("Status Console transport was not created")
            transport_info = await live_console.transport.start()
            live_console.load_transport_urls(transport_info)
            await run(settings=settings, app=app, live_console=live_console)

        asyncio.run(start())

    import webview

    webview.start(start_jarvis)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Jarvis.")
    parser.add_argument(
        "--status-console",
        action="store_true",
        help="open the local Status Console UI and run Jarvis in the same process",
    )
    parser.add_argument(
        "--no-touchstrip",
        action="store_true",
        help="with --status-console, open only the desktop console window",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.status_console:
        run_with_status_console(include_touchstrip=not args.no_touchstrip)
    else:
        asyncio.run(run())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
