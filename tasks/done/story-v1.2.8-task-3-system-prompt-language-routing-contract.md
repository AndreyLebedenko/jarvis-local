# Task: System prompt language-routing contract

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Completed.
**Release:** v1.2.8
**Depends on:** `tasks/done/story-v1.2.8-task-2-tts-buffering-integration.md`

## Summary

Update Jarvis's system prompt and runtime contract so the local LLM emits plain
speakable text while Jarvis handles Russian/English routing deterministically.

## Outcome

The original task direction asked the model to emit a flat SSML-like
`<speak>` / `<lang xml:lang="ru|en">` contract. Manual task-4 checks showed
that `gemma4:12b-it-qat` does not keep that flat XML-like structure stable:
it naturally nests English spans inside Russian prose and sometimes leaves
text outside complete language spans.

The successful contract is now:

- the model emits ordinary speakable text;
- the system prompt preserves short-answer, Russian-by-default,
  low-latency behavior;
- the system prompt says not to use Markdown unless explicitly requested;
- the system prompt says language markup is not needed;
- English terms, API names, identifiers, short English phrases, and English
  quotes may appear as ordinary text where useful;
- `language_segments.py` and `tts.py` route `ru`/`en` by charset before
  sentence buffering.

## Verification

- `python -m pytest` passed after implementation.
- Human manual check passed after the charset-segmentation pivot; see
  `tasks/done/story-v1.2.8-task-4-manual-language-routing-handoff.md`.

## Notes

The failed XML-markup path is preserved as a bug report:
`tasks/bug_reports/gemma4-speech-markup-contract-instability.md`.
