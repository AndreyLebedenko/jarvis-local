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
    MAX_TEXT_FILES_PER_TURN,
    MAX_TEXT_UPLOAD_BYTES,
    MAX_TOTAL_UPLOAD_BYTES_PER_TURN,
    AttachmentClass,
    AttachmentPlan,
    AttachmentPlanItem,
    AttachmentUpload,
    PlannedTextPart,
    compose_turn_images,
    compose_turn_text,
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


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def _image_upload(filename: str = "photo.png", size: int = 100) -> AttachmentUpload:
    data = PNG_SIGNATURE + b"x" * size
    return AttachmentUpload(filename=filename, content_type="image/png", data=data)


def _jpeg_upload(filename: str = "photo.jpg", size: int = 100) -> AttachmentUpload:
    data = JPEG_SIGNATURE + b"x" * size
    return AttachmentUpload(filename=filename, content_type="image/jpeg", data=data)


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


def test_accepts_a_jpeg_image_and_base64_encodes_the_raw_bytes():
    upload = _jpeg_upload("photo.jpg")

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True
    assert item.attachment_class is AttachmentClass.IMAGE
    assert base64.b64decode(item.image.base64_data) == upload.data


def test_accepts_jpeg_bytes_behind_a_png_extension():
    # The byte sniff is class-level, matching the class-level MIME check:
    # a renamed-but-valid image still reaches the model as working bytes.
    upload = AttachmentUpload(
        filename="renamed.png",
        content_type="image/png",
        data=JPEG_SIGNATURE + b"x" * 50,
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is True


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


def test_rejects_image_bytes_without_a_png_or_jpeg_signature():
    upload = AttachmentUpload(
        filename="fake.png", content_type="image/png", data=b"this is not an image"
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert item.attachment_class is AttachmentClass.IMAGE
    assert item.image is None
    assert "not a valid PNG or JPEG image" in item.rejection_reason


def test_rejects_truncated_image_signature():
    upload = AttachmentUpload(
        filename="cut.png", content_type="image/png", data=PNG_SIGNATURE[:4]
    )

    plan = plan_attachments([upload])

    (item,) = plan.items
    assert item.accepted is False
    assert "not a valid PNG or JPEG image" in item.rejection_reason


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


def test_enforces_max_text_files_per_turn():
    uploads = [
        _text_upload(f"note{i}.txt", "hello")
        for i in range(MAX_TEXT_FILES_PER_TURN + 1)
    ]

    plan = plan_attachments(uploads)

    accepted_flags = [item.accepted for item in plan.items]
    assert accepted_flags == [True] * MAX_TEXT_FILES_PER_TURN + [False]
    assert "maximum" in plan.items[-1].rejection_reason
    assert plan.items[-1].text is None


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


# --- composing the model-facing turn text -----------------------------


def test_composes_typed_message_before_attached_text():
    plan = plan_attachments([_text_upload("notes.txt", "meeting notes")])

    composed = compose_turn_text("what should I do with this?", plan)

    assert composed.startswith("what should I do with this?")
    typed_end = composed.index("what should I do with this?") + len(
        "what should I do with this?"
    )
    assert composed.index("[Attached file: notes.txt]") > typed_end


def test_composes_an_image_cue_naming_the_file_without_binary_data():
    upload = _image_upload("photo.png")
    plan = plan_attachments([upload])

    composed = compose_turn_text("describe this image", plan)

    assert composed == "describe this image\n\n[Attached image: photo.png]"
    assert plan.items[0].image.base64_data not in composed


def test_composes_image_cues_and_text_blocks_in_upload_order():
    uploads = [
        _image_upload("first.png"),
        _text_upload("notes.txt", "meeting notes"),
        _jpeg_upload("second.jpg"),
    ]

    plan = plan_attachments(uploads)
    composed = compose_turn_text("hello", plan)

    first_cue = composed.index("[Attached image: first.png]")
    text_block = composed.index("[Attached file: notes.txt]")
    second_cue = composed.index("[Attached image: second.jpg]")
    assert composed.startswith("hello")
    assert first_cue < text_block < second_cue


def test_compose_excludes_the_cue_for_a_rejected_image():
    uploads = [
        AttachmentUpload(
            filename="fake.png", content_type="image/png", data=b"not an image"
        ),
    ]

    plan = plan_attachments(uploads)
    composed = compose_turn_text("hello", plan)

    assert composed == "hello"


def test_composes_attachment_text_alone_when_typed_message_is_empty():
    plan = plan_attachments([_text_upload("notes.txt", "meeting notes")])

    composed = compose_turn_text("", plan)

    assert composed == plan.items[0].text.content
    assert not composed.startswith("\n\n")


def test_compose_excludes_rejected_text_and_contributes_nothing_for_audio():
    uploads = [
        AttachmentUpload(
            filename="bad.txt", content_type="text/plain", data=b"\xff\xfe\x00"
        ),
        _audio_upload("memo.wav"),
    ]

    plan = plan_attachments(uploads)
    composed = compose_turn_text("hello", plan)

    assert composed == "hello"


def test_compose_makes_truncation_visible_in_the_composed_text():
    long_text = "x" * (MAX_TEXT_CHARS + 500)
    plan = plan_attachments([_text_upload("log.txt", long_text)])

    composed = compose_turn_text("summarize this", plan)

    assert str(MAX_TEXT_CHARS) in composed
    assert "truncated" in composed


def test_compose_excludes_a_rejected_item_even_if_it_carries_a_text_part():
    # plan_attachments() never actually builds a rejected item with `text`
    # set, but compose_turn_text() must not rely on that as an implicit
    # invariant - it checks item.accepted directly.
    plan = AttachmentPlan(
        items=(
            AttachmentPlanItem(
                filename="rejected.txt",
                attachment_class=AttachmentClass.TEXT,
                accepted=False,
                text=PlannedTextPart(content="[should not appear]", truncated=False),
                rejection_reason="rejected.txt: some policy violation.",
            ),
        )
    )

    composed = compose_turn_text("hello", plan)

    assert composed == "hello"


def test_compose_turn_images_returns_base64_media_in_upload_order():
    uploads = [
        _image_upload("first.png"),
        _text_upload("notes.txt", "meeting notes"),
        _jpeg_upload("second.jpg"),
    ]

    plan = plan_attachments(uploads)
    images = compose_turn_images(plan)

    assert images == (
        base64.b64encode(uploads[0].data).decode(),
        base64.b64encode(uploads[2].data).decode(),
    )


def test_compose_turn_images_excludes_rejected_images():
    uploads = [
        AttachmentUpload(
            filename="fake.png", content_type="image/png", data=b"not an image"
        ),
        _image_upload("real.png"),
    ]

    plan = plan_attachments(uploads)
    images = compose_turn_images(plan)

    assert images == (base64.b64encode(uploads[1].data).decode(),)


def test_compose_turn_images_is_empty_for_a_text_only_plan():
    plan = plan_attachments([_text_upload("notes.txt", "hello")])

    assert compose_turn_images(plan) == ()


def test_compose_preserves_plan_item_order_for_multiple_text_parts():
    plan = AttachmentPlan(
        items=(
            AttachmentPlanItem(
                filename="first.txt",
                attachment_class=AttachmentClass.TEXT,
                accepted=True,
                text=PlannedTextPart(content="[first part]", truncated=False),
            ),
            AttachmentPlanItem(
                filename="second.txt",
                attachment_class=AttachmentClass.TEXT,
                accepted=True,
                text=PlannedTextPart(content="[second part]", truncated=False),
            ),
        )
    )

    composed = compose_turn_text("typed message", plan)

    assert composed == "typed message\n\n[first part]\n\n[second part]"
