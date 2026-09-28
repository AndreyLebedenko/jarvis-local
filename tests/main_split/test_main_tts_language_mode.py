from _support_from_test_main import (
    _complete_event,
    _generation_with,
    _orchestrator,
    _RequestRecorder,
)

from jarvis.audio.input import UtteranceChunk
from jarvis.audio.speech_language import TtsLanguageMode
from jarvis.core.bus import EventBus
from jarvis.core.config import ResponseSettings
from jarvis.core.lifecycle import CharsetSpeechRouting, SingleLanguageSpeech
from jarvis.dialog.backend import ResponseToken
from jarvis.dialog.response_mode import ResponseMode, ResponseModeState
from jarvis.inputs.attachments import (
    AttachmentClass,
    AttachmentPlan,
    AttachmentPlanItem,
    PlannedTextPart,
)
from jarvis.inputs.clipboard import ClipboardSubmitted

# [tts].language_mode: the directive telling the model which single language
# its spoken text is voiced in goes only where that text is written for
# speech - the voice-mode turn and mode 3's spoken-derivative pass. The
# per-pass TTS routing directive travels on every ModelRequestStarted.

_RESPONSE_SETTINGS = ResponseSettings(
    voice_contract="voice contract",
    speech_language_ru="speak russian",
    speech_language_en="speak english",
    speech_language_request="speak the question's language",
)


def _language_orchestrator(response_mode, tts_language_mode, chat_impl=None):
    bus = EventBus()
    requests = _RequestRecorder(bus)
    orchestrator, backend, _sound_cues = _orchestrator(
        chat_impl=chat_impl,
        bus=bus,
        response_mode=ResponseModeState(bus=bus, initial_mode=response_mode),
        generation_settings=_generation_with(
            {"spoken_derivative": "derivative contract"}
        ),
        response_settings=_RESPONSE_SETTINGS,
        tts_language_mode=tts_language_mode,
    )
    orchestrator._system_prompt = "base prompt"
    return orchestrator, backend, requests


def _system_prompt(backend, call_index=-1):
    return backend.calls[call_index][0][0]["content"]


async def _speak(orchestrator):
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )


async def test_dynamic_mode_changes_neither_the_prompt_nor_the_routing():
    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.DYNAMIC
    )

    await _speak(orchestrator)

    assert _system_prompt(backend) == "base prompt\n\nvoice contract"
    assert requests.events[-1].speech_language == CharsetSpeechRouting()


async def test_voice_mode_with_a_fixed_language_tells_the_model_that_language():
    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.RUSSIAN
    )

    await _speak(orchestrator)

    assert _system_prompt(backend) == "base prompt\n\nvoice contract\n\nspeak russian"
    assert requests.events[-1].speech_language == SingleLanguageSpeech("ru")


async def test_voice_request_in_request_mode_leaves_the_language_to_the_answer():
    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.REQUEST
    )

    await _speak(orchestrator)

    assert _system_prompt(backend) == (
        "base prompt\n\nvoice contract\n\nspeak the question's language"
    )
    assert requests.events[-1].speech_language == SingleLanguageSpeech(None)


async def test_typed_request_in_request_mode_passes_its_language_explicitly():
    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.REQUEST
    )

    await orchestrator.submit_text_input("What is a WebSocket?")

    assert _system_prompt(backend) == "base prompt\n\nvoice contract\n\nspeak english"
    assert requests.events[-1].speech_language == SingleLanguageSpeech("en")


async def test_a_typed_russian_request_with_english_terms_counts_as_russian():
    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.REQUEST
    )

    await orchestrator.submit_text_input("Что такое WebSocket?")

    assert _system_prompt(backend) == "base prompt\n\nvoice contract\n\nspeak russian"
    assert requests.events[-1].speech_language == SingleLanguageSpeech("ru")


async def test_clipboard_request_in_request_mode_passes_its_language_explicitly():
    orchestrator, _backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.REQUEST
    )

    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="Переведи это", truncated=False, is_empty=False)
    )

    assert requests.events[-1].speech_language == SingleLanguageSpeech("ru")


async def test_attachment_request_language_follows_the_typed_text_not_the_file():
    orchestrator, _backend, requests = _language_orchestrator(
        ResponseMode.VOICE, TtsLanguageMode.REQUEST
    )
    russian_file = AttachmentPlanItem(
        filename="notes.txt",
        attachment_class=AttachmentClass.TEXT,
        accepted=True,
        text=PlannedTextPart(content="Длинный русский документ.", truncated=False),
    )

    await orchestrator.on_attachment_submission(
        "Summarize this", AttachmentPlan(items=(russian_file,))
    )

    assert requests.events[-1].speech_language == SingleLanguageSpeech("en")


async def test_text_mode_ignores_the_language_mode_entirely():
    """Owner decision: text mode's answer is written for the screen, not for
    one voice, so it keeps the per-language-run routing."""
    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.TEXT, TtsLanguageMode.ENGLISH
    )

    await _speak(orchestrator)

    assert _system_prompt(backend) == "base prompt"
    assert requests.events[-1].speech_language == CharsetSpeechRouting()


async def _run_text_voice_turn(tts_language_mode, canvas):
    async def chat_impl() -> None:
        if len(backend.calls) == 1:
            await orchestrator.on_response_token(ResponseToken(text=canvas))

    orchestrator, backend, requests = _language_orchestrator(
        ResponseMode.TEXT_VOICE, tts_language_mode, chat_impl=chat_impl
    )
    await _speak(orchestrator)
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.run_derivative_pass()
    return backend, requests


async def test_text_voice_first_pass_gets_no_language_directive():
    backend, _requests = await _run_text_voice_turn(
        TtsLanguageMode.ENGLISH, "Ответ на экране."
    )

    assert _system_prompt(backend, 0) == "base prompt"


async def test_text_voice_second_pass_is_told_the_fixed_language():
    backend, requests = await _run_text_voice_turn(
        TtsLanguageMode.ENGLISH, "Ответ на экране."
    )

    assert _system_prompt(backend, 1) == "derivative contract\n\nspeak english"
    assert requests.events[1].speech_language == SingleLanguageSpeech("en")


async def test_text_voice_second_pass_in_request_mode_follows_the_canvas_language():
    backend, requests = await _run_text_voice_turn(
        TtsLanguageMode.REQUEST, "Ответ: используйте git rebase."
    )

    assert _system_prompt(backend, 1) == "derivative contract\n\nspeak russian"
    assert requests.events[1].speech_language == SingleLanguageSpeech("ru")


async def test_text_voice_second_pass_in_dynamic_mode_is_unchanged():
    backend, requests = await _run_text_voice_turn(
        TtsLanguageMode.DYNAMIC, "Ответ на экране."
    )

    assert _system_prompt(backend, 1) == "derivative contract"
    assert requests.events[1].speech_language == CharsetSpeechRouting()
