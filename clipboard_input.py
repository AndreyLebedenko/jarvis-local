"""Clipboard-to-prompt input.

Reads the current clipboard text and turns it into a ClipboardSubmitted
bus event, applying a length cap (config.clipboard.max_chars) so an
accidental huge paste (e.g. a log file) doesn't blow up local-context
latency. Truncation is visible in-band (a marker appended to the text),
never silent - the model must never reason from a document it doesn't
know is incomplete.

Uses pyperclip, not Tkinter: reusing Tkinter here would risk the same
thread-safety hazard already caught live in capture.py's region-select
overlay (see
tasks/bug_reports/capture-region-select-tkinter-thread-safety.md) -
Tkinter is not safe to drive from an arbitrary background thread, and a
hotkey callback (keyboard's own callback thread) is exactly that.

No hotkey-listening code here yet: task-08's scope deliberately stops at
"read the clipboard, build the event" - the real global hotkey is added
in task-10 alongside the rest of v1.1's runtime wiring (see task-08's
task card for the reasoning: this keeps wiring work from starting before
the riskier Orchestrator refactor this feature also requires has landed
and been reviewed on its own).
"""

from collections.abc import Callable
from dataclasses import dataclass

from config import ClipboardSettings

ReadClipboard = Callable[[], str]

# ASCII, not Russian, per CLAUDE.md's ASCII-preference rule: this marker
# is embedded directly into the model prompt, and non-ASCII text here has
# already caused a real mojibake incident during review (verified: the
# source file itself was correct UTF-8, but the string was garbled
# somewhere downstream before a human reader saw it) - ASCII sidesteps
# that whole class of risk rather than chasing where the corruption
# happened.
TRUNCATION_MARKER_TEMPLATE = "[text truncated to {max_chars} characters]"


def _default_read_clipboard() -> str:
    import pyperclip

    return pyperclip.paste()


@dataclass(frozen=True)
class ClipboardSubmitted:
    text: str
    truncated: bool
    is_empty: bool


def read_clipboard_submission(
    settings: ClipboardSettings,
    read_clipboard: ReadClipboard | None = None,
) -> ClipboardSubmitted:
    """Reads the clipboard and builds a ClipboardSubmitted event, applying
    settings.max_chars. Empty/whitespace-only clipboard content is
    reported via is_empty rather than silently producing a blank turn -
    callers should not start a turn in that case.
    """
    read = read_clipboard or _default_read_clipboard
    text = read() or ""

    if not text.strip():
        return ClipboardSubmitted(text="", truncated=False, is_empty=True)

    if len(text) <= settings.max_chars:
        return ClipboardSubmitted(text=text, truncated=False, is_empty=False)

    marker = TRUNCATION_MARKER_TEMPLATE.format(max_chars=settings.max_chars)
    truncated_text = text[: settings.max_chars] + "\n" + marker
    return ClipboardSubmitted(text=truncated_text, truncated=True, is_empty=False)
