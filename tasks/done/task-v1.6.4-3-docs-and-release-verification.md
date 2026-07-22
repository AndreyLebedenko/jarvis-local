# Task v1.6.4-3: Docs and release verification

**Status:** Completed. The human ran the combined checklist below on
2026-07-22 and reported every section passing, after the two defects it
surfaced were fixed (see "Verification run outcome").
**Story:** `tasks/done/story-v1.6.4-observability-and-logging.md`
**Depends on:** tasks v1.6.4-1..2, and v1.6.4-4, which closed the file
log's missing request line after this card was written.

## Summary

Record the two-log contract and its content rule where future work will
actually read them, and prepare the human-run release check.

## Boundary

- Documentation and checklist only, with one agreed exception below.
  Fixes revealed by verification that are larger than trivial become bug
  reports per the project protocol.

**Agreed boundary extension (owner decision, 2026-07-22):** the demo/QA
harness gained a sample for the new typed panel entry. `demo.js` could
drive the chip strip but not the panel entry, so the harness showed less
than the product does - the exact failure the task-ui-07 precedent
exists to prevent, and it would have made a whole checklist section
unverifiable without a live turn per modality. One button now drives
both surfaces from one payload, mirroring transport.py's
`_on_model_request_started`, and the sample set covers every
`last_request_*` key. Two tests pin both properties.

## Outcome

- `PROJECT.md` gained an "Architecture v1.6.4" section stating the
  two-log contract as a design criterion: which log is for whom, why the
  system log is English, why a UI panel is not a diagnostic tool, the
  content rule binding both, the configured location and justified
  rotation bounds, the locality argument, and the two "do not simplify
  this back" notes (the typed sibling payload, and the request line that
  deliberately bypasses `publish_system_event()`).
- Two stale claims elsewhere in `PROJECT.md` were corrected rather than
  rewritten: the v1.1 note that `run()` calls a bare `basicConfig()` now
  carries a "superseded by v1.6.4" pointer that keeps its original
  reasoning intact, and the speech-markup section no longer says
  `main.py` sends warnings only to the console.
- `README.md` and `README.ru.md` gained a "Logs and diagnostics" section
  in user terms: which file to attach to a problem report, where it is,
  what bounds it, that it never leaves the machine on its own, what the
  events panel does and does not show, and why the panel is not a
  substitute for the file.
- `config.example.toml`'s `[logging]` section already documented the
  directory-not-filename rule from task-v1.6.4-1; no change needed.
- Screenshots in the README files are refreshed by the human, not by the
  agent.

## Human-run release verification checklist (v1.6.3 + v1.6.4)

**This is one combined checklist on purpose.** v1.6.3's deferred visual
review and v1.6.4's checks both exercise the Status Console, and running
them separately would mean opening the same window and the same log file
twice for the same session. The v1.6.3 half is reproduced from
`tasks/done/task-v1.6.3-3-docs-and-verification.md`; record outcomes here.

WebView visual review is human-run per the testing protocol; nothing
below is something the agent can sign off. Run Jarvis normally, once per
UI language (`[ui].language = "en"` and `"ru"`).

### A. Header, on every tab

1. Exactly three tabs render: Status, Journal, Settings.
2. Brand, `LOCAL`, `LOCAL SOURCES`, and Open/Hidden stay in place and
   keep their values when switching tabs.
3. Tab captions are translated; no English text leaks into the Russian
   UI and no key names render raw.

### B. Status tab

4. No scrollbar at the default window size immediately after startup.
5. After a voice turn, the chip strip under the orb shows the voice
   modality with its duration; after a screen-capture turn, it shows the
   screenshot modality.
6. Module chips, including the v1.6.2 camera chip, reflect live health.
7. Reasoning level changes made by hotkey and by voice both render here,
   not only changes made from this tab.
8. MCP toggle round-trips: enable, tools appear, disable, tools clear.
   With a long tool list, the list scrolls inside its own card and
   Shutdown does not move.
9. System events keep arriving while other tabs are open and after
   returning to Status.
10. Shutdown asks for confirmation; opening the confirmation does not
    move the Shutdown button. Cancel leaves the engine running.
11. There is no context reset control anywhere on Status.

### B2. Every tab at a short window

Added 2026-07-22 after the run found a form clipped at the top with no way
to scroll to it
(`tasks/bug_reports/2026-07-22-quiet-microphone-capture-and-unselectable-device.md`).
The console window is created at 960x900 and the Settings form fits 900 px
exactly, so a default-size pass proves nothing about the case below it.
Resize the window to roughly half its height, then, on each of the three
tabs:

4a. Every control is reachable - either visible, or reachable by
    scrolling. Nothing is cut off at the *top* of a scrolling area.
4b. The first field of the Settings form (Model) and the second
    (Microphone) are both reachable.
4c. No content is clipped horizontally.

### C. Journal tab

12. Opens without reload loops; the feed, memory files, and attachments
    behave as before the reorganization.
13. "Новый контекст" is present and is the only context reset on this
    surface.
14. Switching away with unsaved memory edits still asks for
    confirmation, and cancelling keeps the edits.

### D. Settings tab

15. Contains model, microphone, UI language, TTS routes, and VAD.
16. Entering the tab refreshes model and microphone options; Apply stays
    disabled until both have loaded.
17. A settings edit saves and reports restart-to-apply; the change is
    present in `config.ui.toml` and takes effect after a restart.
18. There is no Settings button anywhere on Status.

### E. Hidden mode

19. Hidden behaves exactly as before the reorganization on all three
    tabs; Journal content is replaced by the generic placeholder and no
    memory or journal text is exposed.
20. Switching tabs while Hidden never reveals content that Open mode
    would show.
21. Hidden reveals nothing in the events panel that Open mode did not
    already show. The panel is not hidden by design, and this check is
    what keeps that acceptable.

### F. The user-facing request record (events panel)

Perform one turn of each kind - voice, a screenshot-carrying turn, a
clipboard turn, a typed message, and a turn with an attachment.

22. Each turn adds one panel entry, marked as a request record rather
    than as a warning or error, showing the correct localized modality.
23. The voice turn's entry shows its duration, with the unit in the
    interface language (`s` / `с`) - not a hardcoded English unit.
24. The chip strip under the orb shows the same turn's modalities. The
    two surfaces never disagree.
25. Each turn produces exactly one entry, not a localized entry plus a
    second raw English diagnostic.
26. No file name, transcript, clipboard text, or byte size appears in
    any entry.

`src/jarvis/ui/status_console_ui/demo.html` covers items 22-24 for every
modality without a live turn, including the ones that are awkward to
produce on demand: open it in a browser, use the "last request:" buttons,
and switch language from the console. It is a rendering harness, not a
substitute for items 25-26, which only the live engine can answer.

### G. The system log

27. `logs/jarvis.log` exists after starting Jarvis **not** from a
    terminal, so stderr is not attached.
28. It contains the startup lines, the session's engine events, and the
    shutdown sequence, and it is still there after the process exits.
29. Each accepted turn from section F appears as one
    `[LLM] Model request: inputs=... count=N` line, with
    `audio_duration=` present for voice and absent otherwise.
30. That line is present even for a turn whose backend call failed or
    was interrupted - it is written before the call, not after.
31. No transcript text, clipboard text, attachment file name, or media
    content appears anywhere in the file. Search it for a distinctive
    phrase you actually spoke and for the name of a file you attached;
    neither should be found.
32. Report the file size after a normal session, so the 2 MB / 5-file
    rotation bounds can be sanity-checked against real usage.
33. Optional rotation check: set `[logging].max_bytes` to something
    small (for example 20000), run a session, and confirm
    `jarvis.log.1` appears and the file count stops at
    `backup_count`.
34. Set `[logging].directory` to an unwritable path, start Jarvis, and
    confirm it starts anyway with a warning rather than failing.

## Verification run outcome (2026-07-22)

The human ran the checklist and reported all sections passing. Two
findings came out of it, reported together as "the microphone does not
work" and "I cannot find the microphone setting" - one problem and its
blocked remedy.

1. **The Settings form was unreachable at the top on a short window.**
   `.config-panel` carried `align-self: center` from the pre-v1.6.3
   layout, where its parent was a column flex and the declaration meant
   "center horizontally". Task v1.6.3-2 relocated the panel into
   `.settings`, a row flex, where the same untouched declaration meant
   "center vertically" and overrode the container's `align-items:
   flex-start`. A flex item centered on the axis it overflows spills past
   the start edge into space no scrollbar reaches: Model and Microphone,
   the first two fields, were cut off with no way back. Fixed here;
   regression test
   `tests/test_ui_qa.py::test_the_settings_form_is_not_centered_on_the_axis_it_overflows`.
2. **Microphone capture was very quiet** (peak -26.8 dBFS, RMS ~-46 dBFS
   on the journal's own recordings), because the Windows default input
   device was in use and could not be changed - finding 1 was why. Not an
   engine defect; resolved by the human selecting the correct device.
   Reported in
   `tasks/bug_reports/2026-07-22-quiet-microphone-capture-and-unselectable-device.md`,
   which also records the observability gap it exposed: the system log
   knows neither the opened device name nor any capture level, so the
   whole diagnosis had to be reconstructed from journal wav files. That
   gap needs an owner decision before any code, because a device name is
   payload-adjacent under the content rule.

**The checklist itself was the deeper miss.** Section B checked Status
for a scrollbar at the default size and nothing checked any tab below it,
while the console window is created at 960x900 and the Settings form fits
900 px exactly. Section B2 was added in response.

## Acceptance criteria

- [x] `PROJECT.md` and user docs updated in the same release as the
      behavior change.
- [x] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [x] `python -m pytest` and Ruff checks are green.
