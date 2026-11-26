from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tools.deployment_plan import DeploymentPlanError
from tools.deployment_toml import (
    remove_table,
    remove_table_strings,
    set_table_strings,
)

ORIGIN = Path("config.toml")


def parsed(text: str) -> dict[str, object]:
    return tomllib.loads(text)


def test_an_absent_table_is_appended_after_a_blank_line() -> None:
    source = '# Example\n[ui]\nlanguage = "en"\n'

    result = set_table_strings(source, "brand", {"name": "Work"}, ORIGIN)

    assert result == source + '\n[brand]\nname = "Work"\n'


def test_an_absent_table_in_an_empty_file_has_no_leading_blank_line() -> None:
    assert set_table_strings("", "brand", {"name": "Work"}, ORIGIN) == (
        '[brand]\nname = "Work"\n'
    )


def test_appending_adds_the_missing_final_newline() -> None:
    result = set_table_strings('[ui]\nlanguage = "en"', "brand", {"name": "W"}, ORIGIN)

    assert result == '[ui]\nlanguage = "en"\n\n[brand]\nname = "W"\n'


def test_appending_uses_the_line_ending_of_the_file() -> None:
    source = '[ui]\r\nlanguage = "en"\r\n'

    result = set_table_strings(
        source, "brand", {"name": "W", "accent": "#112233"}, ORIGIN
    )

    assert result == source + '\r\n[brand]\r\nname = "W"\r\naccent = "#112233"\r\n'
    assert "\n" not in result.replace("\r\n", "")


def test_existing_keys_are_replaced_in_place_and_comments_survive() -> None:
    source = (
        "# top\n"
        "[brand]  # identity\n"
        'name = "Old"  # the name\n'
        "# about the accent\n"
        "accent = '#000000'\n"
        '[ui]\nlanguage = "en"\n'
    )

    result = set_table_strings(
        source, "brand", {"name": "New", "accent": "#FFFFFF"}, ORIGIN
    )

    assert result == (
        "# top\n"
        "[brand]  # identity\n"
        'name = "New"  # the name\n'
        "# about the accent\n"
        'accent = "#FFFFFF"\n'
        '[ui]\nlanguage = "en"\n'
    )


def test_missing_keys_are_inserted_right_after_the_header() -> None:
    source = '[brand]\nname = "Old"\n[ui]\nlanguage = "en"\n'

    result = set_table_strings(
        source, "brand", {"name": "Old", "monogram": "Z"}, ORIGIN
    )

    assert parsed(result) == {
        "brand": {"name": "Old", "monogram": "Z"},
        "ui": {"language": "en"},
    }
    assert result.startswith('[brand]\nmonogram = "Z"\nname = "Old"\n')


def test_an_unchanged_value_leaves_the_file_byte_identical() -> None:
    source = '[brand]\nname = "Same"   # keep\n'

    assert set_table_strings(source, "brand", {"name": "Same"}, ORIGIN) == source


def test_a_header_at_the_end_of_a_file_without_a_final_newline_gets_one() -> None:
    result = set_table_strings("[brand]", "brand", {"name": "W"}, ORIGIN)

    assert parsed(result) == {"brand": {"name": "W"}}


FAKE_HEADER_FIRST = (
    '[prompts]\ntext = """\n[brand]\nname = "fake"\n"""\n[brand]\nname = "Old"\n'
)


def test_a_header_line_inside_a_multiline_string_is_ignored() -> None:
    for values in ({"name": "Real"}, {"name": "Old", "monogram": "R"}):
        result = set_table_strings(FAKE_HEADER_FIRST, "brand", values, ORIGIN)

        assert parsed(result) == {
            "prompts": {"text": '[brand]\nname = "fake"\n'},
            "brand": values,
        }


def test_removal_skips_a_header_line_inside_a_multiline_string() -> None:
    result = remove_table(FAKE_HEADER_FIRST, "brand", ORIGIN)

    assert parsed(result) == {"prompts": {"text": '[brand]\nname = "fake"\n'}}


@pytest.mark.parametrize(
    "name",
    ['Say "hi"', "back\\slash", "50% & <b>", "Работа", "tab\tname", "x" * 32],
)
def test_hostile_values_round_trip_through_toml(name: str) -> None:
    for source in ("", '[brand]\nname = "Old"\n'):
        result = set_table_strings(source, "brand", {"name": name}, ORIGIN)

        assert parsed(result)["brand"] == {"name": name}


@pytest.mark.parametrize(
    "source",
    [
        'brand = {name = "Old"}',
        'brand.name = "Old"',
        '["brand"]\nname = "Old"',
        '[brand]\nname = """Old"""',
    ],
)
def test_unsupported_forms_are_refused_naming_the_table_and_file(source: str) -> None:
    with pytest.raises(DeploymentPlanError, match=r"Cannot rewrite \[brand\].*config"):
        set_table_strings(source, "brand", {"name": "New"}, ORIGIN)


def test_an_unparsable_file_is_refused_naming_the_file() -> None:
    with pytest.raises(DeploymentPlanError, match="Cannot parse config.toml"):
        set_table_strings("[broken", "brand", {"name": "W"}, ORIGIN)


def test_removing_a_table_keeps_everything_else_including_comments() -> None:
    source = (
        '# top\n[ui]\nlanguage = "en"  # lang\n\n'
        '[brand]\nname = "W"\n# inside\naccent = "#112233"\n\n'
        '[files]\nx = "y"\n'
    )

    result = remove_table(source, "brand", ORIGIN)

    assert result == '# top\n[ui]\nlanguage = "en"  # lang\n\n[files]\nx = "y"\n'


def test_removing_the_last_table_removes_its_separating_blank_line() -> None:
    source = '[ui]\nlanguage = "en"\n\n[brand]\nname = "W"\n'

    assert remove_table(source, "brand", ORIGIN) == '[ui]\nlanguage = "en"\n'


def test_appending_then_removing_restores_the_original() -> None:
    source = '# Example\n[ui]\nlanguage = "en"\n'
    appended = set_table_strings(source, "brand", {"name": "W"}, ORIGIN)

    assert remove_table(appended, "brand", ORIGIN) == source


def test_removing_an_absent_table_changes_nothing() -> None:
    source = '[ui]\nlanguage = "en"\n'

    assert remove_table(source, "brand", ORIGIN) == source


def test_removal_stops_at_an_array_or_quoted_header() -> None:
    source = '[brand]\nname = "W"\n[[items]]\nx = 1\n'

    assert remove_table(source, "brand", ORIGIN) == "[[items]]\nx = 1\n"


@pytest.mark.parametrize(
    "source", ['brand = {name = "W"}', 'brand.name = "W"', '["brand"]\nname = "W"']
)
def test_removing_an_unsupported_form_is_refused(source: str) -> None:
    with pytest.raises(DeploymentPlanError, match=r"Cannot rewrite \[brand\]"):
        remove_table(source, "brand", ORIGIN)


def test_removing_keys_deletes_only_their_lines() -> None:
    source = (
        '[brand]  # identity\nname = "W"\n# about the icon\nicon = "a/b.png" # x\n'
        '[ui]\nicon = "other"\n'
    )

    result = remove_table_strings(source, "brand", ["icon", "absent"], ORIGIN)

    assert (
        result
        == '[brand]  # identity\nname = "W"\n# about the icon\n[ui]\nicon = "other"\n'
    )


def test_removing_a_key_that_is_not_a_plain_line_is_refused() -> None:
    with pytest.raises(DeploymentPlanError, match=r"Cannot rewrite \[brand\]"):
        remove_table_strings('brand = {icon = "x.png"}', "brand", ["icon"], ORIGIN)
