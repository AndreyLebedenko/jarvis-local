import pytest

from jarvis.core.config import McpModeSettings
from jarvis.dialog.voice_guide import (
    VoiceGuideAccepted,
    VoiceGuideRejected,
    VoiceGuideRejection,
    VoiceGuideRequest,
)
from jarvis.journal.external_canvas import ExternalCanvasCaller, SpeechOrigin
from jarvis.mcp_mode.speak import (
    SpeakError,
    SpeakErrorCode,
    SpeakQueued,
    queued_or_error,
    request_or_error,
)

_LIMITS = McpModeSettings(
    max_canvas_chars=20, max_spoken_text_chars=10, max_guidance_chars=5
)
_CALLER = ExternalCanvasCaller(
    name="claude-code", version="2.1.247", transport_session_id="session-1"
)


def _validate(
    canvas: str, spoken_text: str | None = None, guidance: str | None = None
) -> VoiceGuideRequest | SpeakError:
    return request_or_error(
        canvas, spoken_text, guidance, limits=_LIMITS, caller=_CALLER
    )


def _error_code(result: VoiceGuideRequest | SpeakError) -> SpeakErrorCode:
    assert isinstance(result, SpeakError)
    return result.code


# --- argument validation -----------------------------------------------------


def test_a_canvas_only_call_becomes_a_request_carrying_the_caller():
    assert _validate("An answer.") == VoiceGuideRequest(
        canvas="An answer.", caller=_CALLER
    )


def test_every_argument_reaches_the_request_unchanged():
    result = _validate(" An answer. ", spoken_text=" Read. ", guidance=" Hi ")

    assert result == VoiceGuideRequest(
        canvas=" An answer. ", spoken_text=" Read. ", guidance=" Hi ", caller=_CALLER
    )


@pytest.mark.parametrize("canvas", ["", "  \n\t "])
def test_an_empty_or_blank_canvas_is_empty_canvas(canvas):
    assert _error_code(_validate(canvas)) is SpeakErrorCode.EMPTY_CANVAS


def test_a_canvas_at_the_limit_is_accepted():
    assert isinstance(_validate("x" * 20), VoiceGuideRequest)


def test_a_canvas_over_the_limit_is_canvas_too_long():
    assert _error_code(_validate("x" * 21)) is SpeakErrorCode.CANVAS_TOO_LONG


def test_canvas_length_is_counted_in_characters_not_bytes():
    assert isinstance(_validate("я" * 20), VoiceGuideRequest)


@pytest.mark.parametrize("spoken_text", ["", "   "])
def test_a_provided_but_blank_spoken_text_is_empty_spoken_text(spoken_text):
    result = _validate("An answer.", spoken_text=spoken_text)

    assert _error_code(result) is SpeakErrorCode.EMPTY_SPOKEN_TEXT


def test_a_spoken_text_at_the_limit_is_accepted():
    assert isinstance(_validate("An answer.", spoken_text="x" * 10), VoiceGuideRequest)


def test_a_spoken_text_over_the_limit_is_spoken_text_too_long():
    result = _validate("An answer.", spoken_text="x" * 11)

    assert _error_code(result) is SpeakErrorCode.SPOKEN_TEXT_TOO_LONG


def test_a_guidance_at_the_limit_is_accepted():
    assert isinstance(_validate("An answer.", guidance="x" * 5), VoiceGuideRequest)


def test_a_guidance_over_the_limit_is_guidance_too_long():
    result = _validate("An answer.", guidance="x" * 6)

    assert _error_code(result) is SpeakErrorCode.GUIDANCE_TOO_LONG


@pytest.mark.parametrize("guidance", ["", "  \n          "])
def test_a_blank_guidance_is_treated_as_absent_whatever_its_length(guidance):
    result = _validate("An answer.", guidance=guidance)

    assert result == VoiceGuideRequest(canvas="An answer.", caller=_CALLER)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"canvas": " ", "spoken_text": "", "guidance": "x" * 6}, "empty_canvas"),
        (
            {"canvas": "x" * 21, "spoken_text": "", "guidance": "x" * 6},
            "canvas_too_long",
        ),
        ({"canvas": "ok", "spoken_text": "", "guidance": "x" * 6}, "empty_spoken_text"),
        (
            {"canvas": "ok", "spoken_text": "x" * 11, "guidance": "x" * 6},
            "spoken_text_too_long",
        ),
    ],
)
def test_the_first_failing_check_in_card_order_is_reported(arguments, expected):
    assert _error_code(_validate(**arguments)).value == expected


def test_a_length_error_names_the_limit_but_not_the_rejected_text():
    error = _validate("secret-canvas-text-xx")

    assert isinstance(error, SpeakError)
    assert "20" in error.text
    assert "secret" not in error.text


@pytest.mark.parametrize(
    ("code", "text"),
    [(code, f"{code.value}:") for code in SpeakErrorCode],
)
def test_an_error_text_starts_with_its_machine_readable_code(code, text):
    assert SpeakError(code, "some detail").text.startswith(text)


# --- enqueue result mapping --------------------------------------------------


@pytest.mark.parametrize("origin", list(SpeechOrigin))
def test_an_accepted_request_is_queued_with_its_position_and_origin(origin):
    request = VoiceGuideRequest(canvas="An answer.")

    result = queued_or_error(request, VoiceGuideAccepted(3, origin))

    assert result == SpeakQueued(position=3, speech_origin=origin)


def test_a_queued_payload_without_ignored_guidance_has_no_guidance_flag():
    queued = SpeakQueued(position=2, speech_origin=SpeechOrigin.DERIVATIVE)

    assert queued.payload() == {
        "status": "queued",
        "position": 2,
        "speech_origin": "derivative",
    }


def test_guidance_with_spoken_text_is_queued_with_guidance_ignored():
    request = VoiceGuideRequest(
        canvas="An answer.", spoken_text="Read this.", guidance="Be brief."
    )

    result = queued_or_error(request, VoiceGuideAccepted(1, SpeechOrigin.CALLER))

    assert isinstance(result, SpeakQueued)
    assert result.payload() == {
        "status": "queued",
        "position": 1,
        "speech_origin": "caller",
        "guidance_ignored": True,
    }


def test_guidance_without_spoken_text_is_not_ignored():
    request = VoiceGuideRequest(canvas="An answer.", guidance="Be brief.")

    result = queued_or_error(request, VoiceGuideAccepted(1, SpeechOrigin.DERIVATIVE))

    assert isinstance(result, SpeakQueued)
    assert "guidance_ignored" not in result.payload()


@pytest.mark.parametrize(
    ("rejection", "code"),
    [
        (VoiceGuideRejection.QUEUE_FULL, SpeakErrorCode.QUEUE_FULL),
        (VoiceGuideRejection.CLOSED, SpeakErrorCode.CLOSED),
    ],
)
def test_a_rejected_request_maps_to_its_error_code(rejection, code):
    request = VoiceGuideRequest(canvas="An answer.")

    result = queued_or_error(request, VoiceGuideRejected(rejection))

    assert _error_code(result) is code


def test_every_rejection_the_service_can_return_has_an_error_code():
    request = VoiceGuideRequest(canvas="An answer.")

    for rejection in VoiceGuideRejection:
        result = queued_or_error(request, VoiceGuideRejected(rejection))
        assert _error_code(result).value == rejection.value
