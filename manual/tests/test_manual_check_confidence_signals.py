from manual import manual_check_confidence_signals as harness


def test_word_pairs_keep_the_leading_space_of_each_word():
    document = {"words": [{"word": " Привет", "probability": 0.9}]}

    assert harness.word_pairs(document) == [(" Привет", 0.9)]


def test_texts_are_the_same_regardless_of_whitespace():
    assert harness.same_text("a  b\n", " a b")
    assert not harness.same_text("a b", "a c")


def test_sample_files_are_named_by_subject_temperature_and_seed():
    assert (
        harness.sample_name("id_email", (0.618, 19210)) == "id_email-t0.618-s19210.json"
    )


def test_second_corpus_setup_knows_its_ids_and_uses_its_own_fingerprint():
    import argparse

    from manual.personal_proxy.corpus_v2 import corpus_v2_fingerprint

    setup = harness.setup_for(argparse.Namespace(corpus="v2"))

    assert "v2_card__baya" in setup.ids()
    assert setup.lookup("v2_card__baya").utterance_id == "v2_card__baya"
    assert setup.lookup("id_email") is None
    assert setup.fingerprint == corpus_v2_fingerprint()
    assert not setup.first


def test_first_corpus_setup_keeps_the_controls_path():
    import argparse

    setup = harness.setup_for(argparse.Namespace(corpus="v1"))

    assert setup.first
    assert setup.lookup("id_email") is not None
