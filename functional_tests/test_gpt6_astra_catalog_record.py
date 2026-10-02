# test_gpt6_astra_catalog_record.py
"""
Functional test for the GPT-6 Astra model catalog record.
Version: 0.261.220
Implemented in: 0.261.220

Refs #1606. GPT-6 Astra moves from an operation-only record to a token-evidenced
record: 1,050,000 shared context, 922,000 input and 128,000 output for direct
OpenAI and Azure, total-generation accounting, and a Chat Completions reasoning
policy of low, medium, high and xhigh. Azure Chat Completions rejects function
tools for this model unless reasoning_effort is none, which the model rejects.
toolReasoningEfforts can't express a model with no tool-capable effort, so the
record must not declare one, and the restriction is recorded in notes instead.
No test fetches documentation, initializes application services or calls a model.
"""

import json
import unittest
from itertools import product

from test_model_capability_catalog_resolution import (
    CATALOG_PATH,
    capabilities,
    load_catalog_schema_validator,
)
from test_model_catalog_token_evidence import validate_catalog_integrity


ASTRA = "gpt-6-astra"
LIMITS = (1050000, 922000, 128000)
CAPACITY_FIELDS = ("contextWindow", "inputTokenLimit", "outputTokenLimit")
REVIEWED_AT = "2026-10-01"
EFFORTS = ["low", "medium", "high", "xhigh"]


class TestGpt6AstraCatalogRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.models = {record["id"]: record for record in cls.catalog["models"]}
        cls.sources = {record["id"]: record for record in cls.catalog["sources"]}
        cls.record = cls.models[ASTRA]

    def setUp(self):
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)

    def azure_profile(self):
        profiles = [
            profile for profile in self.record["tokenLimitProfiles"]
            if profile["provider"] == "azure"
        ]
        self.assertEqual(len(profiles), 1)
        self.assertNotIn("protocol", profiles[0])
        self.assertNotIn("modelVersions", profiles[0])
        return profiles[0]

    def test_catalog_validates_with_the_new_record(self):
        load_catalog_schema_validator().validate(self.catalog)
        validate_catalog_integrity(self.catalog)
        self.assertGreaterEqual(self.catalog["lastUpdated"], REVIEWED_AT)
        self.assertTrue(any(
            ASTRA in note and "toolReasoningEfforts" in note
            for note in self.catalog["coverageNotes"]
        ))

    def test_native_limits_cite_the_exact_openai_specification(self):
        record = self.record
        self.assertEqual(tuple(record[field] for field in CAPACITY_FIELDS), LIMITS)
        self.assertEqual(record["outputTokenAccounting"], "total_generation")
        self.assertEqual(record["tokenLimitsApplicability"], "text")
        self.assertEqual(record["verifiedAliases"], [])
        source = self.sources["openai-spec-gpt-6-astra"]
        self.assertEqual(source["provider"], "openai")
        self.assertTrue(source["url"].endswith("/api/docs/models/gpt-6-astra"))
        self.assertEqual(source["verifiedAt"], REVIEWED_AT)
        for field in CAPACITY_FIELDS:
            with self.subTest(field=field):
                evidence = record["tokenLimitEvidence"][field]
                self.assertEqual(evidence["status"], "verified")
                self.assertEqual(evidence["sourceIds"], ["openai-spec-gpt-6-astra"])
                self.assertEqual(evidence["verifiedAt"], REVIEWED_AT)
                self.assertIn(ASTRA, evidence["note"])

    def test_azure_profile_limits_cite_the_gpt6_specification(self):
        profile = self.azure_profile()
        self.assertEqual(tuple(profile[field] for field in CAPACITY_FIELDS), LIMITS)
        self.assertEqual(profile["outputTokenAccounting"], "total_generation")
        source = self.sources["azure-spec-gpt-6"]
        self.assertEqual(source["provider"], "azure")
        self.assertTrue(source["url"].endswith("#gpt-6"))
        for field in CAPACITY_FIELDS:
            with self.subTest(field=field):
                evidence = profile["tokenLimitEvidence"][field]
                self.assertEqual(evidence["status"], "verified")
                self.assertEqual(evidence["sourceIds"], ["azure-spec-gpt-6"])
                self.assertIn("2026-09-03", evidence["note"])

    def test_tool_restriction_is_recorded_without_inventing_a_tool_effort(self):
        self.assertNotIn("toolReasoningEfforts", self.record)
        for profile in self.record["tokenLimitProfiles"]:
            self.assertNotIn("toolReasoningEfforts", profile)
        profile_notes = " ".join(self.azure_profile()["notes"])
        for phrase in ("Chat Completions", "function tools", "none", "Responses API"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, profile_notes)
        self.assertTrue(any(
            "local agents with actions" in note for note in self.record["notes"]
        ))
        self.assertIn("gpt-6-astra-deployed-contract", self.record["sourceIds"])

    def test_budgets_resolve_the_verified_limits_for_both_hosts(self):
        for provider, protocol in product(("azure", "openai"), ("chat_completions", "responses")):
            with self.subTest(provider=provider, protocol=protocol):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": ASTRA},
                    provider=provider,
                    protocol=protocol,
                    request_output_limit=4096,
                )
                self.assertEqual(budget.model_id, ASTRA)
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit), LIMITS
                )
                self.assertEqual(budget.output_accounting, "total_generation")
                self.assertEqual(budget.tool_reasoning_efforts, ())
                self.assertEqual(budget.remaining_input(1000), 922000 - 1000)

    def test_reasoning_policy_excludes_none_and_responses_only_max(self):
        policy = capabilities.resolve_model_reasoning_policy(ASTRA)
        self.assertEqual(policy, {"status": "supported", "efforts": EFFORTS, "default_effort": "low"})
        self.assertIn("gpt-6-astra-deployed-contract", self.record["reasoningPolicy"]["sourceIds"])
        for effort in EFFORTS:
            with self.subTest(effort=effort):
                resolution = capabilities.resolve_model_reasoning_effort(ASTRA, effort)
                self.assertEqual(resolution["effective_effort"], effort)
                self.assertIsNone(resolution["adjustment_reason"])
        resolution = capabilities.resolve_model_reasoning_effort(ASTRA, "none")
        self.assertEqual(resolution["effective_effort"], "low")
        self.assertEqual(resolution["adjustment_reason"], "reasoning_effort_unsupported")

    def test_documented_capabilities_keep_the_responses_image_tool(self):
        flags = capabilities.get_model_catalog_capabilities(ASTRA)
        for name, expected in (
            ("processesText", True), ("generatesText", True), ("processesImages", True),
            ("generatesImages", False), ("processesAudio", False), ("generatesAudio", False),
            ("processesVideo", False), ("generatesVideo", False), ("toolCalling", True),
            ("structuredOutput", True), ("supportsStreaming", True), ("reasoning", True),
            ("imageGenerationTool", True),
        ):
            with self.subTest(capability=name):
                self.assertIs(flags[name], expected)
        self.assertEqual(flags["imageProfiles"], {"openai": "openai-responses"})
        self.assertTrue(capabilities.is_reasoning_model(ASTRA))

    def test_siblings_inherit_nothing_and_suffixed_names_get_no_token_limits(self):
        for name in ("gpt-6", "gpt-6-sol", "gpt-6-luna"):
            with self.subTest(model=name):
                self.assertEqual(
                    capabilities.resolve_model_reasoning_policy(name)["status"], "unknown"
                )
        for name in ("gpt-6-astra-2026-09-03", "gpt-6-astra-eastus"):
            with self.subTest(model=name):
                self.assertEqual(
                    capabilities.resolve_model_reasoning_policy(name)["efforts"], EFFORTS
                )
        for name in ("gpt-6", "gpt-6-sol", "gpt-6-astra-2026-09-03", "gpt-6-astra-eastus"):
            with self.subTest(model=name):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": name}, provider="azure", request_output_limit=4096,
                )
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit),
                    (None, None, None),
                )
                self.assertEqual(budget.output_accounting, "unknown")


if __name__ == "__main__":
    unittest.main()
