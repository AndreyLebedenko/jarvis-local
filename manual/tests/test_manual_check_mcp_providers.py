import pytest

from jarvis.core.config import load_settings
from manual.manual_check_mcp_providers import CHECKS, PROFILES, validate_profile


@pytest.mark.parametrize("profile_name", ["local", "lan"])
def test_checked_in_profile_matches_manual_check_contract(profile_name):
    profile = PROFILES[profile_name]
    settings = load_settings(profile.config_path).mcp

    validate_profile(settings, profile.knowledge_boundary)


def test_checklist_covers_every_required_runtime_scenario():
    assert {check.key for check in CHECKS} == {
        "mcp_off",
        "toggle_on",
        "web_search",
        "knowledge_search",
        "no_tool",
        "provider_failure",
        "toggle_off",
    }
