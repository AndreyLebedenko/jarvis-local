"""The system log's record of what a turn sent to the model
(story-v1.6.4 task 4).

This is deliberately not part of system_log.py. publish_system_event()
exists to make one occurrence reach both the file log and the console's
events panel, and it guarantees they can never disagree about whether an
event fired. A model request is the one case where that guarantee is the
wrong shape: task-v1.6.4-2 already gives the panel a typed, localized
entry for it, so routing the same fact through publish_system_event()
would render every turn twice - once localized, once as a raw English
diagnostic. The panel half and the file half are produced separately and
on purpose.

The line carries modality kinds, their count, and the audio duration -
nothing else. The story's content rule binds this module: no transcript,
no clipboard text, no attachment file names, no media bytes or sizes.
"""

from jarvis.core.lifecycle import ModelRequestStarted

LOG_SOURCE = "LLM"


def model_request_log_message(event: ModelRequestStarted) -> str:
    """Render one system-log line describing a turn's request modalities."""
    kinds = ",".join(input_kind.value for input_kind in event.inputs) or "none"
    parts = [f"Model request: inputs={kinds}", f"count={len(event.inputs)}"]
    if event.audio_duration_seconds is not None:
        parts.append(f"audio_duration={event.audio_duration_seconds:.1f}s")
    if event.prompt_budget is not None:
        parts.append(_format_prompt_budget(event.prompt_budget))
    return " ".join(parts)


def _format_prompt_budget(prompt_budget: dict[str, int | bool]) -> str:
    return " ".join(
        [
            (
                "budget="
                f"{prompt_budget['estimated_prompt_tokens']}/"
                f"{prompt_budget['available_prompt_tokens']}"
            ),
            f"headroom={prompt_budget['headroom_tokens']}",
            "history_truncated="
            f"{str(bool(prompt_budget['truncated_recent_history'])).lower()}",
            "blank_context="
            f"{str(bool(prompt_budget['blank_context_cleared'])).lower()}",
        ]
    )
