import soundfile as sf

from config import SoundCueSettings
from sound_cues import SoundCuePlayer, ensure_generated


def _settings_in(tmp_path) -> SoundCueSettings:
    return SoundCueSettings(
        listening=str(tmp_path / "listening.wav"),
        thinking=str(tmp_path / "thinking.wav"),
        speaking=str(tmp_path / "speaking.wav"),
        error=str(tmp_path / "error.wav"),
    )


def test_ensure_generated_creates_all_missing_cue_files(tmp_path):
    settings = _settings_in(tmp_path)

    ensure_generated(settings)

    for path_str in (settings.listening, settings.thinking, settings.speaking, settings.error):
        data, sample_rate = sf.read(path_str)
        assert sample_rate > 0
        assert len(data) > 0


def test_ensure_generated_does_not_overwrite_existing_file(tmp_path):
    settings = _settings_in(tmp_path)
    (tmp_path / "listening.wav").write_bytes(b"not-really-a-wav-but-untouched")

    ensure_generated(settings)

    assert (tmp_path / "listening.wav").read_bytes() == b"not-really-a-wav-but-untouched"


async def test_play_calls_play_file_with_configured_path(tmp_path):
    settings = _settings_in(tmp_path)
    calls = []

    async def fake_play_file(path: str) -> None:
        calls.append(path)

    player = SoundCuePlayer(settings, play_file=fake_play_file)

    await player.play("thinking")
    await player.wait_for_pending()  # play() is fire-and-forget - see module docstring

    assert calls == [settings.thinking]


async def test_play_skips_unknown_cue_without_raising():
    calls = []

    async def fake_play_file(path: str) -> None:
        calls.append(path)

    player = SoundCuePlayer(SoundCueSettings(), play_file=fake_play_file)

    await player.play("not-a-real-cue")

    assert calls == []
