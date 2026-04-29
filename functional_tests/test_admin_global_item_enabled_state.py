# test_admin_global_item_enabled_state.py
#!/usr/bin/env python3
"""
Functional test for admin-managed global enabled state controls.
Version: 0.241.076
Implemented in: 0.241.076

This test ensures global agents and actions can be disabled without deletion,
that runtime helper reads filter disabled items by default, and that the admin
settings page exposes enable/disable controls for both item types.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
GLOBAL_ACTIONS_FILE = REPO_ROOT / "application" / "single_app" / "functions_global_actions.py"
GLOBAL_AGENTS_FILE = REPO_ROOT / "application" / "single_app" / "functions_global_agents.py"
PLUGIN_ROUTES_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_plugins.py"
AGENT_ROUTES_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_agents.py"
ADMIN_PLUGINS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_plugins.js"
ADMIN_AGENTS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_agents.js"
PLUGIN_COMMON_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "plugin_common.js"
ADMIN_SETTINGS_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
AGENT_SCHEMA_FILE = REPO_ROOT / "application" / "single_app" / "static" / "json" / "schemas" / "agent.schema.json"
PLUGIN_SCHEMA_FILE = REPO_ROOT / "application" / "single_app" / "static" / "json" / "schemas" / "plugin.schema.json"


def test_admin_global_item_enabled_state():
    """Verify global enabled-state wiring across helpers, routes, and admin UI."""
    config_content = CONFIG_FILE.read_text(encoding="utf-8")
    global_actions_content = GLOBAL_ACTIONS_FILE.read_text(encoding="utf-8")
    global_agents_content = GLOBAL_AGENTS_FILE.read_text(encoding="utf-8")
    plugin_routes_content = PLUGIN_ROUTES_FILE.read_text(encoding="utf-8")
    agent_routes_content = AGENT_ROUTES_FILE.read_text(encoding="utf-8")
    admin_plugins_js = ADMIN_PLUGINS_JS.read_text(encoding="utf-8")
    admin_agents_js = ADMIN_AGENTS_JS.read_text(encoding="utf-8")
    plugin_common_js = PLUGIN_COMMON_JS.read_text(encoding="utf-8")
    admin_settings_template = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    agent_schema = AGENT_SCHEMA_FILE.read_text(encoding="utf-8")
    plugin_schema = PLUGIN_SCHEMA_FILE.read_text(encoding="utf-8")

    assert 'VERSION = "0.241.076"' in config_content, "Expected config.py version 0.241.076"

    assert "def get_global_actions(return_type=SecretReturnType.TRIGGER, include_disabled=False):" in global_actions_content, (
        "Expected global actions helper to support admin-only disabled-item reads."
    )
    assert 'NOT IS_DEFINED(c.is_enabled) OR c.is_enabled = true' in global_actions_content, (
        "Expected global actions helper to filter disabled items out of runtime reads by default."
    )
    assert "def update_global_action_enabled(action_id, is_enabled, user_id=None):" in global_actions_content, (
        "Expected a dedicated helper for toggling global action enabled state."
    )

    assert "def get_global_agents(include_disabled=False):" in global_agents_content, (
        "Expected global agents helper to support admin-only disabled-item reads."
    )
    assert 'NOT IS_DEFINED(c.is_enabled) OR c.is_enabled = true' in global_agents_content, (
        "Expected global agents helper to filter disabled items out of runtime reads by default."
    )
    assert "def update_global_agent_enabled(agent_id, is_enabled, user_id=None):" in global_agents_content, (
        "Expected a dedicated helper for toggling global agent enabled state."
    )
    assert "cleaned_agent['is_enabled'] = True" in global_agents_content, (
        "Expected new global agents to default to enabled."
    )

    assert "@bpap.route('/api/admin/plugins/<plugin_name>/enabled', methods=['PATCH'])" in plugin_routes_content, (
        "Expected an admin plugin enabled-state endpoint."
    )
    assert "plugins = get_global_actions(include_disabled=True)" in plugin_routes_content, (
        "Expected admin plugin routes to load disabled items for management."
    )

    assert "@bpa.route('/api/admin/agents/<agent_name>/enabled', methods=['PATCH'])" in agent_routes_content, (
        "Expected an admin agent enabled-state endpoint."
    )
    assert "agents = get_global_agents(include_disabled=True)" in agent_routes_content, (
        "Expected admin agent routes to load disabled items for management."
    )
    assert "fallback_agent_name" in agent_routes_content, (
        "Expected disabling a selected global agent to compute fallback selection metadata."
    )

    assert "onToggleEnabled: name => togglePluginEnabled(name)" in admin_plugins_js, (
        "Expected admin actions table wiring for enable/disable controls."
    )
    assert "async function togglePluginEnabled(name)" in admin_plugins_js, (
        "Expected admin plugins script to toggle global action enabled state."
    )
    assert "/api/admin/plugins/${encodeURIComponent(name)}/enabled" in admin_plugins_js, (
        "Expected admin plugins script to call the new enabled-state endpoint."
    )

    assert "const enabledAgents = agentsList.filter(agent => agent.is_enabled !== false);" in admin_agents_js, (
        "Expected selected-agent dropdowns to hide disabled global agents."
    )
    assert "async function toggleAgentEnabled(idx)" in admin_agents_js, (
        "Expected admin agents script to toggle global agent enabled state."
    )
    assert "/api/admin/agents/${encodeURIComponent(agent.name)}/enabled" in admin_agents_js, (
        "Expected admin agents script to call the new enabled-state endpoint."
    )

    assert "onToggleEnabled" in plugin_common_js, (
        "Expected shared plugin table rendering to support admin toggle controls."
    )
    assert "toggle-plugin-btn" in plugin_common_js, (
        "Expected shared plugin table rendering to create toggle buttons."
    )
    assert "Enabled" in plugin_common_js and "Disabled" in plugin_common_js, (
        "Expected shared plugin table rendering to expose enabled-state badges."
    )

    assert "Disable a global agent to keep it saved for admins while hiding it from runtime selection until it is re-enabled." in admin_settings_template, (
        "Expected admin settings copy to explain the new global agent disable behavior."
    )
    assert "Disable a global action to keep the configuration without exposing it to runtime action loading until it is re-enabled." in admin_settings_template, (
        "Expected admin settings copy to explain the new global action disable behavior."
    )

    assert '"is_enabled"' in agent_schema, "Expected agent schema to persist the enabled-state field."
    assert '"is_enabled"' in plugin_schema, "Expected plugin schema to persist the enabled-state field."


if __name__ == "__main__":
    test_admin_global_item_enabled_state()
    print("✅ Admin global item enabled-state controls verified.")