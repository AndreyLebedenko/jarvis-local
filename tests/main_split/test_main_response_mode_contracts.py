from _support_from_test_main import _orchestrator

from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    PromptSettings,
)
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
# selects no field here at all, matching mode 1 - its own contract
# (response_text_voice) belongs to the second pass instead (story-v1.9.0
# task 3, see run_derivative_pass()'s own tests below, and app.py's
# _RESPONSE_MODE_PROMPT_FIELD_BY_MODE).


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
    prompts = PromptSettings(response_voice="speak plainly")
    orchestrator, backend, _sound_cues = _orchestrator(
        response_mode=response_mode, reasoning_prompt_settings=prompts
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
    response_text_voice field is reserved for the second pass, dispatched
    separately from _compose_response_mode_contract() entirely (see the
    mode-3 second-pass tests below)."""
    response_mode = ResponseModeState(
        bus=EventBus(), initial_mode=ResponseMode.TEXT_VOICE
    )
    prompts = PromptSettings(
        response_voice="voice contract", response_text_voice="derivative contract"
    )
    orchestrator, backend, _sound_cues = _orchestrator(
        response_mode=response_mode, reasoning_prompt_settings=prompts
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
    prompts = PromptSettings(
        reasoning_low="reason briefly", response_voice="speak plainly"
    )
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        response_mode=response_mode,
        reasoning_prompt_settings=prompts,
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
