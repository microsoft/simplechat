# test_mcp_tool_fingerprint_pinning.py
#!/usr/bin/env python3
"""
Functional test for MCP tool fingerprint pinning.
Version: 0.261.459
Implemented in: 0.261.276
Numeric canonicalization fixed in: 0.261.459

This test ensures MCP tool and prompt fingerprints are stable, drift is detected,
and pinned runtime filtering only exposes approved unchanged tools.
"""

from copy import deepcopy
import hashlib
import json
import os
import sys

import pytest

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


def _legacy_tool_hash(tool):
    encoded = json.dumps(
        pinning._tool_payload(tool), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("number", [90.0, -90.0, 0.0, -0.0, 1e20])
def test_whole_number_representation_is_stable_through_save_and_runtime(number):
    tool = _tool()
    tool["input_schema"]["properties"]["timeout"] = {
        "type": "number", "default": number, "examples": [{"values": [number, 0.25]}],
    }
    tool["output_schema"]["properties"]["count"] = {"type": "number", "minimum": number}
    tool["annotations"]["extension"] = {"values": [number]}
    prompt = {"name": "wait", "arguments": [{"name": "timeout", "default": number}]}
    original = deepcopy({"tools": [tool], "prompts": [prompt]})
    approved = pinning.build_mcp_tool_fingerprints([tool], [prompt])
    saved_tool = deepcopy(tool)
    saved_tool["input_schema"]["properties"]["timeout"]["default"] = int(number)
    saved_tool["input_schema"]["properties"]["timeout"]["examples"][0]["values"][0] = int(number)
    saved_tool["output_schema"]["properties"]["count"]["minimum"] = int(number)
    saved_tool["annotations"]["extension"]["values"][0] = int(number)
    saved_prompt = {"name": "wait", "arguments": [{"name": "timeout", "default": int(number)}]}
    action = {
        "type": "mcp",
        "additionalFields": {
            "mcp_tools": [saved_tool], "mcp_prompts": [saved_prompt],
            "mcp_tool_fingerprints": approved,
        },
    }

    pinning.validate_mcp_tool_pinning_for_save(action)
    current = pinning.build_mcp_tool_fingerprints([saved_tool], [saved_prompt])
    filtered, drift = pinning.filter_pinned_mcp_tools([saved_tool], approved)
    manifest_drift = pinning.compare_mcp_fingerprints(approved, current)
    reverse_approved = pinning.build_mcp_tool_fingerprints([saved_tool], [saved_prompt])
    reverse_filtered, reverse_drift = pinning.filter_pinned_mcp_tools([tool], reverse_approved)

    assert [entry["original_name"] for entry in filtered] == ["search"]
    assert [entry["original_name"] for entry in reverse_filtered] == ["search"]
    assert filtered[0]["input_schema"] == saved_tool["input_schema"]
    assert reverse_filtered[0]["input_schema"] == tool["input_schema"]
    assert drift["has_drift"] is False
    assert reverse_drift["has_drift"] is False
    assert manifest_drift["has_drift"] is False
    assert {"tools": [tool], "prompts": [prompt]} == original
    assert type(tool["input_schema"]["properties"]["timeout"]["default"]) is float
    assert type(tool["annotations"]["extension"]["values"][0]) is float
    assert type(prompt["arguments"][0]["default"]) is float


@pytest.mark.parametrize("before,after", [
    (90.0, 91),
    (90.25, 90),
    (90.25, 90.5),
    (True, 1),
    (False, 0),
    ("90", 90),
    ([90, 91], [91, 90]),
])
def test_numeric_normalization_does_not_hide_real_metadata_changes(before, after):
    tool = _tool()
    tool["input_schema"]["properties"]["limit"]["default"] = before
    changed = deepcopy(tool)
    changed["input_schema"]["properties"]["limit"]["default"] = after
    approved = pinning.build_mcp_tool_fingerprints([tool])
    action = {
        "type": "mcp",
        "additionalFields": {"mcp_tools": [changed], "mcp_tool_fingerprints": approved},
    }

    with pytest.raises(ValueError, match="do not match"):
        pinning.validate_mcp_tool_pinning_for_save(action)
    filtered, drift = pinning.filter_pinned_mcp_tools([changed], approved)

    assert filtered == []
    assert drift["changed"] == ["search"]
    assert drift["has_drift"] is True


def test_numeric_schema_type_and_prompt_default_changes_still_require_approval():
    tool = _tool()
    changed = deepcopy(tool)
    changed["input_schema"]["properties"]["limit"]["type"] = "number"
    prompt = {"name": "wait", "arguments": [{"name": "timeout", "default": 90.0}]}
    approved = pinning.build_mcp_tool_fingerprints([tool], [prompt])
    changed_prompt = {"name": "wait", "arguments": [{"name": "timeout", "default": 91}]}
    current = pinning.build_mcp_tool_fingerprints([changed], [changed_prompt])
    drift = pinning.compare_mcp_fingerprints(approved, current)
    action = {
        "type": "mcp",
        "additionalFields": {
            "mcp_tools": [tool], "mcp_prompts": [changed_prompt],
            "mcp_tool_fingerprints": approved,
        },
    }

    with pytest.raises(ValueError, match="do not match"):
        pinning.validate_mcp_tool_pinning_for_save(action)

    assert drift["changed"] == ["search"]
    assert drift["prompts_changed"] == ["wait"]
    assert drift["has_drift"] is True


def test_unaffected_hashes_remain_compatible_and_float_legacy_hash_requires_reapproval():
    tool = _tool()
    tool["input_schema"]["properties"]["fraction"] = {"type": "number", "default": 0.25}
    legacy_hash = _legacy_tool_hash(tool)
    current_hash = pinning.compute_mcp_tool_hash(tool)
    assert current_hash == legacy_hash

    tool["input_schema"]["properties"]["timeout"] = {"type": "number", "default": 90.0}
    legacy_hash = _legacy_tool_hash(tool)
    approved = pinning.build_mcp_tool_fingerprints([tool])
    approved["tools"]["search"] = legacy_hash
    approved["manifest_hash"] = hashlib.sha256(json.dumps(
        {"tools": approved["tools"], "prompts": {}},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    action = {
        "type": "mcp",
        "additionalFields": {"mcp_tools": [tool], "mcp_tool_fingerprints": approved},
    }

    with pytest.raises(ValueError, match="do not match"):
        pinning.validate_mcp_tool_pinning_for_save(action)
    filtered, drift = pinning.filter_pinned_mcp_tools([tool], approved)

    assert filtered == []
    assert drift["changed"] == ["search"]
    assert drift["has_drift"] is True


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
    sys.exit(pytest.main([__file__]))
