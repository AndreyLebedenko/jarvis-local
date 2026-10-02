import sys

import pytest

from jarvis import app
from jarvis.core.run_mode import RunMode
from jarvis.core.single_instance import (
    ALREADY_RUNNING_EXIT_CODE,
    ALREADY_RUNNING_MESSAGE,
    MUTEX_NAME,
    AlreadyRunning,
    HeldInstance,
    MutexCreation,
    Win32MutexApi,
    acquire_single_instance,
)

FAKE_HANDLE = 4242


class FakeMutexApi:
    def __init__(self, *, already_exists: bool) -> None:
        self._already_exists = already_exists
        self.created_names: list[str] = []
        self.closed_handles: list[int] = []

    def create(self, name: str) -> MutexCreation:
        self.created_names.append(name)
        return MutexCreation(handle=FAKE_HANDLE, already_exists=self._already_exists)

    def close(self, handle: int) -> None:
        self.closed_handles.append(handle)


class EntryPointSpy:
    def __init__(self) -> None:
        self.run_calls = 0
        self.status_console_calls: list[dict] = []
        self.message_boxes: list[str] = []
        self.acquire_calls = 0

    async def run(self, run_mode: RunMode) -> None:
        self.run_calls += 1

    def run_with_status_console(self, **kwargs) -> None:
        self.status_console_calls.append(kwargs)

    def show_message_box(self, message: str) -> None:
        self.message_boxes.append(message)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> EntryPointSpy:
    entry_point_spy = EntryPointSpy()
    monkeypatch.setattr(app, "run", entry_point_spy.run)
    monkeypatch.setattr(
        app, "run_with_status_console", entry_point_spy.run_with_status_console
    )
    return entry_point_spy


def make_acquirer(api: FakeMutexApi, spy: EntryPointSpy):
    def acquire():
        spy.acquire_calls += 1
        return acquire_single_instance(api)

    return acquire


def run_main(argv: list[str], api: FakeMutexApi, spy: EntryPointSpy) -> None:
    app.main(
        argv,
        acquire=make_acquirer(api, spy),
        show_message_box=spy.show_message_box,
    )


def test_acquire_on_free_mutex_returns_held_instance() -> None:
    api = FakeMutexApi(already_exists=False)

    result = acquire_single_instance(api)

    assert isinstance(result, HeldInstance)
    assert api.created_names == [MUTEX_NAME]
    assert api.closed_handles == []


def test_release_closes_the_held_handle_once() -> None:
    api = FakeMutexApi(already_exists=False)
    held = acquire_single_instance(api)
    assert isinstance(held, HeldInstance)

    held.release()
    held.release()

    assert api.closed_handles == [FAKE_HANDLE]


def test_acquire_on_existing_mutex_returns_already_running_and_closes_handle() -> None:
    api = FakeMutexApi(already_exists=True)

    result = acquire_single_instance(api)

    assert isinstance(result, AlreadyRunning)
    assert api.closed_handles == [FAKE_HANDLE]


def test_mutex_name_is_one_fixed_per_user_session_name() -> None:
    assert MUTEX_NAME == r"Local\Jarvis.SingleInstance"


def test_refusal_message_says_only_one_instance_may_run() -> None:
    assert "already running" in ALREADY_RUNNING_MESSAGE
    assert "one instance" in ALREADY_RUNNING_MESSAGE
    assert ALREADY_RUNNING_MESSAGE.isascii()


def test_refused_main_exits_with_named_code_and_starts_nothing(
    spy: EntryPointSpy, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeMutexApi(already_exists=True)

    with pytest.raises(SystemExit) as exit_info:
        run_main(["--status-console"], api, spy)

    assert exit_info.value.code == ALREADY_RUNNING_EXIT_CODE
    assert ALREADY_RUNNING_EXIT_CODE != 0
    assert spy.run_calls == 0
    assert spy.status_console_calls == []
    assert capsys.readouterr().err.strip() == ALREADY_RUNNING_MESSAGE


def test_refused_headless_main_exits_with_named_code_and_starts_nothing(
    spy: EntryPointSpy,
) -> None:
    api = FakeMutexApi(already_exists=True)

    with pytest.raises(SystemExit) as exit_info:
        run_main([], api, spy)

    assert exit_info.value.code == ALREADY_RUNNING_EXIT_CODE
    assert spy.run_calls == 0
    assert spy.status_console_calls == []


def test_refused_status_console_main_shows_message_box(spy: EntryPointSpy) -> None:
    api = FakeMutexApi(already_exists=True)

    with pytest.raises(SystemExit):
        run_main(["--status-console"], api, spy)

    assert spy.message_boxes == [ALREADY_RUNNING_MESSAGE]


def test_refused_headless_main_shows_no_message_box(spy: EntryPointSpy) -> None:
    api = FakeMutexApi(already_exists=True)

    with pytest.raises(SystemExit):
        run_main([], api, spy)

    assert spy.message_boxes == []


def test_help_exits_zero_without_consulting_the_guard(
    spy: EntryPointSpy, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeMutexApi(already_exists=True)

    with pytest.raises(SystemExit) as exit_info:
        run_main(["--help"], api, spy)

    assert exit_info.value.code == 0
    assert spy.acquire_calls == 0
    assert spy.message_boxes == []
    assert "--status-console" in capsys.readouterr().out


def test_argument_error_keeps_argparse_exit_code_without_consulting_the_guard(
    spy: EntryPointSpy,
) -> None:
    api = FakeMutexApi(already_exists=True)

    with pytest.raises(SystemExit) as exit_info:
        run_main(["--debug"], api, spy)

    assert exit_info.value.code == 2
    assert spy.acquire_calls == 0


def test_free_headless_main_runs_and_releases_handle_afterwards(
    spy: EntryPointSpy,
) -> None:
    api = FakeMutexApi(already_exists=False)

    run_main([], api, spy)

    assert spy.run_calls == 1
    assert api.closed_handles == [FAKE_HANDLE]


def test_main_without_injected_seams_uses_the_suite_fake_guard_not_win32(
    spy: EntryPointSpy, no_win32_single_instance_guard
) -> None:
    app.main([])

    assert no_win32_single_instance_guard.acquire_calls == 1
    assert spy.run_calls == 1
    assert no_win32_single_instance_guard.closed_handles == [1]


def test_free_status_console_main_runs_console_and_releases_handle_afterwards(
    spy: EntryPointSpy,
) -> None:
    api = FakeMutexApi(already_exists=False)

    run_main(["--status-console"], api, spy)

    assert spy.status_console_calls == [
        {"include_touchstrip": True, "debug": False, "run_mode": RunMode.NORMAL}
    ]
    assert api.closed_handles == [FAKE_HANDLE]


def test_handle_is_still_held_while_run_is_executing(
    spy: EntryPointSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeMutexApi(already_exists=False)
    closed_during_run: list[list[int]] = []

    async def run_probe(run_mode: RunMode) -> None:
        closed_during_run.append(list(api.closed_handles))

    monkeypatch.setattr(app, "run", run_probe)

    run_main([], api, spy)

    assert closed_during_run == [[]]


def test_handle_is_released_when_run_raises(
    spy: EntryPointSpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeMutexApi(already_exists=False)

    async def failing_run(run_mode: RunMode) -> None:
        raise RuntimeError("engine crashed")

    monkeypatch.setattr(app, "run", failing_run)

    with pytest.raises(RuntimeError, match="engine crashed"):
        run_main([], api, spy)

    assert api.closed_handles == [FAKE_HANDLE]


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows-only")
def test_real_mutex_can_be_acquired_released_and_acquired_again() -> None:
    api = Win32MutexApi()
    unique_name = f"Local\\Jarvis.SingleInstance.Test.{id(api)}"

    first = api.create(unique_name)
    second = api.create(unique_name)
    api.close(second.handle)
    api.close(first.handle)
    third = api.create(unique_name)
    api.close(third.handle)

    assert first.already_exists is False
    assert second.already_exists is True
    assert third.already_exists is False
