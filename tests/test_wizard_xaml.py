"""Structure, accessibility basics and loadability of wizard.xaml."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

import pytest
from wizard_ps_support import WIZARD_DIR, json_lines, run_snippet

from jarvis.core.brand_render import contrast_ratio

PRESENTATION = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
XAML = "{http://schemas.microsoft.com/winfx/2006/xaml}"
AUTOMATION_NAME = "AutomationProperties.Name"
INPUTS = ("IdentityName", "IdentityMonogram", "IdentityAccent", "IdentityIconText")
TAB_ORDER = (
    "IdentityName",
    "IdentityMonogram",
    "IdentityAccent",
    "PickColourButton",
    "IdentityIconText",
    "ChoosePngButton",
    "RemovePngButton",
    "RestoreDefaultButton",
    "DiscardButton",
)
CARD_BACKGROUND = "#FFFFFF"


@pytest.fixture(scope="module")
def tree() -> ET.ElementTree:
    return ET.parse(WIZARD_DIR / "wizard.xaml")


def named(tree: ET.ElementTree) -> dict[str, ET.Element]:
    return {
        node.attrib[XAML + "Name"]: node
        for node in tree.iter()
        if XAML + "Name" in node.attrib
    }


def pane(tree: ET.ElementTree, name: str) -> ET.Element:
    return named(tree)[name]


def test_every_identity_input_has_a_label_and_an_automation_name(
    tree: ET.ElementTree,
) -> None:
    labels = {
        re.search(r"ElementName=(\w+)", node.attrib["Target"]).group(1): node
        for node in tree.iter(PRESENTATION + "Label")
        if "Target" in node.attrib
    }
    controls = named(tree)

    for name in INPUTS:
        assert name in labels, f"{name} has no label"
        assert controls[name].attrib.get(AUTOMATION_NAME), f"{name} has no name"


def test_every_image_and_button_is_named_for_assistive_technology(
    tree: ET.ElementTree,
) -> None:
    identity = pane(tree, "IdentityPane")

    for image in identity.iter(PRESENTATION + "Image"):
        assert image.attrib.get(AUTOMATION_NAME), image.attrib[XAML + "Name"]
    for button in identity.iter(PRESENTATION + "Button"):
        assert button.attrib.get("Content", "").replace("_", "").strip()
    assert pane(tree, "AccentSwatch").attrib.get(AUTOMATION_NAME)


def test_access_keys_are_unique_across_all_pages(tree: ET.ElementTree) -> None:
    keys = [
        match.group(1).lower()
        for node in tree.iter()
        if (match := re.search(r"_(\w)", node.attrib.get("Content", "")))
    ]

    assert len(keys) == len(set(keys)), keys
    assert {"n", "m", "a", "i", "p", "h", "g", "r", "c", "u", "d"} <= set(keys)


def test_tab_order_is_the_visual_order(tree: ET.ElementTree) -> None:
    controls = named(tree)
    document = [
        node.attrib[XAML + "Name"]
        for node in pane(tree, "IdentityPane").iter()
        if node.attrib.get(XAML + "Name") in TAB_ORDER
    ]
    indexes = [int(controls[name].attrib["TabIndex"]) for name in TAB_ORDER]

    assert tuple(document) == TAB_ORDER
    assert indexes == sorted(indexes) and len(set(indexes)) == len(indexes)


def test_message_and_hint_text_has_enough_contrast_on_the_card(
    tree: ET.ElementTree,
) -> None:
    colours = {
        node.attrib[XAML + "Key"]: node.attrib["Color"]
        for node in tree.iter(PRESENTATION + "SolidColorBrush")
    }

    for key in ("ErrorBrush", "HintBrush"):
        assert contrast_ratio(colours[key], CARD_BACKGROUND) >= 4.5, key


def test_error_messages_are_announced_and_never_colour_only(
    tree: ET.ElementTree,
) -> None:
    style = next(
        node
        for node in tree.iter(PRESENTATION + "Style")
        if node.attrib.get(XAML + "Key") == "FieldMessage"
    )
    setters = {s.attrib["Property"]: s.attrib["Value"] for s in style}

    assert setters["AutomationProperties.LiveSetting"] == "Polite"
    for name in (
        "IdentityNameMessage",
        "IdentityMonogramMessage",
        "IdentityAccentMessage",
        "IdentityIconMessage",
        "IdentityGeneralMessage",
    ):
        assert "FieldMessage" in named(tree)[name].attrib["Style"]


def test_hostile_text_is_bounded_by_the_input_limits(tree: ET.ElementTree) -> None:
    controls = named(tree)

    assert {
        name: int(controls[name].attrib["MaxLength"])
        for name in ("IdentityName", "IdentityMonogram", "IdentityAccent")
    } == {"IdentityName": 100, "IdentityMonogram": 4, "IdentityAccent": 16}


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell and WPF")
def test_the_xaml_loads_into_objects_without_showing_a_window(tmp_path) -> None:
    body = r"""
Add-Type -AssemblyName PresentationFramework
$xaml = [xml](Get-Content -Raw -Encoding UTF8 -LiteralPath $env:XAML)
$window = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $xaml))
$declared = $xaml.SelectNodes('//*[@*[local-name()="Name"]]') | ForEach-Object {
    $_.GetAttribute('Name', 'http://schemas.microsoft.com/winfx/2006/xaml')
}
$missing = @($declared | Where-Object { $null -eq $window.FindName($_) })
[ordered]@{
    type = $window.GetType().Name; shown = $window.IsVisible
    missing = $missing; count = @($declared).Count
} | ConvertTo-Json -Compress
"""
    result = run_snippet(
        tmp_path, body, env={"XAML": str(WIZARD_DIR / "wizard.xaml")}, sta=True
    )

    (state,) = json_lines(result)
    assert state["type"] == "Window" and state["shown"] is False
    assert state["missing"] == [] and state["count"] > 45
