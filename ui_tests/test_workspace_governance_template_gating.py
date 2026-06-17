# test_workspace_governance_template_gating.py
"""
UI test for workspace governance template gating.

Version: 0.242.011
Implemented in: 0.242.011

This test ensures personal and group workspace templates keep the Jinja-level
governance gates that replace disabled modules with user-facing messages and
avoid loading matching JavaScript modules.
"""

from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


def _read_template(name):
    return (ROOT_DIR / "application" / "single_app" / "templates" / name).read_text(encoding="utf-8")


@pytest.mark.ui
def test_workspace_templates_gate_governed_modules():
    """Validate Jinja governance gates for personal and group workspace modules."""
    workspace_template = _read_template("workspace.html")
    group_template = _read_template("group_workspaces.html")

    personal_markers = [
        "workspace_governance.user_agents",
        "workspace_governance.user_actions",
        "workspace_governance.user_endpoints",
        "Personal agents are disabled by governance",
        "Personal actions are disabled by governance",
        "Personal endpoints are disabled by governance",
        "settings.allow_user_agents and workspace_governance.user_agents",
        "settings.allow_user_plugins and workspace_governance.user_actions",
        "settings.allow_user_custom_endpoints and settings.enable_multi_model_endpoints and workspace_governance.user_endpoints",
        "js/workspace/workspace_agents.js",
        "js/workspace/workspace_plugins.js",
        "js/workspace/workspace_model_endpoints.js",
    ]
    group_markers = [
        "workspace_governance.group_agents",
        "workspace_governance.group_actions",
        "workspace_governance.group_endpoints",
        "Group agents are disabled by governance",
        "Group actions are disabled by governance",
        "Group endpoints are disabled by governance",
        "settings.allow_group_agents and workspace_governance.group_agents",
        "settings.allow_group_plugins and workspace_governance.group_actions",
        "settings.allow_group_custom_endpoints and settings.enable_multi_model_endpoints and workspace_governance.group_endpoints",
        "js/workspace/group_agents.js",
        "js/workspace/group_plugins.js",
        "js/workspace/workspace_model_endpoints.js",
    ]

    for marker in personal_markers:
        assert marker in workspace_template, f"Missing personal workspace governance marker: {marker}"

    for marker in group_markers:
        assert marker in group_template, f"Missing group workspace governance marker: {marker}"