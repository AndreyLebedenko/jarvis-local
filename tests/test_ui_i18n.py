"""Web-layer localization contract (story-v1.2.11, task 2).

Pure file-content checks: the served pages default to English, every
data-i18n key used in markup exists in strings.js for every language,
and both language dictionaries cover the same key set.
"""

import re
from dataclasses import fields

import pytest

from jarvis.core.config import TTS_ROUTE_TYPES
from jarvis.ui.status_console import UI_DIR

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _read(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


def _strings_js_keys() -> dict[str, set[str]]:
    source = _read("strings.js")
    catalogs: dict[str, set[str]] = {}
    for language_match in re.finditer(
        r"^  (\w+): \{\n(.*?)^  \},", source, re.S | re.M
    ):
        language, body = language_match.group(1), language_match.group(2)
        catalogs[language] = set(re.findall(r"^    (\w+):", body, re.M))
    return catalogs


@pytest.mark.parametrize(
    "filename",
    [
        "index.html",
        "touchstrip.html",
        "app.js",
        "touchstrip.js",
        "transport.js",
        "contract.js",
        "demo.html",
        "demo.js",
    ],
)
def test_default_ui_surfaces_contain_no_russian_text(filename):
    assert not _CYRILLIC.search(_read(filename))


def test_strings_js_defines_matching_english_and_russian_key_sets():
    catalogs = _strings_js_keys()
    assert set(catalogs) == {"en", "ru"}
    assert catalogs["en"] == catalogs["ru"]
    assert catalogs["en"]


@pytest.mark.parametrize("filename", ["index.html", "touchstrip.html"])
def test_every_data_i18n_key_in_markup_exists_in_the_dictionary(filename):
    keys = _strings_js_keys()["en"]
    html = _read(filename)
    used = set(re.findall(r'data-i18n(?:-title)?="(\w+)"', html))
    assert used
    assert used <= keys


@pytest.mark.parametrize("filename", ["app.js", "touchstrip.js", "transport.js"])
def test_every_uistring_lookup_key_exists_in_the_dictionary(filename):
    keys = _strings_js_keys()["en"]
    used = set(re.findall(r'uiString\(\s*"(\w+)"', _read(filename)))
    used.discard("config_tts_field_")
    assert used <= keys


def test_every_projected_tts_field_has_a_localized_label():
    keys = _strings_js_keys()["en"]
    field_names = {
        field.name
        for route_type in TTS_ROUTE_TYPES.values()
        for field in fields(route_type)
    }

    assert {f"config_tts_field_{name}" for name in field_names} <= keys


def test_served_pages_load_strings_js_before_the_scripts_that_use_it():
    for filename in ["index.html", "touchstrip.html", "demo.html"]:
        html = _read(filename)
        strings_at = html.index('src="strings.js"')
        for consumer in ["transport.js", "app.js", "touchstrip.js"]:
            if f'src="{consumer}"' in html:
                assert strings_at < html.index(f'src="{consumer}"')


def test_pages_default_to_english_lang_attribute():
    for filename in ["index.html", "touchstrip.html", "demo.html"]:
        assert '<html lang="en"' in _read(filename)
