from dataclasses import replace

import pytest

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.gate.topics_file import (
    MAX_TOPICS_CHARACTERS,
    TopicsFileError,
    load_topics,
)

DEFAULT = PersonalProxySettings()


def test_a_missing_default_file_means_no_topics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert load_topics(DEFAULT) == ""


def test_an_existing_default_file_is_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT.topics_file).write_text("- debts", encoding="utf-8")

    assert load_topics(DEFAULT) == "- debts"


def test_an_explicit_missing_file_is_an_error(tmp_path):
    settings = replace(DEFAULT, topics_file=str(tmp_path / "gone.txt"))

    with pytest.raises(TopicsFileError):
        load_topics(settings)


def test_an_unreadable_path_is_an_error(tmp_path):
    settings = replace(DEFAULT, topics_file=str(tmp_path))

    with pytest.raises(TopicsFileError):
        load_topics(settings)


def test_a_file_that_is_not_utf8_is_an_error_that_hides_its_content(tmp_path):
    path = tmp_path / "topics.txt"
    path.write_bytes("секрет".encode("cp1251"))

    with pytest.raises(TopicsFileError) as caught:
        load_topics(replace(DEFAULT, topics_file=str(path)))

    assert "секрет" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_a_normal_file_is_returned_as_written(tmp_path):
    path = tmp_path / "topics.txt"
    path.write_bytes("- диагноз\n- долги\n".encode())

    assert (
        load_topics(replace(DEFAULT, topics_file=str(path))) == "- диагноз\n- долги\n"
    )


def test_a_byte_order_mark_is_not_part_of_the_text(tmp_path):
    path = tmp_path / "topics.txt"
    path.write_bytes(b"\xef\xbb\xbf- debts")

    assert load_topics(replace(DEFAULT, topics_file=str(path))) == "- debts"


def test_an_empty_file_means_no_topics(tmp_path):
    path = tmp_path / "topics.txt"
    path.write_text("", encoding="utf-8")

    assert load_topics(replace(DEFAULT, topics_file=str(path))) == ""


def test_a_file_at_the_size_cap_is_read_and_one_over_is_an_error(tmp_path):
    path = tmp_path / "topics.txt"
    settings = replace(DEFAULT, topics_file=str(path))
    path.write_bytes(("я" * MAX_TOPICS_CHARACTERS).encode())

    assert len(load_topics(settings)) == MAX_TOPICS_CHARACTERS

    path.write_bytes(("я" * (MAX_TOPICS_CHARACTERS + 1)).encode())
    with pytest.raises(TopicsFileError) as caught:
        load_topics(settings)
    assert "я" not in str(caught.value)


def test_a_path_with_a_nul_is_an_error():
    with pytest.raises(TopicsFileError) as caught:
        load_topics(replace(DEFAULT, topics_file="topics\x00.txt"))

    assert caught.value.__suppress_context__


def test_no_read_error_text_reaches_the_topics_error(tmp_path):
    with pytest.raises(TopicsFileError) as caught:
        load_topics(replace(DEFAULT, topics_file=str(tmp_path)))

    assert str(tmp_path) not in str(caught.value)
    assert "Errno" not in str(caught.value)
    assert caught.value.__cause__ is None
