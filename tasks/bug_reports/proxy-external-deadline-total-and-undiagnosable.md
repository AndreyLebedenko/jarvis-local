# Personal proxy: one 60 s total deadline cuts a slow answer, and nothing records why

Detected at commit d6bdc64 (branch feat/v2.1.0-12a-public-names), live run 2026-10-27,
session `20261027-100105-926fcb`, model `glm-5.3-flash:cloud` via the local Ollama
endpoint, `request_timeout_seconds = 60` in `config.toml`.

## Symptoms

The answer stopped after 373 characters with "Answer incomplete (timed out)". The screen
does not say which limit fired or how long the call ran.

## Suspected cause (code reading)

`external/external_client.py`: a single absolute deadline
(`[personal_proxy].request_timeout_seconds`, default 60 s) covers connect, time to first
token and the whole stream. A slow or "thinking" model is cut wherever it is. An httpx read
timeout of the same value also maps to the same kind `TIMEOUT`, so the kind cannot tell the
deadline from a stalled provider. TTS and UI do not slow the read (decoupled queues).
The client logs nothing; the Journal has no elapsed time, time to first token or chunk count.
README does not mention the key; PROJECT.md says only "an overall deadline".

## Temporary decision

Not fixed in task 12a. Owner experiment proposed: raise `request_timeout_seconds` to 180 and
repeat the request; compare Journal event times.

## Future considerations

- Decide whether a total cap or an idle (between chunks) cap, plus a first-token cap, is the
  right shape for a streamed answer; keep a total ceiling.
- Record the failure cause and elapsed time without content (which limit fired, seconds to
  first token, seconds total), in the notice detail or the Journal metadata.
- Document the key and its meaning in README (EN, RU) and PROJECT.md.
- Unexplained: why the call lasted 60 s of wall time from the first read when only 373
  characters arrived; time to first token is unknown.
