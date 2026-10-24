import pytest

from jarvis.personal_proxy.common.findings import (
    Finding,
    GateCategory,
    GateStage,
)
from jarvis.personal_proxy.confirmation.confirmation_texts import offer_text
from jarvis.personal_proxy.reporting import service_texts
from jarvis.personal_proxy.reporting.service_blocks import NoticeBlock, NoticeKind
from jarvis.personal_proxy.reporting.service_texts import (
    SPOKEN_KINDS,
    notice_text,
    spoken_notice,
)

LANGUAGES = ["ru", "en", None, "de"]


def test_both_catalogs_have_the_same_keys():
    assert set(service_texts._RU) == set(service_texts._EN)


def test_every_notice_kind_but_the_offer_has_a_text_in_both_catalogs():
    for catalog in (service_texts._RU, service_texts._EN):
        for kind in NoticeKind:
            if kind is not NoticeKind.NOT_SENT:
                assert kind.value in catalog
        for kind in SPOKEN_KINDS - {NoticeKind.NOT_SENT}:
            assert f"{kind.value}.spoken" in catalog


def test_every_gate_category_is_named_in_both_catalogs():
    for catalog in (service_texts._RU, service_texts._EN):
        for category in GateCategory:
            assert f"category.{category.value}" in catalog


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("kind", list(NoticeKind))
def test_every_notice_has_a_shown_text(kind, language):
    assert notice_text(NoticeBlock(kind), language).strip()


def test_english_and_russian_differ_and_unknown_language_gets_russian():
    block = NoticeBlock(NoticeKind.NO_SPEECH)

    assert notice_text(block, "en") != notice_text(block, "ru")
    assert notice_text(block, "de") == notice_text(block, "ru")
    assert notice_text(block, None) == notice_text(block, "ru")
    assert notice_text(block, "en-US") == notice_text(block, "en")


@pytest.mark.parametrize("language", ["ru", "en"])
def test_the_offer_notice_reuses_the_task_8_offer_text_shown_and_spoken(language):
    block = NoticeBlock(NoticeKind.NOT_SENT)

    assert notice_text(block, language) == offer_text(language)
    assert spoken_notice(block, language) == offer_text(language)


@pytest.mark.parametrize("language", ["ru", "en"])
def test_only_the_listed_kinds_are_spoken(language):
    for kind in NoticeKind:
        spoken = spoken_notice(NoticeBlock(kind), language)
        assert (spoken is not None) is (kind in SPOKEN_KINDS)


def test_silent_kinds_are_the_ones_that_would_only_add_noise():
    assert NoticeKind.NO_SPEECH not in SPOKEN_KINDS
    assert NoticeKind.BUSY not in SPOKEN_KINDS
    assert NoticeKind.NOT_SENT in SPOKEN_KINDS
    assert NoticeKind.GATE_BLOCKED in SPOKEN_KINDS


FINDINGS = (
    Finding(GateCategory.PHONE, 1, 5, 18),
    Finding(GateCategory.EMAIL, 1, 30, 50),
)


def test_a_gate_notice_shows_categories_and_positions_never_a_value():
    block = NoticeBlock(NoticeKind.GATE_BLOCKED, FINDINGS)

    shown = notice_text(block, "en")

    assert "phone" in shown.lower()
    assert "email" in shown.lower() or "e-mail" in shown.lower()
    assert "5" in shown
    assert "18" in shown


def test_a_gate_notice_speaks_the_categories_without_positions():
    block = NoticeBlock(NoticeKind.GATE_BLOCKED, FINDINGS)

    spoken = spoken_notice(block, "en")

    assert "phone" in spoken.lower()
    assert "18" not in spoken


def test_a_gate_error_finding_names_the_stage_not_a_position():
    error = Finding(GateCategory.GATE_ERROR, -1, 0, 0, GateStage.PATTERNS)

    shown = notice_text(NoticeBlock(NoticeKind.GATE_BLOCKED, (error,)), "en")

    assert "patterns" in shown


def test_a_refusal_shows_the_reason_and_speaks_only_a_fixed_sentence():
    block = NoticeBlock(NoticeKind.REFUSED, reason="medical topic")

    assert "medical topic" in notice_text(block, "en")
    assert "medical topic" not in spoken_notice(block, "en")


def test_an_enum_detail_is_appended_as_its_value():
    block = NoticeBlock(NoticeKind.SANITIZE_FAILED, GateStage.PATTERNS)

    assert "patterns" in notice_text(block, "en")


def test_the_internal_error_wording_does_not_claim_that_nothing_or_something_was_sent():
    block = NoticeBlock(NoticeKind.INTERNAL_ERROR)

    spoken_en = spoken_notice(block, "en").casefold()
    spoken_ru = spoken_notice(block, "ru").casefold()
    assert "sent" not in spoken_en
    assert "отправ" not in spoken_ru
    assert "see the chat" in notice_text(block, "en").casefold()
    assert "в чате" in notice_text(block, "ru").casefold()
    assert "check what was sent" not in notice_text(block, "en").casefold()


def test_the_language_rule_is_public():
    from jarvis.personal_proxy.confirmation.confirmation_texts import is_english

    assert is_english("en-US") and not is_english("ru") and not is_english(None)
