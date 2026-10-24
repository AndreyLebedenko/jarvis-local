import aiohttp

from jarvis.core.bus import EventBus
from jarvis.core.run_mode import RunMode, RunModePolicy
from jarvis.journal import JournalEvent, JournalStore
from jarvis.ui.contract import VisibilityMode
from jarvis.ui.transport import UiStateStore, UiTransportServer

TOKEN = "valid-token"
SESSION_ID = "20260724-100000-ab12"


class _NoControlApi:
    pass


def _store(tmp_path, source="user", role="user", text="first question"):
    store = JournalStore(tmp_path)
    store.append(
        JournalEvent(
            session_id=SESSION_ID,
            timestamp="2026-10-24T10:00:00+01:00",
            source=source,
            role=role,
            text=text,
            media=[],
            transcript=None,
        )
    )
    return store


def _server(store=None, *, run_mode=RunMode.NORMAL, hidden=False, active=None):
    return UiTransportServer(
        EventBus(),
        _NoControlApi(),
        state=UiStateStore(
            run_mode_policy=RunModePolicy(run_mode),
            visibility_mode=VisibilityMode.HIDDEN if hidden else VisibilityMode.OPEN,
        ),
        token_factory=lambda: TOKEN,
        journal_store=store,
        journal_active_session_id=lambda: active,
    )


def _title_url(info, session_id=SESSION_ID, token=TOKEN):
    return (
        f"http://127.0.0.1:{info.port}/api/journal/sessions/{session_id}/title"
        f"?token={token}"
    )


async def _listed_session(session, info):
    response = await session.get(
        f"http://127.0.0.1:{info.port}/api/journal/sessions?token={TOKEN}"
    )
    return (await response.json())["sessions"][0]


async def test_rename_sets_the_title_the_session_list_then_shows(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(
                _title_url(info), json={"title": "  Pump notes "}
            )

            assert response.status == 200
            assert await response.json() == {
                "status": "ok",
                "session_id": SESSION_ID,
                "title": "Pump notes",
            }
            listed = await _listed_session(session, info)
            assert listed["title"] == "Pump notes"
            assert listed["has_user_title"] is True
    finally:
        await server.stop()


async def test_rename_survives_a_restart_of_the_server_and_store(tmp_path):
    first = _server(_store(tmp_path))
    info = await first.start()
    try:
        async with aiohttp.ClientSession() as session:
            await session.put(_title_url(info), json={"title": "Pump notes"})
    finally:
        await first.stop()

    second = _server(JournalStore(tmp_path))
    info = await second.start()
    try:
        async with aiohttp.ClientSession() as session:
            assert (await _listed_session(session, info))["title"] == "Pump notes"
    finally:
        await second.stop()


async def test_empty_title_resets_to_the_automatic_one(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            await session.put(_title_url(info), json={"title": "Pump notes"})

            response = await session.put(_title_url(info), json={"title": ""})

            assert (await response.json())["title"] is None
            listed = await _listed_session(session, info)
            assert listed["title"] == "first question"
            assert listed["has_user_title"] is False
    finally:
        await server.stop()


async def test_the_live_session_can_be_renamed(tmp_path):
    server = _server(_store(tmp_path), active=SESSION_ID)
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "Live"})

            assert response.status == 200
            assert (await _listed_session(session, info))["title"] == "Live"
    finally:
        await server.stop()


async def test_a_title_over_the_limit_is_refused_by_the_server(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "a" * 81})

            assert response.status == 400
            assert await response.json() == {
                "status": "rejected",
                "reason": "title_too_long",
            }
            assert (await _listed_session(session, info))["has_user_title"] is False
    finally:
        await server.stop()


async def test_a_title_with_a_line_break_is_refused_by_the_server(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "a\nb"})

            assert response.status == 400
            assert await response.json() == {
                "status": "rejected",
                "reason": "title_invalid",
            }
    finally:
        await server.stop()


async def test_a_title_that_is_not_text_is_refused(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": 5})

            assert response.status == 400
            assert (await response.json())["reason"] == "title_invalid"
    finally:
        await server.stop()


async def test_a_body_without_a_title_or_not_json_is_a_bad_request(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            missing = await session.put(_title_url(info), json={"name": "x"})
            not_json = await session.put(_title_url(info), data="plain")

            assert missing.status == 400
            assert not_json.status == 400
    finally:
        await server.stop()


async def test_an_unknown_session_is_not_found_and_leaves_no_directory(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(
                _title_url(info, "20260101-000000-zzzz"), json={"title": "x"}
            )

            assert response.status == 404
            assert await response.json() == {
                "status": "rejected",
                "reason": "not_found",
            }
            assert sorted(path.name for path in tmp_path.iterdir()) == [SESSION_ID]
    finally:
        await server.stop()


async def test_a_missing_or_wrong_token_is_unauthorized(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            wrong = await session.put(
                _title_url(info, token="other"), json={"title": "x"}
            )
            missing = await session.put(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/{SESSION_ID}/title",
                json={"title": "x"},
            )

            assert wrong.status == 401
            assert missing.status == 401
    finally:
        await server.stop()


async def test_rename_is_refused_with_a_reason_when_the_journal_is_unavailable():
    server = _server(None)
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "x"})

            assert response.status == 503
            assert await response.json() == {
                "status": "rejected",
                "reason": "journal_unavailable",
            }
    finally:
        await server.stop()


async def test_rename_is_suppressed_while_hidden(tmp_path):
    server = _server(_store(tmp_path), hidden=True)
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "x"})

            assert await response.json() == {"status": "hidden"}
            assert not (tmp_path / SESSION_ID / "session.json").exists()
    finally:
        await server.stop()


async def test_rename_is_allowed_in_the_personal_proxy_mode(tmp_path):
    server = _server(
        _store(tmp_path, source="proxy_heard"), run_mode=RunMode.PERSONAL_PROXY
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "Trip"})

            assert response.status == 200
            listed = await _listed_session(session, info)
            assert listed["title"] == "Trip"
            assert listed["title_kind"] == "proxy_session"
    finally:
        await server.stop()


async def test_rename_is_allowed_in_the_mcp_mode(tmp_path):
    server = _server(_store(tmp_path), run_mode=RunMode.MCP)
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "Guide"})

            assert response.status == 200
    finally:
        await server.stop()


async def test_a_lone_surrogate_title_is_refused_as_invalid(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(
                _title_url(info),
                data=b'{"title": "a' + chr(92).encode() + b'ud800b"}',
                headers={"Content-Type": "application/json"},
            )

            assert response.status == 400
            assert (await response.json())["reason"] == "title_invalid"
    finally:
        await server.stop()


async def test_a_body_that_is_not_utf8_is_a_bad_request(tmp_path):
    server = _server(_store(tmp_path))
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(
                _title_url(info),
                data=b'{"title": "\xff\xfe"}',
                headers={"Content-Type": "application/json"},
            )

            assert response.status == 400
    finally:
        await server.stop()


async def test_a_write_blocked_by_the_system_is_a_clean_503(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def blocked(session_id, title):
        raise PermissionError("file in use")

    monkeypatch.setattr(store, "rename_session", blocked)
    server = _server(store)
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.put(_title_url(info), json={"title": "x"})

            assert response.status == 503
            assert await response.json() == {
                "status": "rejected",
                "reason": "rename_failed",
            }
    finally:
        await server.stop()
