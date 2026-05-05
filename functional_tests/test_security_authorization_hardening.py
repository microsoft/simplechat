# test_security_authorization_hardening.py
"""
Functional test for security authorization hardening.
Version: 0.241.022
Implemented in: 0.241.007; 0.241.010; 0.241.011; 0.241.013; 0.241.014; 0.241.022

This test ensures Azure AI Search filter literals are escaped, active group
selection validates membership, approval routes enforce per-approval
authorization, history-grounded fallback revalidates scope before reuse,
chat routes reject foreign conversation and scope ids, tabular and fact-memory
plugins bind to canonical request authorization, and Control Center public
workspace rendering escapes untrusted text.
"""

import ast
import os
import sys
from typing import Any, Dict, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_search.py")
GROUP_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_group.py")
PUBLIC_WORKSPACES_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "functions_public_workspaces.py",
)
USERS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_users.py")
BACKEND_PUBLIC_WORKSPACES_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_public_workspaces.py",
)
FRONTEND_GROUP_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_frontend_group_workspaces.py")
FRONTEND_PUBLIC_WORKSPACES_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_frontend_public_workspaces.py",
)
PUBLIC_PROMPTS_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_public_prompts.py",
)
GROUP_PROMPTS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_group_prompts.py")
GROUPS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_groups.py")
APPROVALS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_approvals.py")
CONTROL_CENTER_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_control_center.py")
CHATS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_chats.py")
TABULAR_PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "semantic_kernel_plugins",
    "tabular_processing_plugin.py",
)
FACT_MEMORY_PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "semantic_kernel_plugins",
    "fact_memory_plugin.py",
)
CONTROL_CENTER_JS = os.path.join(ROOT_DIR, "application", "single_app", "static", "js", "control-center.js")
PUBLIC_DIRECTORY_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "public",
    "public_directory.js",
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
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.020",
    "PUBLIC_WORKSPACE_DETAILS_DISCLOSURE_FIX.md",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def load_functions(file_path, function_names, namespace=None):
    source = read_file_text(file_path)
    parsed = ast.parse(source, filename=file_path)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert len(selected_nodes) == len(function_names), (
        f"Expected functions {sorted(function_names)} in {file_path}, "
        f"found {[node.name for node in selected_nodes]}"
    )
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec_namespace = dict(namespace or {})
    exec(compile(module, file_path, "exec"), exec_namespace)
    return exec_namespace, source


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


def test_search_odata_helpers_escape_literals():
    """Verify OData helper functions escape injected quotes before filter assembly."""
    print("🔍 Testing OData literal escaping helpers...")

    namespace, source = load_functions(
        SEARCH_FILE,
        {"_escape_odata_literal", "_build_odata_eq", "_build_odata_any_eq"},
        {"Any": Any},
    )
    build_eq = namespace["_build_odata_eq"]
    build_any = namespace["_build_odata_any_eq"]

    malicious_document_id = "doc' or '1'='1"
    assert build_eq("document_id", malicious_document_id) == "document_id eq 'doc'' or ''1''=''1'"
    assert build_any("shared_user_ids", "u", "user'1,approved") == (
        "shared_user_ids/any(u: u eq 'user''1,approved')"
    )

    assert "document_id eq '{document_ids[0]}'" not in source
    assert "shared_group_ids/any(g: g eq '{gid},approved')" not in source

    print("✅ OData escaping helpers passed")


def test_active_group_updates_and_group_routes_require_membership():
    """Verify active-group writes and group-scoped routes use membership validation helpers."""
    print("🔍 Testing active-group and group route authorization hardening...")

    functions_group_source = read_file_text(GROUP_FILE)
    users_source = read_file_text(USERS_FILE)
    frontend_group_source = read_file_text(FRONTEND_GROUP_FILE)
    group_prompts_source = read_file_text(GROUP_PROMPTS_FILE)
    groups_source = read_file_text(GROUPS_FILE)

    assert "assert_group_role(" in functions_group_source
    assert "DocumentManager" in functions_group_source and "User" in functions_group_source
    assert "update_active_group_for_user(requested_active_group, user_id=user_id)" in users_source
    assert "update_active_group_for_user(group_id, user_id=user_id)" in frontend_group_source
    assert "require_active_group(" in group_prompts_source
    assert 'get_user_settings(user_id)["settings"].get("activeGroupOid")' not in group_prompts_source

    group_details_source = extract_function_source(groups_source, "api_get_group_details")
    assert "get_user_role_in_group(group_doc, user_id)" in group_details_source
    assert "You are not a member of this group" in group_details_source

    print("✅ Active-group and group route authorization hardening passed")


def test_active_public_workspace_updates_validate_workspace_existence():
    """Verify active public workspace writes now flow through the validated helper path."""
    print("🔍 Testing active public workspace settings validation...")

    public_workspace_source = read_file_text(PUBLIC_WORKSPACES_FILE)
    users_source = read_file_text(USERS_FILE)
    backend_public_workspace_source = read_file_text(BACKEND_PUBLIC_WORKSPACES_FILE)
    frontend_public_workspace_source = read_file_text(FRONTEND_PUBLIC_WORKSPACES_FILE)
    public_prompts_source = read_file_text(PUBLIC_PROMPTS_FILE)

    assert "workspace_doc = find_public_workspace_by_id(normalized_workspace_id)" in public_workspace_source
    assert 'raise LookupError("Workspace not found")' in public_workspace_source
    assert "def require_active_public_workspace(" in public_workspace_source
    assert 'functions_settings.update_user_settings(' in public_workspace_source
    assert "update_active_public_workspace_for_user(" in users_source
    assert "requested_active_public_workspace" in users_source
    assert 'return jsonify({"error": "Workspace not found"}), 404' in users_source
    assert "No valid settings keys provided" in users_source
    assert backend_public_workspace_source.count("update_active_public_workspace_for_user(user_id, ws_id)") == 1
    assert "update_user_settings(user_id, {\"activePublicWorkspaceOid\": workspace_id})" not in frontend_public_workspace_source
    assert frontend_public_workspace_source.count("update_active_public_workspace_for_user(user_id, workspace_id)") == 1
    assert "require_active_public_workspace(" in public_prompts_source
    assert "settings['settings'].get('activePublicWorkspaceOid')" not in public_prompts_source

    print("✅ Active public workspace settings validation passed")


def test_public_workspace_details_route_limits_non_member_payloads():
    """Verify workspace detail responses stay projected by caller role."""
    print("🔍 Testing public workspace detail payload projection...")

    namespace, _ = load_functions(
        PUBLIC_WORKSPACES_FILE,
        {
            "get_user_role_in_public_workspace",
            "build_public_workspace_public_summary",
            "build_public_workspace_member_payload",
        },
    )
    build_public_summary = namespace["build_public_workspace_public_summary"]
    build_member_payload = namespace["build_public_workspace_member_payload"]

    workspace_doc = {
        "id": "workspace-1",
        "name": "Shared Workspace",
        "description": "Public summary",
        "owner": {
            "userId": "owner-1",
            "displayName": "Workspace Owner",
            "email": "owner@example.com",
        },
        "admins": [
            "admin-legacy-1",
            {"userId": "admin-1", "displayName": "Admin User", "email": "admin@example.com"},
        ],
        "documentManagers": [{"userId": "manager-1", "displayName": "Manager", "email": "manager@example.com"}],
        "pendingDocumentManagers": [{"userId": "pending-1", "displayName": "Pending", "email": "pending@example.com"}],
        "metrics": {"document_metrics": {"total_documents": 5}},
        "retention_policy": {"conversation_retention_days": 30},
        "status": "active",
        "heroColor": "#112233",
    }

    public_summary = build_public_summary(workspace_doc)
    assert public_summary == {
        "id": "workspace-1",
        "name": "Shared Workspace",
        "description": "Public summary",
        "owner": {"displayName": "Workspace Owner"},
        "status": "active",
        "heroColor": "#112233",
        "userRole": None,
        "isMember": False,
    }, public_summary

    owner_payload = build_member_payload(workspace_doc, "owner-1")
    assert owner_payload["userRole"] == "Owner"
    assert owner_payload["isMember"] is True
    assert owner_payload["owner"]["email"] == "owner@example.com"
    assert owner_payload["retention_policy"] == {"conversation_retention_days": 30}
    assert "admins" not in owner_payload
    assert "documentManagers" not in owner_payload
    assert "pendingDocumentManagers" not in owner_payload
    assert "metrics" not in owner_payload

    manager_payload = build_member_payload(workspace_doc, "manager-1")
    assert manager_payload["userRole"] == "DocumentManager"
    assert "retention_policy" not in manager_payload

    admin_payload = build_member_payload(workspace_doc, "admin-1")
    assert admin_payload["userRole"] == "Admin"
    assert admin_payload["retention_policy"] == {"conversation_retention_days": 30}

    backend_route_source = extract_function_source(
        read_file_text(BACKEND_PUBLIC_WORKSPACES_FILE),
        "api_get_public_workspace",
    )
    assert "build_public_workspace_member_payload(ws, user_id)" in backend_route_source
    assert "build_public_workspace_public_summary(ws)" in backend_route_source
    assert "return jsonify(ws), 200" not in backend_route_source

    public_directory_source = read_file_text(PUBLIC_DIRECTORY_JS)
    assert "workspace.owner?.displayName || workspace.owner?.email" not in public_directory_source
    assert "workspace.owner?.displayName || 'Unknown'" in public_directory_source

    manage_workspace_source = read_file_text(MANAGE_PUBLIC_WORKSPACE_JS)
    assert "const isMember = Boolean(ws.isMember);" in manage_workspace_source
    assert "currentUserRole = ws.userRole || null;" in manage_workspace_source
    assert "const admins = ws.admins || [];" not in manage_workspace_source
    assert "const docMgrs = ws.documentManagers || [];" not in manage_workspace_source

    print("✅ Public workspace detail payload projection passed")


def test_approval_access_helper_enforces_visibility_and_eligibility():
    """Verify approval access helper distinguishes view from approve rights."""
    print("🔍 Testing approval access authorization helper...")

    namespace, _ = load_functions(
        APPROVALS_FILE,
        {"_can_user_view", "_can_user_approve", "get_authorized_approval"},
        {
            "Dict": Dict,
            "Any": Any,
            "List": List,
            "TYPE_DELETE_USER_DOCUMENTS": "delete_user_documents",
        },
    )
    approval_doc = {
        "id": "approval-1",
        "group_id": "group-1",
        "request_type": "delete_documents",
        "requester_id": "requester-1",
        "group_owner_id": "owner-1",
    }
    namespace["get_approval_by_id"] = lambda approval_id, group_id: approval_doc if approval_id == "approval-1" else None
    get_authorized_approval = namespace["get_authorized_approval"]

    assert get_authorized_approval("approval-1", "group-1", "owner-1", [], True) == approval_doc

    try:
        get_authorized_approval("approval-1", "group-1", "viewer-1", [], True)
    except PermissionError:
        pass
    else:
        raise AssertionError("Expected ineligible approver lookup to raise PermissionError")

    route_source = read_file_text(CONTROL_CENTER_FILE)
    assert "def _get_authorized_route_approval(" in route_source
    assert route_source.count("get_authorized_approval(") == 1
    assert route_source.count("_get_authorized_route_approval(") >= 7
    assert "approval=approval" in route_source

    print("✅ Approval access authorization helper passed")


def test_history_fallback_revalidation_filters_revoked_scope():
    """Verify grounded fallback scope is filtered to the caller's current access."""
    print("🔍 Testing history-grounded fallback revalidation...")

    namespace, _ = load_functions(
        CHATS_FILE,
        {
            "_normalize_requested_scope_ids",
            "_get_authorized_chat_scope_context",
            "build_prior_grounded_document_search_parameters",
            "revalidate_prior_grounded_document_search_parameters",
        },
    )
    namespace["find_group_by_id"] = lambda group_id: {"id": group_id}
    namespace["get_user_role_in_group"] = (
        lambda group_doc, user_id: "User"
        if user_id == "user-1" and group_doc.get("id") == "group-allowed"
        else None
    )
    namespace["get_user_visible_public_workspace_ids_from_settings"] = (
        lambda user_id: ["workspace-allowed"]
    )

    build_params = namespace["build_prior_grounded_document_search_parameters"]
    revalidate = namespace["revalidate_prior_grounded_document_search_parameters"]

    mixed_parameters = build_params([
        {"document_id": "doc-personal", "scope": "personal", "scope_id": "user-1", "user_id": "user-1"},
        {"document_id": "doc-group", "scope": "group", "scope_id": "group-allowed", "group_id": "group-allowed"},
        {"document_id": "doc-public", "scope": "public", "scope_id": "workspace-allowed", "public_workspace_id": "workspace-allowed"},
        {"document_id": "doc-revoked-group", "scope": "group", "scope_id": "group-revoked", "group_id": "group-revoked"},
    ])
    filtered_parameters = revalidate("user-1", mixed_parameters)

    assert filtered_parameters["active_group_ids"] == ["group-allowed"]
    assert filtered_parameters["active_public_workspace_ids"] == ["workspace-allowed"]
    assert filtered_parameters["doc_scope"] == "all"

    revoked_only_parameters = build_params([
        {"document_id": "doc-revoked-group", "scope": "group", "scope_id": "group-revoked", "group_id": "group-revoked"},
        {"document_id": "doc-revoked-public", "scope": "public", "scope_id": "workspace-revoked", "public_workspace_id": "workspace-revoked"},
    ])
    revoked_only_parameters = revalidate("user-1", revoked_only_parameters)

    assert revoked_only_parameters["document_ids"] == []
    assert revoked_only_parameters["doc_scope"] is None

    print("✅ History-grounded fallback revalidation passed")


def test_chat_route_enforces_conversation_ownership_and_scope_canonicalization():
    """Verify chat helpers reject foreign conversation ids and drop unauthorized request scopes."""
    print("🔍 Testing chat conversation ownership and scope canonicalization...")

    class DummyNotFoundError(Exception):
        pass

    class DummyConversationContainer:
        def __init__(self, item=None, exc=None):
            self.item = item
            self.exc = exc

        def read_item(self, item, partition_key):
            assert item == partition_key
            if self.exc:
                raise self.exc
            return dict(self.item)

    namespace, source = load_functions(
        CHATS_FILE,
        {
            "_normalize_requested_scope_ids",
            "_get_authorized_chat_scope_context",
            "_authorize_personal_conversation_access",
        },
        {
            "CosmosResourceNotFoundError": DummyNotFoundError,
            "cosmos_conversations_container": DummyConversationContainer({"id": "conv-1", "user_id": "user-1"}),
        },
    )
    namespace["find_group_by_id"] = lambda group_id: {"id": group_id}
    namespace["get_user_role_in_group"] = (
        lambda group_doc, user_id: "User"
        if user_id == "user-1" and group_doc.get("id") == "group-allowed"
        else None
    )
    namespace["get_user_visible_public_workspace_ids_from_settings"] = lambda user_id: ["workspace-allowed"]

    scope_context = namespace["_get_authorized_chat_scope_context"](
        "user-1",
        active_group_id="group-revoked",
        active_group_ids=["group-allowed", "group-revoked"],
        active_public_workspace_id="workspace-revoked",
        active_public_workspace_ids=["workspace-allowed", "workspace-revoked"],
    )
    assert scope_context["active_group_ids"] == ["group-allowed"]
    assert scope_context["active_group_id"] == "group-allowed"
    assert scope_context["active_public_workspace_ids"] == ["workspace-allowed"]
    assert scope_context["active_public_workspace_id"] == "workspace-allowed"

    authorize_conversation = namespace["_authorize_personal_conversation_access"]
    authorized_item = authorize_conversation("user-1", "conv-1")
    assert authorized_item["user_id"] == "user-1"

    namespace["cosmos_conversations_container"] = DummyConversationContainer({"id": "conv-1", "user_id": "user-2"})
    try:
        authorize_conversation("user-1", "conv-1")
    except PermissionError:
        pass
    else:
        raise AssertionError("Expected foreign conversation ownership to raise PermissionError")

    namespace["cosmos_conversations_container"] = DummyConversationContainer(exc=DummyNotFoundError())
    try:
        authorize_conversation("user-1", "missing-conv")
    except LookupError:
        pass
    else:
        raise AssertionError("Expected missing conversation to raise LookupError")

    assert "active_group_ids[0] if active_group_ids else data.get('active_group_id')" not in source
    assert "active_public_workspace_ids = [active_public_workspace_id]" not in extract_function_source(source, "chat_api")
    assert source.find("_authorize_personal_conversation_access(user_id, requested_conversation_id)") < source.find(
        "CHAT_STREAM_REGISTRY.start_session(user_id, finalized_conversation_id)"
    )

    print("✅ Chat conversation ownership and scope canonicalization passed")


def test_tabular_plugin_binds_request_scopes_before_blob_access():
    """Verify the tabular plugin validates request context before using tool-call scope ids."""
    print("🔍 Testing tabular plugin request-scope binding...")

    source = read_file_text(TABULAR_PLUGIN_FILE)

    required_snippets = [
        "def _get_authorized_chat_context(self) -> dict:",
        "def _resolve_authorized_scope_arguments(",
        "authorized_context = self._resolve_authorized_scope_arguments(",
        "override and self._is_authorized_blob_location(",
        "return json.dumps({\"error\": str(exc)})",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing tabular authorization snippets: {missing}"

    assert "Tabular processing cannot access that group scope." in source
    assert "Tabular processing cannot access that public workspace scope." in source
    assert "requested_user_id and requested_user_id != authorized_context['user_id']" in source
    assert "requested_conversation_id and requested_conversation_id != authorized_context['conversation_id']" in source

    print("✅ Tabular plugin request-scope binding passed")


def test_fact_memory_plugin_uses_authorized_request_scope():
    """Verify the fact-memory plugin no longer forwards raw tool-call scope ids to the store."""
    print("🔍 Testing fact-memory request-scope binding...")

    source = read_file_text(FACT_MEMORY_PLUGIN_FILE)

    required_snippets = [
        "def _get_authorized_fact_memory_scope(self) -> dict:",
        "def _resolve_authorized_fact_memory_call(",
        "scope_type=authorized_scope['scope_type']",
        "scope_id=authorized_scope['scope_id']",
        "conversation_id=authorized_scope['conversation_id']",
        "[FactMemoryPlugin] Overriding mismatched fact-memory scope in tool call.",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing fact-memory authorization snippets: {missing}"

    print("✅ Fact-memory request-scope binding passed")


def test_control_center_workspace_renderer_escapes_untrusted_fields():
    """Verify the Control Center workspace row renderer escapes untrusted metadata."""
    print("🔍 Testing Control Center public workspace escaping...")

    source = read_file_text(CONTROL_CENTER_JS)

    required_snippets = [
        "this.escapeHtml(workspace.name || 'Unnamed Workspace')",
        "this.escapeHtml(workspace.description || 'No description')",
        "this.escapeHtml(ownerName)",
        "this.escapeHtml(ownerEmail)",
        "this.escapeHtml(log.document?.file_name || 'Unknown')",
        "this.escapeHtml(log.conversation?.title || 'Untitled')",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing escaped Control Center snippets: {missing}"

    forbidden_snippets = [
        "${workspace.name || 'Unnamed Workspace'}",
        "${workspace.description || 'No description'}",
        "${ownerName}",
        "${ownerEmail}",
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unescaped Control Center snippets found: {present}"

    print("✅ Control Center public workspace escaping passed")


def test_security_fix_documentation_and_version_bump_exist():
    """Verify the fix doc exists and config version was bumped for this security pass."""
    print("🔍 Testing security fix documentation and version bump...")

    assert read_config_version() == "0.241.022"
    assert os.path.exists(FIX_DOC), f"Expected fix documentation at {FIX_DOC}"

    fix_doc_text = read_file_text(FIX_DOC)
    assert "/api/public_workspaces/<ws_id>" in fix_doc_text
    assert "pendingDocumentManagers" in fix_doc_text
    assert "userRole" in fix_doc_text

    print("✅ Security fix documentation and version bump passed")


if __name__ == "__main__":
    tests = [
        test_search_odata_helpers_escape_literals,
        test_active_group_updates_and_group_routes_require_membership,
        test_active_public_workspace_updates_validate_workspace_existence,
        test_public_workspace_details_route_limits_non_member_payloads,
        test_approval_access_helper_enforces_visibility_and_eligibility,
        test_history_fallback_revalidation_filters_revoked_scope,
        test_chat_route_enforces_conversation_ownership_and_scope_canonicalization,
        test_tabular_plugin_binds_request_scopes_before_blob_access,
        test_fact_memory_plugin_uses_authorized_request_scope,
        test_control_center_workspace_renderer_escapes_untrusted_fields,
        test_security_fix_documentation_and_version_bump_exist,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)