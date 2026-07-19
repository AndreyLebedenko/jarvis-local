"""File attachment planning (task-v1.6.0-2).

Pure validate-and-plan layer: given trusted upload metadata and bytes, it
classifies each attachment, applies the numeric policy recorded in
tasks/attachment-policy-v1.6.0.md, and produces a deterministic,
order-preserving plan of text parts, ready media, pending audio (raw bytes
gated for task-v1.6.0-5's normalization step), warnings, and rejection
messages.

No wiring here by design - no bus, no config, no other jarvis module. This
mirrors clipboard.py's "read/validate first, wire later" split: task-v1.6.0-
7 owns the real upload transport, task-v1.6.0-6 owns mapping an accepted
plan onto a Turn.

Detection is extension-first (task-v1.6.0-1's decision): the extension
alone picks the attachment class. A declared content_type is checked only
when it looks meaningful (not empty, not the generic application/octet-
stream browsers send for unrecognized types) and must then belong to that
class's MIME set, or the attachment is rejected as unsupported - never
silently trusted, never silently reclassified.

Per-turn caps (max files per class, max total files, max combined bytes)
are enforced greedily in upload order: earlier attachments fill the
budget, anything after the cap is rejected with a clear reason rather than
silently dropped - the policy note's never-silent-loss stance applies here
too, not only to audio chunking.

Audio duration is checked with soundfile.info(), a header/metadata probe
that does not decode the waveform - this is the "cheap metadata check" the
task boundary allows. The real decode/resample/chunk into 30 s model-safe
clips is task-v1.6.0-5's job, consuming this task's PendingAudioMedia.
"""

import base64
import io
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import soundfile as sf

MAX_TEXT_CHARS = 20000
MAX_TEXT_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_IMAGE_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_AUDIO_SECONDS = 90.0

MAX_IMAGES_PER_TURN = 4
MAX_AUDIO_FILES_PER_TURN = 1
MAX_TEXT_FILES_PER_TURN = 1
MAX_ATTACHMENTS_PER_TURN = 4
MAX_TOTAL_UPLOAD_BYTES_PER_TURN = 40 * 1024 * 1024

# ASCII, not Russian, per CLAUDE.md's ASCII-preference rule - these strings
# reach the model prompt (text) or the journal/UI (all of them) verbatim.
TEXT_TRUNCATION_MARKER_TEMPLATE = "[{filename} truncated to {max_chars} characters]"
IMAGE_CUE_TEMPLATE = "[Attached image: {filename}]"


class AttachmentClass(Enum):
    AUDIO = "audio"
    IMAGE = "image"
    TEXT = "text"


_EXTENSION_CLASSES: dict[str, AttachmentClass] = {
    ".wav": AttachmentClass.AUDIO,
    ".mp3": AttachmentClass.AUDIO,
    ".png": AttachmentClass.IMAGE,
    ".jpg": AttachmentClass.IMAGE,
    ".jpeg": AttachmentClass.IMAGE,
    ".txt": AttachmentClass.TEXT,
    ".md": AttachmentClass.TEXT,
    ".csv": AttachmentClass.TEXT,
    ".json": AttachmentClass.TEXT,
    ".log": AttachmentClass.TEXT,
}

# Deliberately wider than task-v1.6.0-1's headline MIME table: real
# browsers/OSes disagree on the "correct" MIME for several of these
# extensions (e.g. audio/x-wav vs audio/wave, image/jpg vs image/jpeg).
# Exact matching is this task's call to make; the goal is catching a
# genuinely wrong declaration (application/pdf on a .txt), not penalizing
# a harmless spelling variant.
_CLASS_MIME_TYPES: dict[AttachmentClass, frozenset[str]] = {
    AttachmentClass.AUDIO: frozenset(
        {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/vnd.wave",
            "audio/mpeg",
            "audio/mp3",
        }
    ),
    AttachmentClass.IMAGE: frozenset({"image/png", "image/jpeg", "image/jpg"}),
    AttachmentClass.TEXT: frozenset(
        {
            "text/plain",
            "text/markdown",
            "text/x-markdown",
            "text/csv",
            "application/json",
            "text/json",
            "application/vnd.ms-excel",
        }
    ),
}

_MAX_UPLOAD_BYTES_BY_CLASS: dict[AttachmentClass, int] = {
    AttachmentClass.AUDIO: MAX_AUDIO_UPLOAD_BYTES,
    AttachmentClass.IMAGE: MAX_IMAGE_UPLOAD_BYTES,
    AttachmentClass.TEXT: MAX_TEXT_UPLOAD_BYTES,
}

_MAX_FILES_PER_TURN_BY_CLASS: dict[AttachmentClass, int] = {
    AttachmentClass.AUDIO: MAX_AUDIO_FILES_PER_TURN,
    AttachmentClass.IMAGE: MAX_IMAGES_PER_TURN,
    AttachmentClass.TEXT: MAX_TEXT_FILES_PER_TURN,
}

_GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream"})

# The image analog of the audio path's soundfile.info() header probe: a
# cheap deterministic check on the leading bytes, not a full decode (which
# would need Pillow - a new dependency this iteration does not justify).
# Class-level like the MIME check above: a .png holding valid JPEG bytes is
# accepted, because the model receives the bytes, not the filename, and
# either signature is a format the images payload verifiably supports.
# What this catches is a genuinely wrong file behind an image extension.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_IMAGE_SIGNATURES = (_PNG_SIGNATURE, _JPEG_SIGNATURE)


@dataclass(frozen=True)
class AttachmentUpload:
    """Trusted upload metadata and bytes from the transport layer. The
    planner never reads a filesystem path - callers own getting bytes off
    the wire."""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class PlannedTextPart:
    """Text ready to append to the outgoing user message."""

    content: str
    truncated: bool


@dataclass(frozen=True)
class PlannedImageMedia:
    """Image bytes ready for the current turn's `images` payload."""

    base64_data: str


@dataclass(frozen=True)
class PendingAudioMedia:
    """Validated raw audio bytes awaiting task-v1.6.0-5's normalization
    into <= 30 s, 16 kHz mono clips. Not base64-encoded or chunked yet."""

    data: bytes
    content_type: str
    duration_seconds: float


@dataclass(frozen=True)
class AttachmentPlanItem:
    filename: str
    attachment_class: AttachmentClass | None
    accepted: bool
    text: PlannedTextPart | None = None
    image: PlannedImageMedia | None = None
    pending_audio: PendingAudioMedia | None = None
    warnings: tuple[str, ...] = ()
    rejection_reason: str | None = None


@dataclass(frozen=True)
class AttachmentPlan:
    """Order-preserving plan for one turn's attachments."""

    items: tuple[AttachmentPlanItem, ...]


def _basename(filename: str) -> str:
    """Attachments are a label, not a path - a client-supplied filename is
    never used to open a file, but a downstream consumer (e.g. the journal
    writer) could mistake an un-stripped "../x" for a real path later, so
    the planner normalizes to a bare filename now rather than passing the
    risk on."""
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _extension_of(filename: str) -> str:
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()


def _format_mb(num_bytes: float) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _rejected(
    filename: str, attachment_class: AttachmentClass | None, reason: str
) -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=attachment_class,
        accepted=False,
        rejection_reason=reason,
    )


def _classify_extension(filename: str) -> tuple[AttachmentClass | None, str | None]:
    """Returns (class, rejection_reason) from the extension alone - the one
    case where class is genuinely unknown, since nothing else identifies
    the file. Every other rejection path keeps this class attached."""
    attachment_class = _EXTENSION_CLASSES.get(_extension_of(filename))
    if attachment_class is not None:
        return attachment_class, None

    supported = ", ".join(sorted(ext.lstrip(".") for ext in _EXTENSION_CLASSES))
    extension = _extension_of(filename) or "no extension"
    reason = f"{filename}: unsupported file type ({extension}). Supported: {supported}."
    return None, reason


def _check_content_type(
    filename: str,
    attachment_class: AttachmentClass,
    normalized_content_type: str,
    raw_content_type: str,
) -> str | None:
    if (
        normalized_content_type in _GENERIC_CONTENT_TYPES
        or normalized_content_type in _CLASS_MIME_TYPES[attachment_class]
    ):
        return None
    return (
        f"{filename}: declared type '{raw_content_type}' does not match "
        f"a {attachment_class.value} file."
    )


def _check_size(
    filename: str, attachment_class: AttachmentClass, data_len: int
) -> str | None:
    max_bytes = _MAX_UPLOAD_BYTES_BY_CLASS[attachment_class]
    if data_len <= max_bytes:
        return None
    return (
        f"{filename}: file is {_format_mb(data_len)}, exceeds the "
        f"{_format_mb(max_bytes)} {attachment_class.value} limit."
    )


def _check_turn_caps(
    filename: str,
    attachment_class: AttachmentClass,
    data_len: int,
    accepted_counts: dict[AttachmentClass, int],
    accepted_total: int,
    accepted_bytes: int,
) -> str | None:
    max_for_class = _MAX_FILES_PER_TURN_BY_CLASS[attachment_class]
    if accepted_counts[attachment_class] >= max_for_class:
        return (
            f"{filename}: turn already has the maximum of {max_for_class} "
            f"{attachment_class.value} attachment(s)."
        )
    if accepted_total >= MAX_ATTACHMENTS_PER_TURN:
        return (
            f"{filename}: turn already has the maximum of "
            f"{MAX_ATTACHMENTS_PER_TURN} attachments."
        )
    if accepted_bytes + data_len > MAX_TOTAL_UPLOAD_BYTES_PER_TURN:
        return (
            f"{filename}: adding this file would exceed the "
            f"{_format_mb(MAX_TOTAL_UPLOAD_BYTES_PER_TURN)} combined attachment "
            "limit for this turn."
        )
    return None


def _wrap_text(filename: str, content: str) -> str:
    return f"[Attached file: {filename}]\n{content}\n[End of {filename}]"


def _plan_text(filename: str, data: bytes) -> AttachmentPlanItem:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _rejected(
            filename,
            AttachmentClass.TEXT,
            f"{filename}: could not be decoded as UTF-8 text.",
        )

    if len(text) <= MAX_TEXT_CHARS:
        return AttachmentPlanItem(
            filename=filename,
            attachment_class=AttachmentClass.TEXT,
            accepted=True,
            text=PlannedTextPart(content=_wrap_text(filename, text), truncated=False),
        )

    marker = TEXT_TRUNCATION_MARKER_TEMPLATE.format(
        filename=filename, max_chars=MAX_TEXT_CHARS
    )
    truncated_text = text[:MAX_TEXT_CHARS] + "\n" + marker
    warning = f"{filename}: truncated to {MAX_TEXT_CHARS} characters."
    wrapped = _wrap_text(filename, truncated_text)
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.TEXT,
        accepted=True,
        text=PlannedTextPart(content=wrapped, truncated=True),
        warnings=(warning,),
    )


def _plan_image(filename: str, data: bytes) -> AttachmentPlanItem:
    if not any(data.startswith(signature) for signature in _IMAGE_SIGNATURES):
        return _rejected(
            filename,
            AttachmentClass.IMAGE,
            f"{filename}: file content is not a valid PNG or JPEG image.",
        )
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.IMAGE,
        accepted=True,
        image=PlannedImageMedia(base64_data=base64.b64encode(data).decode("ascii")),
    )


def _plan_audio(filename: str, content_type: str, data: bytes) -> AttachmentPlanItem:
    try:
        info = sf.info(io.BytesIO(data))
    except Exception:
        return _rejected(
            filename,
            AttachmentClass.AUDIO,
            f"{filename}: could not read audio file (corrupt or unreadable).",
        )

    duration_seconds = info.frames / info.samplerate if info.samplerate else 0.0
    if duration_seconds > MAX_AUDIO_SECONDS:
        return _rejected(
            filename,
            AttachmentClass.AUDIO,
            f"{filename}: audio is {duration_seconds:.1f}s, "
            f"exceeds the {MAX_AUDIO_SECONDS:.0f}s limit.",
        )

    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.AUDIO,
        accepted=True,
        pending_audio=PendingAudioMedia(
            data=data, content_type=content_type, duration_seconds=duration_seconds
        ),
    )


def _plan_by_class(
    attachment_class: AttachmentClass, filename: str, content_type: str, data: bytes
) -> AttachmentPlanItem:
    if attachment_class is AttachmentClass.TEXT:
        return _plan_text(filename, data)
    if attachment_class is AttachmentClass.IMAGE:
        return _plan_image(filename, data)
    return _plan_audio(filename, content_type, data)


def plan_attachments(uploads: Sequence[AttachmentUpload]) -> AttachmentPlan:
    """Validates and plans each upload in order, enforcing per-file and
    per-turn policy. Never raises on bad input - every failure becomes a
    rejected AttachmentPlanItem with a user-facing reason."""
    items: list[AttachmentPlanItem] = []
    accepted_counts: dict[AttachmentClass, int] = dict.fromkeys(AttachmentClass, 0)
    accepted_total = 0
    accepted_bytes = 0

    for upload in uploads:
        filename = _basename(upload.filename)
        data = upload.data

        attachment_class, reason = _classify_extension(filename)
        if reason is not None:
            items.append(_rejected(filename, attachment_class, reason))
            continue

        if len(data) == 0:
            empty_reason = f"{filename}: file is empty."
            items.append(_rejected(filename, attachment_class, empty_reason))
            continue

        content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
        reason = _check_content_type(
            filename, attachment_class, content_type, upload.content_type
        )
        if reason is not None:
            items.append(_rejected(filename, attachment_class, reason))
            continue

        data_len = len(data)
        reason = _check_size(filename, attachment_class, data_len) or _check_turn_caps(
            filename,
            attachment_class,
            data_len,
            accepted_counts,
            accepted_total,
            accepted_bytes,
        )
        if reason is not None:
            items.append(_rejected(filename, attachment_class, reason))
            continue

        item = _plan_by_class(attachment_class, filename, content_type, data)
        if item.accepted:
            accepted_counts[attachment_class] += 1
            accepted_total += 1
            accepted_bytes += len(data)
        items.append(item)

    return AttachmentPlan(items=tuple(items))


def compose_turn_text(typed_text: str, plan: AttachmentPlan) -> str:
    """Joins the Journal input dock's typed message with any accepted text
    attachments (task-v1.6.0-3), typed text always leading so the model
    reads the user's own words before any attached document - it is not
    lost or buried among file content. Each text part already carries its
    own filename delimiters and truncation marker (`_wrap_text`/
    `_plan_text` above), so this is a plain join, not another layer of
    wrapping.

    An accepted image contributes only a short cue naming the file
    (task-v1.6.0-4): the binary reaches the model through the `images`
    payload (`compose_turn_images`), never through text, but without the
    cue the model would see nameless media it cannot connect to the user's
    words. Audio items contribute nothing here by design: their cue comes
    from the normalization result (`attachment_audio.compose_audio_cue`),
    not from the plan, so a cue can never name audio whose decode later
    failed - orchestration (task-v1.6.0-6) appends it. Attachment parts
    keep plan order, which is upload order."""
    parts = [typed_text] if typed_text else []
    for item in plan.items:
        if not item.accepted:
            continue
        if item.text is not None:
            parts.append(item.text.content)
        elif item.image is not None:
            parts.append(IMAGE_CUE_TEMPLATE.format(filename=item.filename))
    return "\n\n".join(parts)


def compose_turn_images(plan: AttachmentPlan) -> tuple[str, ...]:
    """Accepted image attachments as base64 strings in plan (upload)
    order - the exact representation the screenshot path already feeds to
    the current turn's media list, so orchestration (task-v1.6.0-6) can
    concatenate both without conversion. Current-turn only by story
    contract: nothing here enters ConversationHistory."""
    return tuple(
        item.image.base64_data
        for item in plan.items
        if item.accepted and item.image is not None
    )
