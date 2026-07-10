"""OS-agnostic global-hotkey provider plus a Windows RegisterHotKey backend.

Story-v1.2.6 replaces the `keyboard` package's global key hook - which sees
the entire keypress stream - with a provider that registers only the
concrete combinations Jarvis actually uses. `RegisterHotKey` posts a
`WM_HOTKEY` message to the thread that registered the hotkey, so all
registrations and their dispatch must live on one thread; the provider owns
that dispatch thread. Callbacks fire on it, and callers marshal to their
asyncio loop themselves (`run_coroutine_threadsafe`), exactly as the
existing `run_hotkey_listener` functions do - preserving the callback-thread
rule PROJECT.md records for the mic-sleep and thinking hotkeys (the decision
of *what* to do stays on the event loop, never in the callback thread).

Windows-specific details (VK codes, MOD_* flags, the message loop) live in
`WindowsHotkeyProvider` and its ctypes backend. The `HotkeyProvider`
protocol and `parse_binding()` carry none of them.

Automated tests drive the provider through an injected `Win32Api` fake;
the real ctypes backend (`_CtypesWin32Api`) is exercised only by the
human manual handoff, like every other global-hotkey behavior in this
project (see PROJECT.md's Testing protocol).
"""

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class HotkeyError(RuntimeError):
    """Raised for an unparseable binding or a registration conflict."""


# MOD_* flags accepted by RegisterHotKey's fsModifiers. Kept here (not in the
# ctypes backend) so parse_binding() can produce a ready-to-use modifier mask
# that the fake backend sees identically to the real one.
_MODIFIER_FLAGS = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "control": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
    "windows": 0x0008,
    "super": 0x0008,
}

# Fire once per physical press instead of repeating while the combo is held -
# matches the one-action-per-press semantics keyboard.add_hotkey gave the
# existing listeners.
MOD_NOREPEAT = 0x4000

# Virtual-key codes for the non-alphanumeric keys a binding might name. Letters
# and digits are computed directly; F1-F24 are a contiguous range.
_NAMED_VK = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}

_FUNCTION_KEY_RE = re.compile(r"f([1-9]|1[0-9]|2[0-4])")


@dataclass(frozen=True)
class ParsedBinding:
    """A binding translated to RegisterHotKey inputs. `modifiers` excludes
    MOD_NOREPEAT (the provider ORs that in at registration); `label` keeps
    the original string for error messages."""

    modifiers: int
    vk: int
    label: str


def _vk_for_key(key: str, label: str) -> int:
    if len(key) == 1:
        if "a" <= key <= "z":
            return ord(key.upper())
        if "0" <= key <= "9":
            return ord(key)
    if key in _NAMED_VK:
        return _NAMED_VK[key]
    match = _FUNCTION_KEY_RE.fullmatch(key)
    if match:
        return 0x70 + int(match.group(1)) - 1
    raise HotkeyError(f"Unsupported key {key!r} in hotkey {label!r}")


def parse_binding(binding: str) -> ParsedBinding:
    """Parses a '+'-joined combo like 'ctrl+alt+s' into modifier flags and a
    single virtual-key code. The last '+'-separated token is the key; the
    rest are modifiers. Raises HotkeyError for an empty token, an unknown
    modifier, or an unsupported key."""
    tokens = [token.strip().lower() for token in binding.split("+")]
    if not tokens or any(token == "" for token in tokens):
        raise HotkeyError(f"Malformed hotkey binding {binding!r}")

    *modifier_tokens, key = tokens
    modifiers = 0
    for token in modifier_tokens:
        flag = _MODIFIER_FLAGS.get(token)
        if flag is None:
            raise HotkeyError(f"Unknown modifier {token!r} in hotkey {binding!r}")
        modifiers |= flag

    vk = _vk_for_key(key, binding)
    return ParsedBinding(modifiers=modifiers, vk=vk, label=binding)


class HotkeyProvider(Protocol):
    """Caller-facing global-hotkey contract, with no OS-specific detail.

    Register every hotkey, then start(); presses invoke the callbacks until
    stop(). Callbacks run on the provider's own dispatch thread - callers
    must schedule any event-loop work with run_coroutine_threadsafe and must
    not make engine-state decisions in the callback itself."""

    def register(self, binding: str, callback: Callable[[], None]) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class Win32Api(Protocol):
    """The narrow slice of the Win32 API the provider needs, as an injection
    seam. RegisterHotKey binds the hotkey to the calling thread, so the
    provider drives every method below from its single dispatch thread:
    attach() first, then register_hotkey() per binding, then wait_hotkey()
    in a loop, with wake() posted from another thread to end it."""

    def attach(self) -> None: ...

    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> bool: ...

    def unregister_hotkey(self, hotkey_id: int) -> None: ...

    def wait_hotkey(self) -> int | None: ...

    def wake(self) -> None: ...

    def detach(self) -> None: ...


@dataclass(frozen=True)
class _Registration:
    hotkey_id: int
    parsed: ParsedBinding


class WindowsHotkeyProvider:
    """HotkeyProvider backed by RegisterHotKey (via an injectable Win32Api).

    The dispatch thread performs all registrations, reports any conflict back
    to start() synchronously, then pumps hotkey presses until stop() wakes it,
    unregistering everything on the way out."""

    def __init__(self, win32: Win32Api | None = None) -> None:
        self._win32 = win32
        self._bindings: list[_Registration] = []
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: HotkeyError | None = None
        self._started = False

    def register(self, binding: str, callback: Callable[[], None]) -> None:
        if self._started:
            raise HotkeyError("Cannot register hotkeys after start()")
        parsed = parse_binding(binding)
        hotkey_id = self._next_id
        self._next_id += 1
        self._bindings.append(_Registration(hotkey_id, parsed))
        self._callbacks[hotkey_id] = callback

    def start(self) -> None:
        if self._started:
            return
        self._ready.clear()
        self._start_error = None
        self._started = True
        if self._win32 is None:
            self._win32 = _CtypesWin32Api()
        self._thread = threading.Thread(
            target=self._run, name="hotkey-dispatch", daemon=True
        )
        self._thread.start()
        self._ready.wait()
        if self._start_error is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
            raise self._start_error

    def stop(self) -> None:
        if not self._started:
            return
        thread = self._thread
        if thread is not None:
            self._win32.wake()
            thread.join(timeout=5.0)
            self._thread = None
        self._started = False

    def __enter__(self) -> "WindowsHotkeyProvider":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _run(self) -> None:
        api = self._win32
        api.attach()
        registered = self._register_all(api)
        self._ready.set()
        if self._start_error is not None:
            api.detach()
            return
        try:
            self._dispatch_until_woken(api)
        finally:
            for hotkey_id in registered:
                api.unregister_hotkey(hotkey_id)
            api.detach()

    def _register_all(self, api: Win32Api) -> list[int]:
        registered: list[int] = []
        for binding in self._bindings:
            ok = api.register_hotkey(
                binding.hotkey_id,
                binding.parsed.modifiers | MOD_NOREPEAT,
                binding.parsed.vk,
            )
            if not ok:
                self._start_error = HotkeyError(
                    f"Hotkey {binding.parsed.label!r} is already registered by "
                    "another application"
                )
                for done in registered:
                    api.unregister_hotkey(done)
                return []
            registered.append(binding.hotkey_id)
        return registered

    def _dispatch_until_woken(self, api: Win32Api) -> None:
        while True:
            hotkey_id = api.wait_hotkey()
            if hotkey_id is None:
                return
            callback = self._callbacks.get(hotkey_id)
            if callback is not None:
                callback()


# Win32 message constants used only by the ctypes backend below.
_WM_HOTKEY = 0x0312
_WM_STOP = 0x8000  # WM_APP: our own thread-message signal to end the loop.


class _CtypesWin32Api:
    """Real Win32Api over user32/kernel32. Not covered by automated tests
    (no real global hotkeys in CI - see the module docstring); verified by
    the human manual handoff."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._thread_id: int | None = None

    def attach(self) -> None:
        self._thread_id = self._kernel32.GetCurrentThreadId()
        # RegisterHotKey creates messages for this thread, but the queue itself
        # is otherwise created lazily. Force it into existence before start()
        # reports readiness so an immediate stop() can always post its wakeup.
        msg = self._wintypes.MSG()
        self._user32.PeekMessageW(self._ctypes.byref(msg), None, 0, 0, 0)

    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        return bool(self._user32.RegisterHotKey(None, hotkey_id, modifiers, vk))

    def unregister_hotkey(self, hotkey_id: int) -> None:
        self._user32.UnregisterHotKey(None, hotkey_id)

    def wait_hotkey(self) -> int | None:
        msg = self._wintypes.MSG()
        while True:
            result = self._user32.GetMessageW(self._ctypes.byref(msg), None, 0, 0)
            if result <= 0:  # 0 = WM_QUIT, -1 = error
                return None
            if msg.message == _WM_STOP:
                return None
            if msg.message == _WM_HOTKEY:
                return int(msg.wParam)
            # Only thread messages reach a NULL-hwnd queue; ignore anything
            # unexpected and keep pumping.

    def wake(self) -> None:
        if self._thread_id is not None:
            self._kernel32.PostThreadMessageW(self._thread_id, _WM_STOP, 0, 0)

    def detach(self) -> None:
        self._thread_id = None
