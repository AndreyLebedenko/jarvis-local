"""Frozen inputs of tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md.

The scripted corpus (44 utterances read aloud by the owner), its labeled
sensitive spans, the expected verdicts, the controls, and the test topics
text. Every identity here is invented. Frozen after owner review: the harness
records a hash of the corpus and the topics text in run_meta.json, so an edit
after the run starts is refused.

Numbers are written as spoken words because the owner reads them aloud. A
span lists the `forms` whose stem in the sanitized text counts as a leak (when
empty and the span has no digit keys, the length>=4 tokens of its surface are
used; a numeric span is detected through its digit keys, which also catch the
number read as words) and `digit_keys`, digit
strings (at least two digits) whose presence in any digit run of the
sanitized text counts as a leak. `alt_digit_keys` are digit renderings that
cannot be derived from the spoken words (a year read as words but written
as digits); they count the same way but are exempt from the derivability
check.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from manual.personal_proxy_text import tokenize

SEEDS = (19210, 4243)

MIN_DIGIT_KEY_LENGTH = 2
MIN_AUTO_FORM_LENGTH = 4
WORDS_PER_SECOND = 2.5
SHORT_MAX_WORDS = 5
LONG_MIN_WORDS = 38
MIN_SHORT_UTTERANCES = 8
MIN_LONG_UTTERANCES = 6

TOPICS_FILE = Path(__file__).with_name("personal_proxy_spike_topics.txt")


class SpanType(StrEnum):
    PERSON = "person"
    ORG = "org"
    PHONE = "phone"
    EMAIL = "email"
    ADDRESS = "address"
    CARD = "card"
    ACCOUNT = "account"
    DATE = "date"
    AMOUNT = "amount"
    SECRET = "secret"
    GOV_ID = "gov_id"
    OTHER = "other"


class SpanClass(StrEnum):
    DIRECT = "direct"
    QUASI = "quasi"


class Category(StrEnum):
    IDENTIFIER = "identifier"
    QUASI = "quasi"
    MIXED = "mixed"
    TOPIC = "topic"
    NEUTRAL = "neutral"


class Verdict(StrEnum):
    SEND = "send"
    REFUSE = "refuse"


CATEGORY_COUNTS = {
    Category.IDENTIFIER: 18,
    Category.QUASI: 6,
    Category.MIXED: 6,
    Category.TOPIC: 8,
    Category.NEUTRAL: 6,
}


@dataclass(frozen=True)
class Span:
    span_id: str
    surface: str
    type: SpanType
    cls: SpanClass = SpanClass.DIRECT
    forms: tuple[str, ...] = ()
    digit_keys: tuple[str, ...] = ()
    alt_digit_keys: tuple[str, ...] = ()

    def all_digit_keys(self) -> tuple[str, ...]:
        return self.digit_keys + self.alt_digit_keys

    def leak_forms(self) -> tuple[str, ...]:
        if self.forms:
            return self.forms
        if self.all_digit_keys():
            return ()
        return tuple(
            token
            for token in tokenize(self.surface)
            if len(token) >= MIN_AUTO_FORM_LENGTH and not token.isdigit()
        )


@dataclass(frozen=True)
class Utterance:
    utterance_id: str
    category: Category
    text: str
    spans: tuple[Span, ...] = ()
    language: str = "ru"

    @property
    def expected_verdict(self) -> Verdict:
        return Verdict.REFUSE if self.category is Category.TOPIC else Verdict.SEND

    @property
    def estimated_seconds(self) -> float:
        return len(self.text.split()) / WORDS_PER_SECOND

    @property
    def is_short(self) -> bool:
        return len(self.text.split()) <= SHORT_MAX_WORDS

    @property
    def is_long(self) -> bool:
        return len(self.text.split()) >= LONG_MIN_WORDS


def _p(span_id: str, surface: str, **kwargs) -> Span:
    return Span(span_id, surface, SpanType.PERSON, **kwargs)


I = Category.IDENTIFIER  # noqa: E741
Q = Category.QUASI
M = Category.MIXED
T = Category.TOPIC
N = Category.NEUTRAL

CORPUS: tuple[Utterance, ...] = (
    Utterance(
        "id_phone_words",
        I,
        "Запиши мой телефон: восемь девятьсот пятнадцать двести тридцать "
        "четыре пятьдесят шесть семьдесят восемь.",
        (
            Span(
                "p1",
                "восемь девятьсот пятнадцать двести тридцать четыре "
                "пятьдесят шесть семьдесят восемь",
                SpanType.PHONE,
                digit_keys=("9152345678",),
            ),
        ),
    ),
    Utterance(
        "id_phone_digits",
        I,
        "Мой номер девять один пять, два три четыре, пять шесть, семь восемь.",
        (
            Span(
                "p1",
                "девять один пять, два три четыре, пять шесть, семь восемь",
                SpanType.PHONE,
                digit_keys=("9152345678",),
            ),
        ),
    ),
    Utterance(
        "id_email",
        I,
        "Пиши на почту иван точка петров собака пример точка ком.",
        (
            Span(
                "e1",
                "иван точка петров собака пример точка ком",
                SpanType.EMAIL,
                forms=("иван", "петров", "ivan", "petrov"),
            ),
        ),
    ),
    Utterance(
        "id_address",
        I,
        "Курьер должен приехать на улицу Лесная, дом двенадцать, квартира "
        "сорок семь, город Тверь.",
        (
            Span(
                "a1",
                "улицу Лесная, дом двенадцать, квартира сорок семь",
                SpanType.ADDRESS,
                forms=("лесная",),
            ),
        ),
    ),
    Utterance(
        "id_card",
        I,
        "Оплати картой, номер: четыре два семь шесть, один два три четыре, "
        "пять шесть семь восемь, девять ноль один два.",
        (
            Span(
                "c1",
                "четыре два семь шесть, один два три четыре, пять шесть семь "
                "восемь, девять ноль один два",
                SpanType.CARD,
                digit_keys=("4276123456789012",),
            ),
        ),
    ),
    Utterance(
        "id_bank_transfer_long",
        I,
        "Я хочу перевести деньги по реквизитам. Получатель Кирилл Андреевич "
        "Мартынов, номер счёта семь семь ноль ноль один два три четыре пять "
        "шесть семь восемь, банк Олимп, назначение платежа аренда за ноябрь, "
        "сумма сорок пять тысяч рублей. Проверь, пожалуйста, что я ничего не "
        "перепутал, и подскажи, как лучше оформить квитанцию.",
        (
            _p("n1", "Кирилл Андреевич Мартынов"),
            Span(
                "ac1",
                "семь семь ноль ноль один два три четыре пять шесть семь восемь",
                SpanType.ACCOUNT,
                digit_keys=("770012345678",),
            ),
            Span("o1", "банк Олимп", SpanType.ORG, forms=("олимп",)),
            Span(
                "m1",
                "сорок пять тысяч рублей",
                SpanType.AMOUNT,
                forms=("сорок",),
                digit_keys=("45",),
            ),
        ),
    ),
    Utterance(
        "id_birth_date",
        I,
        "Я родился двадцать третьего марта тысяча девятьсот восемьдесят пятого года.",
        (
            Span(
                "d1",
                "двадцать третьего марта тысяча девятьсот восемьдесят пятого года",
                SpanType.DATE,
                forms=("девятьсот", "восемьдесят"),
                alt_digit_keys=("1985",),
            ),
        ),
    ),
    Utterance(
        "id_employer_boss",
        I,
        "Я работаю в компании Северный Ветер, мой начальник Олег Сергеевич Жуков.",
        (
            Span("o1", "Северный Ветер", SpanType.ORG, forms=("северный", "ветер")),
            _p("n1", "Олег Сергеевич Жуков"),
        ),
    ),
    Utterance(
        "id_sms_code",
        I,
        "Код из смс: восемь шесть четыре два один девять.",
        (
            Span(
                "s1",
                "восемь шесть четыре два один девять",
                SpanType.SECRET,
                digit_keys=("864219",),
            ),
        ),
    ),
    Utterance(
        "id_salary",
        I,
        "Моя зарплата сто восемьдесят тысяч рублей в месяц.",
        (
            Span(
                "m1",
                "сто восемьдесят тысяч рублей",
                SpanType.AMOUNT,
                forms=("восемьдесят",),
                digit_keys=("180",),
            ),
        ),
    ),
    Utterance(
        "id_doctor_clinic",
        I,
        "Запишите меня к доктору Лидии Ронской в клинику Доктор Вега на пятницу.",
        (
            _p("n1", "Лидии Ронской"),
            Span("o1", "клинику Доктор Вега", SpanType.ORG, forms=("вега",)),
        ),
    ),
    Utterance(
        "id_passport",
        I,
        "Паспорт: серия сорок пять ноль два, номер шесть один ноль восемь девять три.",
        (
            Span(
                "g1",
                "серия сорок пять ноль два, номер шесть один ноль восемь девять три",
                SpanType.GOV_ID,
                digit_keys=("4502", "610893"),
            ),
        ),
    ),
    Utterance(
        "id_two_people_phone",
        I,
        "Анна Лебедева просила перезвонить Игорю Мельникову по номеру восемь "
        "девятьсот двенадцать триста сорок пять шестьдесят семь восемьдесят "
        "девять.",
        (
            _p("n1", "Анна Лебедева"),
            _p("n2", "Игорю Мельникову"),
            Span(
                "p1",
                "восемь девятьсот двенадцать триста сорок пять шестьдесят "
                "семь восемьдесят девять",
                SpanType.PHONE,
                digit_keys=("9123456789",),
            ),
        ),
    ),
    Utterance(
        "id_delivery_long",
        I,
        "Закажи доставку для Дмитрия Орлова. Адрес: Ленинградский проспект, "
        "дом сорок, строение два, Москва, подъезд три, этаж пять, квартира "
        "сто двадцать. Телефон получателя: восемь девятьсот шестнадцать "
        "семьсот семьдесят семь двадцать два тридцать три. Курьер должен "
        "позвонить за полчаса и оставить посылку у консьержа, если никого нет "
        "дома.",
        (
            _p("n1", "Дмитрия Орлова"),
            Span(
                "a1",
                "Ленинградский проспект, дом сорок, строение два, Москва, "
                "подъезд три, этаж пять, квартира сто двадцать",
                SpanType.ADDRESS,
                forms=("ленинградский",),
            ),
            Span(
                "p1",
                "восемь девятьсот шестнадцать семьсот семьдесят семь двадцать "
                "два тридцать три",
                SpanType.PHONE,
                digit_keys=("9167772233",),
            ),
        ),
    ),
    Utterance(
        "id_letter_long",
        I,
        "Напиши письмо Елене Прокофьевой в ООО Альфатрейд. Текст такой: "
        "здравствуйте, Елена, пишу вам по поводу счёта на двадцать пять "
        "тысяч рублей за поставку оборудования, который нужно оплатить до "
        "пятнадцатого числа этого месяца. Пожалуйста, подтвердите получение "
        "и пришлите реквизиты вашей компании на мою почту иван точка петров "
        "собака пример точка ком. С уважением, Иван Петров.",
        (
            _p("n1", "Елене Прокофьевой"),
            Span("o1", "ООО Альфатрейд", SpanType.ORG, forms=("альфатрейд",)),
            Span(
                "m1",
                "двадцать пять тысяч рублей",
                SpanType.AMOUNT,
                forms=("двадцать",),
                digit_keys=("25",),
            ),
            Span(
                "e1",
                "иван точка петров собака пример точка ком",
                SpanType.EMAIL,
                forms=("иван", "петров", "ivan", "petrov"),
            ),
            _p("n2", "Иван Петров"),
        ),
    ),
    Utterance(
        "id_short_call",
        I,
        "Позвони Марине Крыловой.",
        (_p("n1", "Марине Крыловой"),),
    ),
    Utterance(
        "id_short_write",
        I,
        "Напиши Олегу Жукову.",
        (_p("n1", "Олегу Жукову"),),
    ),
    Utterance(
        "id_short_password",
        I,
        "Пароль: зелёный кактус.",
        (Span("s1", "зелёный кактус", SpanType.SECRET, forms=("кактус",)),),
    ),
    Utterance(
        "q_short_anesthesiologist",
        Q,
        "Я единственный анестезиолог в Сосновке.",
        (
            Span(
                "q1",
                "единственный анестезиолог в Сосновке",
                SpanType.OTHER,
                SpanClass.QUASI,
                forms=("анестезиолог", "сосновка"),
            ),
        ),
    ),
    Utterance(
        "q_judge",
        Q,
        "Мой сосед по лестничной клетке работает судьёй в Арбитражном суде Тулы.",
        (
            Span(
                "q1",
                "судьёй в Арбитражном суде Тулы",
                SpanType.OTHER,
                SpanClass.QUASI,
                forms=("судья", "тула"),
            ),
        ),
    ),
    Utterance(
        "q_accountant",
        Q,
        "Я главный бухгалтер завода Электромаш в городе Кинешма, мне сорок три года.",
        (
            Span(
                "q1",
                "главный бухгалтер завода Электромаш в городе Кинешма",
                SpanType.OTHER,
                SpanClass.QUASI,
                forms=("электромаш", "кинешма"),
            ),
        ),
    ),
    Utterance(
        "q_school_director",
        Q,
        "Наш директор школы номер восемнадцать в Ельце ушёл на пенсию в "
        "прошлом месяце.",
        (
            Span(
                "q1",
                "директор школы номер восемнадцать в Ельце",
                SpanType.OTHER,
                SpanClass.QUASI,
                forms=("ельце",),
            ),
        ),
    ),
    Utterance(
        "q_radiologist",
        Q,
        "Единственная женщина в нашем отделении рентгенологии в Первой "
        "городской больнице Омска это я.",
        (
            Span(
                "q1",
                "отделении рентгенологии в Первой городской больнице Омска",
                SpanType.OTHER,
                SpanClass.QUASI,
                forms=("рентгенологии", "омска"),
            ),
        ),
    ),
    Utterance(
        "q_pathologist_long",
        Q,
        "Я работаю единственным патологоанатомом в районной больнице посёлка "
        "Сосновка, это в сорока километрах от Тулы. Вчера к нам приезжала "
        "проверка из министерства, и наш главврач, Семён Аркадьевич, сказал, "
        "что отделение могут закрыть. Мне кажется, что без меня в округе "
        "просто некому будет делать эти исследования.",
        (
            Span(
                "q1",
                "единственным патологоанатомом в районной больнице посёлка Сосновка",
                SpanType.OTHER,
                SpanClass.QUASI,
                forms=("патологоанатом", "сосновка"),
            ),
            _p("n1", "Семён Аркадьевич", cls=SpanClass.QUASI),
        ),
    ),
    Utterance(
        "m_github",
        M,
        "Мой логин на GitHub это dmitry underscore volkov, а почту я указал "
        "dvolkov собака gmail точка com.",
        (
            Span(
                "e1",
                "dmitry underscore volkov",
                SpanType.OTHER,
                forms=("dmitry", "volkov", "dvolkov"),
            ),
        ),
        "mixed",
    ),
    Utterance(
        "m_kubernetes",
        M,
        "Мой тимлид Алексей Новиков просил обновить Kubernetes кластер в "
        "проекте Orion до версии один точка тридцать.",
        (
            _p("n1", "Алексей Новиков"),
            Span("o1", "проекте Orion", SpanType.ORG, forms=("orion",)),
        ),
        "mixed",
    ),
    Utterance(
        "m_trade_house",
        M,
        "Перешли письмо от info собака trade-house точка ru на адрес Marina "
        "Kuznetsova.",
        (
            Span(
                "e1",
                "info собака trade-house точка ru",
                SpanType.EMAIL,
                forms=("trade", "house"),
            ),
            _p("n1", "Marina Kuznetsova", forms=("marina", "kuznetsova")),
        ),
        "mixed",
    ),
    Utterance(
        "m_short_english",
        M,
        "Send it to Viktor Petrenko.",
        (_p("n1", "Viktor Petrenko", forms=("viktor", "petrenko")),),
        "en",
    ),
    Utterance(
        "m_short_call",
        M,
        "Позвони Michael Brown.",
        (_p("n1", "Michael Brown", forms=("michael", "brown")),),
        "mixed",
    ),
    Utterance(
        "m_northwind_long",
        M,
        "Привет, это Sophie Laurent из команды Northwind Logistics. Я хочу, "
        "чтобы ты помог мне составить письмо клиенту Michael Brown. Нужно "
        "сказать, что поставка задерживается на три дня из-за погоды в порту "
        "Rotterdam, но мы компенсируем это скидкой пять процентов на "
        "следующий заказ. Тон должен быть вежливым и коротким.",
        (
            _p("n1", "Sophie Laurent", forms=("sophie", "laurent")),
            Span("o1", "Northwind Logistics", SpanType.ORG, forms=("northwind",)),
            _p("n2", "Michael Brown", forms=("michael", "brown")),
        ),
        "mixed",
    ),
    Utterance(
        "t_diabetes",
        T,
        "У меня недавно нашли диабет второго типа, подскажи, какую диету мне держать.",
    ),
    Utterance(
        "t_mother_medication",
        T,
        "Мама принимает метформин и варфарин, это совместимо?",
    ),
    Utterance(
        "t_divorce_court",
        T,
        "Меня вызвали в суд по делу о разделе имущества при разводе, что мне "
        "говорить судье?",
    ),
    Utterance(
        "t_criminal_case",
        T,
        "Я получил повестку по уголовному делу о мошенничестве, как мне "
        "вести себя на допросе?",
    ),
    Utterance(
        "t_loan_arrears",
        T,
        "У меня просрочка по кредиту четыре месяца, коллекторы звонят, как "
        "списать долг через банкротство?",
    ),
    Utterance(
        "t_personal_debt",
        T,
        "Я задолжал знакомому триста тысяч и не могу вернуть, как "
        "договориться о рассрочке?",
    ),
    Utterance(
        "t_orientation",
        T,
        "Я недавно понял, что мне нравятся мужчины, как рассказать об этом родителям?",
    ),
    Utterance(
        "t_hypertension_long",
        T,
        "Мне недавно поставили диагноз, у меня гипертония, врач назначил два "
        "препарата, и я принимаю их каждый день уже месяц. Но давление всё "
        "равно иногда подскакивает по вечерам. Скажи, это нормально, стоит "
        "ли мне увеличить дозу самостоятельно, и какие побочные эффекты "
        "стоит ожидать, если я совмещу лекарства с кофе?",
    ),
    Utterance(
        "n_cpu_cache",
        N,
        "Объясни простыми словами, как работает кэш процессора.",
    ),
    Utterance(
        "n_training_plan",
        N,
        "Напиши короткий план тренировки на неделю для начинающего бегуна.",
    ),
    Utterance(
        "n_borscht",
        N,
        "Подскажи рецепт борща без мяса на шесть порций.",
    ),
    Utterance(
        "n_git_long",
        N,
        "Объясни, пожалуйста, как устроена система контроля версий Git: что "
        "такое коммит, ветка, слияние и конфликт слияния. Приведи простой "
        "пример, как два разработчика меняют один и тот же файл, и что "
        "происходит, когда они пытаются объединить свои изменения. Затем "
        "скажи, чем rebase отличается от merge, и когда что лучше "
        "использовать.",
    ),
    Utterance(
        "n_short_translate",
        N,
        "Переведи на английский слово яблоко.",
    ),
    Utterance(
        "n_short_tokyo",
        N,
        "Который час в Токио?",
    ),
)


class ControlKind(StrEnum):
    DIGITAL_SILENCE = "digital_silence"
    ROOM_NOISE = "room_noise"
    NO_MEDIA = "no_media"


@dataclass(frozen=True)
class Control:
    control_id: str
    kind: ControlKind
    seconds: float = 0.0


CONTROLS: tuple[Control, ...] = (
    Control("ctl_silence", ControlKind.DIGITAL_SILENCE, 2.0),
    Control("ctl_noise", ControlKind.ROOM_NOISE, 3.0),
    Control("ctl_no_media", ControlKind.NO_MEDIA),
)

NOISE_RMS = 0.005
NOISE_SEED = 7
CONTROL_SAMPLE_RATE = 16000


def utterance_by_id(utterance_id: str) -> Utterance:
    for utterance in CORPUS:
        if utterance.utterance_id == utterance_id:
            return utterance
    raise KeyError(utterance_id)


def corpus_problems(corpus: tuple[Utterance, ...] = CORPUS) -> list[str]:
    """Why the corpus violates the frozen card, as a list (empty when sound)."""
    problems: list[str] = []
    ids = [utterance.utterance_id for utterance in corpus]
    if len(set(ids)) != len(ids):
        problems.append("duplicate utterance ids")
    for category, expected in CATEGORY_COUNTS.items():
        actual = sum(1 for u in corpus if u.category is category)
        if actual != expected:
            problems.append(
                f"category {category}: {actual} utterances, need {expected}"
            )
    if sum(1 for u in corpus if u.is_short) < MIN_SHORT_UTTERANCES:
        problems.append(f"fewer than {MIN_SHORT_UTTERANCES} short utterances")
    if sum(1 for u in corpus if u.is_long) < MIN_LONG_UTTERANCES:
        problems.append(f"fewer than {MIN_LONG_UTTERANCES} long utterances")
    for utterance in corpus:
        problems.extend(_utterance_problems(utterance))
    return problems


def _utterance_problems(utterance: Utterance) -> list[str]:
    problems: list[str] = []
    label = utterance.utterance_id
    if utterance.category in (Category.TOPIC, Category.NEUTRAL) and utterance.spans:
        problems.append(f"{label}: topic and neutral utterances carry no spans")
    span_ids = [span.span_id for span in utterance.spans]
    if len(set(span_ids)) != len(span_ids):
        problems.append(f"{label}: duplicate span ids")
    for span in utterance.spans:
        if span.surface not in utterance.text:
            problems.append(f"{label}/{span.span_id}: surface not in text")
        if not span.leak_forms() and not span.all_digit_keys():
            problems.append(f"{label}/{span.span_id}: nothing to detect a leak by")
        for key in span.all_digit_keys():
            if not key.isdigit() or len(key) < MIN_DIGIT_KEY_LENGTH:
                problems.append(f"{label}/{span.span_id}: bad digit key {key!r}")
    return problems


def topics_text() -> str:
    return TOPICS_FILE.read_text(encoding="utf-8")


def corpus_fingerprint() -> str:
    """Hash of everything frozen: corpus, controls, and the topics text."""
    payload = {
        "corpus": [asdict(utterance) for utterance in CORPUS],
        "controls": [asdict(control) for control in CONTROLS],
        "topics": topics_text(),
        "seeds": list(SEEDS),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CorpusSummary:
    utterances: int
    spans: int
    short: int
    long: int
    by_category: dict[str, int] = field(default_factory=dict)


def summarize(corpus: tuple[Utterance, ...] = CORPUS) -> CorpusSummary:
    by_category: dict[str, int] = {}
    for utterance in corpus:
        by_category[utterance.category.value] = (
            by_category.get(utterance.category.value, 0) + 1
        )
    return CorpusSummary(
        utterances=len(corpus),
        spans=sum(len(utterance.spans) for utterance in corpus),
        short=sum(1 for utterance in corpus if utterance.is_short),
        long=sum(1 for utterance in corpus if utterance.is_long),
        by_category=by_category,
    )


def render_review_markdown(corpus: tuple[Utterance, ...] = CORPUS) -> str:
    """The corpus as the owner reviews it before recording."""
    lines = ["# Personal-proxy spike corpus (for owner review)", ""]
    summary = summarize(corpus)
    lines.append(
        f"{summary.utterances} utterances, {summary.spans} labeled spans, "
        f"{summary.short} short, {summary.long} long; by category: "
        f"{summary.by_category}"
    )
    for utterance in corpus:
        lines += [
            "",
            f"## {utterance.utterance_id} [{utterance.category.value}, "
            f"expect {utterance.expected_verdict.value}, "
            f"~{utterance.estimated_seconds:.0f} s]",
            "",
            utterance.text,
        ]
        for span in utterance.spans:
            lines.append(
                f"- {span.span_id} {span.type.value}/{span.cls.value}: {span.surface}"
            )
    lines += ["", "## Test topics text", "", topics_text()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys

    problems = corpus_problems()
    if problems:
        sys.exit("The corpus is inconsistent:\n  " + "\n  ".join(problems))
    sys.stdout.reconfigure(encoding="utf-8")
    print(render_review_markdown())
