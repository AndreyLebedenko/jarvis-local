"""Run modes and the one policy that says which control-plane actions a mode
allows.

`NORMAL` is the dialog assistant. `MCP` (`--mcp-mode`) is the voice guide: it
accepts no user input into the model, so every control that submits input or
changes dialog settings is refused here, and nowhere else. The Status Console
transport consults this policy for every WebSocket control command and every
HTTP route; the UI greys out the same actions from the run-mode snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class RunMode(Enum):
    NORMAL = "normal"
    MCP = "mcp"


class ControlAction(Enum):
    """Every action a Status Console client can ask for. The first group are
    WebSocket control commands, named exactly as the command; the rest are the
    HTTP routes, grouped by what they do."""

    TOGGLE_THINKING = "toggle_thinking"
    SET_REASONING_LEVEL = "set_reasoning_level"
    SET_RESPONSE_MODE = "set_response_mode"
    SET_MCP_ENABLED = "set_mcp_enabled"
    SET_TTS_ENABLED = "set_tts_enabled"
    SET_SOLO_SESSION_ENABLED = "set_solo_session_enabled"
    SET_TOOL_ENABLED = "set_tool_enabled"
    RESET_CONTEXT = "reset_context"
    RESET_MODULE = "reset_module"
    SET_VISIBILITY_MODE = "set_visibility_mode"
    REQUEST_SHUTDOWN = "request_shutdown"
    REQUEST_MODEL_OPTIONS = "request_model_options"
    REQUEST_MICROPHONE_OPTIONS = "request_microphone_options"
    SAVE_CONFIG_SELECTION = "save_config_selection"

    UI_SHELL = "ui_shell"
    JOURNAL_READ = "journal_read"
    JOURNAL_INPUT = "journal_input"
    JOURNAL_NEW_CONTEXT = "journal_new_context"
    JOURNAL_FORK = "journal_fork"
    JOURNAL_DELETE_SESSION = "journal_delete_session"
    TRANSCRIPT_EDIT = "transcript_edit"
    TRANSCRIPT_GENERATE = "transcript_generate"
    REPLAY = "replay"
    ANNOTATION_GENERATE = "annotation_generate"
    ANNOTATION_EDIT = "annotation_edit"
    CONSOLIDATION_EXECUTE = "consolidation_execute"
    MEMORY_FILE_READ = "memory_file_read"
    MEMORY_FILE_WRITE = "memory_file_write"


class Verdict(Enum):
    ALLOWED = "allowed"
    REFUSED = "refused"


class RefusalReason(Enum):
    MCP_MODE = "mcp_mode"


_A = ControlAction
_ALLOWED = Verdict.ALLOWED
_REFUSED = Verdict.REFUSED

# Exhaustive on purpose: an action added later has no verdict until someone
# writes one here (RunModePolicy checks coverage at construction).
MCP_MODE_VERDICTS: Mapping[ControlAction, Verdict] = MappingProxyType(
    {
        _A.TOGGLE_THINKING: _REFUSED,
        _A.SET_REASONING_LEVEL: _REFUSED,
        _A.SET_RESPONSE_MODE: _REFUSED,
        _A.SET_MCP_ENABLED: _REFUSED,
        _A.SET_TTS_ENABLED: _ALLOWED,
        _A.SET_SOLO_SESSION_ENABLED: _REFUSED,
        _A.SET_TOOL_ENABLED: _REFUSED,
        _A.RESET_CONTEXT: _REFUSED,
        _A.RESET_MODULE: _ALLOWED,
        _A.SET_VISIBILITY_MODE: _ALLOWED,
        _A.REQUEST_SHUTDOWN: _ALLOWED,
        _A.REQUEST_MODEL_OPTIONS: _ALLOWED,
        _A.REQUEST_MICROPHONE_OPTIONS: _ALLOWED,
        _A.SAVE_CONFIG_SELECTION: _ALLOWED,
        _A.UI_SHELL: _ALLOWED,
        _A.JOURNAL_READ: _ALLOWED,
        _A.JOURNAL_INPUT: _REFUSED,
        _A.JOURNAL_NEW_CONTEXT: _REFUSED,
        _A.JOURNAL_FORK: _REFUSED,
        _A.JOURNAL_DELETE_SESSION: _ALLOWED,
        _A.TRANSCRIPT_EDIT: _ALLOWED,
        _A.TRANSCRIPT_GENERATE: _ALLOWED,
        _A.REPLAY: _ALLOWED,
        _A.ANNOTATION_GENERATE: _ALLOWED,
        _A.ANNOTATION_EDIT: _ALLOWED,
        _A.CONSOLIDATION_EXECUTE: _ALLOWED,
        _A.MEMORY_FILE_READ: _ALLOWED,
        _A.MEMORY_FILE_WRITE: _ALLOWED,
    }
)

_VERDICTS_BY_MODE: Mapping[RunMode, Mapping[ControlAction, Verdict]] = MappingProxyType(
    {
        RunMode.NORMAL: MappingProxyType(dict.fromkeys(ControlAction, _ALLOWED)),
        RunMode.MCP: MCP_MODE_VERDICTS,
    }
)

_REFUSAL_REASON_BY_MODE: Mapping[RunMode, RefusalReason] = MappingProxyType(
    {RunMode.MCP: RefusalReason.MCP_MODE}
)


@dataclass(frozen=True)
class ActionRefusal:
    action: ControlAction
    reason: RefusalReason


class ActionRefusedError(Exception):
    def __init__(self, refusal: ActionRefusal) -> None:
        super().__init__(f"{refusal.action.value} is refused ({refusal.reason.value})")
        self.refusal = refusal


class RunModePolicy:
    def __init__(self, run_mode: RunMode) -> None:
        verdicts = _VERDICTS_BY_MODE[run_mode]
        missing = set(ControlAction) - set(verdicts)
        if missing:
            names = ", ".join(sorted(action.value for action in missing))
            raise ValueError(f"no {run_mode.value} verdict for: {names}")
        self._run_mode = run_mode
        self._verdicts = verdicts

    @property
    def run_mode(self) -> RunMode:
        return self._run_mode

    def verdict(self, action: ControlAction) -> Verdict:
        return self._verdicts[action]

    def refusal(self, action: ControlAction) -> ActionRefusal | None:
        if self._verdicts[action] is Verdict.ALLOWED:
            return None
        return ActionRefusal(action, _REFUSAL_REASON_BY_MODE[self._run_mode])

    def check(self, action: ControlAction) -> None:
        refusal = self.refusal(action)
        if refusal is not None:
            raise ActionRefusedError(refusal)

    def refused_actions(self) -> tuple[ControlAction, ...]:
        return tuple(
            action
            for action in ControlAction
            if self._verdicts[action] is Verdict.REFUSED
        )
