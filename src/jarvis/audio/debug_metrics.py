"""Bridges captured utterances into the debug transcript.

Subscribed unconditionally in app.py's wire(), like every other bus
listener - nothing in the wiring needs to know whether debug is on.
recording() gates the actual work, so an ordinary run pays one check per
utterance and never decodes a wav or computes anything: the same
do-nothing-when-off property as begin_exchange() in debug_transcript.py.
"""

from dataclasses import asdict

from jarvis.audio.input import UtteranceChunk
from jarvis.audio.metrics import utterance_metrics_from_wav_bytes
from jarvis.core.debug_transcript import recording, write_record


async def on_utterance_captured(event: UtteranceChunk) -> None:
    if not recording():
        return
    write_record("utterance", asdict(utterance_metrics_from_wav_bytes(event.wav_bytes)))
