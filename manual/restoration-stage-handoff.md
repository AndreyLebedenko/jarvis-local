# Human-run handoff: restoration stage (task v2.1.0-7)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`).
Run by a human: it calls the live local Ollama endpoint (GPU). The agent
prepared it and ran none of it.

What it answers: does the stage's model branch (restoring original values into a
sentence in the right Russian case, validated by a deterministic check) meet the
card's rule on the production configuration (`gemma4:12b` INT4, `num_ctx` 8192)?
If it does not, the model branch is removed before task 9 and only plain
substitution stays (owner decision of 2026-10-21, `tasks/task-v2.1.0-7-restoration-pass.md`).

This handoff does not rely on `PROJECT.md` or the README for this stage (their
update is not part of the task); every default it uses is cited below.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_restoration_stage.py`,
`tests/test_personal_proxy_restoration_stream.py`,
`tests/test_personal_proxy_restoration_sentences.py`,
`tests/test_personal_proxy_restoration_validation.py`,
`tests/test_personal_proxy_restoration_requests.py`,
`tests/test_personal_proxy_restoration_substitution.py`,
`tests/test_personal_proxy_placeholders.py`,
`tests/test_personal_proxy_restored_sentence.py`,
`manual/tests/test_manual_check_restoration_stage.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs (the one where `pip install -e .` was done,
  README.md "Manual installation"). The tool reads `config.toml` from the current
  directory (option `--config`, default `config.toml`); a missing file means the
  code defaults. It prints the effective values it uses.
- `[backend]` keys used (code defaults in `BackendSettings`,
  `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `endpoint = "http://localhost:11434"`, `read_timeout_seconds = 120.0`, and the
  load options `flash_attention` and `kv_cache_type` (both unset by default).
  `[backend].model` and `[backend].num_ctx` (65536) are NOT used by this stage:
  the check overrides them with the keys below.
- `[personal_proxy]` keys used (code defaults in `PersonalProxySettings`, same
  file; commented in `config.example.toml`): `check_model = "gemma4:12b"`,
  `check_num_ctx = 8192`, `check_temperature = 0.618`, `check_top_p = 0.9`,
  `check_top_k = 50`, `check_min_p = 0.05`, `check_repeat_penalty = 1.025`.
  They do not come from `[generation]`. The stage adds no setting.
- Spike conditions: the spikes ran with `OLLAMA_FLASH_ATTENTION=1` and
  `OLLAMA_KV_CACHE_TYPE=Q8_0`. The project does not read those server variables:
  it sends `[backend].flash_attention` and `[backend].kv_cache_type` with every
  request as load options (`BACKEND_LOAD_OPTION_FIELDS`,
  `src/jarvis/core/config.py`). To match the spikes, put these two lines under
  `[backend]` in `config.toml`:
  `flash_attention = true` and `kv_cache_type = "q8_0"`. The tool prints both
  effective values and a `WARNING:` line for each one that is unset. (Setting the
  server variables as well is optional; if you do, set them before Ollama starts.)
- Constants of the stage (not settings): `num_predict` 512 (`NUM_PREDICT` in
  `src/jarvis/personal_proxy/restoration/restoration_requests.py`); a time limit of 15 s per
  model call (`BACKEND_TIMEOUT_SECONDS`, `src/jarvis/personal_proxy/restoration/restoration.py`;
  a timeout is a fallback); a sentence with more than 8 placeholders
  (`MAX_MODEL_PLACEHOLDERS`) or more than 1000 characters
  (`MAX_MODEL_SENTENCE_CHARS`, both in
  `src/jarvis/personal_proxy/restoration/restoration_validation.py`) is never sent to the model
  and is only substituted; a newline, or more than 4000 pending characters
  (`MAX_PENDING_CHARS`, `src/jarvis/personal_proxy/restoration/restoration_sentences.py`), ends
  a sentence; reasoning off
  (`think: false`, the `ReasoningLevel.OFF` default of
  `src/jarvis/dialog/backend.py`); the text-only request has no `format` and no
  `images`.
- Seeds: `SEEDS = (19210, 4243)` in `manual/personal_proxy/restoration.py`; each
  item runs once per seed (60 generations). The seed is added to the request by
  the tool only; the stage itself sets none.
- Items: `ITEMS` in `manual/personal_proxy/restoration.py`, 30 invented sentences
  with placeholders (names, phone, email, card, address, organization, date,
  amount). Nothing real is involved.
- The rule (constants in `manual/personal_proxy/restoration.py`):
  `MIN_VALIDATION_PASS_RATE = 0.90`, `MAX_ALTERATION_RATE = 0.05`,
  `MIN_FALLBACK_BEATEN_SHARE = 0.80`.

- The validation rule (`src/jarvis/personal_proxy/restoration/restoration_validation.py`): the
  sentence is cut at its placeholders; the model's reply must equal the remaining
  text exactly (case, `ё`, punctuation, digits), and in each placeholder's place
  must stand a form of that placeholder's original: the same number of words and
  the same separators between them. A Cyrillic word of 3 or more letters matches
  by stem, with an ending at most 3 letters longer (`MAX_ENDING_GROWTH`) and the
  same first-letter case; every other word (Latin names, e-mail parts, digits,
  short words) must match exactly, case included. Known limits: a different name
  that shares the stem and fits the length can pass, and a name whose declension
  changes its first letters (`Лев` to `Льва`) falls back to substitution.
- The 10% outage rule: if more than 10% of the 60 generations
  (`MAX_UNUSABLE_SHARE = 0.10`, `manual/manual_check_restoration_stage.py`) have
  fallback reason `no_usable_reply`, the run is INVALID (see section 2).

## 1. Prerequisites

1. Ollama is running at `[backend].endpoint` and the check model is present:
   `ollama list` shows the tag from `check_model` (default `gemma4:12b`). If it
   is missing, `ollama pull gemma4:12b` (about 7.6 GB, network needed once). The
   tool checks this itself first: it calls `GET /api/tags` on `[backend].endpoint`
   and stops with a message (exit code 2) if Ollama does not answer or does not
   list `check_model`. By hand: `curl http://localhost:11434/api/tags` (replace the
   host with your endpoint).
2. `config.toml` has, under `[backend]`, `flash_attention = true` and
   `kv_cache_type = "q8_0"` (see Literal references). Without them the run still
   works but is not the spikes' condition.
3. Close Jarvis and any other GPU-heavy program, so the timings mean something.
4. Check which model build you are measuring. The tool prints, before anything
   else is sent, `model gemma4:12b: parameter_size=...; quantization_level=...`
   (from `POST /api/show` on `[backend].endpoint`, the `details` fields), and a
   `WARNING:` line if `quantization_level` does not start with `Q4` or `INT4`, or
   if the call failed. The same values by hand: `ollama show gemma4:12b` (the
   `Quantization` line). The production configuration is the INT4 build, so the
   printed level must be a 4-bit one (for example `Q4_K_M` or `Q4_0`). The tool
   does not decide this for you: if the printed level is anything else (`Q8_0`,
   `F16`), stop and report it, because the result would not be about the
   production configuration. Write the printed line in your report.

## 2. Run

`python -m manual.manual_check_restoration_stage --out manual_check_restoration_stage_out run`

Before the first measured generation the tool sends one tiny warm-up request so
the model is loaded at `check_num_ctx = 8192`; a cold load can take about a
minute (the backend read timeout, `[backend].read_timeout_seconds = 120.0`,
allows it), and the tool prints nothing until it is done. The request is cut at
one token on purpose; that cut is counted as loaded. If the warm-up fails for
any other reason it stops with "Nothing was run" (exit code 2). `--out` defaults to `manual_check_restoration_stage_out` (gitignored output; it
holds only invented data). The run refuses to start if `results.json` already
exists in `--out` (delete the directory or use another `--out`), so two runs are
never mixed. It takes about 10 to 20 minutes. The warm-up loads the model at
`check_num_ctx = 8192` (it differs from `[backend].num_ctx = 65536`), so the
first generation is not slowed by the reload.

An Ollama outage must not look like a verdict. If more than 10% of the generations
(more than 6 of 60) have fallback reason `no_usable_reply`, the run stops at once
(exit code 3) with `INVALID RUN: ...` and writes no report and no review sheet;
`score` also refuses (exit code 3, no verdict) when `results.json` is incomplete or
has more than 10% unusable replies. Fix Ollama, delete the output directory, and
run again.

Per generation it prints the item id and seed, the sentence, the stage output,
`method` (`model`, `substituted`, or `passthrough`), `unresolved`, the fallback
reason, and the seconds. At the end it prints the automatic part of the rule and
writes into `--out`: `results.json` (every generation with the raw model reply),
`report.md`, `review-sheet.md` (the blind sheet), and `review-answers.toml` (the
answer template; an existing one is not overwritten).

Fallback reasons: `placeholder_left` (the reply still holds a placeholder text),
`literal_changed` (the text outside the values differs from the sentence in any
way: a word, a digit, punctuation, case, markdown, quotes, a moved or lost value),
`bad_slot` (a value's place holds something that is not a form of that original:
another word, a different number of words, reshaped digits or separators),
`no_usable_reply` (backend error, timeout, blank or non-text reply); several
joined with `+`. A sentence over the limits (8 placeholders, 1000 characters) is
not sent and does not occur in the 30 items.

## 3. What is measured automatically and what needs you

Automatic (printed by `run`, from `results.json`):

- validation pass rate: the share of the 60 generations the stage kept from the
  model (`method` is `model`: all three deterministic checks passed). Rule: at
  least 0.90.
- alteration rate: among generations with a usable model reply, the share where
  the text outside the restored values was changed (`literal_changed`). Rule: at
  most 0.05.
- the fallback reasons, counted.

Needs you (case correctness, the third part of the rule): the sentence is
checked for the right Russian case of the inserted values, which only a reader
can judge. Open `review-sheet.md`: per item it shows two sentences, X and Y, in a
random order (the order is fixed by `REVIEW_RNG_SEED = 20261018` in
`manual/personal_proxy/restoration.py`, the spike's). One of them is the model's
raw reply of the first seed (`19210`), the other the plain substitution of the
base forms. Without telling which is which, open `review-answers.toml` and set
`x` and `y` of every item with the three-level scale below (the sheet repeats
it at its top). This scale is the owner's decision of 2026-10-22 and differs from
the spike's two-level `ok` / `bad`.

- `ok`: fully right; the case and form of the inserted values are right.
- `mid`, or an empty string `""`: the meaning comes through, but it is worse than
  `ok`; not critical.
- `bad`: the case is critically wrong.

One empty side next to a filled one counts as `mid`. If BOTH sides of an item are
middle, write `mid` explicitly: an item with both `x` and `y` empty cannot be told
from an unfilled one, and `score` refuses it (exit code 2, naming the item).
Also mark a sentence `bad` if, compared with the plain sentence, it has a changed
digit, a duplicated or missing inserted value, or added markdown or quote marks.
A model reply that the stage rejected is shown on
the sheet too (it is the raw reply), so you judge the model's case quality
independently of validation; the rule counts it only where validation also
passed. Where there was no usable reply the sheet says
`(no usable model reply)`.

Then:

`python -m manual.manual_check_restoration_stage --out manual_check_restoration_stage_out score`

It refuses to score (exit code 2) while an item has both marks empty, a mark
other than `ok`, `mid`, `bad`, or an item is missing. It prints and writes
`report.md` with the three numbers and the decision: `KEEP the model branch`, or
`NOT SUPPORTED: remove the model branch, keep substitution` with the failed
conditions. The case condition is: among the items where the plain substitution
is not `ok` (`mid` or `bad`), the share where the stage's model output is `ok`
and was validated (`method` is `model`) must be at least 0.80
(`MIN_FALLBACK_BEATEN_SHARE`); if every substitution is `ok` the case benefit is
unmeasured and the decision is `NOT SUPPORTED` with that reason.

`report.md` also lists, for information only (the decision does not use them):
the counts of `ok` / `mid` / `bad` for the model output and for the substitution,
the number of items where the model is strictly better than the substitution
(`ok` > `mid` > `bad`), and the items where the model is worse.

## What to report

`manual_check_restoration_stage_out/report.md`; any generation whose `method` is
not `model` with its fallback reason and sentence; any line with `WARNING:`; the
seconds per generation for the second and later items; anything that looked wrong
in the stage output (a changed word, a lost or duplicated value).
