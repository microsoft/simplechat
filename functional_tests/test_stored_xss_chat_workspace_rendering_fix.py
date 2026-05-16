# test_stored_xss_chat_workspace_rendering_fix.py
"""
Functional test for stored XSS chat and workspace rendering hardening.
Version: 0.241.154
Implemented in: 0.241.022

This test ensures chat agent display names, workspace member display names,
and Graph user search filters are safely encoded before HTML or OData
insertion.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_MESSAGES_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-messages.js",
)
MANAGE_PUBLIC_WORKSPACE_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "public",
    "manage_public_workspace.js",
)
MANAGE_GROUP_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "group",
    "manage_group.js",
)
USERS_ROUTE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_users.py",
)
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.022",
    "STORED_XSS_AGENT_AND_MEMBER_RENDERING_FIX.md",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def load_function(file_path, function_name):
    source = read_file_text(file_path)
    parsed = ast.parse(source, filename=file_path)
    selected_node = next(
        (
            node
            for node in parsed.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    assert selected_node is not None, f"Expected function {function_name} in {file_path}"
    module = ast.Module(body=[selected_node], type_ignores=[])
    namespace = {}
    exec(compile(module, file_path, "exec"), namespace)
    return namespace[function_name]


def test_chat_agent_display_name_is_escaped_before_html_rendering():
    """Verify chat agent display names are escaped in both HTML sinks."""
    print("🔍 Testing chat agent display name escaping...")

    source = read_file_text(CHAT_MESSAGES_JS)

    required_snippets = [
        "senderLabel = escapeHtml(agentDisplayName);",
        "${escapeHtml(metadata.agent_display_name)}",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing chat escaping snippets: {missing}"

    forbidden_snippets = [
        "senderLabel = agentDisplayName;",
        "${metadata.agent_display_name}</span>",
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unescaped chat snippets found: {present}"

    print("✅ Chat agent display name escaping passed")


def test_public_workspace_member_renderers_escape_untrusted_fields():
    """Verify public workspace member-management renderers escape display names and emails."""
    print("🔍 Testing public workspace member rendering escaping...")

    source = read_file_text(MANAGE_PUBLIC_WORKSPACE_JS)

    required_snippets = [
        'const safeDisplayName = escapeHtml(m.displayName || "(no name)");',
        'const safeDisplayName = escapeHtml(req.displayName || "(no name)");',
        'const safeDisplayName = escapeHtml(u.displayName || "(no name)");',
        'data-user-name="${safeDisplayName}"',
        'membersList += `<li>&bull; ${safeName} (${safeEmail})</li>`;',
        '$(document).on("click", ".select-user-btn", function () {',
        "${escapeHtml(row.displayName || '')} (${escapeHtml(row.email || '')})",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing public workspace escaping snippets: {missing}"

    forbidden_snippets = [
        'onclick="selectUserForAdd(',
        '<td>${u.displayName || "(no name)"}</td>',
        '<td>${req.displayName}</td>',
        '<li>• ${member.name} (${member.email})</li>',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unescaped public workspace snippets found: {present}"

    print("✅ Public workspace member rendering escaping passed")


def test_group_workspace_member_renderers_escape_untrusted_fields():
    """Verify group workspace member-management renderers escape display names and emails."""
    print("🔍 Testing group workspace member rendering escaping...")

    source = read_file_text(MANAGE_GROUP_JS)

    required_snippets = [
        'const safeDisplayName = escapeHtml(m.displayName || "(no name)");',
        'const safeDisplayName = escapeHtml(u.displayName || "(no name)");',
        'data-user-name="${safeDisplayName}"',
        'membersList += `<li>&bull; ${safeName} (${safeEmail})</li>`;',
        "${escapeHtml(row.displayName || '')} (${escapeHtml(row.email || '')})",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing group workspace escaping snippets: {missing}"

    forbidden_snippets = [
        '<td>${u.displayName || "(no name)"}</td>',
        '<td>${u.email || ""}</td>',
        '<li>• ${member.name} (${member.email})</li>',
        '<option value="${m.userId}">${m.displayName} (${m.email})</option>',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unescaped group workspace snippets found: {present}"

    print("✅ Group workspace member rendering escaping passed")


def test_user_search_filter_escapes_odata_literals():
    """Verify /api/userSearch escapes apostrophes before building the Graph filter."""
    print("🔍 Testing Graph user search OData literal escaping...")

    escape_helper = load_function(USERS_ROUTE, "_escape_graph_odata_literal")
    assert escape_helper("o'hare") == "o''hare"
    assert escape_helper("") == ""

    source = read_file_text(USERS_ROUTE)
    assert "safe_query = _escape_graph_odata_literal(query)" in source
    assert "startswith(displayName, '{safe_query}')" in source
    assert "startswith(mail, '{safe_query}')" in source
    assert "startswith(userPrincipalName, '{safe_query}')" in source
    assert "startswith(displayName, '{query}')" not in source

    print("✅ Graph user search OData literal escaping passed")


def test_fix_documentation_and_version_exist():
    """Verify the version bump and fix documentation landed for this change."""
    print("🔍 Testing stored XSS rendering fix documentation and version...")

    assert read_config_version() == "0.241.154"
    assert os.path.exists(FIX_DOC), f"Expected fix documentation at {FIX_DOC}"

    print("✅ Stored XSS rendering fix documentation and version passed")


if __name__ == "__main__":
    tests = [
        test_chat_agent_display_name_is_escaped_before_html_rendering,
        test_public_workspace_member_renderers_escape_untrusted_fields,
        test_group_workspace_member_renderers_escape_untrusted_fields,
        test_user_search_filter_escapes_odata_literals,
        test_fix_documentation_and_version_exist,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)