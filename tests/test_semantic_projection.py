from __future__ import annotations

from pathlib import Path

import httpx

from jarvis.core.config import (
    BackendSettings,
    HistorySemanticSettings,
)
from jarvis.journal import (
    HistoryCorpusRepository,
    HistoryProjectionStatus,
    JournalEvent,
    JournalEventRecord,
    JournalEventRef,
    JournalStore,
    OllamaEmbeddingProvider,
    SemanticCandidateQuery,
    SemanticCandidateStatus,
    SemanticPassageIndex,
)


def test_rebuild_creates_deterministic_source_grounded_passages(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "alpha text"))
    store.append(_event("20260716-153000-ab12", 1, "system", "ignored"))
    store.append(_event("20260716-153000-ab12", 2, "assistant", "beta text"))
    repository = _build_corpus(store, tmp_path / "derived")
    settings = _semantic_settings()
    first = SemanticPassageIndex(
        repository, tmp_path / "derived", settings, _FakeEmbedder()
    )

    first.rebuild()
    first_passages = first.list_passages()
    first.rebuild()

    assert first.state().status is HistoryProjectionStatus.ENABLED
    assert [(passage.passage_id, passage.text) for passage in first_passages] == [
        ("20260716-153000-ab12:0", "alpha text"),
        ("20260716-153000-ab12:2", "beta text"),
    ]
    assert first.list_passages() == first_passages


def test_append_updates_only_the_referenced_event(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    first_event = _event("20260716-153000-ab12", 0, "user", "first")
    store.append(first_event)
    repository = _build_corpus(store, tmp_path / "derived")
    embedder = _FakeEmbedder()
    index = SemanticPassageIndex(
        repository, tmp_path / "derived", _semantic_settings(), embedder
    )
    index.rebuild()
    calls_after_rebuild = len(embedder.calls)

    second_event = _event("20260716-153000-ab12", 1, "assistant", "second")
    index.project_event(
        JournalEventRecord(JournalEventRef(second_event.session_id, 1), second_event)
    )

    assert len(embedder.calls) == calls_after_rebuild + 1
    assert embedder.calls[-1] == ("passage: second",)
    assert [passage.text for passage in index.list_passages()] == ["first", "second"]

    corrected = _event("20260716-153000-ab12", 1, "assistant", "corrected")
    index.project_event(
        JournalEventRecord(JournalEventRef(corrected.session_id, 1), corrected)
    )

    assert [passage.text for passage in index.list_passages()] == ["first", "corrected"]


def test_delete_session_removes_only_that_session_semantic_data(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "remove me"))
    store.append(_event("20260717-090000-cd34", 0, "user", "keep me"))
    repository = _build_corpus(store, tmp_path / "derived")
    index = SemanticPassageIndex(
        repository, tmp_path / "derived", _semantic_settings(), _FakeEmbedder()
    )
    index.rebuild()

    index.delete_session_projection("20260716-153000-ab12")

    assert [passage.text for passage in index.list_passages()] == ["keep me"]


def test_backend_mismatch_is_unavailable_until_rebuilt(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "stable"))
    repository = _build_corpus(store, tmp_path / "derived")
    first_settings = _semantic_settings(model="model-a")
    first = SemanticPassageIndex(
        repository, tmp_path / "derived", first_settings, _FakeEmbedder()
    )
    first.rebuild()

    second_settings = _semantic_settings(model="model-b")
    second = SemanticPassageIndex(
        repository, tmp_path / "derived", second_settings, _FakeEmbedder()
    )

    assert second.state().status is HistoryProjectionStatus.UNAVAILABLE
    assert second.state().stored_backend is not None
    assert second.state().stored_backend.model == "model-a"

    second.rebuild_if_backend_changed()

    assert second.state().status is HistoryProjectionStatus.ENABLED
    assert second.state().stored_backend == second.configured_backend


def test_failed_rebuild_preserves_old_index_and_marks_state_unavailable(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "old data"))
    repository = _build_corpus(store, tmp_path / "derived")
    first = SemanticPassageIndex(
        repository,
        tmp_path / "derived",
        _semantic_settings(model="model-a"),
        _FakeEmbedder(),
    )
    first.rebuild()

    failing = SemanticPassageIndex(
        repository,
        tmp_path / "derived",
        _semantic_settings(model="model-b"),
        _FailingEmbedder(),
    )
    failing.rebuild_if_backend_changed()

    assert failing.state().status is HistoryProjectionStatus.UNAVAILABLE
    assert failing.state().stored_backend == first.configured_backend
    assert [passage.text for passage in failing.list_passages()] == ["old data"]


def test_query_returns_scored_references_without_passage_text(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    alpha = store.append(_event("20260716-153000-ab12", 0, "user", "alpha"))
    beta = store.append(_event("20260716-153000-ab12", 1, "assistant", "beta"))
    repository = _build_corpus(store, tmp_path / "derived")
    index = SemanticPassageIndex(
        repository, tmp_path / "derived", _semantic_settings(), _FakeEmbedder()
    )
    index.rebuild()

    result = index.query(SemanticCandidateQuery("alpha", limit=2))

    assert result.status is SemanticCandidateStatus.ACCEPTED
    assert result.candidates[0].reference == alpha
    assert result.candidates[0].score == 1.0
    assert result.candidates[1].reference == beta
    assert not hasattr(result.candidates[0], "text")


def test_query_is_unavailable_when_projection_is_disabled(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    repository = _build_corpus(store, tmp_path / "derived")
    settings = _semantic_settings(enabled=False)
    index = SemanticPassageIndex(
        repository, tmp_path / "derived", settings, _FakeEmbedder()
    )

    index.rebuild()
    result = index.query(SemanticCandidateQuery("anything"))

    assert index.state().status is HistoryProjectionStatus.UNAVAILABLE
    assert result.status is SemanticCandidateStatus.UNAVAILABLE
    assert not index.db_path.exists()


def test_query_reports_timeout_when_query_embedding_exceeds_deadline(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "alpha"))
    repository = _build_corpus(store, tmp_path / "derived")
    query_embedder = _TimeoutEmbedder()
    index = SemanticPassageIndex(
        repository,
        tmp_path / "derived",
        _semantic_settings(),
        _FakeEmbedder(),
        query_embedder=query_embedder,
    )

    index.rebuild()
    result = index.query(SemanticCandidateQuery("alpha"))

    assert result.status is SemanticCandidateStatus.TIMEOUT
    assert query_embedder.calls == [("query: alpha",)]


def test_ollama_embedding_provider_uses_local_embeddings_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"embedding": [1, 2.5]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OllamaEmbeddingProvider(
        BackendSettings(endpoint="http://ollama.local"),
        _semantic_settings(model="embedding-model"),
        client=client,
    )
    try:
        vectors = provider.embed(("query text",))
    finally:
        client.close()

    assert vectors == [(1.0, 2.5)]
    assert requests[0].url == "http://ollama.local/api/embeddings"
    assert requests[0].read().decode("utf-8") == (
        '{"model":"embedding-model","prompt":"query text"}'
    )


def test_ollama_embedding_provider_separates_query_and_rebuild_connect_timeouts(
    monkeypatch,
) -> None:
    created_clients: list[_RecordingClient] = []

    def client_factory(*, base_url, timeout):
        client = _RecordingClient(base_url=base_url, timeout=timeout)
        created_clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", client_factory)

    rebuild_provider = OllamaEmbeddingProvider(
        BackendSettings(endpoint="http://ollama.local"),
        _semantic_settings(model="embedding-model"),
    )
    query_provider = OllamaEmbeddingProvider(
        BackendSettings(endpoint="http://ollama.local"),
        _semantic_settings(model="embedding-model"),
        connect_timeout_seconds=1.0,
        read_timeout_seconds=1.0,
    )

    rebuild_vectors = rebuild_provider.embed(("rebuild text",))
    query_vectors = query_provider.embed(("query text",))

    assert rebuild_vectors == [(1.0, 2.5)]
    assert query_vectors == [(1.0, 2.5)]
    assert len(created_clients) == 2
    assert created_clients[0].timeout.connect == 10.0
    assert created_clients[0].timeout.read == 120.0
    assert created_clients[0].timeout.write == 120.0
    assert created_clients[0].timeout.pool == 120.0
    assert created_clients[1].timeout.connect == 1.0
    assert created_clients[1].timeout.read == 1.0
    assert created_clients[1].timeout.write == 1.0
    assert created_clients[1].timeout.pool == 1.0


def _semantic_settings(
    *, model: str = "test-model", enabled: bool = True
) -> HistorySemanticSettings:
    return HistorySemanticSettings(
        enabled=enabled,
        model=model,
        query_prefix="query: ",
        passage_prefix="passage: ",
        dimension=2,
    )


def _build_corpus(store: JournalStore, root: Path) -> HistoryCorpusRepository:
    repository = HistoryCorpusRepository(store, root)
    repository.rebuild()
    return repository


def _event(session_id: str, position: int, role: str, text: str) -> JournalEvent:
    del position
    return JournalEvent(
        session_id=session_id,
        timestamp="2026-07-16T15:30:00+01:00",
        source=role,
        role=role,
        text=text,
        media=(),
        transcript=None,
    )


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        return [(1.0, 0.0) if "alpha" in text else (0.0, 1.0) for text in texts]


class _FailingEmbedder:
    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        del texts
        raise RuntimeError("embedding backend unavailable")


class _TimeoutEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        raise httpx.TimeoutException("query embedding timed out")


class _RecordingClient:
    def __init__(self, *, base_url: str, timeout: httpx.Timeout) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __enter__(self) -> _RecordingClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def post(self, url: str, json: dict[str, str]) -> httpx.Response:
        self.requests.append((url, json))
        request = httpx.Request("POST", url, json=json)
        return httpx.Response(200, request=request, json={"embedding": [1, 2.5]})
