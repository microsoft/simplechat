# test_model_token_budget_resolution.py
"""
Functional tests for separate, scoped model capacities and actual request ceilings.
Version: 0.261.035
Implemented in: 0.261.035

Uses the real dependency-light resolver and Semantic Kernel settings serializer.
No network, settings-store, or configuration bootstrap is required.
"""

from dataclasses import FrozenInstanceError
import asyncio
import json
from pathlib import Path
import sys

import pytest
import httpx
from openai import AsyncAzureOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import kernel_function


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

# Standalone execution establishes the application path before application imports.
from functions_model_capabilities import (
    ModelTokenBudget,
    ModelTokenBudgetError,
    normalize_model_budget_overrides,
    normalize_token_limit,
    project_model_budget_metadata,
    resolve_model_token_budget,
)
from functions_model_budget_runtime import prepare_model_execution_settings


def catalog_record(**changes):
    return {
        "id": "exact-model",
        "provider": "openai",
        "aliases": ["unverified-alias"],
        "verifiedAliases": ["verified-alias"],
        "contextWindow": 10000,
        "inputTokenLimit": 9000,
        "outputTokenLimit": 2000,
        "outputTokenAccounting": "total_generation",
        "tokenLimitsApplicability": "text",
        **changes,
    }


@pytest.mark.parametrize("value", [True, False, 1.0, 1.5, -1, 0, "1.5", "-1", "1e3", {}, [], 9007199254740992, "9" * 5000])
def test_invalid_limits_are_errors_not_fallbacks(value):
    with pytest.raises(ModelTokenBudgetError, match="positive whole number"):
        normalize_token_limit(value)


def test_budget_error_payload_is_actionable_without_requesting_authentication():
    error = ModelTokenBudgetError("model_context_invalid", "Response Length exceeds this model's documented output limit.")
    payload = error.payload
    assert payload == {
        "error_code": "model_context_invalid",
        "error": "Response Length exceeds this model's documented output limit.",
    }
    assert "auth_required" not in payload
    assert "consent_url" not in payload


@pytest.mark.parametrize("value, expected", [(None, None), ("", None), ("  ", None), (128000, 128000), (" 128000 ", 128000)])
def test_valid_limits_and_inheritance(value, expected):
    result = normalize_token_limit(value)
    assert result == expected


def test_partial_overrides_resolve_each_field_independently():
    budget = resolve_model_token_budget(
        {"modelName": "exact-model", "outputTokenLimit": 1500, "contextWindow": None},
        {"contextWindow": 8000},
        request_output_limit=500, catalog_records=[catalog_record()],
    )
    room = budget.remaining_input(100)
    assert (budget.context_window, budget.input_limit, budget.output_limit) == (8000, 9000, 1500)
    assert room == 7400
    assert dict(budget.provenance) == {
        "contextWindow": "endpoint", "inputTokenLimit": "catalog", "outputTokenLimit": "model",
    }


def test_requested_response_length_is_not_model_capacity():
    budget = resolve_model_token_budget(
        {"modelName": "exact-model", "responseLength": 20, "maxCompletionTokens": 30},
        request_output_limit=100, catalog_records=[catalog_record()],
    )
    room = budget.remaining_input()
    assert budget.output_limit == 2000
    assert budget.request_output_limit == 100
    assert room == 9000


@pytest.mark.parametrize("identifier", ["exact-model-eastus", "exact-model-2", "unverified-alias", "Pretty display"])
def test_numeric_resolution_never_guesses_from_names(identifier):
    record = catalog_record(displayName="Pretty display")
    budget = resolve_model_token_budget(identifier, catalog_records=[record])
    assert budget.context_window is None
    assert budget.output_limit is None


def test_explicit_catalog_mapping_overrides_deployment_label():
    budget = resolve_model_token_budget(
        {"catalogModelId": "exact-model", "deploymentName": "private-deployment", "displayName": "Different"},
        catalog_records=[catalog_record()],
    )
    alias_budget = resolve_model_token_budget("verified-alias", catalog_records=[catalog_record()])
    assert budget.model_id == alias_budget.model_id == "exact-model"
    assert budget.context_window == alias_budget.context_window == 10000


def test_provider_version_and_protocol_profiles_are_scoped():
    record = catalog_record(tokenLimitProfiles=[
        {"id": "azure", "provider": "azure", "outputTokenLimit": 1000},
        {"id": "old", "provider": "azure", "modelVersions": ["2025-01-01"], "contextWindow": 7000},
        {"id": "responses", "provider": "azure", "protocol": "responses", "effectiveContextWindow": 6000},
    ])
    direct = resolve_model_token_budget("exact-model", catalog_records=[record])
    old = resolve_model_token_budget(
        {"modelName": "exact-model", "modelVersion": "2025-01-01"},
        {"provider": "aoai"}, protocol="responses", catalog_records=[record],
    )
    new = resolve_model_token_budget(
        {"modelName": "exact-model", "modelVersion": "2026-01-01"},
        {"provider": "aoai"}, catalog_records=[record],
    )
    room = old.remaining_input()
    assert direct.output_limit == 2000
    assert old.output_limit == new.output_limit == 1000
    assert old.context_window == 7000
    assert new.context_window == 10000
    assert old.effective_context_window == 6000
    assert new.effective_context_window is None
    assert room == 5000


def test_explicit_unknown_catalog_profile_blocks_wrong_host_inheritance():
    record = catalog_record(tokenLimitProfiles=[
        {"id": "unknown-version", "provider": "azure", "contextWindow": None, "inputTokenLimit": None},
    ])
    budget = resolve_model_token_budget("exact-model", provider="azure", catalog_records=[record])
    with pytest.raises(ModelTokenBudgetError) as error:
        budget.remaining_input()
    assert error.value.code == "model_context_unavailable"


def test_equal_specificity_conflicts_do_not_silently_select_a_profile():
    record = catalog_record(tokenLimitProfiles=[
        {"id": "one", "provider": "azure", "outputTokenLimit": 1000},
        {"id": "two", "provider": "azure", "outputTokenLimit": 1500},
    ])
    with pytest.raises(ModelTokenBudgetError, match="ambiguous"):
        resolve_model_token_budget("exact-model", provider="azure", catalog_records=[record])


def test_configuration_only_context_is_not_a_verified_serving_window():
    record = catalog_record(
        inputTokenLimit=None,
        tokenLimitEvidence={"contextWindow": {"status": "configuration-only"}},
    )
    budget = resolve_model_token_budget("exact-model", catalog_records=[record])
    assert budget.context_window is None
    with pytest.raises(ModelTokenBudgetError):
        budget.remaining_input()


@pytest.mark.parametrize("used, expected", [(7999, 1), (8000, 0), (8001, 0)])
def test_shared_context_boundary(used, expected):
    budget = ModelTokenBudget(context_window=10000, output_limit=5000, request_output_limit=2000, output_accounting="total_generation")
    room = budget.remaining_input(used)
    assert room == expected


def test_independent_input_is_not_reduced_by_output():
    budget = ModelTokenBudget(input_limit=9000, output_limit=2000, request_output_limit=1000, output_accounting="total_generation")
    room = budget.remaining_input(100)
    assert room == 8900


def test_known_context_and_explicit_total_generation_work_without_inventing_output_max():
    budget = ModelTokenBudget(context_window=10000, request_output_limit=1536, output_accounting="total_generation")
    room = budget.remaining_input(4096)
    assert budget.output_limit is None
    assert room == 4368


@pytest.mark.parametrize("accounting", ["visible_only", "unknown"])
def test_visible_or_unknown_allowance_does_not_bound_reasoning(accounting):
    budget = ModelTokenBudget(context_window=10000, request_output_limit=100, output_accounting=accounting)
    with pytest.raises(ModelTokenBudgetError) as error:
        budget.remaining_input()
    assert error.value.code == "model_generation_unbounded"


@pytest.mark.parametrize("provider", ["google", "vertex", "azure", "openai", "anthropic"])
def test_unknown_models_do_not_infer_generation_accounting_from_provider_name(provider):
    model = {"modelName": "unverified-model", "contextWindow": 10000, "outputTokenLimit": 2000}
    budget = resolve_model_token_budget(model, provider=provider, catalog_records=[])
    assert budget.output_accounting == "unknown"
    assert budget.output_accounting_source == "unresolved"
    with pytest.raises(ModelTokenBudgetError) as error:
        budget.remaining_input()
    assert error.value.code == "model_generation_unbounded"
    configured = resolve_model_token_budget(
        model, {"outputTokenAccounting": "total_generation"}, provider=provider, catalog_records=[],
    )
    room = configured.remaining_input()
    assert room == 8000
    assert configured.output_accounting_source == "endpoint"


def test_non_text_model_cannot_be_used_for_file_evidence():
    budget = ModelTokenBudget(context_window=10000, output_limit=2000, output_accounting="total_generation", applicability="non-text")
    with pytest.raises(ModelTokenBudgetError, match="text-generation"):
        budget.remaining_input()


def test_budget_is_immutable_and_metadata_excludes_secrets():
    projected = project_model_budget_metadata({
        "modelName": "exact-model", "contextWindow": "10000", "auth": {"api_key": "secret"},
        "connection": {"endpoint": "private"}, "client_secret": "secret", "tools": ["untrusted"],
    })
    budget = resolve_model_token_budget(projected, catalog_records=[catalog_record()])
    assert projected == {"modelName": "exact-model", "contextWindow": 10000}
    with pytest.raises(FrozenInstanceError):
        budget.context_window = 1


def test_invalid_metadata_is_not_removed_by_safe_projection():
    with pytest.raises(ModelTokenBudgetError):
        project_model_budget_metadata({"contextWindow": 100.5})


def test_custom_model_metadata_requires_explicit_accounting():
    overrides = normalize_model_budget_overrides({
        "catalogModelId": " custom-model ", "modelVersion": " 1 ",
        "tokenLimitProvider": "custom", "outputTokenAccounting": "total_generation",
        "contextWindow": "10000", "outputTokenLimit": 2000,
    })
    budget = resolve_model_token_budget(overrides, catalog_records=[])
    room = budget.remaining_input()
    assert overrides["modelVersion"] == "1"
    assert room == 8000
    assert budget.output_accounting_source == "model"


def test_explicit_host_override_is_normalized_and_not_replaced_by_model_publisher():
    custom = resolve_model_token_budget(
        {"modelName": "exact-model", "tokenLimitProvider": " custom "},
        catalog_records=[catalog_record()],
    )
    azure = resolve_model_token_budget(
        {"modelName": "exact-model", "tokenLimitProvider": " azure "},
        catalog_records=[catalog_record()],
    )
    assert custom.provider == "custom"
    assert azure.provider == "azure"


def test_wire_settings_use_one_actual_generation_cap_and_preserve_none():
    original = OpenAIChatPromptExecutionSettings(max_tokens=999, max_completion_tokens=500)
    budget = ModelTokenBudget(
        model_id="gpt-5.6-terra", provider="azure", context_window=1050000, output_limit=128000,
        output_accounting="total_generation", tool_reasoning_efforts=("none",),
    )
    prepared, effective = prepare_model_execution_settings(original, budget, tools_enabled=True)
    serialized = prepared.prepare_settings_dict()
    assert effective.request_output_limit == 500
    assert serialized["max_completion_tokens"] == 500
    assert "max_tokens" not in serialized
    assert serialized["extra_body"]["reasoning_effort"] == "none"
    assert original.max_tokens == 999
    assert original.extra_body is None


def test_explicit_unsupported_tool_reasoning_is_not_silently_changed():
    settings = OpenAIChatPromptExecutionSettings(reasoning_effort="high")
    budget = ModelTokenBudget(provider="azure", tool_reasoning_efforts=("none",))
    with pytest.raises(ModelTokenBudgetError) as error:
        prepare_model_execution_settings(settings, budget, tools_enabled=True)
    assert error.value.code == "model_tool_configuration_invalid"


def test_deeper_analysis_limits_extra_body_and_native_fields_together():
    settings = OpenAIChatPromptExecutionSettings(
        max_tokens=5000, extra_body={"max_tokens": 3000, "unrelated": True},
    )
    budget = ModelTokenBudget(provider="anthropic", protocol="messages", context_window=200000, output_limit=64000)
    prepared, effective = prepare_model_execution_settings(settings, budget, output_limit=1536)
    assert prepared.max_tokens == effective.request_output_limit == 1536
    assert prepared.extra_body == {"unrelated": True}
    assert settings.extra_body["max_tokens"] == 3000


def test_azure_sdk_wire_payload_keeps_one_cap_and_explicit_none_with_tools():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "offline", "object": "chat.completion", "created": 0, "model": "friendly-deployment",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    class Tools:
        @kernel_function
        def search(self, query: str) -> str:
            return query

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncAzureOpenAI(
                api_key="offline", azure_endpoint="https://budget.invalid",
                api_version="2025-01-01-preview", http_client=http,
            )
            service = AzureChatCompletion(
                deployment_name="friendly-deployment", async_client=client,
            )
            kernel = Kernel()
            kernel.add_plugin(Tools(), plugin_name="files")
            settings, _budget = prepare_model_execution_settings(
                OpenAIChatPromptExecutionSettings(max_completion_tokens=1024),
                ModelTokenBudget(
                    model_id="gpt-5.6-terra", provider="azure", output_limit=128000,
                    tool_reasoning_efforts=("none",),
                ),
                tools_enabled=True,
            )
            settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
            history = ChatHistory()
            history.add_user_message("Search my files")
            result = await service.get_chat_message_contents(history, settings, kernel=kernel)
            await client.close()
            return result

    result = asyncio.run(invoke())
    assert result[0].content == "ok"
    assert len(requests) == 1
    assert requests[0]["max_completion_tokens"] == 1024
    assert requests[0]["reasoning_effort"] == "none"
    assert requests[0]["tools"][0]["function"]["name"] == "files-search"
    assert "max_tokens" not in requests[0]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
