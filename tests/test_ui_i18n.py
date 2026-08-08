"""Web-layer localization contract (story-v1.2.11, task 2).

Pure file-content checks: the served pages default to English, every
data-i18n key used in markup exists in strings.js for every language,
and both language dictionaries cover the same key set.
"""

import re
from dataclasses import fields

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import TTS_ROUTE_TYPES, MemorySettings
from jarvis.core.lifecycle import ModelRequestInput
from jarvis.dialog.thinking_mode import ReasoningLevelState
from jarvis.inputs.attachments import AttachmentClass
from jarvis.journal.consolidation import MediaActionReason
from jarvis.memory.files import MemoryFileRepository, build_memory_file_specs
from jarvis.tools.builtin import BuiltinToolProvider
from jarvis.tools.registry import ToolRegistry
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
    used.difference_update(
        {
            "config_tts_field_",
            "chip_reset_",
            "data_source_",
            "last_request_",
            "journal_attachment_class_",
            "journal_attachment_status_",
            "journal_consolidation_reason_",
            "mcp_",
            "think_status_",
        }
    )
    assert used <= keys


def test_every_model_request_input_has_a_last_request_label():
    """app.js's applyLastModelRequest() builds its lookup key dynamically
    (uiString("last_request_" + item.kind)), so
    test_every_uistring_lookup_key_exists_in_the_dictionary above cannot
    statically resolve it and excludes the "last_request_" prefix instead.
    This closes that gap from the Python side: every ModelRequestInput
    value (core/lifecycle.py) that can reach ModelRequestStarted.inputs
    must have a matching catalog entry, or the first live turn of that
    kind throws inside uiString() and breaks that delta update."""
    keys = _strings_js_keys()["en"]
    expected = {f"last_request_{member.value}" for member in ModelRequestInput}

    assert expected <= keys


def test_every_attachment_class_has_a_journal_upload_label():
    """The transport serializes AttachmentClass.value as payload["class"],
    and app.js renders it through
    uiString("journal_attachment_class_" + value). Keep that cross-language
    suffix contract pinned the same way ModelRequestInput labels are."""
    keys = _strings_js_keys()["en"]
    expected = {
        f"journal_attachment_class_{member.value}" for member in AttachmentClass
    }

    assert expected <= keys
    assert "journal_attachment_class_unknown" in keys


def test_every_media_action_reason_has_a_consolidation_label():
    """The consolidation API serializes MediaActionReason.value as
    payload["reason"], and app.js renders it through
    uiString("journal_consolidation_reason_" + item.reason). Keep that
    cross-language suffix contract pinned the same way AttachmentClass
    labels are."""
    keys = _strings_js_keys()["en"]
    expected = {
        f"journal_consolidation_reason_{member.value}" for member in MediaActionReason
    }

    assert expected <= keys


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


def test_the_unavailable_tool_label_exists_in_every_language():
    """app.js writes only this one state on a tool row: on/off is the
    checkbox's job. A missing key throws inside uiString() and blanks the
    row - the surface that already misled a user once by calling a tool
    the owner had switched off "unavailable"."""
    for language, keys in _strings_js_keys().items():
        assert "mcp_tool_unavailable" in keys, language


def test_every_builtin_tool_has_a_capability_label_in_every_language():
    """app.js builds the key dynamically (optionalUiString("tool_label_" +
    name)), so the static lookup test cannot resolve it. Absence is not an
    error there - it is the deliberate fallback for third-party MCP tools,
    which keep their real names rather than being given invented friendly
    ones. That makes this the only guard that our own tools do get a
    human label instead of silently falling back to snake_case."""
    registry = ToolRegistry()
    BuiltinToolProvider(
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        memory_file_repository=MemoryFileRepository(
            build_memory_file_specs(MemorySettings())
        ),
    ).register_tools(registry)
    expected = {f"tool_label_{tool.name}" for tool in registry.all()}

    for language, keys in _strings_js_keys().items():
        assert expected <= keys, language


def test_the_tool_row_tooltip_never_becomes_the_accessible_name():
    """The description is written for the model and can be a paragraph of
    instructions. It belongs in the hover tooltip only; a screen reader
    must get the capability label and the identifier instead."""
    source = _read("app.js")
    code_lines = [
        line for line in source.splitlines() if not line.strip().startswith("//")
    ]
    aria_lines = [line for line in code_lines if "aria-label" in line]

    assert "row.title = tool.description" in source
    assert aria_lines
    assert all("description" not in line for line in aria_lines)
