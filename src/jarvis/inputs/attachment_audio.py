"""Uploaded-audio normalization and clip planning (task-v1.6.0-5).

Consumes the PendingAudioMedia that plan_attachments() produced (header
probe only) and does the real work: decode to PCM, downmix to mono,
resample to the 16 kHz model target, split into deterministic <= 30 s
clips, and base64-encode each clip for the current turn's `images`
payload - the verified Ollama media field for audio and images alike.

This is the uploaded-file path only. It shares nothing with microphone
listening except `samples_to_wav_bytes` (a dependency-free encoder used
by both audio directions already): no VAD, no speech-end detection, no
realtime chunking from `jarvis.audio.input`. An uploaded file has no live
speech signal to key off, so windows are fixed-length by policy
(tasks/attachment-policy-v1.6.0.md), not speech-aware - and the model-
facing cue says "Attached audio", never the microphone path's voice
placeholder, so a file upload is not dressed up as realtime listening.

Decoding uses soundfile - the same decoder whose header probe the
planner already ran - so a file that passed planning and still fails
here (truncated data past a valid header) gets the same deterministic
rejection surface, not an exception. Resampling uses
torchaudio.functional.resample from the already-declared torch stack.
"""

import base64
import io
from dataclasses import dataclass

import numpy as np
import soundfile as sf
import torch
import torchaudio

from jarvis.audio.utils import samples_to_wav_bytes
from jarvis.inputs.attachments import MAX_AUDIO_SECONDS, PendingAudioMedia

TARGET_SAMPLE_RATE = 16000
MAX_CLIP_SECONDS = 30.0
MAX_CLIPS_PER_FILE = int(MAX_AUDIO_SECONDS / MAX_CLIP_SECONDS)

# ASCII per CLAUDE.md; reaches the model prompt and journal/UI verbatim.
# Deliberately not VOICE_PLACEHOLDER_TEXT: uploaded audio is a file the
# user attached, not something Jarvis heard.
AUDIO_CUE_SINGLE_TEMPLATE = "[Attached audio: {filename}, {duration:.1f} s]"
AUDIO_CUE_CHUNKED_TEMPLATE = (
    "[Attached audio: {filename}, {duration:.1f} s, split into {clip_count} clips]"
)


@dataclass(frozen=True)
class AudioClip:
    """One model-safe clip: 16 kHz mono 16-bit WAV, base64 for `images`."""

    base64_wav: str
    clip_index: int
    clip_count: int
    start_seconds: float
    end_seconds: float
    description: str


@dataclass(frozen=True)
class NormalizedAudioAttachment:
    filename: str
    accepted: bool
    duration_seconds: float = 0.0
    clips: tuple[AudioClip, ...] = ()
    warnings: tuple[str, ...] = ()
    rejection_reason: str | None = None


def _rejected(filename: str, reason: str) -> NormalizedAudioAttachment:
    return NormalizedAudioAttachment(
        filename=filename, accepted=False, rejection_reason=reason
    )


def _decode_mono_16k(data: bytes) -> torch.Tensor:
    samples, sample_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    mono = torch.from_numpy(np.ascontiguousarray(samples.mean(axis=1)))
    if sample_rate == TARGET_SAMPLE_RATE:
        return mono
    return torchaudio.functional.resample(mono, sample_rate, TARGET_SAMPLE_RATE)


def normalize_audio_attachment(
    filename: str, pending: PendingAudioMedia
) -> NormalizedAudioAttachment:
    """Turns validated raw upload bytes into ordered model-safe clips.
    Never raises on bad input - every failure becomes a rejection with a
    user-facing reason, mirroring plan_attachments()."""
    try:
        mono = _decode_mono_16k(pending.data)
    except Exception:
        return _rejected(
            filename,
            f"{filename}: could not decode audio (corrupt or unsupported encoding).",
        )

    if mono.numel() == 0:
        return _rejected(filename, f"{filename}: audio contains no samples.")

    duration_seconds = mono.numel() / TARGET_SAMPLE_RATE
    window = int(MAX_CLIP_SECONDS * TARGET_SAMPLE_RATE)
    starts = range(0, mono.numel(), window)
    clip_count = len(starts)

    # The planner's sf.info() probe already gates on declared duration,
    # but this layer owns chunk planning "according to policy" - and for
    # compressed formats the decoded length can differ from the header's
    # claim. Re-enforce the cap on what was actually decoded, per the
    # policy's reject-outright rule (never silently send a truncated
    # first 90 seconds).
    if clip_count > MAX_CLIPS_PER_FILE:
        return _rejected(
            filename,
            f"{filename}: audio is {duration_seconds:.1f} s after decoding, "
            f"exceeds the {MAX_AUDIO_SECONDS:.0f} s "
            f"({MAX_CLIPS_PER_FILE} clip) limit; trim or split the file "
            "and re-upload.",
        )

    clips = []
    for clip_index, start in enumerate(starts, start=1):
        chunk = mono[start : start + window]
        start_seconds = start / TARGET_SAMPLE_RATE
        end_seconds = (start + chunk.numel()) / TARGET_SAMPLE_RATE
        clips.append(
            AudioClip(
                base64_wav=base64.b64encode(
                    samples_to_wav_bytes(chunk, TARGET_SAMPLE_RATE)
                ).decode("ascii"),
                clip_index=clip_index,
                clip_count=clip_count,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                description=(
                    f"clip {clip_index} of {clip_count}, "
                    f"{start_seconds:.1f}-{end_seconds:.1f} s"
                ),
            )
        )

    warnings = ()
    if clip_count > 1:
        warnings = (
            f"{filename}: {duration_seconds:.1f} s audio split into "
            f"{clip_count} clips of up to {MAX_CLIP_SECONDS:.0f} s.",
        )

    return NormalizedAudioAttachment(
        filename=filename,
        accepted=True,
        duration_seconds=duration_seconds,
        clips=tuple(clips),
        warnings=warnings,
    )


def compose_audio_media(normalized: NormalizedAudioAttachment) -> tuple[str, ...]:
    """Clip base64 strings in clip order - the same representation the
    screenshot and image-attachment paths feed the current-turn media
    list, ready for orchestration (task-v1.6.0-6) to concatenate.
    Current-turn only by story contract: nothing here enters
    ConversationHistory."""
    return tuple(clip.base64_wav for clip in normalized.clips)


def compose_audio_cue(normalized: NormalizedAudioAttachment) -> str | None:
    """Model-facing text cue naming the attached audio file, emitted from
    the normalization result rather than the plan so a cue can never name
    audio whose decode later failed. None for a rejected attachment."""
    if not normalized.accepted:
        return None
    if len(normalized.clips) > 1:
        return AUDIO_CUE_CHUNKED_TEMPLATE.format(
            filename=normalized.filename,
            duration=normalized.duration_seconds,
            clip_count=len(normalized.clips),
        )
    return AUDIO_CUE_SINGLE_TEMPLATE.format(
        filename=normalized.filename, duration=normalized.duration_seconds
    )
