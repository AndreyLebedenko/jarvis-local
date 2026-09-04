# Short Gemma 4 audio is request-shape-sensitive; no universal suppressor established

**Detected at commit:** `72b4a0b`, branch `fix/voice-turn-audio-framing`
(working tree), during the human-run acceptance session for
`task-voice-turn-audio-framing.md`.

**Reinvestigated at commit:**
`de45ac8d3d93a489e29eb1c997f8b3f70a2bf7f2` with uncommitted research-harness
changes, 2026-09-02 and 2026-09-03.

**Reported by:** owner + agent, 2026-09-01 to 2026-09-03.

**Status:** Open. The user-visible short-audio failure is reproduced, but no
root cause or production fix is established. The earlier universal
request-shape-suppression conclusion and two-pass recommendation are withdrawn.

## User-visible symptom

Some voice turns, especially short ones, are answered as if no audio arrived.
Observed surfaces include an explicit refusal, a generic bluff, a near-miss,
or fabricated words. The journal can still play the stored WAV and the request
log records an audio attachment, so capture and attachment occurred.

Longer recordings often remain understandable under the same production
framing. This is the important boundary: there is a real short-audio problem,
but it is not evidence that one request field universally disables audio.

## Correction to the original investigation

The first investigation was not adequate for a causal conclusion:

- It repeated one 1.1 s clip ten times instead of testing independent clips.
  Repetition estimates run variance for that clip; it does not establish how
  the behavior generalizes across recordings.
- The effective model was not recorded and was later found to be affected by
  the `config.ui.toml` override. Some tables were therefore labeled with a
  model that did not run, and the model for earlier tables cannot be recovered.
- The pass criterion searched an answer for words from the recording. That is
  not a valid comprehension metric when the prompt asks for an answer rather
  than a transcript, and it allows both bluffing and paraphrase to be
  misclassified.
- Raw requests, raw responses, model digests, `/api/show` data, and a committed
  harness were not retained.
- Several comparisons changed more than one factor, then described the result
  as one internal "attention" or template mechanism. No internal attention
  state was measured.
- The rule requiring at least ten runs per condition was unsupported. Repeat
  count and independent-fixture count answer different questions; neither has
  a universal minimum detached from the expected effect and decision risk.

The historical single-clip and padding observations may be useful hypotheses,
but they are not used as verified causal evidence below.

## Controlled follow-up

### Reproducibility record

Human-run harness: `manual_check_audio_request_shape.py`.

Primary controlled raw artifact:
`manual_check_audio_request_shape_out/results-20260903T193753Z.jsonl`.

Artifact SHA-256:
`2c5e84ce4158b661dcce72390d06e8e5b89cbe797972a4c7ccc95453a02ef490`.

The earlier, GPU-layer-uncontrolled artifact remains available as a legacy
comparison record:
`manual_check_audio_request_shape_out/results-20260902T223154Z.jsonl`,
SHA-256
`523543c2de7087d7f185917bc7e10391f4537f37f6f57040e09ddcd5b612b485`.

The artifact is intentionally ignored by Git because it contains raw local
model outputs and prompt material. It records the sanitized payload and raw
response for every cell, plus WAV hashes and model provenance.

Environment:

- Ollama `0.33.3`.
- `temperature=0.0`, `seed=20260902`, `num_predict=256`.
- Common live options: `num_ctx=65536`, `flash_attention=true`,
  `kv_cache_type=q8_0`, `top_p=0.9`, `top_k=50`, `min_p=0.05`, and
  `repeat_penalty=1.1`, plus `num_gpu=99` on every `/api/chat` request.
- One run per model x fixture x condition. The cells were deterministically
  shuffled within each model while models ran sequentially to avoid repeated
  model loading. This run does not estimate stochastic repeat variance.

The three model digests and all six WAV SHA-256 values match the legacy run.

Models were named explicitly and verified through `/api/tags` and `/api/show`:

| model | quant | digest | baked system |
|---|---:|---|---|
| `gemma4:12b-it-q4_K_M` | Q4_K_M | `4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c` | none |
| `gemma4:12b-it-q8_0` | Q8_0 | `41c402fdddc2a87e40a4391caa400961e93786383fbb92a88fc764c333c25322` | none |
| `gemma4-12b-jarvis-free-mm:latest` | Q8_0 | `1f18172bd78b85959df28a29baaf7648863e13c2d1ecca9818d23cc8b4329b5f` | long English persona prompt |

All three `/api/show` records exposed `{{ .Prompt }}` as the template. The
custom model differs in more than its baked system and has a distinct digest;
this experiment therefore does not identify either quantization or that system
prompt as its causal difference.

### Fixtures

Five WAVs have human-supported reference text and are scored. The sixth has no
human-verified transcript and is diagnostic only.

| key | duration | bytes | reference provenance | role |
|---|---:|---:|---|---|
| `short_1_1s` | 1.1 s | 35244 | owner statement in the original report | scored |
| `short_1_3s` | 1.3 s | 41644 | owner statement in the original report | scored |
| `edited_4_8s` | 4.8 s | 153644 | human-edited transcript overlay | scored |
| `edited_6_8s` | 6.8 s | 217644 | human-edited transcript overlay | scored |
| `missing_long_turn_1_replacement` | 9.5 s | 304044 | human-edited transcript overlay | scored replacement |
| `missing_long_turn_2_replacement` | 12.5 s | 400044 | none | unscored replacement |

The original 2026-08-05 WAV pair was removed by journal consolidation. Its
archive record retains only the combined size, `704088` bytes. The selected
9.5 s and 12.5 s substitutes sum to exactly that byte count. The individual
mapping is an approximation; neither substitute is represented as recovered
audio.

The two short WAVs contain the same reported words, "Как ты меня слышишь?",
but they are independent recordings. This gives some replication of content,
not broad linguistic coverage.

### Conditions and scoring

Every audio-bearing condition sends the same English verbatim-transcription
instruction and the same WAV bytes through the verified `images` field:

1. `bare_audio`: one user message.
2. `bare_audio_noop_tool`: bare plus one `noop` declaration.
3. `empty_system_audio`: explicit empty system message plus the user message.
4. `short_system_audio`: `You are Jarvis.` plus the user message.
5. `configured_system_audio`: current composed Jarvis system prompt plus the
   user message.
6. `configured_system_audio_noop_tool`: configured system plus `noop`.
7. `no_media_control`: bare request with no media.

Normalization case-folds text, maps `ё` to `е`, removes punctuation, and
collapses whitespace. Exact match is reported directly. For a compact
descriptive comparison below, "usable" means WER <= 0.10. That boundary is not
a product acceptance standard and does not convert the five fixtures into a
population-rate estimate. The unverified 12.5 s reference is never scored.

## Results

Each table cell is based on five scored fixtures.

| model | condition | exact | usable |
|---|---|---:|---:|
| Q4_K_M | bare | 4/5 | 5/5 |
| Q4_K_M | bare + noop | 3/5 | 3/5 |
| Q4_K_M | empty system | 3/5 | 4/5 |
| Q4_K_M | short system | 3/5 | 3/5 |
| Q4_K_M | configured system | 0/5 | 0/5 |
| Q4_K_M | configured system + noop | 1/5 | 2/5 |
| Q8_0 | bare | 2/5 | 3/5 |
| Q8_0 | bare + noop | 3/5 | 3/5 |
| Q8_0 | empty system | 4/5 | 4/5 |
| Q8_0 | short system | 2/5 | 3/5 |
| Q8_0 | configured system | 2/5 | 3/5 |
| Q8_0 | configured system + noop | 2/5 | 3/5 |
| custom Q8_0 | bare | 3/5 | 3/5 |
| custom Q8_0 | bare + noop | 3/5 | 3/5 |
| custom Q8_0 | empty system | 4/5 | 4/5 |
| custom Q8_0 | short system | 2/5 | 3/5 |
| custom Q8_0 | configured system | 2/5 | 3/5 |
| custom Q8_0 | configured system + noop | 2/5 | 4/5 |

Duration/fixture stratum is much more predictive than request shape:

| scored stratum | cells | exact | usable |
|---|---:|---:|---:|
| short, 1.1/1.3 s | 36 | 6/36 | 6/36 |
| longer, 4.8/6.8/9.5 s | 54 | 38/54 | 50/54 |
| no-media controls | 15 | 0/15 | 0/15 |

The unscored 12.5 s replacement produced closely matching, clearly
audio-derived Russian content in all 18/18 audio-bearing cells. All three of
its no-media controls refused the absent recording. This directly refutes the
claim that any tested system-plus-tool shape necessarily makes audio
unavailable.

### GPU-layer control (resolved)

The 2026-09-02 harness did not explicitly send Ollama `options.num_gpu`. The
custom model's `/api/show` data declared `num_gpu 99` in its Modelfile, while
the Q4_K_M and Q8_0 requests had no harness-controlled GPU-layer value. The
2026-09-03 rerun resolves that gap: metadata records
`requested_num_gpu_layers=99`, every one of its 126 sanitized payloads records
`options.num_gpu=99`, and every model's effective options reports the same
value.

The two runs cannot measure the effect of this change: Ollama also changed
from `0.33.2` to `0.33.3`, and 27/126 raw response strings differ. With one
trial per cell, neither run estimates repeat variance. The controlled rerun is
the primary record; the differences do not support an attribution to GPU-layer
placement, server version, or any internal mechanism.

### Paired tool comparison

Using the same <=0.10 WER boundary across the 15 model/fixture pairs:

- `bare_audio` -> `bare_audio_noop_tool`: 2 degraded, 0 improved, 13 unchanged.
  Both degradations are the Q4_K_M short clips. The longer clips remain usable.
- `configured_system_audio` -> `configured_system_audio_noop_tool`: 0 degraded,
  3 improved, 12 unchanged.

A no-op tool can interact adversely with a marginal short clip, but it is not
an independent universal audio-off switch. The direction also depends on the
surrounding request.

### Paired system observations

- Q4_K_M bare transcribed both short clips, while Q8_0 and custom Q8_0 bare
  refused both.
- An explicit empty system message made the 1.3 s clip exact for all three
  models, but the 1.1 s clip still failed for all three except Q4_K_M bare.
- The configured system failed all five scored Q4_K_M fixtures, yet the same
  long clips generally remained usable for Q8_0 and custom Q8_0.
- In the custom model, configured system plus `noop` made the 1.3 s clip exact
  even though configured system without `noop` was only a near-miss.

These are interactions among model, WAV, and request shape. They do not support
a monotonic rule in which every additional prompt layer consumes audio
attention.

## Supported conclusion

The reproduced behavior is:

> Very short Gemma 4 audio is fragile. Whether it is decoded depends on the
> exact model, exact recording, and request framing. Longer audio in this
> fixture set survives all tested request shapes almost always.

The experiment does not inspect internal attention, prove a chat-template
defect, isolate a quantization effect, or establish a single suppressor.
Refusal wording is only an observable output, not evidence that Ollama dropped
the `images` field.

The bare transcription request remains the best measured Q4_K_M condition,
but it is not reliable across the requested model set: it is usable on only
3/5 scored clips for both Q8_0 variants, with both short clips failing.
Therefore a mandatory two-pass architecture is not justified by this evidence.
It would move the same unresolved short-audio failure into pass one.

## Temporary decision

Make no production request-shape or two-pass change from this report. Keep the
explicit Journal transcription action as an available diagnostic/user action,
not as a proven universally reliable workaround.

The bug remains open as short-audio fragility. A production decision needs a
second study with a larger human-transcribed set of distinct short utterances,
predeclared scoring, and separate factors for clip boundary/padding, prompt
language/task, system framing, and tools. The production answer task must be
tested separately from verbatim transcription because its valid outcome metric
is different.

## Facts retained from earlier work

- Audio continues to use the `images` field of native `/api/chat`; the project
  day-0 transport decision is unchanged.
- An `audio` message field is not a supported native Ollama transport. This is
  independent of the rejected attention-suppression explanation.
- Padding changed outcomes for one historical marginal clip, but that sweep
  lacked the provenance controls of the corrected run. Treat it as a candidate
  intervention for the next short-clip study, not an established root cause.
- The earlier image/tool comparison was not repeated by the corrected audio
  harness and is outside this report's supported conclusion.
