import logging

import soundfile as sf

from config import SoundCueSettings
from sound_cues import SoundCuePlayer, ensure_generated


def _settings_in(tmp_path) -> SoundCueSettings:
    return SoundCueSettings(
        listening=str(tmp_path / "listening.wav"),
        thinking=str(tmp_path / "thinking.wav"),
        speaking=str(tmp_path / "speaking.wav"),
        error=str(tmp_path / "error.wav"),
        clipboard=str(tmp_path / "clipboard.wav"),
        input_error=str(tmp_path / "input_error.wav"),
        mic_sleep=str(tmp_path / "mic_sleep.wav"),
        mic_wake=str(tmp_path / "mic_wake.wav"),
    )


def test_ensure_generated_creates_all_missing_cue_files(tmp_path):
    settings = _settings_in(tmp_path)

    ensure_generated(settings)

    for path_str in (
        settings.listening,
        settings.thinking,
        settings.speaking,
        settings.error,
        settings.clipboard,
        settings.input_error,
        settings.mic_sleep,
        settings.mic_wake,
    ):
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


async def test_play_calls_play_file_for_each_v1_1_cue(tmp_path):
    settings = _settings_in(tmp_path)
    calls = []

    async def fake_play_file(path: str) -> None:
        calls.append(path)

    player = SoundCuePlayer(settings, play_file=fake_play_file)

    for cue in ("clipboard", "input_error", "mic_sleep", "mic_wake"):
        await player.play(cue)
    await player.wait_for_pending()

    assert set(calls) == {
        settings.clipboard,
        settings.input_error,
        settings.mic_sleep,
        settings.mic_wake,
    }


async def test_play_skips_unknown_cue_without_raising():
    calls = []

    async def fake_play_file(path: str) -> None:
        calls.append(path)

    player = SoundCuePlayer(SoundCueSettings(), play_file=fake_play_file)

    await player.play("not-a-real-cue")

    assert calls == []


# --- observability (task-10 human review: INFO-level logging was silently
# dropped process-wide - nothing configured a handler for it) --------------


async def test_play_logs_an_info_message_naming_the_cue(tmp_path, caplog):
    settings = _settings_in(tmp_path)

    async def fake_play_file(path: str) -> None:
        pass

    player = SoundCuePlayer(settings, play_file=fake_play_file)

    with caplog.at_level(logging.INFO, logger="sound_cues"):
        await player.play("input_error")
        await player.wait_for_pending()

    assert any("input_error" in record.message for record in caplog.records)


def test_input_error_cue_is_not_a_single_short_blip(tmp_path):
    """Regression for a human-reported perceptibility issue: the original
    input_error cue was a single 0.1s tone that was not reliably audible
    during manual testing, unlike every other v1.1 cue (all multi-segment
    with a longer total duration). Asserts the regenerated cue is
    meaningfully longer, without pinning down an exact waveform."""
    settings = _settings_in(tmp_path)

    ensure_generated(settings)

    data, sample_rate = sf.read(settings.input_error)
    assert len(data) / sample_rate > 0.15
