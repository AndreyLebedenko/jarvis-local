#!/usr/bin/env python3
"""Human-run check of the doubt trigger (handoff B of task v2.1.0-8).

Handoff with every step: manual/doubt-trigger-handoff.md.

  python -m manual.manual_check_doubt_trigger --config FILE run
      [--v1-wavs DIR] [--v2-wavs DIR]

Runs the 60 labeled recordings of spike v2.1.0-10 (the utterances with labeled
spans of the first and the second corpus) through the guarded speech-to-text
stage and the production transcript check stage against the live local Ollama
endpoint, then applies the rule frozen in the task card on 2026-10-22
(`manual.personal_proxy.doubt_trigger`). A real error is the spike's label
`addresses_assembled`, judged on the checked text.
"""

from __future__ import annotations

import argparse
import asyncio
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from jarvis.core.config import Settings, load_settings
from jarvis.personal_proxy.check.check_backend import CheckBackend
from jarvis.personal_proxy.check.ollama_check_backend import OllamaCheckBackend
from jarvis.personal_proxy.check.transcript_check import check_transcript
from jarvis.personal_proxy.stt.guarded_transcription import (
    ProbabilitySource,
    transcribe_guarded,
)
from jarvis.personal_proxy.stt.silero_probabilities import SileroSpeechProbabilities
from jarvis.personal_proxy.stt.speech_guard import NoSpeech
from jarvis.personal_proxy.stt.stt_engine import SpeechEngine
from jarvis.personal_proxy.stt.stt_whisper import FasterWhisperEngine
from manual.manual_check_stt_stage import decode
from manual.manual_check_transcript_check import (
    CONNECT_TIMEOUT_SECONDS,
    ollama_preflight,
)
from manual.personal_proxy.audio import WavDirectory, WavDirectoryError
from manual.personal_proxy.confidence import LabelRule, is_bad
from manual.personal_proxy.corpus import CORPUS, Utterance
from manual.personal_proxy.corpus_v2 import CORPUS_V2, corpus_v2_fingerprint
from manual.personal_proxy.doubt_trigger import (
    Observation,
    config_problems,
    evaluate,
    render,
)

LABEL_RULE = LabelRule.ADDRESSES_ASSEMBLED
DEFAULT_V1_WAVS = Path("personal_proxy_corpus_wavs")
DEFAULT_V2_WAVS = Path("personal_proxy_corpus_v2_wavs")


@dataclass(frozen=True)
class LabeledRecording:
    utterance: Utterance
    wav: bytes


def labeled_recordings(v1_wavs: Path, v2_wavs: Path) -> list[LabeledRecording]:
    sources = (
        (WavDirectory(v1_wavs, CORPUS, None), CORPUS),
        (WavDirectory(v2_wavs, CORPUS_V2, corpus_v2_fingerprint()), CORPUS_V2),
    )
    return [
        LabeledRecording(u, directory.audio_for(u.utterance_id))
        for directory, corpus in sources
        for u in corpus
        if u.spans
    ]


async def observe(
    utterance: Utterance,
    clip: np.ndarray,
    engine: SpeechEngine,
    probabilities: ProbabilitySource,
    backend: CheckBackend,
    settings: Settings,
) -> Observation | None:
    """None when the speech guard rejected the clip: it never reached the check."""
    proxy = settings.personal_proxy
    transcription = transcribe_guarded(
        clip,
        engine,
        probabilities,
        vad_threshold=settings.vad.threshold,
        minimum_speech_seconds=proxy.stt_min_speech_seconds,
    )
    if isinstance(transcription, NoSpeech):
        return None
    checked = await check_transcript(transcription, clip, backend, proxy)
    error = is_bad(utterance, transcription.text, checked.text, LABEL_RULE)
    fragments = tuple(d.fragment for d in checked.doubts if d.fragment is not None)
    return Observation(utterance.utterance_id, error, checked.would_ask, fragments)


def render_observation(observation: Observation) -> str:
    named = "; ".join(observation.fragments) or "-"
    return (
        f"{observation.subject_id}: error={observation.error} "
        f"asked={observation.asked} doubts: {named}"
    )


async def command_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    proxy = settings.personal_proxy
    problems = config_problems(settings)
    print(
        f"[backend].endpoint = {settings.backend.endpoint}; "
        f"[backend].flash_attention = {settings.backend.flash_attention}; "
        f"[backend].kv_cache_type = {settings.backend.kv_cache_type}; "
        f"check_model = {proxy.check_model}; "
        f"doubt_min_listed = {proxy.doubt_min_listed}"
    )
    if problems:
        print("Configuration differs from the frozen one; nothing was run:")
        print("\n".join(f"  {problem}" for problem in problems))
        return 2
    try:
        recordings = labeled_recordings(args.v1_wavs, args.v2_wavs)
    except WavDirectoryError as error:
        print(f"ERROR: {error}")
        return 2
    with httpx.Client(base_url=settings.backend.endpoint, timeout=5.0) as probe:
        problem = ollama_preflight(probe, settings.backend.endpoint, proxy.check_model)
    if problem:
        print(problem)
        return 2
    print(f"{len(recordings)} labeled recordings; loading Whisper...")
    engine = FasterWhisperEngine(proxy)
    probabilities = SileroSpeechProbabilities()
    timeout = httpx.Timeout(
        CONNECT_TIMEOUT_SECONDS, read=settings.backend.read_timeout_seconds
    )
    observations: list[Observation] = []
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaCheckBackend(settings.backend, proxy, client)
        for recording in recordings:
            clip = decode_wav(recording.wav)
            observation = await observe(
                recording.utterance, clip, engine, probabilities, backend, settings
            )
            if observation is None:
                print(f"{recording.utterance.utterance_id}: NO SPEECH; not checked")
                continue
            observations.append(observation)
            print(render_observation(observation), flush=True)
    print("\n" + render(evaluate(observations)))
    return 0


def decode_wav(wav: bytes) -> np.ndarray:
    return decode(io.BytesIO(wav))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--v1-wavs", type=Path, default=DEFAULT_V1_WAVS)
    run.add_argument("--v2-wavs", type=Path, default=DEFAULT_V2_WAVS)
    run.set_defaults(handler=command_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
