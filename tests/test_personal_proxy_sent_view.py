from jarvis.personal_proxy.common.payload import DEFAULT_SYSTEM_PROMPT
from jarvis.personal_proxy.reporting.sent_view import (
    has_default_system_prompt,
    request_after_default_system_prompt,
)


def test_a_stored_default_prompt_record_yields_the_rest_of_the_text():
    stored = f"system: {DEFAULT_SYSTEM_PROMPT}\n\nuser: hello"

    assert request_after_default_system_prompt(stored) == "user: hello"


def test_a_record_that_starts_with_anything_else_yields_nothing():
    assert request_after_default_system_prompt("system: other\n\nuser: hi") is None
    assert request_after_default_system_prompt("user: hi") is None


def test_the_parse_is_pinned_for_a_system_prompt_that_embeds_a_role_line():
    """The record keeps only the joined text, so a system message equal to the
    default plus a blank line and a role line cannot be told from the default
    followed by that message. Safe while the system prompt is a constant."""
    messages = (
        ("system", DEFAULT_SYSTEM_PROMPT + "\n\nuser: x"),
        ("user", "y"),
    )
    stored = "\n\n".join(f"{role}: {content}" for role, content in messages)

    assert not has_default_system_prompt(messages)
    assert request_after_default_system_prompt(stored) == "user: x\n\nuser: y"
