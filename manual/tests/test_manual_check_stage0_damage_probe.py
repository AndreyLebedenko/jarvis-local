"""Pure tests for the stage-0 damage/inertness probe harness (card v1.9.2-9).

Covers the card's verification list: sampling indices, eligibility
filtering, packet reconstruction shape, dispatch ledger semantics, and
scoring-template generation, plus the CLI command-order invariants of
manual_check_stage0_damage_probe (run reads the frozen selection and never
resamples; template preserves filled columns and repairs a deleted sheet)
and the frozen seed injection into the dispatch options. No test invokes
local or cloud inference.
"""

import csv
import json
import json as json_module
from pathlib import Path

import pytest

from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from manual import manual_check_stage0_damage_probe as cli
from manual.stage0_probe import (
    PROTOCOL_FREEZE_DATE,
    REVISION_PROMPT,
    SEED,
    DispatchLedger,
    EligibleTurn,
    build_evidence_packet,
    build_revision_messages,
    build_scoring_template,
    eligible_completed_turns,
    even_indices,
    load_frozen_selection,
    merge_scoring_template,
    partition_pre_marked,
    persist_run_artifacts,
    read_pre_marked_sheet,
    select_sample,
    validate_endpoint,
    write_scoring_sheet,
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
    session_id: str = "20260912-100000-a1", answer: str = "answer", **kwargs
) -> EligibleTurn:
    return EligibleTurn(
        session_id=session_id,
        user_position=0,
        assistant_position=1,
        request_text="question",
        answer_text=answer,
        timestamp="2026-09-12T10:00:01+03:00",
        **kwargs,
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
        _event(
            "20260912-100000-a1",
            "user",
            "",
            source="voice",
        ),
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


def test_spoken_derivative_gives_text_voice_mode_hint():
    records = [
        _event("20260912-100000-a1", "user", "q"),
        _event(
            "20260912-100000-a1",
            "assistant",
            "a",
            metadata={"spoken_derivative": "spoken a"},
        ),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0].mode_hint == "text_voice"


def test_no_derivative_leaves_mode_hint_empty():
    records = [
        _event("20260912-100000-a1", "user", "q"),
        _event("20260912-100000-a1", "assistant", "a"),
    ]
    pairs = eligible_completed_turns(records)
    assert pairs[0][0].mode_hint == ""


def test_turns_after_protocol_freeze_are_outside_the_population():
    late_event = JournalEvent(
        session_id="20260912-100000-a1",
        timestamp="2026-09-14T10:00:00+03:00",
        source="text",
        role="assistant",
        text="a",
        media=(),
        transcript=None,
    )
    records = [
        _event("20260912-100000-a1", "user", "q", position=0),
        JournalEventRecord(
            reference=JournalEventRef("20260912-100000-a1", 1), event=late_event
        ),
    ]
    sessions = [("20260912-100000-a1", eligible_completed_turns(records))]
    selected, ineligible, pool_size, out_of_window = select_sample(sessions)
    assert selected == []
    assert ineligible == []
    assert pool_size == 0
    assert out_of_window == 1


def test_freeze_boundary_is_the_local_end_of_the_freeze_day():
    # The journal stamps local time with microseconds; whatever offset it
    # uses, every moment of the freeze day is inside the window and the
    # day after is outside (the instant-boundary bug cut at 23:59:59 and
    # dropped the sub-second tail of the day).
    assert PROTOCOL_FREEZE_DATE == "2026-09-13"
    from manual.stage0_probe import _in_window

    assert _in_window("2026-09-13T23:59:59.701642+01:00")
    assert _in_window("2026-09-12T23:30:00+01:00")
    assert not _in_window("2026-09-14T00:00:00+01:00")
    assert not _in_window("2026-09-14T08:59:00+03:00")


def test_even_indices_match_the_frozen_floor_rule():
    assert even_indices(6, size=30) == [0, 1, 2, 3, 4, 5]
    assert even_indices(0) == []
    indices = even_indices(300, size=30)
    assert len(indices) == 30
    assert indices[0] == 5
    assert indices == sorted(set(indices))


def test_even_indices_span_the_whole_pool_not_its_tail():
    indices = even_indices(90, size=30)
    assert indices[0] == 1
    assert indices[-1] == 88


def test_select_sample_applies_even_indices_over_the_pool():
    pool = [_turn(f"20260912-1000{i:02d}-a1") for i in range(40)]
    sessions = [("20260912-100000-a1", [(turn, None) for turn in pool])]
    selected, ineligible, pool_size, out_of_window = select_sample(sessions, size=30)
    assert ineligible == []
    assert pool_size == 40
    assert out_of_window == 0
    assert len(selected) == 30
    assert [turn.turn_id for turn in selected] == [
        pool[index].turn_id for index in even_indices(40, size=30)
    ]
    assert selected[0].session_id == pool[0].session_id


def test_select_sample_reports_all_ineligible_without_silent_drop():
    pool = [_turn() for _ in range(5)]
    ineligible_turns = [_turn(f"20260912-1001{i:02d}-b1") for i in range(3)]
    skipped = [(None, item) for item in ineligible_turns]
    sessions = [("20260912-100000-a1", [(turn, None) for turn in pool] + skipped)]
    selected, ineligible, pool_size, out_of_window = select_sample(sessions, size=30)
    assert len(selected) == 5
    assert len(ineligible) == 3
    assert pool_size == 5
    assert out_of_window == 0


def test_evidence_packet_is_exactly_the_request():
    turn = _turn()
    assert build_evidence_packet(turn) == "question"


def test_revision_messages_carry_system_prompt_labeled_draft_and_frozen_prompt():
    messages = build_revision_messages(
        _turn(answer="draft answer"), system_prompt="persona text"
    )
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "persona text"}
    content = messages[1]["content"]
    assert "question" in content
    assert "draft answer" in content
    assert REVISION_PROMPT in content
    assert "Черновик ответа (D)" in content


def test_revision_prompt_permits_retaining_the_answer():
    assert "сохранить текст без изменений - допустимый исход" in REVISION_PROMPT


def test_endpoint_guard_rejects_public_host_and_cloud_model():
    validate_endpoint("http://localhost:11434", "gemma4:12b")
    validate_endpoint("http://127.0.0.1:11434", "gemma4:12b")
    validate_endpoint("http://[::1]:11434", "gemma4:12b")
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


def test_ledger_resume_blocks_on_unresolved_and_skips_terminal(tmp_path: Path):
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    ledger.record_dispatched("t1")
    ledger.record_completed("t2", "artifact.json")
    ledger.record_failed("t3", "boom")
    ledger.record_interrupted("t4")
    reopened = DispatchLedger(tmp_path / "ledger.jsonl")
    planned = ["t1", "t2", "t3", "t4", "t5"]
    assert reopened.blocking_turn_ids(planned) == ["t1", "t4"]
    assert reopened.pending_turn_ids(planned) == ["t1", "t4", "t5"]
    reopened.record_completed("t1", "artifact.json")
    reopened.record_reset("t4")
    reopened.record_completed("t5", "artifact.json")
    final = DispatchLedger(tmp_path / "ledger.jsonl")
    assert final.blocking_turn_ids(planned) == []
    assert final.pending_turn_ids(planned) == ["t4"]


def test_ledger_records_are_persisted_jsonl(tmp_path: Path):
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    ledger.record_dispatched("t1")
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["status"] == "dispatched"
    assert len(lines) == 1


def test_scoring_template_pre_fills_mode_and_leaves_owner_columns_empty():
    turn = _turn(mode_hint="text_voice")
    rows = build_scoring_template([turn])
    assert len(rows) == 1
    assert rows[0].turn_id == "20260912-100000-a1#1"
    assert rows[0].mode == "text_voice"
    assert rows[0].pre_mark == ""
    assert rows[0].label == ""
    assert rows[0].fidelity_note == ""


def test_merge_scoring_template_preserves_filled_columns():
    turn = _turn(mode_hint="")
    existing = {
        turn.turn_id: {
            "mode": "text",
            "pre_mark": "correct",
            "label": "damaged",
            "reason": "lost a constraint",
            "fidelity_note": "packet complete",
        }
    }
    rows = merge_scoring_template([turn], existing)
    assert rows[0].mode == "text"
    assert rows[0].pre_mark == "correct"
    assert rows[0].label == "damaged"
    assert rows[0].reason == "lost a constraint"
    assert rows[0].fidelity_note == "packet complete"


def test_partition_splits_denominator_from_exclusions():
    text_turn = _turn("20260912-100000-a1")
    voice_turn = _turn("20260912-100001-b2")
    unknown_turn = _turn("20260912-100002-c3")
    unmarked_turn = _turn("20260912-100003-d4")
    not_correct_turn = _turn("20260912-100004-e5")
    sheet = {
        text_turn.turn_id: {"mode": "text", "pre_mark": "correct"},
        voice_turn.turn_id: {"mode": "voice", "pre_mark": "correct"},
        # "unknown" is the owner's honest can-not-tell decision.
        unknown_turn.turn_id: {"mode": "unknown", "pre_mark": "correct"},
        # An empty mode is the same decision (the schema pre-fills nothing
        # for text/voice turns); it must not block or mislabel.
        unmarked_turn.turn_id: {"mode": "", "pre_mark": "correct"},
        not_correct_turn.turn_id: {"mode": "text", "pre_mark": "not_correct"},
    }
    partition = partition_pre_marked(
        [text_turn, voice_turn, unknown_turn, unmarked_turn, not_correct_turn],
        sheet,
    )
    assert [turn.turn_id for turn in partition.to_dispatch] == [text_turn.turn_id]
    assert partition.mode_excluded == [
        (voice_turn.turn_id, "voice"),
        (unknown_turn.turn_id, "unknown"),
        (unmarked_turn.turn_id, "unknown"),
    ]
    assert partition.not_correct == [not_correct_turn.turn_id]
    assert partition.unresolved == []


def test_partition_requires_a_sheet_row_and_a_pre_mark():
    turn = _turn()
    unmarked = _turn("20260912-100009-z9")
    partition = partition_pre_marked(
        [turn, unmarked], {unmarked.turn_id: {"mode": "text", "pre_mark": ""}}
    )
    assert partition.to_dispatch == []
    assert partition.unresolved == [
        (turn.turn_id, "no scoring row for the turn"),
        (unmarked.turn_id, "pre_mark is ''"),
    ]


def _persist_selection(tmp_path: Path, turn: EligibleTurn) -> Path:
    persist_run_artifacts(
        tmp_path,
        turns=[turn],
        ineligible=[],
        scoring_rows=build_scoring_template([turn]),
        selected_count=1,
        pool_size=7,
        out_of_window=2,
    )
    return tmp_path


def test_persist_run_artifacts_writes_local_records(tmp_path: Path):
    turn = _turn(mode_hint="text_voice")
    _persist_selection(tmp_path, turn)
    selection = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert selection["pool_size"] == 7
    assert selection["out_of_window"] == 2
    assert selection["protocol_freeze_date"] == "2026-09-13"
    assert selection["selected"] == 1
    assert selection["selected_turns"][0]["mode_hint"] == "text_voice"
    assert "seed" not in selection
    assert selection["protocol_card"].endswith("stage0-damage-and-inertness-probe.md")
    packets = (tmp_path / "packets.jsonl").read_text(encoding="utf-8").splitlines()
    packet = json.loads(packets[0])
    assert packet["request"] == "question"
    assert packet["draft"] == "answer"
    sheet = (tmp_path / "scoring_sheet.csv").read_text(encoding="utf-8-sig")
    assert "turn_id,mode,pre_mark" in sheet
    assert "fidelity_note" in sheet


def test_load_frozen_selection_reads_back_the_persisted_sample(tmp_path: Path):
    turn = _turn(mode_hint="text_voice")
    _persist_selection(tmp_path, turn)
    loaded = load_frozen_selection(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].turn_id == turn.turn_id
    assert loaded[0].request_text == turn.request_text
    assert loaded[0].answer_text == turn.answer_text
    assert loaded[0].mode_hint == turn.mode_hint


def test_load_frozen_selection_rejects_disagreement(tmp_path: Path):
    turn = _turn()
    _persist_selection(tmp_path, turn)
    selection_path = tmp_path / "selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["selected_turns"] = []
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    try:
        load_frozen_selection(tmp_path)
    except ValueError as exc:
        assert "disagree" in str(exc)
    else:
        raise AssertionError("inconsistent artifacts accepted")


def test_write_scoring_sheet_round_trips_commas_in_owner_columns(
    tmp_path: Path,
):
    # A comma in an owner-filled cell must not shift the following columns:
    # the sheet is the stop-rule record, so label spilling into reason and
    # eating the fidelity note is outcome-corrupting, not cosmetic.
    row = build_scoring_template([_turn()])[0]
    row = type(row)(
        turn_id=row.turn_id,
        mode="text",
        pre_mark="correct",
        request_excerpt=row.request_excerpt,
        published_answer_excerpt=row.published_answer_excerpt,
        label="minor, presentation only",
        reason="ok",
        fidelity_note="",
    )
    path = tmp_path / "sheet.csv"
    write_scoring_sheet(path, [row])
    reread = read_pre_marked_sheet(path)
    assert reread[row.turn_id]["label"] == "minor, presentation only"
    assert reread[row.turn_id]["reason"] == "ok"
    assert reread[row.turn_id]["fidelity_note"] == ""


def test_write_scoring_sheet_round_trips_template_row(tmp_path: Path):
    turn = _turn(mode_hint="text_voice")
    rows = build_scoring_template([turn])
    path = tmp_path / "sheet.csv"
    write_scoring_sheet(path, rows)
    reread = merge_scoring_template([turn], read_pre_marked_sheet(path))
    assert reread == rows


def test_protocol_freeze_date_matches_the_card_authorization():
    assert PROTOCOL_FREEZE_DATE == "2026-09-13"


def test_read_pre_marked_sheet_reads_a_missing_sheet_as_empty(tmp_path: Path):
    assert read_pre_marked_sheet(tmp_path / "absent.csv") == {}


# --- CLI command-order invariants (manual_check_stage0_damage_probe) ---
# The previous blocker lived in the CLI and no test imported it; these tests
# pin the sequencing the handoff depends on, without any live inference.
# The run-path test drives main(["run"]) itself, not its building blocks, so
# a regression in the command order fails here instead of in the owner's run.


def _wire_cli_tmp_paths(monkeypatch: pytest.MonkeyPatch, out_dir: Path) -> None:
    monkeypatch.setattr(cli, "OUT_DIR", out_dir)
    monkeypatch.setattr(cli, "LEDGER_PATH", out_dir / "ledger.jsonl")
    monkeypatch.setattr(cli, "SCORING_SHEET", out_dir / "scoring_sheet.csv")
    monkeypatch.setattr(cli, "_SELECTION_FILE", out_dir / "selection.json")


def _persist_one_turn(out_dir: Path, turn: EligibleTurn) -> None:
    persist_run_artifacts(
        out_dir,
        turns=[turn],
        ineligible=[],
        scoring_rows=build_scoring_template([turn]),
        selected_count=1,
        pool_size=1,
        out_of_window=0,
    )


def _fill_sheet_all_correct(sheet_path: Path, mode: str = "text") -> None:
    with sheet_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    for row in rows:
        row["mode"] = mode
        row["pre_mark"] = "correct"
    with sheet_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _fake_settings(monkeypatch: pytest.MonkeyPatch, memory_root: Path) -> None:
    from jarvis.core.config import BackendSettings, MemorySettings, PromptSettings

    class _Journal:
        root = "unused-by-run"

    settings = type("Settings", (), {})()
    settings.backend = BackendSettings(
        model="gemma4:12b",
        endpoint="http://127.0.0.1:11434",
        read_timeout_seconds=60,
    )
    settings.journal = _Journal()
    settings.prompts = PromptSettings(system="base prompt")
    settings.memory = MemorySettings(root=str(memory_root))
    monkeypatch.setattr(cli, "load_settings", lambda: settings)


class _FakeDispatchClient:
    """Records the last payload and answers with one done:true chunk."""

    last_payload: dict | None = None

    def __init__(self, base_url: str = "", timeout=None) -> None:
        pass

    def stream(self, method: str, url: str, *, json: dict):
        _FakeDispatchClient.last_payload = json
        done_line = json_module.dumps(
            {
                "message": {"role": "assistant", "content": "revised"},
                "done": True,
                "eval_count": 7,
            },
            ensure_ascii=False,
        )

        class _Response:
            def raise_for_status(self) -> None:
                return None

            async def aiter_lines(self):
                yield done_line

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

        return _Response()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def test_run_dispatches_frozen_selection_with_seed_and_system_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _wire_cli_tmp_paths(monkeypatch, tmp_path)
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "self.md").write_text("persona facts", encoding="utf-8")
    turn = _turn(mode_hint="")
    _persist_one_turn(tmp_path, turn)
    _fill_sheet_all_correct(tmp_path / "scoring_sheet.csv")
    _fake_settings(monkeypatch, memory_root)
    monkeypatch.setattr(cli.httpx, "AsyncClient", _FakeDispatchClient)
    _FakeDispatchClient.last_payload = None

    # Any journal access or resampling on the run path fails the test:
    # run must work from the frozen artifacts alone.
    def _fail_open_store(*args, **kwargs):
        raise AssertionError("run must not open the journal store")

    monkeypatch.setattr(cli, "JournalStore", _fail_open_store)

    cli.main(["run"])

    payload = _FakeDispatchClient.last_payload
    assert payload is not None
    assert payload["options"]["seed"] == SEED
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert "base prompt" in messages[0]["content"]
    assert "persona facts" in messages[0]["content"]
    assert messages[1]["content"].startswith("Исходный запрос:")
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    assert ledger.pending_turn_ids([turn.turn_id]) == []
    artifact = tmp_path / f"revision-{turn.turn_id.replace('#', '__')}.json"
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "completed"


def test_run_refuses_to_dispatch_with_unfinished_pre_marking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    _wire_cli_tmp_paths(monkeypatch, tmp_path)
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    turn = _turn(mode_hint="")
    _persist_one_turn(tmp_path, turn)
    _fake_settings(monkeypatch, memory_root)

    def _fail_dispatch(*args, **kwargs):
        raise AssertionError("unfinished pre-marking must not dispatch")

    monkeypatch.setattr(cli, "_run_dispatch", _fail_dispatch)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["run"])
    assert "pre-marking is not complete" in str(exc_info.value)
    assert not (tmp_path / "ledger.jsonl").exists()


def test_template_rebuilds_even_when_the_sheet_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _wire_cli_tmp_paths(monkeypatch, tmp_path)
    turn = _turn(mode_hint="")
    _persist_one_turn(tmp_path, turn)
    (tmp_path / "scoring_sheet.csv").unlink()
    cli.main(["template"])
    reread = read_pre_marked_sheet(tmp_path / "scoring_sheet.csv")
    assert reread[turn.turn_id]["pre_mark"] == ""


def test_template_preserves_owner_marks_and_repairs_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _wire_cli_tmp_paths(monkeypatch, tmp_path)
    turn = _turn(mode_hint="")
    _persist_one_turn(tmp_path, turn)
    _fill_sheet_all_correct(tmp_path / "scoring_sheet.csv")
    cli.main(["template"])
    reread = read_pre_marked_sheet(tmp_path / "scoring_sheet.csv")
    assert reread[turn.turn_id]["pre_mark"] == "correct"
    assert reread[turn.turn_id]["mode"] == "text"


def test_resume_resolves_a_blocked_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _wire_cli_tmp_paths(monkeypatch, tmp_path)
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    ledger.record_dispatched("t1")
    cli._resume(DispatchLedger(tmp_path / "ledger.jsonl"), "completed", "t1")
    final = DispatchLedger(tmp_path / "ledger.jsonl")
    assert final.blocking_turn_ids(["t1"]) == []
    assert final.pending_turn_ids(["t1"]) == []
    cli._resume(DispatchLedger(tmp_path / "ledger.jsonl"), "completed", "t1")
    assert (
        len((tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    )
