# v1.9.2 Rethink probe - raw study

Archived evidence for closing `tasks/story-v1.9.2-local-generation-critique-integration.md`
as unrealistic (2026-09-12). The story card carries the conclusion and the
summary table; this directory holds what produced them.

Not a maintained manual check. The scripts hardcode `D:/AI/Jarvis` and were
run once, by hand, against a live local Ollama. They are kept so the numbers
can be re-derived or disputed, not so they can be re-run as a gate.

## Contents

- `prompts.py` - the 14 authored cases. Each carries `truth` (checkable ground
  truth), and the analytical ten also carry `prediction`: what I expected a
  single pass to return, written before any output existed. Seven of ten
  predictions were wrong, all pessimistic.
- `run_probe.py` - arm 1: draft at reasoning level 2, then critique at level 2.
  Holds the critique instruction (`CRITIQUE_PROMPT`, VERDICT/ANSWER shape).
- `run_probe2.py` - arms 2-4: `draft:<level>` and `crit:<level>:<draft_tag>`.
  Honours `PROBE_NUM_PREDICT` as a runaway cap.
- `grade.py` - mechanical checks for the predeclared formal constraints
  (sentence counts, banned words, line counts, Markdown) plus draft-vs-final
  comparison. Aesthetic judgement was not automated.
- `out/*.json` - 70 calls: `text`, `thinking_chars`, `wall_seconds`,
  `eval_count`, `prompt_eval_count`, `think_param`, `model`.

Artifact naming: `<case>-<stage>.json`, where stage is `pass1`, `critique`
(arm 1), `draft-off`, `draft-medium`, `crit-off-over-draft-off`,
`crit-medium-over-draft-off`, or `crit-medium-over-draft-medium`.

## Setup actually used

`gemma4:12b-it-q8_0`; `[backend]` sampling options unchanged (temperature
0.618, top_p 0.9, top_k 50, min_p 0.05, repeat_penalty 1.025, num_ctx 65536);
seed 19200 on every call; system prompt composed the production way -
`[prompts].system` plus `memory/self.md` and `memory/memory.md` through
`MemoryFileLoader.compose_system_prompt`, then the reasoning-level section
through `app.py`'s `_compose_effective_system_prompt`. At level 2 that is
7226 characters and roughly 1700 prompt tokens; at OFF, 2327 characters.

Response mode is text throughout, so `_compose_response_mode_contract`
selects nothing and the composed prompt is byte-identical to a live text turn
at the same reasoning level.

## Reproduction note

The four empty-output results in `out/` are real, not harness failures: at
reasoning level 2 the model spent its whole generation budget inside the
thinking block on creative prompts with a formal constraint and emitted zero
content. `c02-draft-medium` reproduced this twice - once against the 65536
context ceiling (1330 s, 63 843 tokens, prompt 1693 + eval 63843 = exactly
`num_ctx`) and once against `PROBE_NUM_PREDICT=4000` (79 s). The committed
artifact is the capped run.
