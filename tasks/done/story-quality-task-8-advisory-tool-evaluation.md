# Task: Evaluate advisory quality tools

**Story:** `tasks/done/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Evaluate Pyright and Semdup against the final package layout and record whether
each has enough signal and stability to become a future project check.

## Acceptance Criteria

- [x] Pyright findings are classified by defect signal and remediation cost.
- [x] Semdup findings are classified as actionable duplication, intentional
      similarity, or false positive. (N/A: tool could not be installed; see
      below.)
- [x] Cold/incremental runtime and operational dependencies are recorded.
- [x] A direct recommendation is recorded for each tool: gate, advisory, or
      reject.

## Findings (2026-07-14)

### Pyright

Ran `python -m pyright --outputjson` against the final `src/jarvis` layout:
313 errors, 0 warnings, 91 files analyzed (up from the 203 pre-migration
baseline in Task 1, largely because the analyzer now resolves the full
`tests/` and `manual/` trees consistently under the installed package).

By rule: `reportArgumentType` 193, `reportIndexIssue` 36,
`reportAttributeAccessIssue` 27, `reportOptionalSubscript` 12,
`reportCallIssue` 12, `reportGeneralTypeIssues` 10,
`reportFunctionMemberAccess` 10, `reportOptionalMemberAccess` 7,
`reportReturnType` 3, `reportAssignmentType` 1, `reportMissingImports` 1,
`reportOptionalIterable` 1.

Classification:

1. **Test-double/fixture noise - no signal, high remediation cost (192
   findings, 61%).** `tests/test_main.py` (103) passes fakes/`None` for
   composition-root dependencies typed as concrete classes
   (`OllamaBackend`, `AudioInput`, `TtsOutput`, ...) instead of protocols -
   exactly the pattern Task 1's baseline flagged. `tests/test_ui_transport.py`
   (89) indexes a loosely-typed `JSONValue` union with string-literal keys,
   which Pyright correctly (but unhelpfully) refuses because the union
   includes `int | float | bool | None`. Fixing either requires a real
   design change (Protocol-based DI for the composition root, or a narrower
   typed schema for transport payloads) - out of this task's scope per the
   story boundary ("stop if a quality rule demands ... broad refactoring").
2. **ctypes/Win32 stub noise - no signal (13 findings, `src/jarvis/inputs/hotkeys.py`).**
   `ctypes.windll` functions resolve to generic `object` under typeshed;
   there is no practical fix short of hand-written `.pyi` stubs for the
   Win32 API surface used here.
3. **asyncio/typeshed strictness - no signal (5 findings, `sound_cues.py`,
   `ui/transport.py`).** `Awaitable` vs `CoroutineType` in `create_task`,
   `AbstractServer.sockets` (the real runtime object is `asyncio.Server`,
   which has `.sockets`), and `Callable` variance in `subscribe`/`unsubscribe`
   are all runtime-safe patterns the current stubs can't express.
4. **Config/settings construction - no signal, already validated at
   runtime (39 findings: 23 in `core/config.py`, 16 in
   `ui/transport.py`).** Corrected after the follow-up task
   (`tasks/task-config-settings-type-validation.md`, completed
   2026-07-14): building `TtsLanguageSettings`/`TtsSettings` from a raw
   config dict, and the equivalent transport JSON payload, both already
   validate every field with `_matches_type()`/manual `isinstance` checks
   and raise `ConfigError`/`ProtocolError` *before* construction (see
   `test_engine_specific_tts_settings_reject_invalid_values` in
   `tests/test_config.py`). Pyright cannot trace that generic,
   loop-driven validation back to the precise constructor parameter
   types, and separately cannot resolve `dataclasses.fields()`'s
   `Field.type` (typed `type[Any] | str`) against the plain `type`
   parameter of this module's own `_matches_type`/`_describe_type`
   helpers. Both are the same class of typeshed/inference limitation as
   items 1-3, not a missing validation. Suppressed with
   `# type: ignore[arg-type]` at the 9 affected call/construction sites,
   matching the existing precedent at `ui/transport.py`'s
   `_parse_vad()` (`VadSettings(**kwargs)  # type: ignore[arg-type]`,
   already in the codebase before this evaluation). No behavior change;
   `python -m pytest` and `python -m ruff check .`/`format --check .`
   stay green.
5. **Suspected optional-handling gaps - uncertain signal, needs a manual
   look (8 findings: `app.py:752`, `status_console.py:526`,
   `hotkeys.py:230,244,248,254,255`).** Pyright can't see a runtime
   invariant (e.g. "set before use") that may be guaranteed elsewhere. Not
   confirmed bugs; worth a quick manual pass, not urgent.

**Recommendation: Advisory.** All remaining volume (274 of the original 313
findings) is either a DI/typing redesign, inherent typeshed/stub noise, or
uncertain-signal optional-access spots - none of which this quality-tooling
story should force into a CI gate (see story stop conditions). Keep
`python -m pyright` as a manual, local check; do not wire it into CI.

### Semdup

No installable package or locatable source under the name "Semdup" exists:
`pip index versions semdup` and `pip download semdup` both report no
matching distribution, and web search under several spellings turns up
nothing (only unrelated tools: SemHash, SemDeDup, Duplo, jscpd, PMD CPD).
Per Task 1's own stop condition ("otherwise record the environmental
blocker and stop rather than work around it"), this is recorded as an
unresolved environmental blocker, not routed around by substituting a
different tool under the same recommendation.

No cold/incremental runtime could be measured, since nothing installed.

Independently of installability: Semdup's documented purpose is detecting
semantic logic duplication introduced by multiple agents editing the same
codebase in parallel (a "swarm" workflow). Jarvis development is sequential
and human-supervised - the condition Semdup exists to catch does not occur
here.

**Recommendation: Reject.** Do not reattempt installation. If duplicate-logic
detection becomes valuable later, evaluate a different, resolvable tool
under a new task card rather than continuing to chase this specific name.

