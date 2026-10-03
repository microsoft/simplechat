# test_gpt6_sol_catalog_record.py
"""
Functional test for the GPT-6 Sol model catalog record.
Version: 0.261.221
Implemented in: 0.261.221

Refs #1606. GPT-6 Sol's Chat Completions function calling works only with
reasoning_effort none: OpenAI documents it, and Azure behaved the same. The
record carries the verified limits and a Chat Completions toolReasoningEfforts of
none for both providers, so an agent with tools and no effort sends none, and an
explicit other effort fails before the request instead of with a provider 400.
No test fetches documentation, initializes application services or calls a model.
"""

import json
import unittest
from itertools import product

from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings

from test_model_capability_catalog_resolution import (
    CATALOG_PATH,
    capabilities,
    load_catalog_schema_validator,
)
from test_model_catalog_token_evidence import validate_catalog_integrity
from functions_model_budget_runtime import prepare_model_execution_settings


SOL = "gpt-6-sol"
LIMITS = (1050000, 922000, 128000)
CAPACITY_FIELDS = ("contextWindow", "inputTokenLimit", "outputTokenLimit")
EFFORTS = ["none", "low", "medium", "high", "xhigh"]


class TestGpt6SolCatalogRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.models = {record["id"]: record for record in cls.catalog["models"]}
        cls.sources = {record["id"]: record for record in cls.catalog["sources"]}
        cls.record = cls.models[SOL]

    def setUp(self):
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)

    def budget(self, provider="azure", protocol="chat_completions"):
        return capabilities.resolve_model_token_budget(
            {"modelName": SOL}, provider=provider, protocol=protocol, request_output_limit=4096,
        )

    def test_catalog_validates_with_the_new_record(self):
        load_catalog_schema_validator().validate(self.catalog)
        validate_catalog_integrity(self.catalog)
        self.assertTrue(any(
            "GPT-6 Sol" in note and "toolReasoningEfforts" in note
            for note in self.catalog["coverageNotes"]
        ))

    def test_limits_cite_the_exact_openai_and_azure_specifications(self):
        record = self.record
        self.assertEqual(tuple(record[field] for field in CAPACITY_FIELDS), LIMITS)
        self.assertEqual(record["outputTokenAccounting"], "total_generation")
        self.assertTrue(self.sources["openai-spec-gpt-6-sol"]["url"].endswith("/api/docs/models/gpt-6-sol"))
        azure = next(profile for profile in record["tokenLimitProfiles"] if profile["id"] == "azure")
        self.assertEqual(tuple(azure[field] for field in CAPACITY_FIELDS), LIMITS)
        for field in CAPACITY_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(record["tokenLimitEvidence"][field]["sourceIds"], ["openai-spec-gpt-6-sol"])
                self.assertEqual(azure["tokenLimitEvidence"][field]["sourceIds"], ["azure-spec-gpt-6"])
                self.assertIn("2026-09-22", azure["tokenLimitEvidence"][field]["note"])

    def test_chat_completions_tool_profiles_require_none_for_both_providers(self):
        profiles = {
            profile["provider"]: profile for profile in self.record["tokenLimitProfiles"]
            if "toolReasoningEfforts" in profile
        }
        self.assertEqual(set(profiles), {"openai", "azure"})
        for provider, profile in profiles.items():
            with self.subTest(provider=provider):
                self.assertEqual(profile["protocol"], "chat_completions")
                self.assertNotIn("modelVersions", profile)
                self.assertEqual(profile["toolReasoningEfforts"], ["none"])
                evidence = profile["tokenLimitEvidence"]["toolReasoningEfforts"]
                self.assertEqual(evidence["status"], "verified")
                self.assertIn("openai-spec-gpt-6-sol", evidence["sourceIds"])
        self.assertIn(
            "gpt-6-sol-deployed-contract",
            profiles["azure"]["tokenLimitEvidence"]["toolReasoningEfforts"]["sourceIds"],
        )

    def test_budgets_scope_the_tool_rule_to_chat_completions(self):
        for provider, protocol in product(("azure", "openai"), ("chat_completions", "responses")):
            with self.subTest(provider=provider, protocol=protocol):
                budget = self.budget(provider, protocol)
                self.assertEqual(budget.model_id, SOL)
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit), LIMITS
                )
                self.assertEqual(budget.output_accounting, "total_generation")
                expected = ("none",) if protocol == "chat_completions" else ()
                self.assertEqual(budget.tool_reasoning_efforts, expected)

    def test_tools_without_an_effort_send_none(self):
        for provider in ("azure", "openai"):
            with self.subTest(provider=provider):
                prepared, _ = prepare_model_execution_settings(
                    OpenAIChatPromptExecutionSettings(), self.budget(provider), tools_enabled=True,
                )
                serialized = prepared.prepare_settings_dict()
                self.assertEqual(serialized["extra_body"]["reasoning_effort"], "none")
                self.assertEqual(serialized["max_completion_tokens"], 4096)
                self.assertNotIn("max_tokens", serialized)

    def test_tools_with_another_explicit_effort_fail_before_the_request(self):
        settings = OpenAIChatPromptExecutionSettings(reasoning_effort="high")
        with self.assertRaises(capabilities.ModelTokenBudgetError) as error:
            prepare_model_execution_settings(settings, self.budget(), tools_enabled=True)
        self.assertEqual(error.exception.code, "model_tool_configuration_invalid")
        prepared, _ = prepare_model_execution_settings(settings, self.budget(), tools_enabled=False)
        self.assertEqual(prepared.prepare_settings_dict()["extra_body"]["reasoning_effort"], "high")

    def test_reasoning_policy_and_capabilities(self):
        policy = capabilities.resolve_model_reasoning_policy(SOL)
        self.assertEqual(policy, {"status": "supported", "efforts": EFFORTS, "default_effort": "low"})
        resolution = capabilities.resolve_model_reasoning_effort(SOL, "none")
        self.assertEqual(resolution["effective_effort"], "none")
        self.assertIsNone(resolution["adjustment_reason"])
        flags = capabilities.get_model_catalog_capabilities(SOL)
        for name, expected in (
            ("processesImages", True), ("generatesImages", False), ("toolCalling", True),
            ("reasoning", True), ("supportsStreaming", True), ("imageGenerationTool", True),
        ):
            with self.subTest(capability=name):
                self.assertIs(flags[name], expected)
        self.assertEqual(flags["imageProfiles"], {"openai": "openai-responses"})
        self.assertTrue(capabilities.is_reasoning_model(SOL))

    def test_luna_and_the_bare_family_stay_unknown(self):
        for name in ("gpt-6", "gpt-6-luna"):
            with self.subTest(model=name):
                self.assertEqual(
                    capabilities.resolve_model_reasoning_policy(name)["status"], "unknown"
                )
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": name}, provider="azure", request_output_limit=4096,
                )
                self.assertEqual(budget.tool_reasoning_efforts, ())
                self.assertIsNone(budget.context_window)


if __name__ == "__main__":
    unittest.main()
