#!/usr/bin/env python3
"""One-time setup: downloads and caches the Whisper model --personal-proxy uses.

Requires network access and `pip install -r requirements-stt.txt` - run this
once before starting the offline runtime, the same way setup_tts_model.py is
a one-time step for the voice. The runtime itself never downloads weights; it
loads them from the local cache only.

After the download this script loads the model again from local files only,
so a success means the runtime will find it.

Usage:
  python setup_stt_model.py [--model large-v3-turbo]
"""

import argparse
from collections.abc import Callable

DEFAULT_MODEL = "large-v3-turbo"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser


def _download(model_name: str) -> str:
    from faster_whisper.utils import download_model

    return download_model(model_name)


def _load_offline(model_name: str) -> object:
    from jarvis.personal_proxy.stt_whisper import load_whisper_model

    return load_whisper_model(model_name, "cpu")


def cache_model(
    model_name: str,
    *,
    downloader: Callable[[str], str] = _download,
    offline_loader: Callable[[str], object] = _load_offline,
) -> None:
    print(f"Downloading the speech model ({model_name})...")
    location = downloader(model_name)
    print(f"Downloaded to {location}.")
    print("Checking that it loads from local files only...")
    offline_loader(model_name)
    print("Done. The model is cached locally; --personal-proxy can now run offline.")


def main() -> None:
    args = build_arg_parser().parse_args()
    cache_model(args.model)


if __name__ == "__main__":
    main()
