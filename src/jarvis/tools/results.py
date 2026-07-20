"""Neutral tool-call result types shared by MCP and builtin providers."""

from dataclasses import dataclass

from jarvis.tools.json_types import JSONObject

ToolArguments = JSONObject


@dataclass(frozen=True)
class ToolCallResult:
    content: object
    is_error: bool = False
    structured_content: JSONObject | None = None
