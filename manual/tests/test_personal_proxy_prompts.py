import json

from manual.personal_proxy_parse import ParsedOutput, parse_sanitize_output
from manual.personal_proxy_prompts import (
    COMBINED_SCHEMA,
    COMBINED_SYSTEM_USER_TURN,
    TEXT_SCHEMA,
    combined_system_messages,
    combined_user_messages,
    prompts_fingerprint,
    sanitize_text_messages,
)

TOPICS = "- test topic: gardening"


def test_combined_user_arm_has_no_system_message_and_carries_everything():
    messages = combined_user_messages(TOPICS)

    assert [m["role"] for m in messages] == ["user"]
    content = messages[0]["content"]
    assert "gardening" in content
    assert "raw_transcript" in content
    assert "attached audio" in content


def test_combined_system_arm_keeps_rules_in_system_and_a_short_user_turn():
    messages = combined_system_messages(TOPICS)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "gardening" in messages[0]["content"]
    assert messages[1]["content"] == COMBINED_SYSTEM_USER_TURN


def test_text_step_has_no_audio_wording_and_no_raw_transcript_field():
    messages = sanitize_text_messages("позвони Марине", TOPICS)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "raw_transcript" not in messages[0]["content"]
    assert "attached audio" not in messages[0]["content"]
    assert messages[1]["content"].endswith("позвони Марине")


def test_no_template_marker_is_left_unfilled():
    for messages in (
        combined_user_messages(TOPICS),
        combined_system_messages(TOPICS),
        sanitize_text_messages("x", TOPICS),
    ):
        assert all("{topics}" not in m["content"] for m in messages)


def test_default_topics_come_from_the_frozen_topics_file():
    assert "medical" in combined_user_messages()[0]["content"]


def test_schema_required_fields_match_what_the_parser_demands():
    complete = {
        "verdict": "send",
        "reason": "",
        "raw_transcript": "t",
        "sanitized_text": "s",
        "mapping": {},
    }
    for schema, with_raw in ((COMBINED_SCHEMA, True), (TEXT_SCHEMA, False)):
        document = {name: complete[name] for name in schema["required"]}
        parsed = parse_sanitize_output(
            json.dumps(document), "stop", require_raw_transcript=with_raw
        )
        assert isinstance(parsed, ParsedOutput)
        for name in schema["required"]:
            trimmed = {k: v for k, v in document.items() if k != name}
            assert not isinstance(
                parse_sanitize_output(
                    json.dumps(trimmed), "stop", require_raw_transcript=with_raw
                ),
                ParsedOutput,
            )


def test_fingerprint_is_stable_and_hex():
    assert prompts_fingerprint() == prompts_fingerprint()
    assert len(prompts_fingerprint()) == 64
