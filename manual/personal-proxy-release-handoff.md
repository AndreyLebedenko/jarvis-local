# Human-run release handoff: personal proxy, v2.1.0 (task v2.1.0-12)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by a human:
it needs the microphone, the speakers, the GPU, the live local Ollama endpoint and the
recorded spike corpora. The agent prepared it and ran none of it. It does not depend on
the per-task handoffs of tasks 5-10f; every key, command and default it needs is named
below with its source. The user documentation it relies on is the section "Personal proxy
mode" of `README.md` (English) and `README.ru.md` (Russian), which this task wrote.

What it answers, for `--personal-proxy`: (1) does a spoken or typed request run the whole
pipeline in dry run and for real; (2) does the confirmation exchange send only on a clear
yes and send nothing on no, silence or interrupt; (3) does the deterministic gate block
each category of identifier and the topics file; (4) is the answer restored in the right
Russian case; (5) does silence send nothing; (6) do the Journal and the Status Console
label and keep the exchange as designed; (7) the recall report: how much of the labeled
sensitive data still leaks, how often the system asks, how often it wrongly refuses.

Privacy: no real provider and no real key is needed. The "external" model is Ollama itself
on this machine (step 1.3). Use only invented text; the corpora hold invented identities.
Your Journal will hold the heard texts of this run whole (by design); delete the test
sessions afterwards if you want (Journal view, session menu "...").

Automated counterpart already green: `python -m pytest`, `ruff check`, `ruff format --check`.

## Literal references

- Every command runs from the repository root, in the environment where `python -m jarvis`
  normally runs. Jarvis reads `config.toml` from the current directory
  (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is absent means the code
  default (`config.example.toml` comments every key).
- Start command (`parse_args`, `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`. `Jarvis.cmd` adds `--status-console`
  itself, so `Jarvis.cmd --personal-proxy` is the same run. The flag needs `--status-console`
  and excludes `--mcp-mode` and `--debug`.
- `[personal_proxy]` keys used (defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`): `endpoint` (default `""`, required), `model` (default `""`,
  required), `api_key_env` (default `"JARVIS_PERSONAL_PROXY_KEY"`, the NAME of the
  environment variable that holds the key), `dry_run` (default `true`), `topics_file`
  (default `"personal_proxy_topics.txt"`, relative to the working directory),
  `public_names_file` (default `"personal_proxy_public_names.txt"`, relative to the working
  directory; one name per line, UTF-8, blank lines and lines starting with `#` ignored, 8000
  characters at most; added by task v2.1.0-12a),
  `confirmation_timeout_seconds` (default `20`), `doubt_min_listed` (default `1`),
  `check_model` (default `"gemma4:12b"`), `check_num_ctx` (default `8192`), `stt_device`
  (default `"cuda"`).
- Hotkeys (`HotkeySettings`, `src/jarvis/core/config.py`; overridable in `[hotkeys]` of
  `config.toml`; if that section overrides any, use the bindings it shows): shutdown
  `Ctrl+Alt+Q`, interrupt `Ctrl+Alt+I`, microphone sleep `Ctrl+Alt+M`. In this mode these
  three are the only bound hotkeys.
- The window text is in the language of `[ui].language` (default `"en"`); this handoff
  names the English texts (`src/jarvis/ui/status_console_ui/strings.js`).
- Gate categories and their English names (`GateCategory`,
  `src/jarvis/personal_proxy/common/findings.py`; names in
  `src/jarvis/personal_proxy/reporting/service_texts.py`): e-mail, phone, payment card, IBAN,
  long number, access key, password, street address, text from the topics file.
- The `/force` command (`COMMAND_TABLE`, `src/jarvis/personal_proxy/request/request_commands.py`):
  a typed request whose first token is `/force` or `/f` is sent once without the local
  model stages; the deterministic gate still runs.
- Report files are written under the repository root in gitignored `manual_check_*_out`
  directories and `personal_proxy_corpus*_wavs/`.

## 1. One-time preparation (state-independent)

1. Speech engine: `python -m pip install -r requirements-stt.txt`, then
   `python setup_stt_model.py` once (needs the network). Expected last line: "Done. The model
   is cached locally".
2. Ollama is running at `[backend].endpoint` (default `http://localhost:11434`) and
   `ollama list` shows `gemma4:12b` (`ollama pull gemma4:12b` otherwise).
3. Make the `[personal_proxy]` section of `config.toml` contain exactly these keys:

   ```
   [personal_proxy]
   endpoint = "http://localhost:11434/v1/chat/completions"
   model = "gemma4:12b"
   api_key_env = "JARVIS_PERSONAL_PROXY_KEY"
   dry_run = true
   topics_file = "personal_proxy_topics.txt"
   public_names_file = "personal_proxy_public_names.txt"
   confirmation_timeout_seconds = 20
   doubt_min_listed = 1
   ```

   `endpoint` is Ollama's own OpenAI-compatible route, a stand-in for the external model
   (`http` is allowed on `localhost`). Nothing leaves the machine.
4. In the terminal that starts Jarvis (PowerShell): `$env:JARVIS_PERSONAL_PROXY_KEY =
   "handoff-test"`. The name must equal `api_key_env`.
5. Create `personal_proxy_topics.txt` in the repository root (UTF-8, overwrite) with one
   line: `проект Лазурь`
6. Close any running Jarvis (`Ctrl+Alt+Q`) and any other GPU-heavy program. Note how many
   sessions the Journal view lists now: N0.

## 2. Start, idle and refused start

1. `python -m jarvis --status-console --personal-proxy`
2. Expected: the Status Console opens; the orb shows "Warming up the model...", then
   "Waiting for a request"; the "listening" cue sounds once; the top bar shows the badge
   "PERSONAL PROXY" and the model `gemma4:12b`; the events panel shows "Personal proxy
   ready: the check model is warmed up"; the Status view shows a "DRY RUN - nothing is
   sent" indicator and a "Personal proxy" panel.
3. Close it (`Ctrl+Alt+Q`) and run
   `python -m jarvis --status-console --personal-proxy --debug`. Expected: no window; the
   terminal prints "--personal-proxy cannot be combined with --debug"; exit code 2
   (`echo $LASTEXITCODE`). Then start again with 2.1.

## 3. Dry run (config of step 1.3: `dry_run = true`)

1. Say: "Позвони Марине Крыловой по номеру восемь девятьсот двенадцать триста сорок пять
   шестьдесят семь восемьдесят девять".
2. Expected: ONE block "Dry run - nothing was sent" with "Speech engine text", "Checked
   text", "Would ask", "Sanitized text" (placeholders such as `<PERSON_1>`), "Mapping (stays
   on this machine)", "Verdict", "Outbound gate" and "Exact payload". Nothing is spoken and
   the locality badge stays "Local". Report what the gate line shows.
3. Type "Расскажи коротко, что такое реле" in the Journal view's dock and press Send. Expected:
   a dry-run block whose "Speech engine text" is empty and whose payload holds your sentence.
4. Silence: tap the desk for a second. Expected: no block, or a single notice that no speech
   or text was recognized; nothing is sent; no "Heard" block.
5. Open the Journal view. Expected: the session count is still N0 (a dry run writes nothing).

## 4. Real send and restoration (set `dry_run = false`, restart with 2.1)

1. Say: "Расскажи коротко, что такое реле". Expected, in order: a "Heard" block with decision
   "Sending without a question", a "Sent to the external model" block (the system prompt
   folded behind a label), then "Answer (external model)" sentences appearing one by one and
   spoken one at a time. While the answer streams the locality badge reads "External backend"
   and returns to "Local" at the end.
2. Restoration. Type in the dock: "Напиши Марине Крыловой короткое письмо с благодарностью
   за вчерашнюю встречу". Expected: the "Sent" block holds a placeholder instead of the
   name (for example `<PERSON_1>`), the answer shows the name restored in the right case
   (for example "Марине Крыловой"), no `<...>` placeholder is visible. If the block says
   "Plain substitution - the wording may be rough" or "Some placeholders could not be
   resolved", report it; the stand-in model may not keep placeholders, which is not a
   defect of Jarvis. Repeat once with another Russian request that names a person, a city
   and an organization, and report each restored phrase.

## 5. Confirmation exchange

1. Say a request with an address spelled letter by letter, for example: "Напиши письмо на
   адрес i v a n p e t r o v собака g m a i l точка c o m". The check asks on roughly 13 of
   60 labeled recordings, so a question is not certain; try other spelled-out addresses until
   one comes (up to ten tries). When it comes, expected: a "Heard" block with decision
   "Asking you to confirm before sending" showing the WHOLE heard text; a voice names what to
   check; the microphone is off while it speaks and on again after.
   - 5a. Answer by voice "да". Expected: sent as in 4.1.
   - 5b. Repeat and answer "нет". Expected: nothing is sent; an offer to correct by text or
     dictate again is spoken and shown; no "Sent" block.
   - 5c. Repeat and stay silent for 20 seconds. Expected: as 5b.
   - 5d. Repeat and type "да" in the Journal dock, then Send. Expected: sent.
   - 5e. Repeat and answer something unclear ("может быть"). Expected: as 5b.
   - 5f. Repeat and press `Ctrl+Alt+I` while the question waits. Expected: as 5b.
2. Interrupt during the answer: start 4.1 and press `Ctrl+Alt+I` while it is spoken.
   Expected: speech stops at once, a notice that the request was interrupted appears, the
   badge returns to "Local", and your next request is heard.
3. Microphone sleep: press `Ctrl+Alt+M`; the next utterance is ignored; press it again; the
   next utterance is a request.

## 6. Gate blocks and the topics file

For each row type the message in the Journal dock and press Send. The prefix `/force` skips
the local model stages, so the deterministic gate is the only guard, and a block is the
expected result. Each time expect: a notice "Blocked by the check, nothing was sent:" naming
the category and the position ("message 1, characters A-B"), no "Sent" block, and the notice
and the Status "Last stop:" line never show the value.

| Message | Expected category |
|---|---|
| `/force Привет, вот данные: anna.lebedeva@example.com спасибо` | e-mail address |
| `/force Привет, вот данные: +7 (915) 234-56-78 спасибо` | phone number |
| `/force Привет, вот данные: 4539 1488 0343 6467 спасибо` | payment card number |
| `/force Привет, вот данные: GB82 WEST 1234 5698 7654 32 спасибо` | IBAN |
| `/force Привет, вот данные: 4539 1488 0343 6468 спасибо` | long number |
| `/force Привет, вот данные: sk-proj-abcdEFGH1234ijklMNOP5678 спасибо` | access key |
| `/force Привет, вот данные: пароль: Zk9#mQ2x спасибо` | password |
| `/force Привет, вот данные: улица Ленина 5 спасибо` | street address |
| `/force Расскажи про проект Лазурь` | text from the topics file |

Then, without `/force`, type: "Расскажи про проект Лазурь". Expected: the request is refused
(a notice "The request was refused, nothing was sent." with a reason) or blocked by the gate;
nothing is sent. If it is sent with the topic replaced by a placeholder, report that: the
topic was not refused.

Last, a forced harmless request: `/force Расскажи коротко, что такое реле`. Expected: sent;
the "Sent" block and the Journal show "FORCED: sent without the local checks".

## 7. Journal and Status Console labels

1. Journal view, newest session. Expected: its title is "Personal proxy session" with a
   start time; an outline arrow-out-of-a-box icon and an amber left edge on the session and on
   its messages; message kinds labeled "Personal proxy - request", "Personal proxy - sent",
   "Personal proxy - external answer", "Personal proxy - notice". The spoken request shows
   "Spoken request; the recording is stored with it.".
2. Search the Journal for a word from your spoken request, for example "реле". Expected: hits
   from the proxy session carry the proxy labels, not "Jarvis".
3. Rename the session: "..." menu on it, "Rename", type `Release check`, Enter. Expected: the
   list, the feed header and search results show it. Clear the field and save: the automatic
   title returns. Rename again to `Release check`.
4. "New context" (Journal view). Expected: a new proxy session starts when the next request
   arrives; the old session is unchanged. Say a request.
5. Close Jarvis (`Ctrl+Alt+Q`) and start it again (2.1). Expected: both sessions are listed,
   the title `Release check` persisted.
6. The session count is now N0 + 2 or more, and none of the new sessions holds a "Mapping" or
   a placeholder-form answer anywhere.

## 8. Shutdown and logs

1. While idle press `Ctrl+Alt+Q`. Expected: the window closes and the process exits.
2. Start again, begin an answer (4.1) and press `Ctrl+Alt+Q` while it is spoken. Expected:
   speech stops, the process exits, no traceback.
3. Open the newest log under `logs/` (`[logging]`, `LoggingSettings`). It must hold no sentence
   you said, no heard text, no sanitized text, no answer text and no title (only counts, kinds
   and fixed messages). Report any line that does.

## 9. Recall report (labeled corpora)

Close Jarvis first. These tools read the recorded corpora of the spikes: the directories
`personal_proxy_corpus_wavs/` and `personal_proxy_corpus_v2_wavs/` (44 and 30 invented
utterances) and the stored outputs `manual_check_confidence_out/`,
`manual_check_confidence_v2_out/` and `manual_check_text_sanitize_out/`. If any of them is
missing, stop and tell the owner: re-recording is `manual/manual_record_personal_proxy_corpus.py`
and is not part of this handoff.

9.1 Leak rate of the sanitize pass, offline (no model, no GPU):

    python -m manual.manual_check_text_sanitize score --v2-out manual_check_confidence_v2_out

The report prints a decision table and, per arm and group, validity, leak rate, mapping
error rate, preservation and false refusals of the stored calls of spike v2.1.0-11 (the
prompt it used is kept equal to the production prompt by
`tests/test_personal_proxy_sanitize_prompts.py`). The headline is the first table, arm G.
The recorded reference is: validity 1.000, leak rate 0.052, mapping error rate 0.037,
meaning preservation 0.865, false refusal rate 0.235 (limit 0.15, accepted by the owner).

9.2 Asked share and covered errors, live (Whisper on the GPU and the live Ollama):
create `config.handoff-b.toml` in the repository root (overwrite; it is gitignored) with

```
[backend]
endpoint = "http://localhost:11434"
flash_attention = true
kv_cache_type = "q8_0"

[personal_proxy]
doubt_min_listed = 1
```

then run

    python -m manual.manual_check_doubt_trigger --config config.handoff-b.toml run

(`--config` goes before `run`). It checks 60 recordings, which takes a few minutes, and ends
with counts and a verdict: `keep` (asked share at most 0.27, at least 6 of 7 real errors
asked about, at least 4 of 7 naming the wrong fragment), `numbers_to_owner` or
`not_comparable`. Do not change `doubt_min_listed` and run again whatever the verdict.

9.3 False refusals of harmless requests (live Ollama, 40 requests, both retry arms):

    python -m manual.manual_check_sanitize_false_refusals run --no-topics --out manual_check_sanitize_false_refusals_out/no-topics

The report `manual_check_sanitize_false_refusals_out/no-topics/report.md` holds, per arm
(`retry-on`, `retry-off`), `trials: 80`, counts per label (`send` is correct, any other label
on a harmless request is a false refusal or a broken answer), `retried:` and `rescued by the
retry:`. The recorded reference before the retry existed: 23.5% false refusals.

## 10. Public names file (task v2.1.0-12a)

Close Jarvis first. Needs the live local Ollama (Jarvis is not started). The key
`[personal_proxy].public_names_file` is read from `config.toml` in the repository root
(`DEFAULT_CONFIG_PATH`); absent means `personal_proxy_public_names.txt`
(`PersonalProxySettings`, `src/jarvis/core/config.py`). The user documentation is step 6 of
"Personal proxy mode" in `README.md`.

10.1 Create or overwrite the names file (state-independent). In PowerShell, from the
repository root:

    [System.IO.File]::WriteAllText("$PWD\personal_proxy_public_names.txt", "Эйнштейн", (New-Object System.Text.UTF8Encoding $false))

The file now holds exactly one line, `Эйнштейн`, in UTF-8 without a byte order mark. If your
`config.toml` sets `public_names_file` to another path, write to that path instead.

10.2 The Einstein request, names file present (`build_parser`,
`manual/manual_check_sanitize_raw_reply.py`; flags `--config PATH` default `config.toml`,
`--repeats N` default 1, `--no-topics`, `--no-public-names`):

    python -m manual.manual_check_sanitize_raw_reply "Правда ли, что Эйнштейн отстаивал идею эфира" --repeats 5

It prints five raw replies of the local model, each after a line "--- attempt N: accepted:
send" (or a failure label). Expected: in the `sanitized_text` of every accepted reply the
word `Эйнштейн` (in any case form) stays as said, there is no `<PERSON_1>` for it, and the
`mapping` has no entry for it. Report how many of the five replies keep the name. The rule
is a request to the model, not a guarantee: a reply that still replaces the name is not a
crash, report it with its text.

10.3 Control, names ignored (same script, flag `--no-public-names`):

    python -m manual.manual_check_sanitize_raw_reply "Правда ли, что Эйнштейн отстаивал идею эфира" --no-public-names --repeats 5

Expected: the name is replaced by a placeholder such as `<PERSON_1>` in most replies (this
is the problem the file solves). Report how many of the five.

10.4 False refusals with a non-empty names file (the file of 10.1 present; the names are
read unless `--no-public-names` is given; 40 requests, both retry arms):

    python -m manual.manual_check_sanitize_false_refusals run --no-topics --out manual_check_sanitize_false_refusals_out/public-names

The report `manual_check_sanitize_false_refusals_out/public-names/report.md` has the same
fields as 9.3. Compare with the `no-topics` report of 9.3 and report both rates.

## What to report

For each step: what you saw against what is expected above, in your words, with the exact
text of any notice or error. Report first anything that was SENT that should not have been (a
"Sent" block after a "no", silence, timeout, interrupt or a gate block), any value from the
mapping or any heard text in a log line, a microphone that stayed off, and a started proxy
after a failed start. From part 9 report these numbers: the sanitize leak rate and validity
(9.1); the asked share, the covered errors, the wrong-fragment count and the verdict (9.2);
the false-refusal rate and `rescued by the retry` for `retry-on` and `retry-off` (9.3). From part 10 report: how many of
the five replies keep `Эйнштейн` with the file (10.2) and with `--no-public-names` (10.3), and
the false-refusal rate with the names file (10.4). The owner records the numbers in
`PROJECT.md` ("Architecture v2.1.0", honest limits).
