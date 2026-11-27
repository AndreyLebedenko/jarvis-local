# Session-id test assumes the current UTC offset applies in July

Status: Fixed 2026-11-24. Originally reported outside the consultation-export spike scope.

Detected at commit `e3d38562dda7887599d1750cc9c64f01dfd4d322`, branch
`codex/spike-consultation-export`, with uncommitted spike code and planning docs.
No production journal or timezone code changed. The same test failure was
previously recorded in `task-v2.1.1-6-docs-and-release-verification.md`.

## Symptoms and evidence

`python -m pytest` on 2026-11-16: 6294 passed, 1 skipped, 1 failed in 170.76 s.
The sole failure is
`tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix`.
It expects `20260716-153000`, but receives `20260716-163000`.
The new isolated consultation harness tests all pass (33 tests).

This is an automated verification failure; no new user-visible runtime defect
has been established by this run.

## Suspected cause

The test takes `datetime.now().astimezone().tzinfo`, attaches that current offset
to July 16 at 15:30, and expects the local display time to remain 15:30. In a
timezone with a different July UTC offset, converting that instant to local time
can legitimately produce 16:30. The assertion therefore depends on the season
when tests run. This is a source-level hypothesis supported by the one-hour
observed difference, not a new runtime timezone investigation.

## Temporary decision

Stop the spike under AGENTS.md section 0.5. Do not exclude the test, alter system
timezone/environment, or expand this feature into a journal fix. Leave the
harness and evidence ready for review; no live Ollama calls have run. Keeping the
failure visible respects the task boundary instead of hiding an unrelated red
gate behind a filtered test run.

## Future boundary

The owner can authorize a separate deterministic test fix or explicitly allow
the isolated PoC to proceed with this known failure recorded. A later fix should
decide whether it tests instant conversion or wall-clock formatting, exercise
seasonal offsets without relying on today's timezone, and preserve the runtime
local-time session-id contract. This spike does not choose that implementation.

## Owner decision, 2026-11-17

The owner explicitly allowed the isolated consultation PoC to continue with this
known failure recorded. The test remains unfixed and was not excluded; this
exception does not apply to other tasks or change the general stop rule.

## Resolution, 2026-11-24

The test constructs January and July local wall times using each date's UTC
offset. It passes the corresponding UTC instants to `new_session_id` and checks
the expected local prefixes. The production journal code is unchanged.
