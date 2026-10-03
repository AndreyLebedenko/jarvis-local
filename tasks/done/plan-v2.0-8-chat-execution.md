# Plan: task v2.0-8 executed through the Quoroom chat

**Status:** Completed. (2026-10-03)
**Card:** `tasks/task-v2.0-8-docs-and-release-verification.md`.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Branch:** `feat/v2.0-8-docs-and-release-verification` from `main`
(`a7c72df`).

## Roles

Same as `tasks/done/plan-v2.0-7-chat-execution.md`: `claude-code`
orchestrates, reviews, and commits after the owner's review; `glm` writes,
one slice at a time, never commits; read-only subagents review. Slice
reports by `--file`, addressed `@claude-code`. The owner executes the
human-run handoff; nobody else runs its hardware or live steps (CLAUDE.md
Testing protocol item 1).

## Slices

- **S1. MCP session title placeholder (card item 0).** The only production
  code in this card. TDD, gates.
- **S2. Docs (card items 1-3).**
  - `PROJECT.md`: "Architecture v2.0 (MCP voice guide) - in progress"
    already holds most facts, written by tasks 2-7. Do not rewrite it:
    drop "in progress", check every fact the card lists is present and
    current against the code (fill gaps, fix drift, remove duplicates), and
    amend the runtime locality contract and "Current roadmap" as the card
    says. Facts marked "do not re-litigate" elsewhere stay untouched.
  - Roadmap and both READMEs as the card says. Every value in the README
    client command (port, token-file location, header) is read from the
    code/config defaults and cited, not copied from the card.
- **S3. Handoff (card items 4-5).** `tasks/v2.0-release-verification-handoff.md`
  per CLAUDE.md Testing protocol item 4. The card's hotkey literals may
  have drifted: verify each against `HotkeySettings` in
  `src/jarvis/core/config.py` and cite the source. State how the Status
  Console is opened in `--mcp-mode` (the exact command), since checks 2, 7,
  and 9 need it. Gate: `python tools/check_handoff_self_sufficiency.py
  tasks/v2.0-release-verification-handoff.md`, plus the three automated
  gates recorded at the top of the handoff.

After S3: an independent subagent executes the handoff "on paper" against
the repository (every key, command, path, and default resolvable from the
text alone). Then the owner runs it.

## Boundaries

- No production code beyond S1. If a doc or handoff step reveals a code
  gap, report it; do not fix it here.
- `tasks/done/*` cards are history: do not edit them.
- `README.ru.md` follows its own existing punctuation style.
