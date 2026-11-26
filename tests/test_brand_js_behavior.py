# ruff: noqa: E501
"""Runs strings.js in Node against a stub document, when Node exists: the brand
name fills {brand} unchanged in both languages, a hostile name never becomes
markup or expands replacement patterns, and applyBrand writes the header mark,
the header name and the document title. A real window is the human handoff
(manual/instance-branding-1-handoff.md)."""

import json
import shutil
import subprocess

import pytest

from jarvis.ui.status_console import UI_DIR

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

function element(attributes) {
  const attrs = { ...attributes };
  const props = {};
  return {
    attrs,
    props,
    style: { set: {}, setProperty(name, value) { this.set[name] = value; } },
    getAttribute: (name) => attrs[name],
    setAttribute: (name, value) => { attrs[name] = value; },
    set innerHTML(value) { throw new Error("innerHTML written"); },
    set textContent(value) { props.textContent = value; },
    get textContent() { return props.textContent; },
    set placeholder(value) { props.placeholder = value; },
    set title(value) { props.title = value; },
  };
}

const placeholder = element({ "data-i18n-placeholder": "journal_input_placeholder" });
const label = element({ "data-i18n": "journal_search_label" });
const saved = element({ "data-i18n": "journal_attachment_persist_saved" });
const mark = element({ "data-brand": "default" });
const brandName = element({});
const byId = { brandMark: mark, brandName };
const document = {
  title: "unset",
  body: { dataset: { titleSuffix: process.argv[2] } },
  documentElement: element({}),
  getElementById: (id) => byId[id] || null,
  querySelectorAll(selector) {
    return {
      "[data-i18n]": [label, saved],
      "[data-i18n-title]": [],
      "[data-i18n-placeholder]": [placeholder],
    }[selector];
  },
};
const context = vm.createContext({ document });
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const scenario = JSON.parse(process.argv[3]);
const results = vm.runInContext(scenario.script, context);
console.log(JSON.stringify({
  results,
  title: document.title,
  mark: { text: mark.props.textContent, accent: mark.style.set["--brand-accent"], shape: mark.attrs["data-brand"] },
  brandName: brandName.props.textContent,
  placeholder: placeholder.props.placeholder,
  label: label.props.textContent,
  saved: saved.props.textContent,
}));
"""


def _run(script: str, title_suffix: str = "Status Console") -> dict:
    completed = subprocess.run(
        [
            "node",
            "-e",
            HARNESS,
            str(UI_DIR / "strings.js"),
            title_suffix,
            json.dumps({"script": script}),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_before_any_brand_arrives_the_strings_read_as_jarvis():
    result = _run('uiString("journal_input_placeholder")')

    assert result["results"] == "Message Jarvis"


def test_a_brand_fills_the_english_strings_the_header_and_the_title():
    result = _run(
        """
        applyBrand({name: "Work", monogram: "W", accent: "#E0A03F", is_default: false});
        applyUiLanguage({language: "en"});
        uiString("journal_input_placeholder")
        """
    )

    assert result["results"] == "Message Work"
    assert result["placeholder"] == "Message Work"
    assert result["label"] == "Search Work answers"
    assert result["title"] == "Work - Status Console"
    assert result["mark"] == {"text": "W", "accent": "#E0A03F", "shape": "custom"}
    assert result["brandName"] == "Work"


def test_the_touchstrip_page_title_uses_its_own_suffix():
    result = _run(
        'applyBrand({name: "Work", monogram: "W", accent: "#E0A03F", is_default: false})',
        title_suffix="Touchstrip",
    )

    assert result["title"] == "Work - Touchstrip"


def test_the_default_brand_payload_keeps_the_default_mark_shape():
    result = _run(
        'applyBrand({name: "Jarvis", monogram: "J", accent: "#3FE0D0", is_default: true})'
    )

    assert result["mark"]["shape"] == "default"
    assert result["title"] == "Jarvis - Status Console"
    assert result["brandName"] == "Jarvis"


def test_the_russian_strings_keep_their_words_and_the_name_as_typed():
    result = _run(
        """
        applyBrand({name: "Work", monogram: "W", accent: "#E0A03F", is_default: false});
        applyUiLanguage({language: "ru"});
        uiString("journal_input_busy")
        """
    )

    assert result["results"] == "Work занят. Текст сохранён."
    assert result["placeholder"] == "Сообщение Work"


def test_a_late_brand_restamps_text_already_stamped_in_the_language():
    result = _run(
        """
        applyUiLanguage({language: "ru"});
        applyBrand({name: "Home", monogram: "H", accent: "#3FE0D0", is_default: false});
        """
    )

    assert result["placeholder"] == "Сообщение Home"


HOSTILE_NAME = (
    "<img src=x onerror=alert(1)> \"q\" 's' $& $1 $$ $` $' {max} {brand} {name}"
)


def test_a_hostile_name_is_inserted_literally_everywhere():
    result = _run(
        f"""
        applyBrand({{name: {json.dumps(HOSTILE_NAME)}, monogram: "I", accent: "#112233", is_default: false}});
        applyUiLanguage({{language: "en"}});
        uiString("journal_input_placeholder")
        """
    )

    assert result["results"] == "Message " + HOSTILE_NAME
    assert result["placeholder"] == "Message " + HOSTILE_NAME
    assert result["brandName"] == HOSTILE_NAME
    assert result["title"] == HOSTILE_NAME + " - Status Console"


def test_the_attachment_file_placeholder_is_not_taken_for_the_brand():
    result = _run(
        """
        applyBrand({name: "Work", monogram: "W", accent: "#E0A03F", is_default: false});
        applyUiLanguage({language: "en"});
        uiString("journal_attachment_persist_saved").replace("{name}", "report.txt")
        """
    )

    assert result["results"] == "Saved as report.txt"


def test_a_payload_without_a_name_changes_nothing():
    result = _run(
        'applyBrand({}); applyBrand(undefined); uiString("journal_search_label")'
    )

    assert result["results"] == "Search Jarvis answers"
    assert result["title"] == "unset"
