"""Stage 0 damage/inertness probe core logic (card task-v1.9.2-9).

Pure, local-only support for the frozen stage-0 experiment: sample completed
Journal text turns by the predeclared rule, reconstruct each turn's evidence
packet, build one revision dispatch per pre-marked-correct text-mode turn,
and persist a dispatch ledger plus a scoring template. No live inference
lives here; the CLI wrapper (manual_check_stage0_damage_probe.py) owns
dispatch, and the human owns pre-marking and scoring.

Frozen parameters live in tasks/task-v1.9.2-9-stage0-damage-and-inertness-probe.md
and are re-stated in tasks/v1.9.2-stage0-stop-rule.md. Changing sampling,
eligibility, or stop-rule logic is a protocol change, not a code change.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from jarvis.journal.events import (
    JournalEvent,
    JournalEventRecord,
    parse_journal_timestamp,
)

SAMPLE_SIZE = 30
# Model-options seed for each revision call (control, not a reproducibility
# promise). Selection is deterministic; the seed never influences sampling.
SEED = 19200
RUN_ID = "v192-stage0-01"
RAW_OUTPUT_ROOT = Path("manual_check_answer_revision_out")
PROTOCOL_CARD = "tasks/task-v1.9.2-9-stage0-damage-and-inertness-probe.md"
# The sampling period ends at protocol freeze: the end of 2026-09-13 in the
# Journal's local timezone (the card's frozen parameters were authorized on
# 2026-09-12; turns recorded after that day's end are outside the population
# of record). The journal stamps local wall time, so comparing the stamped
# date against the freeze date gives the local end of day, whatever offset
# the timestamp carries.
PROTOCOL_FREEZE_DATE = "2026-09-13"

SCORING_COLUMNS = (
    "turn_id",
    "mode",
    "pre_mark",
    "request_excerpt",
    "published_answer_excerpt",
    "label",
    "reason",
    "fidelity_note",
)
PRE_MARK_CORRECT = "correct"
PRE_MARK_NOT_CORRECT = "not_correct"
# Response modes as the owner hand-marks them during pre-marking; the
# Journal schema does not record the mode (filed bug report 2026-09-12).
# "unknown" is a first-class owner decision: a correct turn the owner cannot
# confidently mode-mark is recorded and excluded as mode_excluded, never
# merged into not_correct and never blocking the run.
RESPONSE_MODES = ("text", "voice", "text_voice")
MODE_UNKNOWN = "unknown"
_SPOKEN_DERIVATIVE_KEY = "spoken_derivative"

REVISION_PROMPT = (
    "Это мой черновик ответа, ещё не отправленный. Перед отправкой проверь "
    "его по исходному запросу и приведённым материалам. Исправляй только "
    "существенные ошибки (неверно понятый запрос, потерянное ограничение, "
    "неподкреплённое утверждение, ошибка в расчёте или рассуждении, "
    "пропущенная важная оговорка); сохранить текст без изменений - "
    "допустимый исход. Не переписывай стиль без необходимости. Верни "
    "полный окончательный ответ."
)

# Eligibility is judged per turn from what the Journal records: media and
# aborted outcomes are machine-checked; tool execution and retrieved
# history/memory dependence are NOT journaled (the schema gap of bug report
# 2026-09-12), so they are delegated to the owner like the response mode:
# eligibility is confirmed per turn during pre-marking, before any revision
# output exists.
_INELIGIBLE_REASON_UNPAIRED = "no adjacent user request in the same session"
_INELIGIBLE_REASON_ABORTED = "aborted outcome recorded on the assistant event"
_INELIGIBLE_REASON_MEDIA = "media attached to the user or assistant event"
_INELIGIBLE_REASON_UNTRANSCRIBED = "voice request without a usable transcript"


@dataclass(frozen=True)
class EligibleTurn:
    session_id: str
    user_position: int
    assistant_position: int
    request_text: str
    answer_text: str
    timestamp: str
    mode_hint: str = ""

    @property
    def turn_id(self) -> str:
        return f"{self.session_id}#{self.assistant_position}"


@dataclass(frozen=True)
class IneligibleTurn:
    session_id: str
    assistant_position: int
    reason: str
    timestamp: str


def eligible_completed_turns(
    records: list[JournalEventRecord],
) -> list[tuple[EligibleTurn | None, IneligibleTurn | None]]:
    """Split one session's records into (eligible, ineligible) turn tuples.

    A completed turn is an assistant event immediately preceded by a user
    event, with no outcome metadata (an outcome marks interrupted/failed/
    mode_switched turns). Everything else is reported as ineligible with a
    reason; nothing is silently dropped. The mode hint pre-fills the owner's
    hand-marking: a spoken derivative proves text_voice; its absence leaves
    the mode unknown (text and voice are indistinguishable in the schema).
    """
    turns: list[tuple[EligibleTurn | None, IneligibleTurn | None]] = []
    for index, record in enumerate(records):
        event = record.event
        if event.role != "assistant":
            continue
        if event.metadata.get("outcome") is not None:
            turns.append(
                (
                    None,
                    IneligibleTurn(
                        session_id=event.session_id,
                        assistant_position=index,
                        reason=_INELIGIBLE_REASON_ABORTED,
                        timestamp=event.timestamp,
                    ),
                )
            )
            continue
        user = records[index - 1].event if index > 0 else None
        if user is None or user.role != "user":
            turns.append(
                (
                    None,
                    IneligibleTurn(
                        session_id=event.session_id,
                        assistant_position=index,
                        reason=_INELIGIBLE_REASON_UNPAIRED,
                        timestamp=event.timestamp,
                    ),
                )
            )
            continue
        request_text = model_facing_request_text(user)
        if request_text == "":
            turns.append(
                (
                    None,
                    IneligibleTurn(
                        session_id=event.session_id,
                        assistant_position=index,
                        reason=_INELIGIBLE_REASON_UNTRANSCRIBED,
                        timestamp=event.timestamp,
                    ),
                )
            )
            continue
        if event.media or user.media:
            turns.append(
                (
                    None,
                    IneligibleTurn(
                        session_id=event.session_id,
                        assistant_position=index,
                        reason=_INELIGIBLE_REASON_MEDIA,
                        timestamp=event.timestamp,
                    ),
                )
            )
            continue
        turns.append(
            (
                EligibleTurn(
                    session_id=event.session_id,
                    user_position=index - 1,
                    assistant_position=index,
                    request_text=request_text,
                    answer_text=event.text,
                    timestamp=event.timestamp,
                    mode_hint=_mode_hint(event),
                ),
                None,
            )
        )
    return turns


def _mode_hint(event: JournalEvent) -> str:
    if event.metadata.get(_SPOKEN_DERIVATIVE_KEY) is not None:
        return "text_voice"
    return ""


def model_facing_request_text(event: JournalEvent) -> str:
    """The request words as a reviser would see them (fork.py's mapping)."""
    if event.source == "voice":
        if event.transcript is not None and event.transcript != "":
            return event.transcript
        return event.text
    return event.text


def even_indices(total: int, size: int = SAMPLE_SIZE) -> list[int]:
    """The frozen selection rule: floor((i+0.5)*N/size) into an N-item pool.

    Applied directly by select_sample(); the sampling handoff uses it to
    show which pool items the rule picks.
    """
    if total <= 0:
        return []
    if total <= size:
        return list(range(total))
    return [((2 * i + 1) * total) // (2 * size) for i in range(size)]


def _in_window(timestamp: str) -> bool:
    """True when a journal timestamp falls within the freeze day or before.

    The journal stamps local wall time, so the stamped date compared against
    PROTOCOL_FREEZE_DATE is the local end of the freeze day - the whole
    freeze day is inside, the day after is outside, whatever offset the
    timestamp carries. Date comparison, not instant comparison, so
    sub-second timestamps in the last second of the day are inside too.
    """
    return parse_journal_timestamp(timestamp).date() <= date.fromisoformat(
        PROTOCOL_FREEZE_DATE
    )


def select_sample(
    sessions: list[tuple[str, list[tuple[EligibleTurn | None, IneligibleTurn | None]]]],
    *,
    size: int = SAMPLE_SIZE,
) -> tuple[list[EligibleTurn], list[IneligibleTurn], int, int]:
    """The frozen selection over chronologically listed sessions.

    Sessions arrive sorted by first timestamp (JournalStore.list_sessions
    order); turns keep their natural order. The population of record is the
    period ending at protocol freeze: eligible turns and recorded
    exclusions dated after the freeze day's local end are outside it. The
    out-of-window counts are returned separately so the selection record
    can show whether the window cut anything at all. From the in-window
    pool of N eligible turns the rule picks the floor((i+0.5)*N/size)
    indices (even_indices); when N <= size the whole pool is selected and
    the shortfall is reported by the caller.
    """
    pool: list[EligibleTurn] = []
    ineligible: list[IneligibleTurn] = []
    out_of_window = 0
    for _session_id, turns in sessions:
        for eligible, skipped in turns:
            if eligible is not None:
                if _in_window(eligible.timestamp):
                    pool.append(eligible)
                else:
                    out_of_window += 1
            if skipped is not None:
                if _in_window(skipped.timestamp):
                    ineligible.append(skipped)
                else:
                    out_of_window += 1
    selected = [pool[index] for index in even_indices(len(pool), size)]
    return selected, ineligible, len(pool), out_of_window


def build_evidence_packet(turn: EligibleTurn) -> str:
    """Trivially reconstructible packet: the original request, nothing else.

    Media and aborted outcomes are machine-checked in
    eligible_completed_turns(); tool execution and retrieved
    history/memory dependence are not journaled (schema gap, bug report
    2026-09-12), so the owner confirms them per turn during pre-marking.
    If the owner confirms either, the turn is excluded and never revised,
    so a packet needing more than the request text never reaches the
    reviser. The rest of what the published answer was produced under -
    the current effective system prompt - is carried separately as the
    revision request's system message (see build_revision_messages). The
    single user/assistant pair is the boundary; the packet never pulls
    surrounding session context.
    """
    return turn.request_text


def build_revision_messages(
    turn: EligibleTurn, *, system_prompt: str
) -> list[dict[str, str]]:
    """One revision request shaped like a production turn.

    The system message carries the current effective system prompt, so the
    reviser keeps the persona and output contract the published answer was
    written under; without it a reviser would change register and format,
    polluting exactly the damage being measured. The user message carries
    the packet, the labeled draft, and the frozen instruction (the spike
    card's Revision A first-person framing text, frozen verbatim). D is
    labeled data, not fabricated assistant history.
    """
    packet = build_evidence_packet(turn)
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Исходный запрос:\n{packet}\n\n"
                f"Черновик ответа (D):\n{turn.answer_text}\n\n"
                f"{REVISION_PROMPT}"
            ),
        },
    ]


def validate_endpoint(endpoint: str, model: str) -> None:
    """Local-only guard: loopback endpoint, no :cloud tag on the model."""
    host = urlsplit(endpoint).hostname or ""
    loopback = {"localhost", "127.0.0.1", "::1"}
    if host.lower() not in loopback:
        raise ValueError(f"endpoint must be loopback, got {endpoint!r}")
    if ":cloud" in model:
        raise ValueError(f"cloud model is not allowed, got {model!r}")


class DispatchLedger:
    """Append-only JSONL ledger with explicit-resume semantics.

    One record per turn dispatch: turn_id and status. Statuses:
    dispatched (call in flight or outcome unknown - also what a Ctrl+C
    outside the model stream leaves behind), completed / failed
    (terminal), interrupted (a Ctrl+C inside the model stream), pending
    (reset by explicit resume for re-dispatch). Only the latest record per
    turn_id decides. Resume rules: terminal records are skipped;
    dispatched and interrupted records are unresolved - they block run
    until the owner decides each one through the CLI's resume command;
    pending records are dispatched again on the next run.
    """

    TERMINAL_STATUSES = frozenset({"completed", "failed"})
    BLOCKING_STATUSES = frozenset({"dispatched", "interrupted"})
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_INTERRUPTED = "interrupted"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: dict[str, dict[str, object]] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    self._records[str(record["turn_id"])] = record

    @property
    def records(self) -> dict[str, dict[str, object]]:
        return dict(self._records)

    def pending_turn_ids(self, planned: list[str]) -> list[str]:
        """Planned turns to dispatch: unseen or non-terminal latest status."""
        pending = []
        for turn_id in planned:
            record = self._records.get(turn_id)
            if (
                record is None
                or str(record.get("status")) not in self.TERMINAL_STATUSES
            ):
                pending.append(turn_id)
        return pending

    def blocking_turn_ids(self, planned: list[str]) -> list[str]:
        """Unresolved planned turns: dispatched or interrupted last known."""
        return [
            turn_id
            for turn_id in planned
            if turn_id in self._records
            and str(self._records[turn_id].get("status")) in self.BLOCKING_STATUSES
        ]

    def record_dispatched(self, turn_id: str) -> None:
        self._append({"turn_id": turn_id, "status": "dispatched"})

    def record_completed(self, turn_id: str, artifact_name: str) -> None:
        self._append(
            {
                "turn_id": turn_id,
                "status": "completed",
                "artifact": artifact_name,
            }
        )

    def record_failed(self, turn_id: str, error: str) -> None:
        self._append({"turn_id": turn_id, "status": "failed", "error": error})

    def record_interrupted(self, turn_id: str) -> None:
        self._append({"turn_id": turn_id, "status": "interrupted"})

    def record_reset(self, turn_id: str) -> None:
        """Explicit resume outcome: clear the block, queue re-dispatch."""
        self._append({"turn_id": turn_id, "status": "pending"})

    def _append(self, record: dict[str, object]) -> None:
        self._records[str(record["turn_id"])] = record
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ScoringRow:
    turn_id: str
    mode: str
    pre_mark: str
    request_excerpt: str
    published_answer_excerpt: str
    label: str
    reason: str
    fidelity_note: str


def build_scoring_template(turns: list[EligibleTurn]) -> list[ScoringRow]:
    """One row per selected turn; the human fills mode, pre_mark, label.

    The mode column is pre-filled with the schema hint (text_voice when a
    spoken derivative was recorded; empty when text and voice cannot be
    distinguished) and is confirmed or corrected by the owner during
    pre-marking, before any revision output exists. Labels compare the
    revision against the pre-marked-correct published answer: LABELS lists
    the vocabulary, not_assessable leaves the denominators. The
    fidelity_note column keeps the per-turn reconstruction-fidelity note
    the stop rule requires for damage caused by a misread packet.
    """
    rows = []
    for turn in turns:
        rows.append(
            ScoringRow(
                turn_id=turn.turn_id,
                mode=turn.mode_hint,
                pre_mark="",
                request_excerpt=turn.request_text[:160],
                published_answer_excerpt=turn.answer_text[:160],
                label="",
                reason="",
                fidelity_note="",
            )
        )
    return rows


def merge_scoring_template(
    turns: list[EligibleTurn], existing: dict[str, dict[str, str]]
) -> list[ScoringRow]:
    """Rebuild rows from the frozen selection, preserving filled columns.

    Used by the template command so repairing a damaged sheet never wipes
    the owner's pre-marks, labels, reasons, or fidelity notes.
    """
    rows = []
    for turn in turns:
        saved = existing.get(turn.turn_id, {})
        rows.append(
            ScoringRow(
                turn_id=turn.turn_id,
                mode=saved.get("mode") or turn.mode_hint,
                pre_mark=saved.get("pre_mark", ""),
                request_excerpt=saved.get("request_excerpt") or turn.request_text[:160],
                published_answer_excerpt=saved.get("published_answer_excerpt")
                or turn.answer_text[:160],
                label=saved.get("label", ""),
                reason=saved.get("reason", ""),
                fidelity_note=saved.get("fidelity_note", ""),
            )
        )
    return rows


def read_pre_marked_sheet(path: Path) -> dict[str, dict[str, str]]:
    """The scoring sheet as a turn_id -> column-value mapping.

    The sheet is the single pre-marking record: rows the human marked
    "correct" with mode "text" before any revision existed are the damage
    denominator; "not_correct" rows, non-text modes, and "unknown" modes
    are recorded and excluded with distinct reasons. A missing sheet reads
    as empty: whether that is an error (run before sample, or a deleted
    sheet the template command should rebuild) is the CLI's decision, not
    this module's.
    """
    if not path.exists():
        return {}
    sheet: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            turn_id = (row.get("turn_id") or "").strip()
            if turn_id:
                sheet[turn_id] = {
                    column: (row.get(column) or "").strip()
                    for column in SCORING_COLUMNS
                }
    return sheet


@dataclass(frozen=True)
class PreMarkPartition:
    """The owner's pre-marking split into distinct exclusion categories.

    to_dispatch: pre-marked correct with mode text - the damage
    denominator. mode_excluded holds correct turns the owner marked with a
    non-text mode or "unknown" (a first-class decision: cannot
    confidently mode-mark), each recorded as (turn_id, mode) - none of
    them merges into not_correct. not_correct is its own denominator.
    unresolved marks rows the owner has not finished: an empty pre_mark
    (the mark itself is missing) or a row missing from the sheet; run
    stops on those, because a row not yet pre-marked is not the same
    decision as "unknown mode".
    """

    to_dispatch: list[EligibleTurn]
    not_correct: list[str]
    mode_excluded: list[tuple[str, str]]
    unresolved: list[tuple[str, str]]


def partition_pre_marked(
    turns: list[EligibleTurn], sheet: dict[str, dict[str, str]]
) -> PreMarkPartition:
    to_dispatch: list[EligibleTurn] = []
    not_correct: list[str] = []
    mode_excluded: list[tuple[str, str]] = []
    unresolved: list[tuple[str, str]] = []
    for turn in turns:
        row = sheet.get(turn.turn_id)
        if row is None:
            unresolved.append((turn.turn_id, "no scoring row for the turn"))
            continue
        pre_mark = row["pre_mark"].lower()
        mode = row["mode"].lower()
        if pre_mark == PRE_MARK_CORRECT:
            if mode == "text":
                to_dispatch.append(turn)
            elif mode in RESPONSE_MODES:
                mode_excluded.append((turn.turn_id, mode))
            elif mode in ("", MODE_UNKNOWN):
                mode_excluded.append((turn.turn_id, MODE_UNKNOWN))
            else:
                unresolved.append((turn.turn_id, f"unknown mode value: {mode!r}"))
        elif pre_mark == PRE_MARK_NOT_CORRECT:
            not_correct.append(turn.turn_id)
        else:
            unresolved.append((turn.turn_id, f"pre_mark is {pre_mark!r}"))
    return PreMarkPartition(
        to_dispatch=to_dispatch,
        not_correct=not_correct,
        mode_excluded=mode_excluded,
        unresolved=unresolved,
    )


def load_frozen_selection(out_dir: Path) -> list[EligibleTurn]:
    """The frozen sample, read from the persisted selection artifacts.

    run() never resamples: dispatches must go to exactly the turns the
    owner pre-marked, so the turn list comes from selection.json and the
    full texts from packets.jsonl, cross-checked for consistency.
    """
    selection = json.loads((out_dir / "selection.json").read_text(encoding="utf-8"))
    packets: dict[str, dict[str, str]] = {}
    with (out_dir / "packets.jsonl").open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                record = json.loads(line)
                packets[str(record["turn_id"])] = record
    turns = []
    for item in selection["selected_turns"]:
        turn_id = str(item["turn_id"])
        packet = packets.get(turn_id)
        if packet is None:
            raise ValueError(f"packets.jsonl has no record for {turn_id}")
        turns.append(
            EligibleTurn(
                session_id=str(item["session_id"]),
                user_position=int(item["user_position"]),
                assistant_position=int(item["assistant_position"]),
                request_text=packet["request"],
                answer_text=packet["draft"],
                timestamp=str(item["timestamp"]),
                mode_hint=str(item.get("mode_hint", "")),
            )
        )
    if set(packets) != {turn.turn_id for turn in turns}:
        raise ValueError("selection.json and packets.jsonl disagree on turn ids")
    return turns


def persist_run_artifacts(
    out_dir: Path,
    *,
    turns: list[EligibleTurn],
    ineligible: list[IneligibleTurn],
    scoring_rows: list[ScoringRow],
    selected_count: int,
    pool_size: int,
    out_of_window: int,
) -> None:
    """Durable raw artifacts: selection record, scoring sheet, packet map.

    Everything stays local; the journal root is the only content source.
    The selection record stores the pool size N, the exclusions, and the
    out-of-window count (how many journal items the freeze window cut,
    which otherwise would be indistinguishable from zero in
    selection.json); the model-options seed is not part of selection and
    lives in the per-turn revision artifacts instead.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    selection = {
        "run_id": RUN_ID,
        "sample_size": SAMPLE_SIZE,
        "pool_size": pool_size,
        "out_of_window": out_of_window,
        "selected": selected_count,
        "selected_turns": [
            {
                "turn_id": turn.turn_id,
                "session_id": turn.session_id,
                "user_position": turn.user_position,
                "assistant_position": turn.assistant_position,
                "timestamp": turn.timestamp,
                "mode_hint": turn.mode_hint,
            }
            for turn in turns
        ],
        "ineligible_turns": [
            {
                "turn_id": f"{item.session_id}#{item.assistant_position}",
                "reason": item.reason,
            }
            for item in ineligible
        ],
        "protocol_freeze_date": PROTOCOL_FREEZE_DATE,
        "protocol_card": PROTOCOL_CARD,
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "packets.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "turn_id": turn.turn_id,
                    "request": build_evidence_packet(turn),
                    "draft": turn.answer_text,
                },
                ensure_ascii=False,
            )
            for turn in turns
        )
        + "\n",
        encoding="utf-8",
    )
    write_scoring_sheet(out_dir / "scoring_sheet.csv", scoring_rows)


def write_scoring_sheet(path: Path, rows: list[ScoringRow]) -> None:
    """Write the sheet with the csv module, quoting where a cell needs it.

    The sheet is the stop-rule record; a hand-edited comma in a cell must
    never shift the following columns (label spilling into reason and
    eating the fidelity note), so no cell is written through manual
    string joining - csv.writer's minimal quoting quotes exactly the
    cells that would otherwise break parsing.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SCORING_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.turn_id,
                row.mode,
                row.pre_mark,
                row.request_excerpt,
                row.published_answer_excerpt,
                row.label,
                row.reason,
                row.fidelity_note,
            ]
        )
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")
