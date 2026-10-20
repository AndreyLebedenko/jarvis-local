# Task v2.1.0-1: locality contract, capability flag, and config

Status: Open.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 1 (Size: S-M).

## Summary

Make the external-inference capability exist as an explicit, off-by-default,
per-run act, without any pipeline behind it: amend the runtime locality contract,
add the `--personal-proxy` flag, add the `[personal_proxy]` settings (including the
settings of the later stages), and add the seam through which a turn can later
report `DataLocality.EXTERNAL`.

## Decisions of the owner (2026-10-20, planning questions of this task)

- No `RunMode.PERSONAL_PROXY` and no `ControlAction` verdict table in this task.
  The run mode and its table are designed by task 9 with the pipeline.
- `DataLocality.EXTERNAL` is not shown anywhere in this task. The task adds only
  the seam (a way to report a turn as external and return to local afterwards);
  task 9 calls it. Until then the indicator is `LOCAL`, as today.
- `--personal-proxy` is mutually exclusive with `--mcp-mode` (`parser.error`),
  requires `--status-console` (as `--debug` does), and requires a non-empty
  `[personal_proxy].endpoint`; otherwise startup ends with an error, never a
  silent fall back to local. The launcher (`launcher/runtime.py`) is not touched.

## Boundary

In scope:

1. `PROJECT.md`: amend the runtime locality contract (top of the file) with the
   external-inference capability: explicit per-run flag plus configured endpoint,
   off by default, core orchestration and Ollama inference still local, the
   capability sends only a sanitized text, reported as `DataLocality.EXTERNAL`
   for a turn answered externally. With the flag absent the runtime is
   byte-identical to v2.0 behavior. Update the "Tooling notes" wording in
   `CLAUDE.md` only if it contradicts the amendment (it should not need a change).
2. `core/config.py` + `config.example.toml`: a `[personal_proxy]` section
   (`PersonalProxySettings`), parsed and validated like the existing sections,
   every default documented in `config.example.toml` with the reason:
   - `endpoint = ""` (OpenAI-compatible chat URL), `model = ""`,
   - `api_key_env = "JARVIS_PERSONAL_PROXY_KEY"` (the variable name, never a key),
   - `dry_run = true` (safe default: nothing is sent until the owner turns it off),
   - `topics_file = "personal_proxy_topics.txt"` (relative to the working
     directory, local-only; the default path is added to `.gitignore`),
   - `request_timeout_seconds = 60`, `connect_timeout_seconds = 10`,
   - `confirmation_timeout_seconds = 20`,
   - `doubt_min_listed = 1` (the judge's list of doubts; a candidate, confirmed by
     task 8),
   - speech-to-text: `stt_model = "large-v3-turbo"`, `stt_device = "cuda"`,
     `stt_language = "ru"`, `stt_weak_word_probability = 0.5`.
   An invalid value (non-positive timeout, probability outside [0, 1], unknown
   device, empty model/language) is a config error with the key named, as for the
   other sections. The key itself is never a config field.
3. `app.py` `parse_args()` and startup: the flag and the rules above. The settings
   check (non-empty endpoint, non-empty `model`) runs before anything starts.
   With the flag the application starts as a normal (`RunMode.NORMAL`) run; it
   does not call the external endpoint (nothing in this task can).
4. The seam: a small, tested object/function that sets the transport's
   `DataLocality` to `EXTERNAL` for the duration of one turn and restores `LOCAL`
   afterwards (also when the body raises), using the existing
   `ui/transport.py` `set_data_locality`. No caller outside tests.
5. Tests for all of the above (pure logic; no Ollama, no network).

Out of scope: any pipeline stage, the HTTP client, the gate, the STT engine,
`RunMode`/`ControlAction` changes, UI changes, the launcher, journal changes.

## Acceptance criteria

- [ ] `PROJECT.md` names the capability and states the two guarantees (off by
      default; byte-identical to v2.0 without the flag).
- [ ] Without `--personal-proxy` nothing changes: existing tests pass untouched;
      a test shows the default `PersonalProxySettings` and a missing section do not
      enable anything.
- [ ] `--personal-proxy` with `--mcp-mode` fails at `parse_args`; without
      `--status-console` fails at `parse_args`; with an empty `endpoint` or `model`
      the run ends with a clear error and no component starts.
- [ ] Every `[personal_proxy]` key is documented in `config.example.toml`; every
      invalid value is rejected naming the key; no field holds an API key.
- [ ] The locality seam reports `EXTERNAL` inside the scope, `LOCAL` after it
      (including after an exception); no production caller.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
