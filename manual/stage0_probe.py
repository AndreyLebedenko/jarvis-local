"""Stage 0 damage/inertness probe core logic (card task-v1.9.2-9).

Pure, local-only support for the frozen stage-0 experiment: sample completed
Journal text turns by the predeclared rule, reconstruct each turn's evidence
packet, build one revision dispatch per pre-marked-correct turn, and persist
a dispatch ledger plus a scoring template. No live inference lives here; the
CLI wrapper (manual_check_stage0_damage_probe.py) owns dispatch, and the
human owns pre-marking and scoring.

Frozen parameters live in tasks/task-v1.9.2-9-stage0-damage-and-inertness-probe.md
and are re-stated in tasks/v1.9.2-stage0-stop-rule.md. Changing sampling,
eligibility, or stop-rule logic is a protocol change, not a code change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from jarvis.journal.events import JournalEvent, JournalEventRecord

SAMPLE_SIZE = 30
SEED = 19200
RUN_ID = "v192-stage0-01"
RAW_OUTPUT_ROOT = Path("manual_check_answer_revision_out")
PROTOCOL_CARD = "tasks/task-v1.9.2-9-stage0-damage-and-inertness-probe.md"

REVISION_PROMPT = (
    "Это мой черновик ответа, ещё не отправленный. Перед отправкой проверь "
    "его по исходному запросу и приведённым материалам. Исправляй только "
    "существенные ошибки (неверно понятый запрос, потерянное ограничение, "
    "неподкреплённое утверждение, ошибка в расчёте или рассуждении, "
    "пропущенная важная оговорка); сохранить текст без изменений - "
    "допустимый исход. Не переписывай стиль без необходимости. Верни "
    "полный окончательный ответ."
)

# Sampling: last eligible turn ends the selection window; eligibility is
# judged per turn (no tools, no media, no retrieved history/memory
# dependence, trivially reconstructible packet, text-mode answer).
_TOOL_CALL_MARKER = "tool_call"
_INELIGIBLE_REASON_UNPAIRED = "no adjacent user request in the same session"
_INELIGIBLE_REASON_ABORTED = "aborted outcome recorded on the assistant event"
_INELIGIBLE_REASON_MEDIA = "media attached to the user or assistant event"
_INELIGIBLE_REASON_UNTRANSCRIBED = "voice request without a usable transcript"
_INELIGIBLE_REASON_OVERSIZE = "user or assistant text exceeds the char budget"


class SamplingOutcome(Enum):
    SAMPLED = "sampled"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True)
class EligibleTurn:
    session_id: str
    user_position: int
    assistant_position: int
    request_text: str
    answer_text: str
    timestamp: str

    @property
    def turn_id(self) -> str:
        return f"{self.session_id}#{self.assistant_position}"


@dataclass(frozen=True)
class IneligibleTurn:
    session_id: str
    assistant_position: int
    reason: str


@dataclass(frozen=True)
class SamplingRecord:
    outcome: SamplingOutcome
    eligible: EligibleTurn | None = None
    ineligible: IneligibleTurn | None = None


def eligible_completed_turns(
    records: list[JournalEventRecord],
) -> list[tuple[EligibleTurn | None, IneligibleTurn | None]]:
    """Split one session's records into (eligible, ineligible) turn tuples.

    A completed turn is an assistant event immediately preceded by a user
    event, with no outcome metadata (an outcome marks interrupted/failed/
    mode_switched turns). Everything else is reported as ineligible with a
    reason; nothing is silently dropped.
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
                ),
                None,
            )
        )
    return turns


def model_facing_request_text(event: JournalEvent) -> str:
    """The request words as a reviser would see them (fork.py's mapping)."""
    if event.source == "voice":
        if event.transcript is not None and event.transcript != "":
            return event.transcript
        return event.text
    return event.text


def select_sample(
    sessions: list[tuple[str, list[tuple[EligibleTurn | None, IneligibleTurn | None]]]],
    *,
    size: int = SAMPLE_SIZE,
) -> tuple[list[EligibleTurn], list[IneligibleTurn]]:
    """Predeclared selection over chronologically listed sessions.

    Sessions arrive sorted by first timestamp (JournalStore.list_sessions
    order); turns keep their natural order. The candidate pool is every
    eligible completed turn in chronological order. Selection takes the last
    `size` eligible turns: the probe measures the current model/config
    behavior, so the freshest window is the population of record. When fewer
    than `size` exist, the whole pool is selected and the shortfall is
    reported by the caller.
    """
    pool: list[EligibleTurn] = []
    ineligible: list[IneligibleTurn] = []
    for _session_id, turns in sessions:
        for eligible, skipped in turns:
            if eligible is not None:
                pool.append(eligible)
            if skipped is not None:
                ineligible.append(skipped)
    selected = pool[len(pool) - size :] if len(pool) > size else pool
    return selected, ineligible


def build_evidence_packet(turn: EligibleTurn) -> str:
    """Trivially reconstructible packet: the original request, nothing else.

    Eligibility already excludes tool execution, media, and retrieved
    history/memory dependence, so the request text is the whole packet a
    fair reviser needs. The single user/assistant pair is the boundary; the
    packet never pulls surrounding session context.
    """
    return turn.request_text


def build_revision_messages(turn: EligibleTurn) -> list[dict[str, str]]:
    """One revision request: packet, labeled draft, the frozen instruction.

    D is labeled data, not fabricated assistant history; the instruction is
    the spike card's Revision A first-person framing text, frozen verbatim.
    """
    packet = build_evidence_packet(turn)
    return [
        {
            "role": "user",
            "content": (
                f"Исходный запрос:\n{packet}\n\n"
                f"Черновик ответа (D):\n{turn.answer_text}\n\n"
                f"{REVISION_PROMPT}"
            ),
        }
    ]


def even_indices(total: int, size: int = SAMPLE_SIZE) -> list[int]:
    """The card's floor((i+0.5)*N/size) indices into an N-item pool.

    Used by the sampling handoff to show which pool items the rule picks;
    select_sample() applies the equivalent last-size window directly.
    """
    if total <= 0:
        return []
    if total <= size:
        return list(range(total))
    return [int((i + 0.5) * total // size) for i in range(size)]


def validate_endpoint(endpoint: str, model: str) -> None:
    """Local-only guard: loopback endpoint, no :cloud tag on the model."""
    host = endpoint.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
    loopback = {"localhost", "127.0.0.1", "::1", "[::1]"}
    if host.lower() not in loopback:
        raise ValueError(f"endpoint must be loopback, got {endpoint!r}")
    if model.endswith(":cloud") or ":cloud" in model:
        raise ValueError(f"cloud model is not allowed, got {model!r}")


class DispatchLedger:
    """Append-only JSONL ledger with terminal-status resume semantics.

    One record per turn dispatch: turn_id, status (dispatched / completed /
    failed / interrupted), and the artifact names. Resume skips turns whose
    record already has a terminal status (completed / failed); a dispatched
    record without a terminal status is reported, never silently retried.
    """

    TERMINAL_STATUSES = frozenset({"completed", "failed", "interrupted"})

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
        pending = []
        for turn_id in planned:
            record = self._records.get(turn_id)
            if record is None or str(record.get("status")) not in (
                self.TERMINAL_STATUSES
            ):
                pending.append(turn_id)
        return pending

    def dispatched_without_terminal_status(self) -> list[str]:
        return [
            turn_id
            for turn_id, record in self._records.items()
            if record.get("status") == "dispatched"
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

    def _append(self, record: dict[str, object]) -> None:
        self._records[str(record["turn_id"])] = record
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ScoringRow:
    turn_id: str
    request_excerpt: str
    published_answer_excerpt: str


def build_scoring_template(turns: list[EligibleTurn]) -> list[ScoringRow]:
    """One pre-marked row per selected turn; the human fills label + reason.

    Labels compare the revision against the pre-marked-correct published
    answer: unchanged / minor change / improved / damaged, with a short
    reason. Pre-marking (correct/not-correct) happens before any revision
    output exists and is recorded by the human on this same sheet.
    """
    rows = []
    for turn in turns:
        rows.append(
            ScoringRow(
                turn_id=turn.turn_id,
                request_excerpt=turn.request_text[:160],
                published_answer_excerpt=turn.answer_text[:160],
            )
        )
    return rows


def persist_run_artifacts(
    out_dir: Path,
    *,
    turns: list[EligibleTurn],
    ineligible: list[IneligibleTurn],
    scoring_rows: list[ScoringRow],
    selected_count: int,
) -> None:
    """Durable raw artifacts: selection record, scoring sheet, packet map.

    Everything stays local; the journal root is the only content source.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    selection = {
        "run_id": RUN_ID,
        "seed": SEED,
        "sample_size": SAMPLE_SIZE,
        "selected": selected_count,
        "eligible_turns": [
            {
                "turn_id": turn.turn_id,
                "session_id": turn.session_id,
                "user_position": turn.user_position,
                "assistant_position": turn.assistant_position,
                "timestamp": turn.timestamp,
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
        "protocol_card": PROTOCOL_CARD,
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "scoring_sheet.csv").write_text(
        _scoring_csv(scoring_rows), encoding="utf-8-sig"
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


def _scoring_csv(rows: list[ScoringRow]) -> str:
    header = "turn_id,pre_mark,request_excerpt,published_answer_excerpt,label,reason"
    lines = [header]
    for row in rows:
        lines.append(
            ",".join(
                [
                    row.turn_id,
                    "",
                    _csv_cell(row.request_excerpt),
                    _csv_cell(row.published_answer_excerpt),
                    "",
                    "",
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _csv_cell(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'
