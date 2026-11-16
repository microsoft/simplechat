#!/usr/bin/env python3
"""
Functional test for MCP tool fingerprint pinning.
Version: 0.261.276
Implemented in: 0.261.276

This test ensures MCP tool and prompt fingerprints are stable, drift is detected,
and pinned runtime filtering only exposes approved unchanged tools.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app"))

import functions_mcp_tool_pinning as pinning


def _tool(name="search", description="Search docs", extra_schema_order=False):
    properties = {
        "query": {"type": "string", "description": "Query"},
        "limit": {"type": "integer", "default": 5},
    }
    if extra_schema_order:
        properties = {
            "limit": {"default": 5, "type": "integer"},
            "query": {"description": "Query", "type": "string"},
        }
    return {
        "original_name": name,
        "function_name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties},
        "output_schema": {"type": "object", "properties": {"items": {"type": "array"}}},
        "annotations": {"readOnlyHint": True},
    }


def test_tool_hash_is_canonical_and_stable():
    first = _tool()
    second = _tool(extra_schema_order=True)
    assert pinning.compute_mcp_tool_hash(first) == pinning.compute_mcp_tool_hash(second)


def test_manifest_drift_detects_new_changed_and_removed_tools():
    approved = pinning.build_mcp_tool_fingerprints([
        _tool("search"),
        _tool("fetch", "Fetch document"),
    ], [{"name": "summarize", "description": "Summarize", "arguments": [{"name": "topic"}]}])
    current = pinning.build_mcp_tool_fingerprints([
        _tool("search", "Changed description"),
        _tool("new_tool", "New tool"),
    ], [{"name": "summarize", "description": "Changed", "arguments": [{"name": "topic"}]}])

    drift = pinning.compare_mcp_fingerprints(approved, current)

    assert drift["has_drift"] is True
    assert drift["new"] == ["new_tool"]
    assert drift["changed"] == ["search"]
    assert drift["removed"] == ["fetch"]
    assert drift["prompts_changed"] == ["summarize"]


def test_runtime_filtering_keeps_only_approved_unchanged_tools():
    approved_tools = [_tool("search"), _tool("fetch")]
    approved = pinning.build_mcp_tool_fingerprints(approved_tools, [])
    current_tools = [_tool("search"), _tool("fetch", "Changed"), _tool("extra")]

    filtered, drift = pinning.filter_pinned_mcp_tools(current_tools, approved)

    assert [tool["original_name"] for tool in filtered] == ["search"]
    assert drift["has_drift"] is True
    assert drift["new"] == ["extra"]
    assert drift["changed"] == ["fetch"]
    assert drift["removed"] == []


def test_legacy_unpinned_action_is_not_blocked_by_normalized_defaults():
    from functions_mcp_operations import normalize_mcp_additional_fields

    existing = {
        "id": "legacy-mcp",
        "type": "mcp",
        "endpoint": "https://mcp.example.test/mcp",
        "auth": {"type": "key"},
        "additionalFields": {"transport": "streamable_http", "allowed_tool_names": []},
    }
    edited = dict(existing)
    edited["additionalFields"] = normalize_mcp_additional_fields(existing["additionalFields"])
    pinning.validate_mcp_tool_pinning_for_save(edited, existing)

    changed = dict(edited)
    changed["endpoint"] = "https://other.example.test/mcp"
    try:
        pinning.validate_mcp_tool_pinning_for_save(changed, existing)
    except ValueError:
        pass
    else:
        raise AssertionError("Changed legacy MCP endpoint saved without discovery.")


def test_drift_persistence_and_notification_failures_are_logged_not_raised():
    import types

    origin = types.SimpleNamespace(scope_type="personal", scope_id="user-1", action_id="action-1")
    failing_config = types.ModuleType("config")
    failing_notifications = types.ModuleType("functions_notifications")

    def fail_notification(**_kwargs):
        raise RuntimeError("notification failure")

    failing_notifications.create_notification = fail_notification
    saved_modules = {name: sys.modules.get(name) for name in ("config", "functions_notifications")}
    saved_origin = pinning.get_action_origin
    logged = []
    saved_log = pinning.log_event
    try:
        sys.modules["config"] = failing_config
        sys.modules["functions_notifications"] = failing_notifications
        pinning.get_action_origin = lambda _action: origin
        pinning.log_event = lambda message, **kwargs: logged.append(message)
        pinning.persist_mcp_tool_drift({"type": "mcp"}, {"has_drift": True, "manifest_hash": "abc"})
    finally:
        pinning.get_action_origin = saved_origin
        pinning.log_event = saved_log
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    assert len(logged) == 2


if __name__ == "__main__":
    test_tool_hash_is_canonical_and_stable()
    test_manifest_drift_detects_new_changed_and_removed_tools()
    test_runtime_filtering_keeps_only_approved_unchanged_tools()
    test_legacy_unpinned_action_is_not_blocked_by_normalized_defaults()
    test_drift_persistence_and_notification_failures_are_logged_not_raised()
    print("MCP tool fingerprint pinning tests passed.")
