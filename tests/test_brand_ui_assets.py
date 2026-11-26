# ruff: noqa: E501
"""Static contract of the brand surfaces (story-instance-branding.md, task 1):
the {brand} strings render as before for the default brand, the accent colours
only the brand mark, and no brand write can create markup."""

import re

import pytest

from jarvis.core.config import DEFAULT_BRAND_ACCENT, BrandSettings
from jarvis.ui.status_console import UI_DIR

PLACEHOLDER = re.compile(r"\{(\w+)\}")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# The texts as they read before the brand placeholder existed.
PRE_BRAND_TEXTS = {
    "en": {
        "run_mode_mcp_hint": "Voice guide for an MCP client: Jarvis takes no input",
        "confirm_shutdown_text": "Jarvis will be stopped. You will need to start the process again.",
        "pending_restart_text": "Changes saved - restart Jarvis to apply.",
        "journal_source_assistant": "Jarvis",
        "journal_external_answer_status_muted": "Not played: Jarvis is muted.",
        "journal_search_label": "Search Jarvis answers",
        "journal_search_no_results": "No matching Jarvis answers",
        "journal_input_placeholder": "Message Jarvis",
        "journal_input_busy": "Jarvis is busy. Your text was kept.",
        "journal_new_context_busy": "Jarvis is busy. Try again after the current turn.",
        "journal_memory_self_description": "Jarvis persona and self-knowledge.",
        "journal_fork_busy": "Jarvis is busy. Try again after the current turn.",
    },
    "ru": {
        "run_mode_mcp_hint": "Голосовой гид для MCP-клиента: Jarvis не принимает ввод",
        "confirm_shutdown_text": "Jarvis будет остановлен. Потребуется запустить процесс заново.",
        "pending_restart_text": "Изменения сохранены - перезапустите Jarvis, чтобы применить.",
        "journal_source_assistant": "Jarvis",
        "journal_external_answer_status_muted": "Не озвучено: Jarvis заглушен.",
        "journal_search_label": "Поиск ответов Jarvis",
        "journal_search_no_results": "Подходящих ответов Jarvis нет",
        "journal_input_placeholder": "Сообщение Jarvis",
        "journal_input_busy": "Jarvis занят. Текст сохранён.",
        "journal_new_context_busy": "Jarvis занят. Попробуйте после текущего ответа.",
        "journal_memory_self_description": "Персона Jarvis и знание о себе.",
        "journal_fork_busy": "Jarvis занят. Попробуйте после текущего ответа.",
    },
}


def _read(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


def _catalogs() -> dict[str, dict[str, str]]:
    source = _read("strings.js")
    catalogs: dict[str, dict[str, str]] = {}
    for language_match in re.finditer(
        r"^  (\w+): \{\n(.*?)^  \},", source, re.S | re.M
    ):
        language, body = language_match.group(1), language_match.group(2)
        catalogs[language] = dict(
            re.findall(r'^    (\w+): "((?:[^"\\]|\\.)*)",$', body, re.M)
        )
    return catalogs


@pytest.mark.parametrize("language", ["en", "ru"])
def test_with_the_default_name_every_branded_string_reads_as_before(language):
    catalog = _catalogs()[language]

    for key, before in PRE_BRAND_TEXTS[language].items():
        assert catalog[key].replace("{brand}", "Jarvis") == before


@pytest.mark.parametrize("language", ["en", "ru"])
def test_only_the_branded_strings_hold_the_placeholder_and_none_say_jarvis(language):
    catalog = _catalogs()[language]

    with_placeholder = {key for key, text in catalog.items() if "{brand}" in text}

    assert with_placeholder == set(PRE_BRAND_TEXTS[language])
    assert [key for key, text in catalog.items() if "Jarvis" in text] == []


def test_a_string_holding_the_name_placeholder_holds_no_other_placeholder():
    for language, catalog in _catalogs().items():
        for key, text in catalog.items():
            if "{brand}" in text:
                assert set(PLACEHOLDER.findall(text)) == {"brand"}, (language, key)


def test_the_default_accent_equals_the_cyan_of_both_stylesheets():
    for stylesheet in ("style.css", "touchstrip.css"):
        match = re.search(r"--cyan:\s*(#[0-9A-Fa-f]{6});", _read(stylesheet))
        assert match is not None
        assert match.group(1).upper() == DEFAULT_BRAND_ACCENT
    assert BrandSettings().accent == DEFAULT_BRAND_ACCENT


def test_only_the_brand_mark_reads_the_brand_accent():
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", CSS_COMMENT.sub("", _read("style.css")))
    readers = {
        selector.strip() for selector, body in rules if "var(--brand-accent)" in body
    }

    assert readers == {".brand-mark"}
    assert "--brand-accent" not in _read("touchstrip.css")


def test_the_default_brand_mark_is_markup_the_snapshot_restamps():
    html = _read("index.html")

    assert '<div class="brand-mark" id="brandMark" data-brand="default">J</div>' in html
    assert 'id="brandName">Jarvis</span>' in html
    assert 'data-title-suffix="Status Console"' in html
    assert 'data-title-suffix="Touchstrip"' in _read("touchstrip.html")


def test_the_default_header_name_is_upper_cased_by_css_not_by_its_text():
    css = CSS_COMMENT.sub("", _read("style.css"))

    rule = re.search(r"\.brand-name \.brand-name-text \{(.*?)\}", css, re.S)

    assert rule is not None
    assert "text-transform: uppercase" in rule[1]


def test_the_circle_shape_is_set_only_for_a_custom_brand():
    css = CSS_COMMENT.sub("", _read("style.css"))

    assert re.search(
        r'\.brand-mark\[data-brand="custom"\]\s*\{\s*border-radius:\s*50%;\s*\}', css
    )
    default_rule = re.search(r"\.brand-mark \{.*?\}", css, re.S)
    assert default_rule is not None
    assert "border-radius: 6px" in default_rule[0]


def test_both_snapshot_handlers_apply_the_brand_before_the_language():
    for filename in ("app.js", "touchstrip.js"):
        source = _read(filename)
        body = source[source.index("function _applyStateSnapshot") :]

        assert body.index("applyBrand(state.brand)") < body.index("applyUiLanguage(")
        assert "brand: applyBrand," in source


@pytest.mark.parametrize("filename", ["strings.js", "touchstrip.js"])
def test_brand_code_never_writes_markup(filename):
    source = _read(filename)

    for forbidden in (
        "innerHTML",
        "insertAdjacentHTML",
        "outerHTML",
        "document.write",
    ):
        assert forbidden not in source
