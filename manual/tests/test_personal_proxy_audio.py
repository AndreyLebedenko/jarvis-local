import io

import numpy as np
import pytest
import soundfile as sf

from manual.personal_proxy.audio import (
    ManifestEntry,
    WavDirectory,
    WavDirectoryError,
    control_audio,
    sha256_hex,
    wav_duration_seconds,
    wav_path,
    write_manifest,
)
from manual.personal_proxy.corpus import CONTROLS, CORPUS


def _wav(seconds=1.0, value=0.0):
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.full(int(16000 * seconds), value, dtype=np.float32),
        16000,
        format="WAV",
        subtype="PCM_16",
    )
    return buffer.getvalue()


def _record_all(directory):
    entries = []
    for index, utterance in enumerate(CORPUS):
        data = _wav(1.0, 0.001 * (index + 1))
        wav_path(directory, utterance.utterance_id).write_bytes(data)
        entries.append(
            ManifestEntry(utterance.utterance_id, sha256_hex(data), len(data), 1.0)
        )
    write_manifest(directory, entries)
    return entries


def test_silence_control_is_digital_silence_of_the_stated_length():
    control = next(c for c in CONTROLS if c.control_id == "ctl_silence")

    data = control_audio(control)

    assert wav_duration_seconds(data) == 2.0
    samples, _ = sf.read(io.BytesIO(data))
    assert not np.any(samples)


def test_noise_control_is_deterministic_non_silent_noise():
    control = next(c for c in CONTROLS if c.control_id == "ctl_noise")

    first, second = control_audio(control), control_audio(control)

    assert first == second
    samples, _ = sf.read(io.BytesIO(first))
    assert 0.003 < float(np.std(samples)) < 0.008
    assert wav_duration_seconds(first) == 3.0


def test_no_media_control_has_no_audio():
    control = next(c for c in CONTROLS if c.control_id == "ctl_no_media")

    assert control_audio(control) is None


def test_complete_directory_loads_and_serves_audio(tmp_path):
    _record_all(tmp_path)

    directory = WavDirectory(tmp_path)

    first = CORPUS[0].utterance_id
    assert directory.audio_for(first) == wav_path(tmp_path, first).read_bytes()
    assert directory.duration_for(first) == 1.0
    assert len(directory.set_hash()) == 64


def test_missing_manifest_is_refused(tmp_path):
    with pytest.raises(WavDirectoryError, match="manifest"):
        WavDirectory(tmp_path)


def test_missing_recording_is_refused(tmp_path):
    _record_all(tmp_path)
    wav_path(tmp_path, CORPUS[3].utterance_id).unlink()

    with pytest.raises(WavDirectoryError, match="missing recording"):
        WavDirectory(tmp_path)


def test_replaced_recording_is_refused(tmp_path):
    _record_all(tmp_path)
    wav_path(tmp_path, CORPUS[3].utterance_id).write_bytes(_wav(2.0))

    with pytest.raises(WavDirectoryError, match="differs from the manifest"):
        WavDirectory(tmp_path)


def test_recordings_of_another_corpus_are_refused(tmp_path):
    _record_all(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            '"corpus_fingerprint": "', '"corpus_fingerprint": "x'
        ),
        encoding="utf-8",
    )

    with pytest.raises(WavDirectoryError, match="different corpus"):
        WavDirectory(tmp_path)
