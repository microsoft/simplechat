# test_analyze_compare_claude_workflow_stream.py
#!/usr/bin/env python3
"""
Functional test for Analyze/Compare Claude workflow stream support.
Version: 0.261.045
Implemented in: 0.241.193; workflow runtime fixtures and authorization coverage updated in 0.261.045

This test ensures chat and workflow document actions can resolve Claude model
endpoints through the Anthropic adapter and that Anthropic stream responses are
parsed without failing on SSE framing or final usage-only chunks.
"""

import ast
import copy
import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_support.versioning import assert_app_version_at_least
from test_custom_model_endpoint_provider import load_model_endpoint_runtime_module, _restore_modules


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
WORKFLOW_RUNNER = APP_DIR / "functions_workflow_runner.py"
CHAT_ROUTE = APP_DIR / "route_backend_chats.py"
CONFIG = APP_DIR / "config.py"
sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicChatCompletionClient,
    OpenAIStyleChatCompletionClient,
    build_anthropic_chat_client,
    build_openai_style_chat_client,
    infer_model_endpoint_protocol,
)
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model
from functions_model_endpoint_urls import resolve_model_endpoint_route, routing_schema_version


PROJECT_ENDPOINT = "https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev"
EXPECTED_ANTHROPIC_MESSAGES_ENDPOINT = "https://eastus2.services.ai.azure.com/anthropic/v1/messages"


def assert_equal(actual, expected, description):
    """Assert equality with a useful failure message."""
    if actual != expected:
        raise AssertionError(f"{description}: expected {expected!r}, got {actual!r}")


def load_workflow_helpers(function_names):
    """Load selected workflow helper functions without importing the full app."""
    source = WORKFLOW_RUNNER.read_text(encoding="utf-8")
    module_tree = ast.parse(source, filename=str(WORKFLOW_RUNNER))
    selected_nodes = [
        node for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    missing = set(function_names) - {node.name for node in selected_nodes}
    if missing:
        raise AssertionError(f"Missing workflow helper functions: {sorted(missing)}")

    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(helper_module)
    namespace = {
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE": MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        "AzureOpenAI": object,
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "build_anthropic_chat_client": build_anthropic_chat_client,
        "build_openai_style_chat_client": build_openai_style_chat_client,
        "cognitive_services_scope": "https://cognitiveservices.azure.com/.default",
        "get_group_model_endpoints": lambda group_id: [],
        "get_user_settings": lambda user_id: {"settings": {}},
        "assert_group_role": lambda *_args, **_kwargs: "User",
        "ensure_governance_access": lambda *_args, **_kwargs: None,
        "infer_model_endpoint_protocol": infer_model_endpoint_protocol,
        "routing_schema_version": routing_schema_version,
        "get_model_endpoint_api_type": get_model_endpoint_api_type,
        "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
        "keyvault_model_endpoint_get_helper": lambda endpoint, *args, **kwargs: endpoint,
        "normalize_model_endpoints": lambda endpoints: (list(endpoints or []), False),
    }
    runtime, original_modules = load_model_endpoint_runtime_module()
    try:
        namespace["build_model_endpoint_sync_chat_client"] = runtime.build_model_endpoint_sync_chat_client
    finally:
        _restore_modules(original_modules)
    exec(compile(helper_module, WORKFLOW_RUNNER, "exec"), namespace)
    return namespace


def build_endpoint(endpoint_id, model_id, provider="new_foundry"):
    """Build a fake configured model endpoint."""
    return {
        "id": endpoint_id,
        "name": endpoint_id,
        "provider": provider,
        "enabled": True,
        "connection": {
            "endpoint": PROJECT_ENDPOINT,
            "openai_api_version": "v1",
        },
        "auth": {
            "type": "api_key",
            "api_key": "fake-key",
        },
        "models": [
            {
                "id": model_id,
                "deploymentName": model_id,
                "modelName": model_id,
                "enabled": True,
            }
        ],
    }


class FakeAnthropicStreamResponse:
    """Minimal requests.Response stand-in for Anthropic SSE parsing."""

    status_code = 200

    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        for line in self.lines:
            yield line

    def close(self):
        self.closed = True


def test_workflow_resolves_claude_endpoint_to_anthropic_client():
    """Validate workflow document actions use the Anthropic adapter for Claude endpoints."""
    helpers = load_workflow_helpers({"_build_multi_endpoint_client"})
    client, deployment_name, provider = helpers["_build_multi_endpoint_client"](
        "user-1",
        "workflow-claude",
        "claude-sonnet-4",
        {
            "model_endpoints": [build_endpoint("workflow-claude", "claude-sonnet-4")],
            "allow_user_custom_endpoints": False,
            "allow_group_custom_endpoints": False,
            "azure_openai_gpt_api_version": "2024-10-01-preview",
        },
    )

    if not isinstance(client, AnthropicChatCompletionClient):
        raise AssertionError(f"Expected AnthropicChatCompletionClient, got {type(client).__name__}")
    assert_equal(client.endpoint, EXPECTED_ANTHROPIC_MESSAGES_ENDPOINT, "Anthropic endpoint")
    assert_equal(deployment_name, "claude-sonnet-4", "Claude deployment name")
    assert_equal(provider, "new_foundry", "Claude provider")


def test_workflow_resolves_non_claude_foundry_endpoint_to_openai_style_client():
    """Validate the same workflow resolver keeps non-Claude Foundry endpoints functional."""
    helpers = load_workflow_helpers({"_build_multi_endpoint_client"})
    client, deployment_name, provider = helpers["_build_multi_endpoint_client"](
        "user-1",
        "workflow-gpt",
        "gpt-4.1",
        {
            "model_endpoints": [build_endpoint("workflow-gpt", "gpt-4.1")],
            "allow_user_custom_endpoints": False,
            "allow_group_custom_endpoints": False,
            "azure_openai_gpt_api_version": "2024-10-01-preview",
        },
    )

    if not isinstance(client, OpenAIStyleChatCompletionClient):
        raise AssertionError(f"Expected OpenAIStyleChatCompletionClient, got {type(client).__name__}")
    assert_equal(deployment_name, "gpt-4.1", "OpenAI-style deployment name")
    assert_equal(provider, "new_foundry", "OpenAI-style provider")


@pytest.mark.parametrize("scope", ("global", "user", "group"))
@pytest.mark.parametrize("denied_at", ("feature", "item"))
def test_workflow_policy_denial_precedes_storage_and_credentials(scope, denied_at):
    helpers = load_workflow_helpers({"_build_multi_endpoint_client"})
    events = []

    def governance(feature, user_id, **kwargs):
        events.append((feature, user_id, kwargs))
        if feature == f"governance_{scope}_endpoints":
            if denied_at == "feature" or kwargs.get("item_id") == "saved-endpoint":
                raise PermissionError("Denied by current policy")

    forbidden = Mock(side_effect=AssertionError("Denied endpoint must not be read or used"))
    helpers.update({
        "ensure_governance_access": governance,
        "get_group_model_endpoints": forbidden,
        "get_user_settings": forbidden,
        "keyvault_model_endpoint_get_helper": forbidden,
        "build_model_endpoint_sync_chat_client": forbidden,
    })
    settings = {
        "enable_multi_model_endpoints": True,
        "allow_user_custom_endpoints": scope == "user",
        "allow_group_custom_endpoints": scope == "group",
        "model_endpoints": [build_endpoint("saved-endpoint", "model")] if scope == "global" else [],
    }
    with pytest.raises((ValueError, PermissionError)):
        helpers["_build_multi_endpoint_client"](
            "actor", "saved-endpoint", "model", settings,
            group_id="group-one" if scope == "group" else None,
        )
    forbidden.assert_not_called()
    assert events


def test_workflow_revoked_membership_precedes_group_endpoint_read():
    helpers = load_workflow_helpers({"_build_multi_endpoint_client"})
    forbidden = Mock(side_effect=AssertionError("Revoked group must not be read"))
    helpers["assert_group_role"] = Mock(side_effect=PermissionError("Revoked membership"))
    helpers["get_group_model_endpoints"] = forbidden
    with pytest.raises((PermissionError, ValueError)):
        helpers["_build_multi_endpoint_client"](
            "actor", "saved-endpoint", "model",
            {"enable_multi_model_endpoints": True, "allow_group_custom_endpoints": True},
            group_id="group-one",
        )
    forbidden.assert_not_called()


@pytest.mark.parametrize("scope", ("global", "user", "group"))
def test_workflow_explicit_route_uses_fresh_selection_and_safe_context(scope):
    helpers = load_workflow_helpers({"_build_multi_endpoint_client"})
    endpoint = {
        "id": "saved-endpoint", "provider": "custom", "enabled": True,
        "routing_schema_version": 2,
        "connection": {"endpoint": "https://gateway.example/shared/v1"},
        "models": [{
            "id": "model", "api_type": "openai", "modelName": "saved-model",
            "url_mode": "auto", "api_path": "before", "enabled": True,
        }],
    }
    updated = copy.deepcopy(endpoint)
    updated["models"][0].update(api_path="fresh", modelName="current-model")
    updated["auth"] = {"type": "api_key", "api_key": "test-only-secret"}
    updated["_resolved_route"] = resolve_model_endpoint_route(updated, updated["models"][0])
    resolve_context = Mock(return_value=updated)
    build_client = Mock(return_value=(object(), "openai_style"))
    helpers.update({
        "get_user_settings": lambda _user: {"settings": {"personal_model_endpoints": [endpoint]}},
        "get_group_model_endpoints": lambda _group: [endpoint],
        "resolve_model_endpoint_from_context": resolve_context,
        "build_model_endpoint_sync_chat_client": build_client,
        "keyvault_model_endpoint_get_helper": Mock(side_effect=AssertionError("Use authorized resolution")),
    })
    settings = {
        "enable_multi_model_endpoints": True,
        "allow_user_custom_endpoints": scope == "user",
        "allow_group_custom_endpoints": scope == "group",
        "model_endpoints": [endpoint] if scope == "global" else [],
    }
    result = helpers["_build_multi_endpoint_client"](
        "actor", "saved-endpoint", "model", settings,
        group_id="group-one" if scope == "group" else None, include_context=True,
    )
    expected_context = {
        "routing_schema_version": 2, "scope_type": scope,
        "scope_id": {"global": "global", "user": "actor", "group": "group-one"}[scope],
        "endpoint_id": "saved-endpoint", "model_id": "model",
    }
    resolve_context.assert_called_once_with(settings, {**expected_context, "user_id": "actor"})
    assert result[1:] == ("current-model", "custom", expected_context)
    build_client.assert_not_called()
    direct_result = helpers["_build_multi_endpoint_client"](
        "actor", "saved-endpoint", "model", settings,
        group_id="group-one" if scope == "group" else None,
    )
    assert len(direct_result) == 3
    assert build_client.call_args.kwargs["resolved_route"] == updated["_resolved_route"]
    assert "test-only-secret" not in json.dumps(result[3])


def test_anthropic_stream_parser_handles_sse_bytes_and_usage_chunk():
    """Validate Anthropic streaming chunks parse text, usage, and byte lines."""
    client = AnthropicChatCompletionClient(endpoint=PROJECT_ENDPOINT, api_key="fake-key")
    headers = client._build_headers(stream=True)
    assert_equal(headers["Accept"], "text/event-stream", "stream Accept header")
    assert_equal(client._build_headers()["Accept"], "application/json", "non-stream Accept header")

    response = FakeAnthropicStreamResponse([
        b"event: message_start",
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":12}}}',
        b"event: content_block_delta",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}',
        b'data: {"type":"message_delta","usage":{"output_tokens":3}}',
        b'data: {"type":"message_stop"}',
    ])

    chunks = list(client._iter_stream_chunks(response))
    content = "".join(
        chunk.choices[0].delta.content
        for chunk in chunks
        if getattr(chunk, "choices", None)
    )
    usage = chunks[-1].usage

    assert_equal(content, "Hello", "streamed content")
    assert_equal(usage.prompt_tokens, 12, "stream prompt tokens")
    assert_equal(usage.completion_tokens, 3, "stream completion tokens")
    assert_equal(usage.total_tokens, 15, "stream total tokens")
    assert_equal(response.closed, True, "stream response closed")


def test_anthropic_stream_parser_surfaces_error_events():
    """Validate Anthropic stream errors surface cleanly instead of hanging the stream."""
    client = AnthropicChatCompletionClient(endpoint=PROJECT_ENDPOINT, api_key="fake-key")
    response = FakeAnthropicStreamResponse([
        "data: " + json.dumps({
            "type": "error",
            "error": {
                "type": "overloaded_error",
                "message": "provider is overloaded",
            },
        }),
    ])

    try:
        list(client._iter_stream_chunks(response))
    except RuntimeError as exc:
        if "provider is overloaded" not in str(exc):
            raise AssertionError(f"Unexpected stream error message: {exc}") from exc
    else:
        raise AssertionError("Expected RuntimeError for Anthropic stream error event")
    assert_equal(response.closed, True, "error stream response closed")


def test_chat_document_action_stream_uses_workflow_executor():
    """Validate the chat Analyze/Compare stream path still uses workflow execution."""
    route_text = CHAT_ROUTE.read_text(encoding="utf-8")
    required_markers = [
        "@bp.route('/api/chat/document-action/stream', methods=['POST'])",
        "@bp.route('/api/chat/analyze/stream', methods=['POST'])",
        "from functions_workflow_runner import _execute_document_action_workflow",
        "execution_result = _execute_document_action_workflow(",
    ]
    for marker in required_markers:
        if marker not in route_text:
            raise AssertionError(f"Missing chat document-action stream marker: {marker}")


def test_version_bumped_for_fix():
    """Validate config.py version was bumped for this fix."""
    assert_app_version_at_least("0.241.193")


def main():
    """Run all checks."""
    tests = [
        test_workflow_resolves_claude_endpoint_to_anthropic_client,
        test_workflow_resolves_non_claude_foundry_endpoint_to_openai_style_client,
        test_anthropic_stream_parser_handles_sse_bytes_and_usage_chunk,
        test_anthropic_stream_parser_surfaces_error_events,
        test_chat_document_action_stream_uses_workflow_executor,
        test_version_bumped_for_fix,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)