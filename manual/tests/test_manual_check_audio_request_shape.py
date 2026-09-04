import base64
import io
import json
import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings, Settings
from jarvis.dialog.backend import OllamaBackend
from manual import manual_check_audio_request_shape as check
from manual.manual_check_audio_request_shape import (
    DEFAULT_MODELS,
    AudioFixture,
    TrialResult,
    build_conditions,
    build_payload,
    build_trial_plan,
    default_fixture_specs,
    normalize_text,
    run_experiment,
    sanitize_payload,
    score_transcript,
    summarize_trials,
)


def _backend() -> OllamaBackend:
    return OllamaBackend(
        EventBus(),
        BackendSettings(
            model="test-model",
            num_ctx=4096,
            temperature=0.0,
            seed=17,
            num_predict=64,
        ),
    )


def _fixture(key: str, reference_text: str | None = "слова") -> AudioFixture:
    return AudioFixture(
        key=key,
        path=Path(f"{key}.wav"),
        expected_bytes=44,
        reference_text=reference_text,
        reference_provenance=("human_edited" if reference_text else None),
    )


def test_default_models_are_the_three_owner_identified_variants():
    assert DEFAULT_MODELS == (
        "gemma4:12b-it-q4_K_M",
        "gemma4:12b-it-q8_0",
        "gemma4-12b-jarvis-free-mm:latest",
    )


def test_default_fixtures_use_existing_size_matched_replacements():
    fixtures = {fixture.key: fixture for fixture in default_fixture_specs(Path("root"))}

    first = fixtures["missing_long_turn_1_replacement"]
    second = fixtures["missing_long_turn_2_replacement"]
    assert first.expected_bytes == 304_044
    assert second.expected_bytes == 400_044
    assert first.expected_bytes + second.expected_bytes == 704_088
    assert first.replacement_for == (
        "20260805-231334-6d4bee/utterance-20260805-231334-0001.wav"
    )
    assert second.replacement_for == (
        "20260805-231334-6d4bee/utterance-20260805-231421-0002.wav"
    )
    assert first.reference_provenance == "human_edited_transcript_overlay"
    assert second.reference_text is None
    assert second.reference_provenance is None


def test_fixture_float32_variant_preserves_source_samples_and_format(tmp_path):
    wav_path = tmp_path / "fixture.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x80\x00\x00\xff\x7f")
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )

    prepared = check.inspect_fixture(fixture, wav_subtype="float32")

    source_samples, source_rate_hz = sf.read(
        wav_path,
        dtype="float32",
        always_2d=True,
    )
    encoded_samples, encoded_rate_hz = sf.read(
        io.BytesIO(base64.b64decode(prepared.audio_b64)),
        dtype="float32",
        always_2d=True,
    )
    info = sf.info(io.BytesIO(base64.b64decode(prepared.audio_b64)))
    assert source_rate_hz == encoded_rate_hz == 16_000
    np.testing.assert_array_equal(encoded_samples, source_samples)
    assert info.samplerate == 16_000
    assert info.channels == 1
    assert info.subtype == "FLOAT"
    assert prepared.metadata.sample_width_bytes == 4
    assert prepared.metadata.wav_subtype == "FLOAT"


def test_fixture_pcm16_default_preserves_source_bytes(tmp_path):
    wav_path = tmp_path / "fixture.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x80\x00\x00\xff\x7f")
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )

    prepared = check.inspect_fixture(fixture)

    assert base64.b64decode(prepared.audio_b64) == wav_path.read_bytes()
    assert prepared.metadata.wav_subtype == "PCM_16"
    assert prepared.metadata.peak_target is None
    assert prepared.metadata.applied_gain == 1.0
    assert prepared.metadata.leading_padding_seconds == 0.0
    assert prepared.metadata.trailing_padding_seconds == 0.0


def test_fixture_peak_target_amplifies_without_clipping(tmp_path):
    wav_path = tmp_path / "fixture.wav"
    samples = np.array([0.0, 0.1, -0.2, 0.05], dtype=np.float32)
    sf.write(wav_path, samples, 16_000, format="WAV", subtype="PCM_16")
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )

    prepared = check.inspect_fixture(fixture, peak_target=0.8, wav_subtype="float32")
    encoded_samples, _ = sf.read(
        io.BytesIO(base64.b64decode(prepared.audio_b64)),
        dtype="float32",
    )

    assert prepared.metadata.source_peak == pytest.approx(0.2, abs=1e-4)
    assert prepared.metadata.encoded_peak == pytest.approx(0.8, abs=1e-4)
    assert prepared.metadata.peak_target == 0.8
    assert prepared.metadata.applied_gain == pytest.approx(4.0, abs=1e-3)
    assert np.max(np.abs(encoded_samples)) <= 1.0


def test_fixture_min_duration_adds_symmetric_silence(tmp_path):
    wav_path = tmp_path / "fixture.wav"
    source_samples = np.ones(16_000, dtype=np.float32) * 0.25
    sf.write(wav_path, source_samples, 16_000, format="WAV", subtype="PCM_16")
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )

    prepared = check.inspect_fixture(
        fixture,
        min_duration_seconds=2.5,
        wav_subtype="float32",
    )
    encoded_samples, encoded_rate_hz = sf.read(
        io.BytesIO(base64.b64decode(prepared.audio_b64)),
        dtype="float32",
    )

    assert encoded_rate_hz == 16_000
    assert len(encoded_samples) == 40_000
    assert prepared.metadata.duration_seconds == 2.5
    assert prepared.metadata.leading_padding_seconds == 0.75
    assert prepared.metadata.trailing_padding_seconds == 0.75
    np.testing.assert_array_equal(encoded_samples[:12_000], np.zeros(12_000))
    np.testing.assert_allclose(encoded_samples[12_000:28_000], source_samples)
    np.testing.assert_array_equal(encoded_samples[28_000:], np.zeros(12_000))


def test_fixture_min_duration_can_add_deterministic_white_noise(tmp_path):
    wav_path = tmp_path / "fixture.wav"
    source_samples = np.ones(16_000, dtype=np.float32) * 0.25
    sf.write(wav_path, source_samples, 16_000, format="WAV", subtype="PCM_16")
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )

    first = check.inspect_fixture(
        fixture,
        min_duration_seconds=2.5,
        padding_mode="white-noise",
        padding_noise_rms=0.001,
        wav_subtype="float32",
    )
    second = check.inspect_fixture(
        fixture,
        min_duration_seconds=2.5,
        padding_mode="white-noise",
        padding_noise_rms=0.001,
        wav_subtype="float32",
    )
    encoded_samples, _ = sf.read(
        io.BytesIO(base64.b64decode(first.audio_b64)),
        dtype="float32",
    )

    assert first.audio_b64 == second.audio_b64
    assert first.metadata.padding_mode == "white-noise"
    assert first.metadata.padding_noise_rms == 0.001
    assert first.metadata.leading_padding_seconds == 0.75
    assert first.metadata.trailing_padding_seconds == 0.75
    assert float(np.sqrt(np.mean(np.square(encoded_samples[:12_000])))) == (
        pytest.approx(0.001, rel=0.1)
    )
    np.testing.assert_allclose(encoded_samples[12_000:28_000], source_samples)


def test_fixture_rejects_unknown_wav_subtype(tmp_path):
    wav_path = tmp_path / "fixture.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00")
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )

    with pytest.raises(ValueError, match="unknown WAV subtype"):
        check.inspect_fixture(fixture, wav_subtype="pcm24")


def test_normalization_preserves_words_and_removes_case_and_punctuation():
    assert normalize_text("  Ёж: СЛЫШИТ меня?!  ") == "еж слышит меня"


def test_transcript_score_counts_word_and_character_edits():
    score = score_transcript("раз два три", "Раз, два! четыре")

    assert score.reference_normalized == "раз два три"
    assert score.hypothesis_normalized == "раз два четыре"
    assert score.word_edits == 1
    assert score.wer == 1 / 3
    assert score.character_edits == 4
    assert score.cer == 4 / len("раз два три")
    assert score.exact_match is False


def test_empty_reference_edge_cases_are_explicit():
    assert score_transcript("", "").wer == 0.0
    assert score_transcript("", "invented").wer == 1.0


def test_conditions_isolate_system_and_tool_shape_changes():
    conditions = {item.key: item for item in build_conditions("full prompt")}

    assert conditions["bare_audio"].system_prompt is None
    assert conditions["empty_system_audio"].system_prompt == ""
    assert conditions["short_system_audio"].system_prompt == "You are Jarvis."
    assert conditions["configured_system_audio"].system_prompt == "full prompt"
    assert conditions["bare_audio_noop_tool"].include_noop_tool is True
    assert conditions["configured_system_audio_noop_tool"].include_noop_tool is True
    assert conditions["no_media_control"].include_audio is False


def test_payload_builder_uses_images_and_preserves_explicit_empty_system():
    audio_b64 = base64.b64encode(b"wav").decode("ascii")
    conditions = {item.key: item for item in build_conditions("full prompt")}

    payload = build_payload(
        _backend(),
        conditions["empty_system_audio"],
        audio_b64,
        num_gpu=99,
    )

    assert payload["stream"] is False
    assert payload["model"] == "test-model"
    assert payload["messages"][0] == {"role": "system", "content": ""}
    assert payload["messages"][-1]["images"] == [audio_b64]
    assert payload["options"]["num_gpu"] == 99
    assert "tools" not in payload


def test_payload_builder_rejects_non_positive_num_gpu_layers():
    with pytest.raises(ValueError, match="num_gpu must be at least 1"):
        build_payload(_backend(), build_conditions("full")[0], "YQ==", num_gpu=0)


def test_payload_builder_adds_one_noop_tool_and_negative_control_has_no_media():
    conditions = {item.key: item for item in build_conditions("full prompt")}

    with_tool = build_payload(_backend(), conditions["bare_audio_noop_tool"], "YQ==")
    no_media = build_payload(_backend(), conditions["no_media_control"], "YQ==")

    assert len(with_tool["tools"]) == 1
    assert with_tool["tools"][0]["function"]["name"] == "noop"
    assert all("images" not in message for message in no_media["messages"])


def test_trial_plan_is_balanced_deterministic_and_grouped_by_model():
    fixtures = (_fixture("one"), _fixture("two"))
    conditions = build_conditions("full")[:2]

    first = build_trial_plan(("m1", "m2"), fixtures, conditions, repeats=2, seed=9)
    second = build_trial_plan(("m1", "m2"), fixtures, conditions, repeats=2, seed=9)

    assert first == second
    assert len(first) == 16
    assert [trial.model for trial in first[:8]] == ["m1"] * 8
    assert [trial.model for trial in first[8:]] == ["m2"] * 8
    assert {
        (trial.fixture.key, trial.condition.key, trial.repeat_index)
        for trial in first[:8]
    } == {
        (fixture.key, condition.key, repeat_index)
        for fixture in fixtures
        for condition in conditions
        for repeat_index in (1, 2)
    }


def test_sanitized_payload_replaces_base64_with_hash_and_size():
    audio = b"wave bytes"
    payload = build_payload(
        _backend(),
        build_conditions("full")[0],
        base64.b64encode(audio).decode("ascii"),
    )

    sanitized = sanitize_payload(payload)

    [media] = sanitized["messages"][-1]["images"]
    assert media["decoded_bytes"] == len(audio)
    assert len(media["sha256"]) == 64
    assert "wave bytes" not in str(sanitized)


def test_summary_weights_each_fixture_equally_despite_repetition_count():
    rows = [
        TrialResult.scored("m", "c", "one", 1, 0.0, 0.0, True),
        TrialResult.scored("m", "c", "one", 2, 0.0, 0.0, True),
        TrialResult.scored("m", "c", "one", 3, 0.0, 0.0, True),
        TrialResult.scored("m", "c", "two", 1, 1.0, 1.0, False),
        TrialResult.unscored("m", "c", "diagnostic", 1),
    ]

    [summary] = summarize_trials(rows)

    assert summary["trial_count"] == 5
    assert summary["scored_trial_count"] == 4
    assert summary["scored_fixture_count"] == 2
    assert summary["mean_fixture_wer"] == 0.5
    assert summary["mean_fixture_cer"] == 0.5
    assert summary["mean_fixture_exact_match_rate"] == 0.5


@pytest.mark.asyncio
async def test_experiment_writes_complete_jsonl_with_injected_ollama(
    tmp_path, monkeypatch
):
    wav_path = tmp_path / "fixture.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 1_600)
    fixture = AudioFixture(
        key="fixture",
        path=wav_path,
        expected_bytes=wav_path.stat().st_size,
        reference_text="слова",
        reference_provenance="test_reference",
    )
    settings = Settings(
        backend=BackendSettings(model="ignored", endpoint="http://ollama.test")
    )

    async def fake_version(self):
        return {"version": "test"}

    async def fake_tags(self):
        return {"models": [{"name": "model-under-test", "digest": "abc"}]}

    async def fake_show(self, model):
        return {"model": model, "template": "template", "system": "baked"}

    async def fake_chat(self, payload):
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.7
        assert payload["options"]["num_gpu"] == 11
        media = payload["messages"][-1].get("images")
        if media is not None:
            [encoded_audio] = media
            assert (
                sf.info(io.BytesIO(base64.b64decode(encoded_audio))).subtype == "FLOAT"
            )
        return {"message": {"content": "слова"}, "done": True}

    monkeypatch.setattr(check, "load_settings", lambda: settings)
    monkeypatch.setattr(
        check.MemoryFileLoader,
        "compose_system_prompt",
        lambda self, prompt: prompt,
    )
    monkeypatch.setattr(check, "default_fixture_specs", lambda root: (fixture,))
    monkeypatch.setattr(check, "_git_state", lambda: {"commit": "test", "dirty": False})
    monkeypatch.setattr(check.OllamaGateway, "version", fake_version)
    monkeypatch.setattr(check.OllamaGateway, "tags", fake_tags)
    monkeypatch.setattr(check.OllamaGateway, "show", fake_show)
    monkeypatch.setattr(check.OllamaGateway, "chat", fake_chat)
    output_path = tmp_path / "results.jsonl"

    await run_experiment(
        output_path=output_path,
        journal_root=tmp_path,
        models=("model-under-test",),
        repeats=1,
        shuffle_seed=3,
        generation_seed=5,
        num_gpu=11,
        wav_subtype="float32",
        peak_target=0.89,
        min_duration_seconds=2.5,
        padding_mode="white-noise",
        padding_noise_rms=0.001,
        temperature=0.7,
        profile="deterministic",
    )

    records = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["record_type"] == "metadata"
    assert records[0]["schema_version"] == 3
    assert records[0]["models"][0]["name"] == "model-under-test"
    assert records[0]["requested_num_gpu_layers"] == 11
    assert records[0]["requested_temperature"] == 0.7
    assert records[0]["requested_wav_subtype"] == "FLOAT"
    assert records[0]["requested_peak_target"] == 0.89
    assert records[0]["requested_min_duration_seconds"] == 2.5
    assert records[0]["requested_padding_mode"] == "white-noise"
    assert records[0]["requested_padding_noise_rms"] == 0.001
    assert records[0]["models"][0]["effective_options"]["num_gpu"] == 11
    assert sum(record["record_type"] == "trial" for record in records) == 7
    assert records[-1]["record_type"] == "summary"
    encoded_audio = base64.b64encode(wav_path.read_bytes()).decode("ascii")
    assert encoded_audio not in output_path.read_text(encoding="utf-8")
