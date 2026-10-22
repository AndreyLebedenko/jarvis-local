"""The doubt trigger of the confirmation exchange on the production check stage
(handoff B of task v2.1.0-8): the asked share, the real errors covered, and the
errors whose wrong fragment is named, judged by the rule frozen in the task card
on 2026-10-22 before the run. Pure; the harness supplies the observations.

Rule: keep `[personal_proxy].doubt_min_listed = 1` if the asked share is at most
0.27 (the 25% budget plus 2 points), at least 6 of the 7 real errors are asked
about, and at least 4 of 7 name the wrong fragment. Otherwise the numbers go to
the owner; the threshold is not tuned in a loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from jarvis.core.config import Settings
from manual.personal_proxy.address_labels import base_id
from manual.personal_proxy.ask_policy import covers

MAX_ASKED_SHARE = 0.27
MIN_COVERED = 6
MIN_NAMED = 4
EXPECTED_RECORDINGS = 60
EXPECTED_ERRORS = 7
FROZEN_DOUBT_MIN_LISTED = 1
FROZEN_KV_CACHE_TYPE = "q8_0"


class Verdict(StrEnum):
    KEEP = "keep"
    NUMBERS_TO_OWNER = "numbers_to_owner"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class Observation:
    subject_id: str
    error: bool
    asked: bool
    fragments: tuple[str, ...]


@dataclass(frozen=True)
class TriggerResult:
    total: int
    asked: int
    errors: int
    covered: int
    named: int
    verdict: Verdict

    @property
    def asked_share(self) -> float:
        return self.asked / self.total if self.total else 0.0


def evaluate(observations: Sequence[Observation]) -> TriggerResult:
    errors = [o for o in observations if o.error]
    covered = [o for o in errors if o.asked]
    named = [o for o in covered if covers(list(o.fragments), base_id(o.subject_id))]
    asked = sum(o.asked for o in observations)
    total = len(observations)
    verdict = _verdict_of(total, asked, len(errors), len(covered), len(named))
    return TriggerResult(total, asked, len(errors), len(covered), len(named), verdict)


def _verdict_of(
    total: int, asked: int, errors: int, covered: int, named: int
) -> Verdict:
    if total != EXPECTED_RECORDINGS or errors != EXPECTED_ERRORS:
        return Verdict.NOT_COMPARABLE
    within_rule = (
        asked / total <= MAX_ASKED_SHARE
        and covered >= MIN_COVERED
        and named >= MIN_NAMED
    )
    return Verdict.KEEP if within_rule else Verdict.NUMBERS_TO_OWNER


def render(result: TriggerResult) -> str:
    return "\n".join(
        [
            f"recordings: {result.total} (the rule is defined on "
            f"{EXPECTED_RECORDINGS}); real errors: {result.errors} "
            f"(defined on {EXPECTED_ERRORS})",
            f"asked: {result.asked}/{result.total} = {result.asked_share:.3f} "
            f"(limit {MAX_ASKED_SHARE})",
            f"real errors asked about: {result.covered} of {result.errors} "
            f"(at least {MIN_COVERED} of {EXPECTED_ERRORS})",
            f"errors whose wrong fragment is named: {result.named} of "
            f"{result.errors} (at least {MIN_NAMED} of {EXPECTED_ERRORS})",
            f"verdict: {result.verdict.value}",
            "keep: doubt_min_listed stays 1. numbers_to_owner or not_comparable: "
            "send these numbers to the owner; do not tune doubt_min_listed in a "
            "loop.",
        ]
    )


def config_problems(settings: Settings) -> list[str]:
    """What differs from the configuration the rule was frozen for."""
    problems = []
    if settings.backend.flash_attention is not True:
        problems.append("[backend].flash_attention must be true (the spikes' value)")
    if settings.backend.kv_cache_type != FROZEN_KV_CACHE_TYPE:
        problems.append(
            f'[backend].kv_cache_type must be "{FROZEN_KV_CACHE_TYPE}" '
            "(the spikes' value)"
        )
    if settings.personal_proxy.doubt_min_listed != FROZEN_DOUBT_MIN_LISTED:
        problems.append(
            f"[personal_proxy].doubt_min_listed must be {FROZEN_DOUBT_MIN_LISTED} "
            "(the rule is defined for it)"
        )
    return problems
