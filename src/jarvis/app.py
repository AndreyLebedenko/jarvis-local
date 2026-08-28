"""Process entry point and module wiring."""

import argparse
import asyncio
import base64
import concurrent.futures
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jarvis.audio.debug_metrics import on_utterance_captured
from jarvis.audio.input import (
    AudioInput,
    MicrophoneCaptureFailed,
    MicSleepToggled,
    UtteranceChunk,
    VadChunker,
    stream_factory_for_device,
)
from jarvis.audio.input import run_hotkey_listener as run_mic_sleep_hotkey_listener
from jarvis.audio.replay import ReplayOutcome, ReplayPlayer, reply_speech_text
from jarvis.audio.sound_cues import SoundCuePlayer, ensure_generated
from jarvis.audio.tts import TtsOutput
from jarvis.audio.tts_factory import build_tts_engine
from jarvis.audio.tts_mute import TtsMuteState, TtsSpeechEnabledChanged
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BUILTIN_TOOL_PROVIDER_NAME,
    HISTORY_TOOL_PROVIDER_NAME,
    HistorySettings,
    PromptSettings,
    Settings,
    load_settings,
)
from jarvis.core.debug_transcript import (
    configure_debug_transcript,
    disable_debug_transcript,
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
    PersistedFileOutcome,
    TextSubmissionReason,
    TextSubmissionResult,
    TurnAccepted,
    TurnCompleted,
    TurnSource,
    WarmupCompleted,
    WarmupStarted,
)
from jarvis.core.log_config import configure_logging
from jarvis.core.model_request_log import LOG_SOURCE, model_request_log_message
from jarvis.core.solo_session import SoloSessionState
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
from jarvis.files import (
    SessionFileError,
    SessionFileRepository,
    SessionFileScope,
    resolve_session_file_scope,
)
from jarvis.history import (
    AutomaticRetrievalSelectionLimits,
    ConservativeUtf8TokenEstimator,
    ContextBudgetLimits,
    ConversationTurn,
    RetrievedHistoryPassage,
    WorkingContextRequest,
    assemble_working_context,
    build_automatic_retrieval_request,
    select_automatic_retrieval_passages,
    select_recent_history,
    to_history_retrieval_query,
    turns_as_messages,
)
from jarvis.inputs.attachment_audio import (
    MAX_CLIPS_PER_FILE,
    compose_audio_cue,
    compose_audio_media,
    normalize_audio_attachment,
)
from jarvis.inputs.attachments import (
    AttachmentPlan,
    AttachmentUpload,
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
from jarvis.inputs.interrupt import InterruptRequested
from jarvis.inputs.interrupt import run_hotkey_listener as run_interrupt_hotkey_listener
from jarvis.journal import HistoryRetrievalFallbackMode, HistoryRetrievalStatus
from jarvis.journal.annotation import (
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
)
from jarvis.journal.annotation_generator import (
    AnnotationGenerationService,
    OllamaAnnotationBackend,
)
from jarvis.journal.annotation_search import AnnotationSearchIndex
from jarvis.journal.annotation_semantic import AnnotationSemanticIndex
from jarvis.journal.archive import ArchiveOverlayRepository
from jarvis.journal.consolidation import (
    ConsolidationPlanner,
    JournalStoreConsolidationSource,
)
from jarvis.journal.consolidation_executor import ConsolidationExecutor
from jarvis.journal.corpus import HistoryCorpusRepository
from jarvis.journal.events import (
    JournalEventRef,
    TurnOutcome,
    parse_journal_timestamp,
)
from jarvis.journal.fork import (
    ForkSeedOversizeTurnError,
    ForkSessionReason,
    ForkSessionResult,
    build_fork_seed,
)
from jarvis.journal.lifecycle import (
    AnnotationHistoryProjection,
    ArchiveHistoryProjection,
    CorpusHistoryProjection,
    HistoryProjectionLifecycle,
    JournalHistoryService,
    JournalStoreEventReferenceResolver,
    TranscriptHistoryProjection,
)
from jarvis.journal.recorder import JournalRecorder
from jarvis.journal.retrieval import HistoryRetrievalService, Pymorphy3Normalizer
from jarvis.journal.search import JournalSearchIndex
from jarvis.journal.semantic import (
    CachingQueryEmbeddingProvider,
    OllamaEmbeddingProvider,
    SemanticPassageIndex,
)
from jarvis.journal.store import JournalReplay, JournalStore
from jarvis.journal.transcript import (
    TranscriptOverlayRepository,
    TranscriptOverlayTextResolver,
)
from jarvis.journal.transcription import (
    JournalStoreTranscriptionSource,
    OllamaTranscriptionBackend,
    TranscriptionService,
)
from jarvis.memory.files import (
    MemoryFileLoader,
    MemoryFileRepository,
    build_memory_file_specs,
)
from jarvis.tools.builtin import CAMERA_TOOL_NAME, BuiltinToolProvider
from jarvis.tools.history import HistoryToolProvider
from jarvis.tools.host import (
    McpHost,
    McpModuleStatusChanged,
    ToolEnablementChanged,
)
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

_REASONING_PROMPT_FIELD_BY_LEVEL: dict[ReasoningLevel, str] = {
    ReasoningLevel.LOW: "reasoning_low",
    ReasoningLevel.MEDIUM: "reasoning_medium",
    ReasoningLevel.HIGH: "reasoning_high",
}


def _compose_effective_system_prompt(
    base_prompt: str,
    reasoning_level: ReasoningLevel,
    reasoning_prompt_settings: PromptSettings,
) -> str:
    field_name = _REASONING_PROMPT_FIELD_BY_LEVEL.get(reasoning_level)
    if field_name is None:
        return base_prompt
    section = getattr(reasoning_prompt_settings, field_name)
    if section is None:
        return base_prompt
    return f"{base_prompt}\n\n{section}"


def _history_limits_from_settings(
    history_settings: HistorySettings,
) -> ContextBudgetLimits:
    return ContextBudgetLimits(
        prompt_capacity_tokens=history_settings.prompt_capacity_tokens,
        recent_history_max_tokens=history_settings.recent_history_max_tokens,
        automatic_retrieval_max_tokens=history_settings.automatic_retrieval_max_tokens,
        tool_result_reserve_tokens=history_settings.tool_result_reserve_tokens,
        reasoning_generation_reserve_tokens=(
            history_settings.reasoning_generation_reserve_tokens
        ),
        estimator_safety_margin_tokens=history_settings.estimator_safety_margin_tokens,
        minimum_recent_exchanges=history_settings.minimum_recent_exchanges,
    )


# Debug mode is an explicit exception to the v1.6.4 content rule, which
# both records otherwise keep and which README states to the user as a
# promise. It is a CLI flag with no config key on purpose: a persisted
# switch would outlive the session that needed it, while a flag dies at
# the next start.
DEBUG_MODE_LOG_MESSAGE = (
    "DEBUG MODE: the model exchange is being recorded for this run. "
    "Privacy is not guaranteed - logs may contain what you say and send."
)


def announce_debug_mode(enabled: bool, transcript_path: Path | None = None) -> None:
    """Says, everywhere it can, that the content rule is lifted.

    Called first thing in run(), before anything could be recorded, so a
    log carrying the exchange also carries the reason it was allowed to.
    The console banner and the events-panel entry join this function when
    they land; the warning level is deliberate - a normal run must never
    print it, and this one must be impossible to miss in a log file."""
    if not enabled:
        return
    logger.warning(DEBUG_MODE_LOG_MESSAGE)
    if transcript_path is None:
        logger.warning(
            "DEBUG MODE: the transcript file could not be opened, so this run "
            "records nothing - fix the logging directory and start again"
        )
    else:
        logger.warning("DEBUG MODE: recording the exchange to %s", transcript_path)


async def _announce_debug_mode_to_panel(app: "App", language: str) -> None:
    """The events-panel half of the debug announcement.

    announce_debug_mode() runs before app.bus exists and guarantees the
    file log says debug is on even if a bus were never available; this is
    the second, independent notice, using the same publish_system_event()
    call every other user-facing fact in this file goes through - the
    panel entry and the file log can never disagree about whether debug
    was announced. Called from run() once app is built, on every tab via
    the console's shared header/events-panel state."""
    await publish_system_event(
        app.bus,
        logger,
        source="ENGINE",
        level=EventLevel.WARN,
        log_message="Debug mode is active for this session",
        ui_message=ui_text("debug_mode_active", language),
    )


class ConversationHistory:
    """Text-first history with optional media fields for future retention."""

    def __init__(self) -> None:
        self._turns: list[ConversationTurn] = []

    def add(self, role: str, text: str, media_b64: tuple[str, ...] = ()) -> None:
        self._turns.append(ConversationTurn(role=role, text=text, media_b64=media_b64))

    def as_messages(self) -> list[dict[str, object]]:
        return turns_as_messages(self._turns)

    def turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    def clear(self) -> None:
        """Drops recorded conversation turns."""
        self._turns = []


DEFAULT_TEXT_INPUT_MAX_CHARS = 20000

# ConversationHistory notes for a turn ended by record_aborted_turn()
# (task-v1.7.0-3) rather than a normal ResponseComplete. A separate
# system-role Turn, not text appended to whatever partial answer was
# recorded - see record_aborted_turn()'s docstring for why. Russian: this is
# dialog data sent to the model, like the system prompt and time-context
# injection, not documentation (CLAUDE.md rule 9's runtime-string exception).
_INTERRUPTED_HISTORY_NOTE = (
    "Пользователь прервал этот ответ до того, как он был закончен."
)
_FAILED_HISTORY_NOTE = "Ответ не был получен из-за технической ошибки бэкенда."


def _compose_session_file_cue(storage_names: Sequence[str]) -> str:
    """Model-facing cue naming the session files persisted this turn. ASCII and
    English, matching the attachment cues (attachments.py) - it enters the
    model prompt, not the recorded user event."""
    if not storage_names:
        return ""
    listed = ", ".join(storage_names)
    return (
        f"[Session files saved this turn: {listed}. Use read_session_text, "
        "view_session_image, or stat_session_file with a storage name to open one.]"
    )


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
        history_retrieval_service: HistoryRetrievalService | None = None,
        clock: Callable[[], float] | None = None,
        text_input_max_chars: int = DEFAULT_TEXT_INPUT_MAX_CHARS,
        system_prompt_provider: Callable[[bool], str] | None = None,
        reasoning_prompt_settings: PromptSettings | None = None,
        history_limits: ContextBudgetLimits | None = None,
        max_audio_attachment_clips: int = MAX_CLIPS_PER_FILE,
        solo_session_state: SoloSessionState | None = None,
        session_file_repository: SessionFileRepository | None = None,
        session_file_scope: Callable[[], SessionFileScope] | None = None,
        on_turn_start: Callable[[], object] | None = None,
    ) -> None:
        self._backend = backend
        # Called the instant a turn is accepted, before any speech: a live
        # turn takes the single playback channel, so an in-flight reply
        # replay must yield to it (story-v1.8.2 - replay never blocks a new
        # live turn, and a new live turn's speech never interleaves with a
        # replay on the shared playback_lock). Wired to ReplayPlayer.cancel();
        # defaults to a no-op so _start_turn can call it unconditionally.
        self._on_turn_start = on_turn_start or (lambda: None)
        self._history = history
        self._sound_cues = sound_cues
        self._solo_session_state = solo_session_state
        # The bool argument is "solo active right now" - see clear()'s own
        # call for why this is read fresh at every session-start moment
        # rather than once.
        self._system_prompt_provider = system_prompt_provider or (
            lambda _solo: system_prompt
        )
        self._system_prompt = self._system_prompt_provider(self._is_solo_active())
        self._reasoning_prompt_settings = reasoning_prompt_settings or PromptSettings()
        self._history_limits = (
            history_limits
            if history_limits is not None
            else _history_limits_from_settings(Settings().history)
        )
        self._audio_input = audio_input
        self._thinking_mode = thinking_mode
        self._bus = bus
        self._journal_recorder = journal_recorder
        self._history_retrieval_service = history_retrieval_service
        self._clock = clock or time.time
        self._text_input_max_chars = text_input_max_chars
        self._max_audio_attachment_clips = max_audio_attachment_clips
        self._session_file_repository = session_file_repository
        self._session_file_scope = session_file_scope
        self._automatic_retrieval_limits = AutomaticRetrievalSelectionLimits(
            token_budget=self._history_limits.automatic_retrieval_max_tokens
        )
        self._pending_screenshot_b64: str | None = None
        self._pending_screenshot_png: bytes | None = None
        self._response_tokens: list[str] = []
        self._spoke_this_turn = False
        self._busy = False
        self._current_turn_history_text: str = VOICE_PLACEHOLDER_TEXT
        self._journal_turn_started = False
        # Set once record_voice_user()/record_text_user() actually returns
        # (task-v1.7.0-3 review) - see record_aborted_turn(). Replaced with
        # a fresh Event every turn in _start_turn(), same reason
        # _response_tokens etc. are: a stale, already-set Event left over
        # from a previous turn must never be mistaken for this turn's.
        self._journal_recording_done = asyncio.Event()
        # Test-introspection only (mirrors _active_chat_task's existing
        # pattern): the background task record_aborted_turn() creates when
        # it must defer the outcome write - see its docstring. Not read by
        # any production code path.
        self._pending_aborted_journal_write: asyncio.Task[None] | None = None
        # Set for the duration of the backend call only (task-v1.7.0-2
        # interrupt) - see cancel_active_turn() and _start_turn().
        self._active_chat_task: asyncio.Task | None = None
        # Latched per turn (task-v1.7.0-2 interrupt, review finding 2):
        # cancel_active_turn() can be called before _active_chat_task
        # exists yet (interrupt arriving during journal/bus/cue work,
        # before _dispatch_backend_request() even starts) - this flag
        # lets that method notice and skip dispatching instead of
        # starting a backend request for a turn already declared over.
        # An Event, not a bool (task-v1.7.0-3 review, third round): a new
        # turn B replaces this attribute with its own fresh Event in
        # _start_turn() the moment it is accepted, which can happen while
        # turn A's own _start_turn() invocation is still suspended
        # somewhere (e.g. a slow journal-recording call) - turn A's own
        # resumption must keep checking *its own* Event object (captured
        # locally when created), not whatever this attribute currently
        # points to, or it would see B's fresh "not interrupted" Event and
        # wrongly conclude it is safe to keep going.
        self._interrupt_requested = asyncio.Event()
        # Latched per turn (task-v1.7.0-2 interrupt, review finding 1) -
        # see claim_turn_end().
        self._turn_end_claimed = False

    @property
    def is_busy(self) -> bool:
        return self._busy

    def claim_turn_end(self) -> bool:
        """Returns True exactly once per turn, to whichever caller (the
        normal ResponseComplete path or an interrupt) gets here first;
        every other caller - including one that arrives while idle, since
        this also requires busy - must treat False as "this turn is
        already being ended elsewhere, do nothing more for it."

        Deliberately does not itself touch busy, the mic, or
        TurnCompleted: only one caller can ever win this claim per turn,
        so the winner still runs finish_turn() etc. exactly as before -
        this method's only job is making sure there is exactly one
        winner, not replacing what the winner does.

        task-v1.7.0-2 review finding 1: a turn's backend call can finish
        (publishing ResponseComplete) while its trailing TTS is still
        playing, i.e. while _on_full_response_complete() is still
        running - if a hotkey interrupt lands in that window, both paths
        would otherwise independently clear busy, publish TurnCompleted,
        and (worse) _on_full_response_complete could go on to record
        history for a turn the interrupt already ended, possibly
        overwriting state a *new* turn has since started using.

        No `await` between the check and the set, so this is atomic by
        construction - asyncio's cooperative scheduling cannot interleave
        another coroutine between them."""
        if not self._busy or self._turn_end_claimed:
            return False
        self._turn_end_claimed = True
        return True

    def cancel_active_turn(self) -> None:
        """Requests cancellation of the current turn: arms the latched
        interrupt flag (see _interrupt_requested above) and cancels the
        backend task if one already exists. Callers must gate this on a
        successful claim_turn_end() themselves - this method does not
        check busy, so calling it without that guard could arm the flag
        for whatever turn starts next instead of the one intended."""
        self._interrupt_requested.set()
        if self._active_chat_task is not None:
            self._active_chat_task.cancel()

    def _is_solo_active(self) -> bool:
        return self._solo_session_state is not None and self._solo_session_state.enabled

    def clear(self) -> None:
        self._history.clear()
        self._system_prompt = self._system_prompt_provider(self._is_solo_active())

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
        self,
        typed_text: str,
        plan: AttachmentPlan,
        persistent_uploads: Sequence[AttachmentUpload] = (),
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
                pending_audio_item.filename,
                pending_audio_item.pending_audio,
                max_clips=self._max_audio_attachment_clips,
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

        has_content = bool(history_text.strip()) or bool(media) or bool(inputs)
        if not has_content and not persistent_uploads:
            return AttachmentSubmissionResult(
                AttachmentSubmissionReason.NO_ACCEPTED_CONTENT
            )

        persisted: list[PersistedFileOutcome] = []

        async def persist_hook() -> str:
            outcomes = await self._persist_uploads(persistent_uploads)
            persisted.extend(outcomes)
            storage_names = [o.storage_name for o in outcomes if o.storage_name]
            return _compose_session_file_cue(storage_names)

        await self._start_turn(
            history_text,
            media if media else None,
            TurnSource.ATTACHMENT,
            inputs=tuple(inputs),
            audio_duration_seconds=audio_duration_seconds,
            voice_wav_bytes=None,
            screenshot_png_bytes=None,
            post_journal_hook=persist_hook if persistent_uploads else None,
        )
        return AttachmentSubmissionResult(
            AttachmentSubmissionReason.ACCEPTED, persisted_files=tuple(persisted)
        )

    async def _persist_uploads(
        self, uploads: Sequence[AttachmentUpload]
    ) -> list[PersistedFileOutcome]:
        if not uploads:
            return []
        if self._session_file_repository is None or self._session_file_scope is None:
            return [
                PersistedFileOutcome(upload.filename, error="session files unavailable")
                for upload in uploads
            ]
        # The current session's user event was scheduled by _start_turn's
        # record_text_user just before this hook runs; flush it so the session
        # is journal-visible and write_bytes does not report no-active-session
        # on the first turn of a new session.
        if self._journal_recorder is not None:
            await self._journal_recorder.wait_for_pending()
        scope = self._session_file_scope()
        return [self._persist_one(scope, upload) for upload in uploads]

    async def _apply_post_journal_hook(
        self, hook: Callable[[], Awaitable[str]] | None, history_text: str
    ) -> str:
        if hook is None:
            return history_text
        cue = await hook()
        if not cue:
            return history_text
        history_text = f"{history_text}\n\n{cue}" if history_text else cue
        self._current_turn_history_text = history_text
        return history_text

    def _persist_one(
        self, scope: SessionFileScope, upload: AttachmentUpload
    ) -> PersistedFileOutcome:
        try:
            result = self._session_file_repository.write_bytes(
                scope, upload.filename, upload.data
            )
        except SessionFileError as exc:
            return PersistedFileOutcome(upload.filename, error=str(exc))
        except OSError as exc:
            return PersistedFileOutcome(
                upload.filename, error=f"filesystem error: {exc}"
            )
        return PersistedFileOutcome(
            upload.filename, storage_name=result.storage_name, bytes=result.bytes
        )

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
        post_journal_hook: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        # Defensive re-check: on_utterance()/on_clipboard() already gate on
        # busy before doing their own turn-specific setup above, with no
        # `await` in between - so this can only fire for a caller that
        # forgets to pre-check, not for the two above in normal operation.
        if self._busy:
            logger.info("Ignoring new turn: previous request still in flight")
            return
        self._busy = True
        # A live turn owns the playback channel; stop any reply replay now so
        # its remaining sentences never interleave with this turn's speech.
        self._on_turn_start()
        # Captured locally, not just assigned to self.xxx (task-v1.7.0-3
        # review, third round): a later turn B can start - and rebind both
        # of these attributes to its own fresh objects - while *this*
        # invocation is still suspended somewhere below (e.g. a slow
        # journal-recording call), since _cancel_current_turn() clears busy
        # without waiting for this coroutine to actually exit. Every check
        # or `.set()` against these two signals further down in this method
        # (and in _dispatch_backend_request(), which receives
        # interrupt_requested as a parameter for the same reason) uses these
        # local names instead of re-reading self._interrupt_requested/
        # self._journal_recording_done, so this turn always observes and
        # signals *its own* state even after a later turn has moved on.
        interrupt_requested = asyncio.Event()
        journal_recording_done = asyncio.Event()
        self._interrupt_requested = interrupt_requested
        self._journal_recording_done = journal_recording_done
        self._turn_end_claimed = False
        self._journal_turn_started = False
        # Set here, before the journal-recording await below can yield to a
        # concurrent interrupt (task-v1.7.0-3): record_aborted_turn() reads
        # these to describe *this* turn if it never completes normally, and
        # must never see the *previous* turn's leftover text/tokens because
        # this turn's own assignment had not happened yet. No `await` runs
        # between _busy = True above and this point, so there is no window
        # for a concurrent cancel_active_turn() to observe a half-updated
        # state here.
        self._current_turn_history_text = history_text
        self._response_tokens = []
        self._spoke_this_turn = False
        if self._journal_recorder is not None:
            # _journal_turn_started is set *before* each await, not after
            # (task-v1.7.0-3 review): record_aborted_turn() reads this flag
            # to decide whether to write a journal entry for a turn that
            # never completes normally. Setting it only after the await
            # returned left a window - reachable by an interrupt landing
            # during the await itself - where the write had already been
            # decided on (and, in a slower JournalRecorder implementation,
            # already scheduled) but the flag still read False, so a
            # concurrent record_aborted_turn() silently skipped the journal
            # side entirely. Setting it here also removes a second, subtler
            # bug: the old post-await assignment ran even after an
            # interrupt had already ended this turn (and already reset the
            # flag to False for it) - resurrecting a stale True left over
            # from an ended turn until the next _start_turn() call reset it.
            if source is TurnSource.VOICE and voice_wav_bytes is not None:
                self._journal_turn_started = True
                await self._journal_recorder.record_voice_user(
                    voice_wav_bytes, screenshot_png_bytes=screenshot_png_bytes
                )
            elif source in {TurnSource.TEXT, TurnSource.TEXT_INPUT}:
                self._journal_turn_started = True
                await self._journal_recorder.record_text_user(
                    history_text, source=journal_source or "text"
                )
            elif source is TurnSource.ATTACHMENT:
                # No media reference is recorded, matching record_text_user()'s
                # existing text-only contract (only record_voice_user() ever
                # writes a journal media file) - the journal-recording policy
                # does not extend to attachment media.
                self._journal_turn_started = True
                await self._journal_recorder.record_text_user(
                    history_text, source="attachment"
                )
        # Marks that whichever journal-recording decision above was made
        # (including "none") has been carried out - record_aborted_turn()
        # waits on this before writing the assistant/outcome side, so it
        # never races ahead of the user's own entry in the append-only
        # journal (task-v1.7.0-3 review, second round).
        journal_recording_done.set()
        # Runs after the user event is recorded (so the session is
        # journal-visible) and before the model dispatch, so a persisted
        # session file's storage name can be surfaced to the model in this
        # same turn. Only the attachment path passes a hook; it appends to the
        # model-facing text without altering the already-recorded user event.
        history_text = await self._apply_post_journal_hook(
            post_journal_hook, history_text
        )
        # Checked here and again after TurnAccepted (review finding 2,
        # round 2): an interrupt can be requested while still inside the
        # journal-recording await above, before _dispatch_backend_request()
        # exists to catch it. Without this, _cancel_current_turn() would
        # already have published TurnCompleted and returned Jarvis to
        # listening, only for this method to go on and publish
        # TurnAccepted plus play the thinking cue right afterward -
        # UI-visible "TurnCompleted -> TurnAccepted" with nothing to
        # follow, since _dispatch_backend_request()'s own check (below)
        # would then skip the backend call entirely.
        if interrupt_requested.is_set():
            return
        if self._bus is not None:
            await self._bus.publish(TurnAccepted, TurnAccepted(source=source))
        if interrupt_requested.is_set():
            return
        await self._sound_cues.play("thinking")

        reasoning_level = (
            self._thinking_mode.level if self._thinking_mode else ReasoningLevel.OFF
        )
        effective_system_prompt = _compose_effective_system_prompt(
            self._system_prompt,
            reasoning_level,
            self._reasoning_prompt_settings,
        )
        (
            retrieved_passages,
            retrieval_telemetry,
        ) = await self._prepare_automatic_retrieval(history_text, source)
        working_context = assemble_working_context(
            WorkingContextRequest(
                system_prompt=effective_system_prompt,
                recent_history=self._history.turns(),
                retrieved_passages=retrieved_passages,
                time_context=format_time_context(self._clock()),
                current_request_text=history_text,
                limits=self._history_limits,
                current_request_media_b64=tuple(media_b64 or ()),
                minimum_recent_exchanges=self._history_limits.minimum_recent_exchanges,
            )
        )
        messages = list(working_context.messages)
        prompt_budget = asdict(working_context.budget)
        if retrieval_telemetry is not None:
            prompt_budget.update(retrieval_telemetry)
        await self._dispatch_backend_request(
            messages,
            media_b64,
            reasoning_level,
            inputs,
            audio_duration_seconds,
            interrupt_requested,
            prompt_budget,
        )

    async def _prepare_automatic_retrieval(
        self,
        history_text: str,
        source: TurnSource,
    ) -> tuple[tuple[RetrievedHistoryPassage, ...], dict[str, int | bool | str] | None]:
        if source is TurnSource.VOICE or self._history_retrieval_service is None:
            return (), None
        return await asyncio.to_thread(
            self._resolve_automatic_retrieval,
            history_text,
        )

    def _resolve_automatic_retrieval(
        self,
        history_text: str,
    ) -> tuple[tuple[RetrievedHistoryPassage, ...], dict[str, int | bool | str] | None]:
        recent_history = select_recent_history(
            self._history.turns(),
            estimator=ConservativeUtf8TokenEstimator(),
            max_tokens=self._history_limits.recent_history_max_tokens,
            minimum_recent_exchanges=self._history_limits.minimum_recent_exchanges,
        )
        session_ids: tuple[str, ...] = ()
        if self._is_solo_active():
            current_session_id = (
                self._journal_recorder.session_id
                if self._journal_recorder is not None
                else None
            )
            # No session started yet: there is nothing of "this session"
            # to search, and falling through to an unrestricted query
            # would defeat solo mode rather than just finding nothing.
            if current_session_id is None:
                return (), None
            session_ids = (current_session_id,)
        request = build_automatic_retrieval_request(
            history_text, recent_history, session_ids=session_ids
        )
        if not request.query_text.strip():
            return (), None

        started = time.perf_counter()
        retrieval_result = self._history_retrieval_service.retrieve(
            to_history_retrieval_query(
                request,
                limit=self._automatic_retrieval_limits.candidate_limit,
            )
        )
        selection = select_automatic_retrieval_passages(
            request,
            retrieval_result.candidates,
            self._automatic_retrieval_limits,
            estimator=ConservativeUtf8TokenEstimator(),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        telemetry: dict[str, int | bool | str] = {
            "retrieval_candidate_count": retrieval_result.returned_count,
            "retrieval_accepted_passage_count": selection.selected_passage_count,
            "retrieval_elapsed_ms": elapsed_ms,
            "retrieval_full_hybrid": (
                retrieval_result.status is HistoryRetrievalStatus.ACCEPTED
                and retrieval_result.fallback_mode
                is HistoryRetrievalFallbackMode.FULL_HYBRID
            ),
            "retrieval_lexical_by_timeout": (
                retrieval_result.status is HistoryRetrievalStatus.ACCEPTED
                and retrieval_result.fallback_mode
                is HistoryRetrievalFallbackMode.LEXICAL_BY_TIMEOUT
            ),
            "retrieval_lexical_by_unavailable": (
                retrieval_result.status is HistoryRetrievalStatus.ACCEPTED
                and retrieval_result.fallback_mode
                is HistoryRetrievalFallbackMode.LEXICAL_BY_UNAVAILABLE
            ),
            "retrieval_failed": retrieval_result.status
            is not HistoryRetrievalStatus.ACCEPTED,
        }
        if retrieval_result.status is not HistoryRetrievalStatus.ACCEPTED:
            telemetry["retrieval_failed_status"] = retrieval_result.status.value
        return selection.selected_passages, telemetry

    async def _dispatch_backend_request(
        self,
        messages: list[dict[str, object]],
        media_b64: list[str] | None,
        reasoning_level: ReasoningLevel,
        inputs: tuple[ModelRequestInput, ...],
        audio_duration_seconds: float | None,
        interrupt_requested: asyncio.Event,
        prompt_budget: dict[str, int | bool | str] | None = None,
    ) -> None:
        """Runs the backend call as a cancellable task and handles its
        three outcomes: normal completion (nothing further to do here -
        ResponseComplete drives the rest), interruption (cancel_active_turn()
        cancelled it; app.py's _cancel_current_turn() owns busy-clearing,
        mic resume, and TurnCompleted via claim_turn_end(), so this returns
        quietly rather than racing it), and failure (this turn's own
        responsibility to clean up).

        Checks interrupt_requested before dispatching anything (review
        finding 2): an interrupt landing during the journal/bus/cue work
        above, before this method even runs, would otherwise be
        forgotten - cancel_active_turn() has no task to cancel yet at
        that point, so without this check the backend call would start
        anyway, right after _cancel_current_turn() already told the rest
        of the app the turn was over. Takes this as a parameter rather than
        reading self._interrupt_requested (task-v1.7.0-3 review, third
        round): a later turn can replace that attribute with its own fresh
        Event while this call is still suspended below (e.g. still awaiting
        ModelRequestStarted's publish) - reading the parameter instead means
        this call keeps checking *this* turn's own signal even then."""
        if interrupt_requested.is_set():
            return
        # Ownership guard (task-v1.7.0-3 review, fifth round): this dispatch
        # may only ever clear the task *it* created. A stale invocation from
        # an interrupted turn A can resume (from the ModelRequestStarted
        # publish below) after a later turn B has already stored its own
        # task in self._active_chat_task - A's finally must then leave B's
        # reference alone, or the next interrupt would find nothing to
        # cancel while B's backend request keeps running.
        own_chat_task: asyncio.Task | None = None
        try:
            if self._bus is not None:
                request_started = ModelRequestStarted(
                    timestamp=self._clock(),
                    inputs=inputs,
                    audio_duration_seconds=audio_duration_seconds,
                    prompt_budget=prompt_budget,
                )
                # Not publish_system_event(): the events panel already has
                # this turn as a typed, localized entry (task-v1.6.4-2), so
                # routing it through there would show every turn twice. The
                # file log needs its own English line because it, not the
                # panel, is what a user attaches to a problem report.
                logger.info(
                    "[%s] %s",
                    LOG_SOURCE,
                    model_request_log_message(request_started),
                )
                await self._bus.publish(ModelRequestStarted, request_started)
                # Re-checked here (task-v1.7.0-3 review, fourth round): the
                # single check above this `try` is not enough by itself -
                # EventBus.publish() awaits every subscriber, a real
                # suspension point, and an interrupt landing during it finds
                # no _active_chat_task yet to cancel (created only below).
                # Without this second check, resuming here after the
                # interrupt already ran _cancel_current_turn()'s full
                # cleanup (busy cleared, TurnCompleted published) would
                # still go on to dispatch a stale backend request - into a
                # later turn's own state, if one has since started.
                if interrupt_requested.is_set():
                    return
            own_chat_task = asyncio.create_task(
                self._backend.chat(
                    messages, images_b64=media_b64, reasoning_level=reasoning_level
                )
            )
            self._active_chat_task = own_chat_task
            await own_chat_task
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Request failed")
            if self._bus is not None:
                await self._bus.publish(BackendRequestFailed, BackendRequestFailed())
            await self._sound_cues.play("error")
            # Gated on claim_turn_end() purely to avoid double-recording if a
            # hotkey interrupt races this same failure (task-v1.7.0-3): a lost
            # claim means _cancel_current_turn() already recorded this turn as
            # interrupted. Everything else below (busy-clearing) is
            # unconditional, exactly as before - only the new recording call
            # is guarded.
            if self.claim_turn_end():
                await self.record_aborted_turn(outcome=TurnOutcome.FAILED)
            self._busy = False
        finally:
            if self._active_chat_task is own_chat_task:
                self._active_chat_task = None

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

    async def record_aborted_turn(self, *, outcome: TurnOutcome) -> None:
        """Records a turn that ends without its answer being recorded
        through the normal on_response_complete() path above - cancelled by
        an interrupt (TurnOutcome.INTERRUPTED, from _cancel_current_turn())
        or ended by a hard dispatch failure before any answer existed
        (TurnOutcome.FAILED, from _dispatch_backend_request()'s except
        clause). Whatever text had been generated so far - empty or partial
        - is recorded in ConversationHistory and the journal instead of
        being silently discarded, per the story's append-only invariant - a
        later turn must not find this exchange missing outright.

        Callers must only invoke this once per turn and only when certain
        on_response_complete() has not already recorded it - claim_turn_end()
        is the guard both current callers use (_cancel_current_turn(),
        _dispatch_backend_request()).

        A separate system-role Turn carries the outcome rather than a
        marker appended to the assistant's own text: this reuses the
        pattern already established - and verified against the real model -
        by the per-turn time-context injection (format_time_context) of
        interleaving system-role content into the message list (see
        PROJECT.md's v1.3.2 architecture note), keeps the assistant's
        recorded words literal, and means an empty response never has to
        become an empty assistant Turn.

        Journal-write ordering (task-v1.7.0-3 review, second round): if the
        user's own record_voice_user()/record_text_user() call for this turn
        has already returned (_journal_recording_done already set - true for
        every real call today, since neither method has an internal `await`
        before scheduling its own write), the outcome is written immediately,
        exactly as before, so finish_turn()'s wait_for_pending() still waits
        for it. If it has *not* yet returned - not reachable with the real
        JournalRecorder, but reachable if a future implementation gains a
        real await before scheduling - writing immediately would race ahead
        of the user's own entry in the append-only journal. Deferred instead
        to a background task that waits for it first, so the write always
        lands in the correct order; deliberately not awaited here, since
        blocking would make the interrupt itself wait on however long that
        write takes - the same trade-off _cancel_current_turn() already
        makes by not gating tts_output.cancel()/backend cancellation on
        claim_turn_end(). Accepted cost of that (currently unreachable)
        branch: the deferred write may land after finish_turn() returns,
        same class of eventual-consistency gap already accepted for the
        Journal tab-inactive case (see
        tasks/bug_reports/2026-07-27-journal-live-feed-misses-events-while-tab-inactive.md),
        not a new one."""
        text = "".join(self._response_tokens)
        self._history.add("user", self._current_turn_history_text)
        if text:
            self._history.add("assistant", text)
        notes = {
            TurnOutcome.INTERRUPTED: _INTERRUPTED_HISTORY_NOTE,
            TurnOutcome.FAILED: _FAILED_HISTORY_NOTE,
        }
        self._history.add("system", notes[outcome])
        if self._journal_recorder is not None and self._journal_turn_started:
            journal_recorder = self._journal_recorder
            if self._journal_recording_done.is_set():
                await journal_recorder.record_assistant(text, outcome=outcome)
            else:
                recording_done = self._journal_recording_done

                async def _write_after_user_recorded() -> None:
                    await recording_done.wait()
                    await journal_recorder.record_assistant(text, outcome=outcome)

                self._pending_aborted_journal_write = asyncio.create_task(
                    _write_after_user_recorded()
                )
        self._journal_turn_started = False

    async def finish_turn(self, cooldown_seconds: float = 0.0) -> None:
        """Clears the busy flag, optionally after a cooldown, and resumes
        the mic from its auto-pause (see on_response_token()). The single
        place both a normal completion (_on_full_response_complete()) and
        an interrupt (_cancel_current_turn()) converge to end a turn, so
        anything that must hold true "by the time a turn is over,
        whichever way it ended" belongs here, not duplicated in each
        caller.

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

        Waits for any journal writes still in flight in the background
        (task-v1.7.0-2 review): JournalRecorder.record_voice_user()/
        record_text_user() schedule the actual disk write as a background
        task rather than blocking on it (JournalRecorder._schedule()), so
        the live Journal panel's update (JournalEventAppended) can lag
        behind it. A turn that runs its normal, multi-second course
        (generation + TTS) gives that write plenty of time to finish
        first, which is why this went unnoticed before interrupts existed
        - a turn cancelled during the "thinking" phase can end in a
        fraction of a second, well before the write completes, making a
        just-spoken utterance appear briefly missing from the live view
        (confirmed empirically: 0 of 1 pending journal tasks had
        completed at the moment finish_turn() used to return).
        """
        if self._journal_recorder is not None:
            await self._journal_recorder.wait_for_pending()
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
    history_projection_lifecycle: HistoryProjectionLifecycle | None = None
    journal_history_service: JournalHistoryService | None = None
    journal_recorder: JournalRecorder | None = None
    transcript_overlay_repository: TranscriptOverlayRepository | None = None
    annotation_overlay_repository: AnnotationOverlayRepository | None = None
    transcription_service: TranscriptionService | None = None
    annotation_generation_service: AnnotationGenerationService | None = None
    archive_overlay_repository: ArchiveOverlayRepository | None = None
    consolidation_planner: ConsolidationPlanner | None = None
    consolidation_executor: ConsolidationExecutor | None = None
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
    tts_mute_state: TtsMuteState | None = None
    solo_session_state: SoloSessionState | None = None
    replay_player: ReplayPlayer | None = None


def _fork_provenance_seed_line(source_end_timestamp: str) -> str:
    source_end = parse_journal_timestamp(source_end_timestamp)
    return (
        "Эта сессия продолжает более ранний разговор. "
        "Исходная сессия завершилась: "
        f"{format_time_context(source_end.timestamp())}."
    )


def _new_context_provenance_line() -> str:
    return "Новый пустой контекст создан пользователем."


def _build_transcription_service(
    settings: Settings,
    journal_store: JournalStore,
    backend: OllamaBackend,
    transcripts: TranscriptOverlayRepository,
) -> TranscriptionService:
    transcription_settings = settings.history.transcription
    kwargs: dict[str, object] = {
        "max_concurrency": transcription_settings.max_concurrency,
    }
    if transcription_settings.instruction.strip():
        kwargs["instruction"] = transcription_settings.instruction
    return TranscriptionService(
        JournalStoreTranscriptionSource(journal_store),
        OllamaTranscriptionBackend(backend),
        transcripts,
        **kwargs,
    )


def _build_annotation_generation_service(
    settings: Settings,
    corpus: HistoryCorpusRepository,
    backend: OllamaBackend,
    annotations: AnnotationOverlayRepository,
    bus: EventBus,
) -> AnnotationGenerationService:
    annotation_settings = settings.history.annotation
    kwargs: dict[str, object] = {
        "reasoning": ReasoningLevel(annotation_settings.reasoning),
        "max_concurrency": annotation_settings.max_concurrency,
        "max_source_events": annotation_settings.max_source_events,
        "max_source_chars": annotation_settings.max_source_chars,
        "max_annotation_chars": annotation_settings.max_annotation_chars,
    }
    if annotation_settings.instruction.strip():
        kwargs["instruction"] = annotation_settings.instruction
    return AnnotationGenerationService(
        corpus,
        OllamaAnnotationBackend(backend),
        annotations,
        publish_changed=lambda event: bus.publish(AnnotationOverlayChanged, event),
        **kwargs,
    )


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
    solo_session_state = SoloSessionState(bus)
    backend = backend or OllamaBackend(bus, settings.backend)
    audio_input = audio_input or AudioInput(
        bus,
        VadChunker(settings.vad),
        stream_factory=stream_factory_for_device(
            settings.microphone.device, settings.microphone.host_api
        ),
    )
    # Shared so a sound cue and a spoken sentence can never physically
    # overlap on the output device - see tts.py/sound_cues.py docstrings
    # for why (sounddevice's play()/wait() share one implicit stream per
    # process; concurrent calls stop/replace each other, not mix).
    playback_lock = asyncio.Lock()
    tts_mute_state = TtsMuteState(bus, enabled=settings.tts.enabled)
    # One engine, shared by live TTS and replay: a second engine would mean
    # a second model load (VRAM). Replay reuses the same playback_lock and
    # mute_state so it can neither overlap live speech on the device nor
    # play while speech is globally disabled (story-v1.8.2).
    tts_engine = build_tts_engine(settings.tts)
    tts_output = tts_output or TtsOutput(
        settings.tts,
        engine=tts_engine,
        playback_lock=playback_lock,
        bus=bus,
        mute_state=tts_mute_state,
    )
    replay_player = ReplayPlayer(
        settings.tts,
        tts_engine,
        playback_lock=playback_lock,
        mute_state=tts_mute_state,
    )
    capture_input = capture_input or CaptureInput(bus, CaptureEngine())
    camera_state = CameraState(settings.camera.enabled)
    camera_capture = CameraCapture(settings.camera, camera_state)
    sound_cues = SoundCuePlayer(settings.sound_cues, playback_lock=playback_lock)
    memory_file_specs = build_memory_file_specs(settings.memory)
    memory_loader = MemoryFileLoader(memory_file_specs, logger=logger)
    memory_file_repository = MemoryFileRepository(memory_file_specs)
    thinking_mode = ReasoningLevelState(bus)

    async def on_camera_capture(source: str) -> None:
        await bus.publish(CameraCaptureSucceeded, CameraCaptureSucceeded(source))
        await sound_cues.play("camera_capture")

    async def on_camera_failure(source: str) -> None:
        await bus.publish(CameraCaptureFailed, CameraCaptureFailed(source))

    tool_registry = ToolRegistry()
    journal_store = JournalStore(Path(settings.journal.root))
    session_file_repository = SessionFileRepository(
        journal_store.root,
        config=settings.files,
        session_is_visible=lambda sid: bool(journal_store.read_session(sid).records),
    )

    def current_session_file_scope() -> SessionFileScope:
        # Late-bound: journal_recorder is assigned further down in build_app,
        # and this closure only runs during a turn, long after wiring finishes.
        # Rebuilding on every call keeps inherited scopes live (deleted
        # ancestors drop out) per story-v1.8.1.
        current = journal_recorder.session_id if journal_recorder is not None else None
        return resolve_session_file_scope(journal_store, current)

    builtin_tool_provider = BuiltinToolProvider(
        thinking_mode=thinking_mode,
        memory_file_repository=memory_file_repository,
        camera_capture=camera_capture,
        on_camera_capture=on_camera_capture,
        on_camera_failure=on_camera_failure,
        session_file_repository=session_file_repository,
        session_file_scope=current_session_file_scope,
    )
    builtin_tool_provider.register_tools(tool_registry)
    tool_registry.set_tool_enabled(CAMERA_TOOL_NAME, settings.camera.enabled)
    visibility_mode = VisibilityModeState(bus)
    history = ConversationHistory()
    transcript_overlay_repository = TranscriptOverlayRepository(
        journal_store.root,
        JournalStoreEventReferenceResolver(journal_store),
    )
    transcript_text_resolver = TranscriptOverlayTextResolver(
        transcript_overlay_repository
    )
    annotation_overlay_repository = AnnotationOverlayRepository(
        journal_store.root,
        JournalStoreEventReferenceResolver(journal_store),
    )
    archive_overlay_repository = ArchiveOverlayRepository(journal_store.root)
    # One adapter shared by the planner and the executor - JournalStore-
    # backed session/media I/O is not duplicated between the read-only plan
    # (task v1.8.0-24) and the executor that actually deletes files (task
    # v1.8.0-25).
    consolidation_source = JournalStoreConsolidationSource(journal_store)
    consolidation_planner = ConsolidationPlanner(
        consolidation_source,
        transcript_overlay_repository,
        annotation_overlay_repository,
    )
    consolidation_executor = ConsolidationExecutor(
        consolidation_planner, consolidation_source, archive_overlay_repository
    )
    journal_search_index = JournalSearchIndex(
        journal_store,
        journal_store.root,
        transcripts=transcript_text_resolver,
    )
    history_corpus_repository = journal_search_index.repository
    semantic_index_embedder = OllamaEmbeddingProvider(
        settings.backend,
        settings.history.semantic,
    )
    # Shared across both semantic indices so one per-turn query embedding is
    # computed once and reused by the second index instead of a second forward
    # pass (task v1.8.0-23 retrieval contract).
    semantic_query_embedder = CachingQueryEmbeddingProvider(
        OllamaEmbeddingProvider(
            settings.backend,
            settings.history.semantic,
            connect_timeout_seconds=settings.history.semantic.timeout_seconds,
            read_timeout_seconds=settings.history.semantic.timeout_seconds,
        )
    )
    semantic_projection = SemanticPassageIndex(
        history_corpus_repository,
        journal_store.root,
        settings.history.semantic,
        semantic_index_embedder,
        logger=logger,
        query_embedder=semantic_query_embedder,
        transcripts=transcript_text_resolver,
    )
    annotation_search_index = AnnotationSearchIndex(
        annotation_overlay_repository,
        journal_store.root,
    )
    annotation_semantic_index = AnnotationSemanticIndex(
        annotation_overlay_repository,
        journal_store.root,
        settings.history.semantic,
        semantic_index_embedder,
        logger=logger,
        query_embedder=semantic_query_embedder,
    )
    history_retrieval_service = HistoryRetrievalService(
        history_corpus_repository,
        semantic_projection,
        settings.history.semantic,
        Pymorphy3Normalizer(),
        annotation_lexical=annotation_search_index,
        annotation_semantic=annotation_semantic_index,
        annotation_repository=annotation_overlay_repository,
    )
    history_tool_provider = HistoryToolProvider(
        repository=history_corpus_repository,
        retrieval_service=history_retrieval_service,
        solo_session_state=solo_session_state,
        # journal_recorder is assigned later in this same function; by the
        # time this closure is actually called (a live tool invocation,
        # long after build_app() returns) it is always bound.
        current_session_id=(
            lambda: journal_recorder.session_id
            if journal_recorder is not None
            else None
        ),
    )
    history_tool_provider.register_tools(tool_registry)
    transcription_service = (
        _build_transcription_service(
            settings,
            journal_store,
            backend,
            transcript_overlay_repository,
        )
        if settings.history.transcription.enabled
        else None
    )
    annotation_generation_service = (
        _build_annotation_generation_service(
            settings,
            history_corpus_repository,
            backend,
            annotation_overlay_repository,
            bus,
        )
        if settings.history.annotation.enabled
        else None
    )
    history_projection_lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(
            CorpusHistoryProjection(history_corpus_repository),
            TranscriptHistoryProjection(transcript_overlay_repository),
            AnnotationHistoryProjection(annotation_overlay_repository),
            ArchiveHistoryProjection(archive_overlay_repository),
        ),
        semantic_projection=semantic_projection,
        logger=logger,
        transcript_event_source=JournalStoreTranscriptionSource(journal_store),
        annotation_projections=(
            annotation_search_index,
            annotation_semantic_index,
        ),
        annotation_source=annotation_overlay_repository,
    )
    journal_history_service = JournalHistoryService(
        journal_store,
        history_projection_lifecycle,
        journal_search_index,
    )
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
        builtin_clients={
            BUILTIN_TOOL_PROVIDER_NAME: builtin_tool_provider,
            HISTORY_TOOL_PROVIDER_NAME: history_tool_provider,
        },
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
        history_retrieval_service=history_retrieval_service,
        text_input_max_chars=settings.clipboard.max_chars,
        system_prompt_provider=(
            lambda solo: memory_loader.compose_system_prompt(
                settings.prompts.system, include_memory=not solo
            )
        ),
        reasoning_prompt_settings=settings.prompts,
        history_limits=_history_limits_from_settings(settings.history),
        max_audio_attachment_clips=settings.attachments.max_audio_clips,
        solo_session_state=solo_session_state,
        session_file_repository=session_file_repository,
        session_file_scope=current_session_file_scope,
        on_turn_start=replay_player.cancel,
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
        history_projection_lifecycle=history_projection_lifecycle,
        journal_history_service=journal_history_service,
        journal_recorder=journal_recorder,
        transcript_overlay_repository=transcript_overlay_repository,
        annotation_overlay_repository=annotation_overlay_repository,
        annotation_generation_service=annotation_generation_service,
        transcription_service=transcription_service,
        archive_overlay_repository=archive_overlay_repository,
        consolidation_planner=consolidation_planner,
        consolidation_executor=consolidation_executor,
        memory_file_repository=memory_file_repository,
        settings=settings,
        mcp_host=mcp_host,
        camera_state=camera_state,
        camera_capture=camera_capture,
        tts_mute_state=tts_mute_state,
        solo_session_state=solo_session_state,
        replay_player=replay_player,
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


def _tts_health(is_enabled: bool, language: str) -> ModuleHealth:
    # Mirrors _microphone_health/_camera_health: seeds the honest muted/
    # ready distinction (module_health.py's own transition rules apply
    # afterward) so a muted-by-default config never starts the session
    # looking like an unremarkable "unavailable" chip.
    return ModuleHealth(
        module=ModuleId.TTS,
        status=HealthStatus.OK if is_enabled else HealthStatus.UNAVAILABLE,
        detail=ui_text(
            "tts_detail_ready" if is_enabled else "tts_detail_muted", language
        ),
    )


def _seed_tts_module_health(app: App, live_console: LiveStatusConsole) -> None:
    # None only for test fixtures that construct App(...) directly without
    # build_app() (matches visibility_mode/mcp_host's own None convention).
    if app.tts_mute_state is None or live_console.transport is None:
        return
    live_console.transport.set_module_health(
        _tts_health(app.tts_mute_state.enabled, app.settings.ui.language)
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
        tts_mute_state=app.tts_mute_state,
        solo_session_state=app.solo_session_state,
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
    _seed_tts_module_health(app, live_console)

    async def on_runtime_state_changed(event: RuntimeStateChanged) -> None:
        substatus = event.substatus_text
        if substatus is None and event.substatus_key is not None:
            substatus = ui_text(event.substatus_key, app.settings.ui.language)
        _push_runtime_state(live_console, event.state, substatus)

    async def on_tool_enablement_changed(event: ToolEnablementChanged) -> None:
        # No payload on the event: the whole registry is re-read, so a row
        # can never keep a state the engine no longer holds.
        del event
        if app.mcp_host is None or live_console.transport is None:
            return
        live_console.transport.set_mcp_state(
            mcp_state_payload(app.mcp_host.status, app.mcp_host.registry.all())
        )

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
        subscriptions.append((ToolEnablementChanged, on_tool_enablement_changed))
        app.bus.subscribe(ToolEnablementChanged, on_tool_enablement_changed)
    return subscriptions


async def _on_full_response_complete(app: App, event: ResponseComplete) -> None:
    """Finishes a response in the order required by the audio pipeline.

    Gated on claim_turn_end() (task-v1.7.0-2 review finding 1): the
    backend task can finish - publishing this very event - while trailing
    TTS is still playing, i.e. while this handler would still be running;
    if a hotkey interrupt lands in that window, _cancel_current_turn()
    may already have ended the turn by the time this runs. Recording
    history or scheduling more speech for an already-ended turn would be
    wrong, so a lost claim means this whole handler is a no-op, not just
    its finish sequence."""
    if not app.orchestrator.claim_turn_end():
        return
    try:
        await app.tts_output.on_response_complete(event)  # flushes trailing sentence
        await app.orchestrator.on_response_complete(event)  # records history
        await app.tts_output.wait_for_pending()  # waits for ALL of this turn's speech
    except asyncio.CancelledError:
        # An interrupt's tts_output.cancel() (task-v1.7.0-2) cancelled the
        # same pending tasks wait_for_pending() was gathering, which
        # bus.py's publish() re-raises rather than swallows - not a
        # failure, the turn legitimately ended via interrupt. Falls
        # through to finally and the listening cue below exactly like a
        # normal completion, instead of leaving neither cue played.
        pass
    except Exception:
        # task-v1.7.0-3 (review, second round): considered and rejected
        # calling record_aborted_turn() here. The real TtsOutput.on_response_
        # complete() only performs synchronous, in-memory buffer operations
        # and cannot raise; every real synthesis/playback failure surfaces
        # later, through wait_for_pending() - by which point orchestrator.
        # on_response_complete() above has already recorded this turn
        # normally, so calling record_aborted_turn() here would double it.
        # There is no reachable sub-case left to record.
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


async def _cancel_current_turn(app: App) -> bool:
    """The shared cancellation core (task-v1.7.0-2 story design decision
    "both mechanisms share one cancellation core"): stops the in-flight
    backend request and TTS playback and returns Jarvis to listening.
    Both the interrupt hotkey and task 4's future experimental voice
    trigger call this directly.

    Stopping playback/generation is unconditional on being busy - it is
    NOT gated on claim_turn_end() (review finding 1, round 2): gating it
    meant that once ResponseComplete had fired and
    _on_full_response_complete() was already draining trailing TTS via
    wait_for_pending() - the single most common moment someone actually
    wants to interrupt - _on_full_response_complete() had already won the
    claim, so the hotkey did nothing at all until Jarvis finished talking
    on its own. Cancelling first and claiming after fixes this: even when
    the claim is lost, tts_output.cancel() has already cancelled the same
    pending tasks _on_full_response_complete() may be blocked on in
    wait_for_pending(), which is what lets its own finally block (and
    thus finish_turn()/TurnCompleted) complete promptly instead of
    waiting out the rest of the speech - see bus.py's publish(), which
    re-raises a subscriber's CancelledError rather than swallowing it.

    claim_turn_end() still decides who runs the finish sequence itself
    (busy-clear/TurnCompleted/cue) exactly once (review finding 1, round
    1) - only the stopping action moved outside that gate.

    Returns whether there was actually a turn to cancel, mostly useful
    for tests/logging - callers do not need to act on it. Requiring busy
    first is also what makes pressing the hotkey while idle a true
    no-op."""
    if not app.orchestrator.is_busy:
        return False
    app.orchestrator.cancel_active_turn()
    app.tts_output.cancel()
    if not app.orchestrator.claim_turn_end():
        return True
    # task-v1.7.0-3: record what this turn had produced (possibly nothing)
    # before finishing it - the loser of claim_turn_end() (a concurrent
    # _on_full_response_complete()) would have recorded the turn normally
    # instead, so this only ever runs for a turn that genuinely never
    # completed on its own.
    await app.orchestrator.record_aborted_turn(outcome=TurnOutcome.INTERRUPTED)
    await app.orchestrator.finish_turn(
        cooldown_seconds=app.settings.vad.resume_cooldown_seconds
    )
    await app.bus.publish(TurnCompleted, TurnCompleted())
    await app.sound_cues.play("listening")
    return True


async def _on_interrupt_requested(app: App, event: InterruptRequested) -> None:
    """The hotkey's handler (task-v1.7.0-2) - see _cancel_current_turn().

    Also stops an in-progress replay (story-v1.8.2): reject-when-busy means
    a live turn and a replay never run at once, so at most one of these two
    actually cancels anything; cancel() is a no-op when its target is idle."""
    await _cancel_current_turn(app)
    if app.replay_player is not None:
        app.replay_player.cancel()


async def replay_reply(app: App, reference: JournalEventRef) -> ReplayOutcome | None:
    """Re-listen to a past assistant reply (story-v1.8.2 task 1). Returns
    None when replay is unavailable (no player/store, or the reference is
    not an assistant reply), else the ReplayPlayer outcome. Rejected
    attempts (a live turn is speaking, TTS is off, nothing speakable, or a
    replay is already running) beep and publish a visible error rather than
    queueing. The chat-log Play control (task 2) calls this."""
    if app.replay_player is None or app.journal_store is None:
        return None
    if app.orchestrator.is_busy:
        await _reject_replay(app, "replay_busy")
        return ReplayOutcome.BUSY
    text = reply_speech_text(app.journal_store, reference)
    if text is None:
        await _reject_replay(app, "replay_unavailable")
        return None
    outcome = await app.replay_player.replay(text)
    if outcome is ReplayOutcome.BUSY:
        await _reject_replay(app, "replay_busy")
    elif outcome is ReplayOutcome.DISABLED:
        await _reject_replay(app, "replay_tts_disabled")
    elif outcome is ReplayOutcome.EMPTY:
        await _reject_replay(app, "replay_unavailable")
    return outcome


async def _run_reply_replay(app: App, reference: JournalEventRef) -> str:
    """Runs a replay and holds until it ends (story-v1.8.2 task 2): the
    transport keeps the HTTP request open for this coroutine's lifetime, so
    the UI toggles Play<->Stop off the request alone, with no separate
    replay-lifecycle event channel."""
    outcome = await replay_reply(app, reference)
    if outcome is ReplayOutcome.STARTED and app.replay_player is not None:
        await app.replay_player.wait_for_pending()
    return outcome.value if outcome is not None else "unavailable"


def _stop_reply_replay(app: App) -> None:
    if app.replay_player is not None:
        app.replay_player.cancel()


def _pause_reply_replay(app: App) -> bool:
    if app.replay_player is None:
        return False
    return app.replay_player.pause()


def _resume_reply_replay(app: App) -> bool:
    if app.replay_player is None:
        return False
    return app.replay_player.resume()


async def _reject_replay(app: App, ui_text_key: str) -> None:
    await app.sound_cues.play("error")
    await publish_system_event(
        app.bus,
        logger,
        source="TTS",
        level=EventLevel.WARN,
        log_message=f"Replay rejected: {ui_text_key}",
        ui_message=ui_text(ui_text_key, app.settings.ui.language),
    )


async def _on_tts_speech_enabled_changed(
    app: App, event: TtsSpeechEnabledChanged
) -> None:
    """Stops whatever is speaking the instant the user disables TTS.

    Mute-gating (on_token/on_response_complete) reads the state owner
    directly (see tts.py); this is the other half. A global TTS-off must
    silence a live turn AND an in-flight replay (story-v1.8.2: disabling
    TTS disables it completely), mirroring the barge-in interrupt."""
    if event.enabled:
        return
    app.tts_output.cancel()
    if app.replay_player is not None:
        app.replay_player.cancel()


async def _on_mic_sleep_toggled(app: App, event: MicSleepToggled) -> None:
    """Publishes UI/log feedback and plays the sleep/wake cue."""
    awake = event.is_awake
    if app.audio_input.capture_failed:
        # The toggle still flips AudioInput's own state, but no loop is
        # left to observe it, so announcing "awake" would restate the
        # original lie: a healthy-looking microphone that hears nothing.
        # WARN, not ERROR - the failure was already reported once when it
        # happened; this only answers a keypress. The sleep cue plays in
        # both directions because "not capturing" is true either way.
        await publish_system_event(
            app.bus,
            logger,
            source="HOTKEY",
            level=EventLevel.WARN,
            log_message="Microphone sleep toggle ignored: capture stopped",
            ui_message=ui_text(
                "mic_toggle_after_capture_failed", app.settings.ui.language
            ),
        )
        await app.sound_cues.play("mic_sleep")
        return
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


async def _on_microphone_capture_failed(
    app: App, event: MicrophoneCaptureFailed
) -> None:
    """Says out loud that Jarvis has gone deaf.

    The system log carries the driver's own reason, because that is what
    a problem report needs; the events panel gets the localized fact plus
    what to do about it, and no device name - a device name is
    payload-adjacent under the two-log content rule."""
    await publish_system_event(
        app.bus,
        logger,
        source="STT",
        level=EventLevel.ERROR,
        log_message=f"Microphone capture stopped: {event.reason}",
        ui_message=ui_text("microphone_capture_failed", app.settings.ui.language),
    )


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

    async def on_microphone_capture_failed(event: MicrophoneCaptureFailed) -> None:
        await _on_microphone_capture_failed(app, event)

    async def on_reasoning_level_changed(event: ReasoningLevelChanged) -> None:
        await _on_reasoning_level_changed(app, event)

    async def on_interrupt_requested(event: InterruptRequested) -> None:
        await _on_interrupt_requested(app, event)

    async def on_tts_speech_enabled_changed(event: TtsSpeechEnabledChanged) -> None:
        await _on_tts_speech_enabled_changed(app, event)

    subscriptions: list[Subscription] = [
        (UtteranceChunk, app.orchestrator.on_utterance),
        # Unconditional, like every subscription here: on_utterance_captured
        # checks recording() itself and does nothing in a normal run, so
        # wiring it does not need to know whether debug is on.
        (UtteranceChunk, on_utterance_captured),
        (ScreenshotCaptured, app.orchestrator.on_screenshot),
        (ClipboardSubmitted, app.orchestrator.on_clipboard),
        (ResponseToken, app.tts_output.on_token),
        (ResponseToken, app.orchestrator.on_response_token),
        (ResponseComplete, on_full_response_complete),
        (MicSleepToggled, on_mic_sleep_toggled),
        (MicrophoneCaptureFailed, on_microphone_capture_failed),
        (ReasoningLevelChanged, on_reasoning_level_changed),
        (InterruptRequested, on_interrupt_requested),
        (TtsSpeechEnabledChanged, on_tts_speech_enabled_changed),
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
        if app.history_projection_lifecycle is not None:
            logger.info("Shutdown: flushing pending history projection writes")
            await app.history_projection_lifecycle.close()
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
    debug: bool = False,
) -> None:
    # The invariant lives here, not only in parse_args(): run() is an entry
    # point of its own, and once a later slice keys transcript recording off
    # this flag, a caller reaching run() directly could otherwise record an
    # entire session with nothing on screen saying so. The CLI gate is the
    # friendly error; this is the one that cannot be bypassed.
    if debug and live_console is None:
        raise ValueError(
            "debug mode requires the Status Console: it is the surface that "
            "warns privacy is not guaranteed while the exchange is recorded"
        )
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
    #
    # story-v1.6.4-task-1: stderr alone lost all of it again the moment
    # Jarvis was started outside a terminal, which is how a user runs it.
    # configure_logging() keeps this stream output and adds a rotating
    # local file, so a problem report can carry the detailed English
    # stream that publish_system_event()'s log_message has always
    # produced. Settings must load first now: the log directory is
    # configured, not hardcoded.
    settings = settings or load_settings()
    configure_logging(settings.logging)
    if debug:
        transcript_path = configure_debug_transcript(settings.logging)
    else:
        # Explicit, not implied by "we did not enable it": the transcript
        # logger is module state that survives a run, so a second run in
        # the same process would inherit the first one's sink.
        disable_debug_transcript()
        transcript_path = None
    announce_debug_mode(debug, transcript_path)
    ensure_generated(settings.sound_cues)

    app = app or build_app(settings)
    await _start_history_projection_lifecycle(app)
    if debug:
        await _announce_debug_mode_to_panel(app, settings.ui.language)
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
            asyncio.create_task(
                run_interrupt_hotkey_listener(app.bus, settings.hotkeys)
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
            if live_console is not None and live_console.transport is not None:
                await live_console.transport.stop()
            if live_console is not None:
                live_console.close()


async def _start_history_projection_lifecycle(app: App) -> None:
    if app.history_projection_lifecycle is None:
        return
    await app.history_projection_lifecycle.start()


def run_with_status_console(
    settings: Settings | None = None,
    *,
    include_touchstrip: bool = True,
    debug: bool = False,
) -> None:
    settings = settings or load_settings()
    app = build_app(settings)
    if app.journal_history_service is None:
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
            tts_enabled=(
                app.tts_mute_state.enabled
                if app.tts_mute_state is not None
                else settings.tts.enabled
            ),
            solo_session_enabled=(
                app.solo_session_state.enabled
                if app.solo_session_state is not None
                else False
            ),
            language=settings.ui.language,
            config_values=config_values_payload(settings),
            debug=debug,
        ),
        logger=logger,
        journal_history_service=app.journal_history_service,
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
        journal_transcript_repository=app.transcript_overlay_repository,
        journal_transcription_service=app.transcription_service,
        journal_annotation_repository=app.annotation_overlay_repository,
        journal_annotation_generation_service=app.annotation_generation_service,
        journal_consolidation_planner=app.consolidation_planner,
        journal_consolidation_executor=app.consolidation_executor,
        memory_file_repository=app.memory_file_repository,
        journal_reply_replay_handler=lambda reference: _run_reply_replay(
            app, reference
        ),
        journal_reply_replay_stop_handler=lambda: _stop_reply_replay(app),
        journal_reply_replay_pause_handler=lambda: _pause_reply_replay(app),
        journal_reply_replay_resume_handler=lambda: _resume_reply_replay(app),
        max_audio_attachment_clips=settings.attachments.max_audio_clips,
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
            await _start_history_projection_lifecycle(app)
            transport_info = await live_console.transport.start()
            live_console.load_transport_urls(transport_info)
            await run(
                settings=settings, app=app, live_console=live_console, debug=debug
            )

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
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "record the model exchange for diagnosis; requires --status-console, "
            "which is where the debug and privacy warnings are shown"
        ),
    )
    args = parser.parse_args(argv)
    if args.debug and not args.status_console:
        # The console banner is the consent surface: debug lifts the
        # content rule that both logs otherwise keep, so a run that
        # records the exchange must also be a run that says so on screen.
        # A headless debug session would be a recording with nobody told.
        parser.error("--debug requires --status-console")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.status_console:
        run_with_status_console(
            include_touchstrip=not args.no_touchstrip, debug=args.debug
        )
    else:
        asyncio.run(run())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
