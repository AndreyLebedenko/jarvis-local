# Task: UI language setting and Python string catalog

**Story:** `tasks/story-v1.2.11-ui-english-localization.md`
**Status:** Completed.
**Release:** v1.2.11

## Summary

Introduce a `ui.language` config setting (`en` default, `ru` supported) and
move all UI-visible strings produced on the Python side into a per-language
string catalog. All runtime state titles/details, `ui_message` texts, module
labels, and microphone details resolve through the catalog for the configured
language before being pushed over the WS transport.

## Current Boundary

In scope:

- Config: `ui.language` field with validation (`en`/`ru` only), default `en`,
  integrated with the existing config layering contract and settings save
  flow.
- A single catalog module holding English and Russian variants of every
  UI-visible string currently hardcoded in `status_console.py`, `main.py`,
  and `ui_transport.py` (state map, `_MODULE_LABELS_RU` and its messages,
  microphone details, warmup/reset/shutdown/settings `ui_message` strings).
- English translations for all of those strings; existing Russian wording is
  preserved verbatim as the `ru` variant.
- The transport payload additionally carries the active UI language so the
  web layer (task 2) can pick its static-text dictionary.
- Unit tests: catalog completeness (every key exists in both languages),
  config validation, and that the runtime emits English by default and
  Russian under `ui.language: ru`.

Out of scope:

- Any change to static HTML/JS text (task 2).
- System prompt, `VOICE_PLACEHOLDER_TEXT` semantics as dialog data, TTS.
- An in-UI language switcher.

## Acceptance Criteria

- [ ] `ui.language` defaults to `en`; `ru` selects Russian; any other value
      fails config parsing with a clear error naming the field.
- [ ] No UI-visible Russian literal remains inline in `status_console.py`,
      `main.py`, or `ui_transport.py`; all resolve through the catalog.
- [ ] The `ru` catalog reproduces current Russian wording exactly (including
      `не используется` for the user-muted microphone).
- [ ] Transport messages include the active UI language.
- [ ] `python -m pytest` passes.

## Stop Conditions

- Stop if some UI string turns out to be simultaneously UI text and spoken
  TTS text: the split between UI chrome and dialog data must be decided by
  the human.
- Stop if config layering makes the default-`en` change alter saved user
  configs in a surprising way.
