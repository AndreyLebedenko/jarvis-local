import asyncio
import io
import wave
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from backend import LatencyMetrics, ResponseComplete, ResponseToken
from config import TtsSettings
from tts import (
    OrderedPlayback,
    PiperEngine,
    SileroEngine,
    SentenceBuffer,
    TtsEngine,
    TtsModelNotCachedError,
    TtsOutput,
    _piper_chunks_to_wav_bytes,
    _ensure_model_cached,
    normalize_numbers,
    transliterate_latin,
)


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
        return b"".join(value.to_bytes(2, "little", signed=True) for value in self._values)


class _FakePiperVoice:
    def __init__(self, chunks) -> None:
        self.texts: list[str] = []
        self._chunks = chunks

    def synthesize(self, text: str):
        self.texts.append(text)
        return iter(self._chunks)


def test_silero_engine_satisfies_tts_engine_protocol():
    engine: TtsEngine = SileroEngine(TtsSettings())

    assert engine is not None


def test_piper_engine_satisfies_tts_engine_protocol(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)
    engine: TtsEngine = PiperEngine(model_path, config_path=config_path)

    assert engine is not None


# --- _ensure_model_cached (offline preflight check) ------------------------
#
# Two independent things are checked: the manifest/weights exist next to
# the code (repo_root-relative, via the injectable repo_root param - the
# real _load_model() call omits it and defaults to this file's own repo
# root), and the manifest is ALSO visible relative to the process's
# current working directory (a silero_tts() quirk with no override
# parameter - see _ensure_model_cached's docstring).


def test_ensure_model_cached_raises_when_repo_manifest_missing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    model_dir = repo_root / "silero_pkg" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "v3_1_ru.pt").write_bytes(b"fake")
    # repo_root/latest_silero_models.yml deliberately not created
    monkeypatch.chdir(repo_root)

    with pytest.raises(TtsModelNotCachedError):
        _ensure_model_cached(
            _FakeSileroModule(repo_root / "silero_pkg"), repo_root=repo_root
        )


def test_ensure_model_cached_raises_when_model_weights_missing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "latest_silero_models.yml").write_text("fake manifest", encoding="utf-8")
    (repo_root / "silero_pkg").mkdir()
    # model/v3_1_ru.pt deliberately not created
    monkeypatch.chdir(repo_root)

    with pytest.raises(TtsModelNotCachedError):
        _ensure_model_cached(
            _FakeSileroModule(repo_root / "silero_pkg"), repo_root=repo_root
        )


def test_ensure_model_cached_raises_when_cwd_lacks_manifest(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    (repo_root / "silero_pkg" / "model").mkdir(parents=True)
    (repo_root / "silero_pkg" / "model" / "v3_1_ru.pt").write_bytes(b"fake")
    (repo_root / "latest_silero_models.yml").write_text("fake manifest", encoding="utf-8")

    launched_from = tmp_path / "elsewhere"
    launched_from.mkdir()
    monkeypatch.chdir(launched_from)  # process launched from a different directory

    with pytest.raises(TtsModelNotCachedError):
        _ensure_model_cached(
            _FakeSileroModule(repo_root / "silero_pkg"), repo_root=repo_root
        )


def test_ensure_model_cached_passes_when_everything_lines_up(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    model_dir = repo_root / "silero_pkg" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "v3_1_ru.pt").write_bytes(b"fake")
    (repo_root / "latest_silero_models.yml").write_text("fake manifest", encoding="utf-8")
    monkeypatch.chdir(repo_root)  # launched from the repo root, as documented

    _ensure_model_cached(
        _FakeSileroModule(repo_root / "silero_pkg"), repo_root=repo_root
    )  # must not raise


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


def test_piper_engine_rejects_missing_model_path(tmp_path):
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Piper model file does not exist"):
        PiperEngine(tmp_path / "missing.onnx", config_path=config_path)


def test_piper_engine_uses_adjacent_config_path_when_present(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)

    engine = PiperEngine(model_path)

    assert engine.model_path == model_path
    assert engine.config_path == config_path


def test_piper_engine_prefers_explicit_config_path(tmp_path):
    model_path, _adjacent_config = _write_piper_model_pair(tmp_path)
    explicit_config = tmp_path / "explicit.json"
    explicit_config.write_text("{}", encoding="utf-8")

    engine = PiperEngine(model_path, config_path=explicit_config)

    assert engine.config_path == explicit_config


def test_piper_engine_rejects_missing_adjacent_config_path(tmp_path):
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")

    with pytest.raises(FileNotFoundError, match="No Piper config file was supplied"):
        PiperEngine(model_path)


def test_piper_engine_rejects_missing_explicit_config_path(tmp_path):
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")

    with pytest.raises(FileNotFoundError, match="Piper config file does not exist"):
        PiperEngine(model_path, config_path=tmp_path / "missing.json")


async def test_piper_engine_synthesize_returns_wav_bytes_from_chunk_api(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)
    voice = _FakePiperVoice([_piper_chunk(22050, [0, 100, -100, 0])])
    load_calls = []

    def load_voice(*, model_path, config_path, use_cuda):
        load_calls.append((model_path, config_path, use_cuda))
        return voice

    engine = PiperEngine(model_path, config_path=config_path, voice_loader=load_voice)

    wav_bytes = await engine.synthesize("hello", language="en")

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 22050
        assert wav_file.readframes(4) == _Int16Bytes([0, 100, -100, 0]).tobytes()
    assert voice.texts == ["hello"]
    assert load_calls == [(model_path, config_path, False)]


async def test_piper_engine_loads_voice_only_once(tmp_path):
    model_path, config_path = _write_piper_model_pair(tmp_path)
    voice = _FakePiperVoice([_piper_chunk(22050, [0])])
    load_count = 0

    def load_voice(*, model_path, config_path, use_cuda):
        nonlocal load_count
        del model_path, config_path, use_cuda
        load_count += 1
        return voice

    engine = PiperEngine(model_path, config_path=config_path, voice_loader=load_voice)
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
    assert normalize_numbers("число 3.14 и всё") == "число три целых четырнадцать сотых и всё"


def test_normalize_numbers_converts_decimal_with_comma_to_words():
    assert normalize_numbers("число 3,14 и всё") == "число три целых четырнадцать сотых и всё"


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

    async def player(audio: bytes) -> None:
        played.append(audio)

    playback = OrderedPlayback(player)
    await playback.submit(0, b"A")
    await playback.submit(1, b"B")

    assert played == [b"A", b"B"]


async def test_playback_reorders_when_submitted_out_of_order():
    played = []

    async def player(audio: bytes) -> None:
        played.append(audio)

    playback = OrderedPlayback(player)
    await playback.submit(1, b"B")
    assert played == []  # buffered, waiting for index 0

    await playback.submit(0, b"A")

    assert played == [b"A", b"B"]


async def test_playback_reorders_under_concurrent_completion():
    played = []

    async def player(audio: bytes) -> None:
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
                load_seconds=0.0, prompt_eval_seconds=0.0, eval_seconds=0.0, eval_count=0
            )
        )
    )
    await tts.wait_for_pending()

    assert played == ["Без точки в конце"]


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
                load_seconds=0.0, prompt_eval_seconds=0.0, eval_seconds=0.0, eval_count=0
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
    engine = _FakeEngine()

    await _speak_tokens(engine, "Love и Dove.")

    assert engine.seen == [("Love", "en"), ("и Dove.", "en")]


async def test_second_turn_starts_fresh_after_english_text():
    engine = _FakeEngine()
    tts = TtsOutput(TtsSettings(), engine=engine, play=_silent_play)

    await tts.on_token(ResponseToken(text="Unclosed tail"))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0, prompt_eval_seconds=0.0, eval_seconds=0.0, eval_count=0
            )
        )
    )
    await tts.on_token(ResponseToken(text="Снова по-русски."))
    await tts.on_response_complete(
        ResponseComplete(
            metrics=LatencyMetrics(
                load_seconds=0.0, prompt_eval_seconds=0.0, eval_seconds=0.0, eval_count=0
            )
        )
    )
    await tts.wait_for_pending()

    assert engine.seen == [("Unclosed tail", "en"), ("Снова по-русски.", "ru")]
