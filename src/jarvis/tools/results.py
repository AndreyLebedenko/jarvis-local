"""Neutral tool-call result types shared by MCP and builtin providers."""

from dataclasses import dataclass

from jarvis.core.config import DataBoundary
from jarvis.tools.json_types import JSONObject

ToolArguments = JSONObject


@dataclass(frozen=True)
class ToolCallResult:
    content: object
    is_error: bool = False
    structured_content: JSONObject | None = None
    images_b64: tuple[str, ...] = ()
    # A call whose reach is decided by its arguments rather than by the
    # tool it belongs to. The camera is the first: the same tool reads a
    # USB device or a LAN stream depending on the source asked for, so the
    # registered boundary would understate one of them. None means "the
    # registered boundary is the whole truth", which is the normal case.
    data_boundary: DataBoundary | None = None
