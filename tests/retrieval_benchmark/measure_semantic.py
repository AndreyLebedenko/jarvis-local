"""Human-run semantic measurement handoff for v1.8.0 task 8 (B2).

This module measures a REAL local embedding model against the fixed benchmark.
It hits the live Ollama endpoint, so it is hardware-dependent and is NOT part of
the pure automated suite (per the project testing protocol it is run by the
human, not the agent). The pure suite covers the retrieval logic through the
deterministic concept fixture in ``semantic.py``; this script swaps in a real
``embed_fn`` and additionally reports the per-turn query-embedding latency that
is the automatic-retrieval hot-path cost.

Exact commands for the selected stack (run from the repo root; join the
continued lines, or use the ``set PYTHONPATH=tests && ...`` form on cmd.exe):

    # primary: multilingual-e5-large-instruct
    PYTHONPATH=tests python -m retrieval_benchmark.measure_semantic \
        blaifa/multilingual-e5-large-instruct --hybrid --separation 0.05 \
        --query-prefix "query: " --passage-prefix "passage: "

    # fallback: embeddinggemma (latency)
    PYTHONPATH=tests python -m retrieval_benchmark.measure_semantic \
        embeddinggemma:300m-bf16 --hybrid --separation 0.2 \
        --query-prefix "task: search result | query: " \
        --passage-prefix "title: none | text: "

Model-specific query/passage prompts matter: without them cosine scores are
miscalibrated and a fixed threshold over-matches (e5 with no prefix returned
the distractor for every query). Recommended prefixes:

    bge-m3:            no prefixes (works on raw text)
    multilingual-e5*:  --query-prefix "query: " --passage-prefix "passage: "
    embeddinggemma:    --query-prefix "task: search result | query: " \
                       --passage-prefix "title: none | text: "

Gate: an absolute cosine threshold does not transfer across models (e5 needed
0.8 where bge/gemma worked at 0.5), so the default is ``--gate relative`` - a
per-query gate that needs no per-model tuning and keeps the distractor FP at
0.0. Use ``--gate absolute --min-similarity X`` only to reproduce the old
fixed-threshold behaviour for comparison. Watch the distractor FP rate under
either gate: it must stay 0.0.

While a run is in flight, capture host cost separately for the record:
    ollama ps                 # resident model + VRAM footprint
    nvidia-smi                # GPU/VRAM during query embedding

Report to bring back for the spike decision:
    - per-tier recall and precision from the printed table,
    - mean and p95 per-query embedding latency (the per-turn hot-path cost),
    - resident VRAM from ``ollama ps`` while the model is loaded.

This script deliberately does not add any dependency: it calls Ollama over HTTP
with the standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from collections.abc import Sequence
from urllib.parse import urlsplit

from .harness import evaluate_retrieval
from .morphology import pymorphy3_normalizer
from .semantic import (
    embedding_retrieval,
    hybrid_retrieval,
    relative_embedding_retrieval,
)

_DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _normalize_host(raw: str) -> str:
    """Turn an OLLAMA_HOST value into a connectable base URL.

    Ollama commonly exports a bind address such as ``0.0.0.0`` or
    ``0.0.0.0:11434`` with no scheme; ``urllib`` needs a full URL and cannot
    connect to the bind-all address, so add a scheme, map ``0.0.0.0`` to
    loopback, and default the port.
    """

    candidate = raw.strip().rstrip("/") or "http://127.0.0.1:11434"
    if "://" not in candidate:
        candidate = "http://" + candidate
    parts = urlsplit(candidate)
    host = parts.hostname or "127.0.0.1"
    if host == "0.0.0.0":  # bind-all address, map to loopback for the client
        host = "127.0.0.1"
    port = parts.port or 11434
    return f"{parts.scheme}://{host}:{port}"


def ollama_embed_function(
    model: str, host: str = _DEFAULT_HOST, *, timings: list[float] | None = None
):
    """Build an embed_fn backed by the live Ollama endpoint.

    When ``timings`` is provided, each single-text embedding call appends its
    elapsed seconds, so the caller can separate per-turn query latency from
    index-time document embedding.
    """

    endpoint = _normalize_host(host) + "/api/embeddings"

    def embed(texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
            request = urllib.request.Request(
                endpoint, data=payload, headers={"Content-Type": "application/json"}
            )
            start = time.perf_counter()
            with urllib.request.urlopen(request) as response:
                body = json.loads(response.read().decode("utf-8"))
            elapsed = time.perf_counter() - start
            if timings is not None and len(texts) == 1:
                timings.append(elapsed)
            vectors.append([float(value) for value in body["embedding"]])
        return vectors

    return embed


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, int(fraction * (len(ordered) - 1) + 0.5))
    return ordered[position]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Ollama embedding model name")
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument(
        "--gate",
        choices=("relative", "absolute"),
        default="relative",
        help="relative per-query gate (recommended) or fixed absolute threshold",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.5,
        help="absolute-gate threshold (ignored when --gate relative)",
    )
    parser.add_argument("--query-prefix", default="")
    parser.add_argument("--passage-prefix", default="")
    parser.add_argument(
        "--top-ratio",
        type=float,
        default=0.98,
        help="relative gate: keep docs within this fraction of the top score",
    )
    parser.add_argument(
        "--separation",
        type=float,
        default=0.01,
        help="relative gate: reject a query if top - median is below this",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="fuse with the pymorphy3 morphology baseline",
    )
    arguments = parser.parse_args()

    query_timings: list[float] = []
    embed_fn = ollama_embed_function(
        arguments.model, arguments.host, timings=query_timings
    )
    if arguments.gate == "relative":
        semantic = relative_embedding_retrieval(
            embed_fn,
            query_prefix=arguments.query_prefix,
            passage_prefix=arguments.passage_prefix,
            top_ratio=arguments.top_ratio,
            separation=arguments.separation,
        )
    else:
        semantic = embedding_retrieval(
            embed_fn,
            min_similarity=arguments.min_similarity,
            query_prefix=arguments.query_prefix,
            passage_prefix=arguments.passage_prefix,
        )

    if arguments.hybrid:
        retrieval = hybrid_retrieval(_normalized_retrieval_or_exit(), semantic)
        mode = f"hybrid (pymorphy3 + {arguments.model}), {arguments.gate} gate"
    else:
        retrieval = semantic
        mode = f"semantic only ({arguments.model}), {arguments.gate} gate"

    report = evaluate_retrieval(retrieval)

    print(f"=== B2 real embedding measurement: {mode} ===")
    print(report.format_table())
    print("")
    print(f"queries embedded:            {len(query_timings)}")
    print(f"query embed latency mean:    {_mean(query_timings) * 1000:.1f} ms")
    print(
        f"query embed latency p95:     {_percentile(query_timings, 0.95) * 1000:.1f} ms"
    )
    print("Capture 'ollama ps' VRAM separately for the per-turn cost record.")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _normalized_retrieval_or_exit():
    from .morphology import normalized_retrieval

    try:
        normalizer = pymorphy3_normalizer()
    except ImportError as exc:  # pragma: no cover - human-run guard
        raise SystemExit(f"--hybrid needs pymorphy3 installed: {exc}") from exc
    return normalized_retrieval(normalizer)


if __name__ == "__main__":  # pragma: no cover - human-run entry point
    main()
