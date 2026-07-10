# RegisterHotKey shutdown uses the wrong Win32 DLL

**Detected at commit:** `65f1e57`

## Symptoms

`Ctrl+Alt+Q` fires globally and starts the normal shutdown path, but every
hotkey listener raises during cleanup. The final shutdown provider raises the
same exception from `main.run()`, leaving a traceback in the pywebview worker
thread:

```text
AttributeError: function 'PostThreadMessageW' not found
```

## Suspected current cause

`_CtypesWin32Api.wake()` resolves `PostThreadMessageW` from `kernel32`.
`PostThreadMessageW` is exported by `user32`, so the wake call fails before the
provider dispatch thread can leave its message loop and unregister its hotkey.

## Temporary decision

Do not count the live run as a successful v1.2.6 manual handoff. The shutdown
trigger itself is proven to register and fire, but cleanup is not proven and
ends with errors. Keep this fix outside task 3, whose boundary is dependency
and documentation cleanup.

## Future considerations

Fix `_CtypesWin32Api.wake()` to call the correctly bound `user32` function and
add an automated ctypes binding-shape test that does not register a real global
hotkey. Then repeat the live shutdown check and confirm that all providers
unregister without tracebacks. Non-elevated behavior and registration-conflict
handling remain separate task 4 checks.

## Resolution status

Fixed in the task 3 working tree: `_CtypesWin32Api.wake()` now calls
`user32.PostThreadMessageW`. An injected-DLL regression test verifies that the
message is sent through `user32` and never through `kernel32`; the full pure
suite passes. Live shutdown was re-verified by the human on 2026-07-10:
`Ctrl+Alt+Q` triggered the normal shutdown path, all five background tasks
finished, and teardown completed without errors or tracebacks. The issue is
resolved.
