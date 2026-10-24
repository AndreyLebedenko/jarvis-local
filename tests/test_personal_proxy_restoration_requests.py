from jarvis.core.config import GenerationOptions
from jarvis.personal_proxy.restoration.restoration_requests import (
    NUM_PREDICT,
    RESTORE_RULES,
    build_restoration_request,
)
from manual.personal_proxy import restoration as spike

MAPPING = {"<PERSON_1>": "Анна Лебедева", "<PHONE_1>": "8 915 234 56 78"}
SENTENCE = "<PERSON_1> оставила номер <PHONE_1>."


def test_the_rules_equal_the_spike_block_r_rules():
    assert RESTORE_RULES == spike.RESTORE_RULES


def test_the_request_is_text_only_system_plus_user_without_a_format():
    request = build_restoration_request(SENTENCE, MAPPING, 0.618)

    assert request.system == RESTORE_RULES
    assert request.audio_base64 == ""
    assert request.response_format is None
    assert SENTENCE in request.prompt
    assert SENTENCE not in request.system


def test_the_prompt_equals_the_spike_user_message():
    item = spike.RestorationItem("x", SENTENCE, dict(MAPPING))

    request = build_restoration_request(SENTENCE, MAPPING, 0.618)

    assert request.prompt == spike.restoration_messages(item)[1]["content"]


def test_the_options_are_the_temperature_and_the_one_sentence_length_cap():
    request = build_restoration_request(SENTENCE, MAPPING, 0.25)

    assert request.options == GenerationOptions(temperature=0.25, num_predict=512)
    assert NUM_PREDICT == 512


def test_the_prompt_carries_only_the_entries_it_is_given():
    request = build_restoration_request(SENTENCE, {"<PERSON_1>": "Анна Лебедева"}, 0.1)

    assert "Анна Лебедева" in request.prompt
    assert "8 915" not in request.prompt


def test_the_repr_hides_the_text():
    request = build_restoration_request(SENTENCE, MAPPING, 0.1)

    assert "Лебедева" not in repr(request)
