"""story-v1.6.4 task 4: the system log's own record of a turn's request.

The panel's localized entry (task 2) and this line are two projections of
one event. These tests pin what the line may say - and, more importantly,
what it may never say.
"""

from jarvis.core.lifecycle import ModelRequestInput, ModelRequestStarted
from jarvis.core.model_request_log import LOG_SOURCE, model_request_log_message


def _event(inputs, audio_duration_seconds=None):
    return ModelRequestStarted(
        timestamp=1700000000.0,
        inputs=inputs,
        audio_duration_seconds=audio_duration_seconds,
    )


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
