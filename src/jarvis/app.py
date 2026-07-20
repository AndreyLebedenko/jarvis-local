"""Process entry point and module wiring."""

import argparse
import asyncio
import base64
import concurrent.futures
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.audio.input import (
    AudioInput,
    MicSleepToggled,
    UtteranceChunk,
    VadChunker,
    stream_factory_for_device,
)
from jarvis.audio.input import run_hotkey_listener as run_mic_sleep_hotkey_listener
from jarvis.audio.sound_cues import SoundCuePlayer, ensure_generated
from jarvis.audio.tts import TtsOutput
from jarvis.audio.tts_factory import build_tts_engine
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BUILTIN_TOOL_PROVIDER_NAME,
    PromptSettings,
    Settings,
    load_settings,
)
from jarvis.core.lifecycle import (
    VOICE_PLACEHOLDER_TEXT,
    AttachmentSubmissionReason,
    AttachmentSubmissionResult,
    BackendRequestFailed,
    ModelRequestInput,
    ModelRequestStarted,
    NewContextReason,
    NewContextResult,
    TextSubmissionReason,
    TextSubmissionResult,
    TurnAccepted,
    TurnCompleted,
    TurnSource,
    WarmupCompleted,
    WarmupStarted,
)
from jarvis.core.system_log import publish_system_event
from jarvis.dialog.backend import OllamaBackend, ResponseComplete, ResponseToken
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
)
from jarvis.dialog.thinking_mode import (
    run_hotkey_listener as run_thinking_hotkey_listener,
)
from jarvis.dialog.time_context import format_time_context
from jarvis.dialog.tool_presentation import ToolAwareDialog, build_tool_presentation
from jarvis.inputs.attachment_audio import (
    compose_audio_cue,
    compose_audio_media,
    normalize_audio_attachment,
)
from jarvis.inputs.attachments import (
    AttachmentPlan,
    compose_turn_images,
    compose_turn_text,
)
from jarvis.inputs.camera import (
    CameraCapture,
    CameraCaptureFailed,
    CameraCaptureSucceeded,
    CameraState,
)
from jarvis.inputs.capture import CaptureEngine, CaptureInput, ScreenshotCaptured
from jarvis.inputs.capture import run_hotkey_listener as run_capture_hotkey_listener
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.inputs.clipboard import run_hotkey_listener as run_clipboard_hotkey_listener
from jarvis.inputs.hotkeys import HotkeyProvider, WindowsHotkeyProvider
from jarvis.journal.events import parse_journal_timestamp
from jarvis.journal.fork import (
    ForkSeedOversizeTurnError,
    ForkSessionReason,
    ForkSessionResult,
    build_fork_seed,
)
from jarvis.journal.recorder import JournalRecorder
from jarvis.journal.search import JournalSearchIndex
from jarvis.journal.store import JournalReplay, JournalStore
from jarvis.memory.files import (
    MemoryFileLoader,
    MemoryFileRepository,
    build_memory_file_specs,
)
from jarvis.tools.builtin import CAMERA_TOOL_NAME, BuiltinToolProvider
from jarvis.tools.host import McpHost, McpModuleStatusChanged
from jarvis.tools.registry import ToolRegistry
from jarvis.ui.contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
)
from jarvis.ui.module_health import ModuleHealthTracker
from jarvis.ui.runtime_state import RuntimeStateChanged, RuntimeStateTracker
from jarvis.ui.status_console import (
    StatusConsoleApi,
    StatusConsoleWindow,
    TouchstripWindow,
    config_values_payload,
    mcp_state_payload,
)
from jarvis.ui.text import ui_text
from jarvis.ui.transport import UiStateStore, UiTransportInfo, UiTransportServer
from jarvis.ui.visibility import VisibilityModeState

APP_LOGGER_NAME = __name__
logger = logging.getLogger(APP_LOGGER_NAME)

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


DEFAULT_TEXT_INPUT_MAX_CHARS = 20000


class Orchestrator:
    """Owns per-turn orchestration across input, backend, history, and cues."""

    def __init__(
        self,
        backend: OllamaBackend | ToolAwareDialog,
        history: ConversationHistory,
        sound_cues: SoundCuePlayer,
        system_prompt: str = SYSTEM_PROMPT,
        audio_input: AudioInput | None = None,
        thinking_mode: ReasoningLevelState | None = None,
        bus: EventBus | None = None,
        journal_recorder: JournalRecorder | None = None,
        clock: Callable[[], float] | None = None,
        text_input_max_chars: int = DEFAULT_TEXT_INPUT_MAX_CHARS,
        system_prompt_provider: Callable[[], str] | None = None,
    ) -> None:
        self._backend = backend
        self._history = history
        self._sound_cues = sound_cues
        self._system_prompt_provider = system_prompt_provider or (lambda: system_prompt)
        self._system_prompt = self._system_prompt_provider()
        self._audio_input = audio_input
        self._thinking_mode = thinking_mode
        self._bus = bus
        self._journal_recorder = journal_recorder
        self._clock = clock or time.time
        self._text_input_max_chars = text_input_max_chars
        self._pending_screenshot_b64: str | None = None
        self._pending_screenshot_png: bytes | None = None
        self._response_tokens: list[str] = []
        self._spoke_this_turn = False
        self._busy = False
        self._current_turn_history_text: str = VOICE_PLACEHOLDER_TEXT
        self._journal_turn_started = False

    @property
    def is_busy(self) -> bool:
        return self._busy

    def clear(self) -> None:
        self._history.clear()
        self._system_prompt = self._system_prompt_provider()

    async def start_new_context(self) -> NewContextResult:
        if self._busy:
            return NewContextResult(NewContextReason.BUSY)
        self.clear()
        provenance_text = _new_context_provenance_line()
        new_session_id = None
        if self._journal_recorder is not None:
            new_session_id = await self._journal_recorder.start_blank_session(
                provenance_text=provenance_text
            )
        return NewContextResult(
            NewContextReason.ACCEPTED,
            session_id=new_session_id,
            provenance_text=provenance_text,
        )

    async def on_screenshot(self, event: ScreenshotCaptured) -> None:
        self._pending_screenshot_b64 = base64.b64encode(event.png_bytes).decode()
        self._pending_screenshot_png = bytes(event.png_bytes)

    async def on_utterance(self, event: UtteranceChunk) -> None:
        if self._busy:
            logger.info("Ignoring utterance: previous request still in flight")
            return
        # Must check busy before touching _pending_screenshot_b64: consuming
        # it here and then having _start_turn() reject the turn would lose
        # a screenshot that was meant for the next *accepted* turn.
        media = [base64.b64encode(event.wav_bytes).decode()]
        has_pending_screenshot = self._pending_screenshot_b64 is not None
        screenshot_png = (
            self._pending_screenshot_png if has_pending_screenshot else None
        )
        if has_pending_screenshot:
            media.append(self._pending_screenshot_b64)
            self._pending_screenshot_b64 = None
            self._pending_screenshot_png = None
        inputs = [ModelRequestInput.AUDIO]
        if has_pending_screenshot:
            inputs.append(ModelRequestInput.SCREENSHOT)
        await self._start_turn(
            VOICE_PLACEHOLDER_TEXT,
            media,
            TurnSource.VOICE,
            inputs=tuple(inputs),
            audio_duration_seconds=event.end_seconds - event.start_seconds,
            voice_wav_bytes=event.wav_bytes,
            screenshot_png_bytes=screenshot_png,
        )

    async def on_clipboard(self, event: ClipboardSubmitted) -> None:
        if event.is_empty:
            # Not turn-state-dependent: there is nothing to submit either
            # way, so this plays regardless of busy.
            await self._sound_cues.play("input_error")
            return
        if self._busy:
            logger.info(
                "Ignoring clipboard submission: previous request still in flight"
            )
            return
        # Must check busy before playing the ack/warning cue: playing it
        # and then having _start_turn() silently reject the turn would
        # tell the user their input was received when it was not.
        await self._sound_cues.play("input_error" if event.truncated else "clipboard")
        await self._start_turn(
            event.text,
            None,
            TurnSource.TEXT,
            inputs=(ModelRequestInput.CLIPBOARD,),
            audio_duration_seconds=None,
            voice_wav_bytes=None,
            screenshot_png_bytes=None,
        )

    async def submit_text_input(self, text: str) -> TextSubmissionResult:
        if not text.strip():
            return TextSubmissionResult(
                TextSubmissionReason.EMPTY, self._text_input_max_chars
            )
        if len(text) > self._text_input_max_chars:
            return TextSubmissionResult(
                TextSubmissionReason.OVER_LIMIT, self._text_input_max_chars
            )
        if self._busy:
            logger.info(
                "Ignoring text input submission: previous request still in flight"
            )
            return TextSubmissionResult(
                TextSubmissionReason.BUSY, self._text_input_max_chars
            )
        await self._start_turn(
            text,
            None,
            TurnSource.TEXT_INPUT,
            inputs=(ModelRequestInput.TEXT_INPUT,),
            audio_duration_seconds=None,
            voice_wav_bytes=None,
            screenshot_png_bytes=None,
            journal_source="dock",
        )
        return TextSubmissionResult(
            TextSubmissionReason.ACCEPTED, self._text_input_max_chars
        )

    async def fork_from_journal_session(
        self,
        *,
        source_session_id: str,
        replay: JournalReplay,
        source_end_timestamp: str,
        seed_budget_chars: int,
    ) -> ForkSessionResult:
        if self._busy:
            return ForkSessionResult(ForkSessionReason.BUSY)
        try:
            seed = build_fork_seed(replay, seed_budget_chars)
        except ForkSeedOversizeTurnError as error:
            return ForkSessionResult(
                ForkSessionReason.OVERSIZE_TURN,
                oversize_turn_chars=error.turn_chars,
                max_chars=error.budget_chars,
            )

        provenance_text = _fork_provenance_seed_line(source_end_timestamp)
        self.clear()
        self._history.add("system", provenance_text)
        for turn in seed.turns:
            self._history.add(turn.role, turn.text)

        new_session_id = None
        if self._journal_recorder is not None:
            new_session_id = await self._journal_recorder.start_fork_session(
                source_session_id=source_session_id,
                provenance_text=provenance_text,
                seed_drop_report=seed.drop_report,
            )
        return ForkSessionResult(
            ForkSessionReason.ACCEPTED,
            new_session_id=new_session_id,
            drop_report=seed.drop_report,
            provenance_text=provenance_text,
            max_chars=seed_budget_chars,
        )

    async def on_attachment_submission(
        self, typed_text: str, plan: AttachmentPlan
    ) -> AttachmentSubmissionResult:
        """Wires an already-validated attachment plan (task-v1.6.0-2's
        plan_attachments(), handed in by the future Journal input dock
        transport - task-v1.6.0-7) into the normal turn lifecycle. Only
        accepted plan items contribute text/media; the planner already
        reported rejections to its caller, so there is nothing further to
        surface for those here.

        Audio is the one class planning does not fully resolve: it only
        header-probes duration (PendingAudioMedia), so the real decode/
        resample/chunk into model-safe clips happens here via
        normalize_audio_attachment() - which can itself reject audio that
        passed the header probe (e.g. truncated data past a valid header).
        Per the story's never-silent stance, that rejection is reported
        through the same SystemEvent/WARN channel every other recoverable
        mid-turn issue uses, rather than silently dropping the file or
        aborting the whole submission - typed text, images, and any other
        accepted attachment still reach the model.
        """
        if self._busy:
            logger.info(
                "Ignoring attachment submission: previous request still in flight"
            )
            return AttachmentSubmissionResult(AttachmentSubmissionReason.BUSY)

        media: list[str] = list(compose_turn_images(plan))
        inputs: list[ModelRequestInput] = [
            ModelRequestInput.ATTACHMENT_IMAGE for _ in media
        ]
        if any(item.accepted and item.text is not None for item in plan.items):
            inputs.append(ModelRequestInput.ATTACHMENT_TEXT)

        history_text = compose_turn_text(typed_text, plan)
        audio_duration_seconds: float | None = None
        pending_audio_item = next(
            (
                item
                for item in plan.items
                if item.accepted and item.pending_audio is not None
            ),
            None,
        )
        if pending_audio_item is not None:
            normalized = normalize_audio_attachment(
                pending_audio_item.filename, pending_audio_item.pending_audio
            )
            if normalized.accepted:
                media.extend(compose_audio_media(normalized))
                audio_cue = compose_audio_cue(normalized)
                if audio_cue is not None:
                    history_text = (
                        f"{history_text}\n\n{audio_cue}" if history_text else audio_cue
                    )
                audio_duration_seconds = normalized.duration_seconds
                inputs.append(ModelRequestInput.ATTACHMENT_AUDIO)
            elif self._bus is not None:
                reason = (
                    normalized.rejection_reason
                    or f"{pending_audio_item.filename}: audio could not be processed."
                )
                await publish_system_event(
                    self._bus,
                    logger,
                    source="ATTACHMENT",
                    level=EventLevel.WARN,
                    log_message=reason,
                    ui_message=reason,
                )

        if not history_text.strip() and not media and not inputs:
            return AttachmentSubmissionResult(
                AttachmentSubmissionReason.NO_ACCEPTED_CONTENT
            )

        await self._start_turn(
            history_text,
            media if media else None,
            TurnSource.ATTACHMENT,
            inputs=tuple(inputs),
            audio_duration_seconds=audio_duration_seconds,
            voice_wav_bytes=None,
            screenshot_png_bytes=None,
        )
        return AttachmentSubmissionResult(AttachmentSubmissionReason.ACCEPTED)

    async def _start_turn(
        self,
        history_text: str,
        media_b64: list[str] | None,
        source: TurnSource,
        *,
        inputs: tuple[ModelRequestInput, ...],
        audio_duration_seconds: float | None,
        voice_wav_bytes: bytes | None,
        screenshot_png_bytes: bytes | None,
        journal_source: str | None = None,
    ) -> None:
        # Defensive re-check: on_utterance()/on_clipboard() already gate on
        # busy before doing their own turn-specific setup above, with no
        # `await` in between - so this can only fire for a caller that
        # forgets to pre-check, not for the two above in normal operation.
        if self._busy:
            logger.info("Ignoring new turn: previous request still in flight")
            return
        self._busy = True
        self._journal_turn_started = False
        if self._journal_recorder is not None:
            if source is TurnSource.VOICE and voice_wav_bytes is not None:
                await self._journal_recorder.record_voice_user(
                    voice_wav_bytes, screenshot_png_bytes=screenshot_png_bytes
                )
                self._journal_turn_started = True
            elif source in {TurnSource.TEXT, TurnSource.TEXT_INPUT}:
                await self._journal_recorder.record_text_user(
                    history_text, source=journal_source or "text"
                )
                self._journal_turn_started = True
            elif source is TurnSource.ATTACHMENT:
                # No media reference is recorded, matching record_text_user()'s
                # existing text-only contract (only record_voice_user() ever
                # writes a journal media file) - the journal-recording policy
                # does not extend to attachment media.
                await self._journal_recorder.record_text_user(
                    history_text, source="attachment"
                )
                self._journal_turn_started = True
        if self._bus is not None:
            await self._bus.publish(TurnAccepted, TurnAccepted(source=source))
        await self._sound_cues.play("thinking")

        messages: list[dict[str, object]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        messages.extend(self._history.as_messages())
        # Current-turn only, mirroring the media_b64 pattern: this never
        # reaches ConversationHistory.add(), so no two turns' timestamps
        # are ever directly compared by the model (see PROJECT.md's
        # v1.3.2 decision for the accepted DST/indirect-leak limitation).
        messages.append(
            {"role": "system", "content": format_time_context(self._clock())}
        )
        messages.append({"role": "user", "content": history_text})

        self._current_turn_history_text = history_text
        self._response_tokens = []
        self._spoke_this_turn = False
        # Sampled here, synchronously, with no `await` before it reaches
        # backend.chat()'s argument list: a hotkey/UI change that lands
        # while this turn's request is already in flight cannot
        # retroactively change what was already passed - see
        # thinking_mode.py and the story's "sampled at turn start, not the
        # live stream" decision.
        reasoning_level = (
            self._thinking_mode.level if self._thinking_mode else ReasoningLevel.OFF
        )
        try:
            if self._bus is not None:
                await self._bus.publish(
                    ModelRequestStarted,
                    ModelRequestStarted(
                        timestamp=self._clock(),
                        inputs=inputs,
                        audio_duration_seconds=audio_duration_seconds,
                    ),
                )
            await self._backend.chat(
                messages, images_b64=media_b64, reasoning_level=reasoning_level
            )
        except Exception:
            logger.exception("Request failed")
            if self._bus is not None:
                await self._bus.publish(BackendRequestFailed, BackendRequestFailed())
            await self._sound_cues.play("error")
            self._journal_turn_started = False
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
        if self._journal_recorder is not None and self._journal_turn_started:
            await self._journal_recorder.record_assistant(full_text)
            self._journal_turn_started = False

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
    thinking_mode: ReasoningLevelState
    settings: Settings
    visibility_mode: VisibilityModeState | None = None
    history: ConversationHistory | None = None
    journal_store: JournalStore | None = None
    journal_search_index: JournalSearchIndex | None = None
    journal_recorder: JournalRecorder | None = None
    memory_file_repository: MemoryFileRepository | None = None
    # build_app() always constructs a real McpHost, regardless of
    # [mcp].enabled - McpHost is itself side-effect-free at construction
    # and structurally inert (status OFF, no clients) until enable() is
    # explicitly called, which is what lets a later live toggle (task 5's
    # Control Center switch) turn MCP on from a genuinely-off start.
    # None only remains a valid type here for test fixtures that
    # construct App(...) directly without build_app() and do not care
    # about MCP, matching visibility_mode/history's own pattern above.
    mcp_host: McpHost | None = None
    camera_state: CameraState = field(default_factory=CameraState)
    camera_capture: CameraCapture | None = None


def _fork_provenance_seed_line(source_end_timestamp: str) -> str:
    source_end = parse_journal_timestamp(source_end_timestamp)
    return (
        "Эта сессия продолжает более ранний разговор. "
        "Исходная сессия завершилась: "
        f"{format_time_context(source_end.timestamp())}."
    )


def _new_context_provenance_line() -> str:
    return "Новый пустой контекст создан пользователем."


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
    tts_output = tts_output or TtsOutput(
        settings.tts,
        engine=build_tts_engine(settings.tts),
        playback_lock=playback_lock,
        bus=bus,
    )
    capture_input = capture_input or CaptureInput(bus, CaptureEngine())
    camera_state = CameraState(settings.camera.enabled)
    camera_capture = CameraCapture(settings.camera, camera_state)
    sound_cues = SoundCuePlayer(settings.sound_cues, playback_lock=playback_lock)
    memory_file_specs = build_memory_file_specs(settings.memory)
    memory_loader = MemoryFileLoader(memory_file_specs, logger=logger)
    memory_file_repository = MemoryFileRepository(memory_file_specs)
    thinking_mode = ReasoningLevelState(bus)

    async def on_camera_capture() -> None:
        await bus.publish(CameraCaptureSucceeded, CameraCaptureSucceeded())
        await sound_cues.play("camera_capture")

    async def on_camera_failure() -> None:
        await bus.publish(CameraCaptureFailed, CameraCaptureFailed())

    tool_registry = ToolRegistry()
    builtin_tool_provider = BuiltinToolProvider(
        thinking_mode=thinking_mode,
        memory_file_repository=memory_file_repository,
        camera_capture=camera_capture,
        on_camera_capture=on_camera_capture,
        on_camera_failure=on_camera_failure,
    )
    builtin_tool_provider.register_tools(tool_registry)
    tool_registry.set_tool_enabled(CAMERA_TOOL_NAME, settings.camera.enabled)
    visibility_mode = VisibilityModeState(bus)
    history = ConversationHistory()
    journal_store = JournalStore(Path(settings.journal.root))
    journal_search_index = JournalSearchIndex(journal_store, journal_store.root)
    journal_recorder = JournalRecorder(
        journal_store,
        enabled=settings.journal.enabled,
        bus=bus,
        logger=logger,
    )
    # Always constructed, never conditionally omitted - see the App
    # dataclass's mcp_host field comment for why this is still safe under
    # the "off equals the capability does not exist" invariant.
    mcp_host = McpHost(
        bus,
        settings.mcp,
        registry=tool_registry,
        builtin_clients={BUILTIN_TOOL_PROVIDER_NAME: builtin_tool_provider},
        ui_language=settings.ui.language,
    )
    dialog_backend = ToolAwareDialog(
        backend,
        bus,
        mcp_host.registry,
        mcp_host.dispatcher,
        build_tool_presentation(settings.mcp.presentation_strategy),
        settings.mcp.max_tool_calls_per_turn,
    )
    orchestrator = Orchestrator(
        dialog_backend,
        history,
        sound_cues,
        audio_input=audio_input,
        thinking_mode=thinking_mode,
        bus=bus,
        journal_recorder=journal_recorder,
        text_input_max_chars=settings.clipboard.max_chars,
        system_prompt_provider=(
            lambda: memory_loader.compose_system_prompt(settings.prompts.system)
        ),
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
        journal_store=journal_store,
        journal_search_index=journal_search_index,
        journal_recorder=journal_recorder,
        memory_file_repository=memory_file_repository,
        settings=settings,
        mcp_host=mcp_host,
        camera_state=camera_state,
        camera_capture=camera_capture,
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


def _camera_health(is_enabled: bool, language: str) -> ModuleHealth:
    return ModuleHealth(
        module=ModuleId.CAMERA,
        status=HealthStatus.OK if is_enabled else HealthStatus.UNAVAILABLE,
        detail=ui_text(
            "camera_detail_ready" if is_enabled else "camera_detail_disabled", language
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
        history=app.orchestrator,
        bus=app.bus,
        logger=logger,
        visibility_mode=app.visibility_mode,
        settings=app.settings,
        mcp_host=app.mcp_host,
        camera_state=app.camera_state,
        camera_capture=app.camera_capture,
    )
    console = console or StatusConsoleWindow()
    touchstrip = (touchstrip or TouchstripWindow()) if include_touchstrip else None
    live_console = LiveStatusConsole(console=console, touchstrip=touchstrip, api=api)
    return live_console


def wire_status_console(
    app: App,
    live_console: LiveStatusConsole,
    loop: asyncio.AbstractEventLoop,
) -> list[Subscription]:
    """Seeds the transport snapshot from authoritative engine state and
    wires the runtime-state pipeline: RuntimeStateTracker turns lifecycle
    events into RuntimeStateChanged, and the render handler below is the
    only place that pushes RuntimeState to the transport."""
    live_console.api.set_loop(loop)
    if app.visibility_mode is None or live_console.transport is None:
        raise RuntimeError("live Status Console requires an App created by build_app()")
    live_console.transport.set_model_label(app.settings.backend.model)
    live_console.transport.set_data_locality(DataLocality.LOCAL)
    if app.mcp_host is not None:
        live_console.transport.set_mcp_state(
            mcp_state_payload(app.mcp_host.status, app.mcp_host.registry.all())
        )
    live_console.transport.set_thinking_mode(app.thinking_mode.level)
    live_console.transport.set_visibility_mode(app.visibility_mode.mode)
    live_console.transport.set_module_health(
        _microphone_health(app.audio_input.is_awake, app.settings.ui.language)
    )
    live_console.transport.set_module_health(
        _camera_health(app.camera_state.enabled, app.settings.ui.language)
    )

    async def on_runtime_state_changed(event: RuntimeStateChanged) -> None:
        substatus = event.substatus_text
        if substatus is None and event.substatus_key is not None:
            substatus = ui_text(event.substatus_key, app.settings.ui.language)
        _push_runtime_state(live_console, event.state, substatus)

    async def on_mcp_status_changed(event: McpModuleStatusChanged) -> None:
        if app.mcp_host is None or live_console.transport is None:
            return
        live_console.transport.set_mcp_state(
            mcp_state_payload(event.status, app.mcp_host.registry.all())
        )

    tracker = RuntimeStateTracker(app.bus)
    health_tracker = ModuleHealthTracker(app.bus)
    subscriptions: list[Subscription] = [
        *tracker.subscribe(),
        *health_tracker.subscribe(),
        (RuntimeStateChanged, on_runtime_state_changed),
    ]
    app.bus.subscribe(RuntimeStateChanged, on_runtime_state_changed)
    if app.mcp_host is not None:
        subscriptions.append((McpModuleStatusChanged, on_mcp_status_changed))
        app.bus.subscribe(McpModuleStatusChanged, on_mcp_status_changed)
    return subscriptions


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
        # TurnCompleted must follow finish_turn's cooldown so LISTENING is
        # not announced while this turn's speech may still be audible.
        await app.orchestrator.finish_turn(
            cooldown_seconds=app.settings.vad.resume_cooldown_seconds
        )
        await app.bus.publish(TurnCompleted, TurnCompleted())
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


# cue: which sound_cues.py cue to play; plays: how many times, in order
# (sequential awaits - SoundCuePlayer's playback_lock already serializes
# concurrent play() calls, so N calls to the same cue play back-to-back).
_REASONING_LEVEL_CUE: dict[ReasoningLevel, tuple[str, int]] = {
    ReasoningLevel.OFF: ("thinking_off", 1),
    ReasoningLevel.LOW: ("thinking_on", 1),
    ReasoningLevel.MEDIUM: ("thinking_on", 2),
    ReasoningLevel.HIGH: ("thinking_on", 3),
}

_REASONING_LEVEL_UI_TEXT_KEY: dict[ReasoningLevel, str] = {
    ReasoningLevel.OFF: "reasoning_level_off",
    ReasoningLevel.LOW: "reasoning_level_low",
    ReasoningLevel.MEDIUM: "reasoning_level_medium",
    ReasoningLevel.HIGH: "reasoning_level_high",
}


async def _on_reasoning_level_changed(app: App, event: ReasoningLevelChanged) -> None:
    """Publishes UI/log feedback and plays the graded reasoning-level cue."""
    level = event.level
    await publish_system_event(
        app.bus,
        logger,
        source=event.source,
        level=EventLevel.INFO,
        log_message=f"Reasoning level: {level.value}",
        ui_message=ui_text(
            _REASONING_LEVEL_UI_TEXT_KEY[level], app.settings.ui.language
        ),
    )
    cue, play_count = _REASONING_LEVEL_CUE[level]
    for _ in range(play_count):
        await app.sound_cues.play(cue)


def wire(app: App) -> list[Subscription]:
    """Subscribes every module to the bus events it consumes. Returns the
    (event_type, handler) pairs so shutdown can unsubscribe them - see
    unwire().

    Runtime-state ownership note: no handler here decides RuntimeState.
    The Orchestrator publishes TurnAccepted behind its own busy guard,
    _on_full_response_complete publishes TurnCompleted, and
    RuntimeStateTracker (wired by wire_status_console) turns lifecycle
    events into RuntimeStateChanged."""

    async def on_full_response_complete(event: ResponseComplete) -> None:
        await _on_full_response_complete(app, event)

    async def on_mic_sleep_toggled(event: MicSleepToggled) -> None:
        await _on_mic_sleep_toggled(app, event)

    async def on_reasoning_level_changed(event: ReasoningLevelChanged) -> None:
        await _on_reasoning_level_changed(app, event)

    subscriptions: list[Subscription] = [
        (UtteranceChunk, app.orchestrator.on_utterance),
        (ScreenshotCaptured, app.orchestrator.on_screenshot),
        (ClipboardSubmitted, app.orchestrator.on_clipboard),
        (ResponseToken, app.tts_output.on_token),
        (ResponseToken, app.orchestrator.on_response_token),
        (ResponseComplete, on_full_response_complete),
        (MicSleepToggled, on_mic_sleep_toggled),
        (ReasoningLevelChanged, on_reasoning_level_changed),
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
    await bus.publish(WarmupStarted, WarmupStarted())
    succeeded = False
    try:
        await backend.chat([{"role": "user", "content": warmup_prompt}])
        succeeded = True
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
    await bus.publish(WarmupCompleted, WarmupCompleted(succeeded=succeeded))


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
        # cooperative stop before we await all background tasks. stop() is
        # terminal: it returns only after the loop and its read worker
        # have actually finished, so the cancellation below can no longer
        # race a microphone executor submission.
        await app.audio_input.stop()
        logger.info("Shutdown: cancelling %d background task(s)", len(background_tasks))
        for task in background_tasks:
            task.cancel()
        results = await asyncio.gather(*background_tasks, return_exceptions=True)
        for task, result in zip(background_tasks, results, strict=False):
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
        if app.journal_recorder is not None:
            logger.info("Shutdown: flushing pending journal writes")
            await app.journal_recorder.wait_for_pending()
        if app.mcp_host is not None:
            # Disabling before unwiring matters: disable() publishes a
            # SystemEvent, and the Status Console's subscription to it is
            # one of these subscriptions - unwiring first would mean the
            # UI silently never learns MCP went offline (review finding
            # 4).
            logger.info("Shutdown: disabling MCP")
            await app.mcp_host.disable()
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
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

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
    await warm_up(app.backend, app.bus, settings.ui.language, settings.prompts.warmup)

    loop = asyncio.get_running_loop()

    def on_shutdown_hotkey() -> None:
        loop.call_soon_threadsafe(shutdown_event.set)

    # Constructed (no I/O) before the try below so the finally's
    # shutdown_provider.stop() always has a real object to call, even if
    # something inside the try raises before register()/start() run.
    shutdown_provider = shutdown_provider or WindowsHotkeyProvider()

    # Everything from here through run_until_shutdown() is covered by the
    # finally below: a failure anywhere in this block (hotkey
    # registration, background task creation, ...) must not leave MCP
    # connected with nothing left to disable it - review finding 4.
    try:
        if app.mcp_host is not None and settings.mcp.enabled:
            await app.mcp_host.enable()
        subscriptions = [*status_console_subscriptions, *wire(app)]

        shutdown_provider.register(settings.hotkeys.shutdown, on_shutdown_hotkey)
        shutdown_provider.start()

        background_tasks = [
            asyncio.create_task(app.audio_input.run_microphone_loop()),
            asyncio.create_task(
                run_capture_hotkey_listener(app.capture_input, settings.hotkeys)
            ),
            asyncio.create_task(
                run_clipboard_hotkey_listener(
                    app.bus, settings.hotkeys, settings.clipboard
                )
            ),
            asyncio.create_task(
                run_mic_sleep_hotkey_listener(app.audio_input, settings.hotkeys)
            ),
            asyncio.create_task(
                run_thinking_hotkey_listener(app.thinking_mode, settings.hotkeys)
            ),
        ]

        await app.sound_cues.play("listening")
        print("Jarvis is running. Press the shutdown hotkey or Ctrl+C to stop.")

        await run_until_shutdown(app, subscriptions, shutdown_event, background_tasks)
    finally:
        if app.mcp_host is not None:
            # Safety net: run_until_shutdown()'s own disable() call
            # already covers the clean-shutdown path and this is a no-op
            # there (McpHost.disable() is idempotent) - this catches the
            # case where run_until_shutdown() was never reached at all.
            await app.mcp_host.disable()
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
    if app.journal_store is None or app.journal_search_index is None:
        raise RuntimeError("live Status Console requires journal read services")
    live_console = create_live_status_console(
        app, include_touchstrip=include_touchstrip
    )
    live_console.transport = UiTransportServer(
        app.bus,
        live_console.api,
        state=UiStateStore(
            model_label=settings.backend.model,
            # Initial snapshot value only; every later transition comes
            # from RuntimeStateTracker via RuntimeStateChanged.
            runtime_state=RuntimeState.WARMING,
            reasoning_level=app.thinking_mode.level,
            visibility_mode=app.visibility_mode.mode,
            language=settings.ui.language,
            config_values=config_values_payload(settings),
        ),
        logger=logger,
        journal_store=app.journal_store,
        journal_search_index=app.journal_search_index,
        journal_text_submitter=app.orchestrator.submit_text_input,
        journal_attachment_submitter=app.orchestrator.on_attachment_submission,
        journal_new_context_handler=app.orchestrator.start_new_context,
        journal_fork_handler=app.orchestrator.fork_from_journal_session,
        journal_fork_seed_max_chars=settings.memory.fork_seed_max_chars,
        journal_active_session_id=(
            lambda: app.journal_recorder.session_id
            if app.journal_recorder is not None
            else None
        ),
        memory_file_repository=app.memory_file_repository,
    )
    live_console.create_windows()

    # pywebview's start() runs its func argument in a plain thread it
    # never joins, and returns the moment the GUI loop exits (verified
    # against pywebview 6.2.1 source) - possibly before that thread has
    # even been scheduled. Returning from main() at that point begins
    # interpreter shutdown while the engine is still running its clean
    # shutdown sequence, and concurrent.futures' atexit hook then makes
    # any in-flight asyncio.to_thread() submission raise "cannot schedule
    # new futures ..." - the shutdown race recorded in
    # tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md.
    # The completion future owns the engine lifetime: the process waits
    # for the engine's actual result, and an engine exception surfaces
    # here instead of dying silently in the unjoined thread.
    engine_done: concurrent.futures.Future[None] = concurrent.futures.Future()

    def start_jarvis() -> None:
        async def start() -> None:
            if live_console.transport is None:
                raise RuntimeError("Status Console transport was not created")
            transport_info = await live_console.transport.start()
            live_console.load_transport_urls(transport_info)
            await run(settings=settings, app=app, live_console=live_console)

        try:
            asyncio.run(start())
        except BaseException as exc:
            engine_done.set_exception(exc)
        else:
            engine_done.set_result(None)

    import webview

    webview.start(start_jarvis)
    engine_done.result()


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
