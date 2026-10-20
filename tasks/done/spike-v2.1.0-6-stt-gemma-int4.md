# Spike v2.1.0-6: STT engines on the GPU next to Gemma 12B INT4 at num_ctx 8192

Status: Result recorded 2026-10-19 (rule frozen before any run). Closed 2026-10-20.

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spike 5
(`tasks/done/spike-v2.1.0-5-stt-engines.md`), which picked Whisper on accuracy but
found GPU memory pressure and a swap cost of about one second per switch next to
`gemma4:12b-it-q8_0` at `num_ctx` 65536. The owner decided on 2026-10-19 to try
both engines on the GPU next to a lighter Gemma first:

1. `gemma4:12b` (INT4, 7.6 GB), instead of `gemma4:12b-it-q8_0`.
2. `num_ctx` 8192, instead of 65536.

## Question

With Gemma 12B INT4 at `num_ctx` 8192 resident, do GigaAM v3 and Whisper
large-v3-turbo both run on the GPU without the memory pressure and swap cost seen
in spike 5, and how do they compare?

## Scope

Only the `coexist` step of spike 5 is repeated. Accuracy and fidelity do not
depend on Gemma's configuration (decoding is deterministic and the engines run in
their own processes), so the spike 5 numbers stand and are not re-measured:

| | GigaAM v3 | Whisper ru |
|---|---|---|
| audio failures of 88 | 8 | 4 |
| span fidelity | 0.708 (below baseline 0.792, fails criterion 2) | 0.854 |
| isolated warm median | 0.06 s | 0.25 s |

GigaAM stays inadequate on fidelity whatever this spike shows; it is measured
because the owner asked for the comparison and because its resource profile
decides whether it is worth tuning later.

Unchanged from spike 5 and taken from the server environment, not from the
request: flash attention and the Q8_0 KV cache (`OLLAMA_FLASH_ATTENTION=1`,
`OLLAMA_KV_CACHE_TYPE=Q8_0`, `OLLAMA_GPU_MEMORY_FRACTION=0.9`). The probe request
keeps every other option of the recorded spike request and overrides only the
model and `num_ctx`.

## Measurement

The `coexist` output of spike 5, per engine, with `--model gemma4:12b
--num-ctx 8192`: Gemma alone (seconds, GPU share, machine GPU memory), the engine
loaded and run over 10 recordings (median seconds), machine GPU memory with both,
GPU share after, one more Gemma request, and six alternating STT / Gemma cycles.
The recorded `options` in each result file proves which configuration ran.

## Decision rule (frozen)

A configuration is **resource-adequate** when, in the coexistence step:

1. Ollama's GPU share is 1.0 before and after the engine runs;
2. the engine's median seconds per recording is at most 3.0 and at most twice its
   isolated median (0.06 s GigaAM, 0.25 s Whisper, from spike 5);
3. the machine's GPU memory with both loaded leaves at least 1000 MiB free of
   16,303 MiB (at most 15,303 MiB used).

It has **no swap penalty** when the medians of the six alternating cycles are at
most 1.5 times the isolated values: STT at most 1.5 x its isolated median, Gemma
at most 1.5 x its own "before" time of the same run.

Outcome:
- Whisper is resource-adequate: Whisper on the GPU is confirmed (it already
  passes accuracy and fidelity). Whether it also has no swap penalty is reported
  and goes to the owner as the cost of the configuration.
- Whisper is not resource-adequate: the owner decides between further levers
  (a smaller Whisper, `OLLAMA_KEEP_ALIVE`, CPU) and the two-step baseline.
- GigaAM's results are reported for comparison only; it is not adopted while its
  fidelity fails.

The thresholds (1000 MiB, 1.5x) are the agent's choice under the owner's
delegation, not statistics.

## Honest limits

- The machine's GPU memory includes about 1.5 GB held by other programs (spike 5
  measurement); close them or record what runs.
- One GPU, driver, and corpus; six cycles is a small sample.
- INT4 Gemma may differ in sanitization quality from q8; this spike measures
  resources only, and the quality of the text-only step with INT4 is a later task.
- A WDDM spill of GPU memory to system RAM shows up only as slowdown.

## Run (human-run handoff: live Ollama and GPU)

Preconditions, to be checked by the runner:
- `ollama ps` lists no loaded model; `ollama list` shows `gemma4:12b` (7.6 GB).
- The Ollama server was started with `OLLAMA_FLASH_ATTENTION=1` and
  `OLLAMA_KV_CACHE_TYPE=Q8_0` (it reads them at start; `OLLAMA_FLASH_ATTENTION`
  and `OLLAMA_KV_CACHE_TYPE` are set in the owner's user environment at the time of
  writing, the runner restarts Ollama if unsure).
- The repository root is the current directory; `.venv-stt-whisper`,
  `.venv-stt-gigaam`, `personal_proxy_corpus_wavs/`, and
  `manual_check_transcription_prompt_out/calls/a_current-id_email-s19210.json`
  exist (the last is the default `--reference-request`).
- Nothing else uses the GPU heavily; note the idle GPU memory
  (`nvidia-smi --query-gpu=memory.used --format=csv`).

```
.venv-stt-whisper\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_gemma_int4_out coexist --engine whisper_ru --wavs personal_proxy_corpus_wavs --model gemma4:12b --num-ctx 8192
.venv-stt-gigaam\Scripts\python.exe -m manual.manual_check_stt_engines --out manual_check_stt_engines_gemma_int4_out coexist --engine gigaam --wavs personal_proxy_corpus_wavs --model gemma4:12b --num-ctx 8192
```

Each command prints and saves `coexist-<engine>.json` in the output directory. The
runner reports the two files; `score` is not run (it needs the spike 5 calls).

## Result (2026-10-19, run by the agent as in spike 5, owner's instruction)

Run with `gemma4:12b`, `num_ctx` 8192 (recorded in each result file's `options`);
idle machine GPU memory 1,915 MiB before the run, no Ollama model loaded.

| | Whisper ru (GPU) | GigaAM (GPU) | Spike 5, Whisper (q8, 65536) |
|---|---|---|---|
| Gemma alone, s | 0.13 | 0.12 | 0.17 |
| Ollama GPU share before / after | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |
| machine GPU memory, Gemma alone, MiB | 10,437 | 10,382 | 14,630 |
| machine GPU memory, both, MiB | 12,737 | 12,620 | 15,534 |
| engine median in coexistence, s | 0.207 | 0.066 | 0.223 |
| next Gemma request after engine, s | 0.125 | 0.127 | 0.608 |
| six cycles, median STT / Gemma, s | 0.198 / 0.121 | 0.062 / 0.120 | 1.15 / 1.10 |

Outcome by the frozen rule: both engines are **resource-adequate** (GPU share 1.0,
engine median within twice isolated, 12.6-12.7 GB used of 16.3 GB, about 3.6 GB
free) and have **no swap penalty** (cycle medians equal the isolated values).
The one-second swap cost of spike 5 is gone. Whisper on the GPU is confirmed as
the first step; GigaAM remains inadequate on fidelity (0.708, spike 5).

Not measured here: sanitization quality of the INT4 model on the text-only step.
