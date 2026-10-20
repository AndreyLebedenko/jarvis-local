"""Block R of tasks/done/spike-v2.1.0-1-combined-transcribe-sanitize.md.

Restoration puts the original values back into an external answer. It is text
only, so it is measured separately from the audio arms: a set of 30 synthetic
Russian sentences with placeholders, the local model's restoration pass, a
deterministic validation, the deterministic substitution fallback, and a
blind human review of grammatical case. All identities are invented.
"""

from __future__ import annotations

import json
import random
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from manual.personal_proxy.text import stem_present, tokenize

SEEDS = (19210, 4243)
REVIEW_RNG_SEED = 20261018

MIN_VALIDATION_PASS_RATE = 0.90
MAX_ALTERATION_RATE = 0.05
MIN_FALLBACK_BEATEN_SHARE = 0.80

PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")

RESTORE_RULES = (
    "You restore personal details into a sentence that contains placeholders "
    "such as <PERSON_1>. The mapping gives each placeholder's original value "
    "in its base form. Replace every placeholder with its original value, put "
    "the value in the grammatical case and form the sentence requires (Russian "
    "declension), and keep every other word exactly as it is. Output only the "
    "restored sentence."
)


@dataclass(frozen=True)
class RestorationItem:
    item_id: str
    sentence: str
    mapping: dict[str, str]


def _item(item_id: str, sentence: str, **values: str) -> RestorationItem:
    return RestorationItem(
        item_id, sentence, {f"<{key.upper()}>": value for key, value in values.items()}
    )


ITEMS: tuple[RestorationItem, ...] = (
    _item(
        "r01_nominative",
        "<PERSON_1> подтвердила встречу на пятницу.",
        person_1="Анна Лебедева",
    ),
    _item(
        "r02_dative",
        "Передайте <PERSON_1>, что документы готовы.",
        person_1="Марина Крылова",
    ),
    _item(
        "r03_genitive",
        "Письмо от <PERSON_1> пришло вчера вечером.",
        person_1="Олег Жуков",
    ),
    _item(
        "r04_accusative",
        "Вы можете попросить <PERSON_1> выслать счёт.",
        person_1="Кирилл Мартынов",
    ),
    _item(
        "r05_instrumental",
        "Лучше всего обсудить это с <PERSON_1> лично.",
        person_1="Елена Прокофьева",
    ),
    _item(
        "r06_prepositional",
        "Я бы расспросил подробнее о <PERSON_1>.",
        person_1="Дмитрий Орлов",
    ),
    _item(
        "r07_genitive_u",
        "У <PERSON_1> нет доступа к этому файлу.",
        person_1="Игорь Мельников",
    ),
    _item(
        "r08_two_people",
        "<PERSON_1> просила перезвонить <PERSON_2> завтра.",
        person_1="Анна Лебедева",
        person_2="Игорь Мельников",
    ),
    _item(
        "r09_repeated",
        "Скажите <PERSON_1>, что <PERSON_1> может не торопиться.",
        person_1="Павел Сидоров",
    ),
    _item(
        "r10_phone",
        "Позвоните по номеру <PHONE_1> после обеда.",
        phone_1="8 915 234 56 78",
    ),
    _item(
        "r11_email",
        "Отправьте резюме на адрес <EMAIL_1>.",
        email_1="ivan.petrov@example.com",
    ),
    _item(
        "r12_card",
        "Не сообщайте никому номер карты <CARD_1>.",
        card_1="4276 1234 5678 9012",
    ),
    _item(
        "r13_address_prepositional",
        "Курьер уже был на <ADDRESS_1> сегодня утром.",
        address_1="улица Лесная, дом 12",
    ),
    _item(
        "r14_address_accusative",
        "Доставьте посылку на <ADDRESS_1> до обеда.",
        address_1="улица Лесная, дом 12",
    ),
    _item(
        "r15_org_nominative",
        "<ORG_1> обычно отвечает в течение двух рабочих дней.",
        org_1="Северный Ветер",
    ),
    _item(
        "r16_org_genitive",
        "Сотрудники <ORG_1> не ответили на запрос.",
        org_1="Северный Ветер",
    ),
    _item(
        "r17_org_prepositional",
        "Я бы проверил отзывы о <ORG_1> перед заказом.",
        org_1="Северный Ветер",
    ),
    _item(
        "r18_patronymic_dative",
        "Обратитесь с этим вопросом к <PERSON_1>.",
        person_1="Олег Сергеевич Жуков",
    ),
    _item(
        "r19_instrumental_fem",
        "Договоритесь о времени с <PERSON_1>.",
        person_1="Лидия Ронская",
    ),
    _item(
        "r20_accusative_fem",
        "Попросите <PERSON_1> прислать подтверждение.",
        person_1="Елена Прокофьева",
    ),
    _item(
        "r21_genitive_u_fem",
        "Спросите у <PERSON_1> про сроки.",
        person_1="Марина Крылова",
    ),
    _item(
        "r22_english_dative",
        "Перешлите это письмо <PERSON_1> сегодня.",
        person_1="Michael Brown",
    ),
    _item(
        "r23_english_genitive",
        "Адрес <PERSON_1> лучше уточнить заранее.",
        person_1="Sophie Laurent",
    ),
    _item(
        "r24_person_and_date",
        "Встреча с <PERSON_1> назначена на <DATE_1>.",
        person_1="Дмитрий Орлов",
        date_1="23 марта",
    ),
    _item(
        "r25_person_and_phone",
        "<PERSON_1> оставил свой номер <PHONE_1> и просит перезвонить.",
        person_1="Дмитрий Орлов",
        phone_1="8 916 777 22 33",
    ),
    _item(
        "r26_dative_pair",
        "Отправьте копию <PERSON_1> и <PERSON_2>.",
        person_1="Анна Лебедева",
        person_2="Игорь Мельников",
    ),
    _item(
        "r27_amount",
        "Сумма <AMOUNT_1> должна быть выплачена до пятницы.",
        amount_1="45 000 рублей",
    ),
    _item(
        "r28_person_and_org",
        "Мнение <PERSON_1> из <ORG_1> здесь важно.",
        person_1="Олег Жуков",
        org_1="Северный Ветер",
    ),
    _item(
        "r29_instrumental_short",
        "Свяжитесь с <PERSON_1> до конца дня.",
        person_1="Марина Крылова",
    ),
    _item(
        "r30_prepositional_with",
        "В разговоре с <PERSON_1> о сроках всё прояснилось.",
        person_1="Павел Сидоров",
    ),
)


def restoration_messages(item: RestorationItem) -> list[dict[str, str]]:
    mapping = json.dumps(item.mapping, ensure_ascii=False)
    return [
        {"role": "system", "content": RESTORE_RULES},
        {"role": "user", "content": f"Mapping: {mapping}\nSentence: {item.sentence}"},
    ]


def fallback_restore(item: RestorationItem) -> str:
    """Plain substitution of the base-form originals, no declension."""
    text = item.sentence
    for placeholder, original in item.mapping.items():
        text = text.replace(placeholder, original)
    return text


def validation_passes(item: RestorationItem, output: str) -> bool:
    """No placeholder text left, and every original value present."""
    if PLACEHOLDER.search(output):
        return False
    tokens = tokenize(output)
    for original in item.mapping.values():
        value_tokens = [t for t in tokenize(original) if not t.isdigit()]
        digit_tokens = [t for t in tokenize(original) if t.isdigit()]
        if not all(stem_present(t, tokens) for t in value_tokens):
            return False
        if not all(t in tokens for t in digit_tokens):
            return False
    return True


def outside_text_unchanged(item: RestorationItem, output: str) -> bool:
    """Whether every word outside the restored values is exactly as it was."""
    template = tokenize(PLACEHOLDER.sub(" ", item.sentence))
    value_forms = [
        token for original in item.mapping.values() for token in tokenize(original)
    ]
    remaining = [
        token
        for token in tokenize(output)
        if not token.isdigit() and not stem_present_any(token, value_forms)
    ]
    expected = [token for token in template if not token.isdigit()]
    return remaining == expected


def stem_present_any(token: str, forms: list[str]) -> bool:
    return any(stem_present(form, [token]) for form in forms if not form.isdigit())


@dataclass(frozen=True)
class RestorationScore:
    item_id: str
    seed: int
    output: str
    valid: bool
    unchanged_outside: bool


def score_output(item: RestorationItem, seed: int, output: str) -> RestorationScore:
    text = output.strip()
    return RestorationScore(
        item.item_id,
        seed,
        text,
        validation_passes(item, text),
        outside_text_unchanged(item, text),
    )


@dataclass(frozen=True)
class RestorationMetrics:
    generations: int
    validation_pass_rate: float
    alteration_rate: float


def aggregate_restoration(scores: list[RestorationScore]) -> RestorationMetrics:
    if not scores:
        return RestorationMetrics(0, 0.0, 0.0)
    return RestorationMetrics(
        len(scores),
        sum(1 for s in scores if s.valid) / len(scores),
        sum(1 for s in scores if not s.unchanged_outside) / len(scores),
    )


@dataclass(frozen=True)
class ReviewPair:
    item_id: str
    x_is_model: bool


def build_review_pairs(items: tuple[RestorationItem, ...] = ITEMS) -> list[ReviewPair]:
    rng = random.Random(REVIEW_RNG_SEED)
    return [ReviewPair(item.item_id, rng.random() < 0.5) for item in items]


def render_review_sheet(
    pairs: list[ReviewPair],
    model_outputs: dict[str, str],
    items: tuple[RestorationItem, ...] = ITEMS,
) -> str:
    by_id = {item.item_id: item for item in items}
    lines = [
        "# Restoration review (blind)",
        "",
        "For each item mark X and Y in the answers file: ok if the sentence is "
        "grammatically right (case and form of the inserted values), bad if not.",
        "",
    ]
    for pair in pairs:
        item = by_id[pair.item_id]
        model = model_outputs.get(pair.item_id, "")
        fallback = fallback_restore(item)
        first, second = (model, fallback) if pair.x_is_model else (fallback, model)
        lines += [f"## {item.item_id}", f"- X: {first}", f"- Y: {second}", ""]
    return "\n".join(lines)


def render_answer_template(pairs: list[ReviewPair]) -> str:
    blocks = [f'[{pair.item_id}]\nx = ""\ny = ""\n' for pair in pairs]
    return "# Fill x and y with ok or bad.\n\n" + "\n".join(blocks)


def parse_answers(text: str) -> dict[str, dict[str, str]]:
    document = tomllib.loads(text)
    return {
        item_id: {side: str(value).strip().lower() for side, value in sides.items()}
        for item_id, sides in document.items()
    }


@dataclass(frozen=True)
class CaseResult:
    fallback_wrong: int
    model_right_where_fallback_wrong: int

    @property
    def beaten_share(self) -> float | None:
        if not self.fallback_wrong:
            return None
        return self.model_right_where_fallback_wrong / self.fallback_wrong


def score_case_review(
    pairs: list[ReviewPair],
    answers: dict[str, dict[str, str]],
    model_valid: dict[str, bool],
) -> CaseResult:
    """Items the fallback gets wrong, and how many of those the model, with a
    validated output, gets right."""
    wrong = right = 0
    for pair in pairs:
        sides = answers.get(pair.item_id)
        if sides is None:
            continue
        model_side, fallback_side = ("x", "y") if pair.x_is_model else ("y", "x")
        if sides.get(fallback_side) != "bad":
            continue
        wrong += 1
        if model_valid.get(pair.item_id) and sides.get(model_side) == "ok":
            right += 1
    return CaseResult(wrong, right)


def restoration_decision(
    metrics: RestorationMetrics, case: CaseResult
) -> tuple[bool, list[str]]:
    reasons = []
    if metrics.validation_pass_rate < MIN_VALIDATION_PASS_RATE:
        reasons.append(
            f"validation pass rate {metrics.validation_pass_rate:.2f} "
            f"< {MIN_VALIDATION_PASS_RATE}"
        )
    if metrics.alteration_rate > MAX_ALTERATION_RATE:
        reasons.append(
            f"alteration rate {metrics.alteration_rate:.2f} > {MAX_ALTERATION_RATE}"
        )
    share = case.beaten_share
    if share is None:
        reasons.append("no item where the fallback is wrong; case benefit unmeasured")
    elif share < MIN_FALLBACK_BEATEN_SHARE:
        reasons.append(
            f"model right on {share:.2f} of the fallback's failures "
            f"< {MIN_FALLBACK_BEATEN_SHARE}"
        )
    return (not reasons, reasons)


def load_answers(path: Path) -> dict[str, dict[str, str]]:
    return parse_answers(path.read_text(encoding="utf-8"))
