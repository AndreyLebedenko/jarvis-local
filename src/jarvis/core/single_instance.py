"""Single-instance guard: only one Jarvis may run at a time.

A second Jarvis start is refused, in every start mode. The guard is a Windows
named mutex in the per-logon-session `Local\\` namespace: global per user, not
per workspace. The OS releases it when the process dies, so a crash never
leaves a stale lock behind.

The Win32 calls sit behind `MutexApi` so the decision logic is tested without
a real mutex. Only `Win32MutexApi` and `show_already_running_message_box`
touch ctypes; both build their DLL bindings lazily so importing this module
is safe on any platform.
"""

import ctypes
from dataclasses import dataclass
from typing import Protocol

MUTEX_NAME = "Local\\Jarvis.SingleInstance"
ALREADY_RUNNING_EXIT_CODE = 3
ALREADY_RUNNING_MESSAGE = (
    "Jarvis is already running. Only one instance may run at a time."
)

_ERROR_ALREADY_EXISTS = 183
_MESSAGE_BOX_TITLE = "Jarvis"
_MB_OK_ICON_INFORMATION = 0x00000040


@dataclass(frozen=True)
class MutexCreation:
    handle: int
    already_exists: bool


class MutexApi(Protocol):
    def create(self, name: str) -> MutexCreation: ...

    def close(self, handle: int) -> None: ...


class HeldInstance:
    def __init__(self, api: MutexApi, handle: int) -> None:
        self._api = api
        self._handle: int | None = handle

    def release(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._api.close(handle)


@dataclass(frozen=True)
class AlreadyRunning:
    pass


def acquire_single_instance(
    api: MutexApi | None = None,
) -> HeldInstance | AlreadyRunning:
    api = api if api is not None else Win32MutexApi()
    creation = api.create(MUTEX_NAME)
    if creation.already_exists:
        api.close(creation.handle)
        return AlreadyRunning()
    return HeldInstance(api, creation.handle)


class Win32MutexApi:
    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        self._kernel32 = kernel32

    def create(self, name: str) -> MutexCreation:
        # use_last_error keeps a private copy of the error code; without
        # clearing it first, a stale ERROR_ALREADY_EXISTS could be read back
        # after a successful fresh create.
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        return MutexCreation(
            handle=handle, already_exists=error == _ERROR_ALREADY_EXISTS
        )

    def close(self, handle: int) -> None:
        self._kernel32.CloseHandle(handle)


def show_already_running_message_box(message: str) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MessageBoxW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW(None, message, _MESSAGE_BOX_TITLE, _MB_OK_ICON_INFORMATION)
