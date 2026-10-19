import argparse
import io
import json

import numpy as np
import pytest
import soundfile as sf

from manual import manual_check_stt_engines as harness
from manual.personal_proxy.stt_scoring import (
    Coexistence,
    Engine,
    EngineMetrics,
)


def _write_call(calls_dir, engine, subject, pass_no, transcript, seconds=1.0):
    path = harness.call_path(calls_dir, engine, subject, pass_no)
    harness.write_json(
        path,
        {
            "engine": engine.value,
            "subject_id": subject,
            "pass_no": pass_no,
            "transcript": transcript,
            "seconds": seconds,
            "audio_seconds": 4.0,
        },
    )


def _write_baseline(calls_dir, subject, text):
    calls_dir.mkdir(parents=True, exist_ok=True)
    (calls_dir / f"a_current-{subject}-s1.json").write_text(
        json.dumps(
            {"subject_id": subject, "seed": 1, "call": {"response_text": text}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _metrics(engine, failures=0, seconds=1.0):
    groups = {"numeric": (9, 10), "email": (0, 0), "person": (0, 0), "other": (0, 0)}
    return EngineMetrics(engine, 88, failures, 0.1, groups, seconds, seconds, 0.2)


def test_decode_returns_mono_float_samples_and_their_duration():
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(32000, dtype=np.float32), 16000, format="WAV")

    samples, seconds = harness.decode(buffer.getvalue())

    assert (samples.dtype, len(samples), seconds) == (np.float32, 32000, 2.0)


def test_decode_refuses_other_sample_rates():
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(8000, dtype=np.float32), 8000, format="WAV")

    with pytest.raises(ValueError, match="16 kHz"):
        harness.decode(buffer.getvalue())


def test_score_writes_a_report_from_saved_calls_and_baseline(tmp_path, capsys):
    out = tmp_path / "out"
    calls = out / "calls"
    calls.mkdir(parents=True)
    baseline = tmp_path / "baseline"
    _write_baseline(baseline, "id_short_call", "Позвони Марине Крыловой.")
    for pass_no in (1, 2):
        _write_call(
            calls, Engine.GIGAAM, "id_short_call", pass_no, "Позвони Марине Крыловой."
        )
        _write_call(calls, Engine.GIGAAM, "ctl_silence", pass_no, "Продолжение следует")

    code = harness.command_score(argparse.Namespace(out=out, baseline_calls=baseline))

    report = (out / "report.md").read_text(encoding="utf-8")
    assert code == 0
    assert "Outcome: **NONE_ADEQUATE**" in report
    assert "TEXT: 'Продолжение следует'" in report
    assert capsys.readouterr().out.startswith("# STT engines")


def test_score_without_calls_is_an_error(tmp_path):
    (tmp_path / "calls").mkdir()

    code = harness.command_score(
        argparse.Namespace(out=tmp_path, baseline_calls=tmp_path / "none")
    )

    assert code == 2


def test_an_engine_that_fails_only_on_resources_falls_back_to_its_cpu_run():
    metrics = {
        Engine.GIGAAM: _metrics(Engine.GIGAAM, failures=2, seconds=1.0),
        Engine.GIGAAM_CPU: _metrics(Engine.GIGAAM_CPU, failures=3, seconds=2.0),
    }
    spilled = {Engine.GIGAAM: Coexistence(Engine.GIGAAM, 1.0, 0.8, 1.0, 1.0, 1.0, 1.0)}

    chosen, verdict = harness.effective(
        Engine.GIGAAM, Engine.GIGAAM_CPU, metrics, spilled, 0.5
    )

    assert chosen.engine is Engine.GIGAAM_CPU
    assert verdict.adequate


def test_an_engine_that_fails_on_accuracy_does_not_fall_back():
    metrics = {
        Engine.GIGAAM: _metrics(Engine.GIGAAM, failures=20),
        Engine.GIGAAM_CPU: _metrics(Engine.GIGAAM_CPU, failures=1),
    }

    chosen, verdict = harness.effective(
        Engine.GIGAAM, Engine.GIGAAM_CPU, metrics, {}, 0.5
    )

    assert chosen.engine is Engine.GIGAAM
    assert not verdict.adequate


def test_an_engine_that_was_not_run_has_no_result():
    assert harness.effective(Engine.WHISPER_RU, Engine.WHISPER_RU_CPU, {}, {}, 0.5) == (
        None,
        None,
    )


def test_the_job_order_covers_passes_and_skips_the_no_media_control():
    from manual.personal_proxy.audio import control_audio
    from manual.personal_proxy.corpus import CONTROLS

    assert any(control_audio(c) is None for c in CONTROLS)
    assert harness.PASSES == (1, 2)


REFERENCE_REQUEST = {
    "model": "gemma4:12b-it-q8_0",
    "options": {
        "num_ctx": 65536,
        "kv_cache_type": "q8_0",
        "seed": 7,
        "num_predict": 2048,
    },
}


def test_probe_payload_keeps_reference_model_and_options_without_overrides():
    payload = harness.gemma_probe_payload(REFERENCE_REQUEST, model=None, num_ctx=None)

    assert payload["model"] == "gemma4:12b-it-q8_0"
    assert payload["options"]["num_ctx"] == 65536
    assert payload["options"]["kv_cache_type"] == "q8_0"


def test_probe_payload_overrides_model_and_context_size():
    payload = harness.gemma_probe_payload(
        REFERENCE_REQUEST, model="gemma4:12b", num_ctx=8192
    )

    assert payload["model"] == "gemma4:12b"
    assert payload["options"]["num_ctx"] == 8192
    assert payload["options"]["kv_cache_type"] == "q8_0"


def test_probe_payload_is_short_and_deterministic():
    payload = harness.gemma_probe_payload(REFERENCE_REQUEST, model=None, num_ctx=None)

    assert payload["options"]["seed"] == 1
    assert payload["options"]["num_predict"] == 32
    assert payload["stream"] is False
