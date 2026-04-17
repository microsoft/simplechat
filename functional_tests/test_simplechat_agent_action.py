# test_simplechat_agent_action.py
#!/usr/bin/env python3
"""
Functional test for the SimpleChat agent action.
Version: 0.241.023
Implemented in: 0.241.023

This test ensures the SimpleChat action is discoverable, supports per-agent
capability filtering, and applies runtime capability overlays from
other_settings.action_capabilities.
"""

import os
import sys
import importlib


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def build_manifest(enabled_functions=None):
    return {
        "id": "simplechat-action-id",
        "name": "simplechat_tools",
        "displayName": "Simple Chat Tools",
        "type": "simplechat",
        "description": "SimpleChat native workspace tools",
        "endpoint": "simplechat://internal",
        "auth": {
            "type": "user"
        },
        "metadata": {
            "description": "SimpleChat action for tests"
        },
        "enabled_functions": enabled_functions or [
            "create_group",
            "create_personal_conversation"
        ]
    }


def get_simplechat_plugin_class():
    module = importlib.import_module("semantic_kernel_plugins.simplechat_plugin")
    return module.SimpleChatPlugin


def get_discover_plugins_function():
    module = importlib.import_module("semantic_kernel_plugins.plugin_loader")
    return module.discover_plugins


def get_overlay_function():
    module = importlib.import_module("semantic_kernel_loader")
    return module._apply_agent_plugin_runtime_overlays


def test_simplechat_plugin_discovery_and_kernel_filtering():
    """Test that the SimpleChat plugin is discoverable and filters kernel functions."""
    print("🔍 Testing SimpleChat plugin discovery and kernel filtering...")

    try:
        SimpleChatPlugin = get_simplechat_plugin_class()
        discover_plugins = get_discover_plugins_function()

        plugin = SimpleChatPlugin(build_manifest(enabled_functions=[
            "create_group",
            "create_personal_conversation"
        ]))
        kernel_plugin = plugin.get_kernel_plugin("simplechat_tools")

        assert set(kernel_plugin.functions.keys()) == {
            "create_group",
            "create_personal_conversation"
        }, "Kernel plugin should expose only the enabled SimpleChat functions"

        discovered_plugins = discover_plugins()
        assert "SimpleChatPlugin" in discovered_plugins, "Dynamic plugin discovery should include SimpleChatPlugin"

        print("✅ SimpleChat plugin discovery and capability filtering verified.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_simplechat_runtime_capability_overlay():
    """Test that agent runtime overlays translate per-action capability config into enabled functions."""
    print("🔍 Testing SimpleChat runtime capability overlay...")

    try:
        apply_runtime_overlays = get_overlay_function()
        overlaid_manifest = apply_runtime_overlays(
            [
                {
                    "id": "simplechat-action-id",
                    "name": "simplechat_tools",
                    "type": "simplechat"
                }
            ],
            agent_other_settings={
                "action_capabilities": {
                    "simplechat-action-id": {
                        "create_group": False,
                        "add_group_member": False,
                        "create_group_conversation": True,
                        "create_personal_conversation": True,
                        "create_personal_collaboration_conversation": False
                    }
                }
            },
            group_id="group-123"
        )[0]

        assert overlaid_manifest["default_group_id"] == "group-123", "Runtime overlay should inject the group context for group agents"
        assert overlaid_manifest["enabled_functions"] == [
            "create_group_conversation",
            "create_personal_conversation"
        ], "Runtime overlay should translate disabled capabilities into the exact enabled function list"

        print("✅ SimpleChat runtime capability overlay verified.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_simplechat_plugin_discovery_and_kernel_filtering,
        test_simplechat_runtime_capability_overlay,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)