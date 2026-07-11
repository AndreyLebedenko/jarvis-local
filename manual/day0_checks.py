#!/usr/bin/env python3
"""Day-0 checks v2 — rewritten from experimental findings.

Established so far:
  * Audio reaches gemma4 via the "images" field of /api/chat (base64 wav).
    The "audio" field is silently dropped by Ollama.
  * gemma4:12b-it-qat responds to audio; first token ~2 s.

Checks:
  fidelity    : did the model REALLY hear the audio (vs reconstructing
                known text from memory)? Use a NONSENSE recording.
  intonation  : same words, two deliveries -> does tone perception differ?
  ocr         : screenshot OCR at high visual token budget
  vram        : VRAM behaviour with the 64K context actually filled

Usage:
  python manual/day0_checks.py fidelity   nonsense.wav
  python manual/day0_checks.py intonation neutral.wav emotional.wav
  python manual/day0_checks.py ocr        screenshot.png
  python manual/day0_checks.py vram
  python manual/day0_checks.py <check> <files...> --model gemma4:12b-it-qat

Default model: gemma4:12b-it-qat (override with --model).
Every request prints latency and, on anything unexpected, the full
request/response JSON so we debug facts, not guesses.
"""

import argparse
import base64
import json
import subprocess
import sys
import time

import requests

OLLAMA_URL = "http://localhost:11434"


def b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def chat(
    model: str,
    content: str,
    media_b64: list[str] | None = None,
    verbose: bool = False,
    **options,
) -> str:
    """Single-turn chat. Audio and images both go through 'images'."""
    msg = {"role": "user", "content": content}
    if media_b64:
        msg["images"] = media_b64
    payload = {
        "model": model,
        "messages": [msg],
        "stream": False,
        "options": {"num_ctx": 65536, **options},
    }
    t0 = time.time()
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"HTTP {r.status_code} after {dt:.1f}s")
        print(
            "Request (media truncated):",
            json.dumps(
                {**payload, "messages": [{**msg, "images": ["<b64>"]}]},
                ensure_ascii=False,
            )[:500],
        )
        print("Response body:", r.text[:2000])
        r.raise_for_status()
    data = r.json()
    text = data["message"]["content"]
    # Ollama returns nanosecond timings when available.
    load = data.get("load_duration", 0) / 1e9
    prompt_eval = data.get("prompt_eval_duration", 0) / 1e9
    gen = data.get("eval_duration", 0) / 1e9
    print(
        f"[{dt:.1f}s total | load {load:.1f}s | prefill {prompt_eval:.1f}s "
        f"| gen {gen:.1f}s | {data.get('eval_count', '?')} tokens]"
    )
    if verbose or not text.strip():
        print("Full response JSON:", json.dumps(data, ensure_ascii=False)[:2000])
    return text


# --- fidelity ----------------------------------------------------------------


def check_fidelity(model: str, wav: str) -> None:
    """The recording MUST be unguessable: random numbers, invented words.
    Famous poems prove nothing — the model can reconstruct them from
    a half-heard fragment."""
    text = chat(
        model,
        "Transcribe this recording verbatim, word for word. "
        "Do not correct, complete, or interpret anything.",
        [b64(wav)],
    )
    print(f"\n{text}\n")
    print(
        ">>> VERDICT: compare word-by-word with what you actually said. "
        "Exact nonsense reproduced = audio path is real and faithful."
    )


# --- intonation --------------------------------------------------------------

INTONATION_PROMPT = (
    "Listen to this recording. Answer:\n"
    "1. Verbatim transcript.\n"
    "2. The speaker's emotional tone and manner (neutral / irritated / "
    "cheerful / tired / questioning / other). Justify strictly from "
    "acoustic cues — pitch, tempo, volume, pauses — NOT from word choice."
)


def check_intonation(model: str, neutral_wav: str, emotional_wav: str) -> None:
    for label, wav in [("NEUTRAL", neutral_wav), ("EMOTIONAL", emotional_wav)]:
        print(f"--- {label} ({wav}) ---")
        print(chat(model, INTONATION_PROMPT, [b64(wav)]), "\n")
    print(
        ">>> VERDICT: tone descriptions must differ AND match reality. "
        "Identical = prosody lost in this quant -> emotion2vec side "
        "channel goes back into the architecture."
    )


# --- ocr ----------------------------------------------------------------------


def check_ocr(model: str, png: str) -> None:
    text = chat(
        model,
        "Read ALL text visible in this screenshot, preserving layout. "
        "Include the smallest text: menus, status bars, tab titles.",
        [b64(png)],
        visual_token_budget=1120,
    )
    print(f"\n{text}\n")
    print(
        ">>> VERDICT: check the smallest real font (IDE, terminal). "
        "If garbled, the capture module needs a region-select mode "
        "(crop at full resolution) rather than a bigger budget."
    )


# --- vram ----------------------------------------------------------------------


def nvidia_smi() -> str:
    return subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    ).stdout.strip()


def check_vram(model: str) -> None:
    print(f"VRAM before load : {nvidia_smi()}")
    chat(model, "Hi")
    print(f"VRAM after load  : {nvidia_smi()}")
    filler = "word " * 45000
    chat(model, filler + "\nEstimate how many words are above.")
    print(f"VRAM at ~64K ctx : {nvidia_smi()}")
    print(
        "\n>>> VERDICT: if memory.used approaches 16 GB or the long request "
        "showed a huge prefill time, set OLLAMA_KV_CACHE_TYPE=q8_0 or drop "
        "num_ctx to 32768."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("check", choices=["fidelity", "intonation", "ocr", "vram"])
    p.add_argument("files", nargs="*")
    p.add_argument("--model", default="gemma4:12b-it-qat")
    a = p.parse_args()
    need = {"fidelity": 1, "intonation": 2, "ocr": 1, "vram": 0}[a.check]
    if len(a.files) != need:
        sys.exit(f"'{a.check}' expects {need} file argument(s), got {len(a.files)}")
    fn = {
        "fidelity": check_fidelity,
        "intonation": check_intonation,
        "ocr": check_ocr,
        "vram": check_vram,
    }[a.check]
    fn(a.model, *a.files)
