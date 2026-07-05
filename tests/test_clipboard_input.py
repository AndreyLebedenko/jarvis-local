from config import ClipboardSettings
from clipboard_input import ClipboardSubmitted, read_clipboard_submission


def test_reads_clean_short_text_unchanged():
    settings = ClipboardSettings(max_chars=100)

    event = read_clipboard_submission(settings, read_clipboard=lambda: "print('hi')")

    assert event == ClipboardSubmitted(text="print('hi')", truncated=False, is_empty=False)


def test_truncates_text_over_max_chars_with_visible_marker():
    settings = ClipboardSettings(max_chars=10)
    long_text = "x" * 50

    event = read_clipboard_submission(settings, read_clipboard=lambda: long_text)

    assert event.truncated is True
    assert event.is_empty is False
    assert event.text.startswith("x" * 10)
    assert "10" in event.text  # the marker names the character limit
    assert len(event.text) > 10  # marker text appended, not just a hard cut


def test_text_at_exactly_max_chars_is_not_truncated():
    settings = ClipboardSettings(max_chars=10)
    text = "x" * 10

    event = read_clipboard_submission(settings, read_clipboard=lambda: text)

    assert event == ClipboardSubmitted(text=text, truncated=False, is_empty=False)


def test_empty_clipboard_reports_is_empty():
    settings = ClipboardSettings()

    event = read_clipboard_submission(settings, read_clipboard=lambda: "")

    assert event == ClipboardSubmitted(text="", truncated=False, is_empty=True)


def test_whitespace_only_clipboard_reports_is_empty():
    settings = ClipboardSettings()

    event = read_clipboard_submission(settings, read_clipboard=lambda: "   \n\t  ")

    assert event.is_empty is True
