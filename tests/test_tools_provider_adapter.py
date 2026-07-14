import pytest

from jarvis.core.config import McpServerSettings, McpToolAdapterSettings
from jarvis.tools.mcp_client import ToolDeclaration
from jarvis.tools.provider_adapter import adapt_provider_tools


def _server(adapter: McpToolAdapterSettings) -> McpServerSettings:
    return McpServerSettings(
        command="provider",
        tool_adapters={"upstream": adapter},
    )


def test_empty_adapter_table_preserves_provider_declarations():
    declaration = ToolDeclaration("lookup", "Lookup", {"type": "object"})

    adapted = adapt_provider_tools(
        "provider", McpServerSettings(command="provider"), [declaration]
    )

    assert [tool.name for tool in adapted.tools] == ["lookup"]
    assert adapted.issues == ()


def test_implicit_allowed_arguments_exclude_fixed_arguments():
    server = _server(
        McpToolAdapterSettings(
            public_name="lookup",
            fixed_arguments={"backend": "fixed"},
        )
    )
    declaration = ToolDeclaration(
        "upstream",
        "Lookup",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "backend": {"type": "string"},
            },
            "required": ["query", "backend"],
        },
    )

    adapted = adapt_provider_tools("provider", server, [declaration])

    assert adapted.issues == ()
    assert adapted.tools[0].allowed_arguments == ("query",)
    assert adapted.tools[0].schema["required"] == ["query"]


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"properties": []}, "properties must be an object"),
        (
            {"properties": {"query": {"type": "string"}}, "required": "query"},
            "required must be a list of strings",
        ),
    ],
)
def test_invalid_upstream_schema_is_reported_as_adapter_issue(schema, message):
    server = _server(McpToolAdapterSettings(public_name="lookup"))

    adapted = adapt_provider_tools(
        "provider", server, [ToolDeclaration("upstream", "", schema)]
    )

    assert adapted.tools == []
    assert message in adapted.issues[0]


def test_adapter_argument_missing_from_upstream_schema_is_an_issue():
    server = _server(
        McpToolAdapterSettings(
            public_name="lookup", allowed_arguments=("query", "limit")
        )
    )
    declaration = ToolDeclaration(
        "upstream",
        "",
        {"properties": {"query": {"type": "string"}}},
    )

    adapted = adapt_provider_tools("provider", server, [declaration])

    assert adapted.tools == []
    assert "undeclared argument(s): limit" in adapted.issues[0]
