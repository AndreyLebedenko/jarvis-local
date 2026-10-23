"""The command parser of a typed request: pure text in, a parse result out."""

import pytest

from jarvis.personal_proxy.request_commands import (
    COMMAND_TABLE,
    Command,
    ParsedKind,
    parse_typed_request,
)


@pytest.mark.parametrize("token", ["/force", "/f"])
def test_a_known_command_with_text_is_a_command_with_that_text(token):
    parsed = parse_typed_request(f"{token} What is a relay?")

    assert parsed.kind is ParsedKind.COMMAND
    assert parsed.command is Command.FORCE
    assert parsed.text == "What is a relay?"


@pytest.mark.parametrize(
    ("typed", "expected_text"),
    [
        ("  /force   spaced out   ", "spaced out"),
        ("\t/f\tafter a tab", "after a tab"),
        ("/force\nafter a newline", "after a newline"),
        ("/force first line\nsecond line", "first line\nsecond line"),
        ("/f   a /force later in the text", "a /force later in the text"),
    ],
)
def test_whitespace_around_the_command_and_the_text_is_trimmed(typed, expected_text):
    parsed = parse_typed_request(typed)

    assert parsed.kind is ParsedKind.COMMAND
    assert parsed.text == expected_text


@pytest.mark.parametrize(
    "typed",
    ["/force", "/f", "/force   ", "  /f\n\t ", "/force ​", "/f ​​ \n"],
)
def test_a_command_without_text_is_an_empty_command(typed):
    parsed = parse_typed_request(typed)

    assert parsed.kind is ParsedKind.EMPTY_COMMAND
    assert parsed.command is Command.FORCE
    assert parsed.text == ""


@pytest.mark.parametrize(
    "typed", ["/forse hello", "/forcex hello", "/fx hello", "/FORCE hello", "/F hello"]
)
def test_a_token_that_looks_like_a_command_but_is_not_known_is_flagged(typed):
    parsed = parse_typed_request(typed)

    assert parsed.kind is ParsedKind.UNKNOWN_COMMAND
    assert parsed.command is None
    assert parsed.text == ""


@pytest.mark.parametrize("typed", ["/help", "/send now", "/etc", "/сила тут"])
def test_any_slash_and_letters_token_is_a_command_attempt(typed):
    assert parse_typed_request(typed).kind is ParsedKind.UNKNOWN_COMMAND


@pytest.mark.parametrize(
    "typed",
    [
        "/etc/hosts is a file",
        "/",
        "/ force hello",
        "//force hello",
        "/force: hello",
        "/f1 hello",
        "/ ",
        "force hello",
        "f hello",
        "Please /force this one",
        "what is /force",
    ],
)
def test_other_text_is_an_ordinary_request_returned_unchanged(typed):
    parsed = parse_typed_request(typed)

    assert parsed.kind is ParsedKind.ORDINARY
    assert parsed.command is None
    assert parsed.text == typed


def test_an_ordinary_request_keeps_its_own_whitespace():
    assert parse_typed_request("  hello  ").text == "  hello  "


def test_an_empty_text_is_an_ordinary_request():
    assert parse_typed_request("").kind is ParsedKind.ORDINARY


def test_the_command_table_maps_the_long_and_the_short_name_to_one_command():
    assert COMMAND_TABLE == {"force": Command.FORCE, "f": Command.FORCE}


def test_the_text_of_a_request_is_not_shown_by_repr():
    parsed = parse_typed_request("/force a secret text")

    assert "secret" not in repr(parsed)
    assert "secret" not in str(parsed)
