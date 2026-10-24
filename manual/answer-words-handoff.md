# Human-run handoff A: short spoken answers (task v2.1.0-8)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human at the microphone: it loads Whisper (GPU) and records your voice through
the production capture path. The agent prepared it and ran none of it.

What it answers: how reliably do one-word answers ("yes", "no", "send", "stop")
survive the speech guard and the speech engine? A speech-guard rejection or a
wrong text becomes the class `unclear` (safe: nothing is sent). The numbers
decide whether the answer vocabulary needs more variants, and whether any
non-"yes" phrase is ever heard as a "yes" (a false yes; that is the one number
that matters for safety).

This handoff does not rely on `PROJECT.md` or the README for the confirmation
exchange (their update is not part of the task that prepared it). Every default
it uses is cited below. It does rely on the speech-to-text stage of task
v2.1.0-3 being installed: its prerequisites are step 1.

Scope note: this handoff runs the speech stage and the classifier only, not the
transcript check. In the real flow a failed check (every fallback reason except
`EMPTY_TRANSCRIPT`, `src/jarvis/personal_proxy/check/transcript_check.py`) makes
`would_ask` true, so such requests also reach the confirmation question and
the answer path measured here; the share of questions is measured by handoff B
(`manual/doubt-trigger-handoff.md`), where a failed check counts as asked.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_confirmation_vocabulary.py`,
`manual/tests/test_manual_answer_words.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs (the one where `pip install -e .` was done,
  README.md "Manual installation"). The tool reads `config.toml` from the current
  directory (option `--config`, default `config.toml`); a missing file means the
  code defaults. It prints the effective values it uses on its first line; copy
  that line into your report, because the values may differ from the defaults
  quoted here.
- `[personal_proxy]` keys used (code defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `stt_model = "large-v3-turbo"`, `stt_device = "cuda"` (the other value is
  `"cpu"`), `stt_language = "ru"`, `stt_min_speech_seconds = 0.3` (the speech
  guard: a take with less speech than this is rejected and never reaches
  Whisper).
- `[vad]` keys used (`VadSettings`, same file): `threshold = 0.5` (a 32 ms
  Silero window counts as speech at or above it), `request_end_pause_seconds =
  2.0` (a take ends after this much silence, so each take returns about 2 s
  after you stop speaking), `min_chunk_seconds = 3.0` (a shorter take is padded
  with faint noise, `padding_noise_rms = 0.002`, up to this length; padding does
  not count as speech).
- `[microphone]` keys used (`MicrophoneSettings`, same file): `device = ""`
  (the system default input) and `host_api = ""`. Set `device` in `config.toml`
  only if the default input is not the microphone you want.
- The phrases and the expected class of each are the constant `PHRASES` in
  `manual/personal_proxy/answer_words.py`: `да` (yes), `нет` (no), `отправляй`
  (yes), `стоп` (no), `yes` (yes), `no` (no), `да, но исправь` (unclear, a
  sentence containing a yes word), `сегодня хорошая погода` (unclear, a neutral
  phrase). The vocabulary and the classifier are `YES_PHRASES`, `NO_PHRASES` and
  `classify_answer` in `src/jarvis/personal_proxy/confirmation/confirmation_vocabulary.py`.
- Repetitions: `REPETITIONS = 10` in `manual/personal_proxy/answer_words.py`, so
  80 takes in all. The option `--repetitions N` changes it.
- The Whisper settings are fixed in `src/jarvis/personal_proxy/stt/stt_whisper.py`
  (`BEAM_SIZE = 5`, `COMPUTE_TYPE_BY_DEVICE = {"cuda": "float16", "cpu":
  "int8"}`). The tool calls the same guarded function the production stage uses,
  `transcribe_guarded` in `src/jarvis/personal_proxy/stt/guarded_transcription.py`.

## 1. Prerequisites

1. The speech stage works: `python -m pip install -r requirements-stt.txt` and
   `python setup_stt_model.py` were done once (steps 2 and 3 of section "1.
   Install and fetch the weights" of `manual/stt-stage-handoff.md`, with network
   access). `python -c "import jarvis"` must succeed from the repository root;
   if not, run `python -m pip install -e .` there first.
2. Close Jarvis and any program using the microphone or the GPU. The tool opens
   the input device itself.
3. Sit where you normally sit when talking to Jarvis, at your normal distance
   and volume, in the room's normal noise.

## 2. Run

`python -m manual.manual_check_answer_words run`

(State-independent: it needs nothing but the repository and your `config.toml`,
if any.) For each of the 8 phrases, 10 times, the tool prints `Press Enter, then
say: <phrase>`. Press Enter, say the phrase once in your normal voice, and stay
silent. After about 2 s of silence the take ends and the tool prints one line:
what you were asked to say, the Whisper text, the class (`yes`, `no` or
`unclear`) against the expected class, the seconds of speech the guard measured,
and `guard: ok` or `guard: REJECTED`. If no take arrives within 90 s
(`TAKE_TIMEOUT_SECONDS` in `manual/personal_proxy/recorder.py`) the tool says so
and counts the take as rejected. Say the phrases naturally; do not exaggerate
or whisper. The first take includes warm-up and is not special; do not skip it.

At the end the tool prints a table per phrase: takes, how many were classified as
expected, the counts `yes/no/unclear`, how many the guard rejected, the number of
false yes, and the least and mean seconds of speech.

## What to report

1. The first line the tool printed (the effective settings).
2. The final table, whole.
3. Every take where the Whisper text surprised you (empty, another language,
   invented words), with the phrase you said.
4. Above all: any false yes (a yes heard for `нет`, `стоп`, `no`, `да, но
   исправь`, or the neutral phrase). The expected number is 0 of 50 non-yes takes.

Reading it: for a yes phrase, the share `as expected` is how often the real
answer works; the rest is lost safely as `unclear`. If one phrase is often
rejected by the guard, its least speech seconds against
`stt_min_speech_seconds = 0.3` shows whether the guard is the cause. The
decision to add vocabulary variants or to change the guard belongs to the owner;
this run only measures.
