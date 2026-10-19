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
