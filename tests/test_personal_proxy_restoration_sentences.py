import time

from jarvis.personal_proxy.restoration.restoration_sentences import (
    MAX_PENDING_CHARS,
    BoundedSentenceBuffer,
)


def test_ordinary_sentences_are_split_like_the_speech_buffer():
    buffer = BoundedSentenceBuffer()

    assert buffer.feed("Первое. Второе тут. Тре") == ["Первое.", "Второе тут."]
    assert buffer.flush() == "Тре"


def test_a_newline_flushes_the_pending_text_as_a_sentence():
    buffer = BoundedSentenceBuffer()

    assert buffer.feed("пункт один\nпункт два\n") == ["пункт один", "пункт два"]
    assert buffer.flush() is None


def test_a_newline_in_a_later_delta_flushes_what_was_pending():
    buffer = BoundedSentenceBuffer()

    assert buffer.feed("пункт один") == []
    assert buffer.feed("\nпродолжение") == ["пункт один"]
    assert buffer.flush() == "продолжение"


def test_pending_text_over_the_limit_is_emitted_at_the_last_space():
    buffer = BoundedSentenceBuffer()
    words = "слово " * (MAX_PENDING_CHARS // 6 + 10)

    emitted = buffer.feed(words + "<PER")

    assert len(emitted) == 1
    assert emitted[0].endswith("слово")
    assert buffer.flush() == "<PER"


def test_pending_text_without_any_space_over_the_limit_is_emitted_whole():
    buffer = BoundedSentenceBuffer()

    emitted = buffer.feed("а" * (MAX_PENDING_CHARS + 1))

    assert emitted == ["а" * (MAX_PENDING_CHARS + 1)]
    assert buffer.flush() is None


def test_text_within_the_limit_stays_pending():
    buffer = BoundedSentenceBuffer()

    assert buffer.feed("а" * MAX_PENDING_CHARS) == []


def test_abbreviation_dense_text_in_small_deltas_is_processed_in_linear_time():
    text = "г. " * 20_000
    buffer = BoundedSentenceBuffer()
    started = time.perf_counter()

    for start in range(0, len(text), 5):
        buffer.feed(text[start : start + 5])
    elapsed = time.perf_counter() - started

    assert elapsed < 1.5


def _fed_in_pieces(text, size):
    buffer = BoundedSentenceBuffer()
    sentences = []
    for start in range(0, len(text), size):
        sentences += buffer.feed(text[start : start + size])
    tail = buffer.flush()
    return sentences + ([tail] if tail else [])


def test_the_cap_never_cuts_a_placeholder_in_one_feed():
    text = "x" * 4095 + "<PERSON_1>" + "y" * 10

    sentences = _fed_in_pieces(text, len(text))

    assert "".join(sentences) == text
    assert any("<PERSON_1>" in sentence for sentence in sentences)


def test_the_cap_never_cuts_a_placeholder_in_small_deltas():
    text = "x" * 3995 + "<PERSON_1>" + "y" * 10

    for size in (1, 3, 7, 10):
        sentences = _fed_in_pieces(text, size)

        assert "".join(sentences) == text
        assert any("<PERSON_1>" in sentence for sentence in sentences), size


def test_the_cap_holds_back_only_a_possible_placeholder_prefix():
    buffer = BoundedSentenceBuffer()

    emitted = buffer.feed("x" * 4005 + "<PERSON_")

    assert emitted == ["x" * 4005]
    assert buffer.flush() == "<PERSON_"


def test_a_long_placeholder_looking_run_does_not_hold_the_buffer():
    text = "x" * 4005 + "<" + "A" * 100 + "z" * 5000

    sentences = _fed_in_pieces(text, 7)

    assert "".join(sentences) == text
    assert max(len(sentence) for sentence in sentences) <= 2 * MAX_PENDING_CHARS


def test_one_big_delta_is_cut_into_bounded_sentences():
    text = "слово " * 30_000

    sentences = _fed_in_pieces(text, len(text))

    assert len(sentences) > 1
    assert max(len(sentence) for sentence in sentences) <= 2 * MAX_PENDING_CHARS


def test_text_after_a_cap_cut_still_ends_its_sentences():
    buffer = BoundedSentenceBuffer()

    buffer.feed("г. " * 1500)
    emitted = buffer.feed("Привет. Мир")

    assert len(emitted) == 1
    assert emitted[0].endswith("г. Привет.")
    assert buffer.flush() == "Мир"
