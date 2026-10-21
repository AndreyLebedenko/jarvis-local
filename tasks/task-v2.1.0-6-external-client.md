# Task v2.1.0-6: external client

Status: Open.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 6 (Size: S-M). Follows task 1 (the
`[personal_proxy]` settings and the locality seam) and task 2 (`OutboundPayload`, the
only way to obtain an outbound request body). Task 7 consumes the streamed answer;
task 9 composes the gate, the seam and this client.

## Summary

A small client for an OpenAI-compatible chat completions endpoint: it sends one
`OutboundPayload`, streams the answer back as text deltas, and reports every failure
as a typed error that carries no content. This is the only code in the project that
talks to the external provider.

## Boundary

New code in `src/jarvis/personal_proxy/`. Uses `httpx` (already in
`requirements.txt`; no new dependency). Not the Ollama backend: it is a separate
client with its own settings. No gate call (task 9 composes: gate, then locality seam,
then this client), no restoration, no pipeline, no journal, no UI, no real network in
tests.

## Required behavior

1. **Input is only an `OutboundPayload`** (task 2). Anything else is a `TypeError`
   before any key is read or any socket opened. The client has no parameter for extra
   text, headers, options, or messages.
2. **Request.** `POST` to `[personal_proxy].endpoint` (the full URL, used as is), JSON
   body `{"model": settings.model, "messages": payload.to_chat_messages(), "stream":
   true}` and nothing else (no sampling parameters, no `user`, no metadata), headers
   `Authorization: Bearer <key>` and `Content-Type: application/json`. Redirects are
   not followed (`follow_redirects=False`): a 3xx is an HTTP error, so the key and the
   text are never forwarded to another host.
3. **Key.** Read from the environment variable named by `[personal_proxy].api_key_env`
   at each call (an injectable environ mapping for tests). Unset or blank: typed error
   before any network activity. The key is never stored on the client, never in a
   `repr`, an exception, a log line, or a result.
4. **Transport rule.** The endpoint scheme must be `https`, or `http` with a loopback
   host (`localhost`, `127.0.0.1`, `::1`, or a name ending `.localhost`). Anything else
   is a typed error before the key is read (owner decision, 2026-10-21: the key and the
   cleaned text never cross the network unencrypted). Loopback `http` is what makes the
   fake-server tests possible.
5. **Timeouts.** `connect_timeout_seconds` for opening the connection; the whole call,
   stream included, is bounded by `request_timeout_seconds` (an overall deadline, not
   only a per-read one). Both are existing settings.
6. **Answer.** Server-sent events, `data: {json}` lines and a final `data: [DONE]`.
   Yield `choices[0].delta.content` strings in order (ignore role-only and empty
   deltas, comment lines, and unknown fields). Success needs a clean end: `[DONE]`, or a
   `finish_reason` of `stop`. A `finish_reason` of `length` is a typed truncation error
   (the text already yielded is not a complete answer, and the error says so). A stream
   that ends without either, an invalid JSON event, an event that is not an object, or a
   non-text `content` is a typed stream error. An answer with no text at all is a typed
   empty-answer error.
7. **Typed errors** (one exception type with an enum `kind`, plus the HTTP status
   number when there is one): key missing, insecure endpoint, connect failed, timeout,
   HTTP status (any non-2xx, including 3xx), bad stream, truncated, empty answer.
   Messages are fixed strings. They never contain the endpoint, the key, the payload, a
   response body, or the underlying exception text, and are raised `from None`.
8. **Nothing logged.** The client writes no log line and calls nothing of
   `core/model_request_log.py` or the debug transcript; a test asserts that nothing is
   logged at any level, including on every error path.
9. Tests against a loopback fake HTTP server (a local asyncio/`httpx.MockTransport`
   level fake is fine for logic; at least one test through a real local socket server
   so TLS-free loopback `http` and header/body bytes are really exercised): the exact
   request body and headers (only the allowed keys), a split SSE stream (events broken
   mid-line across chunks), `[DONE]`, a `finish_reason` of `length`, a 401/429/500,
   a 302 with a `Location` (not followed, and the second host never sees a request), a
   connect error, an overall-deadline timeout with a slow trickling stream, an invalid
   event, an empty answer, a missing key, a non-loopback `http` endpoint, a non-payload
   argument; and that the key, the payload text and the response body appear in no
   `repr`, `str`, exception, traceback chain, or log record. No real network, no secrets.

Out of scope: retries (none, ever), several providers, tool calls, history, non-text
content, restoration, the gate.

## Acceptance criteria

- [ ] Only an `OutboundPayload` can be sent; the request body holds `model`, `messages`,
      `stream` and nothing else.
- [ ] The key is read from the named environment variable per call and appears nowhere
      (repr, exception, log, result).
- [ ] A non-https, non-loopback endpoint, a missing key, a redirect, a non-2xx status, a
      bad or truncated stream and a timeout are each a typed error without content.
- [ ] The whole call is bounded by `request_timeout_seconds`.
- [ ] Nothing is logged; the request log and the debug transcript are not used.
- [ ] No retry, no new dependency, tests use no real network.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
