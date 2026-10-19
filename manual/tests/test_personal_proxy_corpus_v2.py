from manual.personal_proxy.corpus import CORPUS
from manual.personal_proxy.corpus_v2 import (
    CORPUS_V2,
    OWNER_VOICE,
    PHRASES,
    VOICES,
    corpus_v2_fingerprint,
    corpus_v2_problems,
    utterance_v2_by_id,
    utterances_of_voice,
    voice_of,
    voiced_id,
)


def test_corpus_is_sound():
    assert corpus_v2_problems() == []


def test_every_phrase_exists_in_every_voice():
    assert len(CORPUS_V2) == len(PHRASES) * len(VOICES)
    for voice in VOICES:
        assert len(utterances_of_voice(voice)) == len(PHRASES)


def test_voices_read_the_same_text_with_the_same_spans():
    owner = {voice_of(u.utterance_id) for u in CORPUS_V2}
    by_phrase = {}
    for u in CORPUS_V2:
        by_phrase.setdefault(u.utterance_id.split("__")[0], set()).add(
            (u.text, u.spans)
        )

    assert owner == set(VOICES)
    assert all(len(variants) == 1 for variants in by_phrase.values())


def test_ids_do_not_collide_with_the_first_corpus():
    first = {u.utterance_id for u in CORPUS}

    assert not first & {u.utterance_id for u in CORPUS_V2}


def test_voiced_id_round_trips_through_voice_of():
    assert voice_of(voiced_id("v2_card", OWNER_VOICE)) == OWNER_VOICE


def test_lookup_by_id_finds_the_voiced_utterance():
    assert utterance_v2_by_id("v2_card__baya").utterance_id == "v2_card__baya"


def test_fingerprint_is_stable():
    assert corpus_v2_fingerprint() == corpus_v2_fingerprint()
