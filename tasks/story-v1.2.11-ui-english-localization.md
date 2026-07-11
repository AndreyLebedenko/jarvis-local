# Story: v1.2.11 UI English localization

**Status:** Completed.
**Release:** v1.2.11

## User-facing goal

The Status Console and Touchstrip can be displayed in English, and English is
the default UI language. Russian remains available via configuration. The
assistant's spoken/dialog language, the Russian system prompt, and TTS
behavior are unchanged: this story localizes the UI chrome only.

## Background

Today all UI-visible text is hardcoded Russian in two layers:

- Python runtime layer: runtime state titles/details, `ui_message` strings,
  module labels, and microphone details in `status_console.py`, `main.py`,
  and `ui_transport.py`. These strings reach the web UI through the WS
  transport.
- Web static layer: literal Russian text in `status_console_ui/index.html`,
  `touchstrip.html`, `app.js`, `touchstrip.js`, and the demo pages.

## Boundaries

In scope:

- A `ui.language` config setting with values `en` and `ru`, default `en`,
  following the existing config layering contract.
- An English and Russian string catalog for all UI-visible runtime strings
  produced on the Python side.
- Localization of static text in the Status Console and Touchstrip pages,
  driven by the same language setting (demo pages follow the default
  language).
- Documentation of the new setting.

Out of scope:

- The dialog language: the Russian system prompt, TTS output, speech markup,
  and bilingual TTS routing are runtime data, not UI text (see agent
  instructions), and must not change.
- Wake word behavior and voice command grammar.
- Server-side developer logs and CLI diagnostics (`day0_checks.py` output may
  stay as-is).
- Any new UI controls (no in-UI language switcher in this story; the setting
  is config-only).

## Acceptance criteria

- With default config, the Status Console and Touchstrip render fully in
  English: no Russian text remains in states, module health, action buttons,
  confirmations, settings dialog, or event messages produced by the runtime.
- With `ui.language: ru`, the UI renders in Russian with the current wording
  preserved.
- An unknown `ui.language` value fails config validation with a clear error.
- Spoken responses, the system prompt, and TTS routing are byte-identical to
  v1.2.10 behavior.
- `python -m pytest` passes; the manual handoff for visual verification is
  prepared.

## Task sequence

1. `story-v1.2.11-task-1-ui-language-setting-and-catalog.md` — config
   setting plus Python-side string catalog and wiring.
2. `story-v1.2.11-task-2-web-ui-static-text-localization.md` — Status
   Console and Touchstrip static text localization.
3. `story-v1.2.11-task-3-docs-and-manual-handoff.md` — documentation and
   human verification handoff.
