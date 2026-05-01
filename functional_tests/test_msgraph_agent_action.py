# test_msgraph_agent_action.py
#!/usr/bin/env python3
"""
Functional test for the Microsoft Graph agent action.
Version: 0.241.037
Implemented in: 0.241.037

This test ensures the Microsoft Graph action is discoverable, supports
per-action capability filtering, and applies both action-level and per-agent
runtime capability overlays from other_settings.action_capabilities.
"""

import importlib
import os
import sys
import traceback


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def build_manifest(enabled_functions=None):
    return {
        "id": "msgraph-action-id",
        "name": "msgraph_tools",
        "displayName": "Microsoft Graph Tools",
        "type": "msgraph",
        "description": "Microsoft Graph tools",
        "endpoint": "https://graph.microsoft.com",
        "auth": {
            "type": "user"
        },
        "metadata": {
            "description": "Microsoft Graph action for tests"
        },
        "enabled_functions": enabled_functions or [
            "get_my_profile",
            "create_calendar_invite"
        ]
    }


def get_msgraph_plugin_class():
    module = importlib.import_module("semantic_kernel_plugins.msgraph_plugin")
    return module.MSGraphPlugin


def get_discover_plugins_function():
    module = importlib.import_module("semantic_kernel_plugins.plugin_loader")
    return module.discover_plugins


def get_overlay_function():
    module = importlib.import_module("semantic_kernel_loader")
    return module._apply_agent_plugin_runtime_overlays


def test_msgraph_plugin_discovery_and_kernel_filtering():
    """Test that the Microsoft Graph plugin is discoverable and filters kernel functions."""
    print("🔍 Testing Microsoft Graph plugin discovery and kernel filtering...")

    MSGraphPlugin = get_msgraph_plugin_class()
    discover_plugins = get_discover_plugins_function()

    plugin = MSGraphPlugin(build_manifest(enabled_functions=[
        "get_my_profile",
        "create_calendar_invite"
    ]))
    kernel_plugin = plugin.get_kernel_plugin("msgraph_tools")

    assert set(kernel_plugin.functions.keys()) == {
        "get_my_profile",
        "create_calendar_invite"
    }, "Kernel plugin should expose only the enabled Microsoft Graph functions"

    discovered_plugins = discover_plugins()
    assert "MSGraphPlugin" in discovered_plugins, "Dynamic plugin discovery should include MSGraphPlugin"

    print("✅ Microsoft Graph plugin discovery and capability filtering verified.")


def test_msgraph_runtime_capability_overlay():
    """Test that agent runtime overlays translate Graph capability config into enabled functions."""
    print("🔍 Testing Microsoft Graph runtime capability overlay...")

    apply_runtime_overlays = get_overlay_function()
    overlaid_manifest = apply_runtime_overlays(
        [
            {
                "id": "msgraph-action-id",
                "name": "msgraph_tools",
                "type": "msgraph"
            }
        ],
        agent_other_settings={
            "action_capabilities": {
                "msgraph-action-id": {
                    "get_my_profile": True,
                    "get_my_timezone": False,
                    "get_my_events": False,
                    "create_calendar_invite": True,
                    "get_my_messages": False,
                    "mark_message_as_read": False,
                    "search_users": True,
                    "get_user_by_email": False,
                    "list_drive_items": False,
                    "get_my_security_alerts": False
                }
            }
        },
        group_id="group-123"
    )[0]

    assert overlaid_manifest["default_group_id"] == "group-123", "Runtime overlay should inject the group context for group agents"
    assert overlaid_manifest["enabled_functions"] == [
        "get_my_profile",
        "create_calendar_invite",
        "search_users",
    ], "Runtime overlay should translate Microsoft Graph capability toggles into the exact enabled function list"

    print("✅ Microsoft Graph runtime capability overlay verified.")


def test_msgraph_action_defaults_feed_runtime_overlay():
    """Test that action-level Graph defaults are used when agent overrides are absent."""
    print("🔍 Testing Microsoft Graph action defaults in runtime overlay...")

    apply_runtime_overlays = get_overlay_function()
    overlaid_manifest = apply_runtime_overlays(
        [
            {
                "id": "msgraph-action-id",
                "name": "msgraph_tools",
                "type": "msgraph",
                "additionalFields": {
                    "msgraph_capabilities": {
                        "get_my_profile": True,
                        "get_my_timezone": True,
                        "get_my_events": False,
                        "create_calendar_invite": True,
                        "get_my_messages": False,
                        "mark_message_as_read": False,
                        "search_users": True,
                        "get_user_by_email": True,
                        "list_drive_items": False,
                        "get_my_security_alerts": False
                    }
                }
            }
        ],
        agent_other_settings={},
        group_id=None
    )[0]

    assert overlaid_manifest["enabled_functions"] == [
        "get_my_profile",
        "get_my_timezone",
        "create_calendar_invite",
        "search_users",
        "get_user_by_email",
    ], "Runtime overlay should honor action-level Microsoft Graph capability defaults when no agent override exists"

    print("✅ Microsoft Graph action-level defaults verified.")


if __name__ == "__main__":
    tests = [
        test_msgraph_plugin_discovery_and_kernel_filtering,
        test_msgraph_runtime_capability_overlay,
        test_msgraph_action_defaults_feed_runtime_overlay,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)