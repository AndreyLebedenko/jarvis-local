import aiohttp

from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import TextSubmissionReason, TextSubmissionResult
from jarvis.core.run_mode import RunMode, RunModePolicy
from jarvis.ui.contract import VisibilityMode
from jarvis.ui.transport import UiStateStore, UiTransportServer, hello_message

TOKEN = "valid-token"


class _NoControlApi:
    pass


def _server(run_mode=RunMode.PERSONAL_PROXY, language="en"):
    return UiTransportServer(
        EventBus(),
        _NoControlApi(),
        state=UiStateStore(run_mode_policy=RunModePolicy(run_mode), language=language),
        token_factory=lambda: TOKEN,
    )


async def _connected(server, info, session):
    websocket = await session.ws_connect(info.websocket_url)
    await websocket.send_json(hello_message("status-console", ["state"]))
    await websocket.receive_json()  # hello_ack
    await websocket.receive_json()  # snapshot
    return websocket


async def test_a_proxy_block_is_pushed_as_a_transient_delta():
    server = _server()
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            websocket = await _connected(server, info, session)

            server.publish_proxy_block({"type": "notice", "text": "x"})
            delta = await websocket.receive_json()

            assert delta["payload"] == {
                "key": "proxy_block",
                "value": {"type": "notice", "text": "x"},
            }
            assert "proxy_block" not in server._state.snapshot()
    finally:
        await server.stop()


async def test_a_proxy_block_is_dropped_while_hidden():
    server = _server()
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            websocket = await _connected(server, info, session)

            server.set_visibility_mode(VisibilityMode.HIDDEN)
            await websocket.receive_json()  # the visibility delta
            server.publish_proxy_block({"type": "answer", "text": "personal"})
            server.set_visibility_mode(VisibilityMode.OPEN)
            seen = [await websocket.receive_json() for _ in range(2)]

            keys = [message["payload"]["key"] for message in seen]
            assert "proxy_block" not in keys
    finally:
        await server.stop()


async def test_a_refused_http_route_shows_a_message_in_the_events_panel():
    server = _server()
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            websocket = await _connected(server, info, session)

            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/context/new?token={TOKEN}",
                json={},
            )
            delta = await websocket.receive_json()

            assert response.status == 403
            body = await response.json()
            assert body["reason"] == "personal_proxy"
            assert delta["payload"]["key"] == "system_event"
            event = delta["payload"]["value"]
            assert event["level"] == "warn"
            assert event["message"] == (
                "Personal proxy mode: this control is not available"
            )
    finally:
        await server.stop()


async def test_a_refused_control_command_shows_the_message_in_the_chosen_language():
    server = _server(language="ru")
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            websocket = await _connected(server, info, session)

            await websocket.send_json(
                {
                    "protocol": 1,
                    "channel": "control",
                    "type": "command",
                    "payload": {"command": "toggle_thinking", "arguments": {}},
                }
            )
            messages = [await websocket.receive_json() for _ in range(2)]

            kinds = {(m["channel"], m["type"]) for m in messages}
            assert ("control", "error") in kinds
            event = next(
                m["payload"]["value"]
                for m in messages
                if m["payload"].get("key") == "system_event"
            )
            assert event["message"] == (
                "Режим личного прокси: этот элемент управления недоступен"
            )
    finally:
        await server.stop()


async def test_the_mcp_mode_refusal_adds_no_message():
    server = _server(run_mode=RunMode.MCP)
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/context/new?token={TOKEN}",
                json={},
            )

            assert response.status == 403
            assert server._state.snapshot()["system_events"] == []
    finally:
        await server.stop()


def test_an_unavailable_text_submission_carries_its_reason_text():
    result = TextSubmissionResult(
        TextSubmissionReason.UNAVAILABLE, 100, "The proxy did not start."
    )

    payload = UiTransportServer._text_submission_payload(result)

    assert payload == {
        "status": "rejected",
        "reason": "unavailable",
        "max_chars": 100,
        "detail": "The proxy did not start.",
    }


def test_a_busy_text_submission_has_no_detail_field():
    result = TextSubmissionResult(TextSubmissionReason.BUSY, 100)

    payload = UiTransportServer._text_submission_payload(result)

    assert "detail" not in payload


def test_the_snapshot_reports_the_dry_run_indicator_and_no_block_reason_at_first():
    assert UiStateStore(proxy_dry_run=True).snapshot()["proxy_status"] == {
        "dry_run": True,
        "last_block": None,
    }
    assert UiStateStore().snapshot()["proxy_status"]["dry_run"] is False


async def test_the_last_block_reason_is_a_delta_and_part_of_the_snapshot():
    server = _server()
    info = await server.start()
    reason = {"kind": "gate_blocked", "detail": [{"category": "phone"}]}
    try:
        async with aiohttp.ClientSession() as session:
            websocket = await _connected(server, info, session)

            server.set_proxy_last_block(reason)
            delta = await websocket.receive_json()

            assert delta["payload"] == {
                "key": "proxy_status",
                "value": {"dry_run": False, "last_block": reason},
            }
            assert server._state.snapshot()["proxy_status"]["last_block"] == reason
    finally:
        await server.stop()


async def test_clearing_the_last_block_reason_is_a_delta_and_repeating_it_is_not():
    server = _server()
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            websocket = await _connected(server, info, session)

            server.set_proxy_last_block({"kind": "refused", "detail": None})
            await websocket.receive_json()
            server.set_proxy_last_block(None)
            cleared = await websocket.receive_json()
            server.set_proxy_last_block(None)

            assert cleared["payload"]["value"]["last_block"] is None
            assert server._state.snapshot()["proxy_status"]["last_block"] is None
    finally:
        await server.stop()
