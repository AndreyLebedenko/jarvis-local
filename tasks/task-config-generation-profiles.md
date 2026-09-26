# Task: Generation profiles - restructure model-call config around request kinds

**Status:** Approved (owner, 2026-09-26). Not started.
**Origin:** owner planning dialog, 2026-09-26. Design agreed in that dialog;
this card records it.
**Depends on:** nothing.
**Blocks:** the `num_predict` / `done_reason` card (not yet written), which
sets per-profile generation caps on top of the structure built here; the
single-pass `<tts>` spike (`spike-single-pass-tts-block.md`), whose harness
reads production prompts from the new locations.
**Kind:** behavior-preserving restructure. No default value changes, no new
runtime capability, no new cap. If a change alters what is sent to Ollama for
an unchanged effective configuration, it does not belong here.

## Summary

Every key that shapes one model request currently lives wherever the feature
that introduced it happened to put it. Move them into one tree organized by
*request kind*: `[backend]` keeps only connection and model-load settings,
`[generation]` holds per-request option defaults, and one
`[generation.<profile>]` subsection per request kind holds everything specific
to that kind - its prompt, its reasoning level where it has a choice, and any
option override. Migration is a hard break: every moved key raises a
`ConfigError` that names its new location.

## Why this exists

The trigger was the missing generation cap
(`tasks/bug_reports/2026-09-12-backend-has-no-num-predict-cap-so-only-num-ctx-stops-generation.md`).
A single `[backend].num_predict` is wrong because the right bound depends on
the request kind, and adding per-kind caps into today's layout would scatter
one more family of keys. Today's layout, for the requests Jarvis makes:

| Request kind | Prompt text lives in | Reasoning level from | Sampling from |
|---|---|---|---|
| dialog turn, per reasoning level | `[prompts].reasoning_low/medium/high` (appended to `system`) | runtime toggle | `[backend]` |
| mode-3 spoken derivative (pass 2) | `[prompts].response_text_voice` | hardcoded OFF (`app.py`) | `[backend]` |
| voice-intent probe | `[prompts].voice_intent_directive` | current toggle | `[backend]` |
| warm-up | `[prompts].warmup` | OFF | `[backend]` |
| journal annotation | `[history.annotation].instruction` | `[history.annotation].reasoning` | `[backend]` |
| journal transcription | `[history.transcription].instruction` | OFF | `[backend]` |

Two concrete costs of the scatter:

- Sampling is global. There is no way to give annotation a higher temperature
  than a dialog turn, even though they are different jobs.
- `[backend]` mixes two things that behave differently in Ollama: model-load
  parameters (`num_ctx`, `kv_cache_type`, `flash_attention`) that force a model
  reload when a request carries a different value, and per-request options
  (`temperature`, `top_p`, ...) that are free to vary per call. Nothing stops a
  future per-request override from accidentally varying a load parameter.

## Target structure

```toml
[backend]                 # connection + model load; never varies per request
model = "gemma4:12b-it-q8_0"
endpoint = "http://localhost:11434"
num_ctx = 65536
flash_attention = true
kv_cache_type = "q8_0"
read_timeout_seconds = 120.0

[generation]              # per-request option defaults for every model call
temperature = 0.618
top_p = 0.9
top_k = 50
min_p = 0.05
repeat_penalty = 1.025
# repeat_last_n, seed, num_predict, stop, draft_num_predict: optional

[generation.dialog.off]
[generation.dialog.low]
prompt = "@prompts/think-level-1.md"
[generation.dialog.medium]
prompt = "@prompts/think-level-2.md"
[generation.dialog.high]
prompt = "@prompts/think-level-3.md"

[generation.spoken_derivative]   # mode-3 pass 2
prompt = "..."

[generation.voice_intent]        # present prompt = feature on (as today)
prompt = "..."

[generation.warmup]
prompt = "Hello"

[generation.annotation]
reasoning = "off"
prompt = "..."
temperature = 0.9                # example of a per-profile override

[generation.transcription]
prompt = "..."

[prompts]                 # dialog text shared across dialog profiles
system = """..."""
voice_turn_instruction = "..."

[response]
mode = "text"
voice_contract = "..."    # mode-2 contract; a modifier of the dialog turn,
                          # not a request kind of its own
```

### Rules

1. **`[backend]` is connection and model load only:** `model`, `endpoint`,
   `num_ctx`, `flash_attention`, `kv_cache_type`, `read_timeout_seconds`.
   These keep being sent exactly as today; they are simply not overridable.
2. **`[generation]` holds per-request option defaults:** `temperature`,
   `top_p`, `top_k`, `min_p`, `repeat_penalty`, `repeat_last_n`, `seed`,
   `num_predict`, `stop`, `draft_num_predict`. Each stays optional with
   today's "omit when unset" meaning.
3. **A profile may set any key from rule 2, plus `prompt`, plus `reasoning`**
   (non-dialog profiles only; a dialog profile's level is its name).
   A rule-1 key inside a profile is a `ConfigError` naming the key and saying
   it is a model-load setting that lives in `[backend]`.
4. **Resolution is one level and identical for every profile:** profile key,
   else `[generation]` key, else omitted from the request (Ollama default).
   Profiles never reference each other and there is no inheritance between
   them.
5. **The profile set is fixed by code,** not user-definable: `dialog.off`,
   `dialog.low`, `dialog.medium`, `dialog.high`, `spoken_derivative`,
   `voice_intent`, `warmup`, `annotation`, `transcription`. An unknown profile
   name is a `ConfigError`, consistent with the loader's existing
   unknown-key policy. An absent profile section means "all defaults".
6. **`prompt` keeps today's value grammar:** inline text or `@path` resolved
   under `.jarvis` with the existing `..` guard (`_resolve_prompt_field`). An
   empty or whitespace-only `prompt` is a `ConfigError`, as it is today for the
   `[prompts]` fields. Absent `prompt` means the profile's built-in default,
   or none where there is none today. Placement of `prompt` is defined by the
   consumer and does not change: dialog profiles append it to `system`;
   `spoken_derivative` uses it as the system message; `voice_intent`,
   `annotation`, `transcription` use it where their instruction goes today.
7. **Service policy stays with the service.** `[history.annotation]` keeps
   `enabled`, `max_concurrency`, `max_source_events`, `max_source_chars`,
   `max_annotation_chars`; `[history.transcription]` keeps `enabled`,
   `max_concurrency`. Only *how the model is called* moves.

### Hard migration

Each moved key raises a `ConfigError` of the form
`[prompts].reasoning_low moved to [generation.dialog.low].prompt`, from one
data table (old location -> new location), not per-key code. Moved keys:

| Old | New |
|---|---|
| `[backend].temperature`, `top_p`, `top_k`, `min_p`, `repeat_penalty`, `repeat_last_n`, `seed`, `num_predict`, `stop`, `draft_num_predict` | `[generation].<same>` |
| `[prompts].reasoning_low` / `reasoning_medium` / `reasoning_high` | `[generation.dialog.low|medium|high].prompt` |
| `[prompts].response_text_voice` | `[generation.spoken_derivative].prompt` |
| `[prompts].voice_intent_directive` | `[generation.voice_intent].prompt` |
| `[prompts].warmup` | `[generation.warmup].prompt` |
| `[prompts].response_voice` | `[response].voice_contract` |
| `[history.annotation].reasoning`, `instruction` | `[generation.annotation].reasoning`, `.prompt` |
| `[history.transcription].instruction` | `[generation.transcription].prompt` |

Two semantic notes the migration must preserve or state:

- `voice_intent`: today an absent or blank `voice_intent_directive` means the
  feature is off. After the move, absent `[generation.voice_intent].prompt`
  means off; blank is a `ConfigError` per rule 6 (blank already parsed to "off"
  only by accident of the old grammar - `intent_directive_from_settings`).
- `annotation` / `transcription`: today an empty `instruction` means "use the
  service default". After the move that is expressed by omitting `prompt`;
  an empty string is a `ConfigError` per rule 6.

`config.ui.toml` is unaffected: `write_ui_config` writes only
`[backend].model`, `[microphone]`, `[ui]`, `[vad]`, `[tts]`, `[mcp].enabled`
and `[response].mode`, none of which move. Verify by test that a
`config.ui.toml` in today's shape still loads.

### Explicitly not moved in this card

`[history].reasoning_generation_reserve_tokens` stays where it is, unchanged.
It is the context budget's generation reserve and is recorded in `PROJECT.md`
as the verified default that sums with `prompt_capacity_tokens` to
`num_ctx = 65536`. Folding it into the dialog profiles' `num_predict` is
exactly the behavior change the follow-up `num_predict` card makes (it
introduces an actual cap and has to re-state that `PROJECT.md` fact); doing it
here would make this card not behavior-preserving.

## Code boundary

- `src/jarvis/core/config.py`: `BackendSettings` loses the rule-2 keys; new
  `GenerationOptions` (rule-2 keys, all optional), `GenerationProfile`
  (options + `prompt` + `reasoning`), `GenerationSettings` (defaults + fixed
  profile map) with one pure resolution method returning the effective options
  for a profile. Legacy-key table and its errors. Config stays free of project
  imports (`test_config_has_no_project_import_dependencies`); reasoning stays a
  validated string here, as `[history.annotation].reasoning` is today.
- `src/jarvis/dialog/backend.py`: `build_payload` / `iter_chat` / `chat` take
  the resolved per-request options from the caller and merge them with the
  rule-1 load options. Make the parameter required, so no call site can send a
  request without having chosen a profile; a test enumerates call sites
  through the public API rather than trusting convention.
- Call sites choose their profile: the dialog turn and its tool loop
  (`app.py`, `dialog/tool_presentation.py`) by current reasoning level; the
  spoken derivative pass (`app.py` `run_derivative_pass`, today
  `ReasoningLevel.OFF` + `response_text_voice`); the voice-intent probe
  (`dialog/voice_intent.py`); warm-up (`app.py` `warm_up`); annotation
  (`journal/annotation_generator.py` via `_build_annotation_generation_service`);
  transcription (`journal/transcription.py` via its builder).
- `journal/semantic.py` (`/api/embed`) reads only `endpoint` and the timeout
  from `[backend]`; it is not a generation request and gets no profile.
- Manual scripts that build `BackendSettings` with sampling keys, and their
  CI-run tests under `manual/tests/`: `manual_check_audio_request_shape.py`,
  `manual_check_context_token_budget.py`,
  `manual_check_speech_markup_contract.py`, `manual_check_tool_calling.py`.
  Migrate them to the new types; do not change what they send.
- `config.example.toml` rewritten to the target structure with the same
  effective values as today.
- The owner's `config.toml` is gitignored personal config. The agent does not
  edit it; the handoff gives the exact migrated sections to paste, derived
  from the current file's keys.

## Documentation

Per `CLAUDE.md` "Project context" item 2, `PROJECT.md` changes in the same
commit as the structure:

- New section "Architecture: generation profiles" with the rules above.
- Rewrite the `BackendSettings` paragraph in "Architecture v1.0" (the
  "generation request knobs" sentence).
- Update key names in "Architecture v1.2.12 (external dialog prompts)",
  "Architecture v1.7.3 (reasoning-mode prompt sections)", "Architecture v1.9.0
  (response modes)", and the journal annotation/transcription config text.
- `README.md` and `README.ru.md` mentions of `reasoning_low`,
  `voice_intent_directive`, and `[history.annotation]` keys.

Do not rewrite historical facts: statements of what was measured under the
old key names stay as recorded, with the new name added where a reader would
otherwise look for a key that no longer exists.

## Acceptance criteria

- [ ] For the migrated equivalent of today's `config.example.toml`, the
      payload built for each request kind (dialog at each of the four levels,
      spoken derivative, voice intent, warm-up, annotation, transcription) is
      identical to the payload built on `main` before this card: same
      `options`, same `think`, same messages. Proven by tests that pin the
      payload per request kind.
- [ ] Resolution order is proven per rule 4: a profile key overrides
      `[generation]`; an unset key falls back; a key unset in both is absent
      from `options`. Includes the owner's motivating case: a
      `[generation.annotation].temperature` override reaches annotation
      payloads and no other request kind.
- [ ] Each rule-1 key inside any profile is a `ConfigError` naming the key.
- [ ] Each row of the migration table is a `ConfigError` naming the new
      location. One parametrized test over the table.
- [ ] Unknown profile name and empty `prompt` are `ConfigError`s.
- [ ] A `config.ui.toml` in today's shape loads unchanged.
- [ ] `python -m pytest`, `python -m ruff check .`, and
      `python -m ruff format --check .` are green.
- [ ] Human-run handoff prepared (hardware: live Ollama), self-sufficient per
      `CLAUDE.md` "Testing protocol" item 4. Content: paste the migrated
      sections into `config.toml`; launch `python -m jarvis --status-console
      --debug`; run one dialog turn at reasoning OFF and one at a non-OFF
      level, one mode-3 turn, one annotation generate, one transcription
      generate; confirm in `logs/jarvis-debug.jsonl` (directory from
      `[logging].directory`, file name `TRANSCRIPT_FILE_NAME` in
      `src/jarvis/core/debug_transcript.py`) that each exchange's `options`
      match the pre-change values. Every hotkey used is named literally with
      its source reference.

## Out of scope

- Choosing any `num_predict` value, folding the context reserve into
  profiles, surfacing `done_reason`: the follow-up card.
- UI for editing profiles; per-session or per-conversation overrides.
- Any change to default values, prompt text, or which reasoning level a
  request kind uses.
- The single-pass `<tts>` contract: it is a spike, and if it lands later it
  gets its own profile or `[response]` key through this structure.
