import base64
import io

import numpy as np
import soundfile as sf

from jarvis.inputs.attachment_audio import (
    MAX_CLIP_SECONDS,
    MAX_CLIPS_PER_FILE,
    TARGET_SAMPLE_RATE,
    NormalizedAudioAttachment,
    compose_audio_cue,
    compose_audio_media,
    normalize_audio_attachment,
)
from jarvis.inputs.attachments import MAX_AUDIO_SECONDS, PendingAudioMedia


def _wav_pending(
    duration_seconds: float,
    sample_rate: int = TARGET_SAMPLE_RATE,
    channels: int = 1,
    fill: float = 0.0,
) -> PendingAudioMedia:
    frames = int(sample_rate * duration_seconds)
    samples = np.full((frames, channels), fill, dtype=np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return PendingAudioMedia(
        data=buffer.getvalue(),
        content_type="audio/wav",
        duration_seconds=duration_seconds,
    )


def _decode_clip(base64_wav: str) -> tuple[np.ndarray, int]:
    return sf.read(io.BytesIO(base64.b64decode(base64_wav)))


# --- decode, downmix, resample ---------------------------------------------


def test_short_wav_becomes_one_16k_mono_clip():
    normalized = normalize_audio_attachment("memo.wav", _wav_pending(2.0))

    assert normalized.accepted is True
    assert normalized.warnings == ()
    (clip,) = normalized.clips
    samples, sample_rate = _decode_clip(clip.base64_wav)
    assert sample_rate == TARGET_SAMPLE_RATE
    assert samples.ndim == 1
    assert len(samples) == int(2.0 * TARGET_SAMPLE_RATE)
    assert clip.clip_index == 1
    assert clip.clip_count == 1
    assert clip.start_seconds == 0.0
    assert abs(clip.end_seconds - 2.0) < 0.01


def test_stereo_input_is_downmixed_to_mono():
    normalized = normalize_audio_attachment(
        "stereo.wav", _wav_pending(1.0, channels=2, fill=0.25)
    )

    (clip,) = normalized.clips
    samples, _ = _decode_clip(clip.base64_wav)
    assert samples.ndim == 1
    assert abs(float(np.max(samples)) - 0.25) < 0.01


def test_non_target_sample_rate_is_resampled_preserving_duration():
    normalized = normalize_audio_attachment(
        "cd_quality.wav", _wav_pending(2.0, sample_rate=44100)
    )

    (clip,) = normalized.clips
    samples, sample_rate = _decode_clip(clip.base64_wav)
    assert sample_rate == TARGET_SAMPLE_RATE
    assert abs(len(samples) / TARGET_SAMPLE_RATE - 2.0) < 0.05
    assert abs(normalized.duration_seconds - 2.0) < 0.05


def test_mp3_decodes_through_the_declared_stack():
    tone = np.zeros(TARGET_SAMPLE_RATE, dtype=np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, tone, TARGET_SAMPLE_RATE, format="MP3")
    pending = PendingAudioMedia(
        data=buffer.getvalue(), content_type="audio/mpeg", duration_seconds=1.0
    )

    normalized = normalize_audio_attachment("voice.mp3", pending)

    assert normalized.accepted is True
    (clip,) = normalized.clips
    _, sample_rate = _decode_clip(clip.base64_wav)
    assert sample_rate == TARGET_SAMPLE_RATE
    # MP3 encoders pad the tail; duration must be close, not exact.
    assert abs(normalized.duration_seconds - 1.0) < 0.2


# --- chunk planning ---------------------------------------------------------


def test_audio_over_30_seconds_is_split_into_ordered_fixed_windows():
    normalized = normalize_audio_attachment("long.wav", _wav_pending(65.0))

    assert [clip.clip_index for clip in normalized.clips] == [1, 2, 3]
    assert all(clip.clip_count == 3 for clip in normalized.clips)
    boundaries = [(clip.start_seconds, clip.end_seconds) for clip in normalized.clips]
    assert boundaries == [(0.0, 30.0), (30.0, 60.0), (60.0, 65.0)]
    assert normalized.clips[0].description == "clip 1 of 3, 0.0-30.0 s"
    assert normalized.clips[2].description == "clip 3 of 3, 60.0-65.0 s"


def test_chunking_produces_a_visible_warning():
    normalized = normalize_audio_attachment("long.wav", _wav_pending(65.0))

    (warning,) = normalized.warnings
    assert "long.wav" in warning
    assert "3 clips" in warning


def test_audio_at_exactly_30_seconds_stays_a_single_clip_without_warning():
    normalized = normalize_audio_attachment("exact.wav", _wav_pending(MAX_CLIP_SECONDS))

    assert len(normalized.clips) == 1
    assert normalized.warnings == ()


def test_each_clip_decodes_to_at_most_30_seconds_of_16k_mono():
    normalized = normalize_audio_attachment("long.wav", _wav_pending(65.0))

    max_samples = int(MAX_CLIP_SECONDS * TARGET_SAMPLE_RATE)
    for clip in normalized.clips:
        samples, sample_rate = _decode_clip(clip.base64_wav)
        assert sample_rate == TARGET_SAMPLE_RATE
        assert samples.ndim == 1
        assert len(samples) <= max_samples


def test_audio_at_exactly_the_90_s_cap_is_accepted_as_three_clips():
    normalized = normalize_audio_attachment(
        "at_cap.wav", _wav_pending(MAX_AUDIO_SECONDS)
    )

    assert normalized.accepted is True
    assert len(normalized.clips) == MAX_CLIPS_PER_FILE


def test_audio_one_sample_over_the_90_s_cap_is_rejected_after_decoding():
    # The planner's header probe is not the last line of defense: the cap
    # must hold against what was actually decoded. One extra sample past
    # 90 s would start a 4th window.
    frames = int(MAX_AUDIO_SECONDS * TARGET_SAMPLE_RATE) + 1
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.zeros(frames, dtype=np.float32),
        TARGET_SAMPLE_RATE,
        format="WAV",
        subtype="PCM_16",
    )
    pending = PendingAudioMedia(
        data=buffer.getvalue(),
        content_type="audio/wav",
        duration_seconds=MAX_AUDIO_SECONDS,
    )

    normalized = normalize_audio_attachment("over_cap.wav", pending)

    assert normalized.accepted is False
    assert normalized.clips == ()
    assert "exceeds" in normalized.rejection_reason
    assert "trim or split" in normalized.rejection_reason


# --- rejection --------------------------------------------------------------


def test_undecodable_bytes_are_rejected_with_a_deterministic_reason():
    pending = PendingAudioMedia(
        data=b"RIFF then garbage", content_type="audio/wav", duration_seconds=1.0
    )

    normalized = normalize_audio_attachment("broken.wav", pending)

    assert normalized.accepted is False
    assert normalized.clips == ()
    assert "could not decode audio" in normalized.rejection_reason
    assert "broken.wav" in normalized.rejection_reason


def test_zero_sample_audio_is_rejected():
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.zeros((0, 1), dtype=np.float32),
        TARGET_SAMPLE_RATE,
        format="WAV",
        subtype="PCM_16",
    )
    pending = PendingAudioMedia(
        data=buffer.getvalue(), content_type="audio/wav", duration_seconds=0.0
    )

    normalized = normalize_audio_attachment("silent.wav", pending)

    assert normalized.accepted is False
    assert "no samples" in normalized.rejection_reason


# --- media and cue composition ---------------------------------------------


def test_compose_audio_media_preserves_clip_order():
    normalized = normalize_audio_attachment("long.wav", _wav_pending(65.0))

    media = compose_audio_media(normalized)

    assert media == tuple(clip.base64_wav for clip in normalized.clips)
    assert len(media) == 3


def test_compose_audio_media_is_empty_for_a_rejected_attachment():
    normalized = NormalizedAudioAttachment(
        filename="broken.wav",
        accepted=False,
        rejection_reason="broken.wav: could not decode audio.",
    )

    assert compose_audio_media(normalized) == ()


def test_cue_for_a_single_clip_names_the_file_and_duration():
    normalized = normalize_audio_attachment("memo.wav", _wav_pending(2.0))

    assert compose_audio_cue(normalized) == "[Attached audio: memo.wav, 2.0 s]"


def test_cue_for_chunked_audio_names_the_clip_count():
    normalized = normalize_audio_attachment("long.wav", _wav_pending(65.0))

    cue = compose_audio_cue(normalized)

    assert cue == "[Attached audio: long.wav, 65.0 s, split into 3 clips]"


def test_cue_is_none_for_a_rejected_attachment():
    normalized = NormalizedAudioAttachment(
        filename="broken.wav",
        accepted=False,
        rejection_reason="broken.wav: could not decode audio.",
    )

    assert compose_audio_cue(normalized) is None


def test_uploaded_audio_cue_is_distinct_from_the_microphone_placeholder():
    from jarvis.app import VOICE_PLACEHOLDER_TEXT

    normalized = normalize_audio_attachment("memo.wav", _wav_pending(2.0))

    cue = compose_audio_cue(normalized)
    assert cue != VOICE_PLACEHOLDER_TEXT
    assert VOICE_PLACEHOLDER_TEXT not in cue
