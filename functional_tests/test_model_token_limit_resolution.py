# test_model_token_limit_resolution.py
#!/usr/bin/env python3
"""
Functional tests for catalog-backed, bounded model token-limit resolution.
Version: 0.261.112
Implemented in: 0.261.106
Shared React V2 catalog integration: 0.261.112

Validates canonical identities, explicitly verified snapshots, independent
context/input/output ceilings, authorized deployment constraints, provenance,
and unchanged vision/reasoning decisions. Uses only local catalog data and the
standard library; no provider clients, credentials, tokenizer downloads, or
network access are required.
"""

import copy
import importlib.util
import json
import unittest
from collections import UserDict
from datetime import date
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
RESULT_KEYS = {
    "context_window_tokens", "max_input_tokens", "max_output_tokens",
    "tokenizer", "source", "model_id", "status",
}
UNKNOWN_RESULT = {
    "context_window_tokens": None,
    "max_input_tokens": None,
    "max_output_tokens": None,
    "tokenizer": None,
    "source": "unknown",
    "model_id": None,
    "status": "unknown",
}


class ModelTokenLimitResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "model_token_limit_test_subject", APP_ROOT / "functions_model_capabilities.py",
        )
        cls.capabilities = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.capabilities)
        cls.capabilities.load_model_capability_catalog(force_refresh=True)
        cls.document = json.loads(
            (APP_ROOT / "static" / "json" / "model_capabilities.json").read_text(encoding="utf-8")
        )

    def resolve(self, model, **kwargs):
        return self.capabilities.resolve_model_token_limits(model, **kwargs)

    def test_token_image_and_embedding_metadata_survive_the_same_catalog_load(self):
        catalog = self.capabilities.load_model_capability_catalog(force_refresh=True)
        fields = {"tokenLimits", "embeddingPolicy", "imageProfiles", "imageLifecycle"}
        observed = set()
        for model in self.document["models"]:
            identifier = self.capabilities._normalize_model_identifier(model["id"])
            for field in fields.intersection(model):
                with self.subTest(model=model["id"], field=field):
                    self.assertEqual(catalog[identifier][field], model[field])
                observed.add(field)
        self.assertEqual(observed, fields)
        model = catalog[self.capabilities._normalize_model_identifier("gpt-4.1")]
        self.assertEqual(model["tokenLimits"]["contextWindow"], 1047576)
        self.assertEqual(
            self.capabilities.get_image_operation_profile(model["imageProfiles"]["openai"])["api"],
            "responses",
        )

    def test_exact_public_contract_and_verified_openai_limits(self):
        expected = {
            "gpt-4o": (128000, None, 16384),
            "gpt-4o-mini": (128000, None, 16384),
            "gpt-4.1": (1047576, None, 32768),
            "gpt-4.1-mini": (1047576, None, 32768),
            "gpt-4.1-nano": (1047576, None, 32768),
            "gpt-5": (400000, 272000, 128000),
            "gpt-5-mini": (400000, 272000, 128000),
            "gpt-5-nano": (400000, 272000, 128000),
            "gpt-5.1": (400000, None, 128000),
            "gpt-5.2": (400000, None, 128000),
            "gpt-5.4": (1050000, None, 128000),
            "gpt-5.4-mini": (400000, 272000, 128000),
            "gpt-5.4-nano": (400000, 272000, 128000),
            "gpt-5.5": (1050000, None, 128000),
            "gpt-5.6-sol": (1050000, 922000, 128000),
            "gpt-5.6-terra": (1050000, 922000, 128000),
            "gpt-5.6-luna": (1050000, 922000, 128000),
        }
        for model, (context, input_limit, output) in expected.items():
            with self.subTest(model=model):
                result = self.resolve(model)
                self.assertEqual(set(result), RESULT_KEYS)
                self.assertEqual(result, {
                    "context_window_tokens": context,
                    "max_input_tokens": input_limit,
                    "max_output_tokens": output,
                    "tokenizer": "o200k_base",
                    "source": "catalog",
                    "model_id": model,
                    "status": "known",
                })

    def test_claude_limits_do_not_invent_a_local_tokenizer_or_beta_capacity(self):
        expected = {
            "claude-opus-5": (1000000, 128000),
            "claude-sonnet-5": (1000000, 128000),
            "claude-opus-4-8": (1000000, 128000),
            "claude-opus-4-7": (1000000, 128000),
            "claude-opus-4-6": (1000000, 128000),
            "claude-sonnet-4-6": (1000000, 128000),
            "claude-opus-4-5-20251101": (200000, 64000),
            "claude-sonnet-4-5-20250929": (200000, 64000),
            "claude-haiku-4-5-20251001": (200000, 64000),
        }
        for model, (context, output) in expected.items():
            with self.subTest(model=model):
                result = self.resolve(model, provider="anthropic")
                self.assertEqual(result["context_window_tokens"], context)
                self.assertEqual(result["max_output_tokens"], output)
                self.assertIsNone(result["max_input_tokens"])
                self.assertIsNone(result["tokenizer"])
                self.assertEqual(result["status"], "known")

    def test_actual_model_identity_wins_over_deployment_and_ui_identifiers(self):
        record = {
            "id": "gpt-5.6-sol",
            "model_id": "gpt-5.6-sol",
            "modelId": "gpt-5.6-sol",
            "displayName": "GPT-5.6 Sol",
            "modelName": "gpt-4o",
            "deploymentName": "gpt-5.6-sol",
            "name": "gpt-5.6-sol",
        }
        self.assertEqual(self.resolve(record), self.resolve("gpt-4o"))
        record["modelName"] = "unverified-private-model"
        self.assertEqual(self.resolve(record), UNKNOWN_RESULT)
        for field in ("id", "model_id", "modelId", "displayName", "display_name"):
            with self.subTest(field=field):
                self.assertEqual(self.resolve({field: "gpt-4o"}), UNKNOWN_RESULT)

    def test_strings_mappings_and_existing_model_object_field_shapes(self):
        for field in (
            "modelName", "behavior_name", "model_name", "model",
            "deploymentName", "deployment_name", "model_deployment", "deployment", "name",
        ):
            for factory in (dict, UserDict, MappingProxyType):
                with self.subTest(field=field, factory=factory.__name__):
                    self.assertEqual(self.resolve(factory({field: "gpt-4o"})),
                                     self.resolve("gpt-4o"))
            self.assertEqual(self.resolve(SimpleNamespace(**{field: "gpt-4o"})),
                             self.resolve("gpt-4o"))
        self.assertEqual(self.resolve(SimpleNamespace(
            behavior_name="gpt-4o", deployment="production-answer", provider="aoai",
        )), self.resolve("gpt-4o", provider="aoai"))
        self.assertEqual(self.resolve({"modelName": " ", "deploymentName": "gpt-4o"}),
                         self.resolve("gpt-4o"))

    def test_declared_aliases_and_normalized_canonical_names(self):
        for name in ("GPT 5.6 SOL", "gpt_5_6_sol", "gpt-5.6"):
            self.assertEqual(self.resolve(name), self.resolve("gpt-5.6-sol"))
        self.assertEqual(
            self.resolve("claude-haiku-4-5")["model_id"], "claude-haiku-4-5-20251001",
        )
        self.assertEqual(
            self.resolve("claude-sonnet-4-5"), self.resolve("claude-sonnet-4-5-20250929"),
        )

    def test_verified_snapshots_keep_their_specific_output_limit(self):
        for snapshot, output in (
            ("gpt-4o-2024-05-13", 4096),
            ("gpt-4o-2024-08-06", 16384),
            ("gpt-4o-2024-11-20", 16384),
            ("gpt-4.1-mini-2025-04-14", 32768),
            ("gpt-5-mini-2025-08-07", 128000),
            ("gpt-5.6-luna-2026-07-09", 128000),
        ):
            with self.subTest(snapshot=snapshot):
                result = self.resolve(snapshot)
                self.assertEqual(result["model_id"], snapshot)
                self.assertEqual(result["status"], "known")
                self.assertEqual(result["max_output_tokens"], output)
        self.assertEqual(self.resolve(
            "gpt-4o-2024-05-13", deployment_limits={"maxTokens": 16384},
        )["max_output_tokens"], 4096)
        for field in ("modelVersion", "model_version"):
            self.assertEqual(self.resolve({
                "modelName": "gpt-4o", field: "2024-05-13",
            }), self.resolve("gpt-4o-2024-05-13"))
            self.assertEqual(self.resolve({
                "modelName": "gpt-4o", field: "2030-01-01",
            }), UNKNOWN_RESULT)
        self.assertEqual(self.resolve({
            "modelName": "gpt-4o-2024-05-13", "modelVersion": "2024-05-13",
        }), self.resolve("gpt-4o-2024-05-13"))

    def test_unverified_dates_variants_and_arbitrary_prefixes_are_unknown(self):
        for value in (
            None, {}, [], 123, "", "  ", "my-private-llm",
            "gpt-4o-prod", "gpt-4o-transcribe", "gpt-4o-2024-02-30",
            "gpt-4o-2030-01-01", "gpt-4o-2024-05-13-prod", "gpt-5.99",
            "gpt-5.6-sol-2030-01-01", "gpt-5.4.1",
            {"modelName": "unknown", "deploymentName": "gpt-4o"},
        ):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), UNKNOWN_RESULT)

    def test_unpopulated_catalog_entries_are_explicitly_unknown(self):
        unpopulated = [
            model for model in self.document["models"] if "tokenLimits" not in model
        ]
        self.assertTrue(unpopulated)
        for model in unpopulated:
            with self.subTest(model=model["id"]):
                self.assertEqual(self.resolve(model["id"]), {
                    **UNKNOWN_RESULT, "model_id": model["id"],
                })

    def test_invalid_limits_are_ignored_without_coercion_or_capacity_fallback(self):
        for value in (
            None, True, False, -1, 0, 1.5, 2048.0, float("nan"), float("inf"),
            "", " ", "-8", "0", "true", "1.5", "1e6", "128k", "128,000", "1_000",
            "１２８", [], {}, b"2048",
        ):
            with self.subTest(value=value):
                limits = {field: value for field in (
                    "contextWindow", "maxInputTokens", "maxOutputTokens",
                )}
                self.assertEqual(self.resolve("private-model", deployment_limits=limits),
                                 UNKNOWN_RESULT)
                self.assertEqual(self.resolve("gpt-4o", deployment_limits=limits),
                                 self.resolve("gpt-4o"))
        for value in (None, [], "128000", 128000, True):
            self.assertEqual(self.resolve("private-model", deployment_limits=value),
                             UNKNOWN_RESULT)
            self.assertEqual(self.resolve({
                "modelName": "private-model", "tokenLimits": value,
            }), UNKNOWN_RESULT)

    def test_existing_deployment_field_spellings_are_separate_and_validated(self):
        expected_spellings = {
            "context_window_tokens": (
                "contextWindow", "context_window", "context_window_tokens",
                "maxContextTokens", "max_context_tokens", "contextLength", "context_length",
            ),
            "max_input_tokens": (
                "maxInputTokens", "max_input_tokens", "inputTokenLimit", "input_token_limit",
            ),
            "max_output_tokens": (
                "maxOutputTokens", "max_output_tokens", "outputTokenLimit", "output_token_limit",
                "responseLength", "response_length", "maxCompletionTokens",
                "max_completion_tokens", "maxTokens", "max_tokens",
            ),
        }
        for output_field, spellings in expected_spellings.items():
            for spelling in spellings:
                for container in (None, "tokenLimits", "token_limits", "limits"):
                    with self.subTest(spelling=spelling, container=container):
                        metadata = {spelling: " 2048 "}
                        if container:
                            metadata = {container: metadata}
                        result = self.resolve("private-model", deployment_limits=metadata)
                        self.assertEqual(result, {
                            **UNKNOWN_RESULT, output_field: 2048,
                            "source": "configured", "status": "partial",
                        })

    def test_deployment_constraints_shrink_but_never_enlarge_verified_ceilings(self):
        result = self.resolve({
            "modelName": "gpt-5", "contextWindow": 300000,
            "tokenLimits": {"maxInputTokens": 180000},
        }, deployment_limits={"maxOutputTokens": 4096})
        self.assertEqual(result, {
            "context_window_tokens": 300000,
            "max_input_tokens": 180000,
            "max_output_tokens": 4096,
            "tokenizer": "o200k_base",
            "model_id": "gpt-5",
            "source": "catalog+configured",
            "status": "known",
        })
        enlarged = self.resolve("gpt-5", deployment_limits={
            "contextWindow": 999999999, "maxInputTokens": 999999999, "maxOutputTokens": 999999999,
        })
        self.assertEqual(enlarged, {**self.resolve("gpt-5"), "source": "catalog+configured"})
        self.assertEqual(self.resolve("gpt-4o", deployment_limits={
            "contextWindow": 1000, "maxInputTokens": 2000, "maxOutputTokens": 3000,
        })["max_output_tokens"], 1000)
        self.assertEqual(self.resolve("gpt-4o", deployment_limits={
            "contextWindow": 1000, "maxInputTokens": 2000,
        })["max_input_tokens"], 1000)

    def test_conflicting_metadata_constraints_use_the_smallest_valid_value(self):
        record = {
            "modelName": "private-model",
            "contextWindow": 16000,
            "tokenLimits": {"context_window": 12000, "maxTokens": 2000},
        }
        result = self.resolve(record, deployment_limits={
            "contextWindow": 24000,
            "limits": {"contextLength": 8000, "maxOutputTokens": "1000"},
        })
        self.assertEqual(result["context_window_tokens"], 8000)
        self.assertEqual(result["max_output_tokens"], 1000)
        self.assertIsNone(result["max_input_tokens"])
        self.assertEqual(result["source"], "configured")
        self.assertEqual(result["status"], "known")

    def test_input_output_and_context_are_not_additive_or_interchangeable(self):
        result = self.resolve("private-model", deployment_limits={
            "contextWindow": 12000, "inputTokenLimit": 10000, "maxTokens": 4000,
        })
        self.assertEqual(result["context_window_tokens"], 12000)
        self.assertEqual(result["max_input_tokens"], 10000)
        self.assertEqual(result["max_output_tokens"], 4000)
        result = self.resolve("private-model", deployment_limits={
            "inputTokenLimit": 10000, "maxTokens": 4000,
        })
        self.assertIsNone(result["context_window_tokens"])
        self.assertEqual(result["status"], "partial")
        result = self.resolve("private-model", deployment_limits={"contextWindow": 12000})
        self.assertIsNone(result["max_input_tokens"])
        self.assertIsNone(result["max_output_tokens"])
        self.assertEqual(result["status"], "partial")

    def test_provider_specific_limits_and_explicit_provider_precedence(self):
        for provider in ("aoai", "azure_openai", "aifoundry", "new_foundry", "azure"):
            with self.subTest(provider=provider):
                result = self.resolve("gpt-5.5", provider=provider, deployment_limits={
                    "contextWindow": 1050000, "maxInputTokens": 1050000,
                })
                self.assertEqual(result["context_window_tokens"], 922000)
                self.assertEqual(result["max_input_tokens"], 922000)
                self.assertEqual(result["max_output_tokens"], 128000)
                self.assertEqual(result["source"], "catalog+configured")
                self.assertEqual(self.resolve("gpt-5.2", provider=provider)["max_input_tokens"],
                                 272000)
        self.assertIsNone(self.resolve("gpt-5.2", provider="openai")["max_input_tokens"])
        self.assertEqual(self.resolve(
            {"modelName": "gpt-5.5", "provider": "aoai"}, provider="openai",
        )["context_window_tokens"], 1050000)
        for provider in (None, "", " ", True, {}):
            self.assertEqual(self.resolve(
                {"modelName": "gpt-5.5", "provider": "aoai"}, provider=provider,
            )["context_window_tokens"], 922000)
        self.assertEqual(self.resolve("claude-haiku-4-5", provider="claude"),
                         self.resolve("claude-haiku-4-5", provider="anthropic"))
        for model, provider in (
            ("gpt-4o", "anthropic"), ("claude-haiku-4-5", "openai"),
            ("claude-haiku-4-5", "aoai"), ("gpt-4o", "private-compatible-server"),
        ):
            self.assertEqual(self.resolve(model, provider=provider), UNKNOWN_RESULT)

    def test_configured_tokenizer_cannot_replace_a_verified_catalog_encoding(self):
        self.assertEqual(self.resolve("gpt-4o", deployment_limits={
            "tokenizer": "cl100k_base",
        }), self.resolve("gpt-4o"))
        result = self.resolve("private-model", deployment_limits={"tokenizer": " cl100k_base "})
        self.assertEqual(result, {
            **UNKNOWN_RESULT, "tokenizer": "cl100k_base",
            "source": "configured", "status": "partial",
        })
        for value in (None, "", " ", True, 123, {}, []):
            self.assertEqual(self.resolve("private-model", deployment_limits={"tokenizer": value}),
                             UNKNOWN_RESULT)

    def test_missing_or_malformed_catalog_limits_do_not_invent_capacity(self):
        with patch.object(self.capabilities, "_CATALOG_CACHE", {}):
            self.assertEqual(self.resolve("gpt-4o"), UNKNOWN_RESULT)
            result = self.resolve("gpt-4o", deployment_limits={
                "contextWindow": 8192, "maxTokens": 1024,
            })
            self.assertEqual(result["source"], "configured")
            self.assertEqual(result["status"], "known")
            self.assertIsNone(result["model_id"])
        for limits in (None, [], "128000", {}, {
            "contextWindow": True, "maxInputTokens": -1, "maxOutputTokens": 1.5,
            "tokenizer": False, "snapshots": [], "providerLimits": [],
        }):
            with patch.object(self.capabilities, "_CATALOG_CACHE", {
                "test-model": {"_model_id": "test-model", "tokenLimits": limits},
            }):
                self.assertEqual(self.resolve("test-model"), {
                    **UNKNOWN_RESULT, "model_id": "test-model",
                })
                self.assertEqual(self.resolve("test-model-2030-01-01"), UNKNOWN_RESULT)

    def test_provider_metadata_also_cannot_enlarge_catalog_ceilings(self):
        with patch.object(self.capabilities, "_CATALOG_CACHE", {
            "test-model": {
                "_model_id": "test-model", "_provider": "openai",
                "tokenLimits": {
                    "contextWindow": 8000, "maxInputTokens": 6000, "maxOutputTokens": 1000,
                    "providerLimits": {"azure": {
                        "contextWindow": 16000, "maxInputTokens": 12000, "maxOutputTokens": 2000,
                    }},
                },
            },
        }):
            self.assertEqual(self.resolve("test-model", provider="aoai"),
                             self.resolve("test-model"))

    def test_input_records_catalog_and_independent_results_are_not_mutated(self):
        model = {
            "modelName": "gpt-5", "tokenLimits": {"contextWindow": 200000},
            "limits": {"maxInputTokens": 150000},
        }
        metadata = {"tokenLimits": {"maxOutputTokens": "4096"}}
        original_model, original_metadata = copy.deepcopy(model), copy.deepcopy(metadata)
        original_catalog = copy.deepcopy(self.capabilities.load_model_capability_catalog())
        result = self.resolve(model, deployment_limits=metadata)
        result["context_window_tokens"] = 999999999
        self.assertEqual(self.resolve(model, deployment_limits=metadata)["context_window_tokens"],
                         200000)
        self.assertEqual(model, original_model)
        self.assertEqual(metadata, original_metadata)
        self.assertEqual(self.capabilities.load_model_capability_catalog(), original_catalog)

    def test_limit_provenance_and_declared_snapshots_are_complete(self):
        sources = {source["id"]: source for source in self.document["sources"]}
        for model in self.document["models"]:
            limits = model.get("tokenLimits")
            if not limits:
                continue
            with self.subTest(model=model["id"]):
                date.fromisoformat(limits["verifiedAt"])
                self.assertTrue(limits["sourceIds"])
                for metadata in (
                    limits,
                    *limits.get("providerLimits", {}).values(),
                    *limits.get("snapshots", {}).values(),
                ):
                    for source_id in metadata.get("sourceIds", []):
                        self.assertIn(source_id, sources)
                        self.assertIn(urlparse(sources[source_id]["url"]).hostname, (
                            "developers.openai.com", "learn.microsoft.com",
                            "platform.claude.com", "raw.githubusercontent.com",
                        ))
                    for field in ("contextWindow", "maxInputTokens", "maxOutputTokens"):
                        if field in metadata:
                            self.assertIs(type(metadata[field]), int)
                            self.assertGreater(metadata[field], 0)
                for snapshot in limits.get("snapshots", {}):
                    result = self.resolve(snapshot)
                    self.assertEqual(result["model_id"], snapshot)
                    self.assertEqual(result["status"], "known")

    def test_vision_and_reasoning_matching_are_unchanged(self):
        for model, expected in (
            ("gpt-4o", (True, "catalog")),
            ("gpt-4o-prod", (True, "catalog")),
            ("gpt-4o-2030-01-01", (True, "catalog")),
            ("gpt-4o-2024-05-13", (True, "catalog")),
            ("gpt-5.3-chat", (False, "catalog")),
            ("gpt-4", (False, "inferred")),
            ("acme-vision", (True, "inferred")),
        ):
            self.resolve(model)
            self.assertEqual(self.capabilities.resolve_model_vision_support(model), expected)
        policy = self.capabilities.resolve_model_reasoning_policy("gpt-5.6-luna-prod")
        self.assertEqual(policy["efforts"], ["none", "low", "medium", "high", "xhigh"])
        self.assertEqual(self.capabilities.resolve_model_reasoning_policy("gpt-4o")["status"],
                         "unsupported")
        self.assertEqual(self.capabilities.resolve_model_reasoning_effort(
            "gpt-5.6-luna", "minimal",
        )["effective_effort"], "low")


if __name__ == "__main__":
    unittest.main()
