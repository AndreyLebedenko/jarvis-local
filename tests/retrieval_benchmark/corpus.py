"""Fixed benchmark corpus, relevance labels, and predeclared thresholds.

All data here is declared before any candidate backend is measured. Editing it
after seeing a backend's results is a threshold change and must be recorded as
an explicit revision, per task 8.

Relevance labels are backend-agnostic ground truth: a document is relevant if
it is genuinely about the query, regardless of whether a particular backend
can retrieve it. A query for a name is relevant to every mention of that
person even when the stored form is inflected.

Categories split into three tiers by the retrieval capability they exercise:

- lexical-strength: relevant documents use the query's surface or prefix form,
  so the current exact/prefix FTS already serves them and any backend must keep
  them working;
- morphology: relevant documents use an inflected Russian form (word forms and
  inflected names) that pure prefix FTS cannot reach but a lemmatizer or
  stemmer can;
- semantic: relevant documents share meaning but few or no surface tokens
  (paraphrase, synonym), which no lexical or morphological method reaches and
  only a semantic layer can.

The distractor category has no relevant documents and measures irrelevant-rate.

Document ids use a short letter-for-session, index-in-session scheme (``A0``,
``B3``) so labels stay readable. The harness maps each id to a real
``JournalEventRef`` after building the corpus. Ids prefixed ``HN`` are hard
negatives: irrelevant documents that share surface tokens with a query's
relevant set (polysemy, near-miss identifiers) so precision and irrelevant-rate
are measured, not just recall.

Modality boundary: every document here is native conversation text (``user``
or ``assistant``). Transcript- and annotation-derived text are a different
modality that becomes searchable only in v1.8.1; the retrieval-quality
regression (card 26) adds them as separate labeled slices. This v1.8.0
baseline deliberately does not model voice or annotation sources, so that
threshold canon is set on the text surface first without cross-modality
confusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

BENCHMARK_CORPUS_VERSION = "2026-08-01.1"

_SESSION_A = "20260314-101500-aa01"
_SESSION_B = "20260520-160000-bb02"


class RetrievalCategory(Enum):
    EXACT_TERM = "exact_term"
    PREFIX = "prefix"
    NAME = "name"
    DATE = "date"
    IDENTIFIER = "identifier"
    NUMBER = "number"
    TEMPORAL_FILTER = "temporal_filter"
    SESSION_FILTER = "session_filter"
    DISTRACTOR = "distractor"
    WORD_FORM = "word_form"
    PARAPHRASE = "paraphrase"
    SYNONYM = "synonym"


# Tier 1: relevant documents use the query's surface or prefix form. The
# shipped exact/prefix FTS serves these fully and no backend may regress them.
LEXICAL_STRENGTH_CATEGORIES: frozenset[RetrievalCategory] = frozenset(
    {
        RetrievalCategory.EXACT_TERM,
        RetrievalCategory.PREFIX,
        RetrievalCategory.DATE,
        RetrievalCategory.IDENTIFIER,
        RetrievalCategory.NUMBER,
        RetrievalCategory.TEMPORAL_FILTER,
        RetrievalCategory.SESSION_FILTER,
    }
)

# Tier 2: relevant documents use an inflected Russian form. A morphology-aware
# lexical baseline (lemmatizer or stemmer) closes this cheaply; pure prefix FTS
# cannot. Inflected names live here, not in the lexical tier.
MORPHOLOGY_CATEGORIES: frozenset[RetrievalCategory] = frozenset(
    {
        RetrievalCategory.NAME,
        RetrievalCategory.WORD_FORM,
    }
)

# Tier 3: relevant documents share meaning but few or no surface tokens. Only a
# semantic layer reaches these; morphology does not. This is the increment an
# embedding layer must earn over the morphology baseline.
SEMANTIC_CATEGORIES: frozenset[RetrievalCategory] = frozenset(
    {
        RetrievalCategory.PARAPHRASE,
        RetrievalCategory.SYNONYM,
    }
)


@dataclass(frozen=True)
class BenchmarkDocument:
    doc_id: str
    session_id: str
    timestamp: str
    role: str
    source: str
    text: str


@dataclass(frozen=True)
class BenchmarkQuery:
    query_id: str
    category: RetrievalCategory
    text: str
    relevant: frozenset[str]
    date_from: str | None = None
    date_to: str | None = None
    session_ids: tuple[str, ...] = ()
    forbidden: frozenset[str] = field(default_factory=frozenset)
    k: int = 5


BENCHMARK_DOCUMENTS: tuple[BenchmarkDocument, ...] = (
    # Session A - 2026-03-14: bicycle puncture repair and a meeting.
    BenchmarkDocument(
        "A0",
        _SESSION_A,
        "2026-03-14T10:15:00+00:00",
        "user",
        "text",
        "Сегодня поймал прокол на переднем колесе велосипеда по дороге домой.",
    ),
    BenchmarkDocument(
        "A1",
        _SESSION_A,
        "2026-03-14T10:15:20+00:00",
        "assistant",
        "assistant",
        "Чтобы устранить прокол, сними покрышку, найди камеру и заклей прокол латкой.",
    ),
    BenchmarkDocument(
        "A2",
        _SESSION_A,
        "2026-03-14T10:20:00+00:00",
        "user",
        "text",
        "Напомни, у меня встреча с Андреем 14 марта в 15:00 по поводу проекта.",
    ),
    BenchmarkDocument(
        "A3",
        _SESSION_A,
        "2026-03-14T10:20:05+00:00",
        "assistant",
        "assistant",
        "Готово, Андрей: встречу на 14 марта, 15:00 записал.",
    ),
    BenchmarkDocument(
        "A4",
        _SESSION_A,
        "2026-03-14T10:25:00+00:00",
        "user",
        "text",
        "Какая завтра погода в Лондоне?",
    ),
    # Hard negative: "прокол" in the mistake sense, not the bicycle sense.
    BenchmarkDocument(
        "HN1",
        _SESSION_A,
        "2026-03-14T10:30:00+00:00",
        "user",
        "text",
        "В отчёте по проекту нашёлся досадный прокол в расчётах.",
    ),
    # Session B - 2026-05-20: an order, a payment, and a recipe.
    BenchmarkDocument(
        "B0",
        _SESSION_B,
        "2026-05-20T16:00:00+00:00",
        "user",
        "text",
        "Оформил заказ номер A-2481 на новые покрышки.",
    ),
    BenchmarkDocument(
        "B1",
        _SESSION_B,
        "2026-05-20T16:00:30+00:00",
        "assistant",
        "assistant",
        "Заказ A-2481 подтверждён, доставка через три дня.",
    ),
    BenchmarkDocument(
        "B2",
        _SESSION_B,
        "2026-05-20T16:05:00+00:00",
        "user",
        "text",
        "Сделал перевод 5000 рублей за велосипедные запчасти.",
    ),
    BenchmarkDocument(
        "B3",
        _SESSION_B,
        "2026-05-20T16:05:10+00:00",
        "assistant",
        "assistant",
        "Перевод на сумму 5000 рублей зафиксирован.",
    ),
    BenchmarkDocument(
        "B4",
        _SESSION_B,
        "2026-05-20T16:10:00+00:00",
        "user",
        "text",
        "Хочу приготовить борщ, купил свёклу и капусту.",
    ),
    BenchmarkDocument(
        "B5",
        _SESSION_B,
        "2026-05-20T16:10:20+00:00",
        "assistant",
        "assistant",
        "Для борща свёклу натри, капусту нашинкуй и вари бульон.",
    ),
    BenchmarkDocument(
        "B6",
        _SESSION_B,
        "2026-05-20T16:15:00+00:00",
        "user",
        "text",
        "Посоветуй какой-нибудь фильм на вечер.",
    ),
    # Hard negative: "колесо обозрения" (Ferris wheel), not a bicycle wheel.
    BenchmarkDocument(
        "HN2",
        _SESSION_B,
        "2026-05-20T16:20:00+00:00",
        "user",
        "text",
        "Рядом с парком построили новое колесо обозрения.",
    ),
    # Hard negative: "5000" as a running distance, not the payment sum.
    BenchmarkDocument(
        "HN3",
        _SESSION_B,
        "2026-05-20T16:25:00+00:00",
        "user",
        "text",
        "Утром пробежал 5000 метров на стадионе.",
    ),
    # Hard negative: a near-miss order id that must not match A-2481.
    BenchmarkDocument(
        "HN4",
        _SESSION_B,
        "2026-05-20T16:30:00+00:00",
        "assistant",
        "assistant",
        "Заказ A-2480 отменён вчера по ошибке.",
    ),
)


BENCHMARK_QUERIES: tuple[BenchmarkQuery, ...] = (
    BenchmarkQuery(
        "q-exact-prokol",
        RetrievalCategory.EXACT_TERM,
        "прокол",
        frozenset({"A0", "A1"}),
    ),
    BenchmarkQuery(
        "q-prefix-velosip",
        RetrievalCategory.PREFIX,
        "велосип",
        frozenset({"A0", "B2"}),
    ),
    BenchmarkQuery(
        # Backend-agnostic gold: both mentions are about Andrey. A2 stores the
        # inflected "Андреем", so pure prefix FTS reaches only A3; a morphology
        # backend must reach both.
        "q-name-andrey",
        RetrievalCategory.NAME,
        "Андрей",
        frozenset({"A2", "A3"}),
    ),
    BenchmarkQuery(
        "q-date-14-marta",
        RetrievalCategory.DATE,
        "14 марта",
        frozenset({"A2", "A3"}),
    ),
    BenchmarkQuery(
        "q-id-a2481",
        RetrievalCategory.IDENTIFIER,
        "A-2481",
        frozenset({"B0", "B1"}),
    ),
    BenchmarkQuery(
        "q-number-5000",
        RetrievalCategory.NUMBER,
        "5000",
        frozenset({"B2", "B3"}),
    ),
    BenchmarkQuery(
        "q-temporal-pokryshki",
        RetrievalCategory.TEMPORAL_FILTER,
        "покрышк",
        frozenset({"B0"}),
        date_from="2026-05-01",
        date_to="2026-05-31",
        forbidden=frozenset({"A1"}),
    ),
    BenchmarkQuery(
        "q-session-velosip",
        RetrievalCategory.SESSION_FILTER,
        "велосип",
        frozenset({"B2"}),
        session_ids=(_SESSION_B,),
        forbidden=frozenset({"A0"}),
    ),
    BenchmarkQuery(
        "q-distractor-crypto",
        RetrievalCategory.DISTRACTOR,
        "инвестиции в криптовалюту",
        frozenset(),
    ),
    BenchmarkQuery(
        "q-wordform-prokolom",
        RetrievalCategory.WORD_FORM,
        "проколом",
        frozenset({"A0", "A1"}),
    ),
    BenchmarkQuery(
        "q-wordform-koleso",
        RetrievalCategory.WORD_FORM,
        "колесо",
        frozenset({"A0"}),
    ),
    BenchmarkQuery(
        # Russian names are inflected too: the nominative "Андрей" is stored in
        # A3, but a dative-case query must reach the same meeting via morphology.
        "q-wordform-andreyu",
        RetrievalCategory.WORD_FORM,
        "Андрею",
        frozenset({"A2", "A3"}),
    ),
    BenchmarkQuery(
        "q-paraphrase-tire",
        RetrievalCategory.PARAPHRASE,
        "как заклеить спущенную шину",
        frozenset({"A0", "A1"}),
    ),
    BenchmarkQuery(
        "q-synonym-velik",
        RetrievalCategory.SYNONYM,
        "велик сдулся",
        frozenset({"A0", "A1"}),
    ),
    BenchmarkQuery(
        "q-synonym-beet-soup",
        RetrievalCategory.SYNONYM,
        "рецепт свекольного супа",
        frozenset({"B4", "B5"}),
    ),
    BenchmarkQuery(
        "q-paraphrase-meeting",
        RetrievalCategory.PARAPHRASE,
        "во сколько я договорился увидеться с коллегой",
        frozenset({"A2", "A3"}),
    ),
    BenchmarkQuery(
        "q-paraphrase-order",
        RetrievalCategory.PARAPHRASE,
        "когда привезут мою покупку",
        frozenset({"B0", "B1"}),
    ),
    BenchmarkQuery(
        "q-synonym-payment",
        RetrievalCategory.SYNONYM,
        "оплатил детали для байка",
        frozenset({"B2", "B3"}),
    ),
    BenchmarkQuery(
        "q-synonym-beet-cold-soup",
        RetrievalCategory.SYNONYM,
        "как сварить свекольник",
        frozenset({"B4", "B5"}),
    ),
    BenchmarkQuery(
        # Semantic disambiguation: a deflated bicycle wheel, not the Ferris
        # wheel hard negative (HN2).
        "q-synonym-wheel",
        RetrievalCategory.SYNONYM,
        "на байке спустило колесо",
        frozenset({"A0", "A1"}),
    ),
)


# PASS thresholds for the PRIMARY hybrid backend, expressed as mean recall@k per
# tier (plus overall precision and the distractor guard). Ratified by the owner
# on 2026-08-01 after the task-8 B0/B1/B2 measurements: the semantic bar is set
# to the measured reality of small local embedders on Russian paraphrase and
# synonym (e5-large-instruct reaches ~0.56), not the earlier aspirational 0.80.
# Do not weaken these after seeing a backend's results without a documented
# revision.
#
# These gate the primary backend only. The config-swappable latency fallback
# (embeddinggemma, ~0.50 semantic) is deliberately NOT gated on semantic recall
# - it is a degraded mode that trades semantic quality for lower latency. The
# fallback must still preserve lexical and morphology recall and keep the
# distractor false-positive rate at 0.0; its semantic recall is recorded, not
# a pass/fail bar.
RATIFIED_THRESHOLDS: dict[str, float] = {
    "lexical_strength_recall_at_k": 1.0,
    "morphology_recall_at_k": 0.90,
    "semantic_recall_at_k": 0.55,
    "overall_recall_at_k": 0.80,
    "overall_precision_at_k": 0.85,
    "max_distractor_false_positive_rate": 0.0,
}
