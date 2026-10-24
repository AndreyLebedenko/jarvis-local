import numpy as np

from jarvis.personal_proxy.confirmation.confirmation_vocabulary import (
    NO_PHRASES,
    YES_PHRASES,
    AnswerKind,
    classify_answer,
)
from jarvis.personal_proxy.stt.speech_guard import SpeechProbabilities
from jarvis.personal_proxy.stt.stt_result import Transcription
from manual.personal_proxy.answer_words import (
    PHRASES,
    REPETITIONS,
    Phrase,
    Trial,
    measure,
    render,
    summarize,
)

WINDOW = 0.032
CLIP = np.zeros(16000, dtype=np.float32)


class _Engine:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def transcribe(self, clip):
        self.calls += 1
        return Transcription(text=self.text, words=(), segments=())


def _probabilities(speaking_windows):
    def source(clip):
        return SpeechProbabilities(
            values=[1.0] * speaking_windows + [0.0] * 5, window_seconds=WINDOW
        )

    return source


def _measure(phrase, text, speaking_windows=20):
    return measure(
        phrase,
        CLIP,
        _Engine(text),
        _probabilities(speaking_windows),
        vad_threshold=0.5,
        minimum_speech_seconds=0.3,
    )


def test_each_phrase_is_repeated_ten_times():
    assert REPETITIONS == 10


def test_the_phrases_are_the_ones_the_card_names_with_the_expected_meaning():
    spoken = {phrase.text: phrase.expected for phrase in PHRASES}

    assert spoken["да"] is AnswerKind.YES
    assert spoken["нет"] is AnswerKind.NO
    assert spoken["отправляй"] is AnswerKind.YES
    assert spoken["стоп"] is AnswerKind.NO
    assert spoken["yes"] is AnswerKind.YES
    assert spoken["no"] is AnswerKind.NO
    assert spoken["да, но исправь"] is AnswerKind.UNCLEAR
    assert len(PHRASES) == 8
    neutral = [p for p in PHRASES if p.expected is AnswerKind.UNCLEAR]
    assert len(neutral) == 2


def test_the_expected_meaning_of_each_phrase_matches_the_classifier():
    for phrase in PHRASES:
        assert classify_answer(phrase.text) is phrase.expected


def test_the_vocabulary_phrases_used_exist_in_the_vocabulary():
    for phrase in PHRASES:
        if phrase.expected is AnswerKind.YES:
            assert phrase.text in YES_PHRASES
        if phrase.expected is AnswerKind.NO:
            assert phrase.text in NO_PHRASES


def test_a_clip_with_enough_speech_is_classified_from_the_whisper_text():
    trial = _measure(Phrase("да", AnswerKind.YES), "Да.")

    assert trial.rejected is False
    assert trial.text == "Да."
    assert trial.kind is AnswerKind.YES
    assert trial.speech_seconds == 20 * WINDOW


def test_a_clip_below_the_speech_minimum_is_rejected_and_unclear_without_the_engine():
    engine = _Engine("Да.")

    trial = measure(
        Phrase("да", AnswerKind.YES),
        CLIP,
        engine,
        _probabilities(5),
        vad_threshold=0.5,
        minimum_speech_seconds=0.3,
    )

    assert trial.rejected is True
    assert trial.kind is AnswerKind.UNCLEAR
    assert trial.text == ""
    assert engine.calls == 0


def _trial(phrase, expected, kind, rejected=False, seconds=0.5, text="t"):
    return Trial(phrase, expected, seconds, rejected, text, kind)


def test_the_summary_counts_the_classes_and_the_rejections_per_phrase():
    trials = [
        _trial("да", AnswerKind.YES, AnswerKind.YES),
        _trial("да", AnswerKind.YES, AnswerKind.YES),
        _trial("да", AnswerKind.YES, AnswerKind.UNCLEAR, rejected=True, text=""),
        _trial("да", AnswerKind.YES, AnswerKind.NO),
    ]

    (summary,) = summarize(trials)

    assert summary.trials == 4
    assert summary.rejected == 1
    assert (summary.yes, summary.no, summary.unclear) == (2, 1, 1)
    assert summary.as_expected == 2


def test_a_yes_heard_for_a_phrase_that_is_not_a_yes_is_a_false_yes():
    trials = [
        _trial("нет", AnswerKind.NO, AnswerKind.YES),
        _trial("да, но исправь", AnswerKind.UNCLEAR, AnswerKind.YES),
        _trial("да", AnswerKind.YES, AnswerKind.YES),
    ]

    by_phrase = {s.phrase: s for s in summarize(trials)}

    assert by_phrase["нет"].false_yes == 1
    assert by_phrase["да, но исправь"].false_yes == 1
    assert by_phrase["да"].false_yes == 0


def test_the_summary_keeps_the_phrase_order_of_first_appearance():
    trials = [
        _trial("нет", AnswerKind.NO, AnswerKind.NO),
        _trial("да", AnswerKind.YES, AnswerKind.YES),
        _trial("нет", AnswerKind.NO, AnswerKind.NO),
    ]

    assert [s.phrase for s in summarize(trials)] == ["нет", "да"]


def test_the_summary_reports_the_least_and_mean_speech_seconds():
    trials = [
        _trial("да", AnswerKind.YES, AnswerKind.YES, seconds=0.2),
        _trial("да", AnswerKind.YES, AnswerKind.YES, seconds=0.6),
    ]

    (summary,) = summarize(trials)

    assert summary.least_speech_seconds == 0.2
    assert abs(summary.mean_speech_seconds - 0.4) < 1e-9


def test_the_rendered_table_has_a_row_per_phrase_and_names_false_yes():
    trials = [_trial("нет", AnswerKind.NO, AnswerKind.YES, text="Нет.")]

    text = render(summarize(trials))

    assert "нет" in text
    assert "false yes" in text.lower()


def test_a_trial_line_shows_the_whisper_text_the_class_the_seconds_and_the_guard():
    from manual.personal_proxy.answer_words import render_trial

    accepted = render_trial(3, _trial("да", AnswerKind.YES, AnswerKind.YES, text="Да."))
    rejected = render_trial(
        4, _trial("да", AnswerKind.YES, AnswerKind.UNCLEAR, rejected=True, text="")
    )

    assert "Да." in accepted
    assert "yes" in accepted
    assert "0.50" in accepted
    assert "guard: ok" in accepted
    assert "guard: REJECTED" in rejected
    assert "unclear" in rejected


def test_the_harness_parser_defaults_to_ten_repetitions_and_config_toml():
    from pathlib import Path

    from manual import manual_check_answer_words as harness

    args = harness.build_parser().parse_args(["run"])

    assert args.repetitions == REPETITIONS
    assert args.config == Path("config.toml")
