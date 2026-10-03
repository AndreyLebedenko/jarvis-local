import inspect
from pathlib import Path

import pytest
from aiohttp.web_urldispatcher import StaticResource

from jarvis import app as app_module
from jarvis.app import parse_args
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    MCP_MODE_CANVAS_SPEECH_VALUES,
    ConfigError,
    McpModeSettings,
    Settings,
    load_settings,
)
from jarvis.core.run_mode import (
    MCP_MODE_VERDICTS,
    ActionRefusal,
    ActionRefusedError,
    ControlAction,
    RefusalReason,
    RunMode,
    RunModePolicy,
    Verdict,
)
from jarvis.core.single_instance import ALREADY_RUNNING_EXIT_CODE, HeldInstance
from jarvis.journal.external_canvas import SpeechOrigin
from jarvis.mcp_mode.server import McpPortUnavailableError
from jarvis.mcp_mode.token import McpTokenFileError
from jarvis.ui.status_console import StatusConsoleApi
from jarvis.ui.transport import ROUTES, UiTransportServer

# --- flag --------------------------------------------------------------------


def test_mcp_mode_is_off_unless_asked_for():
    assert parse_args([]).mcp_mode is False


@pytest.mark.parametrize(
    "argv",
    [
        ["--mcp-mode"],
        ["--mcp-mode", "--status-console"],
        ["--status-console", "--mcp-mode", "--no-touchstrip"],
        ["--status-console", "--mcp-mode", "--debug"],
    ],
)
def test_mcp_mode_combines_with_the_other_flags(argv):
    args = parse_args(argv)

    assert args.mcp_mode is True
    assert args.status_console is ("--status-console" in argv)
    assert args.no_touchstrip is ("--no-touchstrip" in argv)
    assert args.debug is ("--debug" in argv)


def test_mcp_mode_keeps_debug_requiring_the_status_console():
    with pytest.raises(SystemExit):
        parse_args(["--mcp-mode", "--debug"])


class _HeldGuard(HeldInstance):
    def __init__(self) -> None:
        pass

    def release(self) -> None:
        pass


def test_main_carries_mcp_mode_into_the_status_console_launch(monkeypatch):
    launches: list[dict] = []
    monkeypatch.setattr(
        app_module, "run_with_status_console", lambda **kwargs: launches.append(kwargs)
    )

    app_module.main(["--status-console", "--mcp-mode"], acquire=_HeldGuard)

    assert launches[0]["run_mode"] is RunMode.MCP


def test_main_carries_mcp_mode_into_a_headless_run(monkeypatch):
    run_modes: list[RunMode] = []

    async def fake_run(run_mode: RunMode) -> None:
        run_modes.append(run_mode)

    monkeypatch.setattr(app_module, "run", fake_run)

    app_module.main(["--mcp-mode"], acquire=_HeldGuard)

    assert run_modes == [RunMode.MCP]


@pytest.mark.parametrize(
    "error",
    [
        McpTokenFileError(Path("mcp_mode.token"), "is empty"),
        McpPortUnavailableError(47821, "address in use"),
    ],
)
def test_a_headless_mcp_mode_startup_failure_exits_with_its_own_code_and_message(
    monkeypatch, capsys, error
):
    async def failing_run(run_mode: RunMode) -> None:
        raise error

    monkeypatch.setattr(app_module, "run", failing_run)

    with pytest.raises(SystemExit) as raised:
        app_module.main(["--mcp-mode"], acquire=_HeldGuard)

    assert raised.value.code == app_module.MCP_MODE_STARTUP_FAILED_EXIT_CODE
    assert raised.value.code not in (0, 1, ALREADY_RUNNING_EXIT_CODE)
    assert str(error) in capsys.readouterr().err


# --- [mcp_mode] config ----------------------------------------------------------


def _load(tmp_path, body: str) -> Settings:
    config_path = tmp_path / "config.toml"
    config_path.write_text(body, encoding="utf-8")
    return load_settings(config_path, ui_path=tmp_path / "no-such-config.ui.toml")


def test_the_canvas_speech_setting_offers_exactly_the_speech_origins():
    """core.config is stdlib-only (conftest.assert_stdlib_only_imports), so it
    cannot import SpeechOrigin and spells the two accepted values itself. This
    is the one place that keeps the two spellings from drifting."""
    assert set(MCP_MODE_CANVAS_SPEECH_VALUES) == {
        SpeechOrigin.DERIVATIVE.value,
        SpeechOrigin.VERBATIM.value,
    }


def test_mcp_mode_section_defaults():
    assert Settings().mcp_mode == McpModeSettings(
        port=47821,
        token_file="mcp_mode.token",
        canvas_speech="derivative",
        max_canvas_chars=40000,
        max_guidance_chars=2000,
        max_spoken_text_chars=8000,
        queue_capacity=8,
    )


def test_mcp_mode_section_parses_from_config(tmp_path):
    settings = _load(
        tmp_path,
        """
        [mcp_mode]
        port = 50123
        token_file = ".local/mcp.token"
        canvas_speech = "verbatim"
        max_canvas_chars = 1000
        max_guidance_chars = 10
        max_spoken_text_chars = 20
        queue_capacity = 2
        """,
    )

    assert settings.mcp_mode == McpModeSettings(
        port=50123,
        token_file=".local/mcp.token",
        canvas_speech="verbatim",
        max_canvas_chars=1000,
        max_guidance_chars=10,
        max_spoken_text_chars=20,
        queue_capacity=2,
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("port = 80", "unprivileged port"),
        ("port = 70000", "unprivileged port"),
        ('token_file = "  "', "token_file must not be empty"),
        ('canvas_speech = "caller"', "canvas_speech must be one of"),
        ("max_canvas_chars = 0", "max_canvas_chars must be a positive int"),
        ("max_guidance_chars = -1", "max_guidance_chars must be a positive int"),
        ("max_spoken_text_chars = 0", "max_spoken_text_chars must be a positive int"),
        ("queue_capacity = 0", "queue_capacity must be a positive int"),
        ("queue_capacity = true", "queue_capacity must be int"),
        ('host = "0.0.0.0"', "Unknown key"),
    ],
)
def test_mcp_mode_section_rejects_invalid_values(tmp_path, line, message):
    with pytest.raises(ConfigError, match=message):
        _load(tmp_path, f"[mcp_mode]\n{line}\n")


# --- the policy ---------------------------------------------------------------

_REFUSED_IN_MCP_MODE = {
    ControlAction.TOGGLE_THINKING,
    ControlAction.SET_REASONING_LEVEL,
    ControlAction.SET_RESPONSE_MODE,
    ControlAction.SET_MCP_ENABLED,
    ControlAction.SET_SOLO_SESSION_ENABLED,
    ControlAction.SET_TOOL_ENABLED,
    ControlAction.RESET_CONTEXT,
    ControlAction.JOURNAL_INPUT,
    ControlAction.JOURNAL_NEW_CONTEXT,
    ControlAction.JOURNAL_FORK,
}


def test_mcp_mode_has_an_explicit_verdict_for_every_action():
    assert set(MCP_MODE_VERDICTS) == set(ControlAction)


def test_the_mcp_mode_verdicts_cannot_be_changed_at_runtime():
    with pytest.raises(TypeError):
        MCP_MODE_VERDICTS[ControlAction.JOURNAL_INPUT] = Verdict.ALLOWED


def test_mcp_mode_refuses_exactly_input_and_dialog_setting_actions():
    policy = RunModePolicy(RunMode.MCP)

    refused = {action for action in ControlAction if policy.refusal(action)}

    assert refused == _REFUSED_IN_MCP_MODE
    assert set(policy.refused_actions()) == _REFUSED_IN_MCP_MODE


def test_normal_mode_allows_every_action():
    policy = RunModePolicy(RunMode.NORMAL)

    assert all(policy.verdict(action) is Verdict.ALLOWED for action in ControlAction)
    assert policy.refused_actions() == ()


def test_a_refusal_names_the_action_and_the_typed_reason():
    policy = RunModePolicy(RunMode.MCP)

    with pytest.raises(ActionRefusedError) as raised:
        policy.check(ControlAction.JOURNAL_INPUT)

    assert raised.value.refusal == ActionRefusal(
        ControlAction.JOURNAL_INPUT, RefusalReason.MCP_MODE
    )


# --- every API method and route has a verdict ----------------------------------

_API_WIRING_METHODS = {"set_loop", "set_shutdown_event"}


class _NoControlApi:
    pass


def test_every_status_console_api_control_is_a_policy_checked_command():
    api_methods = {
        name
        for name, _ in inspect.getmembers(StatusConsoleApi, inspect.isfunction)
        if not name.startswith("_")
    } - _API_WIRING_METHODS
    server = UiTransportServer(EventBus(), _NoControlApi())

    commands = {action.value for action in server.control_commands()}

    assert commands == api_methods


async def test_the_server_registers_only_the_route_table_and_the_static_files():
    server = UiTransportServer(
        EventBus(), _NoControlApi(), token_factory=lambda: "valid-token"
    )
    await server.start()
    try:
        routes = [
            route
            for route in server._runner.app.router.routes()
            if route.method != "HEAD"
        ]
    finally:
        await server.stop()

    static = [route for route in routes if isinstance(route.resource, StaticResource)]
    assert len(static) == 1
    assert len(routes) - len(static) == len(ROUTES)


# Every HTTP route and the action it is checked as. A new route fails
# test_every_route_is_checked_as_the_action_it_performs until it is listed
# here, so it cannot slip in under an allowed action by accident.
EXPECTED_ROUTE_ACTIONS = {
    ("GET", "/"): ControlAction.UI_SHELL,
    ("GET", "/ws"): ControlAction.UI_SHELL,
    ("GET", "/api/journal/sessions"): ControlAction.JOURNAL_READ,
    ("GET", "/api/journal/usage"): ControlAction.JOURNAL_READ,
    ("GET", "/api/journal/sessions/{session_id}"): ControlAction.JOURNAL_READ,
    ("GET", "/api/journal/search"): ControlAction.JOURNAL_READ,
    (
        "GET",
        "/api/journal/transcripts/{session_id}/{event_position}",
    ): ControlAction.JOURNAL_READ,
    ("GET", "/api/journal/annotations/{session_id}"): ControlAction.JOURNAL_READ,
    (
        "GET",
        "/api/journal/annotations/{session_id}/{annotation_id}",
    ): ControlAction.JOURNAL_READ,
    ("GET", "/api/journal/consolidation/{session_id}"): ControlAction.JOURNAL_READ,
    (
        "GET",
        "/api/journal/consolidation/{session_id}/status",
    ): ControlAction.JOURNAL_READ,
    (
        "GET",
        "/api/journal/media/{session_id}/{media_path:.*}",
    ): ControlAction.JOURNAL_READ,
    ("POST", "/api/journal/input"): ControlAction.JOURNAL_INPUT,
    ("POST", "/api/journal/context/new"): ControlAction.JOURNAL_NEW_CONTEXT,
    (
        "POST",
        "/api/journal/sessions/{session_id}/fork",
    ): ControlAction.JOURNAL_FORK,
    (
        "DELETE",
        "/api/journal/sessions/{session_id}",
    ): ControlAction.JOURNAL_DELETE_SESSION,
    (
        "PUT",
        "/api/journal/transcripts/{session_id}/{event_position}",
    ): ControlAction.TRANSCRIPT_EDIT,
    (
        "POST",
        "/api/journal/transcripts/{session_id}/{event_position}/generate",
    ): ControlAction.TRANSCRIPT_GENERATE,
    (
        "POST",
        "/api/journal/replies/{session_id}/{event_position}/replay",
    ): ControlAction.REPLAY,
    (
        "POST",
        "/api/journal/replies/{session_id}/{event_position}/replay-sequence",
    ): ControlAction.REPLAY,
    ("POST", "/api/journal/replies/replay/stop"): ControlAction.REPLAY,
    ("POST", "/api/journal/replies/replay/pause"): ControlAction.REPLAY,
    ("POST", "/api/journal/replies/replay/resume"): ControlAction.REPLAY,
    (
        "POST",
        "/api/journal/annotations/{session_id}/generate",
    ): ControlAction.ANNOTATION_GENERATE,
    (
        "PUT",
        "/api/journal/annotations/{session_id}/{annotation_id}",
    ): ControlAction.ANNOTATION_EDIT,
    (
        "POST",
        "/api/journal/consolidation/{session_id}/execute",
    ): ControlAction.CONSOLIDATION_EXECUTE,
    ("GET", "/api/memory/files/{file_id}"): ControlAction.MEMORY_FILE_READ,
    ("PUT", "/api/memory/files/{file_id}"): ControlAction.MEMORY_FILE_WRITE,
}


def test_every_route_is_checked_as_the_action_it_performs():
    table = [((route.method, route.path), route.action) for route in ROUTES]

    assert len(table) == len(dict(table))
    assert dict(table) == EXPECTED_ROUTE_ACTIONS


def test_mcp_mode_refuses_exactly_the_input_new_context_and_fork_routes():
    policy = RunModePolicy(RunMode.MCP)

    refused = {
        (route.method, route.path) for route in ROUTES if policy.refusal(route.action)
    }

    assert refused == {
        ("POST", "/api/journal/input"),
        ("POST", "/api/journal/context/new"),
        ("POST", "/api/journal/sessions/{session_id}/fork"),
    }
