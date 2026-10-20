import pytest

from setup_stt_model import build_arg_parser, cache_model


def test_the_default_model_is_the_one_in_the_settings_default():
    from jarvis.core.config import PersonalProxySettings

    assert build_arg_parser().parse_args([]).model == PersonalProxySettings().stt_model


def test_an_explicit_model_is_accepted():
    assert build_arg_parser().parse_args(["--model", "small"]).model == "small"


def test_the_model_is_downloaded_first_and_then_loaded_offline():
    calls = []

    cache_model(
        "small",
        downloader=lambda name: calls.append(("download", name)) or "cache-dir",
        offline_loader=lambda name: calls.append(("offline", name)),
    )

    assert calls == [("download", "small"), ("offline", "small")]


def test_a_failed_offline_check_is_not_reported_as_done(capsys):
    def failing_loader(name):
        raise RuntimeError("not loadable")

    with pytest.raises(RuntimeError):
        cache_model(
            "small", downloader=lambda name: "cache-dir", offline_loader=failing_loader
        )

    assert "Done" not in capsys.readouterr().out
