from pathlib import Path

import pytest

from jarvis import app as app_module
from jarvis.app import parse_args
from jarvis.core.config import PersonalProxySettings, Settings
from jarvis.core.run_mode import RunMode
from jarvis.core.single_instance import HeldInstance
from jarvis.personal_proxy.common.locality import external_locality
from jarvis.personal_proxy.startup.startup import (
    PersonalProxyNotConfiguredError,
    require_configured,
)
from jarvis.ui.contract import DataLocality

# --- flag --------------------------------------------------------------------


def test_the_personal_proxy_is_off_unless_asked_for():
    assert parse_args([]).personal_proxy is False
    assert parse_args(["--status-console"]).personal_proxy is False


def test_the_flag_is_accepted_with_the_status_console():
    args = parse_args(["--status-console", "--personal-proxy"])

    assert args.personal_proxy is True
    assert args.mcp_mode is False


def test_the_flag_requires_the_status_console(capsys):
    with pytest.raises(SystemExit) as raised:
        parse_args(["--personal-proxy"])

    assert raised.value.code != 0
    assert "--personal-proxy requires --status-console" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--personal-proxy", "--mcp-mode"],
        ["--status-console", "--personal-proxy", "--mcp-mode"],
    ],
)
def test_the_flag_excludes_mcp_mode(capsys, argv):
    with pytest.raises(SystemExit) as raised:
        parse_args(argv)

    assert raised.value.code != 0
    assert "--personal-proxy and --mcp-mode" in capsys.readouterr().err


def test_the_flag_combines_with_no_touchstrip():
    args = parse_args(["--status-console", "--personal-proxy", "--no-touchstrip"])

    assert (args.personal_proxy, args.no_touchstrip) == (True, True)


def test_the_flag_is_refused_with_debug_because_debug_would_record_the_request(
    capsys,
):
    with pytest.raises(SystemExit) as raised:
        parse_args(["--status-console", "--personal-proxy", "--debug"])

    assert raised.value.code != 0
    assert "--personal-proxy cannot be combined with --debug" in capsys.readouterr().err


# --- settings check ------------------------------------------------------------


def _configured(**overrides) -> PersonalProxySettings:
    values = {"endpoint": "https://proxy.example.test/v1", "model": "m"}
    return PersonalProxySettings(**(values | overrides))


def test_a_configured_endpoint_and_model_pass():
    require_configured(_configured())


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"endpoint": ""}, ["endpoint"]),
        ({"model": ""}, ["model"]),
        ({"endpoint": "  ", "model": "  "}, ["endpoint", "model"]),
    ],
)
def test_an_unconfigured_proxy_is_refused_naming_each_missing_key(overrides, missing):
    with pytest.raises(PersonalProxyNotConfiguredError) as raised:
        require_configured(_configured(**overrides))

    assert raised.value.missing_keys == tuple(missing)
    for key in missing:
        assert f"[personal_proxy].{key}" in str(raised.value)


# --- main ----------------------------------------------------------------------


class _HeldGuard(HeldInstance):
    def __init__(self) -> None:
        pass

    def release(self) -> None:
        pass


def _settings_with(proxy: PersonalProxySettings) -> Settings:
    return Settings(personal_proxy=proxy)


def test_main_starts_the_personal_proxy_run_with_the_validated_settings(monkeypatch):
    settings = _settings_with(_configured())
    monkeypatch.setattr(app_module, "load_settings", lambda: settings)
    launches: list[dict] = []
    monkeypatch.setattr(
        app_module, "run_with_status_console", lambda **kwargs: launches.append(kwargs)
    )

    app_module.main(["--status-console", "--personal-proxy"], acquire=_HeldGuard)

    assert launches[0]["run_mode"] is RunMode.PERSONAL_PROXY
    assert launches[0]["settings"] is settings


@pytest.mark.parametrize("overrides", [{"endpoint": ""}, {"model": ""}])
def test_main_ends_with_an_error_and_starts_nothing_when_unconfigured(
    monkeypatch, capsys, overrides
):
    monkeypatch.setattr(
        app_module,
        "load_settings",
        lambda: _settings_with(_configured(**overrides)),
    )
    started: list[str] = []
    monkeypatch.setattr(
        app_module, "run_with_status_console", lambda **kwargs: started.append("ui")
    )

    def acquire():
        started.append("guard")
        return _HeldGuard()

    with pytest.raises(SystemExit) as raised:
        app_module.main(["--status-console", "--personal-proxy"], acquire=acquire)

    assert raised.value.code == app_module.PERSONAL_PROXY_STARTUP_FAILED_EXIT_CODE
    assert raised.value.code not in (
        0,
        1,
        3,
        app_module.MCP_MODE_STARTUP_FAILED_EXIT_CODE,
    )
    assert "[personal_proxy]" in capsys.readouterr().err
    assert started == []


def test_without_the_flag_main_does_not_read_the_proxy_settings(monkeypatch):
    def forbidden():
        raise AssertionError("settings must not be loaded by main without the flag")

    monkeypatch.setattr(app_module, "load_settings", forbidden)
    launches: list[dict] = []
    monkeypatch.setattr(
        app_module, "run_with_status_console", lambda **kwargs: launches.append(kwargs)
    )

    app_module.main(["--status-console"], acquire=_HeldGuard)

    assert launches == [
        {"include_touchstrip": True, "debug": False, "run_mode": RunMode.NORMAL}
    ]


# --- locality seam ---------------------------------------------------------------


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[DataLocality] = []

    def set_data_locality(self, locality: DataLocality) -> None:
        self.calls.append(locality)


def test_the_seam_reports_external_inside_and_local_after():
    transport = _RecordingTransport()

    with external_locality(transport):
        assert transport.calls == [DataLocality.EXTERNAL]

    assert transport.calls == [DataLocality.EXTERNAL, DataLocality.LOCAL]


def test_the_seam_restores_local_when_the_body_raises():
    transport = _RecordingTransport()

    with pytest.raises(RuntimeError, match="boom"), external_locality(transport):
        raise RuntimeError("boom")

    assert transport.calls[-1] is DataLocality.LOCAL


def test_the_seam_has_no_production_caller():
    source_root = Path(app_module.__file__).parent
    callers = [
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.py")
        if "external_locality" in path.read_text(encoding="utf-8")
        and "personal_proxy" not in path.relative_to(source_root).parts
    ]

    assert callers == []
