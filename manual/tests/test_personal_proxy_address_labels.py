import pytest

from manual.personal_proxy.address_labels import address_is_right, base_id


def test_a_phrase_without_an_address_has_no_verdict():
    assert address_is_right("v2_card__owner", "любой текст") is None


@pytest.mark.parametrize(
    ("utterance_id", "output"),
    [
        ("id_email", "Пиши на почту ivan.petrov@primer.com."),
        ("id_email", "Пиши на почту Ivan.Petrov@example.com"),
        ("m_trade_house", "от info@trade-house.ru на адрес Марина"),
        ("m_github", "почту dvolkov@gmail.com, логин"),
        ("v2_email_underscore__owner", "на почту alex.smirnov_92@pochta.ru"),
    ],
)
def test_a_right_assembled_address_is_accepted(utterance_id, output):
    assert address_is_right(utterance_id, output) is True


@pytest.mark.parametrize(
    ("utterance_id", "output"),
    [
        ("v2_email_underscore__owner", "alex.smirnov@92.собака_почта.ru"),
        ("v2_email_underscore__eugene", "alex.smirnov@92sobakopochta.ru"),
        ("v2_email_underscore__baya", "alex.smirnov.92@sobakapochta.ru"),
        ("m_trade_house", "от info@sobakatradehouse.ru"),
        ("id_email", "Пиши на почту ivan.petrov@primer.ru"),
    ],
)
def test_a_wrongly_assembled_address_is_rejected(utterance_id, output):
    assert address_is_right(utterance_id, output) is False


def test_the_spoken_form_left_as_words_is_accepted():
    output = "Пиши на почту иван точка петров собака пример точка ком."

    assert address_is_right("id_email", output) is True


def test_base_id_drops_the_voice_suffix():
    assert base_id("v2_card__baya") == "v2_card"
    assert base_id("id_email") == "id_email"


def test_a_second_address_makes_the_phrase_wrong_even_if_the_first_is_right():
    output = "от info@trade-house.ru на адрес marina@mail.ru"

    assert address_is_right("m_trade_house", output) is False
