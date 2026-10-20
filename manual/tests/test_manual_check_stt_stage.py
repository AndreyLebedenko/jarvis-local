import numpy as np
import soundfile as sf

from jarvis.personal_proxy.stt_result import Transcription
from manual import manual_check_stt_stage as harness


def _write_silent_wav(directory, name):
    sf.write(directory / f"{name}.wav", np.zeros(16000, dtype=np.float32), 16000)


def test_guard_lists_every_control_and_recording_with_a_verdict(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_silent_wav(tmp_path, "quiet_one")

    harness.main(
        ["--config", str(tmp_path / "none.toml"), "guard", "--wavs", str(tmp_path)]
    )

    output = capsys.readouterr().out
    assert "ctl_silence" in output
    assert "ctl_noise" in output
    assert "quiet_one" in output
    assert "NO SPEECH" in output
    assert "stt_min_speech_seconds = 0.3" in output


def test_transcribe_never_calls_the_engine_for_the_controls(
    tmp_path, capsys, monkeypatch
):
    calls = []

    class _Engine:
        def __init__(self, settings):
            pass

        def transcribe(self, clip):
            calls.append(clip)
            return Transcription(text="", words=(), segments=())

    monkeypatch.setattr(harness, "FasterWhisperEngine", _Engine)
    _write_silent_wav(tmp_path, "quiet_one")

    harness.main(
        ["--config", str(tmp_path / "none.toml"), "transcribe", "--wavs", str(tmp_path)]
    )

    assert calls == []
    assert capsys.readouterr().out.count("engine not called") == 3
