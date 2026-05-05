# test_stored_xss_admin_rendering_fix.py
"""
Functional test for stored XSS admin rendering hardening.
Version: 0.241.016
Implemented in: 0.241.010

This test ensures Control Center member rendering, public workspace member
modal rendering, and admin agent rendering keep user-controlled names inert,
and that Control Center toast messages escape by default unless a caller
explicitly opts into HTML.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROL_CENTER_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "control_center.html",
)
CONTROL_CENTER_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "control-center.js",
)
ADMIN_AGENTS_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "admin",
    "admin_agents.js",
)
WORKSPACE_MANAGER_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "workspace-manager.js",
)
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
LEGACY_FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.012",
    "STORED_XSS_ADMIN_RENDERING_FIX.md",
)
NEW_FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.016",
    "CONTROL_CENTER_PUBLIC_WORKSPACE_MEMBERS_XSS_FIX.md",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def test_control_center_member_rows_escape_untrusted_fields():
    """Verify group-member modal rows escape member names and emails."""
    print("🔍 Testing Control Center group-member row escaping...")

    source = read_file_text(CONTROL_CENTER_TEMPLATE)

    assert "${GroupManager.escapeHtml(member.name || 'Unknown User')}" in source
    assert "${GroupManager.escapeHtml(member.email || 'No email')}" in source
    assert "${member.name || 'Unknown User'}" not in source
    assert "${member.email || 'No email'}" not in source

    print("✅ Control Center group-member row escaping passed")


def test_control_center_toasts_escape_by_default():
    """Verify Control Center toasts require explicit opt-in for HTML."""
    print("🔍 Testing Control Center toast escaping defaults...")

    source = read_file_text(CONTROL_CENTER_JS)

    assert "showToast(message, type = 'info', allowHtml = false)" in source
    assert "const safeMessage = allowHtml" in source
    assert "this.escapeHtml(String(message ?? ''))" in source
    assert "${safeMessage}" in source
    assert source.count("showToast(`Ownership transfer request submitted!<br><br>Status: Pending Approval") == 0

    template_source = read_file_text(CONTROL_CENTER_TEMPLATE)
    assert template_source.count("'success', true") >= 2
    assert "window.controlCenter.showToast(`Successfully added ${displayName} as ${role}`, 'success');" in template_source

    print("✅ Control Center toast escaping defaults passed")


def test_admin_agent_table_escapes_agent_fields():
    """Verify the admin agent table escapes user-controlled agent fields."""
    print("🔍 Testing admin agent table escaping...")

    source = read_file_text(ADMIN_AGENTS_JS)

    required_snippets = [
        "function escapeHtml(text) {",
        "const safeName = escapeHtml(agent.name || '')",
        "const safeDisplayName = escapeHtml(agent.display_name || '')",
        "const safeDescription = escapeHtml(agent.description || '')",
        "<td>${safeName}</td>",
        "<td>${safeDisplayName}</td>",
        "<td>${safeDescription}</td>",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing admin agent escaping snippets: {missing}"

    forbidden_snippets = [
        "<td>${agent.name}</td>",
        "<td>${agent.display_name}</td>",
        "<td>${agent.description || ''}</td>",
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unescaped admin agent snippets found: {present}"

    print("✅ Admin agent table escaping passed")


def test_workspace_members_modal_uses_text_nodes_for_untrusted_fields():
    """Verify the workspace members modal renders stored member metadata as text."""
    print("🔍 Testing workspace members modal escaping...")

    source = read_file_text(WORKSPACE_MANAGER_JS)

    required_snippets = [
        "const nameCell = document.createElement('td');",
        "const displayNameElement = document.createElement('div');",
        "const emailElement = document.createElement('div');",
        "displayNameElement.textContent = displayName;",
        "emailElement.textContent = email;",
        "row.appendChild(nameCell);",
        "row.appendChild(roleCell);",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing workspace members modal hardening snippets: {missing}"

    forbidden_snippets = [
        "<div>${displayName}</div>",
        '<div class="text-muted small">${email}</div>',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unescaped workspace members modal snippets found: {present}"

    print("✅ Workspace members modal escaping passed")


def test_fix_documentation_and_version_exist():
    """Verify the new version and fix documentation landed for this change."""
    print("🔍 Testing stored XSS fix documentation and version...")

    assert read_config_version() == "0.241.016"
    assert os.path.exists(LEGACY_FIX_DOC), f"Expected fix documentation at {LEGACY_FIX_DOC}"
    assert os.path.exists(NEW_FIX_DOC), f"Expected fix documentation at {NEW_FIX_DOC}"

    print("✅ Stored XSS fix documentation and version passed")


if __name__ == "__main__":
    tests = [
        test_control_center_member_rows_escape_untrusted_fields,
        test_control_center_toasts_escape_by_default,
        test_admin_agent_table_escapes_agent_fields,
        test_workspace_members_modal_uses_text_nodes_for_untrusted_fields,
        test_fix_documentation_and_version_exist,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)