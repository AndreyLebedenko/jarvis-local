from manual.personal_proxy.confidence import JudgeResult
from manual.personal_proxy.confidence_report import (
    BASE_KEY,
    SAMPLE_KEYS,
    Signals,
    compute_signals,
    evaluate,
    render_report,
)
from manual.personal_proxy.corpus import utterance_by_id
from manual.personal_proxy.transcription_ab import reference_text

WORDS = [(" Позвони", 0.9), (" Майкл", 0.2)]
SEGMENTS = [{"no_speech_prob": 0.1, "avg_logprob": -0.3}]
NAMES = ("S1", "S2", "S3a", "S3b", "S3c", "S5", "J1", "J2", "J3", "T")


def _compute(samples, judges, whisper="Позвони Майкл", utterance=None):
    return compute_signals("x", utterance, whisper, WORDS, SEGMENTS, samples, judges)


def _same(text, confidence=0.9):
    samples = dict.fromkeys(SAMPLE_KEYS, text)
    judges = dict.fromkeys(SAMPLE_KEYS, JudgeResult(confidence, []))
    return samples, judges


def test_identical_samples_and_texts_give_zero_disagreement_and_instability():
    samples, judges = _same("Позвони Майкл")

    scores = _compute(samples, judges).scores

    assert scores["S1"] == 0.0
    assert scores["S2"] == 0.0


def test_a_differing_sample_raises_instability():
    samples, judges = _same("Позвони Майкл Браун 12345")
    samples[SAMPLE_KEYS[1]] = "Позвони Майкл Браун 12346"

    assert _compute(samples, judges).scores["S2"] > 0.0


def test_engine_confidence_scores_come_from_words_and_segments():
    samples, judges = _same("Позвони Майкл")

    scores = _compute(samples, judges).scores

    assert scores["S3a"] == 0.8
    assert scores["S3b"] == 0.1
    assert scores["S3c"] == 0.3


def test_judge_scores_use_base_and_minimum_confidence():
    samples, judges = _same("Позвони Майкл", 0.9)
    judges[SAMPLE_KEYS[0]] = JudgeResult(0.2, ["Майкл"])
    judges[BASE_KEY] = JudgeResult(0.7, ["a", "b"])

    scores = _compute(samples, judges).scores

    assert round(scores["J1"], 2) == 0.3
    assert round(scores["J2"], 2) == 0.8
    assert scores["J3"] == 2.0


def test_unparsable_judge_counts_as_zero_confidence():
    samples, judges = _same("Позвони Майкл")
    judges[BASE_KEY] = None

    assert _compute(samples, judges).scores["J1"] == 1.0


def test_trivial_baseline_flags_text_with_sensitive_content_only():
    samples, judges = _same("позвони позже")
    assert _compute(samples, judges).scores["T"] == 0.0

    samples, judges = _same("Позвони 89123456789")
    assert _compute(samples, judges).scores["T"] == 1.0


def test_label_is_taken_from_the_base_sample():
    utterance = utterance_by_id("id_email")
    good = reference_text(utterance)
    samples, judges = _same(good)
    samples[BASE_KEY] = "Пиши на почту."

    assert _compute(samples, judges, whisper=good, utterance=utterance).bad is True


def _signals(subject, bad, **scores):
    return Signals(subject, bad, {**dict.fromkeys(NAMES, 0.0), **scores})


def test_evaluation_finds_the_signal_that_separates_bad_from_good():
    recordings = [
        _signals("a", True, S1=3.0, T=1.0),
        _signals("b", True, S1=2.0, T=1.0),
        _signals("c", False, S1=0.0, T=1.0),
        _signals("d", False, S1=0.0, T=1.0),
        _signals("e", False, S1=0.0, T=0.0),
    ]
    controls = [_signals("ctl", None, S3b=0.9, S3c=3.0)]

    found = {e.name: e for e in evaluate(recordings, controls)}

    assert found["S1"].discriminating
    assert not found["S2"].discriminating


def test_report_names_the_verdict_and_the_bad_recordings():
    recordings = [_signals("a", True, S1=3.0, T=1.0), _signals("b", False, T=0.0)]
    controls = [_signals("ctl", None, S3b=0.9, S3c=3.0)]
    evaluations = evaluate(recordings, controls)

    report = render_report(recordings, controls, evaluations, 0, ["x"])

    assert "Fewer than 5 bad" in report
    assert "- a: caught by" in report
    assert "| S1 |" in report


def test_hypothesis_flags_on_instability_or_listed_fragments_only():
    from manual.personal_proxy.confidence_report import HYPOTHESIS_RULES, flagged_by

    assert flagged_by(_signals("a", True, S2=0.6), HYPOTHESIS_RULES)
    assert flagged_by(_signals("a", True, J3=1.0), HYPOTHESIS_RULES)
    assert not flagged_by(_signals("a", True, S2=0.5, S1=9.0), HYPOTHESIS_RULES)


def _batch(bad_flagged, bad_total, good_flagged, good_total):
    flagged = {"S2": 1.0}
    rows = [
        _signals(f"b{i}", True, T=1.0, **(flagged if i < bad_flagged else {}))
        for i in range(bad_total)
    ]
    rows += [
        _signals(f"g{i}", False, T=1.0, **(flagged if i < good_flagged else {}))
        for i in range(good_total)
    ]
    return rows


def test_hypothesis_holds_with_high_recall_and_few_false_refusals():
    from manual.personal_proxy.confidence_report import flagging, hypothesis_verdict

    rows = _batch(5, 6, 2, 20)
    h = flagging(rows, (("S2", 0.6),))

    assert hypothesis_verdict(h, trivial_false_refusals=0.9) == "H holds"


def test_hypothesis_fails_with_low_recall():
    from manual.personal_proxy.confidence_report import flagging, hypothesis_verdict

    h = flagging(_batch(2, 6, 0, 20), (("S2", 0.6),))

    assert hypothesis_verdict(h, 0.9) == "H fails"


def test_hypothesis_is_inconclusive_between_the_two_bounds():
    from manual.personal_proxy.confidence_report import flagging, hypothesis_verdict

    h = flagging(_batch(4, 6, 2, 20), (("S2", 0.6),))

    assert hypothesis_verdict(h, 0.9) == "inconclusive"


def test_hypothesis_needs_five_bad_recordings_to_conclude():
    from manual.personal_proxy.confidence_report import flagging, hypothesis_verdict

    h = flagging(_batch(4, 4, 0, 20), (("S2", 0.6),))

    assert hypothesis_verdict(h, 0.9).startswith("nothing concluded")


def test_hypothesis_must_beat_the_trivial_baseline():
    from manual.personal_proxy.confidence_report import flagging, hypothesis_verdict

    h = flagging(_batch(6, 6, 3, 20), (("S2", 0.6),))

    assert hypothesis_verdict(h, trivial_false_refusals=0.1) != "H holds"
