import pytest

from jarvis.core.config import load_settings
from manual.manual_check_mcp_providers import (
    CHECKS,
    PROFILES,
    WEB_SEARCH_BACKENDS,
    validate_profile,
)


@pytest.mark.parametrize("profile_name", ["local", "lan"])
def test_checked_in_profile_matches_manual_check_contract(profile_name):
    profile = PROFILES[profile_name]
    settings = load_settings(profile.config_path).mcp

    validate_profile(settings, profile.knowledge_boundary)


@pytest.mark.parametrize("profile_name", ["local", "lan"])
def test_checked_in_profile_launches_ddgs_through_the_get_compatibility_script(
    profile_name,
):
    profile = PROFILES[profile_name]
    web = load_settings(profile.config_path).mcp.servers["web"]

    assert web.command == ".venv-mcp-ddgs/Scripts/python.exe"
    assert web.args == ("examples/mcp/ddgs_get_mcp.py",)


@pytest.mark.parametrize("profile_name", ["local", "lan"])
def test_checked_in_profile_fixes_the_issue_390_multi_backend_set(profile_name):
    profile = PROFILES[profile_name]
    web = load_settings(profile.config_path).mcp.servers["web"]

    assert (
        web.tool_adapters["search_text"].fixed_arguments["backend"]
        == WEB_SEARCH_BACKENDS
    )


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
