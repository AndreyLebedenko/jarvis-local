"""Transcript and annotation benchmark slices (task v1.8.0-26).

The task-11 corpus in ``corpus.py`` is frozen: its documents, queries, and
``RATIFIED_THRESHOLDS`` are reused unchanged, per the task-26 requirement to
add transcript and annotation cases "only as new labeled slices." This module
is purely additive - nothing here edits ``BENCHMARK_DOCUMENTS``,
``BENCHMARK_QUERIES``, or the ratified thresholds.

Two new modalities are added, each with its own documents/annotations and
queries, reusing the same ``RetrievalCategory`` tiers so ``evaluate_retrieval``
can score them with the existing tier-aggregation logic:

- Transcript slice: a voice session (``_SESSION_C``) where user turns carry
  empty raw text and their words live only in a transcript overlay, exactly
  as production voice turns do (task v1.8.0-18..20). Assistant replies in the
  same session keep ordinary text, mirroring a real mixed voice/text session.
- Annotation slice: labeled ``ACTIVE`` annotations (task v1.8.0-21..23) over
  the base and transcript sessions, carrying supplementary facts that are
  deliberately absent from any raw event so a query that finds them is
  attributable to annotation retrieval specifically, not to a raw-event hit
  that happens to share vocabulary with its summary.

Both slices reuse ``extended_concept_embedder`` (``semantic.py``) so the whole
corpus - base, transcript, and annotation text - shares one concept-space
fixture, mirroring how the production backend embeds every source through one
model.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.journal.annotation import AnnotationSource

from .corpus import BenchmarkQuery, RetrievalCategory

MULTIMODAL_CORPUS_VERSION = "2026-08-08.1"

_SESSION_C = "20260610-090000-cc03"


@dataclass(frozen=True)
class TranscriptBenchmarkDocument:
    doc_id: str
    session_id: str
    timestamp: str
    role: str
    source: str
    text: str
    is_transcript: bool = True


TRANSCRIPT_BENCHMARK_DOCUMENTS: tuple[TranscriptBenchmarkDocument, ...] = (
    TranscriptBenchmarkDocument(
        "C0",
        _SESSION_C,
        "2026-06-10T09:00:00+00:00",
        "user",
        "voice",
        "Я потерял ключи от квартиры где-то в парке.",
    ),
    TranscriptBenchmarkDocument(
        "C1",
        _SESSION_C,
        "2026-06-10T09:00:20+00:00",
        "assistant",
        "assistant",
        "Проверь карманы куртки и загляни в бюро находок парка, ключи могли "
        "остаться там.",
        is_transcript=False,
    ),
    TranscriptBenchmarkDocument(
        "C2",
        _SESSION_C,
        "2026-06-10T09:05:00+00:00",
        "user",
        "voice",
        "Мою собаку зовут Рекс, я гуляю с ним каждый вечер в семь часов.",
    ),
    TranscriptBenchmarkDocument(
        "C3",
        _SESSION_C,
        "2026-06-10T09:05:20+00:00",
        "assistant",
        "assistant",
        "Понял, Рекс - отличное имя, вечерняя прогулка в семь записана.",
        is_transcript=False,
    ),
    TranscriptBenchmarkDocument(
        "C4",
        _SESSION_C,
        "2026-06-10T09:10:00+00:00",
        "user",
        "voice",
        "Номер моего билета на поезд TR-9917, уточни время отправления.",
    ),
    TranscriptBenchmarkDocument(
        "C5",
        _SESSION_C,
        "2026-06-10T09:10:20+00:00",
        "assistant",
        "assistant",
        "Билет TR-9917 подтверждён, поезд отправляется завтра в девять утра.",
        is_transcript=False,
    ),
)


TRANSCRIPT_BENCHMARK_QUERIES: tuple[BenchmarkQuery, ...] = (
    BenchmarkQuery(
        "q-transcript-exact-klyuchi",
        RetrievalCategory.EXACT_TERM,
        "ключи",
        frozenset({"C0", "C1"}),
    ),
    BenchmarkQuery(
        "q-transcript-prefix-bilet",
        RetrievalCategory.PREFIX,
        "билет",
        frozenset({"C4", "C5"}),
    ),
    BenchmarkQuery(
        "q-transcript-id-tr9917",
        RetrievalCategory.IDENTIFIER,
        "TR-9917",
        frozenset({"C4", "C5"}),
    ),
    BenchmarkQuery(
        # "ключей" (genitive plural) is longer than the document's "ключи"
        # (nominative plural), so a raw-prefix comparison cannot match it -
        # only morphology unifies the two forms, mirroring q-wordform-andreyu.
        "q-transcript-wordform-klyuchey",
        RetrievalCategory.WORD_FORM,
        "ключей",
        frozenset({"C0", "C1"}),
    ),
    BenchmarkQuery(
        "q-transcript-paraphrase-keys",
        RetrievalCategory.PARAPHRASE,
        "куда могли деться ключи от моего дома",
        frozenset({"C0", "C1"}),
    ),
    BenchmarkQuery(
        "q-transcript-synonym-dog-walk",
        RetrievalCategory.SYNONYM,
        "пёс выходит на вечерний променад в семь",
        frozenset({"C2", "C3"}),
    ),
    BenchmarkQuery(
        "q-transcript-distractor-pasta",
        RetrievalCategory.DISTRACTOR,
        "рецепт итальянской пасты",
        frozenset(),
    ),
)


@dataclass(frozen=True)
class BenchmarkAnnotation:
    label: str
    session_id: str
    text: str
    source: AnnotationSource
    author: str = "benchmark"
    start_position: int | None = None
    end_position: int | None = None


BENCHMARK_ANNOTATIONS: tuple[BenchmarkAnnotation, ...] = (
    # Whole-session annotation on session A (bicycle/meeting). Carries a
    # supplementary fact absent from every A/B raw document, so a hit is
    # attributable to annotation retrieval, not to a raw event that happens
    # to share vocabulary with the summary.
    BenchmarkAnnotation(
        "ANN-A",
        "20260314-101500-aa01",
        "Заметка: пользователь также упомянул, что хочет купить новый шлем "
        "для безопасности до конца месяца.",
        AnnotationSource.GENERATED,
    ),
    # Range annotation over session B's order (B0-B1, positions 0-1), edited
    # by the user - mirrors the real bug-report scenario (an edited
    # annotation queried from a fresh context shortly after save).
    BenchmarkAnnotation(
        "ANN-B",
        "20260520-160000-bb02",
        "Уточнение: доставка заказа A-2481 может задержаться из-за нехватки "
        "нужного размера покрышек на складе.",
        AnnotationSource.EDITED,
        start_position=0,
        end_position=1,
    ),
    # Whole-session annotation on the transcript session (C). Also carries a
    # fact absent from the raw/transcript text.
    BenchmarkAnnotation(
        "ANN-C",
        _SESSION_C,
        "Сводка: пользователь просил напомнить о визите к ветеринару для "
        "Рекса в пятницу.",
        AnnotationSource.GENERATED,
    ),
)


ANNOTATION_BENCHMARK_QUERIES: tuple[BenchmarkQuery, ...] = (
    BenchmarkQuery(
        "q-annotation-exact-shlem",
        RetrievalCategory.EXACT_TERM,
        "шлем",
        frozenset({"ANN-A"}),
    ),
    BenchmarkQuery(
        "q-annotation-wordform-shlema",
        RetrievalCategory.WORD_FORM,
        "шлема",
        frozenset({"ANN-A"}),
    ),
    BenchmarkQuery(
        "q-annotation-paraphrase-helmet",
        RetrievalCategory.PARAPHRASE,
        "собирается ли он приобрести защитный шлем",
        frozenset({"ANN-A"}),
    ),
    BenchmarkQuery(
        "q-annotation-exact-nehvatki",
        RetrievalCategory.EXACT_TERM,
        "нехватки",
        frozenset({"ANN-B"}),
    ),
    BenchmarkQuery(
        # "нехватку" (accusative) is longer than the annotation's "нехватки"
        # (genitive); no raw-prefix collision, morphology-only like the
        # transcript slice's q-transcript-wordform-klyuchey.
        "q-annotation-wordform-nehvatku",
        RetrievalCategory.WORD_FORM,
        "нехватку",
        frozenset({"ANN-B"}),
    ),
    BenchmarkQuery(
        "q-annotation-synonym-delay",
        RetrievalCategory.SYNONYM,
        "задержится ли отправка покрышек со склада",
        frozenset({"ANN-B"}),
    ),
    BenchmarkQuery(
        "q-annotation-exact-vet",
        RetrievalCategory.EXACT_TERM,
        "ветеринару",
        frozenset({"ANN-C"}),
    ),
    BenchmarkQuery(
        "q-annotation-paraphrase-vet",
        RetrievalCategory.PARAPHRASE,
        "надо не забыть про визит к доктору для собаки",
        frozenset({"ANN-C"}),
    ),
    BenchmarkQuery(
        "q-annotation-distractor-stocks",
        RetrievalCategory.DISTRACTOR,
        "курс акций на бирже сегодня",
        frozenset(),
    ),
)


# Text -> concept entries layered onto the base concept-space fixture via
# ``extended_concept_embedder``. Every semantic-tier (PARAPHRASE/SYNONYM)
# document and query text above needs an entry; other texts are left
# unlabeled (cosine 0 against everything, including other unlabeled texts),
# matching how the base corpus treats untargeted documents.
TEXT_CONCEPTS: dict[str, str] = {
    # Transcript slice.
    "Я потерял ключи от квартиры где-то в парке.": "lost_keys",
    "Проверь карманы куртки и загляни в бюро находок парка, ключи могли "
    "остаться там.": "lost_keys",
    "куда могли деться ключи от моего дома": "lost_keys",
    "Мою собаку зовут Рекс, я гуляю с ним каждый вечер в семь часов.": (
        "evening_dog_walk"
    ),
    "Понял, Рекс - отличное имя, вечерняя прогулка в семь записана.": (
        "evening_dog_walk"
    ),
    "пёс выходит на вечерний променад в семь": "evening_dog_walk",
    # Annotation slice.
    "Заметка: пользователь также упомянул, что хочет купить новый шлем "
    "для безопасности до конца месяца.": "helmet_purchase_plan",
    "собирается ли он приобрести защитный шлем": "helmet_purchase_plan",
    "Уточнение: доставка заказа A-2481 может задержаться из-за нехватки "
    "нужного размера покрышек на складе.": "delivery_delay_risk",
    "задержится ли отправка покрышек со склада": "delivery_delay_risk",
    "Сводка: пользователь просил напомнить о визите к ветеринару для "
    "Рекса в пятницу.": "vet_appointment_reminder",
    "надо не забыть про визит к доктору для собаки": "vet_appointment_reminder",
}
