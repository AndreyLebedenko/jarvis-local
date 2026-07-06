import pytest

from ui_contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)


def test_runtime_state_has_exactly_the_states_from_the_story_card():
    assert {state.value for state in RuntimeState} == {
        "idle",
        "warming",
        "listening",
        "thinking",
        "speaking",
        "error",
    }


def test_module_id_has_exactly_the_chips_from_the_story_card():
    assert {module.value for module in ModuleId} == {
        "backend",
        "microphone",
        "tts",
        "memory",
        "vision",
    }


def test_module_health_defaults_to_empty_detail():
    health = ModuleHealth(module=ModuleId.TTS, status=HealthStatus.OK)

    assert health.detail == ""


def test_health_status_has_exactly_the_contract_statuses():
    assert {status.value for status in HealthStatus} == {
        "ok",
        "degraded",
        "error",
        "unavailable",
    }


def test_module_health_is_immutable():
    health = ModuleHealth(module=ModuleId.TTS, status=HealthStatus.OK)

    with pytest.raises(AttributeError):
        health.status = HealthStatus.ERROR


def test_event_level_has_exactly_the_system_event_levels():
    assert {level.value for level in EventLevel} == {
        "info",
        "active",
        "warn",
        "error",
    }


def test_system_event_correlation_id_defaults_to_none():
    event = SystemEvent(
        timestamp=0.0, source="ENGINE", level=EventLevel.INFO, message="ready"
    )

    assert event.correlation_id is None


def test_system_event_is_immutable():
    event = SystemEvent(
        timestamp=0.0, source="ENGINE", level=EventLevel.INFO, message="ready"
    )

    with pytest.raises(AttributeError):
        event.message = "tampered"


def test_visibility_mode_has_open_and_hidden_only():
    assert {mode.value for mode in VisibilityMode} == {"open", "hidden"}


def test_data_locality_has_local_and_external_only():
    assert {locality.value for locality in DataLocality} == {"local", "external"}
