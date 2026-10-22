import json
from dataclasses import replace

import httpx
import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check_backend import BackendReplyError
from jarvis.personal_proxy.restoration_validation import restoration_is_valid
from manual import manual_check_restoration_stage as harness
from manual.personal_proxy.restoration import (
    ITEMS,
    SEEDS,
    RestorationMetrics,
    build_review_pairs,
    fallback_restore,
)

PROXY = PersonalProxySettings()
ITEM = next(item for item in ITEMS if item.item_id == "r02_dative")
GOOD = "Передайте Марине Крыловой, что документы готовы."


class FakeBackend:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def _generation(**changes):
    base = harness.Generation(
        item_id="r02_dative",
        seed=SEEDS[0],
        stage_text=GOOD,
        method="model",
        unresolved=False,
        seconds=1.0,
        raw_reply=GOOD,
        failed_rules=[],
        fallback_reason=None,
    )
    return replace(base, **changes)


async def test_every_spike_item_is_one_sentence_for_the_stage():
    for item in ITEMS:
        backend = FakeBackend(fallback_restore(item))

        await harness.run_generation(item, SEEDS[0], backend, PROXY)

        assert len(backend.requests) == 1, item.item_id


async def test_a_generation_records_the_stage_output_method_and_raw_reply():
    generation = await harness.run_generation(ITEM, 7, FakeBackend(GOOD), PROXY)

    assert generation.stage_text == GOOD
    assert generation.method == "model"
    assert generation.raw_reply == GOOD
    assert generation.failed_rules == []
    assert generation.fallback_reason is None
    assert generation.seed == 7
    assert generation.seconds >= 0


async def test_the_seed_goes_into_the_request_options():
    backend = FakeBackend(GOOD)

    await harness.run_generation(ITEM, 4243, backend, PROXY)

    assert backend.requests[0].options.seed == 4243
    assert backend.requests[0].options.temperature == PROXY.check_temperature


async def test_a_failed_rule_is_the_fallback_reason():
    wrong = "Передайте, что документы готовы."

    generation = await harness.run_generation(ITEM, 1, FakeBackend(wrong), PROXY)

    assert generation.method == "substituted"
    assert generation.stage_text == fallback_restore(ITEM)
    assert generation.raw_reply == wrong
    assert generation.fallback_reason == "literal_changed"


async def test_a_backend_error_is_a_fallback_without_a_raw_reply():
    generation = await harness.run_generation(
        ITEM, 1, FakeBackend(RuntimeError("down")), PROXY
    )

    assert generation.method == "substituted"
    assert generation.raw_reply is None
    assert generation.fallback_reason == "no_usable_reply"


async def test_a_blank_reply_is_a_fallback_without_a_usable_reply():
    generation = await harness.run_generation(ITEM, 1, FakeBackend("  "), PROXY)

    assert generation.fallback_reason == "no_usable_reply"


def test_the_pass_rate_is_the_model_share_of_all_generations():
    generations = [
        _generation(),
        _generation(),
        _generation(
            method="substituted",
            fallback_reason="placeholders",
            failed_rules=["placeholders"],
        ),
        _generation(method="substituted", raw_reply=None, fallback_reason="x"),
    ]

    metrics = harness.automatic_metrics(generations)

    assert metrics == RestorationMetrics(4, 0.5, 0.0)


def test_the_alteration_rate_counts_outside_changes_among_replied_generations():
    generations = [
        _generation(),
        _generation(
            method="substituted",
            fallback_reason="literal_changed",
            failed_rules=["literal_changed"],
        ),
        _generation(method="substituted", raw_reply=None, fallback_reason="x"),
    ]

    metrics = harness.automatic_metrics(generations)

    assert metrics.alteration_rate == pytest.approx(0.5)


def test_no_generations_give_zero_metrics():
    assert harness.automatic_metrics([]) == RestorationMetrics(0, 0.0, 0.0)


def test_the_fallback_breakdown_counts_each_reason():
    generations = [
        _generation(),
        _generation(method="substituted", fallback_reason="placeholders"),
        _generation(method="substituted", fallback_reason="placeholders"),
        _generation(method="substituted", fallback_reason="no_usable_reply"),
    ]

    assert harness.fallback_breakdown(generations) == {
        "placeholders": 2,
        "no_usable_reply": 1,
    }


def test_the_review_sheet_shows_the_raw_reply_of_the_review_seed_against_substitution():
    other_seed = _generation(seed=SEEDS[1], raw_reply="other seed text")
    review = _generation(raw_reply=GOOD)

    outputs = harness.review_model_outputs([other_seed, review])

    assert outputs == {"r02_dative": GOOD}


def test_a_missing_raw_reply_is_marked_in_the_review_sheet_text():
    review = _generation(raw_reply=None, method="substituted")

    assert harness.review_model_outputs([review]) == {
        "r02_dative": harness.NO_REPLY_TEXT
    }


def test_the_review_model_validity_is_the_stage_method_at_the_review_seed():
    generations = [
        _generation(),
        _generation(seed=SEEDS[1], method="substituted"),
        _generation(item_id="r03_genitive", method="substituted"),
    ]

    assert harness.review_model_validity(generations) == {
        "r02_dative": True,
        "r03_genitive": False,
    }


def test_the_results_round_trip_through_json(tmp_path):
    generations = [_generation(), _generation(raw_reply=None, failed_rules=[])]
    path = tmp_path / "results.json"

    harness.save_generations(path, generations)

    assert harness.load_generations(path) == generations
    assert json.loads(path.read_text(encoding="utf-8"))[0]["item_id"] == "r02_dative"


def test_the_decision_combines_the_automatic_metrics_with_the_case_review():
    generations = [_generation(item_id=item.item_id) for item in ITEMS]
    pairs = build_review_pairs()
    answers = {pair.item_id: {"x": "ok", "y": "ok"} for pair in pairs}
    answers["r02_dative"] = {
        "x": "ok" if pairs[1].x_is_model else "bad",
        "y": "bad" if pairs[1].x_is_model else "ok",
    }

    keep, reasons = harness.final_decision(generations, answers)

    assert keep
    assert reasons == []


def test_the_decision_fails_on_an_automatic_rate_even_with_a_good_case_review():
    generations = [
        _generation(item_id=item.item_id, method="substituted", fallback_reason="x")
        for item in ITEMS
    ]
    answers = {pair.item_id: {"x": "ok", "y": "ok"} for pair in build_review_pairs()}

    keep, reasons = harness.final_decision(generations, answers)

    assert not keep
    assert any("validation pass rate" in reason for reason in reasons)


def test_the_load_option_check_names_every_unset_spike_option():
    assert harness.load_option_warnings(None, None) == [
        "[backend].flash_attention is unset; the spikes ran with true",
        '[backend].kv_cache_type is unset; the spikes ran with "q8_0"',
    ]
    assert harness.load_option_warnings(True, "q8_0") == []


def _full_run(**changes):
    return [
        _generation(item_id=item.item_id, seed=seed, **changes)
        for seed in SEEDS
        for item in ITEMS
    ]


def test_score_refuses_while_the_answers_file_has_empty_marks(tmp_path, capsys):
    generations = _full_run()
    harness.save_generations(tmp_path / harness.RESULTS_NAME, generations)
    harness._write_review_files(tmp_path, generations)

    exit_code = harness.main(["--out", str(tmp_path), "score"])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "r01_nominative" in output
    assert "write mid explicitly" in output


def test_run_refuses_to_mix_with_an_existing_results_file(tmp_path, capsys):
    harness.save_generations(tmp_path / harness.RESULTS_NAME, [_generation()])

    exit_code = harness.main(
        ["--out", str(tmp_path), "--config", str(tmp_path / "none.toml"), "run"]
    )

    assert exit_code == 2
    assert "Nothing was run" in capsys.readouterr().out


def test_the_review_files_hold_the_sheet_and_an_answer_template(tmp_path):
    generations = [_generation(item_id=item.item_id) for item in ITEMS]

    harness._write_review_files(tmp_path, generations)

    sheet = (tmp_path / harness.SHEET_NAME).read_text(encoding="utf-8")
    assert "## r01_nominative" in sheet
    assert (tmp_path / harness.ANSWERS_NAME).exists()


def test_the_plain_substitution_of_every_spike_item_passes_the_stage_validation():
    for item in ITEMS:
        assert restoration_is_valid(
            item.sentence, item.mapping, fallback_restore(item)
        ), item.item_id


async def test_a_bad_slot_is_the_fallback_reason():
    wrong = "Передайте Анне Лебедевой, что документы готовы."

    generation = await harness.run_generation(ITEM, 1, FakeBackend(wrong), PROXY)

    assert generation.fallback_reason == "bad_slot"


def test_the_model_details_come_from_api_show():
    document = {"details": {"quantization_level": "Q4_K_M", "parameter_size": "12B"}}

    assert harness.describe_model(document) == (
        "parameter_size=12B; quantization_level=Q4_K_M"
    )
    assert harness.describe_model({}) == (
        "parameter_size=unknown; quantization_level=unknown"
    )


def test_only_a_four_bit_quantization_level_looks_four_bit():
    assert harness.looks_four_bit({"details": {"quantization_level": "Q4_K_M"}})
    assert harness.looks_four_bit({"details": {"quantization_level": "INT4"}})
    assert not harness.looks_four_bit({"details": {"quantization_level": "Q8_0"}})
    assert not harness.looks_four_bit({"details": {"quantization_level": "F16"}})
    assert not harness.looks_four_bit({})


def test_the_model_details_are_asked_with_post_api_show():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"details": {"quantization_level": "Q4_0"}})

    with httpx.Client(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    ) as client:
        document = harness.fetch_model_details(client, "gemma4:12b")

    assert document == {"details": {"quantization_level": "Q4_0"}}
    assert seen[0][:2] == ("POST", "/api/show")
    assert json.loads(seen[0][2]) == {"model": "gemma4:12b"}


def test_unavailable_model_details_are_none():
    def handler(request):
        return httpx.Response(500)

    with httpx.Client(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    ) as client:
        assert harness.fetch_model_details(client, "gemma4:12b") is None


async def test_the_warm_up_sends_one_tiny_text_only_request():
    backend = FakeBackend("ok")

    await harness.warm_up(backend)

    assert len(backend.requests) == 1
    assert backend.requests[0].audio_base64 == ""
    assert backend.requests[0].options.num_predict == 1


def test_more_than_ten_percent_unusable_replies_is_too_many():
    unusable = _generation(
        method="substituted", raw_reply=None, fallback_reason="no_usable_reply"
    )
    planned = 60

    assert not harness.too_many_unusable([unusable] * 6, planned)
    assert harness.too_many_unusable([unusable] * 7, planned)


def test_other_fallbacks_do_not_count_as_an_outage():
    wrong = _generation(method="substituted", fallback_reason="bad_slot")

    assert not harness.too_many_unusable([wrong] * 60, 60)


def test_score_gives_no_verdict_for_a_run_with_an_outage(tmp_path, capsys):
    generations = _full_run(
        method="substituted", raw_reply=None, fallback_reason="no_usable_reply"
    )
    harness.save_generations(tmp_path / harness.RESULTS_NAME, generations)
    harness._write_review_files(tmp_path, generations)

    exit_code = harness.main(["--out", str(tmp_path), "score"])

    output = capsys.readouterr().out
    assert exit_code == 3
    assert "INVALID" in output
    assert "KEEP" not in output
    assert "NOT SUPPORTED" not in output


def test_score_gives_no_verdict_for_an_incomplete_run(tmp_path, capsys):
    harness.save_generations(tmp_path / harness.RESULTS_NAME, [_generation()])
    harness._write_review_files(tmp_path, [_generation()])

    exit_code = harness.main(["--out", str(tmp_path), "score"])

    assert exit_code == 3
    assert "INVALID" in capsys.readouterr().out


def test_the_review_sheet_tells_the_owner_to_check_digits_values_and_markup(tmp_path):
    harness._write_review_files(tmp_path, _full_run())

    sheet = (tmp_path / harness.SHEET_NAME).read_text(encoding="utf-8")

    assert "changed digit" in sheet
    assert "duplicated or missing" in sheet
    assert "markdown" in sheet
    assert sheet.index("changed digit") < sheet.index("## r01_nominative")


async def test_a_warm_up_cut_at_the_length_cap_still_counts_as_loaded():
    backend = FakeBackend(BackendReplyError())

    await harness.warm_up(backend)

    assert len(backend.requests) == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), RuntimeError("other")],
)
async def test_a_warm_up_with_any_other_failure_still_fails(failure):
    with pytest.raises(type(failure)):
        await harness.warm_up(FakeBackend(failure))


def _answers(**marks_by_item):
    """Maps item -> (model_mark, substitution_mark) to the x/y of the sheet."""
    pairs = build_review_pairs()
    answers = {pair.item_id: {"x": "ok", "y": "ok"} for pair in pairs}
    for pair in pairs:
        if pair.item_id in marks_by_item:
            model, substitution = marks_by_item[pair.item_id]
            answers[pair.item_id] = (
                {"x": model, "y": substitution}
                if pair.x_is_model
                else {"x": substitution, "y": model}
            )
    return answers


def test_an_empty_mark_beside_a_filled_one_is_mid():
    assert harness.answers_problem(_answers(r02_dative=("", "ok"))) is None
    assert harness.answers_problem(_answers(r02_dative=("mid", "mid"))) is None


def test_both_marks_empty_is_an_error_that_says_to_write_mid():
    problem = harness.answers_problem(_answers(r02_dative=("", "")))

    assert "r02_dative" in problem
    assert "write mid explicitly" in problem


def test_an_unknown_or_missing_mark_is_an_error_naming_the_item():
    assert "r02_dative" in harness.answers_problem(_answers(r02_dative=("fine", "ok")))
    answers = _answers()
    del answers["r05_instrumental"]
    assert "r05_instrumental" in harness.answers_problem(answers)


def test_a_mid_substitution_counts_as_wrong_and_an_ok_model_beats_it():
    case = harness.case_result(
        build_review_pairs(),
        _answers(r02_dative=("ok", ""), r03_genitive=("ok", "bad")),
        {"r02_dative": True, "r03_genitive": True},
    )

    assert (case.fallback_wrong, case.model_right_where_fallback_wrong) == (2, 2)


def test_a_model_that_is_only_mid_or_not_validated_does_not_beat_the_substitution():
    case = harness.case_result(
        build_review_pairs(),
        _answers(
            r02_dative=("mid", "bad"),
            r03_genitive=("ok", "mid"),
            r04_accusative=("ok", "ok"),
        ),
        {"r02_dative": True, "r03_genitive": False, "r04_accusative": True},
    )

    assert (case.fallback_wrong, case.model_right_where_fallback_wrong) == (2, 0)


def test_no_item_with_a_non_ok_substitution_leaves_the_benefit_unmeasured():
    case = harness.case_result(build_review_pairs(), _answers(), {})

    assert case.beaten_share is None


def test_the_scale_summary_counts_marks_and_compares_on_ok_mid_bad():
    summary = harness.scale_summary(
        build_review_pairs(),
        _answers(
            r02_dative=("ok", "mid"),
            r03_genitive=("mid", "bad"),
            r04_accusative=("bad", "ok"),
            r05_instrumental=("mid", ""),
        ),
    )

    assert summary.model_counts == {"ok": 27, "mid": 2, "bad": 1}
    assert summary.substitution_counts == {"ok": 27, "mid": 2, "bad": 1}
    assert summary.strictly_better == 2
    assert summary.model_worse == ["r04_accusative"]
    assert summary.items == 30


def test_the_decision_uses_the_non_ok_substitution_rule():
    generations = [_generation(item_id=item.item_id) for item in ITEMS]
    answers = _answers(r02_dative=("ok", ""), r03_genitive=("ok", "mid"))

    keep, reasons = harness.final_decision(generations, answers)

    assert keep
    assert reasons == []


def test_the_review_sheet_header_explains_the_three_level_scale(tmp_path):
    harness._write_review_files(tmp_path, _full_run())

    sheet = (tmp_path / harness.SHEET_NAME).read_text(encoding="utf-8")
    header = sheet.split("## r01_nominative")[0]

    assert "bad" in header
    assert "mid" in header
    assert "critically wrong" in header
    assert "meaning comes through" in header
    assert "ok if the sentence is grammatically right" not in header
    assert "changed digit" in header


def test_the_answer_template_explains_that_empty_means_mid(tmp_path):
    harness._write_review_files(tmp_path, _full_run())

    template = (tmp_path / harness.ANSWERS_NAME).read_text(encoding="utf-8")

    assert "ok, mid or bad" in template
    assert "empty" in template.splitlines()[0]


def test_score_reports_the_scale_counts_and_the_worse_items(tmp_path, capsys):
    generations = _full_run()
    harness.save_generations(tmp_path / harness.RESULTS_NAME, generations)
    harness._write_review_files(tmp_path, generations)
    answers = _answers(r02_dative=("ok", ""), r04_accusative=("bad", "ok"))
    lines = []
    for item_id, sides in answers.items():
        lines.append(f'[{item_id}]\nx = "{sides["x"]}"\ny = "{sides["y"]}"\n')
    (tmp_path / harness.ANSWERS_NAME).write_text("\n".join(lines), encoding="utf-8")

    exit_code = harness.main(["--out", str(tmp_path), "score"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "model output marks: ok=" in output
    assert "substitution marks: ok=" in output
    assert "strictly better" in output
    assert "r04_accusative" in output
