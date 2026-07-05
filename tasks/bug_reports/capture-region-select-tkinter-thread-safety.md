# Bug report: region-select overlay can crash with KeyError('x')

Commit: HEAD at time of writing is `21348e5` (task-06); observed on the
in-progress task-07 branch during its manual handoff (main.py + capture.py
as of this branch, capture.py's `select_region_interactively()` unchanged
in substance from task-06's commit).

## Symptoms

Live report from the human running `python main.py`, using the
region-select hotkey:

```
Exception in Tkinter callback
Traceback (most recent call last):
  File ".../tkinter/__init__.py", line 1967, in __call__
    return self.func(*args)
  File "capture.py", line 117, in on_release
    x0, y0 = start["x"], start["y"]
             ~~~~~^^^^^
KeyError: 'x'
```

`on_release` fired without `start["x"]`/`start["y"]` having been set by a
preceding `on_press` - i.e. a `<ButtonRelease-1>` event arrived without a
matching `<ButtonPress-1>` having been processed first on the same
`start` dict.

## Suspected cause

`select_region_interactively()` is called synchronously from
`run_hotkey_listener()`'s `on_region()` callback, which is registered via
`keyboard.add_hotkey(...)`. The `keyboard` package invokes hotkey
callbacks on its own internal listener thread, not the thread that called
`asyncio.run()` (main.py's actual "main thread"). `select_region_
interactively()` then constructs a fresh `tk.Tk()` and runs its mainloop
on *that* thread.

Tkinter is documented as not thread-safe: a `Tk()` instance and its
mainloop are expected to be created and driven from a single, consistent
thread for the lifetime of that instance. Constructing and running one
from a background thread that `keyboard` may not even guarantee is the
same thread across separate hotkey presses is a plausible explanation for
dropped or reordered events - press and release ending up processed out
of sequence against the same `start` dict, exactly matching the observed
`KeyError`.

This has not been confirmed with a minimal repro or Tk/Tcl-level tracing;
it is the most plausible explanation given the code and the symptom, not
a proven root cause.

## Temporary decision

Added a defensive guard: `on_drag`/`on_release` now return early if
`start` has no `"x"` key yet, instead of raising. This was chosen over
attempting a full threading fix because:

- A real fix (e.g. marshaling the whole region-select flow onto a single
  dedicated thread, or replacing the hotkey library/threading model)
  needs to be verified interactively against a real display and a real
  global hotkey - hardware/UI-dependent work the agent cannot execute
  itself per CLAUDE.md's testing protocol, and risky to get wrong blind.
- The defensive guard directly prevents the observed crash (an unhandled
  exception escaping a Tkinter callback, which risked taking down
  `keyboard`'s callback thread and with it all hotkey handling for the
  rest of the session) without masking or working around anything else.
- Worst case with the guard in place: one drag/release event is silently
  ignored (the user sees no rectangle for a frame, or a release does
  nothing) and they can retry - Escape still reliably cancels and closes
  the overlay.

## Future considerations

- If this recurs with the guard in place (i.e. region-select becomes
  unreliable rather than merely occasionally dropping one event), the
  threading hypothesis should be tested directly: e.g. route
  `select_region_interactively()` through a single persistent thread
  (created once at startup, reused for every region-select) rather than
  whatever thread `keyboard` happens to invoke the callback on, and
  confirm whether the KeyError stops recurring.
- An alternative longer-term fix: replace the ad hoc Tkinter overlay with
  a purpose-built region-selection approach that doesn't depend on
  Tkinter's threading assumptions at all.
- Out of scope for this report: any other Tkinter/`keyboard` interaction
  bugs. Keep this report scoped to the KeyError symptom above.
