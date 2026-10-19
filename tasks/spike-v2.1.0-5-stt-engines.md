# Spike v2.1.0-5: dedicated speech-to-text engine

Status: In progress. Rule frozen 2026-10-19, before any run.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spikes 1-4. The
two-step baseline's first step (bare Gemma transcription) fails on 22 of 88
generations; a rewording (spike 2), a constrained JSON (spike 3), and a JSON
with a speech flag (spike 4) did not bring it to the 10% level. Spike 1's stop
condition put the dedicated-STT-engine question back on the table; the owner
decided on 2026-10-19 to replace the first step with a dedicated engine:

`STT -> Ollama sanitation and placeholders -> keyword/regex check -> external LLM`.

## Question

Which local engine transcribes the owner's 44 recordings reliably enough to be
the first step: GigaAM v3 or Whisper large-v3-turbo? And does it fit next to
Gemma 12B on the 16 GB GPU, or must it run on the CPU?

## Engines

- **W (Whisper):** `faster-whisper` 1.2.1 with CTranslate2 4.8.3, model
  `large-v3-turbo` (CTranslate2 weights, MIT). `language="ru"`, beam search of
  5, `temperature=0.0`, `condition_on_previous_text=False`, no built-in VAD
  filter (the production capture already feeds only VAD-accepted chunks), GPU
  `float16`. Every other `faster-whisper` parameter keeps its library default
  (for example the no-speech threshold 0.6, the log-probability threshold -1.0,
  and the compression-ratio threshold 2.4). Variant `whisper_auto` is the same with automatic language
  detection and is reported only.
- **G (GigaAM):** GigaAM v3 `e2e_rnnt` (MIT; punctuation and number
  normalization included) through `onnx-asr` 0.12.0 on ONNX Runtime GPU 1.31.0,
  fp32 weights, CUDA execution provider.
- **CPU variants:** run only for an engine whose GPU configuration fails the
  resource criterion below: `int8` on the CPU (CTranslate2 `int8` for W; the
  published `int8` ONNX files for G).

Each engine runs in its own isolated virtual environment
(`.venv-stt-whisper`, `.venv-stt-gigaam`, both gitignored). `requirements.txt`
is not changed by this spike; adopting an engine is a separate owner decision.

## Inputs

The same 44 recordings (`personal_proxy_corpus_wavs/`) and the 2 silence and
noise controls (the no-media control cannot be run through an STT engine and is
dropped). Decoding is deterministic, so the two seeds of the earlier spikes do
not exist here; every recording is run in two passes, which keeps 88 scored
generations per engine for comparability and doubles as a determinism and
warm-timing check. Recordings are the files as recorded (the production capture
already padded short chunks), read as 16 kHz mono float32.

## Measurement

Reference text is the corpus script with the `id_birth_date` correction used in
spikes 2-4 (`KNOWN_RECORDING_DEVIATIONS`). Scored in
`manual/personal_proxy/stt_scoring.py`:

- **Audio failure:** the main-run definition (refusal pattern, or WER above 0.5
  against the reference), so the number is comparable with Gemma's 22 of 88.
- **Median WER** over the 88 generations.
- **Span fidelity:** for every labeled sensitive span in the corpus, whether it
  is still recognizable in the transcript (`leaked_spans` of the main run: stem
  match for text, digit key in a digit run for numbers). Reported overall and in
  four groups: numeric (spans with digit keys), email, person, other. This is the
  number that matters for the next step, because the placeholders and the later
  restoration work on the transcript's wording.
- **Controls:** clean when the transcript is empty after stripping spaces and
  punctuation. Reported only.
- **Memory:** GPU memory used by the machine before the engine loads, after it
  loads, and its peak during the run (`nvidia-smi`), with the Ollama model
  unloaded. Load time.
- **Time:** warm (second pass) seconds per recording, median and p90, and the
  real-time factor (seconds divided by the recording length).
- **Coexistence** (`coexist` step, live Ollama): Gemma is loaded with the
  production transcription options (model, `num_ctx`, flash attention, KV-cache
  type taken from a recorded spike request), then the engine is loaded on the
  GPU and run over 10 recordings. Recorded: the Ollama model's GPU share
  (`size_vram / size` from `/api/ps`) before the engine loads and after it has
  run, the engine's median seconds per recording, and the time of one more Gemma
  request afterwards, against the isolated measurements.

Reference numbers of the Gemma baseline come from spike 2's variant A (same
recordings, same definitions): 22 of 88 failures, median WER 0.165, and its
span fidelity, recomputed with the same function at score time from the saved
spike-2 transcripts.

## Decision rule (frozen)

An engine configuration is **adequate** when all three hold:

1. **Accuracy:** at most 8 audio failures of 88 (10%, the stop level of spike 1).
2. **Fidelity:** overall span fidelity at least that of the Gemma baseline.
3. **Resources:** in the coexistence step, Ollama's GPU share stays 1.0 and the
   engine's median seconds per recording is at most 3.0, and no more than twice
   its isolated median. A configuration that fails this is rerun on the CPU
   (`int8`) for criteria 1-2 and for a median of at most 3.0 s per recording.

Outcome:
- **None adequate:** the spike fails; the owner decides.
- **One adequate:** that engine.
- **Both adequate:** the one with fewer failures when they differ by 3 or more;
  otherwise the one with higher overall fidelity when they differ by 0.02 or
  more; otherwise the one at least 1.5 times faster; otherwise the owner decides.

The thresholds (8, 3.0 s, 3, 0.02, 1.5) are the agent's choice under the
owner's delegation, not statistics.

## Honest limits

- One speaker, one room, 44 utterances, a corpus built from invented identities.
  The ranking of engines is known to flip between domains.
- Forcing `language="ru"` on Whisper may distort the fully English utterances
  (`m_short_english`); `whisper_auto` shows the other side. GigaAM is trained for
  Russian and is expected to fail on English names.
- Span fidelity is lenient for names (a stem match), so a mistranscribed name
  that keeps its first letters counts as found.
- The coexistence step measures one Gemma configuration on this GPU and driver; a
  silent spill of GPU memory to system RAM (WDDM) would show up only as slowdown.
- A winner here says nothing yet about the downstream steps (text-only
  sanitization, the regex check). Those use spike 1's text-only prompt and are a
  later task.

## Run

Authorized by the owner in chat on 2026-10-19: install the packages and run it
without a handoff (the Testing protocol's default is a human-run handoff for live
Ollama and hardware; this card records the exception). Model weights are
downloaded after the owner's explicit yes. Commands:

```
.venv-stt-whisper\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_out run --engine whisper_ru --wavs personal_proxy_corpus_wavs
.venv-stt-whisper\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_out run --engine whisper_auto --wavs personal_proxy_corpus_wavs
.venv-stt-gigaam\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_out run --engine gigaam --wavs personal_proxy_corpus_wavs
.venv-stt-whisper\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_out coexist --engine whisper_ru --wavs personal_proxy_corpus_wavs
.venv-stt-gigaam\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_out coexist --engine gigaam --wavs personal_proxy_corpus_wavs
python -m manual.manual_check_stt_engines --out manual_check_stt_engines_out score --wavs personal_proxy_corpus_wavs
```

## Result

Pending.
