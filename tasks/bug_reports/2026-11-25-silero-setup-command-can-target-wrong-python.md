# Silero setup hint can target the wrong Python installation

**Detected against source commit:** `935bf17881a9524c1c81f7e36653b5d94e4d4086`.

## Symptoms

On a fresh Windows deployment, `python setup_tts_model.py --language ru
--model v5_5_ru` reported success. The next Russian response failed with
`TtsModelNotCachedError`. The error recommended the same command.

## Cause

`Jarvis.cmd` runs `.venv\Scripts\python.exe`. The unqualified `python` in
the setup hint resolved to the user's Windows Python installation, which
cached the weights beside its own Silero package. The deployment virtual
environment had its own Silero package and was missing the weights. Both
cache paths and file presence were checked on the affected machine.

## Temporary resolution

Copied the already cached `v5_5_ru.pt` into the deployment cache and verified
the copy by SHA-256. This reused the existing download without changing
Python packages or runtime configuration. The deployed Python then loaded
the configured route and synthesized a non-empty WAV in memory with Silero's
download function blocked. Speaker playback remains a manual check.

## Follow-up

Make the runtime hint identify the interpreter that owns the missing cache.
Use the deployment interpreter explicitly in Windows setup instructions.
Keep the offline cache check and per-environment package locations.
