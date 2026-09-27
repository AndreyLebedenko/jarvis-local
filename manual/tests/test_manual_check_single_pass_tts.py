import asyncio
import dataclasses
import json

import pytest

from jarvis.core.config import (
    GenerationOptions,
    GenerationProfile,
    GenerationSettings,
    HistorySettings,
)
from jarvis.dialog.thinking_mode import ReasoningLevel
from manual.manual_check_single_pass_tts import (
    CACHE_RESET_NUM_PREDICT,
    CACHE_RESET_SYSTEM,
    NUM_PREDICT,
    LiveRunner,
    RequestFactory,
    RunMetaMismatchError,
    arm_order,
    check_or_write_meta,
    discard_partial_generation,
    generation_stages,
    is_generation_complete,
    needs_pass2,
)
from manual.single_pass_tts_corpus import B_CONTRACT, CORPUS, SEEDS
from manual.single_pass_tts_records import (
    CallRecord,
    GenerationKey,
    Level,
    Stage,
    StreamChunk,
    write_record,
)

BASE_PROMPT = "You are Jarvis."
LEVEL_2_SECTION = "Think in level 2."
DERIVATIVE_PROMPT = "Retell the text aloud."
TIME_CONTEXT = "воскресенье, 2026-09-27T12:00+01:00"
PROMPT_TEXT = "Сколько секунд в сутках?"


def _generation_settings() -> GenerationSettings:
    profiles = dict(GenerationSettings().profiles)
    profiles["dialog.medium"] = GenerationProfile(
        options=GenerationOptions(temperature=0.5),
        prompt=LEVEL_2_SECTION,
        reasoning="medium",
    )
    profiles["spoken_derivative"] = GenerationProfile(
        options=GenerationOptions(temperature=0.2), prompt=DERIVATIVE_PROMPT
    )
    return GenerationSettings(
        defaults=GenerationOptions(temperature=0.618, top_p=0.9, num_predict=100),
        profiles=profiles,
    )


def _factory() -> RequestFactory:
    return RequestFactory.from_settings(
        _generation_settings(),
        HistorySettings(),
        base_system_prompt=BASE_PROMPT,
        time_context=TIME_CONTEXT,
    )


def _key(level: Level = Level.MEDIUM, seed: int = 7) -> GenerationKey:
    return GenerationKey(level, "fact_seconds", seed)


def _record(key: GenerationKey, stage: Stage, content: str, done_reason="stop"):
    return CallRecord(
        key=key,
        stage=stage,
        started_at=0.0,
        chunks=(StreamChunk(0.1, content),),
        done_reason=done_reason,
        eval_count=1,
        prompt_eval_count=1,
        system_prompt_sha256="x",
    )


def test_pass1_system_prompt_is_the_production_composition_for_the_level():
    request = _factory().pass1(_key(Level.MEDIUM), PROMPT_TEXT)

    assert request.messages[0] == {
        "role": "system",
        "content": f"{BASE_PROMPT}\n\n{LEVEL_2_SECTION}",
    }


def test_pass1_at_off_has_no_level_section():
    request = _factory().pass1(_key(Level.OFF), PROMPT_TEXT)

    assert request.messages[0]["content"] == BASE_PROMPT


def test_pass1_ends_with_the_fixed_time_context_then_the_prompt():
    request = _factory().pass1(_key(), PROMPT_TEXT)

    assert request.messages[-2:] == (
        {"role": "system", "content": TIME_CONTEXT},
        {"role": "user", "content": PROMPT_TEXT},
    )


def test_b_differs_from_pass1_only_by_the_contract_appended_to_the_system_prompt():
    factory = _factory()
    pass1 = factory.pass1(_key(), PROMPT_TEXT)
    b = factory.b(_key(), PROMPT_TEXT)

    assert b.messages[0]["content"] == (
        f"{pass1.messages[0]['content']}\n\n{B_CONTRACT}"
    )
    assert b.messages[1:] == pass1.messages[1:]
    assert (b.reasoning, b.options) == (pass1.reasoning, pass1.options)


def test_pass1_uses_the_dialog_profile_with_the_spike_seed_and_cap():
    request = _factory().pass1(_key(Level.MEDIUM, seed=42), PROMPT_TEXT)

    assert request.reasoning is ReasoningLevel.MEDIUM
    assert request.options.temperature == 0.5
    assert request.options.top_p == 0.9
    assert request.options.seed == 42
    assert request.options.num_predict == NUM_PREDICT


def test_a_prod_pass2_is_run_derivative_pass_over_the_verbatim_canvas():
    canvas = "  | a | b |\n"
    request = _factory().pass2(_key(seed=42), Stage.A_PROD_PASS2, canvas)

    assert request.messages == (
        {"role": "system", "content": DERIVATIVE_PROMPT},
        {"role": "user", "content": canvas},
    )
    assert request.reasoning is ReasoningLevel.OFF
    assert request.options.temperature == 0.2
    assert (request.options.seed, request.options.num_predict) == (42, NUM_PREDICT)


def test_a_eq_pass2_changes_only_reasoning_to_the_pass1_level():
    factory = _factory()
    prod = factory.pass2(_key(Level.MEDIUM), Stage.A_PROD_PASS2, "canvas")
    eq = factory.pass2(_key(Level.MEDIUM), Stage.A_EQ_PASS2, "canvas")

    assert eq.reasoning is ReasoningLevel.MEDIUM
    assert (eq.messages, eq.options) == (prod.messages, prod.options)


def test_pass2_rejects_a_stage_that_is_not_a_pass2():
    with pytest.raises(ValueError):
        _factory().pass2(_key(), Stage.B, "canvas")


def test_cache_reset_shares_no_system_prefix_with_any_measured_request():
    factory = _factory()
    reset = factory.cache_reset()
    measured_systems = [
        factory.pass1(_key(), PROMPT_TEXT).messages[0]["content"],
        factory.pass2(_key(), Stage.A_PROD_PASS2, "c").messages[0]["content"],
    ]

    reset_system = reset.messages[0]["content"]
    assert all(reset_system[0] != system[0] for system in measured_systems)
    assert reset.reasoning is ReasoningLevel.OFF
    assert reset.options.num_predict == CACHE_RESET_NUM_PREDICT


def test_equalized_pass2_exists_only_at_medium():
    assert generation_stages(Level.OFF) == (
        Stage.A_PASS1,
        Stage.A_PROD_PASS2,
        Stage.B,
    )
    assert Stage.A_EQ_PASS2 in generation_stages(Level.MEDIUM)


def test_arm_order_alternates_between_neighbouring_prompts_and_between_seeds():
    first, second = CORPUS[0].prompt_id, CORPUS[1].prompt_id
    seeds = (1, 2)

    assert arm_order(first, 1, seeds) != arm_order(second, 1, seeds)
    assert arm_order(first, 1, seeds) != arm_order(first, 2, seeds)
    assert sorted(arm_order(first, 1, seeds)) == ["a", "b"]


def test_pass2_is_skipped_only_when_pass1_hit_the_cap_with_no_text():
    key = _key()

    assert needs_pass2(_record(key, Stage.A_PASS1, "text"))
    assert needs_pass2(_record(key, Stage.A_PASS1, "partial", "length"))
    assert not needs_pass2(_record(key, Stage.A_PASS1, "  ", "length"))


def test_generation_is_complete_only_when_every_stage_file_exists(tmp_path):
    key = _key(Level.OFF)
    write_record(tmp_path, _record(key, Stage.A_PASS1, "canvas"))
    write_record(tmp_path, _record(key, Stage.B, "canvas <tts>voice</tts>"))

    assert not is_generation_complete(tmp_path, key)

    write_record(tmp_path, _record(key, Stage.A_PROD_PASS2, "voice"))
    assert is_generation_complete(tmp_path, key)


def test_generation_with_skipped_pass2_is_complete_without_the_pass2_file(tmp_path):
    key = _key(Level.OFF)
    write_record(tmp_path, _record(key, Stage.A_PASS1, "", "length"))
    write_record(tmp_path, _record(key, Stage.B, "canvas <tts>voice</tts>"))

    assert is_generation_complete(tmp_path, key)


def test_run_meta_is_written_once_and_a_changed_meta_is_refused(tmp_path):
    meta = {"model": "m", "corpus_sha256": "a"}
    check_or_write_meta(tmp_path, meta)
    check_or_write_meta(tmp_path, meta)

    assert json.loads((tmp_path / "run_meta.json").read_text("utf-8")) == meta
    with pytest.raises(RunMetaMismatchError, match="corpus_sha256"):
        check_or_write_meta(tmp_path, {"model": "m", "corpus_sha256": "b"})


def test_corpus_has_sixteen_unique_prompts_two_per_category():
    ids = [prompt.prompt_id for prompt in CORPUS]
    categories = [prompt.category for prompt in CORPUS]

    assert len(ids) == len(set(ids)) == 16
    assert all(categories.count(category) == 2 for category in categories)


def test_b_contract_names_the_exact_tags_the_grader_parses():
    assert "<tts>" in B_CONTRACT
    assert "</tts>" in B_CONTRACT


def test_request_options_keep_every_other_generation_default():
    request = _factory().pass1(_key(Level.OFF), PROMPT_TEXT)
    expected = dataclasses.replace(
        GenerationOptions(temperature=0.618, top_p=0.9),
        seed=7,
        num_predict=NUM_PREDICT,
    )

    assert request.options == expected


def test_partial_generation_files_are_discarded_before_a_rerun(tmp_path):
    key = _key(Level.OFF)
    other = _key(Level.OFF, seed=8)
    write_record(tmp_path, _record(key, Stage.A_PASS1, "canvas"))
    write_record(tmp_path, _record(other, Stage.A_PASS1, "canvas"))

    discard_partial_generation(tmp_path, key)

    assert [path.name for path in tmp_path.iterdir()] == [
        "off-fact_seconds-s8-a_pass1.json"
    ]


class _FakeBackend:
    def __init__(self, replies):
        self.calls = []
        self._replies = replies

    async def iter_chat(self, messages, images, reasoning, *, options):
        self.calls.append((messages[0]["content"], reasoning))
        content, done_reason = self._replies(messages)
        yield {"message": {"content": content, "thinking": ""}, "done": False}
        yield {
            "message": {"content": ""},
            "done": True,
            "done_reason": done_reason,
            "eval_count": 3,
            "prompt_eval_count": 50,
        }

    def build_payload(self, messages, images, reasoning, *, options):
        return {"messages": list(messages)}


def _reply_canvas(messages):
    return "канвас <tts>Голос. </tts>", "stop"


def _stage_of(system_prompt: str) -> str:
    if system_prompt == CACHE_RESET_SYSTEM:
        return "reset"
    if system_prompt == DERIVATIVE_PROMPT:
        return "pass2"
    if system_prompt.endswith(B_CONTRACT):
        return "b"
    return "pass1"


def _run_generation(backend, key):
    factory = _factory()
    runner = LiveRunner(backend, factory)
    records = asyncio.run(runner.run_generation(key, PROMPT_TEXT))
    stages = [_stage_of(system) for system, _ in backend.calls]
    return records, stages


def test_live_runner_resets_the_cache_before_each_arm_and_keeps_a_passes_adjacent():
    key = GenerationKey(Level.MEDIUM, CORPUS[0].prompt_id, SEEDS[0])
    backend = _FakeBackend(_reply_canvas)

    records, stages = _run_generation(backend, key)

    expected_a = ["reset", "pass1", "pass2", "pass2"]
    expected_b = ["reset", "b"]
    assert stages in (expected_a + expected_b, expected_b + expected_a)
    assert sorted(r.stage for r in records) == sorted(generation_stages(key.level))


def test_live_runner_records_timing_and_done_fields():
    key = GenerationKey(Level.OFF, CORPUS[0].prompt_id, SEEDS[0])

    records, _ = _run_generation(_FakeBackend(_reply_canvas), key)

    b = next(r for r in records if r.stage is Stage.B)
    assert b.content == "канвас <tts>Голос. </tts>"
    assert (b.done_reason, b.eval_count, b.prompt_eval_count) == ("stop", 3, 50)
    assert b.wall_seconds >= b.chunks[0].t >= 0


def test_live_runner_skips_pass2_after_an_empty_truncated_pass1():
    key = GenerationKey(Level.MEDIUM, CORPUS[0].prompt_id, SEEDS[0])

    def replies(messages):
        if messages[0]["content"].endswith(B_CONTRACT):
            return _reply_canvas(messages)
        return "", "length"

    records, stages = _run_generation(_FakeBackend(replies), key)

    assert "pass2" not in stages
    assert {r.stage for r in records} == {Stage.A_PASS1, Stage.B}
