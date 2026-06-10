# test_conversation_summary_model_endpoint_protocol.py
#!/usr/bin/env python3
"""
Functional test for conversation summary model endpoint protocol routing.
Version: 0.241.182
Implemented in: 0.241.182

This test ensures export summary intros and Chat Details summary generation can
resolve Claude deployments from configured model endpoints and build the
Anthropic messages adapter instead of the legacy Azure OpenAI client.
"""

import ast
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicChatCompletionClient,
    build_anthropic_chat_client,
    build_openai_style_chat_client,
    infer_model_endpoint_protocol,
)


PROJECT_ENDPOINT = "https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev"
EXPECTED_ANTHROPIC_MESSAGES_ENDPOINT = "https://eastus2.services.ai.azure.com/anthropic/v1/messages"
SUMMARY_HELPER_NAMES = {
    "_normalize_summary_model_value",
    "_append_summary_endpoint_candidates",
    "_get_summary_model_endpoint_candidates",
    "_summary_model_matches",
    "_find_summary_endpoint_model",
    "_resolve_summary_foundry_scope_for_auth",
    "_build_summary_model_endpoint_client",
    "_resolve_summary_multi_endpoint_client",
    "_initialize_gpt_client",
}


def normalize_model_endpoints_for_test(endpoints):
    """Minimal endpoint normalizer for summary helper tests."""
    normalized = []
    for endpoint in endpoints or []:
        if not isinstance(endpoint, dict):
            continue
        endpoint_copy = copy.deepcopy(endpoint)
        connection = endpoint_copy.get("connection") or {}
        endpoint_copy.setdefault("id", endpoint_copy.get("name") or connection.get("endpoint") or "")
        endpoint_copy.setdefault("enabled", True)

        normalized_models = []
        for model in endpoint_copy.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            model_copy = copy.deepcopy(model)
            model_copy.setdefault(
                "id",
                model_copy.get("deploymentName")
                or model_copy.get("deployment")
                or model_copy.get("modelName")
                or model_copy.get("name")
                or "",
            )
            model_copy.setdefault("enabled", True)
            normalized_models.append(model_copy)
        endpoint_copy["models"] = normalized_models
        normalized.append(endpoint_copy)
    return normalized, False


def load_summary_helpers():
    """Load the route summary helpers without importing the full app dependency graph."""
    export_source_path = APP_DIR / "route_backend_conversation_export.py"
    export_tree = ast.parse(export_source_path.read_text(encoding="utf-8"))
    selected_nodes = [
        node for node in export_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in SUMMARY_HELPER_NAMES
    ]
    loaded_names = {node.name for node in selected_nodes}
    missing_names = SUMMARY_HELPER_NAMES - loaded_names
    if missing_names:
        raise AssertionError(f"Missing summary helper functions: {sorted(missing_names)}")

    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(helper_module)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE": MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        "AzureOpenAI": object,
        "ClientSecretCredential": object,
        "DefaultAzureCredential": object,
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "build_anthropic_chat_client": build_anthropic_chat_client,
        "build_openai_style_chat_client": build_openai_style_chat_client,
        "cognitive_services_scope": "https://cognitiveservices.azure.com/.default",
        "debug_print": lambda *args, **kwargs: None,
        "get_bearer_token_provider": lambda *args, **kwargs: None,
        "get_group_model_endpoints": lambda group_id: [],
        "get_user_groups": lambda user_id: [],
        "get_user_settings": lambda user_id: {"settings": {}},
        "infer_model_endpoint_protocol": infer_model_endpoint_protocol,
        "keyvault_model_endpoint_get_helper": lambda endpoint, *args, **kwargs: endpoint,
        "normalize_model_endpoints": normalize_model_endpoints_for_test,
        "resolve_authority": lambda auth_settings: None,
    }
    exec(compile(helper_module, export_source_path, "exec"), namespace)
    return namespace


def build_claude_endpoint(endpoint_id="summary-claude-endpoint"):
    """Build a configured Claude model endpoint without any live Azure dependency."""
    return {
        "id": endpoint_id,
        "name": "Summary Claude Endpoint",
        "provider": "new_foundry",
        "enabled": True,
        "connection": {
            "endpoint": PROJECT_ENDPOINT,
            "openai_api_version": "v1",
        },
        "auth": {
            "type": "api_key",
            "api_key": "fake-summary-key",
        },
        "models": [
            {
                "id": "claude-opus-4-8",
                "deploymentName": "claude-opus-4-8",
                "modelName": "Claude Opus 4.8",
                "enabled": True,
            }
        ],
    }


def build_settings(endpoints=None, allow_user_custom_endpoints=False):
    """Build summary resolver settings for protocol tests."""
    return {
        "enable_multi_model_endpoints": True,
        "allow_user_custom_endpoints": allow_user_custom_endpoints,
        "allow_group_custom_endpoints": False,
        "enable_group_workspaces": False,
        "model_endpoints": endpoints or [],
    }


def assert_anthropic_client(client, description):
    """Validate that the resolved client is the Anthropic adapter."""
    if not isinstance(client, AnthropicChatCompletionClient):
        raise AssertionError(f"{description}: expected AnthropicChatCompletionClient, got {type(client).__name__}")
    if client.endpoint != EXPECTED_ANTHROPIC_MESSAGES_ENDPOINT:
        raise AssertionError(f"{description}: expected {EXPECTED_ANTHROPIC_MESSAGES_ENDPOINT}, got {client.endpoint}")


def test_summary_resolves_explicit_claude_endpoint():
    """Explicit summary endpoint metadata should resolve Claude as Anthropic."""
    print("Testing explicit Claude summary endpoint resolution...")
    helpers = load_summary_helpers()

    settings = build_settings([build_claude_endpoint()])
    client, deployment = helpers["_initialize_gpt_client"](
        settings,
        "claude-opus-4-8",
        user_id="summary-user",
        requested_endpoint_id="summary-claude-endpoint",
        requested_model_id="claude-opus-4-8",
        requested_provider="new_foundry",
    )

    assert_anthropic_client(client, "explicit endpoint")
    if deployment != "claude-opus-4-8":
        raise AssertionError(f"Expected Claude deployment name, got {deployment}")

    print("  Explicit Claude summary endpoint resolution passed.")
    return True


def test_summary_matches_global_claude_deployment_without_endpoint_id():
    """Deployment-only summary requests should still match configured global endpoints."""
    print("Testing deployment-only Claude summary endpoint resolution...")
    helpers = load_summary_helpers()

    settings = build_settings([build_claude_endpoint()])
    client, deployment = helpers["_initialize_gpt_client"](
        settings,
        "claude-opus-4-8",
        user_id="summary-user",
    )

    assert_anthropic_client(client, "deployment-only global endpoint")
    if deployment != "claude-opus-4-8":
        raise AssertionError(f"Expected Claude deployment name, got {deployment}")

    print("  Deployment-only Claude summary endpoint resolution passed.")
    return True


def test_summary_matches_personal_claude_deployment_for_user():
    """Deployment-only summary requests should match personal endpoints when a user is available."""
    print("Testing personal Claude summary endpoint resolution...")
    helpers = load_summary_helpers()
    helpers["get_user_settings"] = lambda user_id: {
        "settings": {
            "personal_model_endpoints": [build_claude_endpoint("personal-summary-claude")]
        }
    }
    settings = build_settings([], allow_user_custom_endpoints=True)
    client, deployment = helpers["_initialize_gpt_client"](
        settings,
        "claude-opus-4-8",
        user_id="summary-user",
    )

    assert_anthropic_client(client, "deployment-only personal endpoint")
    if deployment != "claude-opus-4-8":
        raise AssertionError(f"Expected Claude deployment name, got {deployment}")

    print("  Personal Claude summary endpoint resolution passed.")
    return True


def test_summary_frontend_sends_endpoint_metadata():
    """Export and Chat Details summary requests should include endpoint metadata fields."""
    print("Testing summary frontend request payload metadata...")
    chat_export_source = (APP_DIR / "static" / "js" / "chat" / "chat-export.js").read_text(encoding="utf-8")
    conversation_details_source = (
        APP_DIR / "static" / "js" / "chat" / "chat-conversation-details.js"
    ).read_text(encoding="utf-8")

    required_export_fragments = [
        "summary_model_endpoint_id",
        "summary_model_id",
        "summary_model_provider",
    ]
    missing_export_fragments = [fragment for fragment in required_export_fragments if fragment not in chat_export_source]
    if missing_export_fragments:
        raise AssertionError(f"Export summary payload is missing: {missing_export_fragments}")

    required_details_fragments = [
        "model_endpoint_id: modelEndpointId",
        "model_id: modelId",
        "model_provider: modelProvider",
    ]
    missing_details_fragments = [fragment for fragment in required_details_fragments if fragment not in conversation_details_source]
    if missing_details_fragments:
        raise AssertionError(f"Chat Details summary payload is missing: {missing_details_fragments}")

    print("  Summary frontend payload metadata checks passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_summary_resolves_explicit_claude_endpoint,
        test_summary_matches_global_claude_deployment_without_endpoint_id,
        test_summary_matches_personal_claude_deployment_for_user,
        test_summary_frontend_sends_endpoint_metadata,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print("=" * 60)
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"ERROR: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    raise SystemExit(0 if all(results) else 1)