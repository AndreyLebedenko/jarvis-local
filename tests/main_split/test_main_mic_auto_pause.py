import asyncio

from _support_from_test_main import (
    _FakeAudioInputForEcho,
    _orchestrator,
)

from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.dialog.backend import (
    ResponseToken,
)

# --- mic auto-pause during speech (task-10, layered on the cooldown above) --


async def test_speaking_auto_pauses_mic_and_resumes_after_cooldown():
    audio_input = _FakeAudioInputForEcho()
    orchestrator, _backend, _sound_cues = _orchestrator(audio_input=audio_input)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_token(ResponseToken(text="Привет"))

    assert audio_input.auto_pause_calls == 1
    assert audio_input.auto_resume_calls == 0

    finish_task = asyncio.create_task(orchestrator.finish_turn(cooldown_seconds=0.05))
    await asyncio.sleep(0)
    assert audio_input.auto_resume_calls == 0  # still within the cooldown

    await finish_task

    assert audio_input.auto_resume_calls == 1


async def test_turn_with_no_speech_does_not_auto_pause_or_resume():
    """A turn that never produces a response token (e.g. an empty
    response) never starts speaking, so there is nothing for the mic
    auto-pause to do either."""
    audio_input = _FakeAudioInputForEcho()
    orchestrator, _backend, _sound_cues = _orchestrator(audio_input=audio_input)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.finish_turn()  # no response token in this turn

    assert audio_input.auto_pause_calls == 0
    assert (
        audio_input.auto_resume_calls == 1
    )  # finish_turn() always resumes - harmless no-op


async def test_error_during_chat_plays_error_cue_and_clears_busy():
    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=failing_chat)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert sound_cues.played == ["thinking", "error"]

    # busy was cleared, so a subsequent utterance is not ignored
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 2
