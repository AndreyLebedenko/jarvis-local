# Task v2.1.1-5: Text+Voice mode

Status: Completed.

Story: `tasks/story-v2.1.1-proxy-speech-modes.md`, task 5 (Size: M-L).

## Problem

In Text+Voice the proxy still spoke the restored sentences verbatim (Markdown, "тыс.", "°C").
The mode must show the answer as received and speak a spoken version rendered by the local
model after the whole answer, as the main Jarvis does in mode 3.

## Design

1. `[personal_proxy].spoken_pass_timeout_seconds` (default 30, positive finite number, in
   `config.example.toml`).
2. `answer/spoken_derivative.py`: `SpokenDerivativeRenderer` calls the `CheckBackend` seam with
   `compose_canvas_speech_messages(contract, None, canvas)` as system and the canvas as user,
   under `asyncio.timeout`. The contract and options come from the `spoken_derivative`
   generation profile; `bind_stages` exposes it as the optional `PipelineStages.render_spoken`.
3. `AnswerPresenter.present_rendered`: sentences are shown as they arrive; after the last one
   the microphone is held, the pass runs, the answer is closed with the spoken text, and the
   cleaned, sentence-split result is spoken. Failure, timeout, empty reply, or no render stage
   speaks the cleaned canvas sentences. A failed stream skips the pass. An interrupt during the
   pass speaks nothing and still closes the answer without a derivative.
4. `AnswerCompleteBlock.spoken_derivative` -> `ProxyJournalWriter` -> `record_proxy_answer`
   stores `metadata["spoken_derivative"]` only when present.
5. `PROJECT.md` describes the mode. README is task 6.

## Boundary

Text and Voice unchanged. No change to sanitize, check, gate, restoration, the external client,
the Silero adapter, UI scripts.

## Acceptance criteria

- [x] Shown text is the canvas; spoken text comes from the local pass, cleaned; nothing is
      spoken before the pass ends and the microphone is paused for it.
- [x] Fallback to the cleaned canvas on failure, timeout, empty reply, missing stage.
- [x] The canvas stays the Journal text; the spoken version is metadata only.
- [x] An interrupt speaks nothing; a failed stream skips the pass.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Outcome (2026-10-27)

Implemented as designed; tests in `tests/test_personal_proxy_text_voice.py` plus config and
stage-binding tests. Full suite green except the known timezone failure of
`tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix`.
Limits: latency of Text+Voice is the full answer plus the local pass (not measured here; the
story's 30 s default and the latency figures need a live run); the pass uses the check model's
context (`check_num_ctx`, default 8192), so a long answer may fall back; the pass is run even
when TTS is muted (no TTS-enabled probe in the proxy); the microphone is not held while the
answer streams, only from the end of the stream. Live check is human-run.
