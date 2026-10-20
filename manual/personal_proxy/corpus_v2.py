"""Frozen inputs of tasks/done/spike-v2.1.0-9-confidence-fresh-corpus.md.

Ten new utterances with critical and hard-to-recognize content (digit groups,
spelled addresses, identifiers, English names inside Russian speech), each in
three voices: the owner's and the two Silero voices `eugene` and `baya`. Every
identity here is invented. Numbers are written as spoken words, as in the first
corpus; the TTS voices read exactly the text the owner reads. Frozen like the
first corpus: the fingerprint is recorded with the recordings.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

from manual.personal_proxy.corpus import (
    Category,
    Span,
    SpanType,
    Utterance,
    _utterance_problems,
)

VOICES = ("owner", "eugene", "baya")
OWNER_VOICE = "owner"
VOICE_SEPARATOR = "__"
I = Category.IDENTIFIER  # noqa: E741
M = Category.MIXED

PHRASES: tuple[Utterance, ...] = (
    Utterance(
        "v2_phone_grouped",
        I,
        "Запиши номер: плюс семь, девятьсот шестнадцать, сто двадцать три, "
        "сорок пять, шестьдесят семь.",
        (
            Span(
                "p1",
                "плюс семь, девятьсот шестнадцать, сто двадцать три, "
                "сорок пять, шестьдесят семь",
                SpanType.PHONE,
                digit_keys=("79161234567",),
            ),
        ),
    ),
    Utterance(
        "v2_email_underscore",
        I,
        "Отправь файл на почту алекс точка смирнов подчёркивание девяносто два "
        "собака почта точка ру.",
        (
            Span(
                "e1",
                "алекс точка смирнов подчёркивание девяносто два собака почта точка ру",
                SpanType.EMAIL,
                forms=("алекс", "смирнов", "alex", "smirnov"),
                digit_keys=("92",),
            ),
        ),
    ),
    Utterance(
        "v2_passport",
        I,
        "Мой паспорт: серия сорок пять ноль восемь, номер сто двадцать три "
        "тысячи четыреста пятьдесят шесть, выдан в городе Твери.",
        (
            Span(
                "g1",
                "серия сорок пять ноль восемь, номер сто двадцать три тысячи "
                "четыреста пятьдесят шесть",
                SpanType.GOV_ID,
                digit_keys=("4508123456", "123456"),
            ),
        ),
    ),
    Utterance(
        "v2_card",
        I,
        "Оплати картой номер пять два ноль ноль, четыре шесть восемь один, "
        "девять ноль ноль ноль, семь семь семь два.",
        (
            Span(
                "c1",
                "пять два ноль ноль, четыре шесть восемь один, девять ноль ноль "
                "ноль, семь семь семь два",
                SpanType.CARD,
                digit_keys=("5200468190007772",),
            ),
        ),
    ),
    Utterance(
        "v2_partner_company",
        M,
        "Мой партнёр Томас Шмидт из компании Schneider Electric согласовал "
        "договор до пятницы.",
        (
            Span(
                "n1",
                "Томас Шмидт",
                SpanType.PERSON,
                forms=("томас", "шмидт", "thomas", "schmidt"),
            ),
            Span(
                "o1",
                "Schneider Electric",
                SpanType.ORG,
                forms=("schneider", "electric", "шнайдер", "электрик"),
            ),
        ),
    ),
    Utterance(
        "v2_rare_surname",
        I,
        "Передай документы Хабибуллину Рустему Нургалиевичу в отдел кадров.",
        (
            Span(
                "n1",
                "Хабибуллину Рустему Нургалиевичу",
                SpanType.PERSON,
                forms=("хабибуллин", "рустем", "нургалиев"),
            ),
        ),
    ),
    Utterance(
        "v2_address_complex",
        I,
        "Доставка: Санкт-Петербург, Измайловский проспект, дом двадцать девять, "
        "корпус три, строение два, квартира сто пятнадцать.",
        (
            Span(
                "a1",
                "Измайловский проспект, дом двадцать девять, корпус три, "
                "строение два, квартира сто пятнадцать",
                SpanType.ADDRESS,
                forms=("измайловск",),
                digit_keys=("29", "115"),
            ),
        ),
    ),
    Utterance(
        "v2_tin_date",
        I,
        "Мой ИНН семь семь ноль семь, восемь три девять три, ноль ноль четыре "
        "ноль, оформить надо до двадцать третьего ноября.",
        (
            Span(
                "g1",
                "семь семь ноль семь, восемь три девять три, ноль ноль четыре ноль",
                SpanType.GOV_ID,
                digit_keys=("770783930040",),
            ),
            Span(
                "d1",
                "двадцать третьего ноября",
                SpanType.DATE,
                forms=("ноября",),
                digit_keys=("23",),
            ),
        ),
    ),
    Utterance(
        "v2_sms_code",
        I,
        "Код подтверждения из смс: четыре восемь два девять ноль один. "
        "Никому его не говори.",
        (
            Span(
                "s1",
                "четыре восемь два девять ноль один",
                SpanType.SECRET,
                digit_keys=("482901",),
            ),
        ),
    ),
    Utterance(
        "v2_slack_login",
        M,
        "Мой логин в Slack: иван подчёркивание пэ подчёркивание восемьдесят три, "
        "добавь меня в канал.",
        (
            Span(
                "l1",
                "иван подчёркивание пэ подчёркивание восемьдесят три",
                SpanType.OTHER,
                forms=("иван", "ivan"),
                digit_keys=("83",),
            ),
        ),
    ),
)


def voiced_id(phrase_id: str, voice: str) -> str:
    return f"{phrase_id}{VOICE_SEPARATOR}{voice}"


def voice_of(utterance_id: str) -> str:
    return utterance_id.rsplit(VOICE_SEPARATOR, 1)[1]


CORPUS_V2: tuple[Utterance, ...] = tuple(
    replace(phrase, utterance_id=voiced_id(phrase.utterance_id, voice))
    for phrase in PHRASES
    for voice in VOICES
)


def utterances_of_voice(voice: str) -> tuple[Utterance, ...]:
    return tuple(u for u in CORPUS_V2 if voice_of(u.utterance_id) == voice)


def utterance_v2_by_id(utterance_id: str) -> Utterance:
    for utterance in CORPUS_V2:
        if utterance.utterance_id == utterance_id:
            return utterance
    raise KeyError(utterance_id)


def corpus_v2_problems() -> list[str]:
    problems: list[str] = []
    ids = [u.utterance_id for u in CORPUS_V2]
    if len(set(ids)) != len(ids):
        problems.append("duplicate utterance ids")
    for phrase in PHRASES:
        problems.extend(_utterance_problems(phrase))
    return problems


def corpus_v2_fingerprint() -> str:
    payload = {"corpus": [asdict(u) for u in CORPUS_V2], "voices": list(VOICES)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
