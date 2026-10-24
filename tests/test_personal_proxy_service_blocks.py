import pytest

from jarvis.personal_proxy.common.findings import Finding, GateCategory
from jarvis.personal_proxy.reporting.service_blocks import (
    AnswerBlock,
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
    answer_block_of,
)
from jarvis.personal_proxy.restoration.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)

SECRET = "Марина Крылова marina@example.org"


def test_a_notice_holds_a_kind_and_an_enum_or_int_detail():
    assert NoticeBlock(NoticeKind.BUSY).detail is None
    assert NoticeBlock(NoticeKind.NOT_SENT, RestorationMethod.MODEL).detail
    assert NoticeBlock(NoticeKind.ANSWER_INCOMPLETE, 7).detail == 7
    finding = Finding(GateCategory.PHONE, 1, 2, 9)
    assert NoticeBlock(NoticeKind.GATE_BLOCKED, (finding,)).detail == (finding,)


@pytest.mark.parametrize("detail", ["text", b"bytes", ("a", "b"), {"k": "v"}])
def test_a_notice_refuses_a_detail_that_could_carry_content(detail):
    with pytest.raises(TypeError):
        NoticeBlock(NoticeKind.INTERNAL_ERROR, detail)


def test_a_notice_hides_its_reason_in_repr_and_str():
    block = NoticeBlock(NoticeKind.REFUSED, reason=SECRET)

    assert SECRET not in repr(block)
    assert SECRET not in str(block)
    assert block.reason == SECRET


def test_an_answer_block_carries_the_sentence_method_and_flag_and_hides_the_text():
    sentence = RestoredSentence(SECRET, RestorationMethod.SUBSTITUTED, True)

    block = answer_block_of(sentence)

    assert block == AnswerBlock(SECRET, RestorationMethod.SUBSTITUTED, True)
    assert SECRET not in repr(block)
    assert "SUBSTITUTED" in repr(block)


def test_a_dry_run_block_hides_every_personal_field():
    block = DryRunBlock(
        whisper_text=SECRET,
        checked_text=SECRET,
        doubts=(),
        would_ask=True,
        sanitized_text=SECRET,
        mapping={"<PERSON_1>": SECRET},
        verdict="send",
        reason=SECRET,
        gate_findings=(),
        messages=(("user", SECRET),),
    )

    assert "Марина" not in repr(block) + str(block)
    assert "example.org" not in repr(block) + str(block)
