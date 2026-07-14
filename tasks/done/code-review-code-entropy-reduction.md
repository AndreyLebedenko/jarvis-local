# Code Review: Code Entropy Reduction

**Branch:** `code-entropy-reduction`
**Review status:** Changes requested.
**Reviewed:** 2026-07-14.

## Findings

### P1: Preserve the existing `ConfigError` message contract

Location: `src/jarvis/core/config.py:545`

The validation refactoring changes user-visible error messages:

- `str` becomes `string`;
- `int` becomes `integer`;
- `float | None` becomes `number | None`;
- `bool | None` becomes `boolean | None`.

This conflicts with the explicit task boundary requiring existing error types
and message wording to remain unchanged. The task card also defines an error
message change as a stop condition. The fact that current tests only match a
field name or a partial phrase does not relax that requirement.

Required action: keep the shared validation predicate, but preserve the old
type descriptions produced by `_describe_type()` when constructing
`ConfigError` messages.

### P1: Do not erase the Piper voice interface to `object`

Location: `src/jarvis/audio/tts_piper.py:101`

The new cache is typed as `LazyAsyncLoad[tuple[object, object]]`. After
unpacking the tuple, Pyright cannot establish that `voice` has a
`synthesize()` method and reports:

```text
src/jarvis/audio/tts_piper.py:110:19 - error: Cannot access attribute
"synthesize" for class "object"
```

This is a new finding in changed code and contradicts the project's rule
against type erasure. It also makes the task-card claim that changed TTS
construction sites have no Pyright findings inaccurate.

Required action: give the cached pair concrete types or introduce narrow
protocols describing the voice and synthesis-configuration contracts. The
lazy import boundary must remain intact.

### P2: Cover the shared double-checked locking behavior with a concurrent test

Location: `src/jarvis/audio/tts.py:76`

Existing tests prove sequential success caching for Piper and sequential
terminal-error caching for Silero. They do not start concurrent callers.
Consequently, the two rechecks inside `async with self._lock` are not exercised
and the central guarantee of the new helper - one loader invocation under a
race - is not protected against regression.

Required action: add a focused test that starts at least two concurrent
`LazyAsyncLoad.get()` calls with `asyncio.gather()`, holds the loader long
enough for both callers to contend for the lock, and asserts that:

- the loader runs exactly once;
- both callers receive the same cached value;
- the equivalent concurrent failure path caches and re-raises the same
  `TtsEngineLoadError` instance.

## Verification

- `python -m pytest`: 657 passed, 1 skipped.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed, 91 files already formatted.
- `python -m pyright`: 274 errors, matching the recorded project-wide count,
  but including the new `tts_piper.py:110` finding described above.

Hardware-dependent checks were not run, per the project testing protocol.
They are not required for these pure refactorings.

## Working-tree note

`.claude/settings.json` is untracked and contains an absolute, machine-specific
path under `C:\Users\adinor`. If it is intended for the branch, make the hook
command portable. Otherwise, keep it local and add the appropriate ignore
rule.

## Conclusion

The automated runtime suite remains green, but the changes are not ready for
acceptance. Resolve both P1 findings and add the missing concurrency coverage
before human re-review.
