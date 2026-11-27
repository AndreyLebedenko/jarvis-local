# Task v2.1.1-3: The proxy follows the response mode

Status: Completed.

Story: `tasks/done/story-v2.1.1-proxy-speech-modes.md`, task 3 (Size: M).

## Problem

In `--personal-proxy` mode the response-mode switch does nothing: the hotkey is not bound
(`_personal_proxy_background_work`, `app.py`), the Status Console control is refused
(`PERSONAL_PROXY_VERDICTS[SET_RESPONSE_MODE]` in `core/run_mode.py`), and the proxy never reads
`ResponseModeState` (created unconditionally in `build_app`, `app.py`). The following tasks
(Voice, Text+Voice) need the live mode per request.

## Findings before the change (to verify first, report in the outcome)

- `[response].mode` default is `"text"` (`core/config.py`, `ResponseSettings.mode`), which is
  today's proxy behavior; an unchanged config keeps the proxy in Text.
- Verify that the bus handlers that follow `ResponseModeChanged` (`_on_response_mode_changed`
  in `app.py`, the transport subscription) are live in proxy mode. If they are not, stop and
  report (story stop condition).

## Design

1. `SET_RESPONSE_MODE` becomes ALLOWED for `PERSONAL_PROXY`; the rest of the refused set is
   unchanged. `tests/test_personal_proxy_run_mode.py` pins the refused set and is updated.
2. `_personal_proxy_background_work` binds the same hotkey listener as the normal path
   (`run_response_mode_hotkey_listener`, `[hotkeys].response_mode_toggle`).
3. `ProxyHost` gets a response-mode getter (a `Callable[[], ResponseMode]`), supplied by
   `proxy_host()` in `app_proxy.py` from `app.response_mode`. The proxy service and pipeline
   stay free of application imports: a plain getter or a small port only.
4. The request pipeline reads the mode once at the start of each request and latches it for
   that request. The latched mode is recorded on the `proxy_answer` Journal event metadata
   (key `response_mode`, string value `text`/`voice`/`text_voice`) via the existing
   `record_proxy_answer` path (`journal/proxy_exchange.py`, `journal/recorder.py`,
   `reporting/journal_writer.py`).
5. The behavior of every mode is still Text: nothing in the request, the speech, or the
   outbound payload depends on the mode in this task. The Status Console control works and
   shows the mode.
6. `PROJECT.md`: the statement that response mode is refused in proxy mode is amended; the
   v2.1.1 story is referenced. No README change (later task).

## Boundary

`core/run_mode.py`, `app.py` (`_personal_proxy_background_work` only), `app_proxy.py`,
`startup/proxy_assembly.py` (`ProxyHost`), the request pipeline, the Journal recording of the
mode, tests, and the PROJECT.md amendment. No change to speech, TTS, the outbound payload,
the gate, sanitize, check, restoration, config keys, or the UI code unless the control
cannot work without it (then stop and report).

## Acceptance criteria

- [x] The hotkey and the Status Console control change the mode in proxy mode (tests at the
      policy and wiring level; the live check is human-run).
- [x] The mode is latched per request and recorded on `proxy_answer` metadata; a change
      during a request affects only the next request.
- [x] Default config: proxy behavior byte-identical to before (outbound payload and speech).
- [x] `python -m pytest`, `ruff check`, `ruff format --check` are green.

## Outcome (2026-10-27)

Findings: `[response].mode` default is `text`, so an unchanged config keeps the proxy in Text.
The `ResponseModeChanged` handler and the transport subscription are subscribed
unconditionally in `app.py` (outside `_user_input_subscriptions`), so they are live in proxy
mode; no stop condition. Implemented design points 1-6; the plain getter lives in
`personal_proxy/common/response_mode.py` (`ResponseModeGetter`, default `always_text`). The latched
mode travels on `RequestSourceBlock.response_mode` to `ProxyJournalWriter` and is recorded as
`response_mode` on `proxy_answer`. Full suite green except the known timezone failure of
`tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix` (fails without
these changes too). Limits: the live hotkey and Status Console check is human-run; every mode
still behaves as Text until task 4.
