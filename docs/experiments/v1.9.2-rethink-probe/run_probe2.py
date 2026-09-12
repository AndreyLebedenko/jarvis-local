#!/usr/bin/env python3
"""Rethink probe, arm 2: raw drafts (reasoning OFF) then two critic variants.

Stages:
  draft:<level>            generate a draft at that reasoning level
  crit:<level>:<draft_tag> critique a stored draft at that reasoning level

The reasoning level drives BOTH the payload's think parameter and the
reasoning section appended to the system prompt, exactly as production does
(app.py's _compose_effective_system_prompt). Sampling options come from
[backend] unchanged; the seed is fixed for control.
"""

from __future__ import annotations

import asyncio
import json
import os
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
from run_probe import CRITIQUE_PROMPT  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
SEED = 19200
REPO = Path("D:/AI/Jarvis")
LEVELS = {
    "off": ReasoningLevel.OFF,
    "low": ReasoningLevel.LOW,
    "medium": ReasoningLevel.MEDIUM,
    "high": ReasoningLevel.HIGH,
}


def system_prompt_for(level: ReasoningLevel, settings) -> str:
    loader = MemoryFileLoader(build_memory_file_specs(settings.memory))
    base = loader.compose_system_prompt(settings.prompts.system, include_memory=True)
    return _compose_effective_system_prompt(base, level, settings.prompts)


async def dispatch(client, backend, messages, level) -> dict:
    payload = backend.build_payload(messages, None, reasoning_level=level)
    options = dict(payload.get("options") or {})
    options["seed"] = SEED
    # Ollama counts thinking tokens against num_predict, and [backend] sets
    # no cap: the only stop is num_ctx. Two runs already burned the full
    # 65536-token context in the thinking block and returned an empty
    # answer (c02 draft at level 2: 22 min, 63843 tokens, 0 chars out), so
    # a cap is the difference between a fast empty result and a 22-minute one.
    cap = os.environ.get("PROBE_NUM_PREDICT")
    if cap:
        options["num_predict"] = int(cap)
    payload["options"] = options
    chunks = []
    started = time.perf_counter()
    async with client.stream("POST", "/api/chat", json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.strip():
                chunks.append(json.loads(line))
    wall = time.perf_counter() - started
    msgs = [c.get("message", {}) for c in chunks if isinstance(c.get("message"), dict)]
    done = next((c for c in chunks if c.get("done")), None)
    return {
        "text": "".join(m.get("content", "") for m in msgs),
        "thinking_chars": sum(len(m.get("thinking") or "") for m in msgs),
        "wall_seconds": round(wall, 2),
        "eval_count": (done or {}).get("eval_count"),
        "prompt_eval_count": (done or {}).get("prompt_eval_count"),
        "think_param": payload.get("think"),
        "model": payload.get("model"),
    }


async def main() -> None:
    spec = sys.argv[1].split(":")
    wanted = set(sys.argv[2:])
    cases = [c for c in CASES if not wanted or c["id"] in wanted]
    os.chdir(REPO)
    settings = load_settings(REPO / "config.toml")
    OUT.mkdir(parents=True, exist_ok=True)

    kind, level_name = spec[0], spec[1]
    level = LEVELS[level_name]
    draft_tag = spec[2] if len(spec) > 2 else None
    tag = f"{kind}-{level_name}" + (f"-over-{draft_tag}" if draft_tag else "")
    sysprompt = system_prompt_for(level, settings)
    print(f"{tag}: system {len(sysprompt)} chars, think={level.value}")

    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        for case in cases:
            if kind == "draft":
                content = case["prompt"]
            else:
                draft = json.loads(
                    (OUT / f"{case['id']}-{draft_tag}.json").read_text(encoding="utf-8")
                )["text"]
                content = (
                    f"Исходный запрос пользователя:\n{case['prompt']}\n\n"
                    f"Мой черновик ответа:\n{draft}\n\n{CRITIQUE_PROMPT}"
                )
            messages = [
                {"role": "system", "content": sysprompt},
                {"role": "user", "content": content},
            ]
            result = await dispatch(client, backend, messages, level)
            result |= {"case_id": case["id"], "stage": tag}
            (OUT / f"{case['id']}-{tag}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"  {case['id']}: {result['wall_seconds']}s "
                f"eval={result['eval_count']} think={result['thinking_chars']}ch "
                f"out={len(result['text'])}ch"
            )


if __name__ == "__main__":
    asyncio.run(main())
