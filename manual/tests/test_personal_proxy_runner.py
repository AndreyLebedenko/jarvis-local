import asyncio
import json

import pytest

from jarvis.core.config import GenerationOptions
from manual.personal_proxy_records import (
    Arm,
    CallRecord,
    CallStage,
    load_generations,
)
from manual.personal_proxy_runner import (
    ARMS,
    CACHE_RESET_NUM_PREDICT,
    NUM_PREDICT,
    GenerationJob,
    GenerationRunner,
    RunMetaMismatchError,
    choose_use_format,
    ensure_run_meta,
    plan_jobs,
    run_jobs,
)


class FakeCaller:
    def __init__(self, reply=None, fail_on=None):
        self.requests = []
        self._reply = reply or (lambda request: "{}")
        self._fail_on = fail_on

    async def __call__(self, request):
        self.requests.append(request)
        if self._fail_on and self._fail_on(request):
            raise RuntimeError("ollama down")
        return CallRecord(
            request.stage,
            {"messages": [dict(m) for m in request.messages]},
            self._reply(request),
            "stop",
            3,
            4,
            0.0,
            0.5,
        )


def _runner(caller, use_format=False):
    return GenerationRunner(
        caller,
        GenerationOptions(temperature=0.2),
        transcribe_instruction="Transcribe it.",
        topics="- test topic",
        use_format=use_format,
    )


def _run(coro):
    return asyncio.run(coro)


def test_jobs_cover_every_seed_subject_and_arm():
    jobs = plan_jobs(["a", "b"], seeds=(1, 2))

    assert len(jobs) == 2 * 2 * len(ARMS)
    assert {(j.subject_id, j.arm, j.seed) for j in jobs} == {
        (s, arm, seed) for s in "ab" for arm in ARMS for seed in (1, 2)
    }


def test_first_arm_rotates_between_subjects():
    jobs = plan_jobs(["a", "b", "c"], seeds=(1,))

    firsts = [jobs[i * len(ARMS)].arm for i in range(3)]

    assert firsts == [ARMS[0], ARMS[1], ARMS[2]]


def test_two_step_feeds_the_transcript_into_the_text_only_second_call():
    caller = FakeCaller(
        lambda r: "позвони Марине" if r.stage is CallStage.TRANSCRIBE else "{}"
    )

    record = _run(_runner(caller).run(GenerationJob("x", Arm.T_PLUS_S, 7), b"wav"))

    first, second = caller.requests
    assert (first.stage, first.audio) == (CallStage.TRANSCRIBE, b"wav")
    assert first.messages == ({"role": "user", "content": "Transcribe it."},)
    assert (second.stage, second.audio) == (CallStage.SANITIZE_TEXT, None)
    assert second.messages[-1]["content"].endswith("позвони Марине")
    assert [c.stage for c in record.calls] == [
        CallStage.TRANSCRIBE,
        CallStage.SANITIZE_TEXT,
    ]


def test_combined_user_arm_makes_one_call_without_a_system_message():
    caller = FakeCaller()

    _run(_runner(caller).run(GenerationJob("x", Arm.C_USER, 7), b"wav"))

    (request,) = caller.requests
    assert request.stage is CallStage.COMBINED
    assert request.audio == b"wav"
    assert [m["role"] for m in request.messages] == ["user"]
    assert "test topic" in request.messages[0]["content"]


def test_combined_system_arm_puts_the_rules_in_a_system_message():
    caller = FakeCaller()

    _run(_runner(caller).run(GenerationJob("x", Arm.C_SYSTEM, 7), b"wav"))

    assert [m["role"] for m in caller.requests[0].messages] == ["system", "user"]


def test_every_call_carries_the_job_seed_and_the_runaway_cap():
    caller = FakeCaller()

    _run(_runner(caller).run(GenerationJob("x", Arm.T_PLUS_S, 4243), b"wav"))

    for request in caller.requests:
        assert request.options.seed == 4243
        assert request.options.num_predict == NUM_PREDICT
        assert request.options.temperature == 0.2


def test_constrained_format_is_applied_only_when_enabled():
    constrained, plain = FakeCaller(), FakeCaller()

    _run(
        _runner(constrained, use_format=True).run(
            GenerationJob("x", Arm.C_USER, 1), b"w"
        )
    )
    _run(_runner(plain).run(GenerationJob("x", Arm.C_USER, 1), b"w"))

    assert "raw_transcript" in constrained.requests[0].response_format["required"]
    assert plain.requests[0].response_format is None


def test_a_no_media_job_sends_no_audio():
    caller = FakeCaller()

    _run(_runner(caller).run(GenerationJob("ctl_no_media", Arm.C_USER, 1), None))

    assert caller.requests[0].audio is None


def test_a_failing_call_is_recorded_as_an_error_with_the_calls_made_so_far():
    caller = FakeCaller(fail_on=lambda r: r.stage is CallStage.SANITIZE_TEXT)

    record = _run(_runner(caller).run(GenerationJob("x", Arm.T_PLUS_S, 1), b"wav"))

    assert "ollama down" in record.error
    assert [c.stage for c in record.calls] == [CallStage.TRANSCRIBE]


def test_run_jobs_warms_up_then_resets_the_cache_before_each_generation(tmp_path):
    caller = FakeCaller()
    jobs = [GenerationJob("x", Arm.C_USER, 1), GenerationJob("x", Arm.C_SYSTEM, 1)]

    summary = _run(
        run_jobs(_runner(caller), jobs, lambda _: b"wav", tmp_path, warm_audio=b"w")
    )

    kinds = [
        "warm"
        if r.options.num_predict == 32
        else "reset"
        if r.options.num_predict == CACHE_RESET_NUM_PREDICT
        else "gen"
        for r in caller.requests
    ]
    assert kinds == ["warm", "reset", "gen", "reset", "gen"]
    assert (summary.ran, summary.skipped, summary.errored) == (2, 0, 0)
    assert len(load_generations(tmp_path)) == 2


def test_a_resumed_run_skips_finished_generations(tmp_path):
    jobs = [GenerationJob("x", Arm.C_USER, 1), GenerationJob("x", Arm.C_SYSTEM, 1)]
    _run(
        run_jobs(
            _runner(FakeCaller()), jobs[:1], lambda _: b"w", tmp_path, warm_audio=None
        )
    )
    caller = FakeCaller()

    summary = _run(
        run_jobs(_runner(caller), jobs, lambda _: b"w", tmp_path, warm_audio=None)
    )

    assert (summary.ran, summary.skipped) == (1, 1)


def test_errors_are_counted_and_still_written(tmp_path):
    caller = FakeCaller(
        fail_on=lambda r: r.stage is CallStage.COMBINED and r.options.seed == 1
    )
    jobs = [GenerationJob("x", Arm.C_USER, 1)]

    summary = _run(
        run_jobs(_runner(caller), jobs, lambda _: b"w", tmp_path, warm_audio=None)
    )

    assert summary.errored == 1
    assert load_generations(tmp_path)[0].error is not None


def test_progress_is_reported_per_generation(tmp_path):
    seen = []

    _run(
        run_jobs(
            _runner(FakeCaller()),
            [GenerationJob("x", Arm.C_USER, 1)],
            lambda _: b"w",
            tmp_path,
            warm_audio=None,
            progress=seen.append,
        )
    )

    assert [r.slug for r in seen] == ["c_user-x-s1"]


def test_run_meta_is_written_once_and_then_compared(tmp_path):
    path = tmp_path / "run_meta.json"
    ensure_run_meta(path, {"model": "gemma", "corpus": "abc"})

    ensure_run_meta(path, {"model": "gemma", "corpus": "abc"})

    assert json.loads(path.read_text(encoding="utf-8"))["model"] == "gemma"


def test_changed_inputs_are_named_in_the_refusal(tmp_path):
    path = tmp_path / "run_meta.json"
    ensure_run_meta(path, {"model": "gemma", "corpus": "abc"})

    with pytest.raises(RunMetaMismatchError) as error:
        ensure_run_meta(path, {"model": "other", "corpus": "abc"})

    assert error.value.changed == ["model"]


def test_constrained_output_is_chosen_only_when_strictly_more_valid():
    assert choose_use_format(24, 24, 20, 24)
    assert not choose_use_format(22, 24, 22, 24)
    assert not choose_use_format(20, 24, 22, 24)
    assert not choose_use_format(0, 0, 0, 0)
