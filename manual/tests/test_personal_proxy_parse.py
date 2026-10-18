import json

import pytest

from manual.personal_proxy.corpus import Verdict
from manual.personal_proxy.parse import (
    FailureClass,
    ParsedOutput,
    ParseFailure,
    parse_sanitize_output,
)


def _document(**overrides):
    base = {
        "verdict": "send",
        "reason": "",
        "raw_transcript": "позвони Марине",
        "sanitized_text": "позвони <PERSON_1>",
        "mapping": {"<PERSON_1>": "Марина"},
    }
    return json.dumps({**base, **overrides}, ensure_ascii=False)


def _parse(text, done_reason="stop", require_raw_transcript=True):
    return parse_sanitize_output(
        text, done_reason, require_raw_transcript=require_raw_transcript
    )


def test_valid_output_is_parsed_into_fields():
    parsed = _parse(_document())

    assert parsed == ParsedOutput(
        verdict=Verdict.SEND,
        reason="",
        raw_transcript="позвони Марине",
        sanitized_text="позвони <PERSON_1>",
        mapping={"<PERSON_1>": "Марина"},
    )


def test_surrounding_whitespace_is_allowed():
    assert isinstance(_parse("\n  " + _document() + "  \n"), ParsedOutput)


def test_raw_transcript_is_not_required_for_the_text_only_step():
    document = json.loads(_document())
    del document["raw_transcript"]

    parsed = _parse(json.dumps(document), require_raw_transcript=False)

    assert isinstance(parsed, ParsedOutput)
    assert parsed.raw_transcript is None


def test_length_cap_wins_over_whatever_text_arrived():
    assert _parse(_document(), done_reason="length") == ParseFailure(
        FailureClass.TRUNCATED
    )


def test_blank_output_is_empty():
    assert _parse("  \n") == ParseFailure(FailureClass.EMPTY)


def test_plain_text_is_no_json():
    assert _parse("Привет, это не JSON") == ParseFailure(FailureClass.NO_JSON)


def test_broken_json_is_no_json():
    assert _parse('{"verdict": "send",') == ParseFailure(FailureClass.NO_JSON)


def test_json_inside_a_code_fence_is_extra_prose():
    fenced = "```json\n" + _document() + "\n```"

    assert _parse(fenced) == ParseFailure(FailureClass.EXTRA_PROSE)


def test_json_after_a_sentence_is_extra_prose():
    assert _parse("Вот результат: " + _document()) == ParseFailure(
        FailureClass.EXTRA_PROSE
    )


def test_top_level_array_is_wrong_type():
    assert _parse("[1, 2]") == ParseFailure(
        FailureClass.WRONG_TYPE, "top level is not an object"
    )


@pytest.mark.parametrize("name", ["verdict", "reason", "sanitized_text", "mapping"])
def test_each_required_field_is_enforced(name):
    document = json.loads(_document())
    del document[name]

    assert _parse(json.dumps(document)) == ParseFailure(
        FailureClass.MISSING_FIELD, name
    )


def test_missing_raw_transcript_fails_only_when_required():
    document = json.loads(_document())
    del document["raw_transcript"]

    assert _parse(json.dumps(document)) == ParseFailure(
        FailureClass.MISSING_FIELD, "raw_transcript"
    )


def test_unknown_verdict_is_bad_verdict():
    assert _parse(_document(verdict="maybe")) == ParseFailure(
        FailureClass.BAD_VERDICT, "maybe"
    )


def test_non_string_verdict_is_wrong_type():
    assert _parse(_document(verdict=1)) == ParseFailure(
        FailureClass.WRONG_TYPE, "verdict"
    )


def test_non_string_text_field_is_wrong_type():
    assert _parse(_document(sanitized_text=["a"])) == ParseFailure(
        FailureClass.WRONG_TYPE, "sanitized_text"
    )


def test_mapping_with_non_string_value_is_wrong_type():
    assert _parse(_document(mapping={"<PERSON_1>": 5})) == ParseFailure(
        FailureClass.WRONG_TYPE, "mapping"
    )


def test_extra_keys_are_ignored():
    assert isinstance(_parse(_document(note="hello")), ParsedOutput)
