import sys
import types
from dataclasses import replace

from _support_from_test_main import _fake_app

import jarvis.app as main_module
from jarvis.app import create_live_status_console
from jarvis.core.config import BrandSettings
from jarvis.ui.status_console import brand_payload

WORK = BrandSettings(name="Work", monogram="W", accent="#E0A03F")


def test_live_console_windows_are_titled_from_the_app_brand():
    app = _fake_app()
    app = replace(app, settings=replace(app.settings, brand=WORK))

    live_console = create_live_status_console(app)

    assert live_console.console.title == "Work - Status Console"
    assert live_console.touchstrip is not None
    assert live_console.touchstrip.title == "Work - Touchstrip"


def test_live_console_windows_of_an_unbranded_app_keep_the_current_titles():
    live_console = create_live_status_console(_fake_app())

    assert live_console.console.title == "Jarvis - Status Console"
    assert live_console.touchstrip is not None
    assert live_console.touchstrip.title == "Jarvis - Touchstrip"


def test_the_transport_state_is_built_with_the_settings_brand(monkeypatch):
    app = _fake_app()
    captured_kwargs = {}

    class _FakeUiTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args
            captured_kwargs.update(kwargs)

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings, run_mode: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeUiTransportServer)

    async def fake_run(
        settings=None, app=None, live_console=None, debug=False, run_mode=None
    ) -> None:
        del settings, app, live_console

    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        types.SimpleNamespace(start=lambda callback: callback()),
    )

    main_module.run_with_status_console(
        settings=replace(app.settings, brand=WORK), include_touchstrip=False
    )

    assert captured_kwargs["state"].snapshot()["brand"] == brand_payload(WORK)
