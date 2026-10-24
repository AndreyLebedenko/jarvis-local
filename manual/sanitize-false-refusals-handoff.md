# Human-run handoff: false refusals of the local sanitize model (task v2.1.0-10e)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by a
human: it needs the live local Ollama endpoint and a GPU. The agent prepared it and
ran none of it.

What it answers: how often does the local sanitize stage refuse or break a harmless
request (dates, numbers, places, news, how-to, general knowledge, short and long,
Russian and English), and how many of those does the one retry rescue. The same 40
requests go through the real stage `sanitize_with_retries` in
`src/jarvis/personal_proxy/sanitize/sanitize.py`, on the production backend
(`OllamaCheckBackend`), the production settings and the production prompt, twice
(`--repeats`, default 2), each time once with the retry on and once with it off.

Origin: on 2026-10-23 two harmless requests were refused with no topics file present:
`bad_placeholder` on "tell briefly what a relay is" (request `H01`) and a refusal with
the reason `DATE` on the Wednesday, 21 October question (requests `H03` and `H27`).

Documentation debt, stated on purpose: the user documentation of the whole feature
(README, config guide) is task v2.1.0-12 and does not exist yet. This handoff does not
rely on it; every command, key and default it needs is named below with its source.

Privacy: no request leaves the machine. Only the local Ollama endpoint is called; no
external endpoint, API key or `[personal_proxy].endpoint` is needed. The request texts
are fixed, invented and harmless (`manual/personal_proxy/false_refusals.py`). The report
file holds identifiers and counts only, no request text and no model output.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_sanitize_prompts.py`,
`tests/test_personal_proxy_sanitize_retry.py`,
`tests/test_personal_proxy_force_hint.py`,
`tests/test_manual_false_refusals.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. The script reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`) through `--config`;
  a key that is absent means the code default.
- Keys the run depends on, with code defaults (`BackendSettings` and
  `PersonalProxySettings`, `src/jarvis/core/config.py`): `[backend].endpoint`
  (default `"http://localhost:11434"`), `[personal_proxy].check_model` (default
  `"gemma4:12b"`), `check_num_ctx` (default `8192`), `check_temperature` (default
  `0.618`) and `topics_file` (default `"personal_proxy_topics.txt"`, relative to the
  working directory; a missing file at the default path means no topics). Check
  `config.toml` for overrides of these before the run; whatever it says is what is
  measured, which is the point.
- The script: `manual/manual_check_sanitize_false_refusals.py`. Its subcommands:
  `run` (calls the model) and `show` (prints request texts by id, no model call).
  Options of `run`: `--config PATH`, `--repeats N` (default 2), `--no-topics`
  (measure with an empty topics list whatever the topics file holds, so the start state
  does not matter), `--only H01,H02` (a subset), `--out DIR` (default
  `manual_check_sanitize_false_refusals_out`, holds `report.md`).
- The two arms: `retry-on` uses the production retry count `SANITIZE_RETRIES` (1,
  `src/jarvis/personal_proxy/sanitize/sanitize.py`); `retry-off` uses 0. In `retry-off` a
  refusal while the topics list is empty is reported as `unexpected_refusal`, the same
  class the production stage reports after a second such refusal.
- Outcome labels in the report: `send` (a valid sendable result), `refused` (a refusal
  while topics exist), and the failure classes of `SanitizeFailureClass`
  (`src/jarvis/personal_proxy/sanitize/sanitize_result.py`): `backend_failed`, `empty`,
  `no_json`, `extra_prose`, `missing_field`, `wrong_type`, `bad_verdict`,
  `empty_sanitized_text`, `bad_placeholder`, `empty_mapping_value`,
  `unexpected_refusal`. Any label other than `send` on a harmless request is a false
  refusal or a broken answer.

## Preparation (state-independent)

1. Start Ollama if it is not running (`ollama serve`) and check that the model named by
   `[personal_proxy].check_model` is installed: `ollama list` must show it (default
   `gemma4:12b`). If it is not listed, `ollama pull gemma4:12b`.
2. Close the Jarvis application if it runs, so the model has the GPU to itself.
3. Without the model: `python -m manual.manual_check_sanitize_false_refusals show
   --only H01,H03` must print the two origin requests. If it fails, stop and report the
   error text.

## Part 1: no topics (the case where the false refusals were seen)

Run:

    python -m manual.manual_check_sanitize_false_refusals run --no-topics --out manual_check_sanitize_false_refusals_out/no-topics

It prints one line per call (`repeat N ID arm: label`) and then the report, also
written to `manual_check_sanitize_false_refusals_out/no-topics/report.md`. Expect
at least 160 calls (more when the retry fires), a few seconds each (an estimate, not measured). A cold model load
makes the first call slow.

Expected shape of the report: `topics: none`; per arm `trials: 80`; counts per label;
for `retry-on` also `retried:` and `rescued by the retry:`; `example ids:` with up to
three ids of requests that did not send.

## Part 2: with the real topics file (optional)

Only if your `topics_file` holds topics you use. Run the same command without
`--no-topics`:

    python -m manual.manual_check_sanitize_false_refusals run --out manual_check_sanitize_false_refusals_out/with-topics

If the topics file is missing or holds only blank lines, the report says
`topics: none` and Part 2 equals Part 1 (the topics file has no comment syntax, so a line
starting with `#` counts as a topic). With topics, the report says `topics: present`. A `refused` label here may be a legitimate
refusal by one of your topics; judge each example id.

## Inspecting an example

For each example id in a report, read the request: `python -m
manual.manual_check_sanitize_false_refusals show --only ID`. To see whether it repeats,
run `run --no-topics --only ID --repeats 5 --out manual_check_sanitize_false_refusals_out/one`.

## What to send back

The contents of each `report.md` (identifiers and counts only) and, for the example
ids you inspected, one line each: whether the request was really harmless.

Pass criteria for the task: the retry exists to cut the failures; the numbers decide
whether it is enough, there is no fixed threshold. Report if `retry-on` still shows
more than a few `unexpected_refusal` or malformed labels, or if `backend_failed`
appears (Ollama problem, not a sanitize problem).
