from dataclasses import replace

import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.gate.public_names_file import (
    MAX_PUBLIC_NAMES_CHARACTERS,
    PublicNamesFileError,
    load_public_names,
)

DEFAULT = PersonalProxySettings()


def _settings(path):
    return replace(DEFAULT, public_names_file=str(path))


def test_a_missing_default_file_means_no_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert load_public_names(DEFAULT) == ""


def test_an_existing_default_file_is_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT.public_names_file).write_text("Einstein", encoding="utf-8")

    assert load_public_names(DEFAULT) == "Einstein"


def test_an_explicit_missing_file_is_an_error(tmp_path):
    with pytest.raises(PublicNamesFileError):
        load_public_names(_settings(tmp_path / "gone.txt"))


def test_an_unreadable_path_is_an_error(tmp_path):
    with pytest.raises(PublicNamesFileError):
        load_public_names(_settings(tmp_path))


def test_a_file_that_is_not_utf8_is_an_error_that_hides_its_content(tmp_path):
    path = tmp_path / "names.txt"
    path.write_bytes("Эйнштейн".encode("cp1251"))

    with pytest.raises(PublicNamesFileError) as caught:
        load_public_names(_settings(path))

    assert "Эйнштейн" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_a_byte_order_mark_is_not_part_of_the_first_name(tmp_path):
    path = tmp_path / "names.txt"
    path.write_bytes(b"\xef\xbb\xbfEinstein")

    assert load_public_names(_settings(path)) == "Einstein"


def test_an_empty_file_means_no_names(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("", encoding="utf-8")

    assert load_public_names(_settings(path)) == ""


def test_comment_and_blank_lines_are_dropped_and_each_name_is_stripped(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text(
        "# scientists\n\n  Альберт Эйнштейн  \n   # indented comment\r\n"
        "\t\r\nNikola Tesla\n",
        encoding="utf-8",
    )

    assert load_public_names(_settings(path)) == "Альберт Эйнштейн\nNikola Tesla"


def test_a_file_of_only_comments_and_blanks_means_no_names(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("# nobody yet\n\n   \n", encoding="utf-8")

    assert load_public_names(_settings(path)) == ""


def test_a_file_at_the_size_cap_is_read_and_one_over_is_an_error(tmp_path):
    path = tmp_path / "names.txt"
    settings = _settings(path)
    path.write_bytes(("я" * MAX_PUBLIC_NAMES_CHARACTERS).encode())

    assert len(load_public_names(settings)) == MAX_PUBLIC_NAMES_CHARACTERS

    path.write_bytes(("я" * (MAX_PUBLIC_NAMES_CHARACTERS + 1)).encode())
    with pytest.raises(PublicNamesFileError) as caught:
        load_public_names(settings)
    assert "я" not in str(caught.value)


def test_the_size_cap_counts_the_raw_text_including_comments(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("#" * MAX_PUBLIC_NAMES_CHARACTERS + "\nx", encoding="utf-8")

    with pytest.raises(PublicNamesFileError):
        load_public_names(_settings(path))


def test_a_path_with_a_nul_is_an_error():
    with pytest.raises(PublicNamesFileError) as caught:
        load_public_names(_settings("names\x00.txt"))

    assert caught.value.__suppress_context__


def test_no_read_error_text_reaches_the_names_error(tmp_path):
    with pytest.raises(PublicNamesFileError) as caught:
        load_public_names(_settings(tmp_path))

    assert str(tmp_path) not in str(caught.value)
    assert "Errno" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("problem", ["missing", "unreadable", "too_long"])
def test_no_error_message_calls_the_names_file_a_topics_file(tmp_path, problem):
    path = tmp_path / "names.txt"
    if problem == "unreadable":
        path = tmp_path
    if problem == "too_long":
        path.write_text("я" * (MAX_PUBLIC_NAMES_CHARACTERS + 1), encoding="utf-8")

    with pytest.raises(PublicNamesFileError) as caught:
        load_public_names(_settings(path if problem != "missing" else tmp_path / "x"))

    assert "public names file" in str(caught.value)
    assert "topics" not in str(caught.value)
