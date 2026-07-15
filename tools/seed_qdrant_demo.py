#!/usr/bin/env python3
"""Seed the synthetic Qdrant MCP demonstration collection explicitly."""

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

MetadataValue = str | int | float | bool | None


@dataclass(frozen=True)
class DemoRecord:
    point_id: int
    content: str
    metadata: dict[str, MetadataValue]


def load_records(path: Path) -> tuple[DemoRecord, ...]:
    records: list[DemoRecord] = []
    point_ids: set[int] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"{path}:{line_number}: record must be an object")
        point_id = raw.get("id")
        content = raw.get("content")
        metadata = raw.get("metadata", {})
        if not isinstance(point_id, int) or isinstance(point_id, bool) or point_id < 0:
            raise ValueError(f"{path}:{line_number}: id must be a non-negative integer")
        if point_id in point_ids:
            raise ValueError(f"{path}:{line_number}: duplicate id {point_id}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                f"{path}:{line_number}: content must be a non-empty string"
            )
        if not isinstance(metadata, dict) or not all(
            isinstance(key, str) and isinstance(value, str | int | float | bool | None)
            for key, value in metadata.items()
        ):
            raise ValueError(
                f"{path}:{line_number}: metadata must contain JSON scalar values"
            )
        point_ids.add(point_id)
        records.append(DemoRecord(point_id, content, dict(metadata)))
    if not records:
        raise ValueError(f"{path}: no records found")
    return tuple(records)


async def seed_collection(
    path: Path | None,
    url: str | None,
    collection: str,
    records: tuple[DemoRecord, ...],
    model_name: str,
    *,
    replace: bool,
) -> None:
    # Provider dependencies deliberately live only in its isolated venv.
    from mcp_server_qdrant.embeddings.fastembed import FastEmbedProvider
    from qdrant_client import AsyncQdrantClient, models

    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
    client = AsyncQdrantClient(path=str(path) if path is not None else None, url=url)
    try:
        exists = await client.collection_exists(collection)
        if exists and not replace:
            raise RuntimeError(
                f"Collection {collection!r} already exists; pass --replace to "
                "recreate it"
            )
        if exists:
            await client.delete_collection(collection)

        embedding_provider = FastEmbedProvider(model_name)
        vectors = await embedding_provider.embed_documents(
            [record.content for record in records]
        )
        vector_name = embedding_provider.get_vector_name()
        await client.create_collection(
            collection_name=collection,
            vectors_config={
                vector_name: models.VectorParams(
                    size=embedding_provider.get_vector_size(),
                    distance=models.Distance.COSINE,
                )
            },
        )
        await client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=record.point_id,
                    vector={vector_name: vector},
                    payload={"document": record.content, "metadata": record.metadata},
                )
                for record, vector in zip(records, vectors, strict=True)
            ],
            wait=True,
        )
    finally:
        await client.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("examples/mcp/qdrant-demo.jsonl"),
    )
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--path", type=Path)
    destination.add_argument("--url")
    parser.add_argument("--collection", default="jarvis-demo")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--replace", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    records = load_records(args.data)
    path = args.path
    if path is None and args.url is None:
        path = Path("examples/mcp/data/qdrant")
    asyncio.run(
        seed_collection(
            path,
            args.url,
            args.collection,
            records,
            args.model,
            replace=args.replace,
        )
    )
    destination = args.url or path
    print(f"Seeded {len(records)} records into {args.collection!r} at {destination}")


if __name__ == "__main__":
    main()
