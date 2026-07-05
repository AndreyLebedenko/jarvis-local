"""Sound cue synthesis and playback.

config.example.toml's [sound_cues] section points at sounds/*.wav, but no
audio assets ship with the repo. These are synthesized, offline,
deterministic placeholder tones (pure math, no network) rather than
committed binary files or a manual setup step - ensure_generated()
creates them on first run if missing. Swap sounds/*.wav for your own
recordings any time; nothing else needs to change.

SoundCuePlayer is the only feedback mechanism given PROJECT.md's
"hotkeys + sound cues only, no GUI" interaction model. play() itself is
fire-and-forget (schedules a background task and returns immediately) so
a cue never adds latency to the request pipeline it is signaling about.
The actual device access happens under a lock shared with tts.py's
TtsOutput (see main.py's build_app()): sounddevice's play()/wait()
convenience API shares one implicit default stream per process, and two
concurrent play() calls stop/replace each other rather than mixing -
verified live as the cause of audible crackling/tempo artifacts when a
cue and a spoken sentence landed at the same time.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import SoundCueSettings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 22050


def _tone(freq: float, duration: float, amplitude: float = 0.3) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # Short linear fade in/out so the tone doesn't click at start/end.
    fade_samples = max(1, int(SAMPLE_RATE * 0.01))
    envelope = np.ones_like(t)
    envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
    envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
    return (amplitude * np.sin(2 * np.pi * freq * t) * envelope).astype(np.float32)


def _cue_listening() -> np.ndarray:
    return np.concatenate([_tone(880, 0.08), _tone(1046, 0.10)])


def _cue_thinking() -> np.ndarray:
    return _tone(440, 0.08)


def _cue_speaking() -> np.ndarray:
    return _tone(660, 0.06)


def _cue_error() -> np.ndarray:
    return np.concatenate([_tone(300, 0.12), _tone(200, 0.16)])


def _cue_clipboard() -> np.ndarray:
    return np.concatenate([_tone(660, 0.05), _tone(880, 0.07)])


def _cue_input_error() -> np.ndarray:
    # A repeated double-blip, not the single short low tone this used to
    # be: human-reported during task-10 manual testing that the single
    # tone was not reliably audible in practice, unlike the other new
    # v1.1 cues (all multi-segment). A silent gap between two same-pitch
    # blips also keeps this rhythmically distinct from the generic
    # two-tone *falling* `error` cue below (backend/TTS failures, not a
    # rejected/truncated input).
    gap = np.zeros(int(SAMPLE_RATE * 0.05), dtype=np.float32)
    blip = _tone(320, 0.09)
    return np.concatenate([blip, gap, blip])


def _cue_mic_sleep() -> np.ndarray:
    return np.concatenate([_tone(700, 0.06), _tone(500, 0.08)])


def _cue_mic_wake() -> np.ndarray:
    return np.concatenate([_tone(500, 0.06), _tone(700, 0.08)])


_GENERATORS: dict[str, Callable[[], np.ndarray]] = {
    "listening": _cue_listening,
    "thinking": _cue_thinking,
    "speaking": _cue_speaking,
    "error": _cue_error,
    "clipboard": _cue_clipboard,
    "input_error": _cue_input_error,
    "mic_sleep": _cue_mic_sleep,
    "mic_wake": _cue_mic_wake,
}


def ensure_generated(settings: SoundCueSettings) -> None:
    """Synthesizes any of settings' cue files that don't already exist."""
    paths = {
        "listening": settings.listening,
        "thinking": settings.thinking,
        "speaking": settings.speaking,
        "error": settings.error,
        "clipboard": settings.clipboard,
        "input_error": settings.input_error,
        "mic_sleep": settings.mic_sleep,
        "mic_wake": settings.mic_wake,
    }
    for cue, path_str in paths.items():
        path = Path(path_str)
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, _GENERATORS[cue](), SAMPLE_RATE)


class SoundCuePlayer:
    def __init__(
        self,
        settings: SoundCueSettings,
        play_file: Callable[[str], Awaitable[None]] | None = None,
        playback_lock: asyncio.Lock | None = None,
    ) -> None:
        self._paths = {
            "listening": settings.listening,
            "thinking": settings.thinking,
            "speaking": settings.speaking,
            "error": settings.error,
            "clipboard": settings.clipboard,
            "input_error": settings.input_error,
            "mic_sleep": settings.mic_sleep,
            "mic_wake": settings.mic_wake,
        }
        self._playback_lock = playback_lock or asyncio.Lock()
        self._play_file = play_file or self._default_play_file
        self._pending_tasks: set[asyncio.Task] = set()

    async def play(self, cue: str) -> None:
        path = self._paths.get(cue)
        if path is None:
            logger.warning("Unknown sound cue %r, skipping", cue)
            return
        logger.info("Playing sound cue %r (%s)", cue, path)
        task = asyncio.create_task(self._play_file(path))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def wait_for_pending(self) -> None:
        """Awaits every cue playback scheduled so far. Mirrors
        TtsOutput.wait_for_pending() - useful for tests and so a clean
        shutdown doesn't cut a cue off mid-playback."""
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks)

    async def _default_play_file(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.exists():
            logger.warning("Sound cue file missing, skipping: %s", path)
            return
        data, sample_rate = await asyncio.to_thread(sf.read, path, dtype="float32")
        async with self._playback_lock:
            await asyncio.to_thread(sd.play, data, sample_rate)
            await asyncio.to_thread(sd.wait)
