from __future__ import annotations

import logging
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


def test_rebuild_skips_only_the_passage_that_fails_to_embed(
    tmp_path: Path, caplog
) -> None:
    # Closes bug report 2026-08-09: one oversized passage rejected by the
    # embedding backend must not void the whole semantic projection.
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "alpha short"))
    store.append(_event("20260716-153000-ab12", 1, "assistant", "b" * 5000))
    store.append(_event("20260716-153000-ab12", 2, "user", "alpha again"))
    repository = _build_corpus(store, tmp_path / "derived")
    index = SemanticPassageIndex(
        repository,
        tmp_path / "derived",
        _semantic_settings(),
        _OversizedRejectingEmbedder(max_text_length=100),
    )

    with caplog.at_level(logging.WARNING):
        index.rebuild()

    assert index.state().status is HistoryProjectionStatus.ENABLED
    assert [passage.text for passage in index.list_passages()] == [
        "alpha short",
        "alpha again",
    ]
    result = index.query(SemanticCandidateQuery("alpha", limit=5))
    assert result.status is SemanticCandidateStatus.ACCEPTED
    assert len(result.candidates) == 2
    assert any(
        "20260716-153000-ab12:1" in record.getMessage() for record in caplog.records
    )


def test_incomplete_rebuild_is_retried_on_next_startup(tmp_path: Path) -> None:
    # Bug report 2026-08-09, retry half: a passage skipped because it failed to
    # embed must get another chance on a normal restart, not stay missing until
    # the backend identity changes.
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "alpha short"))
    store.append(_event("20260716-153000-ab12", 1, "assistant", "b" * 5000))
    repository = _build_corpus(store, tmp_path / "derived")
    settings = _semantic_settings()
    first = SemanticPassageIndex(
        repository,
        tmp_path / "derived",
        settings,
        _OversizedRejectingEmbedder(max_text_length=100),
    )
    first.rebuild()
    assert [passage.text for passage in first.list_passages()] == ["alpha short"]

    healed_embedder = _FakeEmbedder()
    restarted = SemanticPassageIndex(
        repository, tmp_path / "derived", settings, healed_embedder
    )
    restarted.rebuild_if_backend_changed()

    assert healed_embedder.calls  # the incomplete index forced a rebuild
    assert [passage.text for passage in restarted.list_passages()] == [
        "alpha short",
        "b" * 5000,
    ]


def test_complete_rebuild_keeps_the_fast_path_on_next_startup(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "alpha"))
    repository = _build_corpus(store, tmp_path / "derived")
    settings = _semantic_settings()
    SemanticPassageIndex(
        repository, tmp_path / "derived", settings, _FakeEmbedder()
    ).rebuild()

    idle_embedder = _FakeEmbedder()
    restarted = SemanticPassageIndex(
        repository, tmp_path / "derived", settings, idle_embedder
    )
    restarted.rebuild_if_backend_changed()

    assert idle_embedder.calls == []  # complete index skipped the rebuild


def test_failed_live_update_marks_index_incomplete_so_restart_rebuilds(
    tmp_path: Path,
) -> None:
    # Bug report 2026-08-09, live-update half: an incremental update that fails
    # to embed must not leave the persisted index marked complete, or the next
    # startup would fast-path over the missing passage forever.
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", "alpha"))
    repository = _build_corpus(store, tmp_path / "derived")
    settings = _semantic_settings()
    SemanticPassageIndex(
        repository, tmp_path / "derived", settings, _FakeEmbedder()
    ).rebuild()

    updating = SemanticPassageIndex(
        repository, tmp_path / "derived", settings, _FailingEmbedder()
    )
    failing = _event("20260716-153000-ab12", 1, "assistant", "beta")
    updating.project_event(
        JournalEventRecord(JournalEventRef(failing.session_id, 1), failing)
    )
    assert updating.state().status is HistoryProjectionStatus.UNAVAILABLE

    healed = _FakeEmbedder()
    restarted = SemanticPassageIndex(repository, tmp_path / "derived", settings, healed)
    restarted.rebuild_if_backend_changed()

    assert healed.calls  # the incomplete flag forced a rebuild


def test_rebuild_marks_unavailable_without_leaking_content_when_all_fail(
    tmp_path: Path, caplog
) -> None:
    # Bug report 2026-08-09, degradation half: when every passage fails, the
    # projection goes unavailable without surfacing any backend error message
    # (which can echo passage content) in last_error or the logged traceback.
    secret = "confidential-passage-body-42"
    store = JournalStore(tmp_path / "journal")
    store.append(_event("20260716-153000-ab12", 0, "user", secret))
    store.append(_event("20260716-153000-ab12", 1, "assistant", "beta"))
    repository = _build_corpus(store, tmp_path / "derived")
    index = SemanticPassageIndex(
        repository,
        tmp_path / "derived",
        _semantic_settings(),
        _ContentEchoingFailingEmbedder(),
    )

    with caplog.at_level(logging.DEBUG):
        index.rebuild()

    state = index.state()
    assert state.status is HistoryProjectionStatus.UNAVAILABLE
    assert index.list_passages() == ()
    assert state.last_error is not None
    assert secret not in state.last_error
    assert secret not in caplog.text


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


def test_ollama_embedding_provider_uses_local_embed_endpoint_with_truncation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"embeddings": [[1, 2.5]]})

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
    assert requests[0].url == "http://ollama.local/api/embed"
    assert requests[0].read().decode("utf-8") == (
        '{"model":"embedding-model","input":"query text","truncate":true}'
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


class _ContentEchoingFailingEmbedder:
    """Fails every request with the offending passage text in the message.

    A stand-in for the worst case the projection must defend against: a backend
    whose error string echoes the prompt. The projection must not surface that
    message anywhere.
    """

    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        raise RuntimeError(f"backend rejected prompt: {texts[0]}")


class _OversizedRejectingEmbedder:
    """Rejects any text longer than a cap, one request per text.

    Mirrors ``OllamaEmbeddingProvider._embed_with_client``: it loops over the
    batch and raises on the first request the backend refuses, exactly how a
    single oversized passage 500s the whole-batch call while each shorter
    passage embeds cleanly on its own.
    """

    def __init__(self, *, max_text_length: int) -> None:
        self._max_text_length = max_text_length
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            if len(text) > self._max_text_length:
                raise RuntimeError(f"passage too long to embed: {len(text)} chars")
            vectors.append((1.0, 0.0) if "alpha" in text else (0.0, 1.0))
        return vectors


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
        return httpx.Response(200, request=request, json={"embeddings": [[1, 2.5]]})
