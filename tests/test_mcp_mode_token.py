import logging
from pathlib import Path

import pytest

from jarvis.mcp_mode.token import McpTokenFileError, load_or_create_token


def test_an_existing_token_is_read_without_surrounding_whitespace(tmp_path):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_text("  stored-token\n", encoding="utf-8")

    assert load_or_create_token(token_file) == "stored-token"


def test_an_existing_token_file_is_left_unchanged(tmp_path):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_text("stored-token\n", encoding="utf-8")

    load_or_create_token(token_file)

    assert token_file.read_text(encoding="utf-8") == "stored-token\n"


def test_a_missing_token_file_is_created_with_the_returned_token(tmp_path):
    token_file = tmp_path / "mcp_mode.token"

    token = load_or_create_token(token_file)

    assert token_file.read_text(encoding="utf-8") == token


def test_a_generated_token_is_long_and_url_safe(tmp_path):
    token = load_or_create_token(tmp_path / "mcp_mode.token")

    assert len(token) >= 43
    assert token.replace("-", "").replace("_", "").isalnum()


def test_two_fresh_token_files_get_different_tokens(tmp_path):
    first = load_or_create_token(tmp_path / "first.token")
    second = load_or_create_token(tmp_path / "second.token")

    assert first != second


def test_a_created_token_is_reused_on_the_next_start(tmp_path):
    token_file = tmp_path / "mcp_mode.token"

    first_start = load_or_create_token(token_file)
    second_start = load_or_create_token(token_file)

    assert second_start == first_start


def test_missing_parent_directories_are_created(tmp_path):
    token_file = tmp_path / "secrets" / "jarvis" / "mcp_mode.token"

    token = load_or_create_token(token_file)

    assert token_file.read_text(encoding="utf-8") == token


def test_a_relative_token_path_is_relative_to_the_working_directory(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    token = load_or_create_token(Path("mcp_mode.token"))

    assert (tmp_path / "mcp_mode.token").read_text(encoding="utf-8") == token


@pytest.mark.parametrize("content", ["", "   \n\t  "])
def test_an_empty_token_file_is_a_startup_error_naming_the_file_and_config_key(
    tmp_path, content
):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_text(content, encoding="utf-8")

    with pytest.raises(McpTokenFileError) as raised:
        load_or_create_token(token_file)

    assert str(token_file) in str(raised.value)
    assert "[mcp_mode].token_file" in str(raised.value)


def test_an_empty_token_file_is_never_silently_regenerated(tmp_path):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_text("", encoding="utf-8")

    with pytest.raises(McpTokenFileError):
        load_or_create_token(token_file)

    assert token_file.read_text(encoding="utf-8") == ""


def test_an_unreadable_token_path_is_a_startup_error_naming_it_and_config_key(
    tmp_path,
):
    token_path = tmp_path / "mcp_mode.token"
    token_path.mkdir()

    with pytest.raises(McpTokenFileError) as raised:
        load_or_create_token(token_path)

    assert str(token_path) in str(raised.value)
    assert "[mcp_mode].token_file" in str(raised.value)


def test_a_token_file_that_is_not_utf8_is_an_error_that_does_not_echo_its_bytes(
    tmp_path,
):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_bytes(b"secret\xff\xfe-token")

    with pytest.raises(McpTokenFileError) as raised:
        load_or_create_token(token_file)

    assert str(token_file) in str(raised.value)
    assert "secret" not in str(raised.value)
    assert "xff" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_an_uncreatable_token_file_is_a_startup_error_naming_it_and_config_key(
    tmp_path,
):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    token_file = blocker / "mcp_mode.token"

    with pytest.raises(McpTokenFileError) as raised:
        load_or_create_token(token_file)

    assert str(token_file) in str(raised.value)
    assert "[mcp_mode].token_file" in str(raised.value)


def test_the_token_appears_in_no_log_record_when_created_or_read(tmp_path, caplog):
    token_file = tmp_path / "mcp_mode.token"
    caplog.set_level(logging.DEBUG)

    token = load_or_create_token(token_file)
    load_or_create_token(token_file)

    assert all(token not in record.getMessage() for record in caplog.records)
