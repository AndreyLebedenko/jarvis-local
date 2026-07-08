import asyncio

import pytest

from backend import LatencyMetrics, ResponseComplete, ResponseToken
from config import TtsSettings
from tts import (
    OrderedPlayback,
    SileroEngine,
    SentenceBuffer,
    SynthesisResult,
    TtsEngine,
    TtsModelNotCachedError,
    TtsOutput,
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
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def synthesize(self, text: str) -> SynthesisResult:
        self.seen.append(text)
        return SynthesisResult(audio_bytes=text.encode(), sample_rate=48000)


def test_silero_engine_satisfies_tts_engine_protocol():
    engine: TtsEngine = SileroEngine(TtsSettings())

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

    async def fake_synthesize(sentence: str) -> bytes:
        # first sentence takes longer to "synthesize" than the second,
        # simulating out-of-order completion of concurrent synthesis
        await asyncio.sleep(0.05 if sentence.startswith("Первое") else 0.01)
        return sentence.encode()

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), synthesize=fake_synthesize, play=fake_play)

    await tts.on_token(ResponseToken(text="Первое предложение. "))
    await tts.on_token(ResponseToken(text="Второе предложение. "))
    await tts.wait_for_pending()

    assert played == ["Первое предложение.", "Второе предложение."]


async def test_on_response_complete_flushes_and_schedules_trailing_sentence():
    played = []

    async def fake_synthesize(sentence: str) -> bytes:
        return sentence.encode()

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    tts = TtsOutput(TtsSettings(), synthesize=fake_synthesize, play=fake_play)

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

    assert engine.seen == ["Фраза готова."]
    assert played == ["Фраза готова."]


def test_tts_output_rejects_two_synthesis_injection_paths():
    async def fake_synthesize(sentence: str) -> bytes:
        return sentence.encode()

    with pytest.raises(ValueError):
        TtsOutput(TtsSettings(), synthesize=fake_synthesize, engine=_FakeEngine())
