import argparse
import json
import sys

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings
from jarvis.dialog.backend import OllamaBackend
from manual.manual_check_context_token_budget import (
    BASE_TOKEN_OVERHEAD,
    MESSAGE_TOKEN_OVERHEAD,
    TOOL_TOKEN_OVERHEAD,
    LiveMeasurement,
    build_measurement_cases,
    canonical_prompt_material,
    estimate_candidates,
    estimate_conservative_tokens,
    main,
    parse_prompt_eval_count,
    sentencepiece_model_path,
    summarize_candidate,
)


def test_canonical_prompt_material_contains_messages_and_tools_only():
    payload = {
        "model": "model-name",
        "stream": True,
        "think": False,
        "options": {"num_ctx": 65536},
        "messages": [{"role": "user", "content": "Привет"}],
        "tools": [{"type": "function", "function": {"name": "search"}}],
    }

    material = json.loads(canonical_prompt_material(payload))

    assert set(material) == {"messages", "tools"}
    assert material["messages"][0]["content"] == "Привет"
    assert material["tools"][0]["function"]["name"] == "search"


def test_conservative_estimator_uses_utf8_bytes_and_fixed_overheads():
    payload = {
        "messages": [{"role": "user", "content": "я"}],
        "tools": [{"name": "t"}],
    }
    material_bytes = len(canonical_prompt_material(payload).encode("utf-8"))

    estimate = estimate_conservative_tokens(payload)

    assert estimate == (
        (material_bytes + 1) // 2
        + BASE_TOKEN_OVERHEAD
        + MESSAGE_TOKEN_OVERHEAD
        + TOOL_TOKEN_OVERHEAD
    )


def test_estimate_candidates_accepts_an_injected_compatible_tokenizer():
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    estimates = estimate_candidates(payload, compatible_counter=lambda text: len(text))

    assert estimates["compatible_sentencepiece_material"] == len(
        canonical_prompt_material(payload)
    )
    assert estimates["conservative_utf8"] == estimate_conservative_tokens(payload)


def test_sentencepiece_model_path_rejects_an_ollama_model_name():
    with pytest.raises(
        argparse.ArgumentTypeError,
        match=(
            "filesystem path to an existing SentencePiece model file, "
            "not an Ollama model name"
        ),
    ):
        sentencepiece_model_path("gemma4:12b-it-qat")


def test_sentencepiece_model_path_accepts_an_existing_file(tmp_path):
    model_path = tmp_path / "tokenizer.model"
    model_path.touch()

    assert sentencepiece_model_path(str(model_path)) == model_path


def test_cli_rejects_an_ollama_model_name_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["manual_check_context_token_budget", "--tokenizer-model", "gemma4:12b"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "not an Ollama model name" in error
    assert "Traceback" not in error


def test_parse_prompt_eval_count_reads_the_terminal_done_chunk():
    chunks = [
        {"message": {"content": "answer"}, "done": False},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 123},
    ]

    assert parse_prompt_eval_count(chunks) == 123


@pytest.mark.parametrize(
    "chunks",
    (
        [{"message": {"content": "answer"}, "done": False}],
        [{"message": {"content": ""}, "done": True}],
        [{"message": {"content": ""}, "done": True, "prompt_eval_count": True}],
    ),
)
def test_parse_prompt_eval_count_rejects_unusable_results(chunks):
    with pytest.raises(ValueError):
        parse_prompt_eval_count(chunks)


def test_measurement_cases_cover_language_history_and_both_tool_strategies():
    backend = OllamaBackend(EventBus(), BackendSettings())

    cases = build_measurement_cases(
        backend,
        "base prompt\n\n[Jarvis curated memory.md]\nпамять\n"
        "[/Jarvis curated memory.md]",
    )

    by_key = {case.key: case for case in cases}
    assert {
        "russian_short_initial",
        "english_code_initial",
        "system_memory_initial",
        "mixed_long_initial",
        "native_tool_initial",
        "native_tool_followup",
        "prompt_tool_initial",
        "prompt_tool_followup",
    } == set(by_key)
    assert by_key["native_tool_initial"].payload["tools"]
    assert all(case.payload["think"] == "high" for case in cases)
    assert by_key["native_tool_followup"].phase == "followup"
    assert by_key["prompt_tool_initial"].payload.get("tools") is None
    assert by_key["prompt_tool_followup"].phase == "followup"
    assert any(
        message.get("role") == "tool"
        for message in by_key["native_tool_followup"].payload["messages"]
    )
    assert len(by_key["mixed_long_initial"].payload["messages"]) > 4


def test_candidate_summary_reports_underestimation_and_headroom():
    rows = [
        LiveMeasurement("one", 1, 100, {"candidate": 95}),
        LiveMeasurement("two", 1, 100, {"candidate": 112}),
    ]

    summary = summarize_candidate(rows, "candidate")

    assert summary.maximum_underestimation == 5
    assert summary.minimum_headroom == -5
    assert summary.maximum_headroom == 12
