# test_foundry_workflow_agent_payload.py
"""
Functional test for Foundry workflow agent payload support.
Version: 0.241.196
Implemented in: 0.241.127

This test ensures that generic Foundry workflow agents can be validated,
normalized, and stored without hardcoded workflow names. It also verifies
that Foundry agents discovered from the project agents API can be invoked
through the workflow agent_reference path. API-key workflow invocation is
rejected because Foundry agents and workflows require Entra/RBAC access.
"""

import os
import sys
import types
import asyncio

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

sys.modules.setdefault(
    "olefile",
    types.SimpleNamespace(isOleFile=lambda *_args, **_kwargs: False, OleFileIO=None),
)


class _DummyMcpConnector:
    """Minimal stand-in for optional Semantic Kernel MCP connectors."""

    def __init__(self, *args, **kwargs):
        pass


semantic_kernel_mcp = types.ModuleType("semantic_kernel.connectors.mcp")
semantic_kernel_mcp.MCPSsePlugin = _DummyMcpConnector
semantic_kernel_mcp.MCPStdioPlugin = _DummyMcpConnector
semantic_kernel_mcp.MCPStreamableHttpPlugin = _DummyMcpConnector
semantic_kernel_mcp.MCPWebsocketPlugin = _DummyMcpConnector
sys.modules.setdefault("semantic_kernel.connectors.mcp", semantic_kernel_mcp)

from functions_agent_payload import (  # noqa: E402
    AgentPayloadError,
    is_azure_ai_foundry_agent,
    is_foundry_workflow_agent,
    sanitize_agent_payload,
)
from json_schema_validation import validate_agent  # noqa: E402
from route_backend_agents import _strip_disallowed_local_custom_connection_fields  # noqa: E402
from foundry_agent_runtime import (  # noqa: E402
    _build_new_foundry_request_payload,
    _build_foundry_file_input_part,
    _build_foundry_workflow_endpoint_candidates,
    _build_foundry_workflow_conversation_params,
    _build_foundry_workflow_request_payload,
    _build_foundry_workflow_request_params,
    _build_foundry_workflow_response_urls,
    _build_foundry_workflow_agent_reference,
    execute_foundry_workflow_agent_stream,
    FoundryAgentStreamMessage,
    _normalize_foundry_workflow_rest_protocol,
    _extract_new_foundry_event_error,
    _extract_new_foundry_stream_text,
    _update_new_foundry_stream_state,
    list_foundry_workflows_from_endpoint,
    FoundryAgentInvocationError,
    NewFoundryStreamState,
)
from semantic_kernel.contents.chat_message_content import ChatMessageContent  # noqa: E402


VALID_WORKFLOW_PAYLOAD = {
    "id": "11111111-1111-4111-8111-111111111111",
    "name": "generic_foundry_workflow",
    "display_name": "Generic Foundry Workflow",
    "description": "Invokes a configured Foundry workflow by name.",
    "instructions": "Placeholder instructions: Azure AI Foundry agent manages its own prompt.",
    "agent_type": "foundry_workflow",
    "is_global": False,
    "is_group": False,
    "enable_agent_gpt_apim": True,
    "actions_to_load": ["should_be_removed"],
    "max_completion_tokens": -1,
    "azure_openai_gpt_endpoint": "https://example.services.ai.azure.com/api/projects/example-project",
    "azure_openai_gpt_deployment": "example-project",
    "azure_openai_gpt_api_version": "v1",
    "other_settings": {
        "azure_ai_foundry": {"agent_id": "stale-agent"},
        "new_foundry": {"application_id": "stale-app", "responses_api_version": "v1"},
        "foundry_workflow": {
            "workflow_name": "ExampleWorkflow",
            "workflow_agent_id": "agent-123",
            "application_id": "ExampleWorkflow:2026-06-01",
            "application_version": "2026-06-01",
            "agent_reference": {
                "type": "agent_reference",
                "name": "ExampleWorkflow",
                "id": "agent-123",
            },
            "include_document_context": True,
            "max_context_chars": "24000",
            "responses_path": "/openai/responses",
        },
    },
}


def test_foundry_workflow_agent_payload_normalizes_and_validates():
    """Validate workflow payload normalization and schema compatibility."""
    cleaned = sanitize_agent_payload(VALID_WORKFLOW_PAYLOAD)

    assert cleaned["agent_type"] == "foundry_workflow"
    assert cleaned["actions_to_load"] == []
    assert cleaned["enable_agent_gpt_apim"] is False
    assert is_foundry_workflow_agent(cleaned) is True
    assert is_azure_ai_foundry_agent(cleaned) is True

    workflow_settings = cleaned["other_settings"]["foundry_workflow"]
    assert workflow_settings["workflow_name"] == "ExampleWorkflow"
    assert workflow_settings["workflow_agent_id"] == "agent-123"
    assert workflow_settings["application_id"] == "ExampleWorkflow:2026-06-01"
    assert workflow_settings["application_version"] == "2026-06-01"
    assert workflow_settings["agent_reference"] == {
        "type": "agent_reference",
        "name": "ExampleWorkflow",
        "id": "agent-123",
    }
    assert workflow_settings["endpoint"] == VALID_WORKFLOW_PAYLOAD["azure_openai_gpt_endpoint"]
    assert workflow_settings["project_name"] == "example-project"
    assert workflow_settings["responses_api_version"] == "v1"
    assert workflow_settings["max_context_chars"] == 24000
    assert "azure_ai_foundry" not in cleaned["other_settings"]
    assert "new_foundry" not in cleaned["other_settings"]

    validation_error = validate_agent(cleaned)
    assert validation_error is None


def test_foundry_workflow_agent_requires_endpoint():
    """Validate that workflow agents need project endpoint configuration."""
    payload = dict(VALID_WORKFLOW_PAYLOAD)
    payload["azure_openai_gpt_endpoint"] = ""
    payload["other_settings"] = {
        "foundry_workflow": {
            "workflow_name": "ExampleWorkflow",
            "responses_api_version": "v1",
        }
    }

    try:
        sanitize_agent_payload(payload)
    except AgentPayloadError as exc:
        assert "endpoint" in str(exc).lower()
    else:
        raise AssertionError("Expected AgentPayloadError for missing endpoint")


def test_foundry_workflow_agent_rejects_invalid_context_limit():
    """Validate max_context_chars is numeric when provided."""
    payload = dict(VALID_WORKFLOW_PAYLOAD)
    payload["other_settings"] = {
        "foundry_workflow": {
            "workflow_name": "ExampleWorkflow",
            "responses_api_version": "v1",
            "max_context_chars": "not-a-number",
        }
    }

    try:
        sanitize_agent_payload(payload)
    except AgentPayloadError as exc:
        assert "max_context_chars" in str(exc)
    else:
        raise AssertionError("Expected AgentPayloadError for invalid max_context_chars")


def test_foundry_workflow_endpoint_survives_custom_endpoint_stripping():
    """Validate manual Foundry workflow details are preserved for users/groups."""
    payload = dict(VALID_WORKFLOW_PAYLOAD)
    stripped = _strip_disallowed_local_custom_connection_fields(payload)

    assert stripped["azure_openai_gpt_endpoint"] == VALID_WORKFLOW_PAYLOAD["azure_openai_gpt_endpoint"]
    assert stripped["azure_openai_gpt_api_version"] == "v1"
    assert stripped["other_settings"]["foundry_workflow"]["workflow_name"] == "ExampleWorkflow"

    local_payload = {
        "agent_type": "local",
        "azure_openai_gpt_endpoint": "https://local.example.openai.azure.com",
        "azure_openai_gpt_key": "secret",
    }
    _strip_disallowed_local_custom_connection_fields(local_payload)
    assert "azure_openai_gpt_endpoint" not in local_payload
    assert "azure_openai_gpt_key" not in local_payload


def test_foundry_workflow_versions_use_protocol_path_without_api_version_query():
    """Validate v1/v2 protocol paths do not send api-version query params."""
    endpoint = "https://example.services.ai.azure.com/api/projects/example-project"

    v2_urls = _build_foundry_workflow_response_urls(endpoint, {}, responses_api_version="v2")
    assert v2_urls[0] == f"{endpoint}/openai/v2/responses"
    assert _build_foundry_workflow_request_params("v2") == {}
    assert _build_foundry_workflow_conversation_params("v2") == {}

    v1_urls = _build_foundry_workflow_response_urls(endpoint, {}, responses_api_version="v1")
    assert v1_urls[0] == f"{endpoint}/openai/v1/responses"
    assert _build_foundry_workflow_request_params("v1") == {}
    assert _build_foundry_workflow_conversation_params("v1") == {}

    dated_params = _build_foundry_workflow_request_params("2025-11-15-preview")
    assert dated_params == {"api-version": "2025-11-15-preview"}
    assert _build_foundry_workflow_conversation_params("2025-11-15-preview") == dated_params


def test_foundry_workflow_rest_protocol_normalizes_saved_v2_to_v1():
    """Validate existing saved v2 workflow configs use documented REST v1."""
    assert _normalize_foundry_workflow_rest_protocol("v2") == "v1"
    assert _normalize_foundry_workflow_rest_protocol("v1") == "v1"
    assert _normalize_foundry_workflow_rest_protocol("2025-11-15-preview") == "2025-11-15-preview"


def test_foundry_workflow_builds_matching_conversation_endpoints():
    """Validate raw HTTP flow mirrors SDK conversation create + response call."""
    endpoint = "https://example.services.ai.azure.com/api/projects/example-project"
    candidates = _build_foundry_workflow_endpoint_candidates(
        endpoint,
        {},
        responses_api_version="v2",
    )

    assert candidates[0] == {
        "responses_url": f"{endpoint}/openai/v2/responses",
        "conversations_url": f"{endpoint}/openai/v2/conversations",
    }


def test_foundry_workflow_payload_keeps_simplechat_conversation_in_metadata_only():
    """Validate SimpleChat conversation IDs are not reused as Foundry conversation IDs."""
    payload = _build_foundry_workflow_request_payload(
        [ChatMessageContent(role="user", content="Hello workflow")],
        {"conversation_id": "simplechat-conversation-id"},
        workflow_name="ExampleWorkflow",
        stream=True,
    )

    assert "conversation" not in payload
    assert payload["metadata"]["conversation_id"] == "simplechat-conversation-id"
    assert payload["agent_reference"] == {
        "name": "ExampleWorkflow",
        "type": "agent_reference",
    }


def test_foundry_workflow_payload_uses_discovered_agent_reference():
    """Validate discovered Foundry agents can be invoked as workflow references."""
    workflow_settings = {
        "workflow_name": "ExampleWorkflow",
        "workflow_agent_id": "agent-123",
        "application_id": "ExampleWorkflow:2026-06-01",
        "application_version": "2026-06-01",
        "agent_reference": {
            "type": "agent_reference",
            "name": "ExampleWorkflow",
            "id": "agent-123",
            "application_id": "ExampleWorkflow:2026-06-01",
        },
    }

    payload = _build_foundry_workflow_request_payload(
        [ChatMessageContent(role="user", content="Hello workflow")],
        {},
        workflow_settings=workflow_settings,
        workflow_name="ExampleWorkflow",
        stream=True,
    )

    assert payload["agent_reference"] == {
        "type": "agent_reference",
        "name": "ExampleWorkflow",
        "id": "agent-123",
        "application_id": "ExampleWorkflow:2026-06-01",
        "application_version": "2026-06-01",
    }
    assert _build_foundry_workflow_agent_reference(workflow_settings, "ExampleWorkflow") == payload["agent_reference"]


def test_foundry_workflow_listing_normalizes_agents_as_workflows(monkeypatch):
    """Validate project agent list entries can populate workflow selection."""
    import foundry_agent_runtime

    def fake_list_new_foundry_agents_from_endpoint(foundry_settings, global_settings):
        return [
            {
                "id": "agent-123",
                "agent_id": "raw-agent-123",
                "name": "ExampleWorkflow",
                "display_name": "Example Workflow",
                "application_id": "ExampleWorkflow:2026-06-01",
                "application_name": "ExampleWorkflow",
                "application_version": "2026-06-01",
            }
        ]

    monkeypatch.setattr(
        foundry_agent_runtime,
        "list_new_foundry_agents_from_endpoint",
        fake_list_new_foundry_agents_from_endpoint,
    )
    workflows = list_foundry_workflows_from_endpoint({}, {})

    assert workflows == [
        {
            "id": "agent-123",
            "agent_id": "raw-agent-123",
            "name": "ExampleWorkflow",
            "display_name": "Example Workflow",
            "application_id": "ExampleWorkflow:2026-06-01",
            "application_name": "ExampleWorkflow",
            "application_version": "2026-06-01",
            "resource_type": "workflow",
            "workflow_name": "ExampleWorkflow",
            "workflow_agent_id": "raw-agent-123",
            "agent_reference": {
                "type": "agent_reference",
                "name": "ExampleWorkflow",
                "id": "raw-agent-123",
                "application_id": "ExampleWorkflow:2026-06-01",
                "application_version": "2026-06-01",
            },
        }
    ]


def test_foundry_workflow_api_key_agent_is_rejected(monkeypatch):
    """Validate API-key workflow agents do not use application-protocol fallback."""
    import foundry_agent_runtime

    def fail_create_conversation(*_args, **_kwargs):
        raise AssertionError("API-key workflow auth should be rejected before creating Foundry conversations.")

    monkeypatch.setattr(
        foundry_agent_runtime,
        "_create_foundry_workflow_conversation",
        fail_create_conversation,
    )

    workflow_settings = {
        "workflow_name": "ExampleWorkflow",
        "application_id": "ExampleWorkflow:2026-06-01",
        "endpoint": "https://example.services.ai.azure.com/api/projects/example-project",
        "responses_api_version": "v1",
        "authentication_type": "api_key",
        "api_key": "test-key",
    }

    async def collect_messages():
        async for stream_message in execute_foundry_workflow_agent_stream(
            workflow_settings=workflow_settings,
            global_settings={},
            message_history=[ChatMessageContent(role="user", content="Hello workflow")],
            metadata={"conversation_id": "simplechat-conversation-id"},
            workflow_name="ExampleWorkflow",
        ):
            raise AssertionError(f"Unexpected stream message for rejected API-key auth: {stream_message}")

    try:
        asyncio.run(collect_messages())
    except FoundryAgentInvocationError as exc:
        assert "requires Microsoft Entra ID/RBAC" in str(exc)
    else:
        raise AssertionError("Expected FoundryAgentInvocationError for API-key workflow auth")


def test_foundry_payload_metadata_omits_internal_scope_lists_and_caps_values():
    """Validate internal scope lists are not sent as Foundry metadata values."""
    metadata = {
        "conversation_id": "simplechat-conversation-id",
        "active_group_ids": [f"group-{index:03d}" for index in range(100)],
        "active_public_workspace_ids": [f"public-{index:03d}" for index in range(100)],
        "selected_document_ids": [f"doc-{index:03d}" for index in range(100)],
        "search_query": "x" * 700,
    }

    workflow_payload = _build_foundry_workflow_request_payload(
        [ChatMessageContent(role="user", content="Hello workflow")],
        metadata,
        workflow_name="ExampleWorkflow",
        stream=True,
    )
    new_foundry_payload = _build_new_foundry_request_payload(
        [ChatMessageContent(role="user", content="Hello application")],
        metadata,
        stream=True,
    )

    for payload in (workflow_payload, new_foundry_payload):
        payload_metadata = payload["metadata"]
        assert payload_metadata["conversation_id"] == "simplechat-conversation-id"
        assert "active_group_ids" not in payload_metadata
        assert "active_public_workspace_ids" not in payload_metadata
        assert "selected_document_ids" not in payload_metadata
        assert len(payload_metadata["search_query"]) == 512
        assert payload_metadata["search_query"].endswith("...")


def test_foundry_workflow_file_part_uses_data_uri_input_file():
    """Validate attached files are encoded in the workflow-compatible input_file shape."""
    file_part = _build_foundry_file_input_part(
        file_name="image.png",
        file_bytes=b"sample-image-bytes",
        content_type="image/png",
    )

    assert file_part == {
        "type": "input_file",
        "filename": "image.png",
        "file_data": "data:image/png;base64,c2FtcGxlLWltYWdlLWJ5dGVz",
    }


def test_foundry_workflow_payload_embeds_file_inputs_as_message_content():
    """Validate file inputs are sent beside text content without changing text-only payloads."""
    text_only_payload = _build_foundry_workflow_request_payload(
        [ChatMessageContent(role="user", content="Hello workflow")],
        {},
        workflow_name="ExampleWorkflow",
        stream=True,
    )
    assert isinstance(text_only_payload["input"], str)

    file_part = _build_foundry_file_input_part(
        file_name="document.pdf",
        file_bytes=b"pdf-bytes",
        content_type="application/pdf",
    )
    payload = _build_foundry_workflow_request_payload(
        [ChatMessageContent(role="user", content="Read this file")],
        {},
        workflow_name="ExampleWorkflow",
        stream=True,
        file_inputs=[file_part],
    )

    assert isinstance(payload["input"], list)
    assert payload["input"][0]["type"] == "message"
    assert payload["input"][0]["role"] == "user"
    content = payload["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "Read this file" in content[0]["text"]
    assert content[1] == file_part


def test_foundry_workflow_payload_duplicates_upload_context_for_user_request():
    """Validate uploaded file context is sent as clean one-shot workflow text."""
    upload_context = (
        "[User uploaded an image named 'image.png'.]\n\n"
        "Extracted Text (OCR):\nFig. 1\n118\n117\n\n"
        "AI Vision Analysis:\n"
        "Description: Exploded-view mechanical assembly with rings, flanges, and fasteners.\n"
        "Objects detected: central housing, rings, numbered callouts\n\n"
        "Use this image information to answer questions about the uploaded image."
    )
    file_part = _build_foundry_file_input_part(
        file_name="image.png",
        file_bytes=b"sample-image-bytes",
        content_type="image/png",
    )
    payload = _build_foundry_workflow_request_payload(
        [
            ChatMessageContent(role="system", content=upload_context),
            ChatMessageContent(
                role="user",
                content=(
                    "okay, lets work on DEMO-PA-021, evaluate the file ive uploaded for prior art. "
                    "The assembly allows polymer to pass through the barrier."
                ),
            ),
        ],
        {},
        workflow_name="ExampleWorkflow",
        stream=True,
        file_inputs=[file_part],
    )

    text = payload["input"][0]["content"][0]["text"]
    assert "Attached file searchable summary" in text
    assert "User request" in text
    assert "Uploaded image image.png searchable summary" in text
    assert "SYSTEM:" not in text
    assert text.count("Exploded-view mechanical assembly") == 1
    assert "file ive uploaded" not in text
    assert "attached file searchable summary" in text.lower()
    assert "Run the prior art search for DEMO-PA-021" in text
    assert text.rfind("Attached file searchable summary") < text.rfind("Run the prior art search")


def test_new_foundry_payload_embeds_file_inputs_on_latest_user_message():
    """Validate normal Foundry Responses agents receive file inputs with user text."""
    file_part = _build_foundry_file_input_part(
        file_name="image.png",
        file_bytes=b"sample-image-bytes",
        content_type="image/png",
    )
    payload = _build_new_foundry_request_payload(
        [
            ChatMessageContent(role="user", content="Remember the first instruction."),
            ChatMessageContent(role="user", content="Analyze this image"),
        ],
        {},
        stream=True,
        file_inputs=[file_part],
    )

    assert len(payload["input"][0]["content"]) == 1
    assert payload["input"][1]["role"] == "user"
    assert payload["input"][1]["content"][0]["type"] == "input_text"
    assert payload["input"][1]["content"][1] == file_part


def test_new_foundry_payload_duplicates_upload_context_on_latest_user_message():
    """Validate normal Foundry Responses agents get upload context in user text."""
    upload_context = (
        "[User uploaded a file named 'spec.txt'. Content preview:\n"
        "A polymer passes through a coated barrier ring assembly.]\n"
        "Use this file context if relevant."
    )
    file_part = _build_foundry_file_input_part(
        file_name="spec.txt",
        file_bytes=b"A polymer passes through a coated barrier ring assembly.",
        content_type="text/plain",
    )
    payload = _build_new_foundry_request_payload(
        [
            ChatMessageContent(role="system", content=upload_context),
            ChatMessageContent(role="user", content="Run the prior art search."),
        ],
        {},
        stream=True,
        file_inputs=[file_part],
    )

    latest_user_text = payload["input"][1]["content"][0]["text"]
    assert "Attached file searchable summary" in latest_user_text
    assert "Original user request" in latest_user_text
    assert "Uploaded file spec.txt searchable content preview" in latest_user_text
    assert "A polymer passes through a coated barrier ring assembly" in latest_user_text
    assert len(payload["input"][0]["content"]) == 1


def test_foundry_stream_failed_event_extracts_response_error_message():
    """Validate stream failures surface the Foundry response error message."""
    message = "Unhandled workflow failure - #plan_drone_mission (InvokeAzureAgent) -> Unsupported element type: List`1"
    event_payload = {
        "type": "response.failed",
        "response": {
            "id": "wfresp_test",
            "status": "failed",
            "error": {
                "code": "invalid_operation_error",
                "message": message,
            },
        },
    }

    extracted = _extract_new_foundry_event_error(event_payload)
    assert "invalid_operation_error" in extracted
    assert message in extracted
    assert "response.failed" not in extracted


def test_foundry_workflow_done_text_replaces_early_outline_deltas():
    """Validate final workflow text wins over early outline-style deltas."""
    state = NewFoundryStreamState()
    state.text_parts.extend([
        "# USPTO Case Portfolio Status\n",
        "## Executive Summary\n",
        "## Case Status\n",
    ])
    final_text = (
        "# USPTO Case Portfolio Status\n"
        "## Executive Summary\n"
        "There are **50 visible cases** in the portfolio.\n\n"
        "## Case Status\n"
        "| Status | Case Count |\n|---|---:|\n| ready | 5 |"
    )

    _update_new_foundry_stream_state(
        state=state,
        event_payload={"type": "response.output_text.done", "text": final_text},
        application_name="USPTOCasePortfolioStatus",
    )

    assert _extract_new_foundry_stream_text(state) == final_text


if __name__ == "__main__":
    test_foundry_workflow_agent_payload_normalizes_and_validates()
    test_foundry_workflow_agent_requires_endpoint()
    test_foundry_workflow_agent_rejects_invalid_context_limit()
    test_foundry_workflow_endpoint_survives_custom_endpoint_stripping()
    test_foundry_workflow_versions_use_protocol_path_without_api_version_query()
    test_foundry_workflow_rest_protocol_normalizes_saved_v2_to_v1()
    test_foundry_workflow_builds_matching_conversation_endpoints()
    test_foundry_workflow_payload_keeps_simplechat_conversation_in_metadata_only()
    test_foundry_workflow_payload_uses_discovered_agent_reference()
    try:
        import pytest
        from _pytest.monkeypatch import MonkeyPatch
        monkeypatch = MonkeyPatch()
        test_foundry_workflow_listing_normalizes_agents_as_workflows(monkeypatch)
        test_foundry_workflow_api_key_agent_is_rejected(monkeypatch)
        monkeypatch.undo()
    except ImportError:
        print("Skipping monkeypatch-based workflow listing test because pytest is unavailable.")
    test_foundry_payload_metadata_omits_internal_scope_lists_and_caps_values()
    test_foundry_workflow_file_part_uses_data_uri_input_file()
    test_foundry_workflow_payload_embeds_file_inputs_as_message_content()
    test_foundry_workflow_payload_duplicates_upload_context_for_user_request()
    test_new_foundry_payload_embeds_file_inputs_on_latest_user_message()
    test_new_foundry_payload_duplicates_upload_context_on_latest_user_message()
    test_foundry_stream_failed_event_extracts_response_error_message()
    test_foundry_workflow_done_text_replaces_early_outline_deltas()
    print("Foundry workflow agent payload tests passed.")
