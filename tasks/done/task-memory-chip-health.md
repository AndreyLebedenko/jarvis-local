# Task: Memory chip health

Status: Completed. Implemented and human-verified by the owner, 2026-11-27.
Detected at commit a496f98. Standalone card, no story.

## Problem

The Memory chip in the status console modules panel is always grey with an empty detail
line. Nothing publishes a health signal for `ModuleId.MEMORY`: `ModuleHealthTracker`
(`src/jarvis/ui/module_health.py`) has transitions for Backend, Microphone, TTS, Vision and
Camera only, and the frontend renders a module without a payload as `unavailable`
(`status_console_ui/app.js`, `renderModules`). The chip looks switched off while the memory
tools work. `ModuleId.MEMORY` was added for the mock-up and defined as "conversation history
and context, not a separate storage service" (`ui/contract.py`).

## Decision (owner, 2026-11-27)

The Memory chip reports whether the long-term memory tools are ready to work: the history
search (`search_history`, backed by the journal search index and the semantic index) and the
`remember` tool (backed by the `self` and `memory` files). This replaces the contract
wording above; the docstring and `PROJECT.md` change in the same commit.

One `ok` is not enough, because "ready" fails in different ways. Four statuses:

| Status | Meaning |
|---|---|
| `ok` | Search works with its configured indices, and `remember` can write. |
| `degraded` | Part works: semantic search is down while lexical works, or a memory file is full (`remember` is refused for it). |
| `error` | A memory file raised `OSError` on read or write. |
| `unavailable` | Not known yet: no health signal has arrived since start. |

Every status other than `ok` carries a detail key that names what is wrong, in EN and RU.
"Semantic search disabled in config" is the user's choice, not a fault: it is not `degraded`.

## Facts established in the code (2026-11-27)

- `remember` writes to files through `MemoryFileRepository`, not to a database. A write over
  the cap returns an error result ("file is full", `tools/builtin.py`, `_remember`).
- `search_history` is always registered; there is no config switch for it or for `remember`.
  So "unavailable by config" does not exist for the two tools. Config switches exist only
  for the semantic index (`history.semantic.enabled`), annotations and transcription.
- `SemanticPassageIndex.state()` (`journal/semantic.py`) already reports enabled, unbuilt,
  and unavailable with a `last_error` (backend mismatch, runtime failure). It is a pull
  accessor; it publishes nothing on the bus.
- `JournalSearchIndex` (`journal/search.py`) has no state or health accessor.
- Solo session mode (`core/solo_session.py`) turns `search_history`, `read_history`,
  automatic retrieval and memory file injection off for the current session.
- `ModuleHealthTracker` is event-driven by its own docstring: "No polling, no probes".

## Design constraint and the choice that follows

The tracker only consumes bus events. The memory components publish none, so something has
to start publishing. Two ways:

- A. Memory components publish small health events (index built or failed, semantic state
  changed, memory file full or recovered, solo toggled) and the tracker subscribes, like
  every other module. Keeps the tracker's rule. More surface: each source needs a publisher
  and a test.
- B. The tracker reads `SemanticPassageIndex.state()` and the file sizes when asked. Smaller,
  but it breaks the "no polling, no probes" rule and needs a trigger to ask.

Decided (owner, 2026-11-27): A. Memory components publish health events; the tracker
subscribes.

## Boundary

In: the new health events and their publishers, the tracker subscriptions and transitions
for `ModuleId.MEMORY`, a startup signal so the chip is not grey until the first incident,
detail keys (EN, RU) in `ui/text.py` and `status_console_ui/strings.js`, the `ModuleId`
docstring, `PROJECT.md`, tests.

Out: the memory panel, the file caps, the semantic index behaviour, annotation and
transcription health, any new module chip, any probing of Ollama on a timer.

## Open points

1. Approach: decided, A (see above).
2. Solo session on. Read from the code 2026-11-27: solo does not turn search off, it
   restricts history reads to the current session (`tools/history.py`, `_solo_violation`);
   `remember` has no solo gate (no solo reference in `tools/builtin.py`). Both tools work as
   designed, so solo is the user's choice, like semantic disabled in config. Decided (owner,
   2026-11-27): solo does not change the status; it stays `ok`.
3. Lexical index. `JournalSearchIndex.rebuild()` is synchronous and returns nothing; the
   startup rebuild runs in `_rebuild_startup_projections` (`journal/lifecycle.py`). There is
   no asynchronous "rebuilding" window to observe. A startup rebuild that raises stops the
   application before the chip exists, so the lexical side has no chip state and no event.
   A failure in a per-event projection task is logged and not surfaced; the chip does not
   cover it.
4. Memory file read failures. `MemoryFileRepository.read` turns a missing file into an empty
   string and lets any other `OSError` propagate untyped; there is no typed read error. So
   `error` means an `OSError` caught at the call sites that touch the files (the `remember`
   tool and the memory panel read and write handlers). "Full" is known only when a write is
   refused (`MemoryFileOverCapError`) or a size is checked against the cap; it clears when a
   later write or a panel save brings the file under the cap, so the panel save path must
   publish too, not only the `remember` tool.

## Acceptance criteria

- [x] Open points 1 to 4 are answered above.
- [x] Tests (pure logic, no Ollama): each row of the status table is produced by the
      matching event sequence; recovery returns to `ok` (a full file after a write, semantic
      back after a failure); semantic disabled in config stays `ok`; solo does not change the
      status (no code path, nothing to test); `run()` publishes the initial health after the
      console is wired so the chip is not left grey at startup.
- [x] Detail keys exist in EN and RU for every status (`tests/test_ui_text.py`).
- [x] `ui/contract.py` docstring and `PROJECT.md` describe the new meaning of the Memory
      chip in the same commit.
- [x] Human-run check (live Ollama, so not run by the agent; handoff: `tasks/done/memory-chip-health-handoff.md`): with the embedding model
      unavailable the chip turns `degraded`, and returns to `ok` after a restart with it available.
      The handoff names every config key and command literally with a source reference, per
      the Testing protocol.
- [x] `python -m pytest` (7213 passed, 2 skipped), `ruff check`, `ruff format --check` are green.
