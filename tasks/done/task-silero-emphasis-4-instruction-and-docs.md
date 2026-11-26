# Task 4: Caller instruction and docs

**Status:** Completed.
**Story:** `tasks/story-silero-v5-emphasis-markers.md`.
**Predecessor:** `tasks/done/task-silero-emphasis-3-provenance.md`.

## Summary

The MCP caller learns the marker rule from the `speak` tool description, and
the project documents the feature, the spike evidence, and the decisions.

## Boundary

Files changed:
- `src/jarvis/mcp_mode/server.py`: `speak_tool_description` teaches the rule
  inside the `spoken_text` clause: single asterisks around one word, in a
  question the meaningful word and the last word (two pairs at most), in a
  statement one word, asterisks elsewhere are never spoken, a voice without the
  support ignores them. The text is the same whatever the TTS config says: with
  the feature off the markers are stripped, so the rule is harmless.
- `tests/test_mcp_mode_server.py`: one test that the description carries the
  rule and a Russian example.
- `config.example.toml`: the `emphasis` comment says only the MCP caller's
  `spoken_text` carries markers.
- `PROJECT.md`: a verified-experiment section (one listener, with what was not
  tested), a `speech_emphasis.py` module entry (policy, engine boundary,
  provenance, known limits), and the `speak` tool description sentence.
- `README.md` and `README.ru.md`: one paragraph each under the MCP section.

Must NOT touch: engines, `voice_guide.py`, config code, the proxy.

## Acceptance criteria

- `python -m pytest`, `ruff check .`, and `ruff format --check .` pass.
- The three decisions of the story (opt-in default off, caller `spoken_text`
  only, xenia and eugene as the documented voices) appear in the docs.
- No behavior changes other than the tool description text.

## Review follow-ups (independent reviewer, 2026-11-25)

- The tool description now reads "In a question, mark ...", tells the caller to
  keep a marked sentence in Russian words only, and says Jarvis removes
  asterisks when the voice lacks the support (no untested claim about the voice).
- Documented limit: in dynamic mode a Latin run splits the sentence into
  separately normalized and voiced parts, so the two-marker question pattern
  holds for an all-Cyrillic sentence.
- `config.example.toml` says to turn `emphasis` on only with a `v5_*_ru` model.
