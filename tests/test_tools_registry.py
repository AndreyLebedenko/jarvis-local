from jarvis.tools.registry import RegisteredTool, ToolRegistry


def _tool(name: str, provider: str) -> RegisteredTool:
    return RegisteredTool(name=name, description="d", schema={}, provider=provider)


def test_empty_registry_has_no_tools():
    registry = ToolRegistry()

    assert registry.all() == ()
    assert registry.get("anything") is None


def test_set_provider_tools_registers_every_tool():
    registry = ToolRegistry()

    collisions = registry.set_provider_tools(
        "search", [_tool("web_search", "search"), _tool("news_search", "search")]
    )

    assert collisions == ()
    assert {t.name for t in registry.all()} == {"web_search", "news_search"}
    assert registry.get("web_search").provider == "search"


def test_set_provider_tools_replaces_the_providers_previous_set():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("a", "search"), _tool("b", "search")])

    registry.set_provider_tools("search", [_tool("c", "search")])

    assert {t.name for t in registry.all()} == {"c"}


def test_set_provider_tools_does_not_touch_other_providers():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("web_search", "search")])

    registry.set_provider_tools("db", [_tool("query", "db")])

    assert {t.name for t in registry.all()} == {"web_search", "query"}


def test_set_provider_tools_rejects_cross_provider_name_collision():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("lookup", "search")])

    rejected = registry.set_provider_tools("db", [_tool("lookup", "db")])

    assert rejected == ("lookup",)
    # Not last-write-wins: the earlier provider keeps the name.
    assert registry.get("lookup").provider == "search"


def test_set_provider_tools_collision_does_not_block_the_providers_other_tools():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("lookup", "search")])

    rejected = registry.set_provider_tools(
        "db", [_tool("lookup", "db"), _tool("query", "db")]
    )

    assert rejected == ("lookup",)
    assert registry.get("lookup").provider == "search"
    assert registry.get("query").provider == "db"


def test_disconnecting_the_rejected_providers_tool_does_not_delete_the_winner():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("lookup", "search")])
    registry.set_provider_tools("db", [_tool("lookup", "db")])

    registry.clear_provider("db")

    # "db" never actually owned "lookup" (its registration was rejected),
    # so "search" - still connected - must still offer it.
    assert registry.get("lookup").provider == "search"


def test_set_tool_enabled_flips_the_flag_on_an_existing_tool():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("web_search", "search")])

    changed = registry.set_tool_enabled("web_search", False)

    assert changed is True
    assert registry.get("web_search").enabled is False


def test_set_tool_enabled_on_a_missing_tool_is_a_no_op():
    registry = ToolRegistry()

    changed = registry.set_tool_enabled("does_not_exist", False)

    assert changed is False


def test_set_provider_tools_reregistering_the_same_provider_is_not_a_collision():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("lookup", "search")])

    collisions = registry.set_provider_tools("search", [_tool("lookup", "search")])

    assert collisions == ()


def test_clear_provider_removes_only_that_providers_tools():
    registry = ToolRegistry()
    registry.set_provider_tools("search", [_tool("web_search", "search")])
    registry.set_provider_tools("db", [_tool("query", "db")])

    registry.clear_provider("search")

    assert {t.name for t in registry.all()} == {"query"}
