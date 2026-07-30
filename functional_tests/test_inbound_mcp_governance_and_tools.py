# test_inbound_mcp_governance_and_tools.py
#!/usr/bin/env python3
"""
Functional test for inbound MCP governance and first tool contracts.
Version: 0.250.100
Implemented in: 0.250.070
Simplified personal access/source governance implemented in: 0.250.080
Single inbound MCP access policy implemented in: 0.250.081
Personal conversation read tools implemented in: 0.250.082
Personal document and prompt listing tools implemented in: 0.250.083
Personal document search tool implemented in: 0.250.084
Stateless MCP lifecycle negotiation implemented in: 0.250.089
Personal workflow execution tool implemented in: 0.250.090
Inbound MCP source governance enforcement implemented in: 0.250.091
Inbound MCP source-only governance implemented in: 0.250.092
Personal workflow listing and clear workflow-id guidance implemented in: 0.250.094
Inbound MCP enterprise readiness hardening implemented in: 0.250.096

This test ensures inbound MCP uses explicit inbound MCP source governance,
exposes only implemented tools through JSON-RPC, and binds personal tools to
the delegated user rather than caller-supplied user identifiers.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file for source-level contract validation."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_governance_policy_dimensions():
    """Validate inbound MCP governance requires source policies."""
    source = read_repo_file("application/single_app/functions_mcp_server_governance.py")
    governance_source = read_repo_file("application/single_app/functions_governance.py")

    expected_entities = [
        "inbound_mcp_source",
    ]
    for entity in expected_entities:
        assert entity in source

    assert "inbound_mcp_access" not in source
    assert "get_explicit_item_policies(entity_type, item_id)" in source
    assert "has no explicit inbound MCP policy" in source
    assert "effect == \"deny\"" in source
    assert "mcp_identity_type_not_allowed" in source
    assert "mcp_delegated_user_required" in source
    assert '"mcp_access_not_allowed"' not in source
    assert "_evaluate_explicit_policy_group(" in source
    assert "INBOUND_MCP_ACCESS_ITEM_ID" not in source
    assert "INBOUND_MCP_ACCESS_POLICY_ENTITY" not in source
    assert "INBOUND_MCP_SOURCE_POLICY_ENTITY = \"inbound_mcp_source\"" in source
    assert "INBOUND_MCP_SOURCE_POLICY_ENTITY," in source
    assert "source_policy_item_ids = [normalized_source_id] if normalized_source_id else []" in source
    assert "source_policy_item_ids.append(\"*\")" in source
    assert '"mcp_source_not_allowed"' in source
    assert "LEGACY_INBOUND_MCP_POLICY_ENTITIES" not in source
    assert "INBOUND_MCP_CLIENT_POLICY_ENTITY" not in source
    assert "INBOUND_MCP_TOOL_POLICY_ENTITY" not in source
    assert "INBOUND_MCP_RESOURCE_OPERATION_POLICY_ENTITY" not in source
    assert 'f"{normalized_scope}:{normalized_resource_family}:{normalized_operation}"' not in source
    assert 'f"{normalized_scope}:{normalized_target_scope_id}"' not in source
    assert 'f"{normalized_scope}:*"' not in source
    assert "INBOUND_MCP_SYSTEM_SOURCE_POLICY_ID = \"system-allow-all-sources\"" in governance_source
    assert "sync_inbound_mcp_source_governance_policy" not in governance_source
    assert "_delete_inbound_mcp_wildcard_source_policies" not in governance_source
    assert "ignored_policy_ids={INBOUND_MCP_SYSTEM_SOURCE_POLICY_ID}" in source
    assert '"system_managed": True' not in governance_source


def test_registry_exposes_only_implemented_governed_tools():
    """Validate the registry separates planned tools from implemented tools."""
    source = read_repo_file("application/single_app/functions_mcp_server_registry.py")

    assert '"id": "list_personal_tags"' in source
    assert '"id": "list_conversations"' in source
    assert '"id": "get_conversation_messages"' in source
    assert '"id": "list_personal_documents"' in source
    assert '"id": "list_personal_prompts"' in source
    assert '"id": "search_personal_documents"' in source
    assert '"id": "list_personal_workflows"' in source
    assert '"implemented": True' in source
    assert '"id": "execute_workflow"' in source
    assert '"implemented": False' not in source
    assert "if not bool(tool.get(\"implemented\", False)):" in source
    assert "evaluate_inbound_mcp_governance(" in source
    assert "build_mcp_tool_descriptor" in source
    assert '"inputSchema": tool.get("input_schema")' in source
    assert "show_user_profile" not in source
    assert "list_agent_template_tags" not in source


def test_json_rpc_tool_dispatch_contract():
    """Validate the inbound route implements the minimal MCP JSON-RPC methods."""
    source = read_repo_file("application/single_app/route_inbound_mcp.py")

    assert '"jsonrpc": "2.0"' in source
    assert 'method == "initialize"' in source
    assert 'method == "tools/list"' in source
    assert 'method == "tools/call"' in source
    assert 'method == "notifications/initialized"' in source
    assert "INBOUND_MCP_SUPPORTED_PROTOCOL_VERSIONS = (" in source
    assert '"2025-11-25"' in source
    assert '"2025-06-18"' in source
    assert '"2025-03-26"' in source
    assert "if requested_protocol_version in INBOUND_MCP_SUPPORTED_PROTOCOL_VERSIONS:" in source
    assert '"protocolVersion": protocol_version' in source
    assert 'Response("", status=202)' in source
    assert '"2024-11-05"' not in source
    assert "_log_initialize_request(auth_context, params, initialize_result[\"protocolVersion\"], mcp_request_id)" in source
    assert "build_mcp_tool_descriptor(tool)" in source
    assert "execute_inbound_mcp_tool(tool.get(\"id\", \"\"), auth_context, arguments)" in source
    assert "Inbound MCP governance denied the tool call." in source
    assert "Inbound MCP tool access denied." in source
    assert "check_inbound_mcp_tool_rate_limit(auth_context, tool, runtime_config=runtime_config)" in source
    assert "Inbound MCP tool call denied by rate limit." in source
    assert "-32029" in source
    assert "-32050" in source
    assert "resolve_inbound_mcp_request_id(auth_context, request)" in source
    assert "Inbound MCP request payload is too large." in source
    assert "mcp_request_id" in source
    assert '"X-Correlation-ID"' in source
    assert "InboundMcpToolConflict" in source
    assert "-32009" in source
    assert "error_data.setdefault(\"http_status\", status_code)" in source
    assert "error_data.setdefault(\"mcp_request_id\", mcp_request_id)" in source
    assert "Inbound MCP resource not found." in source
    assert "def _is_tool_result_error(tool_id, result):" in source
    assert 'str(tool_id or "").strip() != "execute_workflow"' in source
    assert 'return run.get("success") is False' in source
    assert '"isError": is_error_result' in source
    assert "response.status_code = 200" in source
    assert "return _attach_inbound_mcp_headers(response, mcp_request_id)" in source
    assert "Unsupported inbound MCP method." in source


def test_conversation_read_tools_contract():
    """Validate conversation MCP tools are delegated-user scoped and bounded."""
    tool_source = read_repo_file("application/single_app/functions_mcp_server_tools.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")

    assert "def list_conversations(auth_context, arguments=None):" in tool_source
    assert "def get_conversation_messages(auth_context, arguments=None):" in tool_source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in tool_source
    assert "list_personal_collaboration_conversations_for_user(delegated_user_id)" in tool_source
    assert "MEMBERSHIP_STATUS_ACCEPTED" in tool_source
    assert "cosmos_conversations_container.query_items(" in tool_source
    assert "assert_user_can_view_collaboration_conversation(delegated_user_id, conversation_item)" in tool_source
    assert "is_personal_collaboration_conversation(conversation_item)" in tool_source
    assert "list_collaboration_messages(conversation_item.get(\"id\"))" in tool_source
    assert "cosmos_messages_container.query_items(" in tool_source
    assert "filter_assistant_artifact_items(all_items)" in tool_source
    assert "INBOUND_MCP_MESSAGE_CONTENT_MAX_CHARS = 4000" in tool_source
    assert "INBOUND_MCP_CONVERSATION_LIMIT_MAX = 50" in tool_source
    assert "INBOUND_MCP_OFFSET_MAX = 10000" in tool_source
    assert "arguments.get(\"user_id\")" not in tool_source
    assert "get_workspace_tags(arguments" not in tool_source
    assert 'normalized_tool_id == "list_conversations"' in tool_source
    assert 'normalized_tool_id == "get_conversation_messages"' in tool_source
    assert '"offset": {"type": "integer", "minimum": 0}' in registry_source
    assert '"include_hidden": {"type": "boolean"}' in registry_source
    assert '"conversation_id": {"type": "string", "minLength": 1, "maxLength": 128}' in registry_source


def test_personal_document_and_prompt_listing_contract():
    """Validate document and prompt MCP list tools are metadata-only and user-bound."""
    tool_source = read_repo_file("application/single_app/functions_mcp_server_tools.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")

    assert "def list_personal_documents(auth_context, arguments=None):" in tool_source
    assert "def list_personal_prompts(auth_context, arguments=None):" in tool_source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in tool_source
    assert "_query_accessible_documents(delegated_user_id)" in tool_source
    assert "select_current_documents(" in tool_source
    assert "sort_documents(" in tool_source
    assert "sanitize_tags_for_filter(requested_tag)" in tool_source
    assert "tag must contain exactly one valid tag." in tool_source
    assert "cosmos_user_prompts_container.query_items(" in tool_source
    assert "SELECT c.id, c.name, c.type, c.created_at, c.updated_at" in tool_source
    assert 'normalized_tool_id == "list_personal_documents"' in tool_source
    assert 'normalized_tool_id == "list_personal_prompts"' in tool_source
    assert "prompt_item.get(\"content\")" not in tool_source
    assert '"relationship": relationship' in tool_source
    assert '"shared_approval_status": _get_shared_approval_status(document_item, delegated_user_id)' in tool_source
    assert '"offset": {"type": "integer", "minimum": 0}' in registry_source
    assert '"tag": {"type": "string", "minLength": 1, "maxLength": 50}' in registry_source


def test_personal_document_search_contract():
    """Validate personal document MCP search is bounded, metadata-safe, and user-bound."""
    tool_source = read_repo_file("application/single_app/functions_mcp_server_tools.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")
    search_function_source = tool_source[
        tool_source.index("def search_personal_documents"):
        tool_source.index("def list_personal_tags")
    ]

    assert "def search_personal_documents(auth_context, arguments=None):" in tool_source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in search_function_source
    assert "query must be 1000 characters or fewer." in tool_source
    assert "INBOUND_MCP_SEARCH_TOP_N_DEFAULT = 5" in tool_source
    assert "INBOUND_MCP_SEARCH_TOP_N_MAX = 20" in tool_source
    assert "INBOUND_MCP_SEARCH_SNIPPET_MAX_CHARS = 1000" in tool_source
    assert "INBOUND_MCP_SEARCH_SUMMARY_MAX_CHARS = 500" in tool_source
    assert "run_document_search(" in tool_source
    assert 'doc_scope="personal"' in tool_source
    assert "enable_file_sharing=True" in tool_source
    assert '"snippet": snippet' in tool_source
    assert '"snippet_truncated": snippet_truncated' in tool_source
    assert '"chunk_summary": chunk_summary' in tool_source
    assert '"chunk_summary_truncated": chunk_summary_truncated' in tool_source
    assert '"user_id":' not in search_function_source
    assert 'normalized_tool_id == "search_personal_documents"' in tool_source
    assert '"id": "search_personal_documents"' in registry_source
    assert '"top_n": {"type": "integer", "minimum": 1, "maximum": 20}' in registry_source
    assert '"query"' in registry_source


def test_list_personal_tags_contract():
    """Validate list_personal_tags stays delegated-user scoped and bounded."""
    source = read_repo_file("application/single_app/functions_mcp_server_tools.py")

    assert "INBOUND_MCP_TOOL_RESULT_LIMIT_MAX = 100" in source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in source
    assert "get_workspace_tags(delegated_user_id)" in source
    assert "get_workspace_tags(arguments" not in source
    assert '"scope": "personal"' in source
    assert '"name": tag_name' in source
    assert '"count": int(tag.get("count") or 0)' in source
    assert '"color": str(tag.get("color") or "").strip()' in source


def test_list_personal_workflows_contract():
    """Validate workflow listing is delegated-user scoped and metadata-only."""
    tool_source = read_repo_file("application/single_app/functions_mcp_server_tools.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")
    workflow_list_source = tool_source[
        tool_source.index("def list_personal_workflows"):
        tool_source.index("def _coerce_workflow_id")
    ]

    assert "def list_personal_workflows(auth_context, arguments=None):" in tool_source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in workflow_list_source
    assert "_require_personal_workflow_execution_enabled(auth_context)" in workflow_list_source
    assert "get_personal_workflows(delegated_user_id)" in workflow_list_source
    assert "_serialize_personal_workflow_summary(workflow)" in workflow_list_source
    assert "INBOUND_MCP_WORKFLOW_LIMIT_DEFAULT = 50" in tool_source
    assert "INBOUND_MCP_WORKFLOW_LIMIT_MAX = 100" in tool_source
    assert "INBOUND_MCP_WORKFLOW_DESCRIPTION_MAX_CHARS = 500" in tool_source
    assert '"task_prompt":' not in workflow_list_source
    assert "workflow.get(\"task_prompt\")" not in workflow_list_source
    assert '"document_action":' not in workflow_list_source
    assert "workflow.get(\"document_action\")" not in workflow_list_source
    assert '"selected_agent":' not in workflow_list_source
    assert "workflow.get(\"selected_agent\")" not in workflow_list_source
    assert '"id": "list_personal_workflows"' in registry_source
    assert '"operation": "list"' in registry_source
    assert '"resource_family": "workflows"' in registry_source
    assert '"audit_event": "InboundMcpListPersonalWorkflows"' in registry_source
    assert "including generated workflow ids for execution" in registry_source
    assert '"limit": {"type": "integer", "minimum": 1, "maximum": 100}' in registry_source
    assert '"offset": {"type": "integer", "minimum": 0}' in registry_source
    assert 'normalized_tool_id == "list_personal_workflows"' in tool_source


def test_execute_workflow_contract():
    """Validate execute_workflow uses owned personal workflows and runner guardrails."""
    tool_source = read_repo_file("application/single_app/functions_mcp_server_tools.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")
    workflow_source = tool_source[
        tool_source.index("def execute_workflow"):
        tool_source.index("def execute_inbound_mcp_tool")
    ]

    assert "def execute_workflow(auth_context, arguments=None):" in tool_source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in workflow_source
    assert "is_user_workflows_enabled_for_user(get_settings(), user_roles=roles)" in tool_source
    assert "workflow_id = _coerce_workflow_id(arguments)" in workflow_source
    assert "get_personal_workflow(delegated_user_id, workflow_id)" in workflow_source
    assert "Use list_personal_workflows to find the generated workflow id" in workflow_source
    assert "workflow display names are not accepted" in workflow_source
    assert "acquire_distributed_task_lock(" in workflow_source
    assert 'f"workflow_run_{workflow_id}"' in workflow_source
    assert "INBOUND_MCP_WORKFLOW_RUN_LOCK_SECONDS = 900" in tool_source
    assert "run_personal_workflow(" in workflow_source
    assert 'trigger_source="inbound_mcp"' in workflow_source
    assert "actor_user_id=delegated_user_id" in workflow_source
    assert 'run_record["mcp_invocation"] = _build_mcp_workflow_invocation_metadata(auth_context)' in tool_source
    assert "save_personal_workflow_run(delegated_user_id, run_record)" in tool_source
    assert "update_personal_workflow_runtime_fields(" in workflow_source
    assert "compute_next_run_at(" in workflow_source
    assert "release_distributed_task_lock(lock_document)" in workflow_source
    assert '"response_preview_available"' in tool_source
    assert '"response_preview":' not in workflow_source
    assert "InboundMcpToolConflict" in tool_source
    assert 'normalized_tool_id == "execute_workflow"' in tool_source
    assert '"id": "execute_workflow"' in registry_source
    assert '"implemented": True' in registry_source
    assert "Use list_personal_workflows to discover ids" in registry_source
    assert "Generated workflow id returned by list_personal_workflows" in registry_source
    assert "send_personal_chat_message" not in registry_source
    assert "send_personal_message" not in registry_source
    assert "arguments.get(\"user_id\")" not in workflow_source


if __name__ == "__main__":
    tests = [
        test_governance_policy_dimensions,
        test_registry_exposes_only_implemented_governed_tools,
        test_json_rpc_tool_dispatch_contract,
        test_conversation_read_tools_contract,
        test_personal_document_and_prompt_listing_contract,
        test_personal_document_search_contract,
        test_list_personal_tags_contract,
        test_list_personal_workflows_contract,
        test_execute_workflow_contract,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as ex:
            print(f"FAIL: {ex}")
            import traceback

            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
