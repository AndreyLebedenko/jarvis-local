# Task: Externalize the system prompt and warm-up prompt

**Status:** Completed.
**Release:** v1.2.12

## Summary

Move the two dialog prompts hardcoded in main.py - the Russian system
prompt (SYSTEM_PROMPT) and the warm-up request text ("Привет") - into the
external TOML configuration, so a user can switch the assistant's dialog
language (e.g. to English) without editing source. Follows up
story-v1.2.11-ui-english-localization.md, which localized UI chrome only.

## Decision

A new `[prompts]` section in the existing layered config (config.toml /
config.ui.toml), not a separate config.llm.toml file: the existing loader
already provides type checking, unknown-key detection, per-key layering,
and defaults-mirror-example semantics; a second file would need a second
loader and a second documented precedence story for two strings. TOML
multiline basic strings hold the long system prompt.

Fields:

- `[prompts].system` - the system message sent as the first chat message
  of every turn. Default: the current Russian SYSTEM_PROMPT verbatim.
- `[prompts].warmup` - the throwaway user message warm_up() sends before
  input is accepted. Default: "Привет".

## Current Boundary

In scope:

- `PromptSettings` dataclass in config.py with the two fields above;
  defaults are the current literals moved out of main.py. Both must be
  non-empty strings (an empty system prompt or warmup request is almost
  certainly a config mistake, not a choice - fail loudly).
- main.py consumes `settings.prompts.system` (Orchestrator) and
  `settings.prompts.warmup` (warm_up()); no prompt literals remain there.
- `config.example.toml` documents the section with the default Russian
  prompt and a commented English variant hint.
- Unit tests: defaults preserved byte-for-byte, override from config,
  empty/wrong-type values rejected, layering applies.
- PROJECT.md note recording the decision.

Out of scope:

- VOICE_PLACEHOLDER_TEXT ("[голосовое сообщение]") - conversation-history
  data with its own tests, not a prompt sent for its own sake; renaming or
  localizing it changes stored history semantics.
- The wake word / hotword ("Джарвис" appears only inside the prompt text
  itself; there is no separate wake-word engine setting to move).
- TTS routing, speech markup, `[ui].language` interaction - the prompts
  section is language-agnostic text, no coupling to UI language.
- Any prompt editing UI in the Status Console.

## Acceptance Criteria

- [ ] With no config file, behavior is byte-identical to v1.2.11: the same
      Russian system prompt and "Привет" warm-up are sent.
- [ ] `[prompts].system` / `[prompts].warmup` in config.toml replace the
      defaults; config.ui.toml layering applies per-key like every other
      section.
- [ ] Empty or non-string values fail config parsing with an error naming
      the field.
- [ ] No dialog-prompt literal remains in main.py.
- [ ] `python -m pytest` passes.

## Verification

- Automated: `python -m pytest`.
- Human: add `[prompts]` with an English system prompt to config.toml,
  restart, confirm Jarvis answers in English; remove the section, restart,
  confirm Russian behavior returns.

## Stop Conditions

- Stop if moving SYSTEM_PROMPT breaks the thinking-mode or speech-markup
  contracts that reference prompt wording in tests beyond simple relocation.
