from jarvis.core.config import BrandSettings
from jarvis.ui.status_console import (
    StatusConsoleWindow,
    TouchstripWindow,
    brand_payload,
    status_console_title,
    touchstrip_title,
)
from jarvis.ui.transport import UiStateStore

WORK = BrandSettings(name="Work", monogram="W", accent="#E0A03F")


def test_the_default_brand_payload_is_marked_default():
    assert brand_payload(BrandSettings()) == {
        "name": "Jarvis",
        "monogram": "J",
        "accent": "#3FE0D0",
        "is_default": True,
    }


def test_a_non_default_brand_payload_carries_every_value():
    assert brand_payload(WORK) == {
        "name": "Work",
        "monogram": "W",
        "accent": "#E0A03F",
        "is_default": False,
    }


def test_changing_only_the_accent_makes_the_brand_non_default():
    assert brand_payload(BrandSettings(accent="#E0A03F"))["is_default"] is False


def test_naming_the_default_values_explicitly_is_still_the_default():
    explicit = BrandSettings(name="Jarvis", monogram="J", accent="#3FE0D0")

    assert brand_payload(explicit)["is_default"] is True


def test_window_titles_of_the_default_brand_are_the_current_titles():
    assert status_console_title("Jarvis") == "Jarvis - Status Console"
    assert touchstrip_title("Jarvis") == "Jarvis - Touchstrip"


def test_window_titles_carry_the_name_unchanged():
    assert status_console_title("Work <b>") == "Work <b> - Status Console"
    assert touchstrip_title("Work <b>") == "Work <b> - Touchstrip"


def test_window_classes_default_to_the_current_titles():
    assert StatusConsoleWindow().title == "Jarvis - Status Console"
    assert TouchstripWindow().title == "Jarvis - Touchstrip"


def test_the_snapshot_of_a_store_without_a_brand_reports_the_default():
    assert UiStateStore().snapshot()["brand"] == brand_payload(BrandSettings())


def test_the_snapshot_carries_the_brand_the_store_was_built_with():
    snapshot = UiStateStore(brand=brand_payload(WORK)).snapshot_message()

    assert snapshot["payload"]["brand"] == brand_payload(WORK)
