import json
from dataclasses import replace

import numpy as np
import pytest

from jarvis.core.config import BackendSettings, PersonalProxySettings, Settings
from jarvis.personal_proxy.stt.speech_guard import SpeechProbabilities
from jarvis.personal_proxy.stt.stt_result import Transcription
from manual.personal_proxy.corpus import CORPUS
from manual.personal_proxy.doubt_trigger import (
    EXPECTED_ERRORS,
    EXPECTED_RECORDINGS,
    MAX_ASKED_SHARE,
    MIN_COVERED,
    MIN_NAMED,
    Observation,
    Verdict,
    config_problems,
    evaluate,
    render,
)

NAMED_ERROR_IDS = (
    "id_letter_long",
    "id_two_people_phone",
    "m_github",
    "m_trade_house",
    "n_short_translate",
    "v2_email_underscore",
)
NAMING_FRAGMENT = {
    "id_letter_long": "ооо альфтеррейт",
    "id_two_people_phone": "912 345",
    "m_github": "dvolkov",
    "m_trade_house": "info",
    "n_short_translate": "apple",
    "v2_email_underscore": "smirnov",
}


def _observations(*, asked, errors_asked, errors_named, total=60, errors=7):
    """`errors` error recordings (the first `errors_asked` of them asked, the
    first `errors_named` of those naming the wrong fragment) and the rest good;
    `asked` is the total number of asked recordings."""
    items = []
    error_ids = [*NAMED_ERROR_IDS, "id_extra"][:errors]
    for index, subject_id in enumerate(error_ids):
        is_asked = index < errors_asked
        names = is_asked and index < errors_named
        fragments = (NAMING_FRAGMENT.get(subject_id, "x"),) if names else ("zzz",)
        items.append(
            Observation(subject_id, True, is_asked, fragments if is_asked else ())
        )
    good_asked = asked - errors_asked
    for index in range(total - errors):
        is_asked = index < good_asked
        items.append(Observation(f"good_{index}", False, is_asked, ("q",) * is_asked))
    return items


def test_the_frozen_rule_constants_are_the_cards_numbers():
    assert MAX_ASKED_SHARE == 0.27
    assert MIN_COVERED == 6
    assert MIN_NAMED == 4
    assert EXPECTED_RECORDINGS == 60
    assert EXPECTED_ERRORS == 7


def test_numbers_inside_the_rule_keep_the_threshold():
    result = evaluate(_observations(asked=16, errors_asked=7, errors_named=5))

    assert result.verdict is Verdict.KEEP
    assert (result.total, result.asked, result.errors) == (60, 16, 7)
    assert (result.covered, result.named) == (7, 5)
    assert result.asked_share == pytest.approx(16 / 60)


def test_exactly_at_each_limit_still_keeps_the_threshold():
    result = evaluate(_observations(asked=16, errors_asked=6, errors_named=4))

    assert result.verdict is Verdict.KEEP


def test_one_ask_over_the_share_sends_the_numbers_to_the_owner():
    result = evaluate(_observations(asked=17, errors_asked=7, errors_named=7))

    assert result.verdict is Verdict.NUMBERS_TO_OWNER


def test_too_few_covered_errors_send_the_numbers_to_the_owner():
    result = evaluate(_observations(asked=10, errors_asked=5, errors_named=5))

    assert result.verdict is Verdict.NUMBERS_TO_OWNER


def test_too_few_named_wrong_fragments_send_the_numbers_to_the_owner():
    result = evaluate(_observations(asked=10, errors_asked=7, errors_named=3))

    assert result.verdict is Verdict.NUMBERS_TO_OWNER


def test_naming_counts_only_recordings_whose_asked_doubts_quote_the_wrong_fragment():
    result = evaluate(_observations(asked=10, errors_asked=7, errors_named=2))

    assert result.named == 2


def test_an_unasked_error_is_not_covered_and_not_named():
    result = evaluate(_observations(asked=10, errors_asked=4, errors_named=4))

    assert (result.covered, result.named) == (4, 4)


def test_a_different_number_of_recordings_is_not_comparable_with_the_rule():
    result = evaluate(_observations(asked=10, errors_asked=7, errors_named=7, total=59))

    assert result.verdict is Verdict.NOT_COMPARABLE


def test_a_different_number_of_errors_is_not_comparable_with_the_rule():
    result = evaluate(_observations(asked=10, errors_asked=6, errors_named=6, errors=6))

    assert result.verdict is Verdict.NOT_COMPARABLE


def test_an_empty_set_is_not_comparable():
    assert evaluate([]).verdict is Verdict.NOT_COMPARABLE


def test_the_report_gives_the_numbers_the_limits_and_the_verdict():
    observations = _observations(asked=17, errors_asked=7, errors_named=5)

    text = render(evaluate(observations))

    assert "17/60" in text
    assert "0.27" in text
    assert "7 of 7" in text
    assert "5 of 7" in text
    assert "numbers_to_owner" in text.lower()
    assert "do not tune" in text.lower()


# --- the configuration the run needs ------------------------------------------


def _settings(flash=True, cache="q8_0", threshold=1):
    return replace(
        Settings(),
        backend=BackendSettings(flash_attention=flash, kv_cache_type=cache),
        personal_proxy=PersonalProxySettings(doubt_min_listed=threshold),
    )


def test_the_spike_configuration_has_no_problems():
    assert config_problems(_settings()) == []


@pytest.mark.parametrize(
    "settings, key",
    [
        (_settings(flash=None), "flash_attention"),
        (_settings(flash=False), "flash_attention"),
        (_settings(cache=None), "kv_cache_type"),
        (_settings(cache="f16"), "kv_cache_type"),
        (_settings(threshold=2), "doubt_min_listed"),
    ],
)
def test_a_configuration_other_than_the_frozen_one_is_named_by_its_key(settings, key):
    problems = config_problems(settings)

    assert any(key in problem for problem in problems)


# --- observing one recording --------------------------------------------------


class _Backend:
    def __init__(self, *replies):
        self._replies = list(replies)

    async def complete(self, request):
        return self._replies.pop(0)


class _Engine:
    def __init__(self, text):
        self._text = text

    def transcribe(self, clip):
        return Transcription(text=self._text, words=(), segments=())


def _probabilities(windows):
    def source(clip):
        return SpeechProbabilities(values=[1.0] * windows, window_seconds=0.032)

    return source


def _judge(fragments):
    return json.dumps({"uncertain_fragments": fragments, "confidence": 0.9})


GITHUB = next(u for u in CORPUS if u.utterance_id == "m_github")
CLIP = np.zeros(16000, dtype=np.float32)


async def _observe(backend, windows=20, text=GITHUB.text):
    from manual.manual_check_doubt_trigger import observe

    return await observe(
        GITHUB,
        CLIP,
        _Engine(text),
        _probabilities(windows),
        backend,
        Settings(),
    )


async def test_a_good_recording_with_a_listed_doubt_is_asked_and_not_an_error():
    backend = _Backend(GITHUB.text, _judge(["dvolkov"]))

    observation = await _observe(backend)

    assert observation == Observation("m_github", False, True, ("dvolkov",))


async def test_a_wrong_checked_text_with_no_doubt_is_an_unasked_error():
    wrong = "Мой логин на GitHub это ivan, а почту я указал ivan собака mail точка com."
    backend = _Backend(wrong, _judge([]))

    observation = await _observe(backend)

    assert observation.error is True
    assert observation.asked is False
    assert observation.fragments == ()


async def test_a_clip_the_speech_guard_rejects_is_not_observed():
    backend = _Backend()

    assert await _observe(backend, windows=2) is None


def test_the_harness_needs_a_config_file_and_defaults_the_two_recording_directories():
    from pathlib import Path

    from manual import manual_check_doubt_trigger as harness

    args = harness.build_parser().parse_args(["--config", "c.toml", "run"])

    assert args.config == Path("c.toml")
    assert args.v1_wavs == Path("personal_proxy_corpus_wavs")
    assert args.v2_wavs == Path("personal_proxy_corpus_v2_wavs")


def test_the_labeled_recordings_are_the_sixty_utterances_with_spans():
    from manual.personal_proxy.corpus_v2 import CORPUS_V2

    labeled = [u for u in (*CORPUS, *CORPUS_V2) if u.spans]

    assert len(labeled) == EXPECTED_RECORDINGS
