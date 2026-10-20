import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import numpy as np
import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy import stt_whisper
from jarvis.personal_proxy.stt_engine import (
    MissingSpeechDependencyError,
    SpeechDeviceError,
    SpeechEngineLoadError,
    SpeechModelUnavailableError,
)
from jarvis.personal_proxy.stt_result import Segment, Transcription, Word
from jarvis.personal_proxy.stt_whisper import FasterWhisperEngine, load_whisper_model


class _FakeWhisperModel:
    instances: ClassVar[list["_FakeWhisperModel"]] = []

    def __init__(self, model_name, **kwargs):
        self.model_name = model_name
        self.load_kwargs = kwargs
        self.transcribe_calls = []
        self.segments = []
        _FakeWhisperModel.instances.append(self)

    def transcribe(self, clip, **kwargs):
        self.transcribe_calls.append((clip, kwargs))
        return iter(self.segments), SimpleNamespace(language="ru")


def _segment(text, avg_logprob, no_speech_prob, compression_ratio, words):
    return SimpleNamespace(
        text=text,
        avg_logprob=avg_logprob,
        no_speech_prob=no_speech_prob,
        compression_ratio=compression_ratio,
        words=[
            SimpleNamespace(word=w, start=s, end=e, probability=p)
            for w, s, e, p in words
        ],
    )


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    _FakeWhisperModel.instances = []
    module = ModuleType("faster_whisper")
    module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return _FakeWhisperModel


@pytest.fixture
def cpu_settings():
    return PersonalProxySettings(stt_device="cpu")


def test_the_model_loads_from_local_files_only(fake_faster_whisper, cpu_settings):
    FasterWhisperEngine(cpu_settings)

    assert fake_faster_whisper.instances[0].load_kwargs["local_files_only"] is True


def test_model_device_and_precision_follow_the_settings(fake_faster_whisper):
    FasterWhisperEngine(PersonalProxySettings(stt_model="small", stt_device="cpu"))

    loaded = fake_faster_whisper.instances[0]
    assert loaded.model_name == "small"
    assert loaded.load_kwargs["device"] == "cpu"
    assert loaded.load_kwargs["compute_type"] == "int8"


def test_the_gpu_loads_in_float16(fake_faster_whisper, monkeypatch):
    monkeypatch.setattr(
        "jarvis.personal_proxy.stt_whisper._add_nvidia_dll_directories", lambda: None
    )

    FasterWhisperEngine(PersonalProxySettings(stt_device="cuda"))

    assert fake_faster_whisper.instances[0].load_kwargs["compute_type"] == "float16"


def test_decoding_uses_the_settings_measured_in_the_spikes(fake_faster_whisper):
    engine = FasterWhisperEngine(
        PersonalProxySettings(stt_device="cpu", stt_language="en")
    )
    clip = np.zeros(16000, dtype=np.float32)

    engine.transcribe(clip)

    given_clip, options = fake_faster_whisper.instances[0].transcribe_calls[0]
    assert given_clip is clip
    assert options == {
        "language": "en",
        "beam_size": 5,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "vad_filter": False,
        "word_timestamps": True,
    }


def test_the_result_carries_text_words_and_segment_signals(
    fake_faster_whisper, cpu_settings
):
    engine = FasterWhisperEngine(cpu_settings)
    fake_faster_whisper.instances[0].segments = [
        _segment(
            " one two",
            -0.2,
            0.01,
            1.1,
            [(" one", 0.0, 0.4, 0.9), (" two", 0.5, 0.9, 0.4)],
        ),
        _segment(" three ", -0.5, 0.02, 1.3, [(" three", 1.0, 1.4, 0.8)]),
    ]

    result = engine.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == Transcription(
        text="one two three",
        words=(
            Word("one", 0.0, 0.4, 0.9),
            Word("two", 0.5, 0.9, 0.4),
            Word("three", 1.0, 1.4, 0.8),
        ),
        segments=(
            Segment("one two", -0.2, 0.01, 1.1),
            Segment("three", -0.5, 0.02, 1.3),
        ),
    )


def test_a_segment_without_words_contributes_no_words(
    fake_faster_whisper, cpu_settings
):
    engine = FasterWhisperEngine(cpu_settings)
    bare = _segment("hello", -0.1, 0.0, 1.0, [])
    bare.words = None
    fake_faster_whisper.instances[0].segments = [bare]

    result = engine.transcribe(np.zeros(16000, dtype=np.float32))

    assert result.words == ()
    assert result.text == "hello"


def test_no_segments_give_an_empty_transcription(fake_faster_whisper, cpu_settings):
    engine = FasterWhisperEngine(cpu_settings)

    result = engine.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == Transcription(text="", words=(), segments=())


def test_a_missing_package_raises_an_actionable_typed_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    with pytest.raises(MissingSpeechDependencyError, match="requirements-stt.txt"):
        load_whisper_model("large-v3-turbo", "cpu")


def _install_failing_model(monkeypatch, error):
    class _Failing:
        def __init__(self, *args, **kwargs):
            raise error

    module = ModuleType("faster_whisper")
    module.WhisperModel = _Failing
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def test_weights_missing_from_the_cache_advise_the_setup_script(monkeypatch):
    _install_failing_model(monkeypatch, FileNotFoundError("not in the local cache"))

    with pytest.raises(SpeechModelUnavailableError) as raised:
        load_whisper_model("large-v3-turbo", "cpu")

    assert "setup_stt_model.py" in str(raised.value)
    assert "not in the local cache" in str(raised.value)


def test_an_unknown_model_name_is_a_model_error(monkeypatch):
    _install_failing_model(monkeypatch, ValueError("Invalid model size 'x'"))

    with pytest.raises(SpeechModelUnavailableError, match="Invalid model size"):
        load_whisper_model("x", "cpu")


def test_a_cuda_library_failure_is_a_device_error_without_setup_advice(monkeypatch):
    monkeypatch.setattr(stt_whisper, "_add_nvidia_dll_directories", lambda: None)
    _install_failing_model(
        monkeypatch, RuntimeError("Library cublas64_12.dll is not found")
    )

    with pytest.raises(SpeechDeviceError) as raised:
        load_whisper_model("large-v3-turbo", "cuda")

    message = str(raised.value)
    assert "cublas64_12.dll" in message
    assert "RuntimeError" in message
    assert 'stt_device = "cpu"' in message
    assert "setup_stt_model.py" not in message


def test_a_failure_on_the_cpu_is_a_device_error_without_the_gpu_hint(monkeypatch):
    _install_failing_model(monkeypatch, RuntimeError("unsupported compute type"))

    with pytest.raises(SpeechDeviceError) as raised:
        load_whisper_model("large-v3-turbo", "cpu")

    assert "unsupported compute type" in str(raised.value)
    assert "cuBLAS" not in str(raised.value)


def test_a_native_library_failure_while_importing_is_a_device_error(monkeypatch):
    class _BrokenModule:
        def __getattr__(self, name):
            raise OSError("DLL load failed")

    monkeypatch.setitem(sys.modules, "faster_whisper", _BrokenModule())

    with pytest.raises(SpeechDeviceError, match="DLL load failed"):
        load_whisper_model("large-v3-turbo", "cpu")


def test_both_load_errors_share_one_base_type():
    assert issubclass(MissingSpeechDependencyError, SpeechEngineLoadError)
    assert issubclass(SpeechModelUnavailableError, SpeechEngineLoadError)
    assert issubclass(SpeechDeviceError, SpeechEngineLoadError)


@pytest.fixture
def dll_registry(monkeypatch):
    added = []
    monkeypatch.setattr(stt_whisper, "_registered_dll_directories", {})
    monkeypatch.setattr(
        os, "add_dll_directory", lambda path: added.append(path) or path, raising=False
    )
    monkeypatch.setenv("PATH", "base")
    return added


def _fake_nvidia(root, *libraries):
    for library in libraries:
        (root / "nvidia" / library / "bin").mkdir(parents=True)
    return root


def test_dll_directories_are_found_in_every_given_site_packages(tmp_path, dll_registry):
    first = _fake_nvidia(tmp_path / "system", "cublas")
    second = _fake_nvidia(tmp_path / "user", "cudnn")

    stt_whisper._add_nvidia_dll_directories([first, second])

    assert sorted(dll_registry) == sorted(
        [
            str(first / "nvidia" / "cublas" / "bin"),
            str(second / "nvidia" / "cudnn" / "bin"),
        ]
    )
    assert str(first / "nvidia" / "cublas" / "bin") in os.environ["PATH"]


def test_a_repeated_call_adds_nothing_new(tmp_path, dll_registry):
    root = _fake_nvidia(tmp_path / "site", "cublas")

    stt_whisper._add_nvidia_dll_directories([root])
    path_after_first = os.environ["PATH"]
    stt_whisper._add_nvidia_dll_directories([root, root])

    assert len(dll_registry) == 1
    assert os.environ["PATH"] == path_after_first


def test_missing_nvidia_trees_are_skipped(tmp_path, dll_registry):
    stt_whisper._add_nvidia_dll_directories([tmp_path / "nothing"])

    assert dll_registry == []
    assert os.environ["PATH"] == "base"


def test_the_default_search_includes_the_user_site(monkeypatch):
    monkeypatch.setattr(stt_whisper.site, "getusersitepackages", lambda: "C:/user-site")

    assert Path("C:/user-site") in stt_whisper._site_packages_directories()


def test_importing_the_stage_without_the_optional_package_works():
    program = textwrap.dedent(
        """
        import sys

        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] == "faster_whisper":
                    raise ImportError("blocked for the test")

        sys.meta_path.insert(0, _Blocker())
        import jarvis.personal_proxy.guarded_transcription
        import jarvis.personal_proxy.silero_probabilities
        import jarvis.personal_proxy.stt_whisper

        assert "faster_whisper" not in sys.modules
        from jarvis.core.config import PersonalProxySettings
        from jarvis.personal_proxy.stt_engine import MissingSpeechDependencyError
        from jarvis.personal_proxy.stt_whisper import FasterWhisperEngine

        try:
            FasterWhisperEngine(PersonalProxySettings(stt_device="cpu"))
        except MissingSpeechDependencyError:
            print("typed-error")
        """
    )
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))

    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "typed-error"
