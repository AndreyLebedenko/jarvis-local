"""Deterministic grader for tasks/spike-single-pass-tts-block.md (mode 3b spike).

Reads CallRecords only. Arm B is one generation: the canvas, then one trailing
`<tts>...</tts>` block. Arms A-prod and A-eq are two requests sharing the same
pass 1 (the canvas); their pass 2 content is entirely voice.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from jarvis.audio.tts import SentenceBuffer
from manual.single_pass_tts_records import (
    LENGTH_DONE_REASON,
    Arm,
    CallRecord,
    GenerationKey,
    GenerationMetrics,
    Stage,
    StreamChunk,
    TagOutcome,
    VoiceHygiene,
)

OPEN_TAG = "<tts>"
CLOSE_TAG = "</tts>"
CODE_FENCE = "```"

_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"\*\*|__")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_LIST_MARKER_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])\s", re.MULTILINE)
_RAW_URL_RE = re.compile(r"https?://\S+|www\.\S+")

_PASS2_STAGES = {Arm.A_PROD: Stage.A_PROD_PASS2, Arm.A_EQ: Stage.A_EQ_PASS2}


# --- tag classification ---


def classify_tag(content: str, done_reason: str | None) -> TagOutcome:
    if done_reason == LENGTH_DONE_REASON:
        return TagOutcome.TRUNCATED
    opening_count = content.count(OPEN_TAG)
    if opening_count == 0:
        return TagOutcome.MISSING
    if opening_count > 1:
        return TagOutcome.MULTIPLE
    return _classify_single_block(content, content.index(OPEN_TAG))


def _classify_single_block(content: str, open_at: int) -> TagOutcome:
    if _is_inside_code_fence(content, open_at):
        return TagOutcome.IN_CODE_FENCE
    voice_start = open_at + len(OPEN_TAG)
    close_at = content.find(CLOSE_TAG, voice_start)
    if close_at < 0:
        return TagOutcome.UNCLOSED
    if content[close_at + len(CLOSE_TAG) :].strip():
        return TagOutcome.TEXT_AFTER
    if not content[voice_start:close_at].strip():
        return TagOutcome.EMPTY
    return TagOutcome.WELL_FORMED


def _is_inside_code_fence(content: str, position: int) -> bool:
    line_start = content.rfind("\n", 0, position) + 1
    preceding_lines = content[:line_start].splitlines()
    fence_lines = sum(1 for line in preceding_lines if _is_fence_line(line))
    return fence_lines % 2 == 1


def _is_fence_line(line: str) -> bool:
    return line.strip().startswith(CODE_FENCE)


def b_canvas(content: str) -> str:
    return content.partition(OPEN_TAG)[0].strip()


def b_voice(content: str, done_reason: str | None) -> str | None:
    if classify_tag(content, done_reason) is not TagOutcome.WELL_FORMED:
        return None
    after_open = content.partition(OPEN_TAG)[2]
    return after_open.partition(CLOSE_TAG)[0].strip()


# --- time to first spoken sentence ---


def pass2_first_sentence_seconds(chunks: Sequence[StreamChunk]) -> float | None:
    buffer = SentenceBuffer()
    for chunk in chunks:
        if buffer.feed(chunk.content):
            return chunk.t
    if chunks and buffer.flush():
        return chunks[-1].t
    return None


@dataclass(frozen=True)
class _VoiceRegion:
    start: int
    end: int
    closed: bool

    @property
    def closed_at(self) -> int:
        return self.end + len(CLOSE_TAG)


def block_first_sentence_seconds(chunks: Sequence[StreamChunk]) -> float | None:
    content = "".join(chunk.content for chunk in chunks)
    region = _voice_region(content)
    if region is None:
        return None
    buffer = SentenceBuffer()
    for t, chunk_start, chunk_end in _positioned(chunks):
        voice = content[max(region.start, chunk_start) : min(region.end, chunk_end)]
        if voice and buffer.feed(voice):
            return t
        if region.closed and chunk_end >= region.closed_at:
            return t if buffer.flush() else None
    return None


def _voice_region(content: str) -> _VoiceRegion | None:
    open_at = content.find(OPEN_TAG)
    if open_at < 0:
        return None
    start = open_at + len(OPEN_TAG)
    close_at = content.find(CLOSE_TAG, start)
    if close_at < 0:
        return _VoiceRegion(start, len(content), closed=False)
    return _VoiceRegion(start, close_at, closed=True)


def _positioned(chunks: Sequence[StreamChunk]) -> Iterator[tuple[float, int, int]]:
    offset = 0
    for chunk in chunks:
        start, offset = offset, offset + len(chunk.content)
        yield chunk.t, start, offset


# --- voice hygiene ---


def voice_hygiene(text: str) -> VoiceHygiene:
    lines = text.splitlines()
    return VoiceHygiene(
        markdown_markers=_count_markdown_markers(text),
        table_pipe_lines=sum(1 for line in lines if line.count("|") >= 2),
        code_fences=sum(1 for line in lines if _is_fence_line(line)),
        raw_urls=len(_RAW_URL_RE.findall(text)),
    )


def _count_markdown_markers(text: str) -> int:
    patterns = (_HEADING_RE, _EMPHASIS_RE, _INLINE_CODE_RE, _LIST_MARKER_RE)
    return sum(len(pattern.findall(text)) for pattern in patterns)


# --- per-generation metrics ---


def grade_generations(records: Iterable[CallRecord]) -> list[GenerationMetrics]:
    metrics = [
        metric
        for key, stages in _group_by_key(records).items()
        for metric in _grade_generation(key, stages)
    ]
    return sorted(metrics, key=lambda metric: (metric.key, metric.arm))


def _group_by_key(
    records: Iterable[CallRecord],
) -> dict[GenerationKey, dict[Stage, CallRecord]]:
    groups: dict[GenerationKey, dict[Stage, CallRecord]] = {}
    for record in records:
        stages = groups.setdefault(record.key, {})
        if record.stage in stages:
            raise ValueError(f"duplicate {record.stage} record for {record.key.slug}")
        stages[record.stage] = record
    return groups


def _grade_generation(
    key: GenerationKey, stages: dict[Stage, CallRecord]
) -> list[GenerationMetrics]:
    _require_pass1_for_every_pass2(key, stages)
    metrics = []
    if Stage.B in stages:
        metrics.append(_grade_b(stages[Stage.B]))
    if Stage.A_PASS1 in stages:
        pass1 = stages[Stage.A_PASS1]
        metrics.append(_grade_two_pass(Arm.A_PROD, pass1, stages))
        if Stage.A_EQ_PASS2 in stages:
            metrics.append(_grade_two_pass(Arm.A_EQ, pass1, stages))
    return metrics


def _require_pass1_for_every_pass2(
    key: GenerationKey, stages: dict[Stage, CallRecord]
) -> None:
    if Stage.A_PASS1 in stages:
        return
    orphans = [stage for stage in _PASS2_STAGES.values() if stage in stages]
    if orphans:
        raise ValueError(f"{orphans[0]} record without a_pass1 for {key.slug}")


def _grade_b(record: CallRecord) -> GenerationMetrics:
    content = record.content
    outcome = classify_tag(content, record.done_reason)
    voice = b_voice(content, record.done_reason)
    first_sentence = (
        block_first_sentence_seconds(record.chunks)
        if outcome is TagOutcome.WELL_FORMED
        else None
    )
    return GenerationMetrics(
        key=record.key,
        arm=Arm.B,
        canvas_text=b_canvas(content),
        voice_text=voice,
        first_sentence_seconds=first_sentence,
        total_wall_seconds=record.wall_seconds,
        eval_count_sum=record.eval_count or 0,
        runaway=_is_runaway(record),
        hygiene=_hygiene_or_none(voice),
        tag_outcome=outcome,
    )


def _grade_two_pass(
    arm: Arm, pass1: CallRecord, stages: dict[Stage, CallRecord]
) -> GenerationMetrics:
    pass2 = stages.get(_PASS2_STAGES[arm])
    voice = (pass2.content.strip() or None) if pass2 is not None else None
    return GenerationMetrics(
        key=pass1.key,
        arm=arm,
        canvas_text=pass1.content.strip(),
        voice_text=voice,
        first_sentence_seconds=_two_pass_first_sentence(pass1, pass2),
        total_wall_seconds=_two_pass_wall(pass1, pass2),
        eval_count_sum=sum(
            record.eval_count or 0 for record in (pass1, pass2) if record is not None
        ),
        runaway=pass2 is None or _is_runaway(pass1) or _is_runaway(pass2),
        hygiene=_hygiene_or_none(voice),
    )


def _two_pass_first_sentence(
    pass1: CallRecord, pass2: CallRecord | None
) -> float | None:
    if pass2 is None:
        return None
    within_pass2 = pass2_first_sentence_seconds(pass2.chunks)
    if within_pass2 is None:
        return None
    return (pass2.started_at - pass1.started_at) + within_pass2


def _two_pass_wall(pass1: CallRecord, pass2: CallRecord | None) -> float:
    if pass2 is None:
        return pass1.wall_seconds
    return pass2.started_at + pass2.wall_seconds - pass1.started_at


def _is_runaway(record: CallRecord) -> bool:
    return record.hit_length_cap or not record.content.strip()


def _hygiene_or_none(voice: str | None) -> VoiceHygiene | None:
    return voice_hygiene(voice) if voice is not None else None
