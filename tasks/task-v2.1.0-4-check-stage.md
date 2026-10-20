# Task v2.1.0-4: transcript check stage

Status: Open.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 4 (Size: M), and "Revisions of
2026-10-19", items 1, 2, 4. Facts: spikes v2.1.0-7, -8, -9, -10 (`tasks/done/`) and
`PROJECT.md` "v2.1.0 speech recognition and confidence spikes". Follows tasks 1-3
(`src/jarvis/personal_proxy/`: settings, `Transcription` with word probabilities,
the guarded speech-to-text stage).

## Summary

Promote the spike code to `src/`: Gemma checks the Whisper transcript against the
recording (one sample), a judge call lists the fragments it doubts, and the stage
returns the checked transcript plus the doubt list. Every failure falls back to the
Whisper text with a doubt. The stage never sends anything and never retries.

## Owner decision (2026-10-20, planning question of this task)

A deterministic rewrite guard is part of the stage (spike 7: Gemma invented an
e-mail and translated a request into English; temperature does not cure it). Two
rules, both already in the spike code with data:
- the checked text has more `@` than the Whisper text has address markers
  (`ADDRESS_MARKERS`, `invented_address` of `manual/personal_proxy/verification.py`);
- the Cyrillic share of the letters drops by `CYRILLIC_SHARE_DROP` (0.5) or more
  (`manual/personal_proxy/confidence.py`).
On either, the Whisper text is used and a doubt of kind "rewrite" is added. No
threshold on rewrite length (unmeasured; not introduced).

## Boundary

In scope (all under `src/jarvis/personal_proxy/`, tests under `tests/`):

1. **Sample request.** Promote from the spike (`verification.py`, spike 8/9 cards):
   the `ERROR_HINT` and `RULES` texts, the `[?]` marking of every Whisper word with
   probability below `[personal_proxy].stt_weak_word_probability` (0.5) plus the
   sentence that `[?]` words were uncertain for the engine and are to be checked, not
   assumed wrong; the recording goes in the `images` field of `/api/chat` as the
   spike did (PROJECT.md: audio and images both go through `images`); output is the
   corrected transcript without marks. Options: model, `num_ctx`, temperature from
   settings, `num_predict` 2048.
2. **Judge request.** Gemma at temperature 0, seed 1 (`JUDGE_SEED`) with the
   recording, the Whisper transcript, and the sample; constrained JSON (`format`)
   with the same schema as the spike (the list of doubted fragments quoted exactly,
   and the overall confidence number, which is parsed but NOT used). Parse as the
   spike's `parse_judge`; an invalid structure is a failure (below).
3. **Settings** in `[personal_proxy]` (task 1's section, same validation style,
   documented in `config.example.toml` with the reason): `check_model = "gemma4:12b"`,
   `check_num_ctx = 8192`, `check_temperature = 0.618`. The judge's temperature and
   seed are constants. No seed for the sample in production.
4. **Result.** A frozen `CheckedTranscript`: `text`, `doubts` (tuple of typed doubts:
   kind in {fragment, rewrite, check_failed}, and for a fragment the quoted text),
   `source` (checked or whisper fallback), plus `would_ask`, true when the number of
   doubts is at least `[personal_proxy].doubt_min_listed` (task 1). The doubt kinds
   and the fallback reason are enums; no exception text in results.
5. **Failure policy.** A call error, timeout, empty or unparseable sample, an
   unparseable judge reply, or a guard trip: the text is the Whisper text, one doubt
   of the matching kind is added, no retry, never a send. An empty Whisper
   transcript is not sent to Gemma.
6. **Backend seam.** A small protocol for "post a chat payload, return the reply"
   so tests use a fake. The production adapter reuses the project's existing Ollama
   client/backend code (find it; do not write a second HTTP client). If reuse needs a
   change to existing code, stop and report. The stage logs nothing derived from the
   transcript, the doubts, or the audio.
7. Tests with a fake backend (pure logic): `[?]` marking, payload shape (audio in
   `images`, options), judge parsing, doubt list, `would_ask` boundary at
   `doubt_min_listed`, each failure path falling back to the Whisper text, each of
   the two rewrite rules (positive and negative fixtures, including a legitimate
   Latin word or an address in the Whisper text that must not trip them), an empty
   transcript, no text in `repr`/exceptions of failure results, config keys.

Out of scope: sanitization, the outbound gate, application wiring, pipeline
composition, UI, any live Ollama call by the agent.

## Human-run handoff (prepared by the agent, run by the owner)

A script/command set under `manual/`, self-sufficient per CLAUDE.md Testing protocol
4 (every command, key, and default named literally with its source; the Ollama
endpoint, model, and options named from settings): run the stage on a few recordings
of `personal_proxy_corpus_wavs/` (after the speech-to-text stage), print the Whisper
text, checked text, doubts, `would_ask`, source, and timing; include at least the
known cases of spike 7 (`n_short_translate`, `m_trade_house`) so the rewrite guard
is seen working. Preparing it must not run it. Check it with
`tools/check_handoff_self_sufficiency.py`.

## Acceptance criteria

- [ ] The stage returns the checked transcript and the doubt list; `would_ask`
      follows `doubt_min_listed`.
- [ ] Any failure falls back to the Whisper text with a doubt of the matching kind,
      with no retry and nothing sent.
- [ ] Both rewrite rules trip on the spike's known cases and not on ordinary text.
- [ ] The audio goes in `images`; no new HTTP client; no text in logs or failure
      results.
- [ ] The human-run handoff exists and is self-sufficient.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
