import asyncio
import io

import numpy as np
import pytest
import soundfile as sf

from manual.personal_proxy_audio import MANIFEST_NAME, WavDirectory, wav_path
from manual.personal_proxy_corpus import CORPUS
from manual.personal_proxy_recorder import (
    Choice,
    RecordingDirectoryError,
    load_entries,
    pending,
    record_corpus,
    take_advice,
)


def _wav(seconds=1.0, value=0.01):
    buffer = io.BytesIO()
    sf.write(
        buffer,
        np.full(int(16000 * seconds), value, dtype=np.float32),
        16000,
        format="WAV",
        subtype="PCM_16",
    )
    return buffer.getvalue()


class FakeSource:
    def __init__(self, takes):
        self._takes = list(takes)
        self.calls = 0

    async def next_take(self, timeout_seconds):
        self.calls += 1
        return self._takes.pop(0) if self._takes else _wav()


class FakeInteraction:
    def __init__(self, choices):
        self._choices = list(choices)
        self.announced = []
        self.played = []
        self.infos = []
        self.advice_seen = []

    async def announce(self, index, total, utterance):
        self.announced.append((index, total, utterance.utterance_id))

    async def wait_ready(self):
        return None

    async def review(self, seconds, advice):
        self.advice_seen.append(advice)
        return self._choices.pop(0) if self._choices else Choice.ACCEPT

    def play(self, wav):
        self.played.append(wav)

    def info(self, message):
        self.infos.append(message)


def _record(source, interaction, directory, **kwargs):
    return asyncio.run(record_corpus(source, interaction, directory, **kwargs))


def test_recording_everything_produces_a_verifiable_directory(tmp_path):
    summary = _record(FakeSource([]), FakeInteraction([]), tmp_path)

    assert (summary.recorded, summary.skipped, summary.quit_early) == (44, 0, False)
    assert WavDirectory(tmp_path).duration_for(CORPUS[0].utterance_id) == 1.0


def test_utterances_are_announced_in_corpus_order_with_progress(tmp_path):
    interaction = FakeInteraction([])

    _record(FakeSource([]), interaction, tmp_path)

    assert interaction.announced[0] == (1, 44, CORPUS[0].utterance_id)
    assert interaction.announced[-1] == (44, 44, CORPUS[-1].utterance_id)


def test_redo_replaces_the_take_before_it_is_saved(tmp_path):
    first, second = _wav(1.0, 0.01), _wav(1.0, 0.02)
    source = FakeSource([first, second])
    interaction = FakeInteraction([Choice.REDO])

    _record(source, interaction, tmp_path)

    saved = wav_path(tmp_path, CORPUS[0].utterance_id).read_bytes()
    assert saved == second
    assert source.calls >= 2


def test_play_replays_the_take_without_recording_again(tmp_path):
    take = _wav()
    source = FakeSource([take])
    interaction = FakeInteraction([Choice.PLAY])

    _record(source, interaction, tmp_path)

    assert interaction.played == [take]


def test_a_missing_capture_asks_again(tmp_path):
    class SilentThenSpeech(FakeSource):
        async def next_take(self, timeout_seconds):
            self.calls += 1
            return None if self.calls == 1 else _wav()

    interaction = FakeInteraction([])

    _record(SilentThenSpeech([]), interaction, tmp_path)

    assert any("Nothing was captured" in message for message in interaction.infos)


def test_quitting_keeps_what_was_accepted_so_far(tmp_path):
    interaction = FakeInteraction([Choice.ACCEPT, Choice.ACCEPT, Choice.QUIT])

    summary = _record(FakeSource([]), interaction, tmp_path)

    assert (summary.recorded, summary.quit_early) == (2, True)
    assert set(load_entries(tmp_path)) == {
        CORPUS[0].utterance_id,
        CORPUS[1].utterance_id,
    }


def test_a_second_session_records_only_what_is_missing(tmp_path):
    _record(FakeSource([]), FakeInteraction([Choice.ACCEPT, Choice.QUIT]), tmp_path)
    interaction = FakeInteraction([])

    summary = _record(FakeSource([]), interaction, tmp_path)

    assert (summary.recorded, summary.skipped) == (43, 1)
    assert interaction.announced[0][2] == CORPUS[1].utterance_id


def test_redo_option_re_records_a_chosen_utterance(tmp_path):
    _record(FakeSource([]), FakeInteraction([]), tmp_path)
    target = CORPUS[5].utterance_id
    new_take = _wav(2.0)

    summary = _record(
        FakeSource([new_take]), FakeInteraction([]), tmp_path, redo={target}
    )

    assert summary.recorded == 1
    assert wav_path(tmp_path, target).read_bytes() == new_take


def test_pending_lists_unrecorded_and_redo_utterances():
    assert len(pending({})) == 44


def test_advice_flags_a_take_cut_short_or_padded_with_extra_speech():
    utterance = next(u for u in CORPUS if u.utterance_id == "id_delivery_long")

    assert "pause" in take_advice(2.0, utterance)
    assert "extra speech" in take_advice(60.0, utterance)
    assert take_advice(utterance.estimated_seconds, utterance) is None


def test_advice_is_shown_to_the_reviewer(tmp_path):
    interaction = FakeInteraction([])

    _record(FakeSource([_wav(0.2)]), interaction, tmp_path)

    assert interaction.advice_seen[0] is not None


def test_a_directory_of_another_corpus_is_refused(tmp_path):
    _record(FakeSource([]), FakeInteraction([Choice.ACCEPT, Choice.QUIT]), tmp_path)
    manifest = tmp_path / MANIFEST_NAME
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            '"corpus_fingerprint": "', '"corpus_fingerprint": "x'
        ),
        encoding="utf-8",
    )

    with pytest.raises(RecordingDirectoryError):
        load_entries(tmp_path)
