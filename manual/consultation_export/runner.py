"""Serial local calls and immutable experiment inputs; no external transport."""

import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from jarvis.core.config import load_settings
from manual.consultation_export.corpus import CASES, SEEDS, Case
from manual.consultation_export.protocol import (
    EXPORT_SCHEMA,
    PREPARATION_PROMPT,
    Export,
    application_messages,
    build_payload,
    decode_export,
    export_findings,
    local_endpoint,
    object_value,
    render_reference,
    text_value,
)

ROOT = Path(__file__).resolve().parents[2]
INPUTS = (
    "manual/consultation_export/corpus.py",
    "manual/consultation_export/protocol.py",
    "manual/consultation_export/runner.py",
    "manual/manual_check_consultation_export.py",
    "tasks/consultation-export-rubric.md",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def read_json(path: Path) -> dict[str, object]:
    return object_value(json.loads(path.read_text(encoding="utf-8")))


def fingerprint() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS
    }


def freeze(out: Path) -> None:
    settings = load_settings()
    backend = settings.backend
    endpoint = local_endpoint(backend.endpoint)
    # Existence is checked before contacting Ollama; a run is never overwritten.
    if out.exists():
        raise ValueError("output directory already exists; refusing to overwrite")
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        version = client.get(endpoint + "/api/version")
        version.raise_for_status()
        tags = client.get(endpoint + "/api/tags")
        tags.raise_for_status()
    models = object_value(tags.json()).get("models")
    if not isinstance(models, list):
        raise ValueError("invalid model inventory")
    matching = [m for m in models if object_value(m).get("name") == backend.model]
    if len(matching) != 1:
        raise ValueError("configured model is not uniquely installed; no downloads")
    manifest = {
        "candidate": "v1",
        "inputs_sha256": fingerprint(),
        "endpoint": endpoint,
        "model": backend.model,
        "num_ctx": backend.num_ctx,
        "read_timeout_seconds": max(backend.read_timeout_seconds, 300),
        "seeds": SEEDS,
        "python": sys.version,
        "platform": platform.platform(),
        "httpx": httpx.__version__,
        "ollama": version.json(),
        "installed_model": matching[0],
        "cases": [asdict(case) for case in CASES],
        "options": {"temperature": 0.2, "num_predict": 8192, "think": False},
    }
    write_json(out / "manifest.json", manifest)
    print(f"Frozen {len(CASES)} fixtures, {len(SEEDS)} repeats: {out}", flush=True)


def verified_manifest(out: Path) -> dict[str, object]:
    manifest = read_json(out / "manifest.json")
    if manifest["inputs_sha256"] != fingerprint():
        raise ValueError("frozen inputs changed; do not resume this experiment")
    return manifest


def call_model(
    client: httpx.Client, endpoint: str, payload: dict[str, object]
) -> dict[str, object]:
    local_endpoint(endpoint)
    start = time.perf_counter()
    response = client.post(endpoint + "/api/chat", json=payload)
    response.raise_for_status()
    body = object_value(response.json())
    if body.get("done") is not True:
        raise ValueError("Ollama response missing completion marker")
    return {
        "request": payload,
        "response": body,
        "seconds": time.perf_counter() - start,
    }


def output_text(record: dict[str, object]) -> tuple[str, str]:
    response = object_value(record["response"])
    return (
        text_value(object_value(response["message"])["content"]),
        text_value(response["done_reason"]),
    )


def record_path(out: Path, stage: str, case: Case, seed: int) -> Path:
    return out / "calls" / stage / f"{case.name}-s{seed}.json"


def preparation_messages(case: Case) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PREPARATION_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scope": "selected turns only; other turns are not provided",
                    "turns": case.selection(),
                },
                ensure_ascii=False,
            ),
        },
    ]


def payload_for(
    manifest: dict[str, object],
    messages: list[dict[str, str]],
    seed: int,
    schema: dict[str, object] | None = None,
) -> dict[str, object]:
    num_ctx = manifest["num_ctx"]
    if not isinstance(num_ctx, int):
        raise ValueError("invalid frozen context window")
    return build_payload(text_value(manifest["model"]), messages, seed, num_ctx, schema)


def run_preparation(out: Path) -> None:
    manifest = verified_manifest(out)
    endpoint = text_value(manifest["endpoint"])
    timeout = float(str(manifest["read_timeout_seconds"]))
    with httpx.Client(
        timeout=timeout, trust_env=False, follow_redirects=False
    ) as client:
        for case in CASES:
            for seed in SEEDS:
                path = record_path(out, "prepare", case, seed)
                if path.exists():
                    continue
                payload = payload_for(
                    manifest, preparation_messages(case), seed, EXPORT_SCHEMA
                )
                record = call_model(client, endpoint, payload)
                write_json(path, record)
                print(
                    f"prepare {case.name} s{seed}: {record['seconds']:.1f}s", flush=True
                )


def load_export(out: Path, case: Case, seed: int) -> Export:
    return decode_export(
        *output_text(read_json(record_path(out, "prepare", case, seed)))
    )


def run_application(out: Path) -> None:
    manifest = verified_manifest(out)
    review = read_json(out / "preparation-review.json")
    if review.get("decision") != "proceed" or review.get(
        "manifest_sha256"
    ) != file_hash(out / "manifest.json"):
        raise ValueError("application requires a preparation review for this manifest")
    timeout = float(str(manifest["read_timeout_seconds"]))
    with httpx.Client(
        timeout=timeout, trust_env=False, follow_redirects=False
    ) as client:
        for case in CASES:
            for seed in SEEDS:
                result = load_export(out, case, seed)
                answer = render_reference(
                    case.reference_answer, result, case.reference_private_terms
                )
                for arm in ("control", "A", "B"):
                    _run_application_call(
                        client, manifest, out, case, seed, result, answer, arm
                    )


def _run_application_call(
    client: httpx.Client,
    manifest: dict[str, object],
    out: Path,
    case: Case,
    seed: int,
    result: Export,
    answer: str,
    arm: str,
) -> None:
    path = record_path(out, arm, case, seed)
    if path.exists():
        return
    reference = case.reference_answer if arm == "control" else answer
    messages = application_messages(case.source(), result, reference, arm)
    record = call_model(
        client, text_value(manifest["endpoint"]), payload_for(manifest, messages, seed)
    )
    write_json(path, record)
    print(f"apply {arm} {case.name} s{seed}: {record['seconds']:.1f}s", flush=True)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_preparation(out: Path) -> None:
    verified_manifest(out)
    rows: list[dict[str, object]] = []
    for case in CASES:
        for seed in SEEDS:
            record = read_json(record_path(out, "prepare", case, seed))
            row: dict[str, object] = {
                "case": case.name,
                "seed": seed,
                "seconds": record["seconds"],
            }
            try:
                result = decode_export(*output_text(record))
            except (ValueError, KeyError) as error:
                row["protocol_error"] = str(error)
            else:
                expected = tuple((t["id"], t["role"]) for t in case.selection())
                row.update(export_findings(result, expected, case.sensitive))
                row["risks"] = result.risks
                row["input_chars"] = sum(len(t["content"]) for t in case.selection())
                row["output_chars"] = len(result.text)
            rows.append(row)
    write_json(
        out / "preparation-scores.json",
        {
            "manifest_sha256": file_hash(out / "manifest.json"),
            "rows": rows,
            "semantic_review": (
                "pending; literal checks cannot establish preservation or privacy"
            ),
        },
    )
    print(
        f"Wrote {len(rows)} preliminary scores; semantic review required.", flush=True
    )
