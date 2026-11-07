# test_saved_analysis_model_metadata.py
"""
Functional tests for canonical model metadata used by saved Analyze batching.
Version: 0.261.109
Implemented in: 0.261.109

The chosen endpoint or legacy model record supplies custom token ceilings;
model display names and a second capability catalog are not used.
"""

from copy import deepcopy
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from test_support.app_stubs import import_app_module


models = import_app_module("functions_orchestration_models")
budgets = import_app_module("functions_workflow_context")


MODEL = {
    "id": "custom-model", "deploymentName": "private-deployment", "modelName": "private-model",
    "enabled": True, "responseLength": 512,
    "tokenLimits": {"contextWindow": 12000, "maxInputTokens": 11000, "maxOutputTokens": 1500},
}


def assert_custom_budget(binding):
    audit = budgets.calculate_workflow_context_budget(
        [{"role": "user", "content": "Explain the saved findings."}],
        binding.model_metadata, provider=binding.provider, output_tokens=binding.response_length,
    )
    assert audit["context_window_tokens"] == 12000
    assert audit["max_input_tokens"] == 11000
    assert audit["output_reserve_tokens"] == 512
    assert audit["limit_source"] == "configured"


def test_endpoint_model_metadata_preserves_custom_limits_without_credentials(monkeypatch):
    endpoint = {
        "id": "endpoint-1", "provider": "aoai", "enabled": True,
        "connection": {"endpoint": "https://example.test", "openai_api_version": "2025-04-01-preview"},
        "auth": {"api_key": "test-only"}, "models": [deepcopy(MODEL)],
    }
    monkeypatch.setitem(sys.modules, "functions_model_endpoint_runtime", SimpleNamespace(
        MODEL_ENDPOINT_PROVIDER_ALLOWLIST={"aoai"},
        resolve_model_endpoint_from_context=lambda *args, **kwargs: endpoint,
        build_model_endpoint_sync_chat_client=lambda *args, **kwargs: (Mock(), "azure_openai"),
    ))
    binding = models.resolve_orchestration_model(
        {"enable_multi_model_endpoints": True}, user_id="owner",
        seeds={"model": {"model_endpoint_id": "endpoint-1", "model_id": "custom-model"}},
    )
    assert binding.model_metadata == MODEL
    assert_custom_budget(binding)
    endpoint["models"][0]["tokenLimits"]["contextWindow"] = 999999
    assert binding.model_metadata == MODEL
    assert "test-only" not in str(binding.model_metadata)
    assert "tokenLimits" not in binding.metadata()


def test_legacy_selected_model_uses_the_same_custom_limits(monkeypatch):
    monkeypatch.setitem(sys.modules, "functions_orchestration_planner", SimpleNamespace(
        resolve_planner_client=lambda settings: (Mock(), "private-deployment"),
    ))
    binding = models.resolve_orchestration_model(
        {"gpt_model": {"selected": [deepcopy(MODEL)]}},
        user_id="owner", seeds={"model": {"model_deployment": "private-deployment"}},
    )
    assert binding.model_metadata == MODEL
    assert binding.response_length == 512
    assert_custom_budget(binding)
