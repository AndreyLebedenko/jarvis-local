"""Frozen inputs of tasks/done/spike-single-pass-tts-block.md: the 16-prompt corpus
and arm B's contract. Frozen after owner review; any edit after the run starts
invalidates the run (the harness records a hash of both in run_meta.json)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CorpusPrompt:
    prompt_id: str
    category: str
    text: str


SEEDS = (19200, 4242)
REVIEW_SEED = SEEDS[0]

CORPUS: tuple[CorpusPrompt, ...] = (
    CorpusPrompt(
        "table_storage",
        "table",
        "Сравни HDD, SATA SSD и NVMe SSD по скорости последовательного чтения, "
        "цене за терабайт и типичному ресурсу. Сведи в таблицу.",
    ),
    CorpusPrompt(
        "table_timezones",
        "table",
        "Сделай таблицу: Лондон, Москва, Нью-Йорк, Токио - смещение от UTC "
        "зимой и летом.",
    ),
    CorpusPrompt(
        "code_palindrome",
        "code",
        "Напиши на Python функцию, которая проверяет, является ли строка "
        "палиндромом, без учёта регистра, пробелов и знаков препинания. "
        "Приведи код и пару примеров вызова.",
    ),
    CorpusPrompt(
        "code_powershell",
        "code",
        "Как в PowerShell рекурсивно найти в папке D:\\Projects все файлы "
        "больше 100 МБ и вывести их пути и размер в мегабайтах? Дай команду.",
    ),
    CorpusPrompt(
        "calc_loan",
        "formula",
        "Кредит 300 000 рублей на 2 года под 12% годовых, платежи "
        "аннуитетные. Какой ежемесячный платёж? Покажи формулу и расчёт.",
    ),
    CorpusPrompt(
        "calc_kv_cache",
        "formula",
        "Сколько памяти займёт KV-кэш модели с 48 слоями и 8 KV-головами "
        "размерности 256 при контексте 32 768 токенов в fp16? Покажи расчёт.",
    ),
    CorpusPrompt(
        "list_windows_update",
        "list_caveats",
        "Что проверить перед установкой крупного обновления Windows 11? "
        "Дай список и для каждого пункта оговорку, что может пойти не так.",
    ),
    CorpusPrompt(
        "list_vram",
        "list_caveats",
        "Какими способами можно уменьшить расход видеопамяти при локальном "
        "запуске LLM? Перечисли и для каждого оговори, чем за него платишь.",
    ),
    CorpusPrompt(
        "refs_transformers",
        "references",
        "Посоветуй три-четыре работы или книги, чтобы разобраться в "
        "архитектуре трансформеров: авторы, год и где их найти.",
    ),
    CorpusPrompt(
        "refs_ollama_api",
        "references",
        "Где найти официальную документацию Ollama по эндпоинту /api/chat и "
        "какие там основные параметры запроса? Дай ссылки.",
    ),
    CorpusPrompt(
        "mixed_async",
        "mixed_ru_en",
        "Объясни разницу между async/await и threading в Python: при чём тут "
        "GIL и event loop, и когда что выбирать.",
    ),
    CorpusPrompt(
        "mixed_speculative",
        "mixed_ru_en",
        "Что такое speculative decoding и за счёт чего draft model ускоряет "
        "inference? Объясни простыми словами.",
    ),
    CorpusPrompt(
        "chat_language",
        "conversational",
        "Как думаешь, есть смысл учить второй иностранный язык после "
        "тридцати, или уже поздно?",
    ),
    CorpusPrompt(
        "chat_rainy_sunday",
        "conversational",
        "Чем можно заняться в Лондоне в дождливое воскресенье?",
    ),
    CorpusPrompt(
        "fact_capital",
        "short_fact",
        "Какая столица у Австралии?",
    ),
    CorpusPrompt(
        "fact_seconds",
        "short_fact",
        "Сколько секунд в сутках?",
    ),
)

B_CONTRACT = (
    "Этот ответ будет показан пользователю на экране и одновременно озвучен. "
    "Сначала напиши ответ для экрана полностью - так, как написал бы его без "
    "этой инструкции. Затем, в самом конце, добавь ровно один блок "
    "<tts>...</tts> - устный пересказ ответа выше для озвучивания. Внутри "
    "блока только связная речь: без Markdown, списков, таблиц, кода и "
    "ссылок - замени их естественным пересказом. Можешь ссылаться на то, что "
    "видно на экране (например, «как в таблице выше»). Не добавляй новых "
    "фактов и не меняй смысл - это пересказ формы, а не новый ответ. Не "
    "помещай блок в блок кода и ничего не пиши после закрывающего тега </tts>."
)


def corpus_sha256() -> str:
    payload = json.dumps(
        {"corpus": [asdict(prompt) for prompt in CORPUS], "b_contract": B_CONTRACT},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
