#!/usr/bin/env python3
"""
Functional test for personal workspace plugin stepper script gating.
Version: 0.250.032
Implemented in: 0.250.032

This test ensures the personal workspace only loads the plugin modal stepper
when the plugin modal is rendered, and that the stepper module also guards
against missing modal markup before binding event handlers.
"""

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"
PLUGIN_STEPPER_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "plugin_modal_stepper.js"


def test_workspace_plugin_stepper_script_gating() -> bool:
    """Verify the workspace plugin stepper cannot bind against missing modal controls."""
    print("Testing personal workspace plugin stepper script gating...")

    workspace_template = WORKSPACE_TEMPLATE.read_text(encoding="utf-8")
    stepper_js = PLUGIN_STEPPER_JS.read_text(encoding="utf-8")

    gated_script_pattern = re.compile(
        r"\{% if settings\.per_user_semantic_kernel and settings\.enable_semantic_kernel "
        r"and settings\.allow_user_plugins and workspace_governance\.user_actions %\}"
        r"[\s\S]*plugin_modal_stepper\.js[\s\S]*"
        r"\{% endif %\}",
        re.MULTILINE,
    )

    checks = {
        "workspace template gates plugin_modal_stepper.js behind user action availability": bool(gated_script_pattern.search(workspace_template)),
        "stepper module checks for #plugin-modal before creating PluginModalStepper": "if (document.getElementById('plugin-modal'))" in stepper_js,
        "stepper module still creates the global instance when modal markup exists": "window.pluginModalStepper = new PluginModalStepper();" in stepper_js,
    }

    failed = [description for description, passed in checks.items() if not passed]
    if failed:
        print("Plugin stepper script gating checks failed:")
        for description in failed:
            print(f"  - {description}")
        assert not failed, "Plugin stepper script gating checks failed."

    print("Personal workspace plugin stepper script gating test passed!")


if __name__ == "__main__":
    test_workspace_plugin_stepper_script_gating()
    sys.exit(0)