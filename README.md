# Jarvis

Jarvis is a local voice and vision assistant for a Windows workstation. It listens through the microphone, sends audio and optional screenshots to a local Ollama model, and speaks short Russian answers through local TTS.

Runtime is designed to work offline after the one-time model setup steps are complete.

[Russian README](README.ru.md)

## Status

This is a v1.0 hobby/research release. It is usable, but intentionally honest about its limits: no full echo cancellation, Russian-only Silero TTS, rough Latin transliteration, and imperfect OCR on dense screenshots.

Jarvis is not affiliated with Marvel, Disney, or any related trademark owner.

## Features

- Local Ollama backend using `gemma4:12b-it-qat`.
- Voice input with Silero VAD.
- Sentence-level streaming TTS for low perceived latency.
- Full-screen and region screenshot capture.
- Hotkey and sound-cue interface, no GUI.
- Async event-bus architecture with isolated modules.
- Type-checked TOML configuration.
- Runtime offline mode after models are downloaded.

## Requirements

- Windows 11.
- Python 3.11.
- Ollama installed and running.
- A GPU with enough VRAM for the selected Ollama model.
- Administrator terminal for global hotkeys on Windows.

## Installation

Clone this repository, then install Python dependencies:

```bash
pip install -r requirements.txt
```

Pull the Ollama model:

```bash
ollama pull gemma4:12b-it-qat
```

Download and cache the Silero TTS model once:

```bash
python setup_tts_model.py
```

Optionally create a local config:

```cmd
copy config.example.toml config.toml
```

## Usage

Run from the repository root:

```bash
python main.py
```

For global hotkeys to work from any application on Windows, run the terminal as Administrator. Without elevation, hotkeys may only fire while the app's own terminal window has focus.

Default hotkeys:

- `Ctrl+Alt+S`: capture the full screen for the next request.
- `Ctrl+Alt+R`: capture a selected screen region for the next request.
- `Ctrl+Alt+Q`: shut down Jarvis.

## Architecture

The app is split into small asyncio modules connected through `bus.py`:

- `audio_in.py`: microphone capture, VAD, utterance chunking.
- `backend.py`: Ollama `/api/chat` streaming adapter.
- `capture.py`: screenshot capture.
- `tts.py`: sentence buffering, Silero TTS synthesis, playback.
- `sound_cues.py`: generated local cue sounds.
- `config.py`: TOML settings and validation.
- `main.py`: wiring, orchestration, prompt, shutdown.

`PROJECT.md` is the source of truth for architectural decisions and verified experiments. The `tasks/` directory keeps story cards, task cards, and bug reports from development.

## Development Process

This repository was built with an agent-assisted workflow: project facts were recorded in `PROJECT.md`, implementation was split into task cards, and day-0 experiments were kept as verified constraints instead of being rediscovered during later work. That history is intentionally public because it shows the engineering trade-offs behind v1.0: local multimodal model behavior, audio payload quirks, hotkey limitations, TTS model constraints, latency measurements, and known risks.

## Known Issues

- Windows global hotkeys require Administrator privileges.
- A true cold Ollama start can take long enough to require a generous read timeout.
- There is no real echo cancellation in v1.0. Jarvis can hear its own TTS through speakers; the app includes a cooldown mitigation, not a full fix.
- Silero TTS `v3_1_ru` does not support Latin characters. Jarvis transliterates Latin words to Cyrillic before synthesis as a best-effort workaround.
- Dense screenshots, especially large IDE views, can cause OCR confabulation. Use region capture for targeted questions.

## Tests

Automated tests cover pure logic only. Hardware-dependent checks for microphone, speakers, global hotkeys, screenshots, VRAM, and a live Ollama endpoint are manual by project policy.

```bash
python -m pytest
```

## Licensing

The project code is released under the MIT License. See [LICENSE](LICENSE).

External model weights are not distributed by this repository and are governed by their own licenses and terms:

- Silero VAD is published under MIT by its upstream project.
- Silero TTS models are governed by Silero Models licensing; the currently configured `v3_1_ru` model is not part of this repository's MIT license.
- Gemma model weights are governed by Google's Gemma terms or the specific license attached to the model you use through Ollama.

Review the upstream model licenses before commercial use or redistribution.
