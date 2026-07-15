"""Projects provider-specific MCP tools onto Jarvis's stable public surface."""

from copy import deepcopy
from dataclasses import dataclass

from jarvis.core.config import McpServerSettings, McpToolAdapterSettings
from jarvis.tools.json_types import JSONObject, JSONValue
from jarvis.tools.mcp_client import ToolDeclaration
from jarvis.tools.registry import RegisteredTool


@dataclass(frozen=True)
class AdaptedTools:
    tools: list[RegisteredTool]
    issues: tuple[str, ...] = ()


def adapt_provider_tools(
    provider: str,
    server: McpServerSettings,
    declarations: list[ToolDeclaration],
) -> AdaptedTools:
    """Apply an optional allowlist/rename contract to discovered tools.

    An empty adapter table preserves the original pass-through behavior.
    A non-empty table is an allowlist: unmentioned upstream tools never
    enter the registry, and every configured upstream tool must exist and
    have the arguments named by its adapter.
    """
    if not server.tool_adapters:
        return AdaptedTools(
            tools=[
                RegisteredTool(
                    name=declaration.name,
                    description=declaration.description,
                    schema=declaration.schema,
                    provider=provider,
                    data_boundary=server.boundary_for(declaration.name),
                )
                for declaration in declarations
            ]
        )

    by_name = {declaration.name: declaration for declaration in declarations}
    tools: list[RegisteredTool] = []
    issues: list[str] = []
    for upstream_name, adapter in server.tool_adapters.items():
        declaration = by_name.get(upstream_name)
        if declaration is None:
            issues.append(f"configured upstream tool {upstream_name!r} is missing")
            continue
        try:
            schema, allowed_arguments = _project_schema(declaration.schema, adapter)
        except ValueError as exc:
            issues.append(f"upstream tool {upstream_name!r}: {exc}")
            continue
        tools.append(
            RegisteredTool(
                name=adapter.public_name,
                description=adapter.description or declaration.description,
                schema=schema,
                provider=provider,
                data_boundary=server.boundary_for(adapter.public_name),
                upstream_name=upstream_name,
                allowed_arguments=allowed_arguments,
                fixed_arguments=dict(adapter.fixed_arguments),
            )
        )
    return AdaptedTools(tools=tools, issues=tuple(issues))


def _project_schema(
    schema: JSONObject, adapter: McpToolAdapterSettings
) -> tuple[JSONObject, tuple[str, ...]]:
    properties_value = schema.get("properties", {})
    if not isinstance(properties_value, dict):
        raise ValueError("input schema properties must be an object")
    properties: dict[str, JSONValue] = properties_value

    allowed = (
        adapter.allowed_arguments
        if adapter.allowed_arguments is not None
        else tuple(name for name in properties if name not in adapter.fixed_arguments)
    )
    referenced = set(allowed) | set(adapter.fixed_arguments)
    missing = referenced - set(properties)
    if missing:
        raise ValueError(
            "adapter references undeclared argument(s): " + ", ".join(sorted(missing))
        )

    projected = deepcopy(schema)
    projected["properties"] = {name: deepcopy(properties[name]) for name in allowed}
    required_value = schema.get("required", [])
    if not isinstance(required_value, list) or not all(
        isinstance(name, str) for name in required_value
    ):
        raise ValueError("input schema required must be a list of strings")
    projected["required"] = [name for name in required_value if name in allowed]
    projected["additionalProperties"] = False
    return projected, allowed
