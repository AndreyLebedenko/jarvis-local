"""Deterministic check of a restored sentence by template alignment.

The sentence is cut at its known placeholders into literal segments and value
slots. The model's output must be exactly the literal segments with, in each
slot, a form of that placeholder's original: the same number of words, each
word matching the original's word (by stem, a bounded ending and the same
first-letter case for a Cyrillic word of three or more letters, exactly
otherwise), and the same separators between them. An unknown placeholder is
part of a literal segment and so must stay."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from jarvis.personal_proxy.placeholders import ANY_PLACEHOLDER
from jarvis.personal_proxy.text import (
    MIN_STEM_LENGTH,
    TokenSpan,
    stem_present,
    token_spans,
)

MAX_MODEL_PLACEHOLDERS = 8
MAX_MODEL_SENTENCE_CHARS = 1000
_SEARCH_BUDGET = 20_000
MAX_ENDING_GROWTH = 3


class RestorationRule(Enum):
    PLACEHOLDER_LEFT = "placeholder_left"
    LITERAL_CHANGED = "literal_changed"
    BAD_SLOT = "bad_slot"


@dataclass(frozen=True)
class _Template:
    literals: list[str]
    originals: list[str]
    keys: list[str]


def _template(sentence: str, entries: Mapping[str, str]) -> _Template:
    literals = [""]
    originals: list[str] = []
    keys: list[str] = []
    last = 0
    for found in ANY_PLACEHOLDER.finditer(sentence):
        literals[-1] += sentence[last : found.start()]
        last = found.end()
        if found.group() in entries:
            originals.append(entries[found.group()])
            keys.append(found.group())
            literals.append("")
        else:
            literals[-1] += found.group()
    literals[-1] += sentence[last:]
    return _Template(literals, originals, keys)


def fits_model_limits(sentence: str, entries: Mapping[str, str]) -> bool:
    slots = sum(1 for found in ANY_PLACEHOLDER.findall(sentence) if found in entries)
    return slots <= MAX_MODEL_PLACEHOLDERS and len(sentence) <= MAX_MODEL_SENTENCE_CHARS


def restoration_is_valid(
    sentence: str, entries: Mapping[str, str], output: str
) -> bool:
    template = _template(sentence, entries)
    return _aligns(
        template,
        output,
        lambda index, text: _slot_matches(text, template.originals[index]),
    )


def failed_rules(
    sentence: str, entries: Mapping[str, str], output: str
) -> list[RestorationRule]:
    template = _template(sentence, entries)
    if _aligns(
        template,
        output,
        lambda index, text: _slot_matches(text, template.originals[index]),
    ):
        return []
    rules = []
    if any(key in output for key in template.keys):
        rules.append(RestorationRule.PLACEHOLDER_LEFT)
    if _aligns(template, output, lambda index, text: True):
        rules.append(RestorationRule.BAD_SLOT)
    else:
        rules.append(RestorationRule.LITERAL_CHANGED)
    return rules


def _aligns(
    template: _Template, output: str, slot_ok: Callable[[int, str], bool]
) -> bool:
    literals = template.literals
    slots = len(template.originals)
    if slots == 0:
        return output == literals[0]
    first, last = literals[0], literals[-1]
    end = len(output) - len(last)
    if not output.startswith(first) or end < len(first) or not output.endswith(last):
        return False
    return _Search(literals, output, end, slot_ok).run(0, len(first))


class _Search:
    """Depth-first choice of where each slot ends, with a step budget so that
    no output can make the check slow; running out of budget is a failure."""

    def __init__(
        self,
        literals: list[str],
        output: str,
        end: int,
        slot_ok: Callable[[int, str], bool],
    ) -> None:
        self._literals = literals
        self._output = output
        self._end = end
        self._slot_ok = slot_ok
        self._budget = _SEARCH_BUDGET

    def run(self, index: int, start: int) -> bool:
        if index == len(self._literals) - 2:
            return self._try(index, start, self._end, None)
        literal = self._literals[index + 1]
        for stop in self._stops(literal, start):
            if self._budget <= 0:
                return False
            if self._try(index, start, stop, literal):
                return True
        return False

    def _try(self, index: int, start: int, stop: int, literal: str | None) -> bool:
        self._budget -= 1
        if stop <= start or not self._slot_ok(index, self._output[start:stop]):
            return False
        if literal is None:
            return True
        return self.run(index + 1, stop + len(literal))

    def _stops(self, literal: str, start: int):
        limit = self._end
        if not literal:
            yield from range(start + 1, limit + 1)
            return
        stop = self._output.find(literal, start + 1)
        while stop != -1 and stop <= limit:
            yield stop
            stop = self._output.find(literal, stop + 1)


def _gaps(text: str, spans: list[TokenSpan]) -> list[str]:
    edges = [0, *(edge for span in spans for edge in (span.start, span.end)), len(text)]
    return [text[edges[i] : edges[i + 1]] for i in range(0, len(edges), 2)]


def _is_cyrillic_word(word: str) -> bool:
    return word.isalpha() and all("Ѐ" <= letter <= "ӿ" for letter in word)


def _word_matches(original: str, candidate: str) -> bool:
    """Only a Cyrillic word of a few letters can change its ending, so only it
    is matched by stem, with a bounded ending and the same first-letter case;
    anything else (Latin names, e-mail parts, digits, short words) is exact."""
    if not _is_cyrillic_word(original) or len(original) < MIN_STEM_LENGTH:
        return original == candidate
    return (
        stem_present(_fold(original), [_fold(candidate)])
        and len(candidate) <= len(original) + MAX_ENDING_GROWTH
        and original[0].isupper() == candidate[0].isupper()
    )


def _fold(word: str) -> str:
    return word.casefold().replace("ё", "е")


def _raw_words(text: str, spans: list[TokenSpan]) -> list[str]:
    return [text[span.start : span.end] for span in spans]


def _slot_matches(captured: str, original: str) -> bool:
    original_spans = token_spans(original)
    if not original_spans:
        return captured == original
    captured_spans = token_spans(captured)
    if len(captured_spans) != len(original_spans):
        return False
    if _gaps(captured, captured_spans) != _gaps(original, original_spans):
        return False
    return all(
        _word_matches(o, c)
        for o, c in zip(
            _raw_words(original, original_spans),
            _raw_words(captured, captured_spans),
            strict=True,
        )
    )
