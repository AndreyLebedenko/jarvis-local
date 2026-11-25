#!/usr/bin/env python3
"""Manual handoff: does Silero v5 mark the intonation centre of a question?

Not an automated test - it plays audio, so the human runs it. The Silero v5
announcement says a general question can name its intonation centre with
asterisks, e.g. 'Организаторы *прислали* нам электронные билеты?'. The
announcement names v5_4_ru, not v5_6_ru, and does not say what happens with
an unpaired or doubled marker. This script answers, by ear, for the model
Jarvis can actually use:
  1. Is the asterisk spoken or dropped silently?
  2. Does the stress of the question move with the marked word?
  3. Is the marked question audibly different from the unmarked one?
  4. What do an unpaired marker, two markers, and a marker on a statement do?

Every sentence goes through SileroEngine, so Jarvis's own number and Latin
preprocessing is part of the check. Each case prints what to listen for and
the synthesized duration, then plays the audio.

Round 3 (--round 3) repeats round 2 on the same three sentences as statements
(full stop instead of a question mark): the announcement says emphasis in
statements is not supported yet, so this checks what the markers do there.

Round 2 (--round 2) tests one hypothesis from round 1, where the most natural
clip had two marked words, the second being the last word of the question:
is "a content word + the last word" consistently the natural pattern? It uses
three other general questions and, per question, plays: no marker, the last
word alone, each content word paired with the last word, and one pair that
leaves the last word unmarked. Several speakers can be given to --speaker.

Usage (from the repository root, with the project's .venv):
  python setup_tts_model.py --language ru --model v5_6_ru   # once, network
  python -m manual.manual_check_silero_v5_question_intonation
  python -m manual.manual_check_silero_v5_question_intonation --speaker baya
  python -m manual.manual_check_silero_v5_question_intonation --out-dir D:\\spike
  python -m manual.manual_check_silero_v5_question_intonation --round 2
    --speaker xenia aidar

Expected output: one block per case (id, text, listen-for line), then a
`duration` row; a summary table per speaker at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import io
from dataclasses import dataclass
from pathlib import Path

import sounddevice as sd
import soundfile as sf

from jarvis.audio.tts_silero import SileroEngine
from jarvis.core.config import SileroTtsSettings

DEFAULT_MODEL = "v5_6_ru"
DEFAULT_SPEAKER = "xenia"
GAP_SECONDS = 0.8

QUESTION = "Организаторы прислали нам электронные билеты?"


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    listen_for: str


CASES: tuple[Case, ...] = (
    Case("general_unmarked", QUESTION, "Baseline: question with no marker."),
    Case(
        "general_centre_1",
        "*Организаторы* прислали нам электронные билеты?",
        "Stress on 'Организаторы' (not someone else). No spoken asterisk.",
    ),
    Case(
        "general_centre_2",
        "Организаторы *прислали* нам электронные билеты?",
        "Stress on 'прислали' (sent, not promised).",
    ),
    Case(
        "general_centre_3",
        "Организаторы прислали *нам* электронные билеты?",
        "Stress on 'нам' (to us, not to others).",
    ),
    Case(
        "general_centre_4",
        "Организаторы прислали нам *электронные* билеты?",
        "Stress on 'электронные' (electronic, not paper).",
    ),
    Case(
        "general_centre_5",
        "Организаторы прислали нам электронные *билеты*?",
        "Stress on 'билеты' (tickets, not something else).",
    ),
    Case(
        "special_unmarked",
        "Кто прислал нам электронные билеты?",
        "Baseline: question word, no marker.",
    ),
    Case(
        "special_marked",
        "Кто *прислал* нам электронные билеты?",
        "Marker is optional here; any audible difference from the baseline.",
    ),
    Case(
        "alternative_unmarked",
        "Ты любишь рыбу или мясо?",
        "Baseline: alternative question, no marker.",
    ),
    Case(
        "alternative_marked",
        "Ты любишь *рыбу* или мясо?",
        "Marker is optional here; any audible difference from the baseline.",
    ),
    Case(
        "phrase_marker",
        "Организаторы *прислали нам* электронные билеты?",
        "Two words inside one pair: still one centre, or garbled?",
    ),
    Case(
        "malformed_unpaired",
        "*Организаторы прислали нам электронные билеты?",
        "Unpaired asterisk: read aloud, dropped, or breaks the sentence?",
    ),
    Case(
        "malformed_two_pairs",
        "Организаторы *прислали* нам электронные *билеты*?",
        "Two centres in one question: which wins, or garbled?",
    ),
    Case(
        "statement_unmarked",
        "Организаторы прислали нам электронные билеты.",
        "Baseline: statement, no marker.",
    ),
    Case(
        "statement_marked",
        "Организаторы *прислали* нам электронные билеты.",
        "Announcement says emphasis in statements is not supported yet: "
        "ignored (same as baseline), spoken asterisk, or damage?",
    ),
)


@dataclass(frozen=True)
class Question:
    id: str
    sentence: str
    content_words: tuple[int, ...]

    @property
    def last_word(self) -> int:
        return self.content_words[-1]


PAIR_SENTENCES: tuple[Question, ...] = (
    Question("s1", "Вы уже отправили нам договор", (0, 2, 3, 4)),
    Question("s2", "Курьер привёз заказ вчера вечером", (0, 1, 2, 4)),
    Question("s3", "Твой брат всё ещё живёт в Лондоне", (0, 1, 4, 6)),
)

STATEMENT_NOTE = " Also: is an asterisk audible? Does the end rise like a question?"


def mark_words(
    sentence: str, word_indexes: tuple[int, ...], terminal: str = "?"
) -> str:
    words = sentence.split()
    marked = [
        f"*{word}*" if index in word_indexes else word
        for index, word in enumerate(words)
    ]
    return " ".join(marked) + terminal


def build_pair_cases(round_number: int, terminal: str) -> tuple[Case, ...]:
    return tuple(
        case
        for sentence in PAIR_SENTENCES
        for case in _pair_cases_for(round_number, sentence, terminal)
    )


def _pair_cases_for(round_number: int, sentence: Question, terminal: str) -> list[Case]:
    note = "" if terminal == "?" else STATEMENT_NOTE
    prefix = f"r{round_number}_{sentence.id}"
    last = sentence.last_word
    first, second = sentence.content_words[1:3]
    plan = [
        ("unmarked", (), "Baseline."),
        ("last", (last,), "Last word only. Rate naturalness 1-5."),
        *(
            (f"w{index}_last", (index, last), "Word + last word. Rate naturalness 1-5.")
            for index in sentence.content_words[:-1]
        ),
        (
            f"w{first}_w{second}",
            (first, second),
            "Two words, last word NOT marked. Rate naturalness 1-5.",
        ),
    ]
    return [
        Case(
            f"{prefix}_{suffix}",
            mark_words(sentence.sentence, indexes, terminal),
            listen_for + note,
        )
        for suffix, indexes, listen_for in plan
    ]


def build_round_two_cases() -> tuple[Case, ...]:
    return build_pair_cases(2, "?")


def build_round_three_cases() -> tuple[Case, ...]:
    return build_pair_cases(3, ".")


def cases_for_round(round_number: int) -> tuple[Case, ...]:
    if round_number == 2:
        return build_round_two_cases()
    if round_number == 3:
        return build_round_three_cases()
    return CASES


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--speaker", nargs="+", default=[DEFAULT_SPEAKER])
    parser.add_argument("--round", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Also save each case as <speaker>_<id>.wav here (created if missing).",
    )
    return parser


def build_route(model: str, speaker: str) -> SileroTtsSettings:
    return SileroTtsSettings(model=model, language="ru", speaker=speaker)


def wav_duration_seconds(wav_bytes: bytes) -> float:
    info = sf.info(io.BytesIO(wav_bytes))
    return info.frames / info.samplerate


async def play_wav_bytes(wav_bytes: bytes) -> None:
    data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    sd.play(data, sample_rate)
    sd.wait()


async def run_speaker(
    args: argparse.Namespace, speaker: str, cases: tuple[Case, ...]
) -> None:
    engine = SileroEngine(build_route(args.model, speaker))
    print(f"\nSilero question spike: model={args.model} speaker={speaker}")
    durations: list[tuple[str, float]] = []
    for number, case in enumerate(cases, start=1):
        print(f"\ncase,{case.id},{number}/{len(cases)}")
        print(f"text,{case.text}\nlisten_for,{case.listen_for}")
        wav = await engine.synthesize(case.text, "ru")
        seconds = wav_duration_seconds(wav)
        durations.append((case.id, seconds))
        print(f"duration,{seconds:.2f}")
        if args.out_dir is not None:
            (args.out_dir / f"{speaker}_{case.id}.wav").write_bytes(wav)
        await play_wav_bytes(wav)
        await asyncio.sleep(GAP_SECONDS)

    print(f"\nsummary,{speaker},case_id,duration_seconds")
    for case_id, seconds in durations:
        print(f"summary,{speaker},{case_id},{seconds:.2f}")


async def main() -> None:
    args = build_arg_parser().parse_args()
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    cases = cases_for_round(args.round)
    for speaker in args.speaker:
        await run_speaker(args, speaker, cases)


if __name__ == "__main__":
    asyncio.run(main())
