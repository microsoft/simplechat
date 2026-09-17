# test_model_catalog_rebase_integration.py
"""
Offline regression tests for audited token and React V2 metadata coexistence.
Version: 0.261.122
Implemented in: 0.261.122

Protect audited, qualitative-capability, reasoning-only, and embedding-policy
records present on this topic, historical source reviews, and their independent
resolvers. Operation eligibility must never widen exact chat-capacity matching
or turn unknown limits into a budget. No external services or Git history are
required; provider-qualified image profiles belong to a separate topic.
"""

import copy
import json
import unittest
from itertools import product
from unittest.mock import patch

from jsonschema import ValidationError

from test_model_capability_catalog_resolution import (
    CATALOG_PATH,
    capabilities,
    load_catalog_schema_validator,
)
from test_model_catalog_token_evidence import (
    AUDITED_NATIVE_LIMITS,
    TOKEN_METADATA_FIELDS,
    validate_catalog_integrity,
)
from functions_embedding_policy import EmbeddingPolicyError, resolve_embedding_policy


OPERATION_ONLY_IDS = {
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    "o1", "o3", "o3-mini", "o4-mini", "gpt-image-2", "gpt-image-1.5",
    "gpt-image-1", "gpt-image-1-mini", "dall-e-3",
}
REASONING_ONLY_IDS = {
    "gpt-4", "gpt-4.5", "gpt-35-turbo", "o1-mini", "o1-preview", "o3-pro",
}
REASONING_POLICY_IDS = REASONING_ONLY_IDS | {
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
    "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano",
    "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2", "gpt-5.1",
    "gpt-5.1-codex", "gpt-5.1-codex-mini", "gpt-5.1-codex-max",
    "gpt-5", "gpt-5-pro", "gpt-5-codex", "gpt-5-mini", "gpt-5-nano",
    "gpt-4o", "gpt-4.1", "o1", "o3", "o3-mini", "o4-mini",
}
OPENAI_EMBEDDING_POLICY = {
    "max_input_tokens": 8192,
    "max_batch_size": 2048,
    "max_batch_tokens": 300000,
    "tokenizer": "cl100k_base",
    "document_prefix": "",
    "query_prefix": "",
    "api": "openai",
    "requires_input_type": False,
}
COHERE_EMBEDDING_POLICY = {
    "max_input_tokens": 512,
    "max_batch_size": 96,
    "max_batch_tokens": 49152,
    "tokenizer": "conservative",
    "document_prefix": "",
    "query_prefix": "",
    "api": "unsupported",
    "requires_input_type": True,
}
EXPECTED_EMBEDDING_POLICIES = {
    "text-embedding-ada-002": {
        **OPENAI_EMBEDDING_POLICY,
        "default_dimensions": 1536, "supports_dimensions": False,
        "min_dimensions": 1536, "max_dimensions": 1536,
        "model_revision": "text-embedding-ada-002:2",
        "versions": {
            "1": {"max_input_tokens": 2046, "model_revision": "text-embedding-ada-002:1"},
            "2": {"max_input_tokens": 8192, "model_revision": "text-embedding-ada-002:2"},
        },
    },
    "text-embedding-3-small": {
        **OPENAI_EMBEDDING_POLICY,
        "default_dimensions": 1536, "supports_dimensions": True,
        "min_dimensions": 1, "max_dimensions": 1536,
        "model_revision": "text-embedding-3-small",
    },
    "text-embedding-3-large": {
        **OPENAI_EMBEDDING_POLICY,
        "default_dimensions": 3072, "supports_dimensions": True,
        "min_dimensions": 1, "max_dimensions": 3072,
        "model_revision": "text-embedding-3-large",
    },
    "embed-v-4-0": {
        **COHERE_EMBEDDING_POLICY,
        "default_dimensions": 1536, "supports_dimensions": True,
        "min_dimensions": 256, "max_dimensions": 1536,
        "allowed_dimensions": [256, 512, 1024, 1536],
        "model_context_tokens": 128000,
        "hosting_limits": {"azure": {"max_input_tokens": 512}},
        "model_revision": "embed-v4.0",
    },
    "Cohere-embed-v3-english": {
        **COHERE_EMBEDDING_POLICY,
        "default_dimensions": 1024, "supports_dimensions": False,
        "min_dimensions": 1024, "max_dimensions": 1024,
        "model_revision": "embed-english-v3.0",
    },
    "Cohere-embed-v3-multilingual": {
        **COHERE_EMBEDDING_POLICY,
        "default_dimensions": 1024, "supports_dimensions": False,
        "min_dimensions": 1024, "max_dimensions": 1024,
        "model_revision": "embed-multilingual-v3.0",
    },
}
EMBEDDING_IDS = set(EXPECTED_EMBEDDING_POLICIES)
SOURCE_REVIEW_HISTORY = {
    "2026-09-07": {
        "azure-openai-reasoning", "luna-deployed-contract", "openai-chat-completions",
    },
    "2026-09-08": {
        "azure-openai-responses", "azure-openai-v1", "azure-openai-images",
        "openai-gpt5-6-terra", "openai-gpt5-6-luna", "openai-gpt5-5",
        "openai-gpt5-4", "openai-gpt5-4-pro", "openai-gpt5-4-mini", "openai-gpt5-4-nano",
        "openai-gpt5-3-codex", "openai-gpt5-2", "openai-gpt5-2-codex",
        "openai-gpt5-1-codex", "openai-gpt5-1-codex-mini", "openai-gpt5-1-codex-max",
        "openai-gpt5-pro", "openai-gpt5-codex", "openai-gpt5-mini", "openai-gpt5-nano",
        "openai-gpt4o", "openai-gpt4o-mini", "openai-gpt4-1",
        "openai-gpt4-1-mini", "openai-gpt4-1-nano",
        "openai-o1", "openai-o3", "openai-o3-mini", "openai-o4-mini",
        "openai-gpt-image-2", "openai-gpt-image-1-5", "openai-gpt-image-1",
        "openai-gpt-image-1-mini", "openai-dalle3", "openai-deprecations",
    },
    "2026-09-16": {
        "azure-openai-embeddings", "azure-openai-embeddings-rest",
        "azure-embedding-models", "azure-cohere-embedding-models",
        "azure-partner-embedding-models", "cohere-embedding-models",
        "cohere-embedding-api", "cohere-azure-embeddings",
    },
}


class TestModelCatalogRebaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.models = {record["id"]: record for record in cls.catalog["models"]}
        cls.sources = {record["id"]: record for record in cls.catalog["sources"]}
        cls.validator = load_catalog_schema_validator()

    def setUp(self):
        capabilities.reset_model_capability_catalog_cache()
        self.addCleanup(capabilities.reset_model_capability_catalog_cache)

    def validate_model(self, record):
        self.validator.validate({**self.catalog, "models": [record]})

    def test_original_audit_and_v2_inventories_coexist(self):
        self.assertTrue(set(AUDITED_NATIVE_LIMITS).issubset(self.models))
        self.assertTrue(OPERATION_ONLY_IDS.issubset(self.models))
        self.assertTrue(REASONING_ONLY_IDS.issubset(self.models))
        self.assertTrue(EMBEDDING_IDS.issubset(self.models))
        self.validator.validate(self.catalog)
        validate_catalog_integrity(self.catalog)
        self.assertEqual(
            capabilities.get_model_capability_catalog_records(), self.catalog["models"]
        )

    def test_public_record_copies_protect_nested_token_and_operation_metadata(self):
        records = capabilities.get_model_capability_catalog_records()
        models = {record["id"]: record for record in records}
        sol = models["gpt-5.6-sol"]
        sol["contextWindow"] = 1
        sol["capabilities"]["processesImages"] = False
        sol["tokenLimitEvidence"]["contextWindow"]["sourceIds"].clear()
        sol["tokenLimitProfiles"][0]["contextWindow"] = 1
        sol["reasoningPolicy"]["efforts"].clear()
        models["o3-pro"]["reasoningPolicy"]["default_effort"] = "none"
        models["embed-v-4-0"]["embeddingPolicy"]["allowed_dimensions"].clear()
        models["embed-v-4-0"]["embeddingPolicy"]["hosting_limits"]["azure"]["max_input_tokens"] = 128000
        models["text-embedding-ada-002"]["embeddingPolicy"]["versions"]["1"]["max_input_tokens"] = 8192
        records.clear()

        self.assertEqual(
            capabilities.get_model_capability_catalog_records(), self.catalog["models"]
        )
        budget = capabilities.resolve_model_token_budget("gpt-5.6-sol", provider="openai")
        self.assertEqual(budget.context_window, 1050000)
        self.assertTrue(
            capabilities.get_model_catalog_capabilities("gpt-5.6-sol")["imageGenerationTool"]
        )

    def test_operation_records_do_not_invent_unreviewed_fields(self):
        for model_id in OPERATION_ONLY_IDS:
            with self.subTest(model=model_id):
                record = self.models[model_id]
                self.assertFalse(TOKEN_METADATA_FIELDS.intersection(record))
                self.assertNotIn("supportsStreaming", record["capabilities"])
                self.assertNotIn("reasoning", record["capabilities"])
                resolved = capabilities.get_model_catalog_capabilities(model_id)
                for field, value in record["capabilities"].items():
                    self.assertIs(type(value), bool)
                    self.assertIs(resolved[field], value)

    def test_reasoning_only_records_make_no_qualitative_claim(self):
        for model_id in REASONING_ONLY_IDS:
            with self.subTest(model=model_id):
                record = self.models[model_id]
                self.assertTrue(set(record) <= {"id", "aliases", "reasoningPolicy"})
                self.assertIsNone(capabilities.get_model_catalog_capabilities(model_id))
                self.assertEqual(
                    capabilities.resolve_model_vision_support(model_id)[1], "inferred"
                )

    def test_operation_and_reasoning_metadata_never_authorize_a_budget(self):
        for model_id, provider in product(
            OPERATION_ONLY_IDS | REASONING_ONLY_IDS, ("openai", "azure", "publisher")
        ):
            with self.subTest(model=model_id, provider=provider):
                budget = capabilities.resolve_model_token_budget(
                    {"modelName": model_id}, provider=provider,
                    protocol="responses", request_output_limit=4096,
                )
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit,
                     budget.effective_context_window),
                    (None, None, None, None),
                )
                self.assertEqual(budget.output_accounting, "unknown")
                self.assertEqual(budget.provenance, ())
                self.assertEqual(budget.tool_reasoning_efforts, ())
                with self.assertRaises(capabilities.ModelTokenBudgetError):
                    budget.remaining_input()

    def test_operation_snapshot_matching_does_not_widen_numeric_identity(self):
        for identifier, operation_supported in (
            ("gpt-5.6-sol-2026-07-09", True),
            ("gpt-5.6-sol-2026-02-30", False),
            ("gpt-5.6-sol-eastus", False),
            ("gpt-5.6-sol-99", False),
            ("gpt-5.99", False),
        ):
            with self.subTest(identifier=identifier):
                operation = capabilities.get_model_catalog_capabilities(identifier)
                if operation_supported:
                    self.assertTrue(operation["imageGenerationTool"])
                else:
                    self.assertIsNone(operation)
                budget = capabilities.resolve_model_token_budget(identifier, provider="openai")
                self.assertEqual(
                    (budget.context_window, budget.input_limit, budget.output_limit),
                    (None, None, None),
                )
        verified_alias = capabilities.resolve_model_token_budget("gpt-5.6", provider="openai")
        self.assertEqual(verified_alias.model_id, "gpt-5.6-sol")
        self.assertEqual(verified_alias.context_window, 1050000)

    def test_reasoning_policies_survive_the_identifier_index(self):
        for model_id in REASONING_POLICY_IDS:
            with self.subTest(model=model_id):
                policy = self.models[model_id]["reasoningPolicy"]
                expected = {
                    key: policy[key] for key in ("status", "efforts", "default_effort")
                }
                resolved = capabilities.resolve_model_reasoning_policy(model_id)
                self.assertEqual(resolved, expected)
                resolved["efforts"].clear()
                self.assertEqual(capabilities.resolve_model_reasoning_policy(model_id), expected)

    def test_raw_document_cache_fixtures_exercise_valid_and_invalid_policies(self):
        policy = copy.deepcopy(self.models["o3-pro"]["reasoningPolicy"])
        record = {"id": "policy-test", "reasoningPolicy": policy}
        document = {**self.catalog, "models": [record]}
        with patch.object(capabilities, "_CATALOG_CACHE", document):
            self.assertEqual(
                capabilities.resolve_model_reasoning_policy("policy-test")["status"],
                "supported",
            )
            policy["default_effort"] = "none"
            self.assertEqual(
                capabilities.resolve_model_reasoning_policy("policy-test")["status"],
                "unknown",
            )
            self.assertEqual(capabilities.get_model_capability_catalog_records(), [record])
            self.assertIn("policy-test", capabilities.load_model_capability_catalog())

    def test_legacy_image_tool_flags_do_not_imply_native_images_or_vision(self):
        for model_id, vision, native_images, image_tool in (
            ("gpt-4o", True, False, True),
            ("gpt-4.1-mini", True, False, False),
            ("o1", True, False, False),
            ("o3-mini", False, False, True),
            ("gpt-image-2", True, True, False),
            ("dall-e-3", False, True, False),
        ):
            with self.subTest(model=model_id):
                flags = capabilities.get_model_catalog_capabilities(model_id)
                self.assertEqual(
                    (flags["processesImages"], flags["generatesImages"], flags["imageGenerationTool"]),
                    (vision, native_images, image_tool),
                )
        self.assertEqual(self.models["dall-e-3"]["lifecycle"], "retired")

    def test_historical_metadata_reviews_are_not_relabelled_as_token_audits(self):
        for reviewed_at, source_ids in SOURCE_REVIEW_HISTORY.items():
            for source_id in source_ids:
                with self.subTest(source=source_id):
                    self.assertEqual(self.sources[source_id]["verifiedAt"], reviewed_at)
                    self.assertLessEqual(reviewed_at, self.catalog["lastUpdated"])

    def test_metadata_only_variants_reject_token_fields(self):
        audited = self.models["gpt-5.6-sol"]
        for model_id, field in product(
            ("gpt-4", "gpt-4o", "gpt-4.1-mini", "gpt-image-2",
             "text-embedding-ada-002", "embed-v-4-0"),
            TOKEN_METADATA_FIELDS,
        ):
            with self.subTest(model=model_id, field=field):
                record = copy.deepcopy(self.models[model_id])
                record[field] = copy.deepcopy(audited.get(field, 100))
                with self.assertRaises(ValidationError):
                    self.validate_model(record)
        record = copy.deepcopy(self.models["gpt-4"])
        record["capabilities"] = {"processesImages": True}
        with self.assertRaises(ValidationError):
            self.validate_model(record)
        with self.assertRaises(ValidationError):
            self.validate_model({"id": "undocumented-model"})

    def test_reasoning_schema_rejects_invalid_efforts_defaults_and_evidence(self):
        for changes in (
            {"status": "enabled"}, {"efforts": []}, {"efforts": ["low", "low"]},
            {"efforts": ["max"]}, {"efforts": [True]}, {"default_effort": "none"},
            {"default_effort": None}, {"status": "unsupported"}, {"status": "unknown"},
            {"sourceIds": []}, {"sourceIds": [""]}, {"contextWindow": 128000},
        ):
            with self.subTest(changes=changes):
                record = copy.deepcopy(self.models["o3-pro"])
                record["reasoningPolicy"].update(changes)
                with self.assertRaises(ValidationError):
                    self.validate_model(record)
        for field in ("status", "efforts", "default_effort", "sourceIds"):
            record = copy.deepcopy(self.models["o3-pro"])
            del record["reasoningPolicy"][field]
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                self.validate_model(record)

    def test_operation_schema_rejects_unknown_keys_and_lifecycle(self):
        for path, value in (
            (("unexpected",), True),
            (("lifecycle",), "available"),
            (("provider",), "foundry"),
            (("capabilities", "unexpected"), True),
            (("capabilities", "imageGenerationTool"), "true"),
            (("reasoningPolicy", "unexpected"), True),
            (("reasoningPolicy", "sourceIds"), []),
        ):
            with self.subTest(path=path):
                record = copy.deepcopy(self.models["gpt-4o"])
                target = record
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValidationError):
                    self.validate_model(record)

    def test_integrity_rejects_unresolved_metadata_sources(self):
        for target in ("reasoning", "model"):
            with self.subTest(target=target):
                document = copy.deepcopy(self.catalog)
                models = {record["id"]: record for record in document["models"]}
                if target == "reasoning":
                    models["o3-pro"]["reasoningPolicy"]["sourceIds"].append("missing")
                else:
                    models["gpt-4o"]["sourceIds"].append("missing")
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(document)

    def test_integrity_rejects_new_identity_and_provenance_corruption(self):
        for target in ("identity", "alias", "publisher", "date", "capacity"):
            with self.subTest(target=target):
                document = copy.deepcopy(self.catalog)
                models = {record["id"]: record for record in document["models"]}
                sources = {record["id"]: record for record in document["sources"]}
                if target == "identity":
                    duplicate = copy.deepcopy(models["gpt-4"])
                    duplicate["id"] = "GPT_4"
                    document["models"].append(duplicate)
                elif target == "alias":
                    models["gpt-5.6-sol"]["verifiedAliases"].append("gpt-4")
                elif target == "publisher":
                    sources["azure-openai-images"]["provider"] = "openai"
                elif target == "date":
                    sources["azure-openai-images"]["verifiedAt"] = "2099-01-01"
                else:
                    models["gpt-4"]["contextWindow"] = 128000
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(document)

    def test_embedding_records_keep_exact_operation_policies_without_chat_metadata(self):
        for model_id, expected_policy in EXPECTED_EMBEDDING_POLICIES.items():
            with self.subTest(model=model_id):
                record = self.models[model_id]
                self.assertEqual(record["embeddingPolicy"], expected_policy)
                self.assertFalse(TOKEN_METADATA_FIELDS.intersection(record))
                self.assertNotIn("lifecycle", record)
                self.assertNotIn("imageProfiles", record)
                self.assertEqual(set(record["capabilities"]), {
                    "processesText", "generatesText", "generatesEmbeddings", "processesImages",
                    "generatesImages", "imageGenerationTool", "toolCalling",
                })
                for identifier in (model_id, *record["aliases"]):
                    budget = capabilities.resolve_model_token_budget(identifier, provider="azure")
                    self.assertEqual(
                        (budget.context_window, budget.input_limit, budget.output_limit,
                         budget.effective_context_window),
                        (None, None, None, None),
                    )
                    self.assertEqual(budget.output_accounting, "unknown")
                    self.assertEqual(budget.provenance, ())
                    with self.assertRaises(capabilities.ModelTokenBudgetError):
                        budget.remaining_input()
        self.assertEqual(self.models["embed-v-4-0"]["provider"], "cohere")
        self.assertEqual(self.sources["azure-cohere-embedding-models"]["provider"], "microsoft")
        self.assertTrue(any(
            "49,152-token" in note and "conservative application bound" in note
            and "not a claim" in note
            for note in self.catalog["coverageNotes"]
        ))

    def test_embedding_policies_and_aliases_survive_isolated_strict_lookups(self):
        for model_id in EMBEDDING_IDS:
            record = self.models[model_id]
            for identifier in (model_id, *record["aliases"]):
                with self.subTest(identifier=identifier):
                    resolved = capabilities.get_model_catalog_capabilities(
                        identifier, strict_identity=True
                    )
                    self.assertTrue(resolved["generatesEmbeddings"])
                    self.assertEqual(resolved["embeddingPolicy"], record["embeddingPolicy"])
                    resolved["embeddingPolicy"]["max_input_tokens"] = 1
                    again = capabilities.get_model_catalog_capabilities(
                        identifier, strict_identity=True
                    )
                    self.assertEqual(again["embeddingPolicy"], record["embeddingPolicy"])
        for identifier in (
            "text-embedding-3-small-2026-09-16",
            "text-embedding-3-small-eastus",
            "Cohere Embed v4",
            {"displayName": "text-embedding-3-small"},
            {"modelName": "private-model", "deploymentName": "text-embedding-3-small"},
        ):
            with self.subTest(unverified_identifier=identifier):
                self.assertIsNone(capabilities.get_model_catalog_capabilities(
                    identifier, strict_identity=True
                ))

    def test_embedding_version_limits_and_host_limits_remain_distinct(self):
        for version, expected in (("1", 2046), ("2", 8192)):
            policy = resolve_embedding_policy({
                "modelName": "text-embedding-ada-002", "modelVersion": version,
            })
            self.assertEqual(policy["max_input_tokens"], expected)
            self.assertEqual(policy["model_revision"], f"text-embedding-ada-002:{version}")
        with self.assertRaisesRegex(EmbeddingPolicyError, "version is not cataloged"):
            resolve_embedding_policy({
                "modelName": "text-embedding-ada-002", "modelVersion": "future",
            })
        cohere = resolve_embedding_policy("embed-v4.0")
        self.assertEqual(cohere["max_input_tokens"], 512)
        self.assertEqual(cohere["max_batch_tokens"], 49152)
        self.assertEqual(cohere["api"], "unsupported")
        self.assertTrue(cohere["requires_input_type"])
        raw_policy = self.models["embed-v-4-0"]["embeddingPolicy"]
        self.assertEqual(raw_policy["model_context_tokens"], 128000)
        self.assertEqual(raw_policy["hosting_limits"], {"azure": {"max_input_tokens": 512}})

    def test_embedding_schema_requires_positive_true_integers_and_bounded_values(self):
        for field, invalid in product(
            ("default_dimensions", "min_dimensions", "max_dimensions", "max_input_tokens",
             "model_context_tokens", "max_batch_size", "max_batch_tokens"),
            (True, False, None, 0, -1, 1.0, 1.5, "512", float("nan"), float("inf")),
        ):
            with self.subTest(field=field, value=invalid):
                record = copy.deepcopy(self.models["embed-v-4-0"])
                record["embeddingPolicy"][field] = invalid
                with self.assertRaises(ValidationError):
                    self.validate_model(record)
        for field, invalid in (
            ("default_dimensions", 65537), ("max_input_tokens", 1048577),
            ("max_batch_size", 2049), ("max_batch_tokens", 16777217),
        ):
            with self.subTest(field=field, value=invalid):
                record = copy.deepcopy(self.models["embed-v-4-0"])
                record["embeddingPolicy"][field] = invalid
                with self.assertRaises(ValidationError):
                    self.validate_model(record)

    def test_embedding_schema_requires_complete_closed_operation_contracts(self):
        required = {
            "default_dimensions", "supports_dimensions", "min_dimensions", "max_dimensions",
            "max_input_tokens", "max_batch_size", "max_batch_tokens", "tokenizer",
            "model_revision", "document_prefix", "query_prefix", "api", "requires_input_type",
        }
        for field in required:
            with self.subTest(missing=field):
                record = copy.deepcopy(self.models["text-embedding-3-small"])
                del record["embeddingPolicy"][field]
                with self.assertRaises(ValidationError):
                    self.validate_model(record)
        for field, invalid in (
            ("api", "cohere"), ("tokenizer", "guessed-tokenizer"),
            ("supports_dimensions", "true"), ("requires_input_type", 1),
            ("model_revision", ""), ("model_revision", "   "),
            ("model_revision", "revision\n"), ("query_prefix", "\u0000"),
            ("default_dimensions_typo", 1024),
        ):
            with self.subTest(field=field, value=invalid):
                record = copy.deepcopy(self.models["text-embedding-3-small"])
                record["embeddingPolicy"][field] = invalid
                with self.assertRaises(ValidationError):
                    self.validate_model(record)
        for model_id in ("gpt-5.6-sol", "gpt-4o", "gpt-4"):
            record = copy.deepcopy(self.models[model_id])
            record.setdefault("capabilities", {})["generatesEmbeddings"] = True
            with self.subTest(non_embedding_record=model_id), self.assertRaises(ValidationError):
                self.validate_model(record)
        for field, value in (
            ("generatesEmbeddings", False), ("generatesEmbeddings", 1),
            ("generatesText", True), ("imageGenerationTool", True), ("unverifiedFlag", False),
        ):
            record = copy.deepcopy(self.models["text-embedding-3-small"])
            record["capabilities"][field] = value
            with self.subTest(capability=field, value=value), self.assertRaises(ValidationError):
                self.validate_model(record)

    def test_embedding_schema_rejects_invalid_dimensions_hosts_and_versions(self):
        for allowed in ([], [256, 256], [True], [256.0], [0], [65537]):
            record = copy.deepcopy(self.models["embed-v-4-0"])
            record["embeddingPolicy"]["allowed_dimensions"] = allowed
            with self.subTest(allowed=allowed), self.assertRaises(ValidationError):
                self.validate_model(record)
        for host_limits in (
            {}, {"unknown-host": {"max_input_tokens": 512}},
            {"azure": {"max_input_tokens": True}},
            {"azure": {"max_input_tokens": 512.0}},
            {"azure": {"max_input_tokens": 512, "contextWindow": 128000}},
        ):
            record = copy.deepcopy(self.models["embed-v-4-0"])
            record["embeddingPolicy"]["hosting_limits"] = host_limits
            with self.subTest(hosting_limits=host_limits), self.assertRaises(ValidationError):
                self.validate_model(record)
        for versions in (
            {}, {" ": {"max_input_tokens": 2046, "model_revision": "ada:1"}},
            {"1": {"max_input_tokens": 2046}},
            {"1": {"max_input_tokens": 2046.0, "model_revision": "ada:1"}},
            {"1": {"max_input_tokens": 2046, "model_revision": "ada:1", "outputTokenLimit": 4096}},
        ):
            record = copy.deepcopy(self.models["text-embedding-ada-002"])
            record["embeddingPolicy"]["versions"] = versions
            with self.subTest(versions=versions), self.assertRaises(ValidationError):
                self.validate_model(record)

    def test_embedding_integrity_rejects_contradictory_policy_relationships(self):
        for changes in (
            {"max_dimensions": 1024},
            {"supports_dimensions": False},
            {"allowed_dimensions": [256, 512, 1024]},
            {"allowed_dimensions": [256, 512, 1024, 1536, 2048]},
            {"max_batch_tokens": 511},
            {"max_input_tokens": 128001},
            {"hosting_limits": {"azure": {"max_input_tokens": 128001}}},
        ):
            with self.subTest(changes=changes):
                document = copy.deepcopy(self.catalog)
                record = next(model for model in document["models"] if model["id"] == "embed-v-4-0")
                record["embeddingPolicy"].update(changes)
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(document)
        document = copy.deepcopy(self.catalog)
        ada = next(model for model in document["models"] if model["id"] == "text-embedding-ada-002")
        ada["embeddingPolicy"]["versions"]["1"]["max_input_tokens"] = 300001
        with self.assertRaises(ValueError):
            validate_catalog_integrity(document)

    def test_embedding_integrity_preserves_source_and_identity_boundaries(self):
        for target in ("source", "alias", "chat_alias", "policy", "capability", "publisher"):
            with self.subTest(target=target):
                document = copy.deepcopy(self.catalog)
                models = {record["id"]: record for record in document["models"]}
                record = models["embed-v-4-0"]
                if target == "source":
                    record["sourceIds"].append("missing-embedding-evidence")
                elif target == "alias":
                    models["Cohere-embed-v3-english"]["aliases"].append("embed-v4.0")
                elif target == "chat_alias":
                    models["gpt-5.6-sol"]["aliases"].append("embed-v4.0")
                elif target == "policy":
                    del record["embeddingPolicy"]
                elif target == "capability":
                    record["capabilities"]["generatesEmbeddings"] = False
                else:
                    source = next(source for source in document["sources"] if source["id"] == "cohere-embedding-models")
                    source["provider"] = "microsoft"
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(document)


if __name__ == "__main__":
    unittest.main()
