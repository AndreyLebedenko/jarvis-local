import asyncio

from jarvis.core.config import TtsLanguageSettings, TtsSettings
from manual.manual_check_bilingual_tts_production import (
    SAMPLES,
    ReportingEngine,
    reporting_builders,
    run_samples,
    stream_tokens,
)
from language_segments import segment_by_charset
from tts import BilingualTtsEngine, TtsOutput, build_tts_engine


class _FakeEngine:
    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        return text.encode()


def _bilingual_settings() -> TtsSettings:
    return TtsSettings(
        languages={
            "ru": TtsLanguageSettings(engine="silero", model="v3_1_ru"),
            "en": TtsLanguageSettings(engine="piper", model="en.onnx"),
        }
    )


def test_sample_catalog_exercises_mixed_charset_text():
    for sample in SAMPLES:
        languages = {segment.language for segment in segment_by_charset(sample.text)}

        assert languages == {"ru", "en"}


def test_stream_tokens_reassemble_to_the_original_text():
    for sample in SAMPLES:
        assert "".join(stream_tokens(sample.text)) == sample.text


async def test_reporting_engine_reports_and_delegates():
    reports = []

    engine = ReportingEngine(
        "piper", _FakeEngine(), lambda *args: reports.append(args)
    )

    assert await engine.synthesize("Hello.", "en") == b"Hello."
    assert reports == [("piper", "en", "Hello.")]


def test_reporting_builders_wrap_every_base_builder():
    settings = _bilingual_settings()
    reports = []
    base = {
        "silero": lambda route: _FakeEngine(),
        "piper": lambda route: _FakeEngine(),
    }

    builders = reporting_builders(
        settings, lambda *args: reports.append(args), base_builders=base
    )

    assert set(builders) == {"silero", "piper"}
    built = builders["piper"](settings.languages["en"])
    assert isinstance(built, ReportingEngine)
    assert asyncio.run(built.synthesize("Hi.", "en")) == b"Hi."
    assert reports == [("piper", "en", "Hi.")]


async def test_run_samples_reports_the_configured_engine_per_language_in_text_order():
    settings = _bilingual_settings()
    reports = []
    played = []

    async def fake_play(audio: bytes) -> None:
        played.append(audio.decode())

    base = {
        "silero": lambda route: _FakeEngine(),
        "piper": lambda route: _FakeEngine(),
    }
    engine = build_tts_engine(
        settings, reporting_builders(settings, lambda *args: reports.append(args), base)
    )
    assert isinstance(engine, BilingualTtsEngine)
    tts = TtsOutput(settings, engine=engine, play=fake_play)

    await run_samples(tts, SAMPLES)

    assert reports  # every synthesized unit was attributed to an engine
    assert all(
        (language == "ru" and label == "silero")
        or (language == "en" and label == "piper")
        for label, language, text in reports
    )
    # ordered playback: what was played is exactly what was reported, in order
    assert played == [text for _, _, text in reports]
