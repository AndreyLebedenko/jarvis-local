"""When to ask the owner to confirm, and what to point at (spike v2.1.0-9 follow-up).

A flag now means "ask a confirmation question with the doubts named", not "refuse",
so the measures are: how many requests would be asked about (the ask rate), how
many real errors the asking covers, and whether the named doubts include the wrong
fragment. Pure; the harness reads the recorded data.
"""

from __future__ import annotations

from dataclasses import dataclass

from manual.personal_proxy.confidence_report import Signals, flagged_by

MAX_ASK_RATE = 0.25

Rule = tuple[tuple[str, float], ...]

CANDIDATE_RULES: dict[str, Rule] = {
    "J3 >= 1": (("J3", 1.0),),
    "S2 >= 0.6": (("S2", 0.6),),
    "S1 >= 3": (("S1", 3.0),),
    "S3a >= 0.5": (("S3a", 0.5),),
    "H = S2 >= 0.6 or J3 >= 1": (("S2", 0.6), ("J3", 1.0)),
    "S1 >= 3 or J3 >= 1": (("S1", 3.0), ("J3", 1.0)),
    "S1 >= 3 or S2 >= 0.6 or J3 >= 1": (("S1", 3.0), ("S2", 0.6), ("J3", 1.0)),
    "S1 >= 3 or S2 >= 0.6 or J3 >= 1 or S3a >= 0.5": (
        ("S1", 3.0),
        ("S2", 0.6),
        ("J3", 1.0),
        ("S3a", 0.5),
    ),
}

# Strings that identify the wrong fragment of each real error, chosen by the agent
# after reading the outputs (lowercase substrings).
WRONG_FRAGMENT_KEYS: dict[str, tuple[str, ...]] = {
    "id_letter_long": ("альфтеррейт", "альфатрейд", "ооо"),
    "id_two_people_phone": ("912", "345", "607", "60 78"),
    "m_github": ("dvolkov", "gmail", "sobaka"),
    "m_trade_house": ("info", "trade", "sobak", "marina", "kuznet"),
    "n_short_translate": ("apple", "translate", "яблок", "переведи"),
    "v2_email_underscore": ("smirnov", "смирнов", "alex", "алекс", "pochta", "почта"),
}


@dataclass(frozen=True)
class AskResult:
    name: str
    asked: int
    total: int
    caught: int
    bad: int
    missed: tuple[str, ...]

    @property
    def ask_rate(self) -> float:
        return self.asked / self.total if self.total else 0.0

    @property
    def recall(self) -> float:
        return self.caught / self.bad if self.bad else 0.0

    @property
    def within_budget(self) -> bool:
        return self.ask_rate <= MAX_ASK_RATE


def evaluate_rule(name: str, rule: Rule, recordings: list[Signals]) -> AskResult:
    asked = [r for r in recordings if flagged_by(r, rule)]
    bad = [r for r in recordings if r.bad]
    missed = tuple(r.subject_id for r in bad if not flagged_by(r, rule))
    return AskResult(
        name,
        len(asked),
        len(recordings),
        len(bad) - len(missed),
        len(bad),
        missed,
    )


def evaluate_candidates(recordings: list[Signals]) -> list[AskResult]:
    return [evaluate_rule(n, rule, recordings) for n, rule in CANDIDATE_RULES.items()]


def covers(doubts: list[str], base_id: str) -> bool:
    keys = WRONG_FRAGMENT_KEYS.get(base_id, ())
    return any(key in doubt.lower() for doubt in doubts for key in keys)


def differing_items(projections: list[frozenset[str]]) -> list[str]:
    """Projection items that not every sample agrees on."""
    if not projections:
        return []
    everyone = frozenset.intersection(*projections)
    anyone = frozenset.union(*projections)
    return sorted(anyone - everyone)


def weak_words(words: list[tuple[str, float]], threshold: float = 0.5) -> list[str]:
    return [w.strip() for w, p in words if p < threshold]
