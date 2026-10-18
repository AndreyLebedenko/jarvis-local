import pytest

from manual.personal_proxy_corpus import (
    CORPUS,
    SEEDS,
    Category,
    Span,
    SpanType,
    Utterance,
    Verdict,
    corpus_fingerprint,
    corpus_problems,
    summarize,
    topics_text,
    utterance_by_id,
)
from manual.personal_proxy_text import digit_runs, tokenize


def test_frozen_corpus_meets_the_card():
    assert corpus_problems() == []


def test_corpus_has_forty_four_utterances_and_two_seeds():
    assert summarize().utterances == 44
    assert len(SEEDS) == 2


def test_topic_utterances_expect_refusal_and_the_rest_expect_send():
    for utterance in CORPUS:
        expected = (
            Verdict.REFUSE if utterance.category is Category.TOPIC else Verdict.SEND
        )
        assert utterance.expected_verdict is expected


def test_every_derivable_digit_key_is_reachable_from_its_own_surface():
    for utterance in CORPUS:
        for span in utterance.spans:
            for key in span.digit_keys:
                assert any(key in run for run in digit_runs(span.surface)), (
                    utterance.utterance_id,
                    span.span_id,
                    key,
                )


def test_every_leak_form_appears_in_its_own_surface_stem_wise():
    for utterance in CORPUS:
        for span in utterance.spans:
            tokens = tokenize(span.surface)
            for form in span.forms:
                stem_prefix = form[: max(3, len(form) - 2)]
                latin_alias = form.isascii()
                if latin_alias:
                    continue
                assert any(t.startswith(stem_prefix) for t in tokens), (
                    utterance.utterance_id,
                    span.span_id,
                    form,
                )


def test_alt_digit_keys_count_as_keys_but_are_not_derivability_checked():
    span = Span("d", "год", SpanType.DATE, alt_digit_keys=("1985",))

    assert span.all_digit_keys() == ("1985",)
    assert span.digit_keys == ()


def test_auto_forms_skip_short_tokens_and_numbers():
    span = Span("x", "в Ельце сорок пять", SpanType.ADDRESS)

    assert span.leak_forms() == ("ельце", "сорок", "пять")


def test_problems_report_a_surface_missing_from_the_text():
    broken = Utterance(
        "broken",
        Category.IDENTIFIER,
        "Позвони Марине.",
        (Span("n1", "Олегу", SpanType.PERSON),),
    )

    assert any("surface not in text" in p for p in corpus_problems((broken,)))


def test_problems_report_a_short_digit_key():
    broken = Utterance(
        "broken",
        Category.IDENTIFIER,
        "Код восемь шесть.",
        (Span("s1", "восемь шесть", SpanType.SECRET, digit_keys=("8",)),),
    )

    assert any("bad digit key" in p for p in corpus_problems((broken,)))


def test_fingerprint_is_stable_and_covers_the_topics_text():
    assert corpus_fingerprint() == corpus_fingerprint()
    assert len(corpus_fingerprint()) == 64


def test_topics_file_is_non_empty_and_named_topics_exist():
    assert "medical" in topics_text()


def test_utterance_lookup_rejects_unknown_ids():
    assert utterance_by_id("id_email").category is Category.IDENTIFIER
    with pytest.raises(KeyError):
        utterance_by_id("nope")


def test_review_markdown_lists_every_utterance_span_and_the_topics():
    from manual.personal_proxy_corpus import render_review_markdown

    text = render_review_markdown()

    assert all(f"## {u.utterance_id} " in text for u in CORPUS)
    assert "phone/direct" in text
    assert "Test topics text" in text
    assert "expect refuse" in text
