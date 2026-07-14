# Task: Extract shared TTS engine lazy-load helper

**Story:** `tasks/done/story-code-entropy-reduction.md`
**Status:** Completed.

## Summary

`SileroEngine._ensure_model()` (`src/jarvis/audio/tts_silero.py`) and
`PiperEngine._ensure_voice()` (`src/jarvis/audio/tts_piper.py`)
independently implement the same double-checked-locking pattern: check a
cached error and raise it; check a cached value and return it; acquire an
`asyncio.Lock`; re-check both under the lock; call the engine-specific
loader; on exception, wrap it in `TtsEngineLoadError` and cache it before
re-raising; otherwise cache and return the loaded value. A future
concurrency fix or bug in this pattern would have to be found and applied
twice.

## Boundary

In scope:

- A single shared helper (e.g. a small class or function in
  `src/jarvis/audio/`) implementing: check cached error -> raise; check
  cached value -> return; acquire lock; re-check both; call a supplied
  async loader callable; on exception, wrap into `TtsEngineLoadError`
  (using the engine/model identifiers already available on each route)
  and cache it; on success, cache and return the value.
- Refactor `SileroEngine._ensure_model()` to use it, loading a single
  cached value (the model).
- Refactor `PiperEngine._ensure_voice()` to use it. Note `PiperEngine`
  caches *two* values from one load (`self._voice`,
  `self._synthesis_config`) - the helper must support this without
  forcing an artificial single-value wrapper that changes call-site
  ergonomics.
- Preserve current behavior exactly: same `TtsEngineLoadError` type,
  message, and caching semantics (an error, once cached, keeps being
  raised on every subsequent call; a value, once cached, is never
  reloaded); same lock granularity (one lock per engine instance).
- Existing Silero/Piper tests covering load failure, load success, and
  caching behavior continue to pass without behavior changes (import
  path updates only, if any).

Out of scope:

- Any change to synthesis behavior itself.
- Any change to `TtsEngineLoadError`'s shape or message.
- The TTS field-validation duplication (Task 2 - separate task card).

## Acceptance Criteria

- One shared implementation of the load-once/cache-error pattern is used
  by both `SileroEngine` and `PiperEngine`; neither reimplements it.
- `python -m pytest` passes, including existing Silero/Piper load-error
  and caching tests, unmodified in behavior.
- `python -m ruff check .` and `python -m ruff format --check .` stay
  green.
- `python -m pyright` finding count does not increase.

## Findings (2026-07-14)

Added `LazyAsyncLoad[_T]` to `src/jarvis/audio/tts.py`, next to
`TtsEngineLoadError` (which both engines already imported from there): a
generic `get(loader)` that checks a cached error and raises it, checks a
cached value and returns it, then acquires an `asyncio.Lock` and re-checks
both before calling `loader()`, wrapping any exception in
`TtsEngineLoadError` and caching it, or caching and returning the
successful value.

`SileroEngine._ensure_model()` now delegates to a
`LazyAsyncLoad[LoadedSileroModel]` instance; `PiperEngine._ensure_voice()`
now delegates to a `LazyAsyncLoad[tuple[object, object]]` instance (Piper
loads a `(voice, synthesis_config)` pair from one call - the generic
helper caches the pair as a single value, and `synthesize()` unpacks it,
removing the two separate `self._voice`/`self._synthesis_config` mutable
attributes entirely rather than forcing an artificial single-value
wrapper).

Verified: `python -m pytest` (657 passed, 1 skipped, including
`test_silero_engine_caches_a_terminal_load_failure`,
`test_piper_engine_loads_voice_only_once`, and the rest of `test_tts.py`
unmodified) - no test changes were needed, confirming behavior is
unchanged. `python -m ruff check .` / `format --check .` stay green.
`python -m pyright`: 274 findings, unchanged from before this task.

## Review fixes (2026-07-14)

`tasks/code-review-code-entropy-reduction.md` requested changes on two
points:

**P1, type erasure in `PiperEngine`.** Typing the cached pair as
`LazyAsyncLoad[tuple[object, object]]` erased `voice`'s real interface,
and Pyright flagged a new `Cannot access attribute "synthesize" for
class "object"` at the `voice.synthesize(...)` call - a real regression,
and one that made this card's original "no new findings" claim wrong.
Fix: added a `LoadedPiperVoice` Protocol (mirroring `tts_silero.py`'s
existing `LoadedSileroModel` Protocol) with a positional-only
`synthesize(self, text, synthesis_config, /)` signature - positional-only
because the real `piper.voice.PiperVoice.synthesize()`'s second parameter
is named `syn_config`, and Python's structural typing for callables
requires either matching names or positional-only params. `synthesis_config`
itself is typed via a `TYPE_CHECKING`-only import of `piper.config
.SynthesisConfig` (the runtime lazy-import in `_load_voice()` is
untouched - `TYPE_CHECKING` imports never execute), because Pyright's
contravariant parameter check rejects a `object`-typed protocol parameter
against the real, narrower `SynthesisConfig | None` parameter it must
substitute for. `VoiceLoader.__call__`'s return type changed from
`object` to `LoadedPiperVoice` to match. This is the first
`TYPE_CHECKING`-guarded import in this codebase; it was the correct tool
here specifically because the alternative (a hand-written protocol
describing `SynthesisConfig`'s shape) would have had to be kept in sync
with a real third-party type by hand - itself a small instance of the
entropy this story exists to avoid.

Fixing this exposed two more pre-existing latent gaps in the same area,
both real (not caused by this task, but only surfaced once Pyright had a
concrete type to check against instead of `object`): `TtsEngine`
(`tts.py`)'s Protocol method used `pass` instead of `...` as its stub
body, which Pyright reads as an actual (wrong) implementation returning
`None` against a declared `-> bytes`; and `LoadedSileroModel.synthesize()`
had no return-type annotation at all, so `audio_tensor =
await asyncio.to_thread(model.synthesize, prepared)` inferred as `None`.
Fixed both (`pass` -> `...`; added `-> torch.Tensor`, importing `torch` at
module level in `tts_silero.py` - already an eager, non-lazy dependency
elsewhere in this project, e.g. `audio/utils.py`, `audio/input.py`).

**P2, missing concurrency coverage.** Added
`test_lazy_async_load_runs_loader_once_for_concurrent_callers` and
`test_lazy_async_load_caches_and_reraises_same_error_for_concurrent_callers`
to `tests/test_tts.py`: each starts two `LazyAsyncLoad.get()` calls via
`asyncio.create_task()`, synchronizes with `asyncio.Event`s so the second
call is guaranteed to reach and block on the lock while the first is
still inside its loader, then asserts the loader ran exactly once, both
callers got the same cached value (or, in the failure test, the exact
same cached `TtsEngineLoadError` instance), for both the success and
terminal-error paths. Ran 5x locally to check for scheduling-order
flakiness - stable every time.

Re-verified after all fixes: `python -m pytest` 659 passed, 1 skipped
(657 + the 2 new concurrency tests). `python -m ruff check .` /
`format --check .` stay green. `python -m pyright`: 271 findings - three
fewer than the 274 baseline (the two pre-existing latent gaps above are
now fixed, on top of the Piper erasure not regressing anything).
