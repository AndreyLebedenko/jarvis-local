import asyncio
import io
import wave
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from jarvis.audio.tts import (
    BilingualTtsEngine,
    OrderedPlayback,
    SentenceBuffer,
    TtsEngine,
    TtsEngineLoadError,
    TtsEngineLoadFailed,
    TtsOutput,
    _append_wav_tail_silence,
)
from jarvis.audio.tts_factory import build_tts_engine
from jarvis.audio.tts_piper import (
    PiperEngine,
)
from jarvis.audio.tts_piper import (
    piper_chunks_to_wav_bytes as _piper_chunks_to_wav_bytes,
)
from jarvis.audio.tts_silero import (
    JitSileroModel as _JitSileroModel,
)
from jarvis.audio.tts_silero import (
    PackageSileroModel as _PackageSileroModel,
)
from jarvis.audio.tts_silero import (
    SileroEngine,
    TtsModelNotCachedError,
    normalize_numbers,
    transliterate_latin,
)
from jarvis.audio.tts_silero import (
    ensure_model_cached as _ensure_model_cached,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import PiperTtsSettings, SileroTtsSettings, TtsSettings
from jarvis.dialog.backend import LatencyMetrics, ResponseComplete, ResponseToken


class _FakeSileroModule:
    """Stands in for the real `silero` module: _ensure_model_cached only
    needs a `.__file__` attribute to derive the expected model path."""

    def __init__(self, package_dir) -> None:
        self.__file__ = str(package_dir / "__init__.py")


class _FakeEngine:
    """Echo engine: 'wav bytes' are just the sentence text, and an optional
    per-sentence delay simulates out-of-order completion of concurrent
    synthesis."""

    def __init__(self, delay_for: Callable[[str], float] | None = None) -> None:
        self.seen: list[tuple[str, str]] = []
        self._delay_for = delay_for

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        self.seen.append((text, language))
        if self._delay_for is not None:
            await asyncio.sleep(self._delay_for(text))
        return text.encode()


class _Int16Bytes:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def tobytes(self) -> bytes:
        return b"".join(
            value.to_bytes(2, "little", signed=True) for value in self._values
        )


class _FakePiperVoice:
    def __init__(self, chunks) -> None:
        self.texts: list[str] = []
        self.synthesis_configs = []
        self._chunks = chunks

    def synthesize(self, text: str, syn_config=None):
        self.texts.append(text)
        self.synthesis_configs.append(syn_config)
        return iter(self._chunks)


def _pcm_wav_bytes(sample_rate: int, frames: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _wav_frame_count(wav_bytes: bytes) -> int:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        return wav_file.getnframes()


def _fake_engine_builder(label: str, seen: list[tuple[str, str, str]]):
    class _NamedFakeEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            seen.append((label, text, language))
            return f"{label}:{text}".encode()

    return _NamedFakeEngine()


def test_silero_engine_satisfies_tts_engine_protocol():
    engine: TtsEngine = SileroEngine(SileroTtsSettings())

    assert engine is not None


def test_package_silero_model_receives_route_synthesis_parameters():
    calls = []

    class _RawModel:
        def apply_tts(self, **kwargs):
            calls.append(kwargs)
            return "audio"

    route = SileroTtsSettings(
        model="v5_ru",
        language="ru",
        speaker="eugene",
        sample_rate=24000,
        put_accent=True,
        put_yo=False,
    )

    result = _PackageSileroModel(_RawModel(), route).synthesize("Текст")

    assert result == "audio"
    assert calls == [
        {
            "text": "Текст",
            "speaker": "eugene",
            "sample_rate": 24000,
            "put_accent": True,
            "put_yo": False,
        }
    ]


def test_jit_silero_model_rejects_incompatible_sample_rate():
    with pytest.raises(ValueError, match="requires sample_rate 16000"):
        _JitSileroModel(
            object(),
            "symbols",
            16000,
            lambda **kwargs: [],
            SileroTtsSettings(model="baya_16khz", sample_rate=48000),
        )


async def test_silero_engine_caches_a_terminal_load_failure():
    load_count = 0

    def fail_load(route):
        nonlocal load_count
        del route
        load_count += 1
        raise FileNotFoundError("weights missing")

    engine = SileroEngine(SileroTtsSettings(), model_loader=fail_load)

    for _ in range(2):
        with pytest.raises(TtsEngineLoadError, match="weights missing"):
            await engine.synthesize("Текст")

    assert load_count == 1


def test_piper_engine_satisfies_tts_engine_protocol(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)
    engine: TtsEngine = PiperEngine(
        PiperTtsSettings(model=str(model_path), config_path=str(config_path))
    )

    assert engine is not None


def test_bilingual_tts_engine_routes_supported_languages_to_child_engines():
    seen: list[tuple[str, str, str]] = []
    engine = BilingualTtsEngine(
        {
            "ru": _fake_engine_builder("silero", seen),
            "en": _fake_engine_builder("piper", seen),
        }
    )

    assert (
        asyncio.run(engine.synthesize("Привет", language="ru"))
        == "silero:Привет".encode()
    )
    assert asyncio.run(engine.synthesize("Hello", language="en")) == b"piper:Hello"
    assert seen == [
        ("silero", "Привет", "ru"),
        ("piper", "Hello", "en"),
    ]


async def test_bilingual_tts_engine_rejects_unsupported_language_hint():
    engine = BilingualTtsEngine({"ru": _FakeEngine()})

    with pytest.raises(ValueError, match="Unsupported TTS language"):
        await engine.synthesize("Hallo", language="de")


async def test_tts_output_keeps_order_when_bilingual_engines_finish_out_of_order():
    played = []
    ru_engine = _FakeEngine(delay_for=lambda text: 0.05)
    en_engine = _FakeEngine(delay_for=lambda text: 0.01)
    router = BilingualTtsEngine({"ru": ru_engine, "en": en_engine})

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), engine=router, play=fake_play)
    await tts.on_token(ResponseToken(text="Привет. "))
    await tts.on_token(ResponseToken(text="Hello. "))
    await tts.wait_for_pending()

    assert played == ["Привет.", "Hello."]


def test_build_tts_engine_preserves_default_silero_only_behavior():
    engine = build_tts_engine(TtsSettings())

    assert isinstance(engine, SileroEngine)


def test_build_tts_engine_builds_configured_bilingual_route_with_injected_builders():
    seen: list[tuple[str, str]] = []
    settings = TtsSettings(
        languages={
            "ru": SileroTtsSettings(),
            "en": PiperTtsSettings(model="en.onnx"),
        }
    )

    engine = build_tts_engine(
        settings,
        engine_builders={
            "silero": lambda route: seen.append(("silero", route.model))
            or _FakeEngine(),
            "piper": lambda route: seen.append(("piper", route.model)) or _FakeEngine(),
        },
    )

    assert isinstance(engine, BilingualTtsEngine)
    assert seen == [("silero", "v3_1_ru"), ("piper", "en.onnx")]


def test_build_tts_engine_rejects_routes_that_do_not_cover_english():
    """Charset segmentation emits 'en' for any Latin run no matter what is
    configured, so a non-default routing table without an English route
    would fail at runtime on the first English word - reject it at
    startup instead."""
    settings = TtsSettings(languages={"ru": PiperTtsSettings(model="ru.onnx")})

    with pytest.raises(ValueError, match="Missing: en"):
        build_tts_engine(
            settings, engine_builders={"piper": lambda route: _FakeEngine()}
        )


def test_build_tts_engine_accepts_non_default_silero_model():
    settings = TtsSettings(
        languages={
            "ru": SileroTtsSettings(model="future_ru_model"),
            "en": SileroTtsSettings(model="v3_en", language="en", speaker="en_0"),
        }
    )

    engine = build_tts_engine(settings)

    assert isinstance(engine, BilingualTtsEngine)


# --- _ensure_model_cached (offline preflight check) ------------------------
#
# Two independent things are checked: the manifest/weights exist next to
# the code (repo_root-relative, via the injectable repo_root param - the
# real _load_model() call omits it and defaults to this file's own repo
# root), and the manifest is ALSO visible relative to the process's
# current working directory (a silero_tts() quirk with no override
# parameter - see _ensure_model_cached's docstring).


def _write_silero_manifest(path, model: str = "v3_1_ru") -> None:
    path.write_text(
        f"""
tts_models:
  ru:
    {model}:
      latest:
        package: https://models.example/{model}.pt
""",
        encoding="utf-8",
    )


def test_ensure_model_cached_raises_when_repo_manifest_missing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    model_dir = repo_root / "silero_pkg" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "v3_1_ru.pt").write_bytes(b"fake")
    # repo_root/latest_silero_models.yml deliberately not created
    monkeypatch.chdir(repo_root)

    with pytest.raises(TtsModelNotCachedError):
        _ensure_model_cached(
            _FakeSileroModule(repo_root / "silero_pkg"),
            SileroTtsSettings(),
            repo_root=repo_root,
        )


def test_ensure_model_cached_raises_when_model_weights_missing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_silero_manifest(repo_root / "latest_silero_models.yml")
    (repo_root / "silero_pkg").mkdir()
    # model/v3_1_ru.pt deliberately not created
    monkeypatch.chdir(repo_root)

    with pytest.raises(TtsModelNotCachedError):
        _ensure_model_cached(
            _FakeSileroModule(repo_root / "silero_pkg"),
            SileroTtsSettings(),
            repo_root=repo_root,
        )


def test_ensure_model_cached_raises_when_cwd_lacks_manifest(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "silero_pkg" / "model").mkdir(parents=True)
    (repo_root / "silero_pkg" / "model" / "v3_1_ru.pt").write_bytes(b"fake")
    _write_silero_manifest(repo_root / "latest_silero_models.yml")

    launched_from = tmp_path / "elsewhere"
    launched_from.mkdir()
    monkeypatch.chdir(launched_from)  # process launched from a different directory

    with pytest.raises(TtsModelNotCachedError):
        _ensure_model_cached(
            _FakeSileroModule(repo_root / "silero_pkg"),
            SileroTtsSettings(),
            repo_root=repo_root,
        )


def test_ensure_model_cached_passes_when_everything_lines_up(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    model_dir = repo_root / "silero_pkg" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "v3_1_ru.pt").write_bytes(b"fake")
    _write_silero_manifest(repo_root / "latest_silero_models.yml")
    monkeypatch.chdir(repo_root)  # launched from the repo root, as documented

    _ensure_model_cached(
        _FakeSileroModule(repo_root / "silero_pkg"),
        SileroTtsSettings(),
        repo_root=repo_root,
    )  # must not raise


def test_ensure_model_cached_uses_manifest_asset_name(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    model_dir = repo_root / "silero_pkg" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "actual-weights.pt").write_bytes(b"fake")
    (repo_root / "latest_silero_models.yml").write_text(
        """
tts_models:
  ru:
    future_model:
      latest:
        package: https://models.example/actual-weights.pt
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo_root)

    _ensure_model_cached(
        _FakeSileroModule(repo_root / "silero_pkg"),
        SileroTtsSettings(model="future_model"),
        repo_root=repo_root,
    )


# --- PiperEngine ------------------------------------------------------------


def _write_piper_model_pair(tmp_path):
    model_path = tmp_path / "voice.onnx"
    config_path = tmp_path / "voice.onnx.json"
    model_path.write_bytes(b"model")
    config_path.write_text("{}", encoding="utf-8")
    return model_path, config_path


def _piper_chunk(sample_rate: int, values: list[int]):
    return SimpleNamespace(
        sample_rate=sample_rate,
        audio_int16_array=_Int16Bytes(values),
    )


def test_piper_engine_constructor_does_not_probe_model_paths(tmp_path):
    route = PiperTtsSettings(
        model=str(tmp_path / "missing.onnx"),
        config_path=str(tmp_path / "missing.json"),
    )

    engine = PiperEngine(route)

    assert engine is not None


async def test_piper_engine_reports_missing_model_on_first_synthesis(tmp_path):
    engine = PiperEngine(PiperTtsSettings(model=str(tmp_path / "missing.onnx")))

    with pytest.raises(TtsEngineLoadError, match="Piper model file does not exist"):
        await engine.synthesize("hello", language="en")


async def test_piper_engine_synthesize_returns_wav_bytes_from_chunk_api(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)
    voice = _FakePiperVoice([_piper_chunk(22050, [0, 100, -100, 0])])
    load_calls = []

    def load_voice(*, model_path, config_path, use_cuda, espeak_data_dir, download_dir):
        load_calls.append(
            (model_path, config_path, use_cuda, espeak_data_dir, download_dir)
        )
        return voice

    route = PiperTtsSettings(
        model=str(model_path),
        config_path=str(config_path),
        use_cuda=True,
        espeak_data_dir="espeak-data",
        download_dir="resources",
        speaker_id=3,
        length_scale=0.9,
        noise_scale=0.6,
        noise_w_scale=0.7,
        normalize_audio=False,
        volume=0.8,
    )
    engine = PiperEngine(route, voice_loader=load_voice)

    wav_bytes = await engine.synthesize("hello", language="en")

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 22050
        assert wav_file.readframes(4) == _Int16Bytes([0, 100, -100, 0]).tobytes()
    assert voice.texts == ["hello"]
    assert load_calls == [(model_path, config_path, True, "espeak-data", "resources")]
    synthesis_config = voice.synthesis_configs[0]
    assert synthesis_config.speaker_id == 3
    assert synthesis_config.length_scale == 0.9
    assert synthesis_config.noise_scale == 0.6
    assert synthesis_config.noise_w_scale == 0.7
    assert synthesis_config.normalize_audio is False
    assert synthesis_config.volume == 0.8


async def test_piper_engine_loads_voice_only_once(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)
    voice = _FakePiperVoice([_piper_chunk(22050, [0])])
    load_count = 0

    def load_voice(*, model_path, config_path, use_cuda, espeak_data_dir, download_dir):
        nonlocal load_count
        del model_path, config_path, use_cuda, espeak_data_dir, download_dir
        load_count += 1
        return voice

    engine = PiperEngine(
        PiperTtsSettings(model=str(model_path), config_path=str(config_path)),
        voice_loader=load_voice,
    )
    await engine.synthesize("one", language="en")
    await engine.synthesize("two", language="en")

    assert load_count == 1


def test_piper_chunks_are_encoded_as_readable_wav_bytes():
    wav_bytes = _piper_chunks_to_wav_bytes([_piper_chunk(22050, [0, 100, -100, 0])])

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 22050
        assert wav_file.readframes(4) == _Int16Bytes([0, 100, -100, 0]).tobytes()


def test_piper_chunks_reject_empty_output():
    with pytest.raises(RuntimeError, match="no audio chunks"):
        _piper_chunks_to_wav_bytes([])


def test_piper_chunks_reject_mixed_sample_rates():
    chunks = [
        _piper_chunk(22050, [0]),
        _piper_chunk(16000, [0]),
    ]

    with pytest.raises(RuntimeError, match="mixed sample rates"):
        _piper_chunks_to_wav_bytes(chunks)


# --- normalize_numbers -----------------------------------------------------


def test_normalize_numbers_converts_decimal_to_words():
    assert (
        normalize_numbers("число 3.14 и всё")
        == "число три целых четырнадцать сотых и всё"
    )


def test_normalize_numbers_converts_decimal_with_comma_to_words():
    assert (
        normalize_numbers("число 3,14 и всё")
        == "число три целых четырнадцать сотых и всё"
    )


def test_normalize_numbers_converts_integer_to_words():
    assert normalize_numbers("у меня 5 яблок") == "у меня пять яблок"


def test_normalize_numbers_leaves_text_without_digits_unchanged():
    text = "тут нет цифр вообще"
    assert normalize_numbers(text) == text


# --- transliterate_latin -----------------------------------------------------


def test_transliterate_latin_converts_a_simple_word():
    """Regression test for a real bug (task-07 manual handoff): asked to
    say the English word "gemma4" aloud, Silero spoke the digit ("four",
    via normalize_numbers) but silently dropped "gemma" entirely - its
    v3_1_ru symbol set has no Latin characters at all, same root cause
    class as the earlier digit-stripping bug."""
    assert transliterate_latin("gemma") == "гемма"


def test_transliterate_latin_handles_common_digraphs():
    assert transliterate_latin("sushi") == "суши"
    assert transliterate_latin("photo") == "фото"


def test_transliterate_latin_is_case_insensitive():
    assert transliterate_latin("GEMMA") == "гемма"


def test_transliterate_latin_leaves_cyrillic_and_digits_unchanged():
    assert transliterate_latin("привет 42") == "привет 42"


def test_transliterate_latin_only_touches_latin_runs_within_a_sentence():
    assert transliterate_latin("модель gemma работает") == "модель гемма работает"


# --- SentenceBuffer -----------------------------------------------------


def test_feed_returns_complete_sentence_with_trailing_whitespace():
    buffer = SentenceBuffer()

    sentences = buffer.feed("Привет, как дела? Продолжение.")

    assert sentences == ["Привет, как дела?"]


def test_feed_handles_incremental_tokens_across_calls():
    buffer = SentenceBuffer()

    assert buffer.feed("Привет") == []
    assert buffer.feed(", как ") == []
    assert buffer.feed("дела?") == []
    assert buffer.feed(" Дальше.") == ["Привет, как дела?"]


def test_feed_does_not_split_on_decimal_number():
    buffer = SentenceBuffer()

    sentences = buffer.feed("Значение равно 3.14 и это важно. Дальше текст.")

    assert sentences == ["Значение равно 3.14 и это важно."]


def test_feed_does_not_split_on_known_abbreviation():
    buffer = SentenceBuffer()

    # trailing space after the last sentence: a boundary is only ever
    # recognized once it is followed by whitespace already in the buffer
    # (see module docstring - avoids splitting on a token boundary that
    # might turn out to be a decimal point once more text arrives).
    sentences = buffer.feed("Он пришёл, т.е. опоздал. Все ждали. ")

    assert sentences == ["Он пришёл, т.е. опоздал.", "Все ждали."]


def test_feed_treats_ellipsis_as_a_boundary():
    buffer = SentenceBuffer()

    sentences = buffer.feed("Хм... даже не знаю. Ладно. ")

    assert sentences == ["Хм...", "даже не знаю.", "Ладно."]


def test_feed_does_not_emit_a_final_sentence_without_trailing_whitespace():
    """A boundary is only recognized once followed by whitespace already
    in the buffer - the dot at the very end of a feed() call might still
    turn out to be a decimal point once more text arrives. flush() is
    what closes out a response's final sentence."""
    buffer = SentenceBuffer()

    sentences = buffer.feed("Первое. Последнее без пробела в конце.")

    assert sentences == ["Первое."]


def test_flush_returns_trailing_partial_sentence():
    buffer = SentenceBuffer()
    buffer.feed("Незаконченная мысль без точки")

    assert buffer.flush() == "Незаконченная мысль без точки"


def test_flush_returns_none_for_empty_buffer():
    buffer = SentenceBuffer()
    buffer.feed("Готово. ")
    buffer.feed("")

    # the complete sentence was already returned by feed(); nothing left
    assert buffer.flush() is None


# --- OrderedPlayback -----------------------------------------------------


async def test_playback_plays_in_order_when_submitted_in_order():
    played = []

    async def player(index: int, audio: bytes) -> None:
        played.append(audio)

    playback = OrderedPlayback(player)
    await playback.submit(0, b"A")
    await playback.submit(1, b"B")

    assert played == [b"A", b"B"]


async def test_playback_reorders_when_submitted_out_of_order():
    played = []

    async def player(index: int, audio: bytes) -> None:
        played.append(audio)

    playback = OrderedPlayback(player)
    await playback.submit(1, b"B")
    assert played == []  # buffered, waiting for index 0

    await playback.submit(0, b"A")

    assert played == [b"A", b"B"]


async def test_playback_passes_the_unit_index_to_the_player():
    played = []

    async def player(index: int, audio: bytes) -> None:
        played.append((index, audio))

    playback = OrderedPlayback(player)
    await playback.submit(0, b"A")
    await playback.submit(1, b"B")

    assert played == [(0, b"A"), (1, b"B")]


async def test_playback_skips_none_audio_without_stalling_later_units():
    """A failed synthesis submits None for its index; playback must
    advance past it instead of buffering every later unit forever."""
    played = []

    async def player(index: int, audio: bytes) -> None:
        played.append(audio)

    playback = OrderedPlayback(player)
    await playback.submit(1, b"B")
    assert played == []  # buffered, waiting for index 0

    await playback.submit(0, None)

    assert played == [b"B"]


async def test_playback_reorders_under_concurrent_completion():
    played = []

    async def player(index: int, audio: bytes) -> None:
        played.append(audio)

    playback = OrderedPlayback(player)

    async def submit_after_delay(index: int, audio: bytes, delay: float) -> None:
        await asyncio.sleep(delay)
        await playback.submit(index, audio)

    # sentence 0 "finishes synthesizing" after sentence 1, out of order
    await asyncio.gather(
        submit_after_delay(1, b"B", delay=0.01),
        submit_after_delay(0, b"A", delay=0.05),
    )

    assert played == [b"A", b"B"]


# --- TtsOutput ------------------------------------------------------------


async def test_on_token_schedules_sentences_and_plays_them_in_order():
    played = []
    engine = _FakeEngine(
        delay_for=lambda sentence: 0.05 if sentence.startswith("Первое") else 0.01
    )

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), engine=engine, play=fake_play)

    await tts.on_token(ResponseToken(text="Первое предложение. "))
    await tts.on_token(ResponseToken(text="Второе предложение. "))
    await tts.wait_for_pending()

    assert played == ["Первое предложение.", "Второе предложение."]


async def test_on_response_complete_flushes_and_schedules_trailing_sentence():
    played = []

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), engine=_FakeEngine(), play=fake_play)

    await tts.on_token(ResponseToken(text="Без точки в конце"))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.wait_for_pending()

    assert played == ["Без точки в конце"]


def test_append_wav_tail_silence_extends_audio_duration():
    wav_bytes = _pcm_wav_bytes(sample_rate=10, frames=2)

    padded = _append_wav_tail_silence(wav_bytes, seconds=0.3)

    assert _wav_frame_count(padded) == 5


class _TinyWavEngine:
    """Returns a 2-frame wav at a tiny sample rate, so the 1.0 s tail guard
    adds exactly sample_rate frames and frame counts stay assertable."""

    def __init__(self, sample_rate: int = 10) -> None:
        self.sample_rate = sample_rate

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        del text, language
        await asyncio.sleep(0)
        return _pcm_wav_bytes(sample_rate=self.sample_rate, frames=2)


def _default_playback_tts_with_captured_audio(
    engine, captured: list[bytes]
) -> TtsOutput:
    """TtsOutput on the default-playback path (play=None, so the tail
    guard is active) with the hardware sounddevice call stubbed out."""
    tts = TtsOutput(TtsSettings(), engine=engine)

    async def capture(audio: bytes) -> None:
        captured.append(audio)

    tts._play = capture
    return tts


async def test_on_response_complete_pads_the_final_default_playback_unit():
    captured: list[bytes] = []
    tts = _default_playback_tts_with_captured_audio(_TinyWavEngine(), captured)

    await tts.on_token(ResponseToken(text="Финальная фраза."))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.wait_for_pending()

    assert len(captured) == 1
    assert _wav_frame_count(captured[0]) == 12


async def test_tail_guard_pads_currently_last_unit_even_before_response_complete():
    """Regression for the live-observed race: the final sentence can be
    flushed mid-stream by on_token and finish synthesis before
    ResponseComplete arrives, so finality cannot be decided against state
    recorded by on_response_complete. The guard decides at play time
    instead: a unit with no later unit scheduled yet gets the tail."""
    captured: list[bytes] = []
    tts = _default_playback_tts_with_captured_audio(_TinyWavEngine(), captured)

    await tts.on_token(ResponseToken(text="Фраза целиком. "))
    await tts.wait_for_pending()  # played before any ResponseComplete

    assert len(captured) == 1
    assert _wav_frame_count(captured[0]) == 12


async def test_tail_guard_skips_units_with_a_later_unit_already_scheduled():
    captured: list[bytes] = []
    tts = _default_playback_tts_with_captured_audio(_TinyWavEngine(), captured)

    await tts.on_token(ResponseToken(text="Первая фраза. Вторая фраза. "))
    await tts.wait_for_pending()

    assert [_wav_frame_count(audio) for audio in captured] == [2, 12]


async def test_tail_guard_does_not_touch_injected_playback():
    played = []

    async def fake_play(audio: bytes) -> None:
        played.append(audio)

    tts = TtsOutput(TtsSettings(), engine=_TinyWavEngine(), play=fake_play)

    await tts.on_token(ResponseToken(text="Фраза целиком. "))
    await tts.wait_for_pending()

    assert [_wav_frame_count(audio) for audio in played] == [2]


async def test_failed_synthesis_is_skipped_and_later_units_still_play(caplog):
    """Regression for the silent-stall risk: an engine exception must not
    leave OrderedPlayback waiting forever on the failed index, killing all
    speech for the rest of the session. The failed unit is logged and
    skipped; every later unit still plays."""

    class _FlakyEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            if text.startswith("Первая"):
                raise RuntimeError("Piper returned no audio chunks")
            return text.encode()

    played = []

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), engine=_FlakyEngine(), play=fake_play)

    with caplog.at_level("ERROR", logger="tts"):
        await tts.on_token(ResponseToken(text="Первая фраза. Вторая фраза. "))
        await tts.wait_for_pending()

    assert played == ["Вторая фраза."]
    assert "TTS synthesis failed" in caplog.text


async def test_engine_load_failure_is_published_once_with_route_context(caplog):
    class _UnavailableEngine:
        async def synthesize(self, text: str, language: str = "ru") -> bytes:
            del text, language
            raise TtsEngineLoadError("silero", "future_ru", "weights missing")

    bus = EventBus()
    failures: list[TtsEngineLoadFailed] = []

    async def record(event: TtsEngineLoadFailed) -> None:
        failures.append(event)

    bus.subscribe(TtsEngineLoadFailed, record)
    tts = TtsOutput(
        TtsSettings(), engine=_UnavailableEngine(), play=_silent_play, bus=bus
    )

    with caplog.at_level("ERROR", logger="tts"):
        await tts.on_token(ResponseToken(text="Первая фраза. Вторая фраза. "))
        await tts.wait_for_pending()

    assert failures == [
        TtsEngineLoadFailed(
            language="ru",
            engine="silero",
            model="future_ru",
            message="weights missing",
        )
    ]
    assert caplog.text.count("TTS engine load failed") == 1


async def test_tts_output_uses_injected_engine_for_synthesis():
    played = []
    engine = _FakeEngine()

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), engine=engine, play=fake_play)

    await tts.on_token(ResponseToken(text="Фраза готова. "))
    await tts.wait_for_pending()

    assert engine.seen == [("Фраза готова.", "ru")]
    assert played == ["Фраза готова."]


# --- charset language segmentation (story-v1.2.8 pivot) ---------------------
#
# Language segmentation now happens deterministically from character sets
# before sentence buffering. The model emits plain text; Jarvis splits
# Cyrillic as Russian and Latin-script runs as English.


async def _speak_tokens(engine, *tokens: str) -> None:
    tts = TtsOutput(TtsSettings(), engine=engine, play=_silent_play)
    for token in tokens:
        await tts.on_token(ResponseToken(text=token))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.wait_for_pending()


async def _silent_play(audio: bytes) -> None:
    del audio


async def test_plain_russian_text_routes_to_russian():
    engine = _FakeEngine()

    await _speak_tokens(engine, "Привет. Как дела?")

    assert engine.seen == [("Привет.", "ru"), ("Как дела?", "ru")]


async def test_plain_mixed_language_text_decomposes_into_ordered_language_units():
    engine = _FakeEngine()

    await _speak_tokens(
        engine,
        "Ответ: blank verse без рифмы.",
    )

    assert engine.seen == [
        ("Ответ:", "ru"),
        ("blank verse", "en"),
        ("без рифмы.", "ru"),
    ]


async def test_latin_identifier_survives_token_split():
    engine = _FakeEngine()

    await _speak_tokens(engine, "Функция par", "se_user_id готова.")

    assert engine.seen == [
        ("Функция", "ru"),
        ("parse_user_id", "en"),
        ("готова.", "ru"),
    ]


async def test_english_span_crossing_a_sentence_boundary_keeps_its_language():
    engine = _FakeEngine()

    await _speak_tokens(
        engine,
        "First one. Second one.",
    )

    assert engine.seen == [("First one.", "en"), ("Second one.", "en")]


async def test_http_terms_with_punctuation_stay_in_english_unit():
    engine = _FakeEngine()

    await _speak_tokens(
        engine,
        "HTTP/2, WebSocket, REST: когда что выбрать?",
    )

    assert engine.seen == [
        ("HTTP/2, WebSocket, REST:", "en"),
        ("когда что выбрать?", "ru"),
    ]


async def test_short_russian_connective_between_english_words_is_carried():
    """Single-engine (default Silero-only) settings: prosody wins, the
    short connective rides along into the next unit - Silero's
    transliteration can voice either language."""
    engine = _FakeEngine()

    await _speak_tokens(engine, "Love и Dove.")

    assert engine.seen == [("Love", "en"), ("и Dove.", "en")]


async def test_connectives_stay_in_their_own_language_when_engines_differ():
    """Regression for the v1.2.9 task-4 live finding: with distinct
    per-language engines, a carried Russian connective ("Для", "и",
    "без") lands in Piper, which has no Cyrillic phonemes and spells it
    out letter by letter. With multi-engine routes every language run
    must reach its own engine, even a short one."""
    bilingual_settings = TtsSettings(
        languages={
            "ru": SileroTtsSettings(),
            "en": PiperTtsSettings(model="en.onnx"),
        }
    )
    ru_engine = _FakeEngine()
    en_engine = _FakeEngine()
    router = BilingualTtsEngine({"ru": ru_engine, "en": en_engine})
    tts = TtsOutput(bilingual_settings, engine=router, play=_silent_play)

    await tts.on_token(ResponseToken(text="Для APIClient важны latency."))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.wait_for_pending()

    assert ru_engine.seen == [("Для", "ru"), ("важны", "ru")]
    assert en_engine.seen == [("APIClient", "en"), ("latency.", "en")]


async def test_second_turn_starts_fresh_after_english_text():
    engine = _FakeEngine()
    tts = TtsOutput(TtsSettings(), engine=engine, play=_silent_play)

    await tts.on_token(ResponseToken(text="Unclosed tail"))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.on_token(ResponseToken(text="Снова по-русски."))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0,
                prompt_eval_seconds=0.0,
                eval_seconds=0.0,
                eval_count=0,
            )
        )
    )
    await tts.wait_for_pending()

    assert engine.seen == [("Unclosed tail", "en"), ("Снова по-русски.", "ru")]
