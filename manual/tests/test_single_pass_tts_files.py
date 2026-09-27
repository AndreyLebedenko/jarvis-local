import pytest

from manual.single_pass_tts_corpus import CORPUS, SEEDS
from manual.single_pass_tts_files import (
    CALLS_DIR_NAME,
    KEY_FILE_NAME,
    ReviewStepError,
    answers_path,
    sheet_path,
    write_equalized_review,
    write_production_review,
    write_report,
)
from manual.single_pass_tts_records import (
    CallRecord,
    GenerationKey,
    Level,
    Stage,
    StreamChunk,
    write_record,
)
from manual.single_pass_tts_review import Sitting

A_VOICE_SECOND = 5.0
B_VOICE_SECOND = 2.0


def _record(key, stage, started_at, chunks):
    return CallRecord(
        key=key,
        stage=stage,
        started_at=started_at,
        chunks=tuple(chunks),
        done_reason="stop",
        eval_count=10,
        prompt_eval_count=100,
        system_prompt_sha256="sha",
    )


def _write_generation(calls_dir, key):
    canvas = f"| {key.slug} | a |"
    write_record(
        calls_dir,
        _record(key, Stage.A_PASS1, 0.0, [StreamChunk(3.0, canvas)]),
    )
    pass2_stages = [Stage.A_PROD_PASS2]
    if key.level is Level.MEDIUM:
        pass2_stages.append(Stage.A_EQ_PASS2)
    for stage in pass2_stages:
        voice = f"Голос {stage} для {key.slug}. "
        write_record(
            calls_dir,
            _record(key, stage, 3.0, [StreamChunk(A_VOICE_SECOND - 3.0, voice)]),
        )
    b_content = f"{canvas} b\n<tts>Голос b для {key.slug}. </tts>"
    write_record(
        calls_dir,
        _record(key, Stage.B, 100.0, [StreamChunk(B_VOICE_SECOND, b_content)]),
    )


@pytest.fixture
def out_dir(tmp_path):
    calls_dir = tmp_path / CALLS_DIR_NAME
    calls_dir.mkdir()
    for level in (Level.OFF, Level.MEDIUM):
        for prompt in CORPUS:
            for seed in SEEDS:
                _write_generation(
                    calls_dir, GenerationKey(level, prompt.prompt_id, seed)
                )
    return tmp_path


def _fill_as_all_ties(path):
    text = path.read_text(encoding="utf-8")
    text = text.replace('verdict = ""', 'verdict = "="')
    text = text.replace('guess_b = ""', 'guess_b = "X"')
    text = text.replace('invented = ""', 'invented = "no"')
    path.write_text(text, encoding="utf-8")


def test_production_step_writes_key_sheet_and_blank_answers(out_dir):
    write_production_review(out_dir)

    assert (out_dir / KEY_FILE_NAME).exists()
    assert sheet_path(out_dir, Sitting.PRODUCTION).exists()
    assert 'verdict = ""' in answers_path(out_dir, Sitting.PRODUCTION).read_text(
        encoding="utf-8"
    )
    assert not sheet_path(out_dir, Sitting.EQUALIZED).exists()


def test_rerunning_the_production_step_keeps_the_reviewers_answers(out_dir):
    write_production_review(out_dir)
    _fill_as_all_ties(answers_path(out_dir, Sitting.PRODUCTION))
    filled = answers_path(out_dir, Sitting.PRODUCTION).read_text(encoding="utf-8")

    write_production_review(out_dir)

    assert answers_path(out_dir, Sitting.PRODUCTION).read_text("utf-8") == filled


def test_equalized_sheet_is_refused_until_production_answers_are_complete(out_dir):
    write_production_review(out_dir)

    with pytest.raises(ReviewStepError, match="production"):
        write_equalized_review(out_dir)
    assert not sheet_path(out_dir, Sitting.EQUALIZED).exists()

    _fill_as_all_ties(answers_path(out_dir, Sitting.PRODUCTION))
    write_equalized_review(out_dir)
    assert sheet_path(out_dir, Sitting.EQUALIZED).exists()


def test_changed_records_after_the_production_sheet_are_refused(out_dir):
    write_production_review(out_dir)
    key = GenerationKey(Level.OFF, CORPUS[0].prompt_id, SEEDS[0])
    write_record(
        out_dir / CALLS_DIR_NAME,
        _record(key, Stage.B, 0.0, [StreamChunk(1.0, "другой <tts>Текст. </tts>")]),
    )

    with pytest.raises(ReviewStepError, match="records changed"):
        write_production_review(out_dir)


def test_report_applies_the_decision_rule_without_the_equalized_sitting(out_dir):
    write_production_review(out_dir)
    _fill_as_all_ties(answers_path(out_dir, Sitting.PRODUCTION))

    report = write_report(out_dir).read_text(encoding="utf-8")

    assert "GO" in report
    assert "not reviewed" in report


def test_report_includes_the_equalized_sitting_once_it_is_answered(out_dir):
    write_production_review(out_dir)
    _fill_as_all_ties(answers_path(out_dir, Sitting.PRODUCTION))
    write_equalized_review(out_dir)
    _fill_as_all_ties(answers_path(out_dir, Sitting.EQUALIZED))

    report = write_report(out_dir).read_text(encoding="utf-8")

    assert "not reviewed" not in report


def test_report_without_a_review_key_names_the_missing_step(tmp_path):
    with pytest.raises(ReviewStepError, match="review step"):
        write_report(tmp_path)
