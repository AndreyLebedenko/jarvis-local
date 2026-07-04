#!/usr/bin/env python3
"""One-time setup: downloads and caches the Silero TTS model tts.py uses.

Requires network access - run this once before starting the offline
runtime, the same way `ollama pull gemma4:12b-it-qat` is a one-time setup
step for the backend model (PROJECT.md: the runtime itself must not
require network access).

After this succeeds: the model weights are cached inside the installed
silero package's own directory, and this repo's latest_silero_models.yml
manifest (checked into git, next to this script) is populated/refreshed.
silero_tts() looks for that manifest relative to the process's current
working directory - not relative to this script - so this always copies
the result to the exact repo-root path regardless of where it was
invoked from, matching what tts.py's _load_model() checks for.

The app itself still needs to be launched with the repo root as its
working directory for silero_tts() to find the manifest at runtime (see
tts.py's _ensure_model_cached() docstring) - this is an existing project
convention (config.toml's default path, sound cue paths, etc.), not a
new one introduced here.

Usage:
  python setup_tts_model.py
"""

import shutil
from pathlib import Path

import silero

_MODELS_MANIFEST_FILENAME = "latest_silero_models.yml"


def main() -> None:
    print("Downloading/verifying the Silero TTS model (ru, v3_1_ru)...")
    silero.silero_tts(language="ru", speaker="v3_1_ru")

    repo_target = Path(__file__).resolve().parent / _MODELS_MANIFEST_FILENAME
    produced = Path(_MODELS_MANIFEST_FILENAME).resolve()
    if produced != repo_target:
        shutil.copyfile(produced, repo_target)
        print(f"Copied manifest to {repo_target} (script was run from elsewhere).")

    print("Done. The model is cached locally; tts.py can now run offline")
    print("as long as it is launched with the repo root as its working")
    print("directory.")


if __name__ == "__main__":
    main()
