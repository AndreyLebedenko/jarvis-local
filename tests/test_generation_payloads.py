"""Payload pin per request kind for a config in the owner's shape.

The move to generation profiles (tasks/done/task-config-generation-profiles.md)
kept every request kind sending exactly what [backend] sent before; the
generation length cap (task-generation-num-predict-cap.md) then added the
default num_predict = 16384 to every request kind and nothing else."""

import pytest

from jarvis.app import _dialog_profile_name, _profile_reasoning
from jarvis.core.bus import EventBus
from jarvis.core.config import GENERATION_PROFILE_NAMES, load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel

OWNER_SHAPED_CONFIG = """
[backend]
model = "gemma4:12b-it-q8_0"
num_ctx = 65536
flash_attention = true
kv_cache_type = "q8_0"

[generation]
temperature = 0.618
top_p = 0.9
top_k = 50
min_p = 0.05
repeat_penalty = 1.025
"""

OWNER_SHAPED_OPTIONS = {
    "num_ctx": 65536,
    "flash_attention": True,
    "kv_cache_type": "q8_0",
    "temperature": 0.618,
    "top_p": 0.9,
    "top_k": 50,
    "min_p": 0.05,
    "repeat_penalty": 1.025,
    "num_predict": 16384,
}


@pytest.fixture
def settings(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(OWNER_SHAPED_CONFIG, encoding="utf-8")
    return load_settings(config_path, ui_path=tmp_path / "absent.ui.toml")


@pytest.mark.parametrize("profile_name", GENERATION_PROFILE_NAMES)
def test_every_request_kind_sends_the_owner_options_and_the_default_cap(
    settings, profile_name
):
    backend = OllamaBackend(EventBus(), settings.backend)
    profile = settings.generation.profile(profile_name)

    payload = backend.build_payload(
        [{"role": "user", "content": "q"}],
        reasoning_level=_profile_reasoning(profile),
        options=settings.generation.options_for(profile_name),
    )

    assert payload["options"] == OWNER_SHAPED_OPTIONS


@pytest.mark.parametrize(
    ("level", "think"),
    [
        (ReasoningLevel.OFF, False),
        (ReasoningLevel.LOW, "low"),
        (ReasoningLevel.MEDIUM, "medium"),
        (ReasoningLevel.HIGH, "high"),
    ],
)
def test_dialog_profiles_keep_their_levels_think_value(settings, level, think):
    profile = settings.generation.profile(_dialog_profile_name(level))

    assert _profile_reasoning(profile) is level
    payload = OllamaBackend(EventBus(), settings.backend).build_payload(
        [{"role": "user", "content": "q"}],
        reasoning_level=_profile_reasoning(profile),
        options=settings.generation.options_for(_dialog_profile_name(level)),
    )
    assert payload["think"] == think


@pytest.mark.parametrize(
    "profile_name",
    ["spoken_derivative", "voice_intent", "warmup", "annotation", "transcription"],
)
def test_non_dialog_requests_keep_reasoning_off_by_default(settings, profile_name):
    assert _profile_reasoning(settings.generation.profile(profile_name)) is (
        ReasoningLevel.OFF
    )
