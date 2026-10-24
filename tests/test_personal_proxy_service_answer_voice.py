import asyncio

import pytest
from _confirmation_fakes import FakeMicrophone, FakeSpeaker

from jarvis.personal_proxy.answer.answer_voice import AnswerVoice
from jarvis.personal_proxy.confirmation.confirmation_ports import SpeechResult
from jarvis.personal_proxy.reporting.service_blocks import NoticeKind


def _voice(log, *, speaker=None, microphone=None, language="en", limit=0.05):
    speaker = speaker or FakeSpeaker(log)
    microphone = microphone or FakeMicrophone(log)
    voice = AnswerVoice(
        speaker=speaker,
        microphone=microphone,
        language=lambda: language,
        resume_limit_seconds=limit,
    )
    return voice, speaker, microphone


async def test_a_sentence_is_spoken_in_the_current_language_between_pause_and_resume():
    log = []
    voice, speaker, _ = _voice(log, language="ru")

    async with voice.session() as session:
        await session.say("Привет.")

    assert speaker.spoken == [("Привет.", "ru")]
    assert log == ["pause", "speak", "resume"]


async def test_the_microphone_is_paused_once_for_the_whole_answer():
    log = []
    voice, speaker, _ = _voice(log)

    async with voice.session() as session:
        await session.say("One.")
        await session.say("Two.")
        await session.say("Three.")

    assert log == ["pause", "speak", "speak", "speak", "resume"]
    assert [text for text, _ in speaker.spoken] == ["One.", "Two.", "Three."]


async def test_control_tags_are_removed_before_speaking():
    log = []
    voice, speaker, _ = _voice(log)

    async with voice.session() as session:
        await session.say('<speak>Hi <lang xml:lang="ru">там</lang></speak>')

    assert speaker.spoken == [("Hi там", "en")]


async def test_a_sentence_that_is_only_tags_or_blank_is_not_spoken_and_does_not_pause():
    log = []
    voice, speaker, _ = _voice(log)

    async with voice.session() as session:
        await session.say("<speak></speak>")
        await session.say("   ")

    assert speaker.spoken == []
    assert log == []


async def test_a_muted_tts_stops_speaking_and_gives_the_microphone_back_at_once():
    log = []
    speaker = FakeSpeaker(log, result=SpeechResult.DISABLED)
    voice, _, _ = _voice(log, speaker=speaker)

    async with voice.session() as session:
        await session.say("One.")
        assert log == ["pause", "speak", "resume"]
        await session.say("Two.")

    assert log == ["pause", "speak", "resume"]
    assert session.take_problems() == []


async def test_a_speaker_failure_degrades_to_text_and_is_reported_once():
    log = []
    speaker = FakeSpeaker(log, error=RuntimeError("tts broke"))
    voice, _, _ = _voice(log, speaker=speaker)

    async with voice.session() as session:
        await session.say("One.")
        await session.say("Two.")

    assert log == ["pause", "speak", "resume"]
    assert session.take_problems() == [NoticeKind.SPEECH_FAILED]
    assert session.take_problems() == []


async def test_a_pause_failure_speaks_nothing_and_still_tries_to_resume():
    log = []
    microphone = FakeMicrophone(log, pause_error=RuntimeError("mic broke"))
    voice, speaker, _ = _voice(log, microphone=microphone)

    async with voice.session() as session:
        await session.say("One.")

    assert speaker.spoken == []
    assert log == ["pause", "resume"]
    assert session.take_problems() == [NoticeKind.SPEECH_FAILED]


async def test_a_resume_failure_is_reported_not_raised():
    log = []
    microphone = FakeMicrophone(log, resume_error=RuntimeError("mic broke"))
    voice, _, _ = _voice(log, microphone=microphone)

    async with voice.session() as session:
        await session.say("One.")

    assert session.take_problems() == [NoticeKind.MICROPHONE_FAILED]


async def test_a_hung_resume_is_given_up_after_the_limit():
    log = []
    microphone = FakeMicrophone(log, resume_hold=asyncio.Event())
    voice, _, _ = _voice(log, microphone=microphone, limit=0.01)

    async with voice.session() as session:
        await session.say("One.")

    assert session.take_problems() == [NoticeKind.MICROPHONE_FAILED]


async def test_cancellation_stops_the_speaker_resumes_the_microphone_and_propagates():
    log = []
    speaker = FakeSpeaker(log, hold=True)
    voice, _, _ = _voice(log, speaker=speaker)

    async def speaking():
        async with voice.session() as session:
            await session.say("One.")

    task = asyncio.ensure_future(speaking())
    while "speak" not in log:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert log == ["pause", "speak", "stop", "resume"]


async def test_an_exception_inside_the_session_still_resumes_the_microphone():
    log = []
    voice, _, _ = _voice(log)

    with pytest.raises(ValueError):
        async with voice.session() as session:
            await session.say("One.")
            raise ValueError("x")

    assert log == ["pause", "speak", "resume"]


async def test_stop_stops_the_speaker_and_never_raises():
    log = []
    voice, speaker, _ = _voice(log)

    voice.stop()
    assert log == ["stop"]

    def broken():
        raise RuntimeError("x")

    speaker.stop = broken
    voice.stop()
