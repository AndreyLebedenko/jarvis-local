# Human-run handoff: transcript check stage (task v2.1.0-4)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`).
Run by a human: it loads Whisper (GPU) and calls the live local Ollama
endpoint with the recordings of spike v2.1.0-1. The agent prepared it and ran
none of it.

What it answers: (a) what the stage returns for real recordings (engine text,
checked text, doubts, `would_ask`, source, timing); (b) whether the rewrite
guard turns the two known rewrites of spike v2.1.0-7 (`n_short_translate`,
`m_trade_house`) into the engine text with a `rewrite` doubt, and leaves an
ordinary recording alone; (c) how long the check takes next to the speech
engine on the GPU.

This handoff does not rely on `PROJECT.md` or the README for this stage (their
update for this stage is not part of the task); every default it uses is cited
below. It does rely on the speech-to-text stage of task v2.1.0-3 being
installed: its prerequisites are step 1.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_transcript_check.py`,
`tests/test_personal_proxy_rewrite_guard.py`,
`tests/test_personal_proxy_check_requests.py`,
`tests/test_personal_proxy_ollama_check_backend.py`,
`manual/tests/test_manual_check_transcript_check.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs (the one where `pip install -e .` was done,
  README.md "Manual installation"). The tool reads `config.toml` from the
  current directory (option `--config`, default `config.toml`); a missing file
  means the code defaults. It prints the effective values it uses.
- `[backend]` keys used (code defaults in `BackendSettings`,
  `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `endpoint = "http://localhost:11434"`, `read_timeout_seconds = 120.0`, and the
  load options `flash_attention` and `kv_cache_type` (both unset by default).
  `[backend].model` and `[backend].num_ctx` are NOT used by this stage: the
  check overrides them with the keys below.
- `[personal_proxy]` keys used (code defaults in `PersonalProxySettings`, same
  file; commented in `config.example.toml`): `check_model = "gemma4:12b"`,
  `check_num_ctx = 8192`, `check_temperature = 0.618`, `doubt_min_listed = 1`,
  `stt_weak_word_probability = 0.5`, `stt_model = "large-v3-turbo"`,
  `stt_device = "cuda"`, `stt_language = "ru"`, `stt_min_speech_seconds = 0.3`.
- The speech threshold is `[vad].threshold` (`VadSettings`, same file;
  default `0.5`).
- Sampling: both requests use `check_top_p = 0.9`, `check_top_k = 50`,
  `check_min_p = 0.05`, `check_repeat_penalty = 1.025` from `[personal_proxy]`
  (`PersonalProxySettings`, `src/jarvis/core/config.py`; the values of the spike
  runs, `manual_check_confidence_out/run_meta.json`). They do not come from
  `[generation]`. The stage does not set `flash_attention` or `kv_cache_type`:
  `[backend].flash_attention` and `[backend].kv_cache_type` (`BackendSettings`,
  same file) are sent with every request as load options, not read from server
  environment variables; the spikes ran with `flash_attention = true` and
  `kv_cache_type = "q8_0"`. Set those two in `config.toml` to match the spikes
  before judging the results. The tool prints the sampling values it uses.
- Constants of the stage (not settings): the judge runs at temperature 0 with
  seed 1 (`JUDGE_TEMPERATURE`, `JUDGE_SEED` in
  `src/jarvis/personal_proxy/check/check_requests.py`); both requests use
  `num_predict` 2048 (`NUM_PREDICT`, same file); the rewrite guard's alphabet
  limit is `CYRILLIC_SHARE_DROP = 0.5` (`src/jarvis/personal_proxy/check/rewrite_guard.py`).
- The recordings are the `.wav` files of `personal_proxy_corpus_wavs/` (spike
  v2.1.0-1 recordings; gitignored; invented data only). The known rewrite cases
  are `n_short_translate.wav` and `m_trade_house.wav` in that directory; the
  tool stops with "missing recordings" if either is absent.

## 1. Prerequisites

1. The speech stage works: `python -m pip install -r requirements-stt.txt` and
   `python setup_stt_model.py` were done once (items 2 and 3 of section "1.
   Install and fetch the weights" of `manual/stt-stage-handoff.md`, with
   network access).
2. Ollama is running at `[backend].endpoint` and the check model is present:
   `ollama list` shows the tag from `check_model` (default `gemma4:12b`). If it
   is missing, `ollama pull gemma4:12b` (about 7.6 GB, network needed once).
   The tool checks this itself before loading Whisper: it calls `GET /api/tags`
   on `[backend].endpoint` and stops with a message (exit code 2) if Ollama does
   not answer or does not list `check_model`. You can run the same check by hand:
   `curl http://localhost:11434/api/tags` (replace the host with your endpoint).
3. Close Jarvis and any other GPU-heavy program, so the timings mean something.
   The tool loads Whisper and Ollama loads the check model; with the defaults
   both fit the GPU (spike v2.1.0-6: about 12.7 GB of 16.3 GB).

## 2. Run

`python -m manual.manual_check_transcript_check run --wavs personal_proxy_corpus_wavs`

It runs `n_short_translate`, `m_trade_house`, and then the first 3 other
recordings by file name (`--extra N` changes 3). For each it prints the engine
text, then the checked text, the source and fallback reason, `would_ask` and the
number of doubts, each doubt (`fragment` doubts show the quoted text), and the
seconds of the check. `check_num_ctx = 8192` differs from `[backend].num_ctx =
65536`, so the first call makes Ollama reload the model at the smaller context;
the first recording's seconds include that reload and are not representative.
Read the later ones for steady timing. When the rewrite guard fires, the tool
also prints `rejected sample:` with the model's discarded text (local terminal
only; the stage itself never exposes it).

Read it as:

- `source: checked` with `fallback reason: -`: the model's corrected text was
  accepted. The doubts are the fragments the judge was unsure of. With
  `doubt_min_listed = 1`, `would_ask` is True exactly when there is at least one
  doubt.
- `source: whisper_fallback` and `fallback reason: invented_address` or
  `alphabet_switch`, one `rewrite` doubt, and `checked text` equal to `engine
  text`: the rewrite guard fired. This is what the two known cases are for. The
  model is not deterministic here, so a known case may also come back as
  `source: checked` when the model did not rewrite on this run; that is not a
  defect, but report it.
- `fallback reason: call_failed`, `empty_sample`, or `unparseable_judge` with one
  `check_failed` doubt: the call or the model's reply failed. Any of these on
  more than an occasional recording should be reported with the reason.

## What to report

For `n_short_translate` and `m_trade_house`: the engine text, the checked text,
the source and fallback reason. For the others: any recording whose checked text
differs from the engine text in a way that is not a repair (a rewording, a
translation, a missing sentence), and any `would_ask: True` with its doubts.
The seconds of the check for the second and later recordings, and any fallback
reason other than the two rewrite ones.
