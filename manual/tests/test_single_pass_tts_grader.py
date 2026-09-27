import pytest

from manual.single_pass_tts_grader import (
    b_canvas,
    b_voice,
    block_first_sentence_seconds,
    classify_tag,
    grade_generations,
    pass2_first_sentence_seconds,
    voice_hygiene,
)
from manual.single_pass_tts_records import (
    Arm,
    CallRecord,
    GenerationKey,
    Level,
    Stage,
    StreamChunk,
    TagOutcome,
    VoiceHygiene,
)

OFF_KEY = GenerationKey(Level.OFF, "p01", 1)
MEDIUM_KEY = GenerationKey(Level.MEDIUM, "p01", 1)


def _chunks(*timed_texts: tuple[float, str]) -> tuple[StreamChunk, ...]:
    return tuple(StreamChunk(t, text) for t, text in timed_texts)


def _record(
    stage: Stage,
    *timed_texts: tuple[float, str],
    key: GenerationKey = OFF_KEY,
    started_at: float = 100.0,
    done_reason: str | None = "stop",
    eval_count: int | None = 10,
) -> CallRecord:
    return CallRecord(
        key=key,
        stage=stage,
        started_at=started_at,
        chunks=_chunks(*timed_texts),
        done_reason=done_reason,
        eval_count=eval_count,
        prompt_eval_count=5,
        system_prompt_sha256="sha",
    )


# --- tag classification: one fixture per class ---


def test_well_formed_block_after_canvas():
    content = "Ответ.\n\n<tts>Короткий ответ.</tts>\n"

    assert classify_tag(content, "stop") is TagOutcome.WELL_FORMED


def test_length_done_reason_is_truncated_even_for_a_well_formed_block():
    content = "Ответ.<tts>Голос.</tts>"

    assert classify_tag(content, "length") is TagOutcome.TRUNCATED


def test_no_opening_tag_is_missing():
    assert classify_tag("Только ответ.", "stop") is TagOutcome.MISSING


def test_stray_closing_tag_without_opening_is_missing():
    assert classify_tag("Ответ.</tts>", "stop") is TagOutcome.MISSING


def test_uppercase_or_spaced_tags_are_not_tags():
    assert classify_tag("Ответ.<TTS>Голос.</TTS>", "stop") is TagOutcome.MISSING
    assert classify_tag("Ответ.<tts >Голос.</tts>", "stop") is TagOutcome.MISSING


def test_two_opening_tags_are_multiple():
    content = "Ответ.<tts>Раз.</tts><tts>Два.</tts>"

    assert classify_tag(content, "stop") is TagOutcome.MULTIPLE


def test_block_inside_an_open_code_fence_is_in_code_fence():
    content = "Пример:\n```text\n<tts>Голос.</tts>\n```\n"

    assert classify_tag(content, "stop") is TagOutcome.IN_CODE_FENCE


def test_block_after_a_closed_code_fence_is_not_in_code_fence():
    content = "```python\nx = 1\n```\n<tts>Голос.</tts>"

    assert classify_tag(content, "stop") is TagOutcome.WELL_FORMED


def test_indented_fence_line_still_counts_as_a_fence():
    content = "Пример:\n  ```\n<tts>Голос.</tts>\n  ```"

    assert classify_tag(content, "stop") is TagOutcome.IN_CODE_FENCE


def test_opening_without_closing_tag_is_unclosed():
    assert classify_tag("Ответ.<tts>Голос.", "stop") is TagOutcome.UNCLOSED


def test_closing_tag_only_before_the_opening_is_unclosed():
    assert classify_tag("Ответ.</tts><tts>Голос.", "stop") is TagOutcome.UNCLOSED


def test_non_whitespace_after_closing_tag_is_text_after():
    content = "Ответ.<tts>Голос.</tts>\nЕщё немного."

    assert classify_tag(content, "stop") is TagOutcome.TEXT_AFTER


def test_second_closing_tag_counts_as_text_after():
    content = "Ответ.<tts>Голос.</tts></tts>"

    assert classify_tag(content, "stop") is TagOutcome.TEXT_AFTER


def test_whitespace_only_block_is_empty():
    assert classify_tag("Ответ.<tts>  \n </tts>", "stop") is TagOutcome.EMPTY


# --- tag classification: precedence ---


def test_truncated_takes_precedence_over_unclosed():
    assert classify_tag("Ответ.<tts>Голос", "length") is TagOutcome.TRUNCATED


def test_truncated_takes_precedence_over_missing():
    assert classify_tag("Ответ без бло", "length") is TagOutcome.TRUNCATED


def test_multiple_takes_precedence_over_code_fence_and_unclosed():
    content = "```\n<tts>Раз.\n<tts>Два."

    assert classify_tag(content, "stop") is TagOutcome.MULTIPLE


def test_code_fence_takes_precedence_over_unclosed():
    content = "```\n<tts>Голос."

    assert classify_tag(content, "stop") is TagOutcome.IN_CODE_FENCE


def test_unclosed_takes_precedence_over_empty():
    assert classify_tag("Ответ.<tts>   ", "stop") is TagOutcome.UNCLOSED


def test_text_after_takes_precedence_over_empty():
    assert classify_tag("Ответ.<tts> </tts> хвост", "stop") is TagOutcome.TEXT_AFTER


# --- canvas and voice extraction ---


def test_b_canvas_is_stripped_text_before_the_opening_tag():
    assert b_canvas("\n# Ответ\n\nТекст.\n<tts>Голос.</tts>") == "# Ответ\n\nТекст."


def test_b_canvas_is_whole_stripped_content_without_a_tag():
    assert b_canvas("  Только ответ.  \n") == "Только ответ."


def test_b_voice_is_stripped_block_content_when_well_formed():
    assert b_voice("Ответ.<tts>\n Голос тут. \n</tts>\n", "stop") == "Голос тут."


def test_b_voice_is_none_for_any_tag_failure():
    assert b_voice("Ответ.<tts>Голос.", "stop") is None
    assert b_voice("Ответ.<tts>Голос.</tts>", "length") is None
    assert b_voice("Ответ.<tts>Голос.</tts> хвост", "stop") is None


# --- time to first spoken sentence: pass 2 (all content is voice) ---


def test_pass2_sentence_arrives_with_the_chunk_whose_whitespace_ends_it():
    chunks = _chunks((0.2, "Первое"), (0.4, " предложение."), (0.6, " Второе"))

    assert pass2_first_sentence_seconds(chunks) == 0.6


def test_pass2_single_unterminated_sentence_is_flushed_at_stream_end():
    chunks = _chunks((0.2, "Единственное"), (0.5, " предложение."))

    assert pass2_first_sentence_seconds(chunks) == 0.5


def test_pass2_whitespace_only_voice_has_no_sentence():
    assert pass2_first_sentence_seconds(_chunks((0.2, "  "), (0.3, "\n"))) is None


def test_pass2_without_chunks_has_no_sentence():
    assert pass2_first_sentence_seconds(()) is None


def test_pass2_abbreviation_from_sentence_buffer_does_not_end_a_sentence():
    chunks = _chunks((0.1, "Это важно, т.е."), (0.3, " нужно"), (0.5, " помнить. Да"))

    assert pass2_first_sentence_seconds(chunks) == 0.5


# --- time to first spoken sentence: B block ---


def test_block_canvas_sentences_before_the_tag_are_not_spoken():
    chunks = _chunks(
        (0.1, "Ответ первый. Ответ второй. "),
        (0.3, "<tts>Голос"),
        (0.5, " первый."),
        (0.7, " Голос второй.</tts>"),
    )

    assert block_first_sentence_seconds(chunks) == 0.7


def test_block_opening_tag_split_across_chunks_is_recognised():
    chunks = _chunks(
        (0.1, "Ответ.\n<t"),
        (0.2, "ts>Привет."),
        (0.3, " Как"),
        (0.4, " дела?</tts>"),
    )

    assert block_first_sentence_seconds(chunks) == 0.3


def test_block_closing_tag_characters_are_not_fed_as_voice():
    chunks = _chunks((0.1, "<tts>Голос. </t"), (0.2, "ts>"))

    assert block_first_sentence_seconds(chunks) == 0.1


def test_block_single_sentence_is_flushed_where_closing_tag_completes():
    chunks = _chunks(
        (0.1, "Ответ.<tts>Один"),
        (0.3, " ответ.</"),
        (0.5, "tts>"),
        (0.9, "\n"),
    )

    assert block_first_sentence_seconds(chunks) == 0.5


def test_block_whitespace_only_voice_has_no_sentence():
    assert block_first_sentence_seconds(_chunks((0.1, "Ответ.<tts>  </tts>"))) is None


def test_block_without_opening_tag_has_no_sentence():
    assert block_first_sentence_seconds(_chunks((0.1, "Ответ. Ещё."))) is None


def test_unclosed_block_without_a_terminated_sentence_has_no_sentence():
    chunks = _chunks((0.1, "Ответ.<tts>Голос"), (0.3, " без конца"))

    assert block_first_sentence_seconds(chunks) is None


def test_block_abbreviation_from_sentence_buffer_does_not_end_a_sentence():
    chunks = _chunks(
        (0.1, "Ответ.<tts>Подробнее см. ниже"),
        (0.4, " в тексте. Всё"),
        (0.6, ".</tts>"),
    )

    assert block_first_sentence_seconds(chunks) == 0.4


# --- voice hygiene ---


def test_plain_prose_voice_has_no_hygiene_findings():
    assert voice_hygiene("Просто ответ. Без разметки, 3 + 4 = 7.") == VoiceHygiene()


def test_hygiene_counts_each_markdown_marker_occurrence():
    text = (
        "## Заголовок\n"
        "Это **жирный** и __подчёркнутый__ текст с `кодом`.\n"
        "- пункт\n"
        "  * вложенный\n"
        "1. первый\n"
        "2) второй\n"
    )

    assert voice_hygiene(text).markdown_markers == 1 + 2 + 2 + 1 + 2 + 2


def test_hygiene_does_not_count_hyphen_or_number_inside_a_line_as_list():
    assert voice_hygiene("Шаг - это 1. не список").markdown_markers == 0


def test_hygiene_counts_lines_with_at_least_two_pipes():
    text = "| a | b |\n|---|---|\nодин | ноль\nили a|b|c"

    assert voice_hygiene(text).table_pipe_lines == 3


def test_hygiene_counts_fence_lines_and_does_not_treat_them_as_inline_code():
    hygiene = voice_hygiene("```python\nx = 1\n```")

    assert hygiene.code_fences == 2
    assert hygiene.markdown_markers == 0


def test_hygiene_counts_raw_urls_once_each():
    text = "См. https://www.example.com/a и www.example.org, а не example.net."

    assert voice_hygiene(text).raw_urls == 2


# --- per-generation metrics: arm B ---


def test_well_formed_b_generation_metrics():
    record = _record(
        Stage.B,
        (0.5, "Ответ.\n<tts>Голос"),
        (0.9, " первый. Голос второй.</tts>"),
        eval_count=42,
    )

    [metrics] = grade_generations([record])

    assert metrics.arm is Arm.B
    assert metrics.key == OFF_KEY
    assert metrics.canvas_text == "Ответ."
    assert metrics.voice_text == "Голос первый. Голос второй."
    assert metrics.tag_outcome is TagOutcome.WELL_FORMED
    assert metrics.first_sentence_seconds == 0.9
    assert metrics.total_wall_seconds == 0.9
    assert metrics.eval_count_sum == 42
    assert metrics.runaway is False
    assert metrics.hygiene == VoiceHygiene()


def test_b_tag_failure_has_no_voice_timing_or_hygiene():
    record = _record(Stage.B, (0.5, "Ответ.<tts>Голос. Второй."))

    [metrics] = grade_generations([record])

    assert metrics.tag_outcome is TagOutcome.UNCLOSED
    assert metrics.voice_text is None
    assert metrics.first_sentence_seconds is None
    assert metrics.hygiene is None
    assert metrics.runaway is False


def test_b_truncation_is_a_runaway():
    record = _record(Stage.B, (0.5, "Ответ.<tts>Голос"), done_reason="length")

    [metrics] = grade_generations([record])

    assert metrics.tag_outcome is TagOutcome.TRUNCATED
    assert metrics.runaway is True


def test_b_empty_visible_answer_is_a_runaway_and_missing_eval_count_is_zero():
    record = _record(Stage.B, (3.0, "  \n"), eval_count=None)

    [metrics] = grade_generations([record])

    assert metrics.runaway is True
    assert metrics.eval_count_sum == 0
    assert metrics.tag_outcome is TagOutcome.MISSING


# --- per-generation metrics: arms A ---


def test_a_prod_first_sentence_spans_pass1_and_pass2_start_offset():
    pass1 = _record(Stage.A_PASS1, (2.0, "Ответ."), started_at=100.0, eval_count=30)
    pass2 = _record(
        Stage.A_PROD_PASS2,
        (0.3, "Голос"),
        (0.6, " первый. Голос"),
        (0.8, " второй."),
        started_at=102.5,
        eval_count=12,
    )

    [metrics] = grade_generations([pass1, pass2])

    assert metrics.arm is Arm.A_PROD
    assert metrics.canvas_text == "Ответ."
    assert metrics.voice_text == "Голос первый. Голос второй."
    assert metrics.first_sentence_seconds == pytest.approx(3.1)
    assert metrics.total_wall_seconds == pytest.approx(3.3)
    assert metrics.eval_count_sum == 42
    assert metrics.runaway is False
    assert metrics.hygiene == VoiceHygiene()
    assert metrics.tag_outcome is None


def test_a_prod_without_pass2_is_a_runaway_with_pass1_wall_time():
    pass1 = _record(Stage.A_PASS1, (2.0, "Ответ."), eval_count=30)

    [metrics] = grade_generations([pass1])

    assert metrics.arm is Arm.A_PROD
    assert metrics.voice_text is None
    assert metrics.first_sentence_seconds is None
    assert metrics.total_wall_seconds == 2.0
    assert metrics.eval_count_sum == 30
    assert metrics.runaway is True
    assert metrics.hygiene is None


def test_a_prod_empty_pass2_is_a_runaway_without_voice():
    pass1 = _record(Stage.A_PASS1, (2.0, "Ответ."), started_at=100.0)
    pass2 = _record(Stage.A_PROD_PASS2, (0.4, " "), started_at=102.0)

    [metrics] = grade_generations([pass1, pass2])

    assert metrics.voice_text is None
    assert metrics.first_sentence_seconds is None
    assert metrics.runaway is True
    assert metrics.hygiene is None


def test_a_prod_truncated_pass1_is_a_runaway():
    pass1 = _record(Stage.A_PASS1, (9.0, "Отв"), done_reason="length")
    pass2 = _record(Stage.A_PROD_PASS2, (0.4, "Голос."), started_at=110.0)

    [metrics] = grade_generations([pass1, pass2])

    assert metrics.runaway is True


def test_a_prod_voice_hygiene_reports_markdown_in_pass2():
    pass1 = _record(Stage.A_PASS1, (2.0, "Ответ."))
    pass2 = _record(Stage.A_PROD_PASS2, (0.4, "- **Пункт**."), started_at=102.0)

    [metrics] = grade_generations([pass1, pass2])

    assert metrics.hygiene == VoiceHygiene(markdown_markers=3)


def test_a_eq_shares_pass1_with_a_prod_and_both_are_emitted():
    pass1 = _record(Stage.A_PASS1, (2.0, "Ответ."), key=MEDIUM_KEY, started_at=0.0)
    prod = _record(Stage.A_PROD_PASS2, (0.5, "Быстро."), key=MEDIUM_KEY, started_at=2.1)
    eq = _record(Stage.A_EQ_PASS2, (1.5, "Медленно."), key=MEDIUM_KEY, started_at=4.0)

    by_arm = {m.arm: m for m in grade_generations([pass1, prod, eq])}

    assert set(by_arm) == {Arm.A_PROD, Arm.A_EQ}
    assert by_arm[Arm.A_PROD].canvas_text == by_arm[Arm.A_EQ].canvas_text
    assert by_arm[Arm.A_PROD].first_sentence_seconds == pytest.approx(2.6)
    assert by_arm[Arm.A_EQ].first_sentence_seconds == pytest.approx(5.5)
    assert by_arm[Arm.A_EQ].voice_text == "Медленно."


def test_a_eq_is_not_emitted_without_its_pass2():
    pass1 = _record(Stage.A_PASS1, (2.0, "Ответ."))
    prod = _record(Stage.A_PROD_PASS2, (0.5, "Голос."), started_at=102.0)

    arms = [m.arm for m in grade_generations([pass1, prod])]

    assert arms == [Arm.A_PROD]


def test_pass2_without_pass1_is_an_error_naming_the_key():
    orphan = _record(Stage.A_EQ_PASS2, (0.5, "Голос."), key=MEDIUM_KEY)

    with pytest.raises(ValueError, match=MEDIUM_KEY.slug):
        grade_generations([orphan])


def test_duplicate_stage_for_one_generation_is_an_error_naming_the_key():
    first = _record(Stage.B, (0.5, "Ответ."))
    second = _record(Stage.B, (0.6, "Другой ответ."))

    with pytest.raises(ValueError, match=OFF_KEY.slug):
        grade_generations([first, second])


# --- per-generation metrics: grouping and order ---


def test_metrics_are_sorted_by_key_then_arm():
    later_key = GenerationKey(Level.OFF, "p02", 1)
    records = [
        _record(Stage.B, (0.5, "Ответ."), key=later_key),
        _record(Stage.A_PASS1, (0.5, "Ответ."), key=later_key),
        _record(Stage.B, (0.5, "Ответ."), key=MEDIUM_KEY),
        _record(Stage.A_PASS1, (0.5, "Ответ."), key=MEDIUM_KEY),
        _record(Stage.A_EQ_PASS2, (0.5, "Голос."), key=MEDIUM_KEY),
        _record(Stage.B, (0.5, "Ответ."), key=OFF_KEY),
    ]

    order = [(m.key, m.arm) for m in grade_generations(records)]

    assert order == [
        (MEDIUM_KEY, Arm.A_EQ),
        (MEDIUM_KEY, Arm.A_PROD),
        (MEDIUM_KEY, Arm.B),
        (OFF_KEY, Arm.B),
        (later_key, Arm.A_PROD),
        (later_key, Arm.B),
    ]
