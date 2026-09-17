# test_workflow_react_v2_integration.py
"""
Functional tests for the workflow and React V2 connection integration.
Version: 0.261.112
Implemented in: 0.261.112

The real agent configuration resolver must retain workflow budget metadata and
Custom provider routing together, in both global and per-user execution modes.
Only credential retrieval and unrelated service boundaries are replaced.
"""

import ast
import copy
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Pure application helpers follow the standalone test's module-path setup.
from functions_model_capabilities import resolve_model_token_limits
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model


@pytest.mark.parametrize("per_user_enabled", [False, True])
def test_agent_preserves_custom_routing_and_workflow_budget_metadata(per_user_enabled):
    model = {
        "id": "model", "modelName": "gpt-4.1", "deploymentName": "azure-deployment",
        "contextWindow": 8192, "maxOutputTokens": 1024, "enabled": True,
    }
    endpoint = {
        "id": "connection", "provider": "custom", "api_type": "openai", "enabled": True,
        "connection": {"endpoint": "https://gateway.example.test/v1"},
        "auth": {"type": "api_key", "api_key": "fixture-key"}, "models": [model],
    }
    agent = {
        "id": "agent", "name": "Agent", "is_global": True,
        "model_endpoint_id": endpoint["id"], "model_id": model["id"],
    }
    path = APP_ROOT / "semantic_kernel_loader.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"resolve_agent_config", "first_if_comma"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    namespace = {
        "logging": logging, "debug_print": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
        "require_model_capability": lambda *args, **kwargs: None,
        "keyvault_model_endpoint_get_helper": lambda value, *args, **kwargs: copy.deepcopy(value),
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "get_model_endpoint_api_type": get_model_endpoint_api_type,
        "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    config = namespace["resolve_agent_config"](
        agent, {"per_user_semantic_kernel": per_user_enabled, "model_endpoints": [endpoint]},
    )
    assert config["deployment"] == model["modelName"]
    assert config["api_type"] == "openai"
    assert config["model_endpoint_config"] == endpoint
    assert config["model_metadata"] == model
    limits = resolve_model_token_limits(config["model_metadata"], provider=config["model_provider"])
    assert limits["context_window_tokens"] == 8192
    assert limits["max_output_tokens"] == 1024
