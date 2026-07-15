import json
from pathlib import Path

import pytest

from tools.seed_qdrant_demo import DemoRecord, load_records


def test_load_records_parses_the_checked_in_demo_dataset():
    records = load_records(Path("examples/mcp/qdrant-demo.jsonl"))

    assert len(records) == 6
    assert records[0] == DemoRecord(
        point_id=1,
        content=(
            "Project Aurora uses the callsign Northstar for its production environment."
        ),
        metadata={"source": "synthetic-project-handbook", "topic": "deployment"},
    )


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ([], "record must be an object"),
        ({"id": True, "content": "text"}, "id must be a non-negative integer"),
        ({"id": 1, "content": ""}, "content must be a non-empty string"),
        (
            {"id": 1, "content": "text", "metadata": {"nested": []}},
            "metadata must contain JSON scalar values",
        ),
    ],
)
def test_load_records_rejects_invalid_demo_data(tmp_path, record, message):
    path = tmp_path / "data.jsonl"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_records(path)


def test_load_records_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"id": 1, "content": "one"}\n{"id": 1, "content": "two"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate id 1"):
        load_records(path)


def test_load_records_rejects_an_empty_dataset(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no records found"):
        load_records(path)
