# Spike v1.2.9 - Bilingual TTS Routing

Status: Completed.

## Summary

Compare three local bilingual TTS routing variants over the existing
Russian/English charset segmentation:

1. `ru`, `en` -> Silero.
2. `ru` -> Silero, `en` -> Piper.
3. `ru`, `en` -> Piper.

This is a spike, not a runtime migration. Do not change Jarvis's production
TTS engine selection until the manual listening results are recorded.

## Boundary

In scope:

- Add a manual check script that uses `language_segments.segment_by_charset()`
  to split mixed Russian/English text.
- Route each segment to the selected engine according to the active variant.
- Preserve audible segment order even when synthesis completes out of order.
- Print per-route and per-segment timings for human comparison.
- Cover route selection and model-path validation with automated tests.

Out of scope:

- Replacing the production `TtsOutput` engine.
- Downloading Piper or Silero models automatically.
- Running speaker/GPU/live TTS checks by the agent.
- Updating graphify before the human explicitly requests it.

## Manual Check

Run from the repository root after installing the required TTS packages and
placing the Piper models locally:

```powershell
python manual_check_bilingual_tts_routes.py --piper-ru-model D:\voices\ru_RU.onnx
```

Useful focused runs:

```powershell
python manual_check_bilingual_tts_routes.py --route silero_ru_en
python manual_check_bilingual_tts_routes.py --route silero_ru_piper_en
python manual_check_bilingual_tts_routes.py --route piper_ru_en --piper-ru-model D:\voices\ru_RU.onnx
```

The English Piper model defaults to:

```text
.local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx
```

If a different English model is used, pass `--piper-en-model`.

## Piper Russian Model Download

Downloaded model:

```text
.local-models/piper/ru_RU-irina-medium/ru_RU-irina-medium.onnx
.local-models/piper/ru_RU-irina-medium/ru_RU-irina-medium.onnx.json
```

Source:

```text
https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU/irina/medium
```

Reason for choosing `ru_RU-irina-medium`: it is an official Piper Russian
medium-quality voice from `rhasspy/piper-voices`, and its female voice is a
closer subjective comparison point to the current Silero `baya` voice than the
male Russian Piper voices.

Download commands used from the repository root:

```powershell
$target = Join-Path (Get-Location) '.local-models\piper\ru_RU-irina-medium'
New-Item -ItemType Directory -Force -Path $target | Out-Null
$modelUrl = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx'
$configUrl = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json'
Invoke-WebRequest -Uri $modelUrl -OutFile (Join-Path $target 'ru_RU-irina-medium.onnx')
Invoke-WebRequest -Uri $configUrl -OutFile (Join-Path $target 'ru_RU-irina-medium.onnx.json')
```

Verification commands used:

```powershell
Get-FileHash -Algorithm SHA256 .local-models\piper\ru_RU-irina-medium\ru_RU-irina-medium.onnx
Get-FileHash -Algorithm SHA256 .local-models\piper\ru_RU-irina-medium\ru_RU-irina-medium.onnx.json
```

Observed file sizes and hashes:

```text
ru_RU-irina-medium.onnx      63201294 bytes, SHA256 8FF38212D23DA300BBE3705C645E6E5B9475F0BFDE01558EB17813E22ACAAAAA
ru_RU-irina-medium.onnx.json     4765 bytes, SHA256 C2EC28BB38E2B59E93B959B3E40348C1AFEBBD272F30FED5D41205D08E98A9D7
```

The ONNX hash matches the Hugging Face LFS oid reported by the model API for
`ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx`.

Full local check command:

```powershell
python manual_check_bilingual_tts_routes.py --piper-ru-model .local-models\piper\ru_RU-irina-medium\ru_RU-irina-medium.onnx
```

## Acceptance Criteria

- The script exposes all three route variants.
- The script prints the charset segment plan before playback.
- Playback remains ordered by original segment index.
- Automated tests pass for pure route-planning and path-validation logic.
- Human records which route gives the best quality/latency/coherence tradeoff.

## Result

Human-run command:

```powershell
python manual_check_bilingual_tts_routes.py --piper-ru-model .local-models\piper\ru_RU-irina-medium\ru_RU-irina-medium.onnx
```

Tested route totals:

```text
silero_ru_en:
  code_switch_short 5.26 s
  technical_terms   6.57 s
  sentence_mix      4.21 s

silero_ru_piper_en:
  code_switch_short 5.94 s
  technical_terms   6.64 s
  sentence_mix      4.59 s

piper_ru_en:
  code_switch_short 4.96 s
  technical_terms   6.59 s
  sentence_mix      4.44 s
```

Subjective listening result: `silero_ru_piper_en` was the best combination.

Decision for the initial follow-up configuration: use Silero for Russian and
Piper for English because that was the preferred tested combination. This is
not an architectural language-to-engine restriction: either engine may be
configured for either supported language when a compatible model is supplied.
