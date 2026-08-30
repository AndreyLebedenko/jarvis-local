import asyncio

import pytest

from jarvis.app import (
    SYSTEM_PROMPT,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    PromptSettings,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelState,
)
from tests.main_split._support_from_test_main import _complete_event, _orchestrator

# --- graded reasoning level (story-v1.3.1 task 2) ---------------------------
#
# Orchestrator samples ReasoningLevelState.level at turn start (in
# _start_turn(), synchronously with no `await` before the value reaches
# backend.chat()) and passes it through, per the story's decision that a
# hotkey/UI change applies to the next accepted turn, not any request
# already in flight.


async def test_start_turn_passes_off_by_default():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(thinking_mode=thinking_mode)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.OFF]


async def test_start_turn_passes_the_sampled_level_after_a_cycle():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(thinking_mode=thinking_mode)

    await thinking_mode.cycle_level(source="HOTKEY")  # off -> low
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.LOW]


@pytest.mark.parametrize(
    ("level", "field_name", "section"),
    [
        (ReasoningLevel.LOW, "reasoning_low", "reason briefly"),
        (ReasoningLevel.MEDIUM, "reasoning_medium", "compare alternatives"),
        (ReasoningLevel.HIGH, "reasoning_high", "verify conclusions"),
    ],
)
async def test_reasoning_turn_appends_the_active_section_after_memory_material(
    level, field_name, section
):
    thinking_mode = ReasoningLevelState(bus=EventBus())
    await thinking_mode.set_level(level, source="TEST")
    prompts = PromptSettings(**{field_name: section})
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt\n\nmemory material"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": f"base prompt\n\nmemory material\n\n{section}",
    }
    assert backend.reasoning_level_calls == [level]


async def test_off_turn_does_not_append_any_reasoning_prompt_section():
    prompts = PromptSettings(
        reasoning_low="low section",
        reasoning_medium="medium section",
        reasoning_high="high section",
    )
    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=prompts,
    )
    orchestrator._system_prompt = "base prompt\n\nmemory material"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nmemory material",
    }


async def test_level_with_no_configured_section_uses_base_and_memory_only():
    thinking_mode = ReasoningLevelState(bus=EventBus())
    await thinking_mode.set_level(ReasoningLevel.MEDIUM, source="TEST")
    orchestrator, backend, _sound_cues = _orchestrator(
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=PromptSettings(reasoning_low="low section"),
    )
    orchestrator._system_prompt = "base prompt\n\nmemory material"

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.calls[-1][0][0] == {
        "role": "system",
        "content": "base prompt\n\nmemory material",
    }
    assert backend.reasoning_level_calls == [ReasoningLevel.MEDIUM]


async def test_level_change_while_busy_does_not_affect_the_in_flight_turn():
    """Regression guard for the story's explicit boundary: changing a live
    Ollama stream mid-response is out of scope. A level change that lands
    while a turn's backend.chat() call is already in flight must not
    retroactively change what was already passed for that call - only the
    next accepted turn should see the new value."""
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    thinking_mode = ReasoningLevelState(bus=EventBus())
    orchestrator, backend, _sound_cues = _orchestrator(
        chat_impl=slow_chat,
        thinking_mode=thinking_mode,
        reasoning_prompt_settings=PromptSettings(reasoning_low="low section"),
    )

    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and sample level=off

    await thinking_mode.cycle_level(
        source="HOTKEY"
    )  # off -> low, while the first call is in flight

    still_busy.set()
    await first

    assert backend.reasoning_level_calls == [
        ReasoningLevel.OFF
    ]  # the in-flight call was unaffected
    assert backend.calls[0][0][0]["content"] == SYSTEM_PROMPT

    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [
        ReasoningLevel.OFF,
        ReasoningLevel.LOW,
    ]  # next accepted turn sees the new value
    assert backend.calls[1][0][0]["content"] == f"{SYSTEM_PROMPT}\n\nlow section"


async def test_start_turn_with_no_thinking_mode_defaults_to_off():
    """Orchestrator can be constructed without a thinking_mode (e.g. older
    tests/callers) - must not crash, and must behave as if reasoning is
    permanently off."""
    orchestrator, backend, _sound_cues = _orchestrator()

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    assert backend.reasoning_level_calls == [ReasoningLevel.OFF]
