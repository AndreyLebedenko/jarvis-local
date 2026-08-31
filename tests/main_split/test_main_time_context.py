import base64

from _support_from_test_main import _complete_event, _orchestrator

from jarvis.app import (
    VOICE_PLACEHOLDER_TEXT,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.dialog.backend import (
    ResponseToken,
)
from jarvis.dialog.time_context import format_time_context

# --- current-turn time context (v1.3.2) -------------------------------------
#
# format_time_context() is injected as an extra system message immediately
# before the user turn - closest to the query, not buried ahead of a
# potentially long history block - and must never reach
# ConversationHistory.add() (mirrors the current-turn-only media_b64
# pattern applied to time instead of images; see PROJECT.md's v1.3.2 note).


async def test_start_turn_appends_time_context_system_message_before_user_turn():
    orchestrator, backend, _sound_cues = _orchestrator(clock=lambda: 1700000123.0)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )

    [(messages, _images)] = backend.calls
    assert messages[-2] == {
        "role": "system",
        "content": format_time_context(1700000123.0),
    }
    assert messages[-1] == {
        "role": "user",
        "content": VOICE_PLACEHOLDER_TEXT,
        "images": [base64.b64encode(b"a").decode()],
    }


async def test_time_context_message_is_not_recorded_in_history():
    orchestrator, _backend, _sound_cues = _orchestrator(clock=lambda: 1700000123.0)

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    time_context_text = format_time_context(1700000123.0)
    recorded_texts = [m["content"] for m in orchestrator._history.as_messages()]
    assert time_context_text not in recorded_texts
    assert all(m.get("role") != "system" for m in orchestrator._history.as_messages())
