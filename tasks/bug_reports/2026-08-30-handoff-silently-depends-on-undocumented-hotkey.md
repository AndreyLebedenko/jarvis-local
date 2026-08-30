# 2026-08-30: Human handoff silently depends on an undocumented config default

Detected on commit `f472f5a` (branch `fix/handoff-literal-bindings`,
investigation opened 2026-08-30).

## Symptoms

The owner started the mode-3 human verification handoff in
`tasks/done/task-v1.9.0-3-mode3-second-pass-and-tts-suppression.md`
("Human verification handoff (prepared, not yet run)") and could not execute
step 2: it says "press the response-mode cycle hotkey twice" without naming
the binding. The binding (`ctrl+alt+o`,
`src/jarvis/core/config.py:140`) is stated nowhere the owner would look -
not in `config.example.toml` (the `[hotkeys]` section ends at
`interrupt = "ctrl+alt+i"`, line 141), not in either README ("Default
hotkeys" list omits it), not in any task or story card. The owner rejected
the handoff.

The same gap exists in `tasks/done/task-v1.9.0-2-hotkey-and-ui-dropdown.md`,
whose handoff requirement (lines 93-97) and acceptance criterion (line 107)
promise "exact steps" for a hotkey the card itself never names.

## Why this is a process defect, not a docs omission

Documentation of the hotkey was always scheduled for task-v1.9.0-5 (its
requirements explicitly say the README must state the real binding). The
defect is that a **prepared, handoff-gated card was closed while its handoff
was unexecutable from the repository alone**:

1. A handoff is the human's *only* execution surface. A step that says
   "press the cycle hotkey" without the literal binding is only executable
   by someone reading `config.py` - which the handoff's own contract
   ("exact steps", the project's hotkey-honesty precedent, e.g. README:241
   naming `Ctrl+Alt+I`) forbids implicitly.
2. All existing gates (Codex stop-time review, code review passes, ruff,
   pytest) verify code and tests. None verifies that a handoff section can
   actually be executed from its text. The gap crossed silently.
3. Worse, the mode is *persistent* (that is the v1.9.0 design), so "press
   twice from the default" is also state-dependent, not just unnamed - a
   second layer of the same defect (steps relying on implicit state).

The severity is the silent crossing: no layer flagged "this handoff
depends on facts scheduled for later documentation". The debt moved
across a boundary without a marker.

## Temporary decision

Three fixes, all in this investigation:

1. Repair the two v1.9.0 handoffs (task 2 and task 3) so every hotkey is
   named literally with its config source, and the mode-switch step is
   state-independent (read the current mode from the drop-down, cycle until
   the target is shown) instead of assuming startup default `text`.
2. Add the general rule to `AGENTS.md`/`CLAUDE.md`: every handoff is
   self-sufficient - all hotkeys, config keys, and defaults are named
   literally with a source reference; if a handoff depends on a documented
   debt, the debt must be flagged in the handoff itself.
3. Record a task-v1.9.0-5 checklist item so the docs task audits the
   remaining handoffs when it lands the hotkey table.

Audit of the remaining prepared-but-unrun handoffs (2026-08-30): only the
two v1.9.0 cards had un-run handoffs with hotkey references; every other
handoff naming a hotkey (`Ctrl+Alt+I` replay/interrupt paths,
`interrupt-hotkey-handoff.md`) was already owner-run (2026-07-27,
2026-08-28) and names bindings README already documents. No other card
needs this correction.

Rejection of the mode-3 handoff stands until the owner re-admits it; no
re-run is claimed by these fixes.

## Why chosen over nearby alternatives

- Fixing only README now (pulling task-5 work forward) would mask the
  process defect; the process fix is the point of this card.
- Hard-failing every commit over handoff prose is disproportionate; the
  chosen enforcement is a lightweight staged-file check, offered to the
  owner as a git hook (see `tools/check_handoff_self_sufficiency.py`),
  so the guarantee stops depending on agent discipline.

## Future considerations

- The Status Console does not currently surface the active hotkey bindings
  anywhere; documenting them in one place does not make them discoverable
  in-product. A control-panel hint (or a bindings table in the UI) is a
  separate product idea, deliberately out of scope here.
- Config defaults may drift (rebinding). The self-sufficiency rule's
  "with a source reference" clause is the cheap protection: a reader can
  check the current default against the cited file, and a rebinding task
  edits that one file.