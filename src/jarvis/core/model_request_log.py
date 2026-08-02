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

The line carries modality kinds, their count, the audio duration, and the
budget/retrieval telemetry exposed through prompt_budget - nothing else.
The story's content rule binds this module: no transcript, no clipboard
text, no attachment file names, no media bytes or sizes.
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


def _format_prompt_budget(prompt_budget: dict[str, int | bool | str]) -> str:
    parts = [
        (
            "budget="
            f"{prompt_budget['estimated_prompt_tokens']}/"
            f"{prompt_budget['available_prompt_tokens']}"
        ),
        f"headroom={prompt_budget['headroom_tokens']}",
        "history_truncated="
        f"{str(bool(prompt_budget['truncated_recent_history'])).lower()}",
        f"blank_context={str(bool(prompt_budget['blank_context_cleared'])).lower()}",
    ]
    retrieval_fragment = _format_retrieval_prompt_budget(prompt_budget)
    if retrieval_fragment is not None:
        parts.append(retrieval_fragment)
    return " ".join(parts)


def _format_retrieval_prompt_budget(
    prompt_budget: dict[str, int | bool | str],
) -> str | None:
    if not any(
        key in prompt_budget
        for key in (
            "retrieval_candidate_count",
            "retrieval_accepted_passage_count",
            "retrieval_elapsed_ms",
            "retrieval_full_hybrid",
            "retrieval_lexical_by_timeout",
            "retrieval_lexical_by_unavailable",
            "retrieval_failed_status",
            "retrieval_failed",
        )
    ):
        return None
    failed_status = prompt_budget.get("retrieval_failed_status")
    if isinstance(failed_status, str) and failed_status:
        mode = f"failed({failed_status})"
    elif bool(prompt_budget.get("retrieval_failed")):
        mode = "failed"
    elif bool(prompt_budget.get("retrieval_lexical_by_timeout")):
        mode = "lexical-by-timeout"
    elif bool(prompt_budget.get("retrieval_lexical_by_unavailable")):
        mode = "lexical-by-unavailable"
    elif bool(prompt_budget.get("retrieval_full_hybrid")):
        mode = "full-hybrid"
    else:
        mode = "unknown"
    return (
        "retrieval="
        f"{prompt_budget.get('retrieval_candidate_count', 0)} candidates "
        f"accepted={prompt_budget.get('retrieval_accepted_passage_count', 0)} "
        f"elapsed={prompt_budget.get('retrieval_elapsed_ms', 0)}ms "
        f"mode={mode}"
    )
