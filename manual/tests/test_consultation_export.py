import json

import httpx
import pytest

from manual.consultation_export.protocol import (
    APPLICATION_PROMPT,
    EXPORT_SCHEMA,
    PREPARATION_PROMPT,
    application_messages,
    build_payload,
    check_capacity,
    decode_export,
    export_findings,
    local_endpoint,
    render_reference,
)


def reply(turns=None, mapping=None, risks=None):
    return json.dumps(
        {
            "turns": turns
            or [{"id": "t1", "role": "user", "content": "<P_1>: 12 дней"}],
            "mapping": mapping or [{"original": "Ирина", "alias": "<P_1>"}],
            "risks": risks or [],
        },
        ensure_ascii=False,
    )


def test_exact_export_excludes_private_mapping_and_review_notes():
    result = decode_export(reply(risks=["Private review note"]), "stop")
    assert "Ирина" not in result.text
    assert "Private review note" not in result.text
    assert "<P_1>" in result.text
    assert result.mapping == (("Ирина", "<P_1>"),)


@pytest.mark.parametrize(
    ("text", "reason"),
    [("not json", "stop"), (reply(), "length"), ("{}", "stop")],
)
def test_invalid_or_truncated_generation_is_never_a_completed_export(text, reason):
    with pytest.raises(ValueError):
        decode_export(text, reason)


@pytest.mark.parametrize(
    "change",
    [
        {"risks": [1]},
        {"turns": [{"id": "t1", "role": "system", "content": "x"}]},
        {"mapping": [{"original": "", "alias": "<P_1>"}]},
        {"mapping": [{"original": "Ирина", "alias": "Ирина"}]},
        {"turns": []},
    ],
)
def test_protocol_rejects_invalid_shapes(change):
    document = json.loads(reply())
    document.update(change)
    with pytest.raises(ValueError):
        decode_export(json.dumps(document), "stop")


def test_repeated_original_with_conflicting_aliases_is_rejected():
    text = reply(
        mapping=[
            {"original": "Ирина", "alias": "<P_1>"},
            {"original": "Ирина", "alias": "<P_2>"},
        ]
    )
    with pytest.raises(ValueError, match="conflicting"):
        decode_export(text, "stop")


def test_findings_check_order_attribution_and_casefolded_leaks():
    result = decode_export(
        reply(
            turns=[
                {"id": "t2", "role": "assistant", "content": "ИРИНА: 12 дней"},
            ]
        ),
        "stop",
    )
    assert export_findings(result, (("t1", "user"),), ("Ирина",)) == {
        "turn_structure_matches": False,
        "literal_leaks": ["Ирина"],
    }


def test_reference_uses_longest_original_first_and_never_private_only_terms():
    result = decode_export(
        reply(
            mapping=[
                {"original": "Ирина", "alias": "<P_1>"},
                {"original": "Ирина Ланская", "alias": "<P_1>"},
            ]
        ),
        "stop",
    )
    assert render_reference("Ирина Ланская: 12 дней", result) == "<P_1>: 12 дней"
    with pytest.raises(ValueError, match="absent"):
        render_reference("Сергей: 12 дней", result, ("Сергей",))


def test_application_arms_share_originals_and_answer_but_only_b_has_mapping():
    result = decode_export(reply(), "stop")
    source = [{"role": "user", "content": "Ирина: 12 дней"}]
    a = application_messages(source, result, "<P_1>: уточнить", "A")
    b = application_messages(source, result, "<P_1>: уточнить", "B")
    control = application_messages(source, result, "Ирина: уточнить", "control")
    assert a[1] == b[1] == control[1] == source[0]
    assert a[-1]["content"] in b[-1]["content"]
    assert "LOCAL_CORRESPONDENCE" not in a[-1]["content"]
    assert "LOCAL_CORRESPONDENCE" in b[-1]["content"]
    assert "PREPARED_EXPORT" not in control[-1]["content"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://192.168.1.2:11434",
        "http://localhost@evil.test",
        "http://localhost/path",
        "http://localhost?x=1",
        "ftp://127.0.0.1",
    ],
)
def test_nonlocal_or_ambiguous_endpoint_is_rejected_before_network(endpoint):
    with pytest.raises(ValueError):
        local_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434/",
    ],
)
def test_loopback_endpoint_is_accepted(endpoint):
    assert local_endpoint(endpoint) == endpoint.rstrip("/")


def test_budget_refuses_oversize_instead_of_cutting_source():
    messages = [{"role": "user", "content": "я" * 10000}]
    with pytest.raises(ValueError, match="capacity"):
        check_capacity(messages, 8192)
    assert len(messages[0]["content"]) == 10000
    assert check_capacity(messages, 65536) > 10000


def test_payload_is_local_text_only_with_reasoning_off_and_frozen_seed():
    messages = [{"role": "system", "content": PREPARATION_PROMPT}]
    payload = build_payload("gemma4:12b", messages, 17, 65536, EXPORT_SCHEMA)
    assert payload["messages"] == messages
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["options"] == {
        "seed": 17,
        "temperature": 0.2,
        "num_ctx": 65536,
        "num_predict": 8192,
    }
    assert "images" not in payload and "tools" not in payload
    assert "untrusted" in APPLICATION_PROMPT


def test_mocked_http_records_raw_request_without_following_redirects():
    from manual.consultation_export.runner import call_model

    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": reply()},
                "done": True,
                "done_reason": "stop",
            },
        )

    payload = build_payload("m", [{"role": "user", "content": "test"}], 1, 65536)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        record = call_model(client, "http://localhost:11434", payload)
    assert seen == [payload]
    assert record["request"] == payload
    assert record["response"]["done_reason"] == "stop"


def test_http_errors_propagate_without_retry_or_saved_fake_output():
    from manual.consultation_export.runner import call_model

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        call_model(client, "http://localhost:11434", {})


def test_invalid_arm_and_json_value_types_are_explicit_errors():
    from manual.consultation_export.protocol import (
        array_value,
        object_value,
        text_value,
    )

    for function, value in [(array_value, {}), (object_value, []), (text_value, "")]:
        with pytest.raises(ValueError):
            function(value)
    with pytest.raises(ValueError, match="arm"):
        application_messages([], decode_export(reply(), "stop"), "answer", "invalid")


def test_empty_mapping_and_no_replacements_preserve_reference():
    result = decode_export(
        json.dumps(
            {
                "turns": [{"id": "t1", "role": "user", "content": "12 days"}],
                "mapping": [],
                "risks": [],
            }
        ),
        "stop",
    )
    assert render_reference("12 days", result) == "12 days"


def test_duplicate_turns_are_rejected():
    turn = {"id": "t1", "role": "user", "content": "test"}
    with pytest.raises(ValueError, match="duplicate"):
        decode_export(reply(turns=[turn, turn]), "stop")


def test_missing_completion_marker_is_an_environment_protocol_error():
    from manual.consultation_export.runner import call_model

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"message": {"content": "x"}})
            )
        ) as client,
        pytest.raises(ValueError, match="completion"),
    ):
        call_model(client, "http://localhost:11434", {})


def test_frozen_inputs_cannot_change_and_existing_files_cannot_be_overwritten(
    tmp_path, monkeypatch
):
    from manual.consultation_export import runner

    path = tmp_path / "manifest.json"
    runner.write_json(path, {"inputs_sha256": {"file": "old"}})
    monkeypatch.setattr(runner, "fingerprint", lambda: {"file": "new"})
    with pytest.raises(ValueError, match="changed"):
        runner.verified_manifest(tmp_path)
    with pytest.raises(FileExistsError):
        runner.write_json(path, {})


def test_application_requires_completed_review_of_exact_manifest(tmp_path, monkeypatch):
    from manual.consultation_export import runner

    monkeypatch.setattr(runner, "fingerprint", lambda: {})
    runner.write_json(tmp_path / "manifest.json", {"inputs_sha256": {}})
    runner.write_json(
        tmp_path / "preparation-review.json",
        {
            "decision": "proceed",
            "manifest_sha256": "wrong",
        },
    )
    with pytest.raises(ValueError, match="review"):
        runner.run_application(tmp_path)


def test_full_experiment_with_fake_ollama_keeps_phases_separate_and_resumes(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from jarvis.core.config import BackendSettings
    from manual.consultation_export import runner
    from manual.consultation_export.corpus import CASES

    case = CASES[0]
    requests = []
    real_client = httpx.Client

    def handle(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test-only"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:12b"}]})
        payload = json.loads(request.content)
        requests.append(payload)
        if "format" in payload:
            content = reply(
                turns=case.selection(),
                mapping=[{"original": "Ирина Ланская", "alias": "<PERSON_1>"}],
            )
        else:
            content = "Synthetic test answer, not a measured result."
        return httpx.Response(
            200,
            json={
                "message": {"content": content},
                "done": True,
                "done_reason": "stop",
            },
        )

    monkeypatch.setattr(runner, "CASES", (case,))
    monkeypatch.setattr(runner, "SEEDS", (19210,))
    monkeypatch.setattr(
        runner, "load_settings", lambda: SimpleNamespace(backend=BackendSettings())
    )
    monkeypatch.setattr(
        runner.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    out = tmp_path / "isolated-output"
    runner.freeze(out)
    assert not requests  # Version/inventory probes are not chat generations.
    with pytest.raises(ValueError, match="overwrite"):
        runner.freeze(out)
    runner.run_preparation(out)
    runner.run_preparation(out)
    assert len(requests) == 1
    runner.score_preparation(out)
    scores = runner.read_json(out / "preparation-scores.json")
    assert scores["semantic_review"].startswith("pending")
    runner.write_json(
        out / "preparation-review.json",
        {
            "decision": "proceed",
            "manifest_sha256": runner.file_hash(out / "manifest.json"),
        },
    )
    runner.run_application(out)
    runner.run_application(out)
    assert len(requests) == 4
    assert "LOCAL_CORRESPONDENCE" not in requests[2]["messages"][-1]["content"]
    assert "LOCAL_CORRESPONDENCE" in requests[3]["messages"][-1]["content"]
