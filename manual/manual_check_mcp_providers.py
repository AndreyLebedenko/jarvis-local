#!/usr/bin/env python3
"""Print and validate the human-run MCP provider checklist for task 6."""

import argparse
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.config import DataBoundary, McpSettings, load_settings


@dataclass(frozen=True)
class Profile:
    config_path: Path
    knowledge_boundary: DataBoundary


@dataclass(frozen=True)
class Check:
    key: str
    instruction: str


PROFILES = {
    "local": Profile(
        Path("examples/mcp/config.ddgs-qdrant-local.toml"), DataBoundary.LOCAL
    ),
    "lan": Profile(Path("examples/mcp/config.ddgs-qdrant-lan.toml"), DataBoundary.LAN),
}

CHECKS = (
    Check(
        "mcp_off",
        "Copy the profile to config.toml, set [mcp].enabled=false, and remove "
        "only the [mcp].enabled override from config.ui.toml if one exists. Start "
        "with 'python -m jarvis --status-console'. Confirm no MCP process, "
        "connection, tool, or data-source indicator exists. Process inspection: "
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
        "'ddgs|mcp-server-qdrant' }.",
    ),
    Check(
        "toggle_on",
        "Without restarting, toggle MCP on in Control Center. Confirm exactly "
        "web_search and search_local_knowledge appear and the two subprocesses "
        "are present in the process-inspection command.",
    ),
    Check(
        "web_search",
        "Ask: 'Find today's official Qdrant release news on the web.' Confirm "
        "an internet source label and correlated call/outcome events.",
    ),
    Check(
        "knowledge_search",
        "Ask: 'What is Project Aurora's production callsign?' Confirm the answer "
        "is Northstar and the source label matches the selected profile.",
    ),
    Check(
        "no_tool",
        "Ask: 'In one sentence, what is recursion?' Confirm that no tool call is made.",
    ),
    Check(
        "provider_failure",
        "Terminate Qdrant with: Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -match 'mcp-server-qdrant' } | ForEach-Object { "
        "Stop-Process -Id $_.ProcessId }. Run a knowledge query, then confirm "
        "honest degraded state and that the turn ends with a text answer.",
    ),
    Check(
        "toggle_off",
        "Toggle MCP off and confirm both subprocesses exit, tools disappear, and "
        "subsequent tool requests are not dispatched.",
    ),
)


def validate_profile(settings: McpSettings, expected_boundary: DataBoundary) -> None:
    if not settings.enabled:
        raise ValueError("example profile must explicitly enable MCP")
    if set(settings.servers) != {"web", "knowledge"}:
        raise ValueError("example profile must configure web and knowledge servers")
    web = settings.servers["web"]
    knowledge = settings.servers["knowledge"]
    if web.data_boundary is not DataBoundary.INTERNET:
        raise ValueError("web provider must declare the internet boundary")
    if knowledge.data_boundary is not expected_boundary:
        raise ValueError("knowledge provider boundary does not match the profile")
    if web.tool_adapters["search_text"].public_name != "web_search":
        raise ValueError("web profile does not expose canonical web_search")
    if web.tool_adapters["search_text"].fixed_arguments.get("backend") != "duckduckgo":
        raise ValueError("web profile must fix the DDGS backend to duckduckgo")
    if knowledge.tool_adapters["qdrant-find"].public_name != "search_local_knowledge":
        raise ValueError("knowledge profile does not expose the canonical tool")
    if knowledge.env.get("QDRANT_READ_ONLY") != "true":
        raise ValueError("Qdrant example must be read-only")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="local")
    return parser


def main() -> None:
    profile_name = _parser().parse_args().profile
    profile = PROFILES[profile_name]
    settings = load_settings(profile.config_path).mcp
    validate_profile(settings, profile.knowledge_boundary)
    print(f"Validated {profile_name} profile: {profile.config_path}")
    print("Copy that file to config.toml before running the checklist.\n")
    for number, check in enumerate(CHECKS, 1):
        print(f"{number}. [{check.key}] {check.instruction}")


if __name__ == "__main__":
    main()
