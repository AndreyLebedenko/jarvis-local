import re

from manual.personal_proxy.restoration import (
    ITEMS,
    CaseResult,
    RestorationMetrics,
    RestorationScore,
    aggregate_restoration,
    build_review_pairs,
    fallback_restore,
    outside_text_unchanged,
    parse_answers,
    render_answer_template,
    render_review_sheet,
    restoration_decision,
    restoration_messages,
    score_case_review,
    score_output,
    validation_passes,
)


def _item(item_id):
    return next(item for item in ITEMS if item.item_id == item_id)


def test_the_set_has_thirty_items_with_unique_ids():
    assert len(ITEMS) == 30
    assert len({item.item_id for item in ITEMS}) == 30


def test_every_placeholder_in_a_sentence_has_a_mapping_entry_and_vice_versa():
    for item in ITEMS:
        in_sentence = set(re.findall(r"<[A-Z_]+_\d+>", item.sentence))
        assert in_sentence == set(item.mapping), item.item_id


def test_messages_carry_the_mapping_and_the_sentence():
    messages = restoration_messages(_item("r02_dative"))

    assert messages[0]["role"] == "system"
    assert "Марина Крылова" in messages[1]["content"]
    assert "Передайте <PERSON_1>" in messages[1]["content"]


def test_fallback_inserts_the_base_form_without_declension():
    assert (
        fallback_restore(_item("r02_dative"))
        == "Передайте Марина Крылова, что документы готовы."
    )


def test_fallback_replaces_a_repeated_placeholder_everywhere():
    assert fallback_restore(_item("r09_repeated")).count("Павел Сидоров") == 2


def test_a_declined_value_passes_validation():
    assert validation_passes(
        _item("r02_dative"), "Передайте Марине Крыловой, что документы готовы."
    )


def test_a_left_over_placeholder_fails_validation():
    assert not validation_passes(
        _item("r02_dative"), "Передайте <PERSON_1>, что документы готовы."
    )


def test_a_missing_original_fails_validation():
    assert not validation_passes(
        _item("r02_dative"), "Передайте Анне, что документы готовы."
    )


def test_digits_must_appear_exactly():
    item = _item("r10_phone")

    assert validation_passes(item, "Позвоните по номеру 8 915 234 56 78 после обеда.")
    assert not validation_passes(
        item, "Позвоните по номеру 8 915 234 56 79 после обеда."
    )


def test_untouched_surrounding_words_count_as_unchanged():
    assert outside_text_unchanged(
        _item("r02_dative"), "Передайте Марине Крыловой, что документы готовы."
    )


def test_a_rewritten_surrounding_phrase_counts_as_altered():
    assert not outside_text_unchanged(
        _item("r02_dative"), "Сообщите Марине Крыловой, что бумаги готовы."
    )


def test_score_output_strips_whitespace_and_reports_both_checks():
    score = score_output(
        _item("r02_dative"), 1, "  Передайте Марине Крыловой, что документы готовы.\n"
    )

    assert (score.valid, score.unchanged_outside) == (True, True)
    assert score.output.startswith("Передайте")


def test_aggregate_computes_pass_and_alteration_rates():
    scores = [
        RestorationScore("a", 1, "x", True, True),
        RestorationScore("b", 1, "x", True, False),
        RestorationScore("c", 1, "x", False, True),
        RestorationScore("d", 1, "x", True, True),
    ]

    metrics = aggregate_restoration(scores)

    assert metrics == RestorationMetrics(4, 0.75, 0.25)


def test_review_pairs_are_deterministic_and_balanced_in_order():
    first, second = build_review_pairs(), build_review_pairs()

    assert first == second
    assert {pair.x_is_model for pair in first} == {True, False}


def test_sheet_lists_every_item_and_labels_texts_only_as_x_and_y():
    pairs = build_review_pairs()
    outputs = {item.item_id: "ВЫВОД " + item.item_id for item in ITEMS}

    sheet = render_review_sheet(pairs, outputs)

    assert sheet.count("- X:") == 30
    assert sheet.count("- Y:") == 30
    assert all(item.item_id in sheet for item in ITEMS)
    assert "fallback" not in sheet.lower()


def test_answers_roundtrip_through_the_template():
    pairs = build_review_pairs()

    template = render_answer_template(pairs)

    parsed = parse_answers(template)
    assert set(parsed) == {item.item_id for item in ITEMS}
    assert parsed[pairs[0].item_id] == {"x": "", "y": ""}


def test_case_scoring_counts_model_successes_where_the_fallback_fails():
    pairs = build_review_pairs()[:3]
    model_x = {p.item_id: p.x_is_model for p in pairs}
    answers = {}
    for pair in pairs:
        model_side, fallback_side = ("x", "y") if model_x[pair.item_id] else ("y", "x")
        answers[pair.item_id] = {fallback_side: "bad", model_side: "ok"}
    answers[pairs[2].item_id][("x" if model_x[pairs[2].item_id] else "y")] = "bad"
    valid = {p.item_id: True for p in pairs}

    result = score_case_review(pairs, answers, valid)

    assert result == CaseResult(3, 2)
    assert abs(result.beaten_share - 2 / 3) < 1e-9


def test_a_model_output_that_failed_validation_never_counts_as_right():
    pairs = build_review_pairs()[:1]
    pair = pairs[0]
    model_side, fallback_side = ("x", "y") if pair.x_is_model else ("y", "x")
    answers = {pair.item_id: {fallback_side: "bad", model_side: "ok"}}

    result = score_case_review(pairs, answers, {pair.item_id: False})

    assert result.model_right_where_fallback_wrong == 0


def test_decision_passes_when_all_three_conditions_hold():
    ok, reasons = restoration_decision(
        RestorationMetrics(60, 0.95, 0.03), CaseResult(10, 9)
    )

    assert ok and reasons == []


def test_decision_lists_every_failed_condition():
    ok, reasons = restoration_decision(
        RestorationMetrics(60, 0.80, 0.10), CaseResult(10, 5)
    )

    assert not ok
    assert len(reasons) == 3


def test_decision_reports_an_unmeasurable_case_benefit():
    ok, reasons = restoration_decision(
        RestorationMetrics(60, 0.95, 0.0), CaseResult(0, 0)
    )

    assert not ok
    assert "unmeasured" in reasons[0]
