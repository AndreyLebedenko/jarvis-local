import numpy as np
import pytest
import torch

from jarvis.personal_proxy.stt.clip_check import InvalidClipError
from jarvis.personal_proxy.stt.guarded_transcription import transcribe_guarded
from jarvis.personal_proxy.stt.silero_probabilities import (
    SAMPLE_RATE,
    WINDOW_SAMPLES,
    SileroSpeechProbabilities,
)
from jarvis.personal_proxy.stt.speech_guard import (
    NoSpeech,
    SpeechGuardError,
    SpeechProbabilities,
    speech_seconds,
)
from jarvis.personal_proxy.stt.stt_result import Transcription

WINDOW = 0.1
THRESHOLD = 0.5
MINIMUM = 0.3
CLIP = np.zeros(16000, dtype=np.float32)


class _RecordingEngine:
    def __init__(self):
        self.clips = []
        self.answer = Transcription(text="heard", words=(), segments=())

    def transcribe(self, clip):
        self.clips.append(clip)
        return self.answer


def _source(values):
    return lambda clip: SpeechProbabilities(values, WINDOW)


def _guarded(clip, engine, values, minimum=MINIMUM):
    return transcribe_guarded(
        clip,
        engine,
        _source(values),
        vad_threshold=THRESHOLD,
        minimum_speech_seconds=minimum,
    )


def test_speech_seconds_counts_the_windows_at_or_above_the_threshold():
    probabilities = SpeechProbabilities([0.49, 0.5, 0.9, 0.1], WINDOW)

    assert speech_seconds(probabilities, THRESHOLD) == pytest.approx(0.2)


def test_an_empty_series_holds_no_speech():
    assert speech_seconds(SpeechProbabilities([], WINDOW), THRESHOLD) == 0


def test_all_silence_never_reaches_the_engine():
    engine = _RecordingEngine()

    result = _guarded(CLIP, engine, [0.0] * 20)

    assert result == NoSpeech(speech_seconds=0, required_seconds=MINIMUM)
    assert engine.clips == []


def test_an_empty_clip_never_reaches_the_engine():
    engine = _RecordingEngine()

    result = _guarded(np.zeros(0, dtype=np.float32), engine, [])

    assert isinstance(result, NoSpeech)
    assert engine.clips == []


def test_speech_just_below_the_minimum_never_reaches_the_engine():
    engine = _RecordingEngine()

    result = _guarded(CLIP, engine, [0.9, 0.9, 0.0, 0.0])

    assert isinstance(result, NoSpeech)
    assert result.speech_seconds == pytest.approx(0.2)
    assert engine.clips == []


def test_speech_exactly_at_the_minimum_reaches_the_engine():
    engine = _RecordingEngine()

    result = _guarded(CLIP, engine, [0.9] * 4, minimum=4 * WINDOW)

    assert result is engine.answer
    assert engine.clips == [CLIP]


def test_all_speech_reaches_the_engine_with_the_clip_unchanged():
    engine = _RecordingEngine()

    result = _guarded(CLIP, engine, [0.95] * 10)

    assert result is engine.answer
    assert engine.clips[0] is CLIP


def test_scattered_windows_add_up_to_the_minimum():
    engine = _RecordingEngine()

    _guarded(CLIP, engine, [0.9, 0.0, 0.9, 0.0, 0.9])

    assert len(engine.clips) == 1


class _FakeSileroModel:
    def __init__(self, windows):
        self._windows = windows
        self.calls = []

    def audio_forward(self, samples, sample_rate):
        self.calls.append((samples, sample_rate))
        return torch.tensor([self._windows])


def test_the_adapter_turns_the_model_output_into_window_probabilities():
    model = _FakeSileroModel([0.1, 0.8, 0.9])
    clip = np.zeros(3 * WINDOW_SAMPLES, dtype=np.float32)

    result = SileroSpeechProbabilities(model)(clip)

    assert result.values == pytest.approx((0.1, 0.8, 0.9))
    assert result.window_seconds == pytest.approx(WINDOW_SAMPLES / SAMPLE_RATE)
    assert model.calls[0][1] == SAMPLE_RATE


def test_the_adapter_does_not_call_the_model_for_an_empty_clip():
    model = _FakeSileroModel([])

    result = SileroSpeechProbabilities(model)(np.zeros(0, dtype=np.float32))

    assert result.values == ()
    assert model.calls == []


def test_the_adapter_pads_a_clip_shorter_than_one_window():
    model = _FakeSileroModel([0.0])

    SileroSpeechProbabilities(model)(np.ones(100, dtype=np.float32))

    assert model.calls[0][0].shape[0] == WINDOW_SAMPLES


def test_the_real_vad_finds_no_speech_in_digital_silence_and_room_noise():
    source = SileroSpeechProbabilities()
    noise = np.random.default_rng(7).normal(0.0, 0.005, 3 * SAMPLE_RATE)

    silence_seconds = speech_seconds(
        source(np.zeros(2 * SAMPLE_RATE, dtype=np.float32)), THRESHOLD
    )
    noise_seconds = speech_seconds(source(noise.astype(np.float32)), THRESHOLD)

    assert silence_seconds == 0
    assert noise_seconds == 0


def test_the_real_vad_accepts_a_clip_shorter_than_one_window():
    result = SileroSpeechProbabilities()(np.zeros(10, dtype=np.float32))

    assert len(result.values) == 1


BAD_CLIPS = [
    pytest.param(np.zeros(1600, dtype=np.float64), "float64", id="float64"),
    pytest.param(np.zeros(1600, dtype=np.int16), "int16", id="int16"),
    pytest.param(np.zeros((1600, 2), dtype=np.float32), "(1600, 2)", id="stereo"),
    pytest.param(np.zeros((1600, 1), dtype=np.float32), "(1600, 1)", id="column"),
    pytest.param(np.array([0.0, np.nan, 0.1], dtype=np.float32), "NaN", id="nan"),
    pytest.param(np.array([0.0, np.inf, 0.1], dtype=np.float32), "infinite", id="inf"),
    pytest.param([0.0, 0.1], "list", id="not-an-array"),
]


@pytest.mark.parametrize(("clip", "named"), BAD_CLIPS)
def test_an_invalid_clip_is_refused_and_never_reaches_the_engine(clip, named):
    engine = _RecordingEngine()

    with pytest.raises(InvalidClipError, match=named):
        _guarded(clip, engine, [0.9] * 10)

    assert engine.clips == []


def test_the_message_names_what_was_expected_and_what_came():
    with pytest.raises(InvalidClipError) as raised:
        _guarded(np.zeros(5, dtype=np.int16), _RecordingEngine(), [0.9])

    assert "expected float32 mono, got int16 shape (5,)" in str(raised.value)


@pytest.mark.parametrize(("clip", "named"), BAD_CLIPS[:5])
def test_the_silero_adapter_applies_the_same_check(clip, named):
    model = _FakeSileroModel([0.9])

    with pytest.raises(InvalidClipError, match=named):
        SileroSpeechProbabilities(model)(clip)

    assert model.calls == []


def test_a_failing_probability_source_fails_closed_naming_only_the_type():
    engine = _RecordingEngine()

    def broken_source(clip):
        raise RuntimeError("secret-path C:/Users/someone/private")

    with pytest.raises(SpeechGuardError) as raised:
        transcribe_guarded(
            CLIP,
            engine,
            broken_source,
            vad_threshold=THRESHOLD,
            minimum_speech_seconds=MINIMUM,
        )

    assert "RuntimeError" in str(raised.value)
    assert "secret-path" not in str(raised.value)
    assert engine.clips == []


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_an_invalid_threshold_is_refused_and_never_reaches_the_engine(threshold):
    engine = _RecordingEngine()

    with pytest.raises(SpeechGuardError, match="vad_threshold"):
        transcribe_guarded(
            CLIP,
            engine,
            _source([0.9] * 10),
            vad_threshold=threshold,
            minimum_speech_seconds=MINIMUM,
        )

    assert engine.clips == []
