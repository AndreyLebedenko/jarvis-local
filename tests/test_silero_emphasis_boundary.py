import pytest
import torch

from jarvis.audio.replay import ReplayPlayer, TextReply
from jarvis.audio.tts_silero import SileroEngine
from jarvis.core.config import SileroTtsSettings, TtsSettings


class _RecordingModel:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> torch.Tensor:
        self.texts.append(text)
        return torch.zeros(100)


async def _text_sent_to_the_model(text: str, **route_fields) -> str:
    model = _RecordingModel()
    engine = SileroEngine(
        SileroTtsSettings(**route_fields), model_loader=lambda route: model
    )

    await engine.synthesize(text)

    (sent,) = model.texts
    return sent


def test_emphasis_is_off_by_default():
    assert SileroTtsSettings().emphasis is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ты *правда* *пришёл*?", "Ты правда пришёл?"),
        ("Это **важно** понимать.", "Это важно понимать."),
        ("*Организаторы прислали билеты?", "Организаторы прислали билеты?"),
    ],
    ids=["markers", "markdown-bold", "stray-asterisk"],
)
async def test_model_receives_no_asterisk_when_emphasis_is_off(text, expected):
    assert await _text_sent_to_the_model(text) == expected


async def test_question_markers_reach_the_model_when_emphasis_is_on():
    sent = await _text_sent_to_the_model(
        "Твой брат всё ещё *живёт* в *Лондоне*?", emphasis=True
    )

    assert sent == "Твой брат всё ещё *живёт* в *Лондоне*?"


async def test_only_the_first_statement_marker_reaches_the_model_when_emphasis_is_on():
    sent = await _text_sent_to_the_model("Курьер *привёз* *заказ*.", emphasis=True)

    assert sent == "Курьер *привёз* заказ."


async def test_markdown_bold_is_stripped_even_when_emphasis_is_on():
    sent = await _text_sent_to_the_model("Это **важно** понимать.", emphasis=True)

    assert sent == "Это важно понимать."


async def test_digit_marker_is_spelled_out_before_it_is_normalized():
    sent = await _text_sent_to_the_model("Он купил *3* билета.", emphasis=True)

    assert sent == "Он купил *три* билета."


async def test_marker_that_spells_out_to_several_words_loses_its_asterisks():
    sent = await _text_sent_to_the_model("Он купил *21* билет.", emphasis=True)

    assert sent == "Он купил двадцать один билет."


async def test_latin_marker_is_transliterated_before_it_is_normalized():
    sent = await _text_sent_to_the_model("Это *API* работает.", emphasis=True)

    assert sent == "Это *апи* работает."


async def test_non_russian_silero_route_strips_when_emphasis_is_off():
    sent = await _text_sent_to_the_model(
        "It is *very* good.", model="v3_en", language="en", speaker="en_0"
    )

    assert sent == "It is very good."


async def test_non_russian_silero_route_keeps_a_marker_when_emphasis_is_on():
    sent = await _text_sent_to_the_model(
        "It is *very* good.",
        model="v3_en",
        language="en",
        speaker="en_0",
        emphasis=True,
    )

    assert sent == "It is *very* good."


async def _replay_through_an_emphasis_engine(reply: TextReply) -> list[str]:
    model = _RecordingModel()
    engine = SileroEngine(
        SileroTtsSettings(emphasis=True), model_loader=lambda route: model
    )

    async def discard(wav_bytes: bytes) -> None:
        return None

    player = ReplayPlayer(TtsSettings(), engine, play=discard)
    await player.replay(reply)
    await player.wait_for_pending()
    return model.texts


async def test_trusted_reply_reaches_the_model_with_its_markers():
    text = "Твой брат всё ещё *живёт* в *Лондоне*?"

    sent = await _replay_through_an_emphasis_engine(
        TextReply(text, emphasis_trusted=True)
    )

    assert sent == [text]


async def test_untrusted_reply_loses_its_asterisks_even_with_emphasis_on():
    sent = await _replay_through_an_emphasis_engine(
        TextReply("Твой брат всё ещё *живёт* в *Лондоне*?")
    )

    assert sent == ["Твой брат всё ещё живёт в Лондоне?"]
