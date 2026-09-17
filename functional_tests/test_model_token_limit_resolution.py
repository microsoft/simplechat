# test_model_token_limit_resolution.py
"""
Functional tests for the workflow/model-budget integration contract.
Version: 0.261.122
Implemented in: 0.261.106

Workflow callers use the audited ModelTokenBudget API without replacing the
existing tuple helper or reviving older nested tokenLimits annotations. These
offline tests cover actual catalog identities, independent ceilings, scoped
profiles, explicit configuration, and separation from request response length.
"""

import copy
import importlib.util
import sys
import unittest
from collections import UserDict
from pathlib import Path
from types import MappingProxyType, SimpleNamespace


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


class ModelTokenLimitResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "workflow_token_limit_test_subject", APP_ROOT / "functions_model_capabilities.py",
        )
        cls.capabilities = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.capabilities
        spec.loader.exec_module(cls.capabilities)
        cls.capabilities.load_model_capability_catalog(force_refresh=True)

    def resolve(self, model, endpoint=None, **kwargs):
        return self.capabilities.resolve_model_token_budget(model, endpoint, **kwargs)

    def test_existing_tuple_api_and_output_helper_are_preserved(self):
        for model in ("gpt-5.6-sol", "gpt-5.5", "claude-haiku-4-5", "private-model"):
            with self.subTest(model=model):
                budget = self.resolve(model)
                bounds = [
                    value for value in (
                        budget.context_window, budget.input_limit, budget.effective_context_window,
                    ) if value is not None
                ]
                self.assertEqual(
                    self.capabilities.resolve_model_token_limits(model),
                    (min(bounds) if bounds else None, budget.output_limit),
                )
                self.assertEqual(
                    self.capabilities.resolve_model_output_token_limit(model, default=4096),
                    budget.output_limit or 4096,
                )
        self.assertEqual(
            self.capabilities.resolve_model_token_limits(
                "gpt-5.6-sol", {"contextWindow": 8192, "outputTokenLimit": 1024},
            ),
            (8192, 1024),
        )

    def test_shared_context_and_independent_input_are_not_interchanged(self):
        direct = self.resolve("gpt-5.5", provider="openai")
        azure = self.resolve("gpt-5.5", provider="aoai")
        responses = self.resolve("gpt-5.5", provider="aoai", protocol="responses")
        self.assertEqual(direct.context_window, 1050000)
        self.assertIsNone(direct.input_limit)
        self.assertEqual((azure.context_window, azure.input_limit), (1050000, 922000))
        self.assertEqual(azure.output_limit, 128000)
        self.assertIsNone(azure.effective_context_window)
        self.assertEqual(responses.effective_context_window, 922000)
        self.assertEqual(responses.with_request_limit(1000).remaining_input(), 921000)

    def test_verified_model_metadata_has_explicit_capacity_provenance(self):
        budget = self.resolve("gpt-5.6-sol")
        self.assertEqual(
            (budget.context_window, budget.input_limit, budget.output_limit),
            (1050000, 922000, 128000),
        )
        self.assertEqual(budget.output_accounting, "total_generation")
        self.assertEqual(dict(budget.provenance), {
            "contextWindow": "catalog",
            "inputTokenLimit": "catalog",
            "outputTokenLimit": "catalog",
        })
        self.assertEqual(self.resolve("claude-haiku-4-5").context_window, 200000)

    def test_actual_identity_precedes_deployment_and_ui_identifiers(self):
        record = {
            "id": "gpt-5.5", "model_id": "gpt-5.5", "displayName": "GPT-5.5",
            "modelName": "gpt-5.6-sol", "deploymentName": "gpt-5.5",
        }
        self.assertEqual(self.resolve(record), self.resolve("gpt-5.6-sol"))
        record["modelName"] = "private-model"
        self.assertIsNone(self.resolve(record).context_window)
        for field in ("id", "model_id", "modelId", "displayName", "display_name"):
            with self.subTest(field=field):
                self.assertIsNone(self.resolve({field: "gpt-5.6-sol"}).context_window)

    def test_authorized_catalog_mapping_and_existing_record_shapes(self):
        for field in ("modelName", "deploymentName", "deployment", "name"):
            for factory in (dict, UserDict, MappingProxyType):
                with self.subTest(field=field, factory=factory.__name__):
                    self.assertEqual(
                        self.resolve(factory({field: "gpt-5.6-sol"})),
                        self.resolve("gpt-5.6-sol"),
                    )
            self.assertEqual(
                self.resolve(SimpleNamespace(**{field: "gpt-5.6-sol"})),
                self.resolve("gpt-5.6-sol"),
            )
        self.assertEqual(
            self.resolve({"catalogModelId": "gpt-5.6-sol", "deploymentName": "private"}),
            self.resolve("gpt-5.6-sol"),
        )

    def test_only_verified_aliases_receive_numeric_limits(self):
        for alias in ("GPT 5.6 SOL", "gpt_5_6_sol", "gpt-5.6"):
            self.assertEqual(self.resolve(alias), self.resolve("gpt-5.6-sol"))
        self.assertEqual(
            self.resolve("gpt-5.5-2026-04-23").context_window,
            self.resolve("gpt-5.5").context_window,
        )
        for name in (
            "gpt-5.6-sol-prod", "gpt-5.6-sol-2030-01-01", "gpt-5.6-sol-transcribe",
            "gpt-5.99", "private-model",
        ):
            with self.subTest(name=name):
                budget = self.resolve(name)
                self.assertIsNone(budget.context_window)
                self.assertIsNone(budget.input_limit)
                self.assertIsNone(budget.output_limit)

    def test_metadata_only_records_do_not_gain_old_unaudited_capacities(self):
        for record in self.capabilities.get_model_capability_catalog_records():
            if any(record.get(field) is not None for field in (
                "contextWindow", "inputTokenLimit", "outputTokenLimit",
            )) or record.get("tokenLimitProfiles"):
                continue
            with self.subTest(model=record["id"]):
                budget = self.resolve(record["id"])
                self.assertIsNone(budget.context_window)
                self.assertIsNone(budget.input_limit)
                self.assertIsNone(budget.output_limit)
        legacy = self.resolve({
            "modelName": "private-model",
            "tokenLimits": {"contextWindow": 128000, "maxOutputTokens": 16000},
        })
        self.assertIsNone(legacy.context_window)
        self.assertIsNone(legacy.output_limit)

    def test_requested_output_does_not_replace_hard_output_capacity(self):
        budget = self.resolve({
            "modelName": "gpt-5.6-sol",
            "responseLength": 1000, "maxTokens": 2000, "maxCompletionTokens": 3000,
        }, request_output_limit=1000)
        self.assertEqual(budget.output_limit, 128000)
        self.assertEqual(budget.request_output_limit, 1000)
        self.assertEqual(budget.remaining_input(), 922000)
        self.assertEqual(budget.with_request_limit(2000).output_limit, 128000)

    def test_authorized_model_and_endpoint_fields_resolve_independently(self):
        budget = self.resolve(
            {"modelName": "private-model", "inputTokenLimit": " 7000 ", "outputTokenLimit": 1000},
            {"contextWindow": 8192, "outputTokenLimit": 2000, "outputTokenAccounting": "total_generation"},
            request_output_limit=500,
        )
        self.assertEqual((budget.context_window, budget.input_limit, budget.output_limit), (8192, 7000, 1000))
        self.assertEqual(budget.remaining_input(), 7000)
        self.assertEqual(dict(budget.provenance), {
            "contextWindow": "endpoint", "inputTokenLimit": "model", "outputTokenLimit": "model",
        })

    def test_invalid_declared_limits_are_actionable_errors_not_silent_defaults(self):
        for value in (True, False, -1, 0, 1.5, 2048.0, "1e6", "128k", "128,000", [], {}):
            for field in ("contextWindow", "inputTokenLimit", "outputTokenLimit"):
                with self.subTest(value=value, field=field):
                    with self.assertRaises(self.capabilities.ModelTokenBudgetError):
                        self.resolve("gpt-5.6-sol", {field: value})

    def test_unknown_generation_accounting_is_not_inferred_from_numeric_limits(self):
        budget = self.resolve("gemini-2.5-pro", provider="google", protocol="generate_content")
        self.assertIsNone(budget.context_window)
        self.assertEqual(budget.input_limit, 1048576)
        self.assertEqual(budget.output_limit, 65536)
        self.assertEqual(budget.output_accounting, "unknown")
        with self.assertRaises(self.capabilities.ModelTokenBudgetError) as error:
            budget.with_request_limit(1000).remaining_input()
        self.assertEqual(error.exception.code, "model_generation_unbounded")

    def test_metadata_and_qualitative_capabilities_are_unchanged(self):
        model = {"modelName": "gpt-5.6-sol", "contextWindow": 200000}
        endpoint = {"outputTokenLimit": 4096}
        original_model, original_endpoint = copy.deepcopy(model), copy.deepcopy(endpoint)
        catalog = copy.deepcopy(self.capabilities.load_model_capability_catalog())
        vision = self.capabilities.resolve_model_vision_support(model)
        reasoning = self.capabilities.resolve_model_reasoning_policy(model)
        self.resolve(model, endpoint)
        self.assertEqual(model, original_model)
        self.assertEqual(endpoint, original_endpoint)
        self.assertEqual(self.capabilities.load_model_capability_catalog(), catalog)
        self.assertEqual(self.capabilities.resolve_model_vision_support(model), vision)
        self.assertEqual(self.capabilities.resolve_model_reasoning_policy(model), reasoning)


if __name__ == "__main__":
    unittest.main()
