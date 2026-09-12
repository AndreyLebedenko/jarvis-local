"""Pure tests for the stage-0 damage/inertness probe harness (card v1.9.2-9).

Covers the card's verification list: sampling indices, eligibility
filtering, packet reconstruction shape, dispatch ledger semantics, and
scoring-template generation. No test invokes local or cloud inference.
"""

import json
from pathlib import Path

from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from manual.stage0_probe import (
    REVISION_PROMPT,
    SEED,
    DispatchLedger,
    EligibleTurn,
    SamplingOutcome,
    build_evidence_packet,
    build_revision_messages,
    build_scoring_template,
    eligible_completed_turns,
    even_indices,
    persist_run_artifacts,
    select_sample,
    validate_endpoint,
)


def _event(
    session_id: str,
    role: str,
    text: str,
    *,
    position: int = 0,
    source: str = "text",
    metadata: dict | None = None,
    media: tuple[str, ...] = (),
    transcript: str | None = None,
) -> JournalEventRecord:
    return JournalEventRecord(
        reference=JournalEventRef(session_id, position),
        event=JournalEvent(
            session_id=session_id,
            timestamp="2026-09-12T10:00:00+03:00",
            source=source,
            role=role,
            text=text,
            media=media,
            transcript=transcript,
            metadata=metadata or {},
        ),
    )


def _turn(
    session_id: str = "20260912-100000-a1", answer: str = "answer"
) -> EligibleTurn:
    return EligibleTurn(
        session_id=session_id,
        user_position=0,
        assistant_position=1,
        request_text="question",
        answer_text=answer,
        timestamp="2026-09-12T10:00:01+03:00",
    )


def test_completed_text_turn_is_eligible():
    records = [
        _event("20260912-100000-a1", "user", "q", position=0),
        _event("20260912-100000-a1", "assistant", "a", position=1),
    ]
    pairs = eligible_completed_turns(records)
    assert len(pairs) == 1
    eligible, skipped = pairs[0]
    assert eligible is not None
    assert skipped is None
    assert eligible.request_text == "q"
    assert eligible.answer_text == "a"


def test_voice_turn_transcript_becomes_request_text():
    records = [
        _event(
            "20260912-100000-a1",
            "user",
            "",
            source="voice",
            transcript="spoken question",
        ),
        _event("20260912-100000-a1", "assistant", "a"),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0].request_text == "spoken question"


def test_voice_turn_without_transcript_is_ineligible():
    records = [
        _event("20260912-100000-a1", "user", "", source="voice"),
        _event("20260912-100000-a1", "assistant", "a"),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0] is None
    assert pairs[0][1].reason == "voice request without a usable transcript"


def test_aborted_outcome_marks_turn_ineligible():
    records = [
        _event("20260912-100000-a1", "user", "q"),
        _event(
            "20260912-100000-a1",
            "assistant",
            "",
            metadata={"outcome": "interrupted"},
        ),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0] is None
    assert pairs[0][1].reason == "aborted outcome recorded on the assistant event"


def test_media_on_either_event_is_ineligible():
    records = [
        _event("20260912-100000-a1", "user", "q", media=("shot.png",)),
        _event("20260912-100000-a1", "assistant", "a"),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0] is None
    assert pairs[0][1].reason == "media attached to the user or assistant event"

    records = [
        _event("20260912-100000-a1", "user", "q"),
        _event("20260912-100000-a1", "assistant", "a", media=("clip.wav",)),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0] is None


def test_unpaired_assistant_event_is_ineligible():
    records = [_event("20260912-100000-a1", "assistant", "a")]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0] is None
    assert pairs[0][1].reason == "no adjacent user request in the same session"


def test_select_sample_takes_last_size_from_chronological_pool():
    pool = [_turn(f"20260912-1000{i:02d}-a1") for i in range(40)]
    sessions = [("20260912-100000-a1", [(turn, None) for turn in pool])]
    selected, ineligible = select_sample(sessions, size=30)
    assert ineligible == []
    assert len(selected) == 30
    assert selected[0].session_id == "20260912-100010-a1"
    assert selected[-1].session_id == "20260912-100039-a1"


def test_select_sample_reports_all_ineligible_without_silent_drop():
    pool = [_turn() for _ in range(5)]
    ineligible_turns = [_turn(f"20260912-1001{i:02d}-b1") for i in range(3)]
    skipped = [(None, item) for item in ineligible_turns]
    sessions = [("20260912-100000-a1", [(turn, None) for turn in pool] + skipped)]
    selected, ineligible = select_sample(sessions, size=30)
    assert len(selected) == 5
    assert len(ineligible) == 3


def test_even_indices_match_floor_rule():
    assert even_indices(6, size=30) == [0, 1, 2, 3, 4, 5]
    assert even_indices(0) == []
    indices = even_indices(300, size=30)
    assert len(indices) == 30
    assert indices[0] == int(0.5 * 300 // 30)
    assert indices == sorted(set(indices))


def test_evidence_packet_is_exactly_the_request():
    turn = _turn()
    assert build_evidence_packet(turn) == "question"


def test_revision_messages_carry_labeled_draft_and_frozen_prompt():
    messages = build_revision_messages(_turn(answer="draft answer"))
    assert len(messages) == 1
    content = messages[0]["content"]
    assert "question" in content
    assert "draft answer" in content
    assert REVISION_PROMPT in content
    assert "Черновик ответа (D)" in content


def test_revision_prompt_permits_retaining_the_answer():
    assert "сохранить текст без изменений - допустимый исход" in REVISION_PROMPT


def test_endpoint_guard_rejects_public_host_and_cloud_model():
    validate_endpoint("http://localhost:11434", "gemma4:12b")
    validate_endpoint("http://127.0.0.1:11434", "gemma4:12b")
    try:
        validate_endpoint("http://example.com:11434", "gemma4:12b")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("public endpoint accepted")
    try:
        validate_endpoint("http://localhost:11434", "glm-5.3-flash:cloud")
    except ValueError as exc:
        assert "cloud" in str(exc)
    else:
        raise AssertionError("cloud model accepted")


def test_ledger_resume_skips_terminal_and_flags_unresolved(tmp_path: Path):
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    ledger.record_dispatched("t1")
    ledger.record_completed("t2", "artifact.json")
    ledger.record_failed("t3", "boom")
    ledger.record_interrupted("t4")
    reopened = DispatchLedger(tmp_path / "ledger.jsonl")
    pending = reopened.pending_turn_ids(["t1", "t2", "t3", "t4", "t5"])
    assert pending == ["t1", "t5"]
    assert reopened.dispatched_without_terminal_status() == ["t1"]
    reopened.record_completed("t1", "artifact.json")
    reopened.record_completed("t5", "artifact.json")
    final = DispatchLedger(tmp_path / "ledger.jsonl")
    assert final.pending_turn_ids(["t1", "t2", "t3", "t4", "t5"]) == []
    assert final.dispatched_without_terminal_status() == []


def test_ledger_records_are_persisted_jsonl(tmp_path: Path):
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    ledger.record_dispatched("t1")
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["status"] == "dispatched"
    assert len(lines) == 1


def test_scoring_template_has_pre_mark_column_and_excerpts():
    rows = build_scoring_template([_turn()])
    assert len(rows) == 1
    assert rows[0].turn_id == "20260912-100000-a1#1"


def test_persist_run_artifacts_writes_local_records(tmp_path: Path):
    turn = _turn()
    persist_run_artifacts(
        tmp_path,
        turns=[turn],
        ineligible=[],
        scoring_rows=build_scoring_template([turn]),
        selected_count=1,
    )
    selection = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert selection["seed"] == SEED
    assert selection["selected"] == 1
    assert selection["protocol_card"].endswith("stage0-damage-and-inertness-probe.md")
    packets = (tmp_path / "packets.jsonl").read_text(encoding="utf-8").splitlines()
    packet = json.loads(packets[0])
    assert packet["request"] == "question"
    assert packet["draft"] == "answer"
    sheet = (tmp_path / "scoring_sheet.csv").read_text(encoding="utf-8-sig")
    assert "turn_id,pre_mark" in sheet


def test_sampling_outcome_enum_exists_for_sheet_reporting():
    assert SamplingOutcome.SAMPLED.value == "sampled"
    assert SamplingOutcome.INELIGIBLE.value == "ineligible"
