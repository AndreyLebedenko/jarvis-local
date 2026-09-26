from _support_from_test_main import _generation_with, _orchestrator

from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import ResponseSettings
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeState,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelState,
)

# --- response mode (story-v1.9.0, task 1) -----------------------------------
#
# Orchestrator samples ResponseModeState.mode at turn start - same seam and
# same "next accepted turn only" rule as ReasoningLevelState above. Mode 1
# (text) appends nothing, so the first pass stays byte-identical to today.
# Mode 2 (voice) selects the self-contained voice contract on its single
# pass. Mode 3 (text_voice)'s first pass is the canonical rich text, so it
# appends nothing here at all, matching mode 1 - its own contract is the
# spoken_derivative generation profile's prompt, used by the second pass
# instead (story-v1.9.0 task 3, see run_derivative_pass()'s own tests).


async def test_text_mode_turn_does_not_append_any_response_mode_contract():
    response_mode = ResponseModeState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(response_mode=response_mode)
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {"role": "system", "content": "base prompt"}


async def test_voice_mode_appends_the_voice_contract():
    response_mode = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.VOICE)
    orchestrator, backend, _sound_cues = _orchestrator(
        response_mode=response_mode,
        response_settings=ResponseSettings(voice_contract="speak plainly"),
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nspeak plainly",
    }


async def test_text_voice_modes_first_pass_uses_the_base_prompt_only():
    """Mode 3's first pass is the canonical rich text (story-v1.9.0 task 3):
    it composes exactly like mode 1, never the voice contract - the
    spoken_derivative profile's prompt is reserved for the second pass,
    dispatched separately from _compose_response_mode_contract() entirely
    (see the mode-3 second-pass tests)."""
    response_mode = ResponseModeState(
        bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE
    )
    orchestrator, backend, _sound_cues = _orchestrator(
        response_mode=response_mode,
        generation_settings=_generation_with(
            {"spoken_derivative": "derivative contract"}
        ),
        response_settings=ResponseSettings(voice_contract="voice contract"),
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {"role": "system", "content": "base prompt"}


async def test_reasoning_section_and_response_mode_contract_compose_together():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    await thinking_mode.set_level(ReasoningLevel.LOW, source="TEST")
    response_mode = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.VOICE)
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        response_mode=response_mode,
        generation_settings=_generation_with({"dialog.low": "reason briefly"}),
        response_settings=ResponseSettings(voice_contract="speak plainly"),
    )
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nreason briefly\n\nspeak plainly",
    }


async def test_start_turn_with_no_response_mode_defaults_to_text():
    """Orchestrator can be constructed without a response_mode (e.g. older
    tests/callers) - must not crash, and must behave as text mode (append
    nothing)."""
    orchestrator, backend, _sound_cues = _orchestrator()
    orchestrator._system_prompt = "base prompt"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {"role": "system", "content": "base prompt"}
