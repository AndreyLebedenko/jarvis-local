import base64
import io

import numpy as np
import soundfile as sf

from jarvis.inputs.attachments import (
    MAX_ATTACHMENTS_PER_TURN,
    MAX_AUDIO_SECONDS,
    MAX_IMAGE_UPLOAD_BYTES,
    MAX_IMAGES_PER_TURN,
    MAX_TEXT_CHARS,
    MAX_TEXT_UPLOAD_BYTES,
    MAX_TOTAL_UPLOAD_BYTES_PER_TURN,
    AttachmentClass,
    AttachmentUpload,
    plan_attachments,
)

SAMPLE_RATE = 16000


def _wav_bytes(duration_seconds: float) -> bytes:
    samples = np.zeros(int(SAMPLE_RATE * duration_seconds), dtype=np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _text_upload(
    filename: str, text: str, content_type: str = "text/plain"
) -> AttachmentUpload:
    return AttachmentUpload(
        filename=filename, content_type=content_type, data=text.encode()
    )


def _image_upload(filename: str = "photo.png", size: int = 100) -> AttachmentUpload:
    data = b"\x89PNG" + b"x" * size
    return AttachmentUpload(filename=filename, content_type="image/png", data=data)


def _audio_upload(
    filename: str = "memo.wav",
    duration_seconds: float = 2.0,
    content_type: str = "audio/wav",
) -> AttachmentUpload:
    return AttachmentUpload(
        filename=filename, content_type=content_type, data=_wav_bytes(duration_seconds)
    )


# --- accepted, single class -----------------------------------------------


def test_accepts_a_short_text_file():
    plan = plan_attachments([_text_upload("notes.txt", "hello world")])

    (item,) = plan.items
    assert item.accepted is True
    assert item.attachment_class is AttachmentClass.TEXT
    assert item.text is not None
    assert item.text.truncated is False
    assert "hello world" in item.text.content
    assert item.text.content.startswith("[Attached file: notes.txt]")
    assert item.warnings == ()
    assert item.rejection_reason is None


def test_accepts_a_png_image_and_base64_encodes_the_raw_bytes():
    upload = _image_upload("photo.png")

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True
    assert item.attachment_class is AttachmentClass.IMAGE
    assert item.image is not None
    assert base64.b64decode(item.image.base64_data) == upload.data


def test_accepts_a_short_wav_and_reports_duration_without_normalizing():
    upload = _audio_upload("memo.wav", duration_seconds=2.0)

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True
    assert item.attachment_class is AttachmentClass.AUDIO
    assert item.pending_audio is not None
    assert item.pending_audio.data == upload.data
    assert item.pending_audio.content_type == "audio/wav"
    assert abs(item.pending_audio.duration_seconds - 2.0) < 0.01


def test_accepts_an_mp3_via_the_existing_soundfile_stack():
    tone = np.zeros(SAMPLE_RATE, dtype=np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, tone, SAMPLE_RATE, format="MP3")
    upload = AttachmentUpload(
        filename="voice.mp3", content_type="audio/mpeg", data=buffer.getvalue()
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True
    assert item.attachment_class is AttachmentClass.AUDIO


# --- text truncation and encoding -----------------------------------------


def test_truncates_text_over_max_chars_with_visible_marker_and_warning():
    long_text = "x" * (MAX_TEXT_CHARS + 500)

    plan = plan_attachments([_text_upload("log.txt", long_text)])

    (item,) = plan.items
    assert item.accepted is True
    assert item.text.truncated is True
    assert str(MAX_TEXT_CHARS) in item.text.content
    assert len(item.warnings) == 1
    assert "truncated" in item.warnings[0]


def test_text_at_exactly_max_chars_is_not_truncated():
    text = "x" * MAX_TEXT_CHARS

    plan = plan_attachments([_text_upload("log.txt", text)])

    (item,) = plan.items
    assert item.text.truncated is False
    assert item.warnings == ()


def test_rejects_non_utf8_text():
    upload = AttachmentUpload(
        filename="bad.txt", content_type="text/plain", data=b"\xff\xfe\x00"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert "UTF-8" in item.rejection_reason


# --- rejection: format, empty, size, content-type mismatch ----------------


def test_rejects_unsupported_extension():
    upload = AttachmentUpload(
        filename="report.pdf", content_type="application/pdf", data=b"%PDF-1.4"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert item.attachment_class is None
    assert "unsupported file type" in item.rejection_reason
    assert ".pdf" in item.rejection_reason


def test_rejects_m4a_as_unsupported_pending_a_dependency_decision():
    upload = AttachmentUpload(
        filename="memo.m4a", content_type="audio/mp4", data=b"\x00\x00\x00 ftypM4A "
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert item.attachment_class is None


def test_rejects_empty_file():
    upload = AttachmentUpload(filename="empty.txt", content_type="text/plain", data=b"")

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert "empty" in item.rejection_reason
    # extension-first classification is still reported on an empty-file
    # rejection - same typed-contract expectation as the MIME-mismatch case.
    assert item.attachment_class is AttachmentClass.TEXT


def test_rejects_empty_file_with_unsupported_extension_as_unclassified():
    upload = AttachmentUpload(
        filename="empty.pdf", content_type="application/pdf", data=b""
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert item.attachment_class is None
    assert "unsupported file type" in item.rejection_reason


def test_rejects_oversize_image():
    upload = _image_upload("huge.png", size=MAX_IMAGE_UPLOAD_BYTES + 1)

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert item.attachment_class is AttachmentClass.IMAGE
    assert "exceeds" in item.rejection_reason


def test_rejects_oversize_text_upload_before_decoding():
    upload = AttachmentUpload(
        filename="huge.txt",
        content_type="text/plain",
        data=b"x" * (MAX_TEXT_UPLOAD_BYTES + 1),
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert "exceeds" in item.rejection_reason


def test_rejects_audio_over_the_max_duration():
    upload = _audio_upload("long.wav", duration_seconds=MAX_AUDIO_SECONDS + 1)

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert item.attachment_class is AttachmentClass.AUDIO
    assert "exceeds" in item.rejection_reason


def test_rejects_corrupt_audio_bytes():
    upload = AttachmentUpload(
        filename="broken.wav", content_type="audio/wav", data=b"not a wav file"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert "could not read audio file" in item.rejection_reason


def test_rejects_mismatched_content_type():
    upload = AttachmentUpload(
        filename="notes.txt", content_type="application/pdf", data=b"hello"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert "does not match" in item.rejection_reason
    # extension-first classification is still reported on a MIME-mismatch
    # rejection - callers must not have to parse the class back out of the
    # message string.
    assert item.attachment_class is AttachmentClass.TEXT


def test_accepts_generic_content_type_by_trusting_the_extension():
    upload = AttachmentUpload(
        filename="notes.txt", content_type="application/octet-stream", data=b"hi"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True


def test_accepts_missing_content_type_by_trusting_the_extension():
    upload = AttachmentUpload(filename="notes.txt", content_type="", data=b"hi")

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True


# --- filename handling ------------------------------------------------


def test_normalizes_a_path_like_filename_to_its_basename():
    upload = AttachmentUpload(
        filename="../../etc/evil.txt", content_type="text/plain", data=b"hi"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.filename == "evil.txt"


def test_normalizes_a_windows_path_like_filename_to_its_basename():
    upload = AttachmentUpload(
        filename="C:\\Users\\someone\\secret.txt", content_type="text/plain", data=b"hi"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.filename == "secret.txt"


# --- batch ordering and per-turn caps --------------------------------------


def test_mixed_batch_preserves_input_order_and_rejects_selectively():
    uploads = [
        _text_upload("a.txt", "hello"),
        AttachmentUpload(filename="b.pdf", content_type="application/pdf", data=b"x"),
        _image_upload("c.png"),
    ]

    plan = plan_attachments(uploads)

    filenames = [item.filename for item in plan.items]
    accepted = [item.accepted for item in plan.items]
    assert filenames == ["a.txt", "b.pdf", "c.png"]
    assert accepted == [True, False, True]


def test_enforces_max_images_per_turn():
    uploads = [_image_upload(f"img{i}.png") for i in range(MAX_IMAGES_PER_TURN + 1)]

    plan = plan_attachments(uploads)

    accepted_flags = [item.accepted for item in plan.items]
    assert accepted_flags == [True] * MAX_IMAGES_PER_TURN + [False]
    assert "maximum" in plan.items[-1].rejection_reason


def test_enforces_max_audio_files_per_turn():
    uploads = [_audio_upload("a.wav"), _audio_upload("b.wav")]

    plan = plan_attachments(uploads)

    assert plan.items[0].accepted is True
    assert plan.items[1].accepted is False
    assert "maximum" in plan.items[1].rejection_reason


def test_enforces_max_total_attachments_per_turn_across_classes():
    uploads = [
        _image_upload("a.png"),
        _image_upload("b.png"),
        _image_upload("c.png"),
        _audio_upload("d.wav"),
        _text_upload("e.txt", "hello"),
    ]

    plan = plan_attachments(uploads)

    accepted_flags = [item.accepted for item in plan.items]
    assert accepted_flags == [True, True, True, True, False]
    assert plan.items[-1].filename == "e.txt"
    assert str(MAX_ATTACHMENTS_PER_TURN) in plan.items[-1].rejection_reason


def test_enforces_combined_upload_bytes_per_turn():
    per_file_size = MAX_TOTAL_UPLOAD_BYTES_PER_TURN // 3 + 1024
    uploads = [_image_upload(f"img{i}.png", size=per_file_size) for i in range(3)]

    plan = plan_attachments(uploads)

    assert [item.accepted for item in plan.items] == [True, True, False]
    assert "combined" in plan.items[-1].rejection_reason
