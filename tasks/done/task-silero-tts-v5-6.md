# Task: Silero TTS v5.6

**Status:** Completed.

Register the official Russian `v5_6_ru` package in
`latest_silero_models.yml`. Model selection uses the existing Silero route,
with explicit setup and cached weights during runtime.

## Acceptance criteria

- The existing TTS route accepts `v5_6_ru` and produces WAV audio when the
  model is cached. Missing weights are reported before Silero's downloader
  can run.
- The existing `setup_tts_model.py` command provisions `v5_6_ru` explicitly.

## Verification

Ruff checks passed. The full pytest run had 6362 passing tests and 3 skips.
The route test uses a stub model. Playback with real weights is a manual check.

## Manual check

Run this from the repository root with the project's `.venv` installed. The
first command needs network access. The setup arguments come from
`setup_tts_model.py`. The route fields come from `SileroTtsSettings` in
`config.py`, and `tts_silero.py` supplies the production loader and WAV path.

```powershell
.\.venv\Scripts\python.exe setup_tts_model.py --language ru --model v5_6_ru
```

Once the download succeeds, run the following block with the network
disconnected. This uses an explicit route and the Windows default speakers.

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@'
import asyncio
import winsound

from jarvis.audio.tts_silero import SileroEngine
from jarvis.core.config import SileroTtsSettings

route = SileroTtsSettings(
    model="v5_6_ru", language="ru", speaker="eugene", sample_rate=48000
)
wav = asyncio.run(SileroEngine(route).synthesize("Мы готовы? Поехали!", "ru"))
winsound.PlaySound(wav, winsound.SND_MEMORY)
'@ | .\.venv\Scripts\python.exe -X utf8 -
```

Expected result: both Russian phrases play in order with no exception.
