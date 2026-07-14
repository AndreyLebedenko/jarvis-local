"""Tool registry: aggregated declarations from connected MCP servers.

Pure data - the model presentation layer (story-v1.4.0 task 4) and the
Control Center's read-only tool list (task 5) are both views over this
registry. No network/subprocess code lives here; McpHost is the only
writer, populating it from connected McpClients.
"""

from dataclasses import dataclass, replace

from jarvis.core.config import DataBoundary
from jarvis.tools.json_types import JSONObject


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    schema: JSONObject
    provider: str
    enabled: bool = True
    data_boundary: DataBoundary = DataBoundary.UNKNOWN


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def set_provider_tools(
        self, provider: str, tools: list[RegisteredTool]
    ) -> tuple[str, ...]:
        """Replaces every tool previously registered by this provider with
        the given list - list_tools() returns a server's full current set,
        not a diff, so a whole-provider replace is the natural
        granularity for both first connect and reconnect.

        A tool whose name collides with an already-registered tool from a
        *different* provider is rejected outright - the earlier
        provider's registration is kept unchanged, and the colliding tool
        never enters the registry. This is deliberately not
        last-write-wins: tool names are the model-facing namespace (task
        4's flat presentation), so silently letting a later-connecting
        provider steal an established name would make tool identity
        depend on connection order, and that provider's later disconnect
        would then delete a tool a *different*, still-connected provider
        still owns. Returns the names of every rejected tool so the
        caller (McpHost) can surface a degraded-state event - this
        structure never hides the collision, only refuses to act on it.
        """
        self._tools = {
            name: tool
            for name, tool in self._tools.items()
            if tool.provider != provider
        }
        rejected: list[str] = []
        for tool in tools:
            existing = self._tools.get(tool.name)
            if existing is not None and existing.provider != provider:
                rejected.append(tool.name)
                continue
            self._tools[tool.name] = tool
        return tuple(rejected)

    def clear_provider(self, provider: str) -> None:
        self._tools = {
            name: tool
            for name, tool in self._tools.items()
            if tool.provider != provider
        }

    def clear(self) -> None:
        self._tools = {}

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def all(self) -> tuple[RegisteredTool, ...]:
        return tuple(self._tools.values())

    def set_tool_enabled(self, name: str, enabled: bool) -> bool:
        """The production path RegisteredTool.enabled actually changes
        through (task 5's future per-tool Control Center control calls
        this via McpHost.set_tool_enabled()). Returns False, and does
        nothing, when the tool does not currently exist - a stale UI
        reference to a tool that disconnected in the meantime must not
        resurrect it."""
        tool = self._tools.get(name)
        if tool is None:
            return False
        self._tools[name] = replace(tool, enabled=enabled)
        return True
