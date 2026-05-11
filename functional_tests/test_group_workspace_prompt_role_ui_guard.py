# test_group_workspace_prompt_role_ui_guard.py
"""
Functional test for group workspace prompt role UI guard.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures that the group workspace prompt role UI safely handles
missing prompt containers so active-group loading can continue.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUP_WORKSPACE_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "group_workspaces.html",
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "config.py",
)


def read_file(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_group_workspace_prompt_role_ui_uses_guarded_dom_access():
    """Verify prompt role UI updates tolerate missing containers."""
    print("Testing group workspace prompt role UI guard...")

    content = read_file(GROUP_WORKSPACE_TEMPLATE)

    required_snippets = [
        'const createGroupPromptSection = document.getElementById(',
        '"create-group-prompt-section"',
        'const groupPromptsRoleWarning = document.getElementById(',
        '"group-prompts-role-warning"',
        'if (!createGroupPromptSection || !groupPromptsRoleWarning) {',
        'createGroupPromptSection.classList.toggle("d-none", !canManage);',
        'groupPromptsRoleWarning.classList.toggle("d-none", canManage);',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f"Missing guarded prompt role UI snippets: {missing}"

    forbidden_snippets = [
        'document.getElementById("create-group-prompt-section").style.display',
        'document.getElementById("group-prompts-role-warning").style.display',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in content]
    assert not present, f"Unexpected direct prompt role UI DOM access found: {present}"

    print("Prompt role UI guard is present")


def test_config_version_is_bumped_for_prompt_role_ui_guard_fix():
    """Verify config version was bumped for the prompt role UI guard fix."""
    print("Testing config version bump...")

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.241.007"' in config_content, "Expected config.py version 0.241.007"

    print("Config version bump passed")


if __name__ == "__main__":
    tests = [
        test_group_workspace_prompt_role_ui_uses_guarded_dom_access,
        test_config_version_is_bumped_for_prompt_role_ui_guard_fix,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)