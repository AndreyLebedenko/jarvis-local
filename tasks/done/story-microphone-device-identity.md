# Story: Microphone device identity and visible capture failure

**Status:** Completed. Owner-run verification 2026-07-25; see "Verification
run outcome" below.
**Created:** 2026-07-25.
**Raised by:**
`tasks/bug_reports/2026-07-24-microphone-device-name-ambiguous-across-host-apis.md`,
found during the v1.6.2 LAN camera release checklist and deferred there
on purpose.
**Roadmap:** not a roadmap feature. This is release-blocking stabilization
for the work accumulated on `main` since v1.6.4.

## User-facing goal

Selecting a microphone in Settings makes Jarvis listen to that
microphone. When it cannot, Jarvis says so at the moment it happens,
instead of running as a healthy-looking assistant that answers nothing.

## Why this blocks a release

Windows exposes one physical microphone once per host API, and PortAudio
lists each copy under an identical `name`. The Settings selector stores a
bare name (`src/jarvis/ui/status_console.py`,
`_default_microphone_options_source()`), and the capture path hands that
name to PortAudio (`src/jarvis/audio/input.py`,
`_default_stream_factory()`), which matches it against device names, finds
four, and raises. The selection persists in `config.ui.toml`, so the state
is sticky across restarts, and the raised exception is only observed
during shutdown teardown. The result is a deaf assistant with a microphone
chip that still reads "listening".

Shipping a release whose microphone selector is a trap is worse than
delaying it.

## Design decisions (owner, 2026-07-25)

1. **Device identity is name plus host API, in two config fields.**
   `[microphone].device` keeps its meaning and gains an optional
   `[microphone].host_api`. A bare name that is unambiguous on this
   machine keeps working exactly as before, so no existing configuration
   needs migration. Rejected: encoding both into one delimited string
   (introduces a separator that can occur inside a device name), and
   storing a PortAudio index (stable only within one enumeration).
2. **An unresolvable selection degrades the module; it does not stop
   startup.** This departs from the bug report's own suggestion of a
   config error at startup. The remedy - the Settings tab - lives inside
   the console, and a hard startup failure locks the user out of the only
   place they can fix the setting. Failure must be loud instead: chip in
   ERROR, one events-panel entry, one system-log line, all naming the
   candidates.
3. **Silent failure is fixed in the same story.** Device identity closes
   one known way to break the microphone; it does not close the class
   "the microphone died and nothing said so". Both halves ship together
   or the next failure is invisible again.
4. **Host API stays the user's choice.** PROJECT.md ties MME to both the
   wake-recovery fix (2026-07-11) and the post-mute degraded-capture
   finding (2026-07-18), so the selector shows every host API copy with
   its API named, rather than curating one. Resolution must never
   silently move an existing configuration to a different host API.

## Boundaries

- No change to VAD, chunking, capture quality, or the sleep/wake design.
- No automatic retry or device-hotplug recovery. A failed microphone
  reports and stays reported until restart; recovery design is out of
  scope and is not implied by this story.
- No new dependency. `sounddevice` already exposes everything needed.

## Scope (ordered task cards)

1. `tasks/done/task-microphone-device-identity.md` - identity, resolution, and
   the selector.
2. `tasks/done/task-microphone-failure-visibility.md` - a capture loop that
   cannot start says so, at the moment it happens.

## Acceptance criteria

- [x] A device selected in Settings opens, including when several host
      APIs expose the same name.
- [x] An existing `config.ui.toml` holding a bare unambiguous name keeps
      working, on the same host API it resolved to before.
- [x] An ambiguous or missing device produces a degraded microphone chip,
      one events-panel entry, and one system-log line naming the
      candidates - not a silent background failure and not a startup
      abort.
- [x] Device enumeration has one implementation in the package;
      `manual/manual_check_microphone_devices.py` consumes it instead of
      keeping its own copy.
- [x] `python -m pytest` and Ruff are green.
- [x] Human-run hardware verification per the testing protocol, on a
      machine with a multi-host-API microphone.

## Verification run outcome (2026-07-25)

The owner selected an unworkable device, confirmed the error chip and the
warning on `Ctrl+Alt+M`, then selected Yeti X on MME and confirmed capture
works: the journal records the utterance, it plays back clearly, and the
system log carries `[LLM] Model request: inputs=audio count=1`. The
release-blocking defect this story existed for is closed.

Two things came out of the run and neither belongs to this story:

1. **The model answers a voice turn with a refusal to listen.** Captured,
   delivered, and then refused - a separate and older defect, traced
   across four experiments during this run and recorded in
   `tasks/bug_reports/2026-07-25-model-stopped-comprehending-voice-audio.md`.
   Comprehension itself is confirmed working; weak audio triggers a
   refusal and the refusal then persists through the session's history.
2. **The failure mode nobody predicted was the useful one.** The device
   picked to be "broken" answered `Invalid sample rate` rather than an
   ambiguous name, and the reporting path handled it identically. That is
   the argument for having built the visibility half at all.

**Not re-run after the last change:** step 1's Bluetooth listing. The
`--list-only` output that motivated the label work was captured before it
landed; the labels themselves have automated coverage and were checked in
the QA harness, but no one has looked at the real listing since. Cheap to
do on the next run of that script.

## Human-run verification checklist

Hardware-dependent per the testing protocol; nothing below is something
the agent can sign off. Run on the machine with the Yeti X, which is the
one that reproduces the original failure. Back up `config.ui.toml` first -
step B edits it by hand.

### A. Enumeration and selection

1. `python -m manual.manual_check_microphone_devices --list-only` lists
   every input device with its host API, one device per line. The three
   Bluetooth headsets must read as `Headset (Galaxy Buds Live (2A04))`,
   `Headset (TicPods ANC)`, `Headset (C15)` - not as the raw
   `bthhfenum.sys` resource strings that used to wrap onto a second line.
2. Start with the console, open Settings: the Yeti X appears once per
   host API, each row naming its API, instead of four identical rows.
3. Select the WASAPI copy, Apply. `config.ui.toml` now holds both
   `device` and `host_api` under `[microphone]`.
4. Restart, speak. The turn is captured and sent: the Journal shows the
   utterance and plays it back, and `logs/jarvis.log` records
   `[LLM] Model request: inputs=audio count=1`. This is the whole bug:
   before this change the same selection produced a session that captured
   nothing at all.
   **Note (2026-07-25 run):** the model's *answer* to a voice turn is
   currently a refusal to listen. That is a separate, older defect -
   `tasks/bug_reports/2026-07-25-model-stopped-comprehending-voice-audio.md` -
   and it does not block this step. What this step verifies is capture and
   delivery, both of which the log line and the playable recording prove.
5. Repeat with the MME copy and confirm capture still works, so the
   choice is real rather than nominal.

### B. Failure is visible

6. Edit `config.ui.toml` by hand to `device = "Microphone (Yeti X)"` with
   `host_api = ""` (the exact state the bug left behind) and start
   Jarvis. Expected, within a second: the microphone chip reads error
   ("capture stopped" / "захват остановлен"), one events-panel entry says
   the microphone stopped and to check Settings, and `logs/jarvis.log`
   carries `Microphone capture stopped:` with PortAudio's own candidate
   list.
7. Jarvis is still usable: a typed turn in the Journal tab works, and
   Settings opens so the microphone can be re-selected.
8. The events-panel entry names no device. Search the panel for "Yeti":
   nothing. Search `logs/jarvis.log` for it: present. That split is the
   content rule.
9. Repeat step 6 with `host_api = "Windows WDM-KS"` misspelled or absent
   from the machine - same behavior, message names what was found.
9a. While the microphone chip is in error, press `Ctrl+Alt+M` twice
    (mute, unmute). The chip must stay in error, each press must add a
    warning entry saying the microphone is stopped until restart - never
    "Microphone awake" - and both presses must play the sleep cue, not
    the wake cue.
9b. Start Jarvis with the broken configuration and mute *before* the
    first wake. Nothing is reported while muted; the failure appears on
    the first unmute. This is expected: capture only proves a device
    broken when it opens it.

### C. The quiet paths stay quiet

10. A normal session with several sleep/wake cycles (`Ctrl+Alt+M`)
    produces no failure entry and no error chip.
11. A normal shutdown (`Ctrl+Alt+Q` and the console's Shutdown) produces
    no failure entry.

### D. Rendering, both languages

12. `src/jarvis/ui/status_console_ui/demo.html`, "mic options": the
    sample repeats one name across two host APIs, so the labels can be
    read without owning four devices. Check both UI languages.

## Stop conditions

- Resolution needs a PortAudio behavior that cannot be verified without
  hardware: write the check, hand it over, do not guess.
- The fix turns out to require reworking the sleep/wake stream lifecycle:
  stop and report; that is a separate design.
