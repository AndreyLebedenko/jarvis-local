from manual.personal_proxy.records import (
    COLD_LOAD_SECONDS,
    Arm,
    CallRecord,
    CallStage,
    GenerationRecord,
    generation_exists,
    load_generations,
    write_generation,
)


def _call(stage=CallStage.COMBINED, total=1.5, load=0.0, text='{"a": "я"}'):
    return CallRecord(
        stage=stage,
        request={"model": "m", "messages": [{"role": "user", "content": "x"}]},
        response_text=text,
        done_reason="stop",
        eval_count=7,
        prompt_eval_count=11,
        load_seconds=load,
        total_seconds=total,
    )


def _generation(calls=None, error=None):
    return GenerationRecord(
        "id_email",
        Arm.C_USER,
        19210,
        tuple(calls if calls is not None else [_call()]),
        error,
    )


def test_slug_names_arm_subject_and_seed():
    assert _generation().slug == "c_user-id_email-s19210"


def test_total_seconds_sums_every_call():
    record = _generation(
        [_call(CallStage.TRANSCRIBE, 1.0), _call(CallStage.SANITIZE_TEXT, 0.5)]
    )

    assert record.total_seconds == 1.5


def test_a_generation_with_a_slow_model_load_is_cold():
    assert _generation([_call(load=COLD_LOAD_SECONDS + 0.1)]).is_cold
    assert not _generation([_call(load=0.2)]).is_cold


def test_round_trip_preserves_cyrillic_and_calls(tmp_path):
    original = _generation(
        [_call(CallStage.TRANSCRIBE, text="позвони Марине"), _call()], error="boom"
    )

    write_generation(tmp_path, original)

    assert load_generations(tmp_path) == [original]


def test_existence_check_matches_what_was_written(tmp_path):
    record = _generation()
    assert not generation_exists(tmp_path, record.arm, record.subject_id, record.seed)

    write_generation(tmp_path, record)

    assert generation_exists(tmp_path, record.arm, record.subject_id, record.seed)


def test_no_temporary_file_is_left_after_a_write(tmp_path):
    write_generation(tmp_path, _generation())

    assert [p.name for p in tmp_path.iterdir()] == ["c_user-id_email-s19210.json"]


def test_loading_a_missing_directory_is_empty(tmp_path):
    assert load_generations(tmp_path / "absent") == []


def test_call_for_finds_a_stage_or_none():
    record = _generation([_call(CallStage.TRANSCRIBE)])

    assert record.call_for(CallStage.TRANSCRIBE) is not None
    assert record.call_for(CallStage.SANITIZE_TEXT) is None
