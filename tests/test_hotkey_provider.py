import asyncio
import queue
import threading

import pytest

from hotkey_provider import (
    MOD_NOREPEAT,
    HotkeyError,
    HotkeyProvider,
    WindowsHotkeyProvider,
    parse_binding,
    run_hotkey_provider,
)

_MOD_ALT = 0x0001
_MOD_CTRL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008


# --- parse_binding ----------------------------------------------------------


def test_parse_binding_translates_modifiers_and_letter():
    parsed = parse_binding("ctrl+alt+s")

    assert parsed.modifiers == _MOD_CTRL | _MOD_ALT
    assert parsed.vk == ord("S")
    assert parsed.label == "ctrl+alt+s"


def test_parse_binding_is_case_and_whitespace_insensitive():
    parsed = parse_binding("  Ctrl + Shift + Q ")

    assert parsed.modifiers == _MOD_CTRL | _MOD_SHIFT
    assert parsed.vk == ord("Q")


def test_parse_binding_accepts_control_and_windows_aliases():
    assert parse_binding("control+a").modifiers == _MOD_CTRL
    assert parse_binding("win+a").modifiers == _MOD_WIN
    assert parse_binding("windows+a").modifiers == _MOD_WIN
    assert parse_binding("super+a").modifiers == _MOD_WIN


def test_parse_binding_maps_digits_function_and_named_keys():
    assert parse_binding("ctrl+5").vk == ord("5")
    assert parse_binding("ctrl+f1").vk == 0x70
    assert parse_binding("ctrl+f12").vk == 0x7B
    assert parse_binding("ctrl+f24").vk == 0x87
    assert parse_binding("ctrl+space").vk == 0x20


def test_parse_binding_allows_a_bare_key_without_modifiers():
    parsed = parse_binding("f5")

    assert parsed.modifiers == 0
    assert parsed.vk == 0x74


@pytest.mark.parametrize("binding", ["", "ctrl+", "+s", "ctrl++s"])
def test_parse_binding_rejects_malformed_bindings(binding):
    with pytest.raises(HotkeyError, match="Malformed"):
        parse_binding(binding)


def test_parse_binding_rejects_unknown_modifier():
    with pytest.raises(HotkeyError, match="Unknown modifier 'hyper'"):
        parse_binding("hyper+s")


def test_parse_binding_rejects_unsupported_key():
    with pytest.raises(HotkeyError, match="Unsupported key 'f25'"):
        parse_binding("ctrl+f25")


# --- provider with an injected Win32 fake -----------------------------------


class _FakeWin32Api:
    """Drives WindowsHotkeyProvider without real global hotkeys. register_hotkey
    records the exact (modifiers, vk) it was handed and refuses any combination
    seeded as already taken; wait_hotkey blocks on a queue the test feeds with
    press()/wake()."""

    def __init__(self, taken: set[tuple[int, int]] | None = None) -> None:
        self.register_calls: list[tuple[int, int, int]] = []
        self.registered: dict[int, tuple[int, int]] = {}
        self.unregistered: list[int] = []
        self.attached = False
        self.detached = False
        self.dispatch_thread_ident: int | None = None
        self._taken = set(taken or set())
        self._queue: queue.Queue[int | None] = queue.Queue()

    def attach(self) -> None:
        self.attached = True
        self.dispatch_thread_ident = threading.get_ident()

    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        self.register_calls.append((hotkey_id, modifiers, vk))
        combo = (modifiers, vk)
        if combo in self._taken:
            return False
        self.registered[hotkey_id] = combo
        self._taken.add(combo)
        return True

    def unregister_hotkey(self, hotkey_id: int) -> None:
        self.unregistered.append(hotkey_id)
        combo = self.registered.pop(hotkey_id, None)
        if combo is not None:
            self._taken.discard(combo)

    def wait_hotkey(self) -> int | None:
        return self._queue.get()

    def wake(self) -> None:
        self._queue.put(None)

    def detach(self) -> None:
        self.detached = True

    # test-only driver
    def press(self, hotkey_id: int) -> None:
        self._queue.put(hotkey_id)


def test_windows_provider_satisfies_hotkey_provider_protocol():
    provider: HotkeyProvider = WindowsHotkeyProvider(_FakeWin32Api())

    assert provider is not None


def test_start_registers_each_binding_with_norepeat_modifiers_and_vk():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    provider.register("ctrl+alt+s", lambda: None)
    provider.register("ctrl+alt+q", lambda: None)

    provider.start()
    try:
        assert fake.attached
        assert fake.register_calls == [
            (1, _MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("S")),
            (2, _MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("Q")),
        ]
    finally:
        provider.stop()


def test_press_dispatches_to_the_matching_callback():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    first_fired = threading.Event()
    second_fired = threading.Event()
    provider.register("ctrl+alt+s", first_fired.set)
    provider.register("ctrl+alt+q", second_fired.set)

    provider.start()
    try:
        fake.press(2)
        assert second_fired.wait(timeout=2.0)
        assert not first_fired.is_set()

        fake.press(1)
        assert first_fired.wait(timeout=2.0)
    finally:
        provider.stop()


def test_callback_runs_on_the_dispatch_thread_not_the_caller_thread():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    seen_ident: dict[str, int] = {}
    fired = threading.Event()

    def record() -> None:
        seen_ident["callback"] = threading.get_ident()
        fired.set()

    provider.register("ctrl+alt+s", record)
    provider.start()
    try:
        fake.press(1)
        assert fired.wait(timeout=2.0)
        assert seen_ident["callback"] == fake.dispatch_thread_ident
        assert seen_ident["callback"] != threading.get_ident()
    finally:
        provider.stop()


def test_registration_conflict_raises_and_rolls_back_earlier_registrations():
    conflicting = (_MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("Q"))
    fake = _FakeWin32Api(taken={conflicting})
    provider = WindowsHotkeyProvider(fake)
    provider.register("ctrl+alt+s", lambda: None)  # id 1, succeeds
    provider.register("ctrl+alt+q", lambda: None)  # id 2, conflicts

    with pytest.raises(HotkeyError, match="'ctrl\\+alt\\+q' is already registered"):
        provider.start()

    # the one that did register must be rolled back, leaving nothing held
    assert fake.registered == {}
    assert fake.unregistered == [1]


def test_stop_unregisters_all_hotkeys_and_cleans_up():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    provider.register("ctrl+alt+s", lambda: None)
    provider.register("ctrl+alt+q", lambda: None)
    provider.start()

    provider.stop()

    assert sorted(fake.unregistered) == [1, 2]
    assert fake.registered == {}
    assert fake.detached


def test_stop_is_idempotent_and_safe_before_start():
    provider = WindowsHotkeyProvider(_FakeWin32Api())

    provider.stop()  # never started - no-op

    provider.register("ctrl+alt+s", lambda: None)
    provider.start()
    provider.stop()
    provider.stop()  # second stop - no-op


def test_provider_can_restart_after_stop():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    provider.register("ctrl+alt+s", lambda: None)

    provider.start()
    provider.stop()
    provider.start()
    try:
        assert fake.register_calls == [
            (1, _MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("S")),
            (1, _MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("S")),
        ]
        assert fake.registered == {
            1: (_MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("S"))
        }
    finally:
        provider.stop()


def test_register_after_start_is_rejected():
    provider = WindowsHotkeyProvider(_FakeWin32Api())
    provider.start()
    try:
        with pytest.raises(HotkeyError, match="after start"):
            provider.register("ctrl+alt+s", lambda: None)
    finally:
        provider.stop()


def test_context_manager_starts_and_stops():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    provider.register("ctrl+alt+s", lambda: None)

    with provider:
        assert fake.registered == {1: (_MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("S"))}

    assert fake.unregistered == [1]
    assert fake.detached


async def test_async_provider_lifecycle_registers_and_stops_on_cancellation():
    fake = _FakeWin32Api()
    provider = WindowsHotkeyProvider(fake)
    task = asyncio.create_task(
        run_hotkey_provider([("ctrl+alt+s", lambda: None)], provider)
    )
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake.register_calls == [
        (1, _MOD_CTRL | _MOD_ALT | MOD_NOREPEAT, ord("S"))
    ]
    assert fake.unregistered == [1]
