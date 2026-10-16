"""Native Win32 notification icon on its own message-loop thread."""

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes as wt
from pathlib import Path
from typing import ClassVar

from jarvis.launcher.model import LaunchMode

WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_TRAY = 0x8001
WM_REFRESH = 0x8002
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
MENU_ITEMS = (
    (1, "Assistant"),
    (2, "MCP"),
    (0, ""),
    (3, "Settings"),
    (0, ""),
    (4, "Exit"),
)


class NotifyIconData(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wt.HICON),
    ]


class WindowsTray:
    def __init__(
        self,
        icon: Path,
        on_action: Callable[[int], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self._icon_path = icon
        self._on_action = on_action
        self._on_error = on_error
        self._mode: LaunchMode | None = None
        self._tooltip = "Jarvis - waiting for a mode"
        self._hwnd: int | None = None
        self._data = NotifyIconData(cbSize=ctypes.sizeof(NotifyIconData))
        self._ready = threading.Event()
        self._failure: Exception | None = None
        self._thread = threading.Thread(
            target=self._run, name="jarvis-tray", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("The Windows notification icon did not initialize.")
        if self._failure is not None:
            raise self._failure

    def update(self, mode: LaunchMode | None, *, exiting: bool = False) -> None:
        self._mode = mode
        self._tooltip = (
            "Jarvis - shutting down"
            if exiting
            else f"Jarvis - {mode.value.title()}"
            if mode is not None
            else "Jarvis - waiting for a mode"
        )
        if self._hwnd is not None:
            self._user32.PostMessageW(self._hwnd, WM_REFRESH, 0, 0)

    def close(self) -> None:
        if self._hwnd is not None:
            self._user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("The Windows tray message loop did not stop.")

    def _bind(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
        )
        bindings = (
            (
                "CreateWindowExW",
                [
                    wt.DWORD,
                    wt.LPCWSTR,
                    wt.LPCWSTR,
                    wt.DWORD,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wt.HWND,
                    wt.HMENU,
                    wt.HINSTANCE,
                    wt.LPVOID,
                ],
                wt.HWND,
            ),
            (
                "DefWindowProcW",
                [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM],
                ctypes.c_ssize_t,
            ),
            (
                "LoadImageW",
                [
                    wt.HINSTANCE,
                    wt.LPCWSTR,
                    wt.UINT,
                    ctypes.c_int,
                    ctypes.c_int,
                    wt.UINT,
                ],
                wt.HANDLE,
            ),
            ("CreatePopupMenu", [], wt.HMENU),
            ("AppendMenuW", [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR], wt.BOOL),
            (
                "TrackPopupMenu",
                [
                    wt.HMENU,
                    wt.UINT,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wt.HWND,
                    ctypes.c_void_p,
                ],
                wt.UINT,
            ),
            ("DestroyMenu", [wt.HMENU], wt.BOOL),
            ("DestroyWindow", [wt.HWND], wt.BOOL),
            ("DestroyIcon", [wt.HICON], wt.BOOL),
            ("SetForegroundWindow", [wt.HWND], wt.BOOL),
            ("PostMessageW", [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL),
            (
                "GetMessageW",
                [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT],
                wt.BOOL,
            ),
            ("TranslateMessage", [ctypes.POINTER(wt.MSG)], wt.BOOL),
            ("DispatchMessageW", [ctypes.POINTER(wt.MSG)], ctypes.c_ssize_t),
            ("RegisterWindowMessageW", [wt.LPCWSTR], wt.UINT),
            ("GetCursorPos", [ctypes.POINTER(wt.POINT)], wt.BOOL),
            ("GetSystemMetrics", [ctypes.c_int], ctypes.c_int),
            ("PostQuitMessage", [ctypes.c_int], None),
            ("UnregisterClassW", [wt.LPCWSTR, wt.HINSTANCE], wt.BOOL),
        )
        for name, arguments, result in bindings:
            function = getattr(self._user32, name)
            function.argtypes = arguments
            function.restype = result
        self._kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wt.HMODULE
        self._shell32.Shell_NotifyIconW.argtypes = [
            wt.DWORD,
            ctypes.POINTER(NotifyIconData),
        ]
        self._shell32.Shell_NotifyIconW.restype = wt.BOOL

    def _run(self) -> None:
        try:
            self._bind()
            self._create()
            self._ready.set()
            message = wt.MSG()
            while True:
                result = self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self._failure = error
            self._ready.set()
            self._on_error(error)
        finally:
            if self._hwnd is not None:
                self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data))
                self._user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            if getattr(self, "_icon", None):
                self._user32.DestroyIcon(self._icon)
            if getattr(self, "_class_registered", False):
                self._user32.UnregisterClassW(self._class_name, self._instance)

    def _create(self) -> None:
        class WindowClass(ctypes.Structure):
            _fields_: ClassVar[list[tuple[str, type]]] = [
                ("style", wt.UINT),
                ("lpfnWndProc", self._wndproc_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR),
            ]

        self._instance = self._kernel32.GetModuleHandleW(None)
        self._class_name = "JarvisLauncherTray"
        self._wndproc = self._wndproc_type(self._window_proc)
        window_class = WindowClass(
            lpfnWndProc=self._wndproc,
            hInstance=self._instance,
            lpszClassName=self._class_name,
        )
        self._user32.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        self._user32.RegisterClassW.restype = wt.ATOM
        if not self._user32.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        self._class_registered = True
        self._taskbar_created = self._user32.RegisterWindowMessageW("TaskbarCreated")
        self._hwnd = self._user32.CreateWindowExW(
            0,
            self._class_name,
            "Jarvis Launcher",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._instance,
            None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._icon = self._user32.LoadImageW(
            None,
            str(self._icon_path),
            1,
            self._user32.GetSystemMetrics(49),
            self._user32.GetSystemMetrics(50),
            0x10,
        )
        if not self._icon:
            raise ctypes.WinError(ctypes.get_last_error())
        self._data = NotifyIconData(
            cbSize=ctypes.sizeof(NotifyIconData),
            hWnd=self._hwnd,
            uID=1,
            uFlags=7,
            uCallbackMessage=WM_TRAY,
            hIcon=self._icon,
            szTip=self._tooltip,
        )
        if not self._shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data)):
            raise RuntimeError("Windows refused to add the Jarvis notification icon.")

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        try:
            return self._handle_message(hwnd, message, wparam, lparam)
        except Exception as error:
            self._on_error(error)
            return 0

    def _handle_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == WM_TRAY and lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
            self._popup(hwnd)
            return 0
        if message == WM_REFRESH:
            self._data.szTip = self._tooltip
            self._shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data))
            return 0
        if message == getattr(self, "_taskbar_created", -1):
            self._shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data))
            return 0
        if message == WM_CLOSE:
            self._user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data))
            self._hwnd = None
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _popup(self, hwnd: int) -> None:
        menu = self._user32.CreatePopupMenu()
        if not menu:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            active = (
                1
                if self._mode is LaunchMode.ASSISTANT
                else 2
                if self._mode is LaunchMode.MCP
                else -1
            )
            for identifier, label in MENU_ITEMS:
                flags = (
                    0x0800 if identifier == 0 else 0x0008 if identifier == active else 0
                )
                if not self._user32.AppendMenuW(menu, flags, identifier, label):
                    raise ctypes.WinError(ctypes.get_last_error())
            point = wt.POINT()
            if not self._user32.GetCursorPos(ctypes.byref(point)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._user32.SetForegroundWindow(hwnd)
            action = self._user32.TrackPopupMenu(
                menu, 0x0102, point.x, point.y, 0, hwnd, None
            )
            self._user32.PostMessageW(hwnd, 0, 0, 0)
            if action:
                self._on_action(action)
        finally:
            self._user32.DestroyMenu(menu)
