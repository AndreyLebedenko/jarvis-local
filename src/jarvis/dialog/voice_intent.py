"""Pure intent probe for the voice-triggered mode switch (story-v1.9.0, task 4).

A voice utterance reaches Jarvis as raw audio the model itself transcribes;
there is no text to regex against before dispatch. The only construction
that can separate "switch to voice mode" from an ordinary request that
merely mentions modes is therefore a separate, non-dialog probe pass over
the same audio: the model reads a directive that either answers with one
exact marker (SWITCH_RESPONSE_MODE=<name>) or an explicit proceed token,
and the result handler acts only on the exact marker. Everything else -
including a plausible-looking sentence about modes - fails safe to "it
was a request".

The probe is a transcription-style pass, not a dialog turn: it never
publishes ResponseToken, so nothing here can reach TTS or the shown text.
That is the same isolation rule OllamaTranscriptionBackend and the
annotation backend follow (PROJECT.md's reasoning-isolation discipline).

Fail-safe principle (task card): only one exact marker string switches;
anything else - empty, verbose, a near-miss, or a mode name that does not
exist - is treated as request content and flows through the normal turn
unchanged. Ambiguity never lands on "swallow the utterance".
"""

import re

from jarvis.core.config import PromptSettings
from jarvis.dialog.response_mode import ResponseMode

PROBE_USER_INSTRUCTION = "Answer with one marker word only, no other text."

# The exact marker contract: SWITCH_RESPONSE_MODE=<mode value>. One line,
# nothing else on it. Anything not matching this exactly is request content.
_SWITCH_MARKER_RE = re.compile(r"^\s*SWITCH_RESPONSE_MODE=(\w+)\s*$")

# The explicit no-op token the directive makes the model emit for an
# ordinary request. Deliberately distinct from "anything non-marker":
# receiving it and receiving nothing parse the same way, but a verbose
# answer also parses as PROCEED - fail-safe either way. The near-miss
# guards below still refuse to switch on prose that merely mentions modes.
_PROCEED_TOKEN = "PROCEED"

# A bare mode name with "mode" appended ("voice mode") would be a
# near-miss; require the exact "SWITCH_RESPONSE_MODE=" prefix so a
# chatty answer can never match by containing the words.
_MODE_VALUE_BY_NAME = {mode.value: mode for mode in ResponseMode}


def build_probe_messages(directive: str) -> list[dict[str, str]]:
    """The probe's message list: the directive as the system message, the
    one-line user instruction as the user message. Media attach at
    dispatch, not here - the caller owns the turn's own audio/images."""
    return [
        {"role": "system", "content": directive},
        {"role": "user", "content": PROBE_USER_INSTRUCTION},
    ]


def parse_mode_switch_marker(text: str) -> ResponseMode | None:
    """Returns the ResponseMode the whole reply's one exact marker names, or
    None.

    The accepted shape is the entire reply being a single marker line:
    strip the text, and it must be exactly SWITCH_RESPONSE_MODE=<known
    mode>. Anything else - prose around the marker, multiple lines, an
    unknown mode value, empty text - returns None and fails safe to "it
    was a request". The probe directive demands one marker word; a reply
    that wraps the marker in chatter is treated exactly as unreliable,
    which is the point of the exact-shape contract."""
    match = _SWITCH_MARKER_RE.match(text.strip())
    if match is None:
        return None
    return _MODE_VALUE_BY_NAME.get(match.group(1))


def intent_directive_from_settings(
    settings: PromptSettings,
) -> str | None:
    """The effective voice-intent directive, or None when the feature is
    off (the default). A configured-but-blank directive counts as off on
    purpose: a blank marker contract would parse nothing, so "off" is the
    only honest meaning blank can carry."""
    directive = settings.voice_intent_directive
    if directive is None or not directive.strip():
        return None
    return directive
