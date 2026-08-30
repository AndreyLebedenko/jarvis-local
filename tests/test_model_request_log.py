"""story-v1.6.4 task 4: the system log's own record of a turn's request.

The panel's localized entry (task 2) and this line are two projections of
one event. These tests pin what the line may say - and, more importantly,
what it may never say.
"""

from jarvis.core.lifecycle import (
    ModelRequestInput,
    ModelRequestPassKind,
    ModelRequestStarted,
)
from jarvis.core.model_request_log import LOG_SOURCE, model_request_log_message


def _event(
    inputs,
    audio_duration_seconds=None,
    prompt_budget=None,
    pass_kind=ModelRequestPassKind.PRIMARY,
):
    return ModelRequestStarted(
        timestamp=1700000000.0,
        inputs=inputs,
        audio_duration_seconds=audio_duration_seconds,
        prompt_budget=prompt_budget,
        pass_kind=pass_kind,
    )


def test_a_primary_pass_carries_no_pass_tag():
    message = model_request_log_message(_event((ModelRequestInput.TEXT_INPUT,)))

    assert "pass=" not in message


def test_mode_3s_derivative_pass_is_tagged_so_it_reads_as_a_sub_pass():
    """story-v1.9.0 task 3: a real inference call for the derivative,
    honestly logged like any other request - but tagged so it is not
    mistaken for a second turn."""
    message = model_request_log_message(
        _event((), pass_kind=ModelRequestPassKind.DERIVATIVE)
    )

    assert "pass=derivative" in message


def test_voice_with_screenshot_names_both_modalities_and_the_duration():
    message = model_request_log_message(
        _event(
            (ModelRequestInput.AUDIO, ModelRequestInput.SCREENSHOT),
            audio_duration_seconds=4.25,
        )
    )

    assert message == (
        "Model request: inputs=audio,screenshot count=2 audio_duration=4.2s"
    )


def test_a_request_without_audio_omits_the_duration_rather_than_faking_one():
    message = model_request_log_message(_event((ModelRequestInput.CLIPBOARD,)))

    assert message == "Model request: inputs=clipboard count=1"
    assert "duration" not in message


def test_an_empty_input_tuple_still_produces_a_readable_line():
    """A turn with no modalities should read as a fact, not as a formatting
    accident that a reader has to decode from a trailing separator."""
    message = model_request_log_message(_event(()))

    assert message == "Model request: inputs=none count=0"


def test_every_modality_renders_under_its_contract_value():
    """The log line's vocabulary is the enum's own values, so a new
    modality cannot reach the file log as an opaque repr."""
    for input_kind in ModelRequestInput:
        message = model_request_log_message(_event((input_kind,)))

        assert f"inputs={input_kind.value}" in message
        assert "ModelRequestInput" not in message


def test_the_line_is_tagged_with_the_same_source_shape_as_system_events():
    assert LOG_SOURCE == "LLM"


def test_prompt_budget_details_are_appended_when_present():
    message = model_request_log_message(
        _event(
            (ModelRequestInput.AUDIO,),
            audio_duration_seconds=1.5,
            prompt_budget={
                "prompt_capacity_tokens": 49152,
                "available_prompt_tokens": 24576,
                "tool_result_reserve_tokens": 8192,
                "reasoning_generation_reserve_tokens": 16384,
                "estimator_safety_margin_tokens": 1024,
                "estimated_prompt_tokens": 24000,
                "headroom_tokens": 576,
                "base_prompt_tokens": 1200,
                "recent_history_tokens": 20000,
                "retrieval_tokens": 800,
                "recent_history_message_count": 8,
                "retrieval_message_count": 1,
                "truncated_recent_history": True,
                "blank_context_cleared": False,
                "retrieval_candidate_count": 3,
                "retrieval_accepted_passage_count": 2,
                "retrieval_elapsed_ms": 84,
                "retrieval_full_hybrid": False,
                "retrieval_lexical_by_timeout": True,
                "retrieval_lexical_by_unavailable": False,
                "retrieval_failed": False,
            },
        )
    )

    assert "budget=24000/24576" in message
    assert "headroom=576" in message
    assert "history_truncated=true" in message
    assert "blank_context=false" in message
    assert (
        "retrieval=3 candidates accepted=2 elapsed=84ms mode=lexical-by-timeout"
        in message
    )


def test_failed_retrieval_details_are_rendered_when_present():
    message = model_request_log_message(
        _event(
            (ModelRequestInput.AUDIO,),
            prompt_budget={
                "prompt_capacity_tokens": 49152,
                "available_prompt_tokens": 24576,
                "tool_result_reserve_tokens": 8192,
                "reasoning_generation_reserve_tokens": 16384,
                "estimator_safety_margin_tokens": 1024,
                "estimated_prompt_tokens": 24000,
                "headroom_tokens": 576,
                "base_prompt_tokens": 1200,
                "recent_history_tokens": 20000,
                "retrieval_tokens": 800,
                "recent_history_message_count": 8,
                "retrieval_message_count": 1,
                "truncated_recent_history": True,
                "blank_context_cleared": False,
                "retrieval_candidate_count": 0,
                "retrieval_accepted_passage_count": 0,
                "retrieval_elapsed_ms": 3,
                "retrieval_failed": True,
                "retrieval_failed_status": "hydration_failed",
            },
        )
    )

    assert "mode=failed(hydration_failed)" in message
