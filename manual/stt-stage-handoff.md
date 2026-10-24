# Human-run handoff: speech-to-text stage (task v2.1.0-3)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`).
Run by a human: it loads Whisper (GPU), needs the network once, and uses the
recordings of spike v2.1.0-1. The agent prepared it and ran none of it.

What it answers: (a) does the stage install, fetch its weights once and load
offline; (b) what does the guarded function return for real recordings (text,
per-word probabilities, per-segment signals, timing); (c) does
`stt_min_speech_seconds` separate the silence and noise controls from real
utterances, so that its unmeasured default of 0.3 can be kept or changed.

`PROJECT.md` (section "v2.1.0 speech recognition and confidence spikes")
describes this stage. This handoff does not rely on it; every default it uses is
cited below.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_stt_whisper.py`, `tests/test_personal_proxy_speech_guard.py`,
`tests/test_setup_stt_model.py`, `manual/tests/test_manual_check_stt_stage.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. The tools read `config.toml` from the
  current directory (option `--config`, default `config.toml`); a missing file
  means the code defaults.
- `[personal_proxy]` keys used (code defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `stt_model = "large-v3-turbo"`, `stt_device = "cuda"` (the other value is
  `"cpu"`), `stt_language = "ru"`, `stt_min_speech_seconds = 0.3` (unmeasured
  starting value). Each tool prints the effective values it uses.
- The speech threshold is `[vad].threshold` (`VadSettings`, same file;
  default `0.5`). A `>=` comparison per 512-sample window (32 ms) of the Silero
  VAD, as in `src/jarvis/personal_proxy/stt/silero_probabilities.py`.
- The controls are the spike's: `ctl_silence` (2.0 s of digital silence) and
  `ctl_noise` (3.0 s of seeded room noise, RMS 0.005), defined by `CONTROLS`
  and `NOISE_RMS` in `manual/personal_proxy/corpus.py`.
- The real utterances are the `.wav` files of `personal_proxy_corpus_wavs/`
  (spike v2.1.0-1 recordings; gitignored; contains invented data only). Any
  other directory of 16 kHz `.wav` files works the same way, for example
  `personal_proxy_corpus_v2_wavs/`.
- The Whisper settings are fixed in `src/jarvis/personal_proxy/stt/stt_whisper.py`:
  `BEAM_SIZE = 5`, `COMPUTE_TYPE_BY_DEVICE = {"cuda": "float16", "cpu": "int8"}`.

## 1. Install and fetch the weights (network needed once)

0. `setup_stt_model.py` imports the `jarvis` package for its offline check, so
   it must be importable: run every command of this handoff from the
   repository root, in the environment where `python -m jarvis` runs, which
   is the one where `pip install -e .` was done (README.md, "Manual
   installation"). If `python -c "import jarvis"` fails there, run
   `pip install -e .` from the repository root first.

1. Jarvis and any other GPU-heavy program (including a loaded Ollama model)
   should not be running while step 3 measures timing.
2. `python -m pip install -r requirements-stt.txt`
   (pins in `requirements-stt.txt`: `faster-whisper==1.2.1`,
   `ctranslate2==4.8.3`, the CUDA 12 cuBLAS and cuDNN wheels).
3. `python setup_stt_model.py`
   It downloads the model named by `DEFAULT_MODEL` in `setup_stt_model.py`
   (`large-v3-turbo`) and then loads it from local files only on the CPU.
   Expected: the lines "Downloaded to ..." and "Done. The model is cached
   locally". Any error ends the handoff: report it.
   This proves the weights are cached and load on the CPU. It does not prove
   the CUDA path: that is first exercised in step 3.

## 2. Guard: speech seconds per clip (no Whisper involved)

`python -m manual.manual_check_stt_stage guard --wavs personal_proxy_corpus_wavs`

It prints one line per clip: kind, seconds of speech found, length, verdict at
the effective `stt_min_speech_seconds`, id; then the most speech found in any
control and the least speech found in any real utterance.

Read it as: the minimum must lie above the controls' maximum and below the
utterances' minimum. Expected for the default: both controls `NO SPEECH` with
0.00 s (the automated test
`test_the_real_vad_finds_no_speech_in_digital_silence_and_room_noise` in
`tests/test_personal_proxy_speech_guard.py` asserts this for the same
controls), every utterance `speech` (not asserted anywhere; this is what you
are measuring). Report the two summary numbers and any
utterance marked `NO SPEECH`. If the numbers do not leave room for a value
between them, say so; do not tune on this alone, the guard is meant to reject
silence and noise, not to be tight.

## 3. Transcription through the guarded function

`python -m manual.manual_check_stt_stage transcribe --wavs personal_proxy_corpus_wavs --limit 5`

This loads Whisper on `stt_device` from local files only (no download), runs
the two controls and the first 5 recordings (alphabetical) through
`transcribe_guarded`, and prints per clip: the text, each word with its
probability, each segment's `avg_logprob`, `no_speech_prob`,
`compression_ratio`, and the seconds taken (guard included).

Expected: both controls print `NO SPEECH ... engine not called`; each
recording prints Russian text close to what was said and word probabilities.
Timing for comparison: spike v2.1.0-5 measured 0.25 s per recording on the GPU
(`PROJECT.md`, section "v2.1.0 speech recognition and confidence spikes";
`tasks/done/spike-v2.1.0-5-stt-engines.md`); this run also includes the guard.
`--limit` takes any positive number.

If loading fails on `cuda`, the error is a device error (it quotes the
original text and suggests checking the CUDA libraries or setting
`stt_device = "cpu"`); it is not a missing-weights error, and it does not
mean `setup_stt_model.py` must be run again.

To check the CPU path as well, set `stt_device = "cpu"` under `[personal_proxy]`
in `config.toml` and repeat this step (slower, spike 5 measured 3.7 to 5.1 s);
set it back to `"cuda"` afterwards.

## 4. Offline proof

With the network disabled (airplane mode or unplugged), repeat step 3 once.
Expected: it works unchanged. If the weights are not cached, it must stop with
a message that names `python setup_stt_model.py`, never start a download.

## What to report

The two summary numbers of step 2, any clip that surprised you in step 3 (empty
text, wrong language, invented words), the timing, and the outcome of step 4.
