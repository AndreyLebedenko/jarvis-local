# Spike v2.1.0-5: dedicated speech-to-text engine

Status: Result recorded 2026-10-19 (rule frozen before any run). Closed 2026-10-20.

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

## Result (2026-10-19, run by the agent; weights downloaded with the owner's yes)

Outcome by the frozen rule: **Whisper** (`whisper_ru`: faster-whisper 1.2.1,
large-v3-turbo, GPU float16, language `ru`).

| | Gemma A (spike 2) | GigaAM v3 (GPU) | Whisper ru (GPU) |
|---|---|---|---|
| audio failures of 88 | 22 | 8 | 4 |
| median WER | 0.163 | 0.000 | 0.000 |
| span fidelity, overall | 0.792 | 0.708 | 0.854 |
| numeric / email / person / other | 23/24, 4/6, 24/34, 25/32 | 16/24, 4/6, 24/34, 24/32 | 22/24, 4/6, 26/34, 30/32 |
| warm seconds per recording, median | - | 0.06 | 0.25 |
| GPU memory added (load / peak) | - | +1974 / +2290 MiB | +2202 / +2430 MiB |

- GigaAM: accuracy passes (8 is the limit), **fidelity fails** (0.708 against
  0.792), so it is not adequate. Whisper is adequate on all three criteria.
- Both engines ran on the RTX 5070 Ti (Blackwell): faster-whisper 1.2.1 with
  CTranslate2 4.8.3 and the cuBLAS/cuDNN 12 wheels, and onnx-asr 0.12.0 with
  ONNX Runtime GPU 1.31.0 and the CUDA 13 wheels
  (`pip install "onnxruntime-gpu[cuda,cudnn]"`). Load time 2.2 s each.
- Whisper's failures are two utterances at both passes: `m_short_call`
  (transliteration artifact: "Позвони Майкл Браун." for the script "Michael
  Brown") and `m_trade_house` (an email spelled "info собака trade-house точка
  ru" comes out glued: "инфособакотрейдэшхаус.ру"). Its fidelity misses: the
  org "ООО Альфатрейд" heard as "Альфтеррейт", the Latin names of the English
  utterances written in Cyrillic, and one wrong phone number
  (`id_two_people_phone`: "8 912 345 607 89" for "...шестьдесят семь
  восемьдесят девять").
- GigaAM's failures: `id_passport` truncated to "Паспорт серия 450" (the
  number is lost), `id_bank_transfer_long` account heard as 7012345678 (digits
  dropped), `id_delivery_long` phone missing, `id_two_people_phone` as
  891234560789, `m_github` mixed Cyrillic and Latin garbage ("Дмитрий Андрov"),
  `m_short_english` "Сэндеп to Виктор Петренко", `m_trade_house`, `m_short_call`.
- Controls (reported only): GigaAM returns an empty string on all 4 silence and
  noise generations. Whisper invents text on all 4: "Продолжение следует..."
  with `language="ru"`, "Thank you." with automatic language detection. The
  production capture feeds only VAD-accepted chunks, so this is a guard to add,
  not measured here.
- `whisper_auto` equals `whisper_ru` on failures and fidelity (4 of 88, 0.854).

**Coexistence with Gemma 12B (frozen criterion 3 passed for both).** With the
production options (`num_ctx` 65536, q8 KV cache) the machine's GPU memory with
Gemma alone is 14,477 MiB of 16,303 MiB (about 1.5 GB of it belongs to other
programs); Ollama's GPU share stayed 1.0 for both engines and each
engine ran at its isolated speed (Whisper 0.22 s, GigaAM 0.07 s). But the next
Gemma text request took 0.61 s (Whisper) and 0.69 s (GigaAM) against 0.17 s
before, and the machine's GPU memory with both loaded was near full (15,534 and 15,726 MiB).

**Exploratory, not part of the rule:** six alternating STT / Gemma cycles, as in
the real pipeline, show a swap cost for both GPU engines:

| | STT alone | STT in cycles | Gemma alone | Gemma in cycles |
|---|---|---|---|---|
| Whisper ru (GPU) | 0.25 s | 1.15 s | 0.17 s | 1.10 s |
| GigaAM (GPU) | 0.06 s | 0.96 s | 0.17 s | 1.30 s |
| GigaAM int8 (CPU) | 0.14 s | 0.11 s | 0.18 s | 0.21 s |
| Whisper int8 (CPU) | 3.72 s | 5.01 s | 0.18 s | 0.29 s |

Two GPU-resident models cost about one extra second on each switch. Whisper on
the CPU is accurate (same 4 failures and fidelity as on the GPU) but 3.7 to 5.1
s per recording, over the 3.0 s limit. GigaAM int8 on the CPU is fast and does
not disturb Gemma, but has 6 failures and fidelity 0.729, below the baseline.

Reading: the dedicated engine removes the failure mode of spikes 1 to 4
(Whisper 4 failures of 88, the two that remain are a transliteration artifact
and an email spelled out letter by letter). The price is GPU memory pressure
next to Gemma at `num_ctx` 65536. Untested levers: a smaller `num_ctx` for the
text-only sanitization step, a Whisper small variant, or `OLLAMA_KEEP_ALIVE`
changes. `requirements.txt` is not changed; the engines live in the gitignored
`.venv-stt-whisper` and `.venv-stt-gigaam`, and their weights in the Hugging
Face cache (about 2.9 GB).
