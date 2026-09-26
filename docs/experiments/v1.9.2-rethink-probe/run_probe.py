#!/usr/bin/env python3
"""Rethink-mode probe runner: pass 1, then the self-critique pass.

Production-shaped requests: the same effective system prompt a live turn
gets (config [prompts].system composed with the curated memory files, then
the reasoning-level section for level 2), the same backend payload builder,
the same sampling options from [backend]. Reasoning level is MEDIUM for
both passes, so the only difference measured between them is the prompt.

Usage:
  python run_probe.py pass1 [case_id ...]
  python run_probe.py critique [case_id ...]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, "D:/AI/Jarvis")
sys.path.insert(0, "D:/AI/Jarvis/src")

from jarvis.app import _compose_effective_system_prompt  # noqa: E402
from jarvis.core.bus import EventBus  # noqa: E402
from jarvis.core.config import load_settings  # noqa: E402
from jarvis.dialog.backend import OllamaBackend  # noqa: E402
from jarvis.dialog.thinking_mode import ReasoningLevel  # noqa: E402
from jarvis.memory.files import MemoryFileLoader, build_memory_file_specs  # noqa: E402
from prompts import CASES  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
SEED = 19200
LEVEL = ReasoningLevel.MEDIUM
REPO = Path("D:/AI/Jarvis")
# load_settings() and the memory file specs resolve relative to the process
# cwd; without this the probe silently loads default settings (a model name
# that is not even pulled) instead of the project's real [backend] section.
CONFIG = REPO / "config.toml"

CRITIQUE_PROMPT = (
    "Это мой собственный черновик ответа, ещё не отправленный пользователю.\n"
    "Проверь его заново по исходному запросу.\n\n"
    "Проверь именно это:\n"
    "- выполнены ли ВСЕ явные ограничения запроса, включая запреты, "
    "лимиты и формат;\n"
    "- нет ли ошибок в расчётах: пересчитай каждое число сам, не доверяй "
    "черновику;\n"
    "- нет ли утверждений, не подкреплённых запросом, и не выдумано ли "
    "то, чего в запросе нет;\n"
    "- не противоречат ли требования запроса друг другу; если да - это "
    "нужно назвать прямо, а не обойти;\n"
    "- не упущена ли существенная оговорка.\n\n"
    "Сохранить черновик без изменений - допустимый исход. Стиль без "
    "необходимости не переписывай.\n\n"
    "Выведи ровно две части и ничего больше:\n"
    "VERDICT: одна строка - либо OK, либо перечисление найденных дефектов "
    "через точку с запятой.\n"
    "ANSWER: полный окончательный текст ответа пользователю, готовый к "
    "отправке как есть."
)


def effective_system_prompt() -> tuple[str, object]:
    import os

    os.chdir(REPO)
    settings = load_settings(CONFIG)
    loader = MemoryFileLoader(build_memory_file_specs(settings.memory))
    base = loader.compose_system_prompt(settings.prompts.system, include_memory=True)
    return _compose_effective_system_prompt(base, LEVEL, settings.prompts), settings


async def dispatch(
    client: httpx.AsyncClient,
    backend: OllamaBackend,
    messages: list[dict[str, str]],
) -> dict[str, object]:
    payload = backend.build_payload(messages, None, reasoning_level=LEVEL)
    options = dict(payload.get("options") or {})
    options["seed"] = SEED
    payload["options"] = options
    chunks: list[dict] = []
    started = time.perf_counter()
    async with client.stream("POST", "/api/chat", json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.strip():
                chunks.append(json.loads(line))
    wall = time.perf_counter() - started
    text = "".join(
        c.get("message", {}).get("content", "")
        for c in chunks
        if isinstance(c.get("message"), dict)
    )
    thinking = "".join(
        c.get("message", {}).get("thinking", "") or ""
        for c in chunks
        if isinstance(c.get("message"), dict)
    )
    done = next((c for c in chunks if c.get("done")), None)
    return {
        "text": text,
        "thinking_chars": len(thinking),
        "wall_seconds": round(wall, 2),
        "eval_count": (done or {}).get("eval_count"),
        "prompt_eval_count": (done or {}).get("prompt_eval_count"),
        "think_param": payload.get("think"),
        "model": payload.get("model"),
    }


async def main() -> None:
    stage = sys.argv[1]
    wanted = set(sys.argv[2:])
    cases = [c for c in CASES if not wanted or c["id"] in wanted]
    OUT.mkdir(parents=True, exist_ok=True)
    system_prompt, settings = effective_system_prompt()
    print(f"system prompt: {len(system_prompt)} chars | level {LEVEL.value}")
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        for case in cases:
            if stage == "pass1":
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": case["prompt"]},
                ]
            else:
                draft = json.loads(
                    (OUT / f"{case['id']}-pass1.json").read_text(encoding="utf-8")
                )["text"]
                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Исходный запрос пользователя:\n{case['prompt']}\n\n"
                            f"Мой черновик ответа:\n{draft}\n\n{CRITIQUE_PROMPT}"
                        ),
                    },
                ]
            try:
                result = await dispatch(client, backend, messages)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {case['id']}: {type(exc).__name__}: {exc}")
                raise
            result["case_id"] = case["id"]
            result["stage"] = stage
            (OUT / f"{case['id']}-{stage}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"{case['id']} {stage}: {result['wall_seconds']}s "
                f"prompt={result['prompt_eval_count']} eval={result['eval_count']} "
                f"think={result['thinking_chars']}ch out={len(result['text'])}ch"
            )


if __name__ == "__main__":
    asyncio.run(main())
