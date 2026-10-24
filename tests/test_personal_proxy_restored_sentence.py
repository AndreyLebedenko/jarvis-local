import dataclasses

import pytest

from jarvis.personal_proxy.restoration.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)

SECRET = "Анна Лебедева подтвердила встречу."


def _sentence():
    return RestoredSentence(SECRET, RestorationMethod.MODEL, False)


def test_repr_and_str_hide_the_text():
    sentence = _sentence()

    assert SECRET not in repr(sentence)
    assert SECRET not in str(sentence)
    assert "MODEL" in repr(sentence)


def test_a_restored_sentence_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _sentence().text = "other"


def test_the_methods_are_passthrough_model_and_substituted():
    assert {method.name for method in RestorationMethod} == {
        "PASSTHROUGH",
        "MODEL",
        "SUBSTITUTED",
    }
