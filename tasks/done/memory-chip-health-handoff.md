# Handoff: Memory chip health (human-run)

Task: `tasks/done/task-memory-chip-health.md`. Needs a live Ollama and the Status Console
window, so the agent does not run it. Branch: `feature/memory-chip-health`.

## What this checks

The Memory chip in the MODULES panel turns amber ("degraded") when semantic history
search cannot work, and returns to green after it can. Everything else in the card
(file full, file unreadable, solo, ordering of statuses) is covered by automated tests
only; this handoff does not exercise the memory panel, so those paths are not verified
live.

## Preconditions

1. Ollama is running and the embedding model is installed:
   `ollama list` shows `blaifa/multilingual-e5-large-instruct:latest`
   (the default of `[history.semantic].model`, `config.example.toml` line 158).
2. The journal holds at least one earlier conversation turn. The journal folder is
   `[journal].root`, default `journal` (`config.example.toml` line 443). If it is empty,
   start Jarvis once, say or type any sentence, wait for the answer, close Jarvis.
   Why: with nothing to embed, a wrong model name fails nothing and the chip stays green,
   which would look like a defect and is not one.
3. Jarvis is closed.

## Steps

1. Open `config.toml` in the repository root. Make sure it contains a table
   `[history.semantic]` whose `model` is exactly:

   ```toml
   [history.semantic]
   model = "no-such-embedding-model:latest"
   ```

   If the table already exists, change only its `model` line. If it does not exist, add
   the two lines at the end of the file. (The current `config.toml` has no such table.)
2. Start Jarvis with the Status Console: `Jarvis.cmd` in the repository root
   (`README.md`, Usage: it runs `python -m jarvis --status-console`).
3. Look at the MODULES panel. Expected: the Memory chip dot is amber and the line under
   the name reads `семантический поиск недоступен` (when `[ui].language = "ru"`,
   `config.toml` line 81) or `semantic search unavailable` (when `"en"`).
4. Close Jarvis.
5. In `config.toml` set `model = "blaifa/multilingual-e5-large-instruct:latest"`
   (or remove the `[history.semantic]` table). Start `Jarvis.cmd` again.
6. Expected: the Memory chip dot is green and the line reads `готова` (ru) or `ready`
   (en).

## Report back

- A screenshot of the MODULES panel after step 3 and after step 6.
- If step 3 shows grey or green instead of amber, the last 40 lines of the newest file in
  the `logs` folder (`[logging].directory`, default `logs`).

## Known limit, not a defect

After a semantic failure during a running session the chip stays amber until Jarvis is
restarted, because the semantic index does not retry on its own (`PROJECT.md`,
"Architecture: Memory chip health"). Returning to green is therefore checked by the
restart in steps 5 and 6, not by waiting.
