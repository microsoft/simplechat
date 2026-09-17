# test_ai_connection_embedding_capabilities.py
"""
Functional tests for catalog-backed embedding capability and policy contracts.
Version: 0.261.106
Implemented in: 0.261.106

Validate sourced aliases, strict limits, gateway attestations, publication,
independent global defaults and legacy handoff without application/service imports.
"""

import copy
import json
import unittest
from unittest import mock

from test_ai_connections_capabilities import CATALOG_PATH, IsolatedConnectionsTestCase


class EmbeddingPolicyTests(IsolatedConnectionsTestCase):
    def resolve(self, model, **kwargs):
        return self.embedding_policy.resolve_embedding_policy(model, **kwargs)

    def embedding_model(self, name="text-embedding-3-small", **config):
        return self.model(model_name=name, embedding_config=config)

    def test_openai_defaults_come_from_the_catalog_without_request_dimensions(self):
        for name, dimensions, resizable in (
            ("text-embedding-ada-002", 1536, False),
            ("text-embedding-3-small", 1536, True),
            ("text-embedding-3-large", 3072, True),
        ):
            with self.subTest(model=name):
                policy = self.resolve(name)
                self.assertEqual(policy["default_dimensions"], dimensions)
                self.assertEqual(policy["dimensions"], dimensions)
                self.assertIs(policy["supports_dimensions"], resizable)
                self.assertIsNone(policy["request_dimensions"])
                self.assertEqual(policy["max_input_tokens"], 8192)
                self.assertEqual(policy["max_batch_size"], 2048)
                self.assertEqual(policy["max_batch_tokens"], 300000)
                self.assertEqual(policy["tokenizer"], "cl100k_base")
                self.assertEqual(policy["api"], "openai")
                self.assertIs(policy["requires_input_type"], False)
                self.assertTrue(policy["model_revision"])
                self.assertEqual(policy["document_prefix"], "")
                self.assertEqual(policy["query_prefix"], "")

    def test_dimensions_are_sent_only_for_an_explicit_supported_choice(self):
        for dimensions in (1, 256, 1536, 3072):
            with self.subTest(dimensions=dimensions):
                policy = self.resolve(self.embedding_model("text-embedding-3-large", dimensions=dimensions))
                self.assertEqual(policy["dimensions"], dimensions)
                self.assertEqual(policy["request_dimensions"], dimensions)
                self.assertEqual(policy["default_dimensions"], 3072)
        policy = self.resolve(self.embedding_model("text-embedding-ada-002", dimensions=1536))
        self.assertEqual(policy["dimensions"], 1536)
        self.assertIsNone(policy["request_dimensions"])
        for name, dimensions in (
            ("text-embedding-ada-002", 1024),
            ("text-embedding-3-small", 1537),
            ("text-embedding-3-large", 3073),
            ("embed-english-v3.0", 512),
        ):
            with self.subTest(model=name, dimensions=dimensions):
                with self.assertRaisesRegex(ValueError, "dimensions"):
                    self.resolve(self.embedding_model(name, dimensions=dimensions))

    def test_ada_versions_use_their_actual_input_limits(self):
        for version, tokens in (("1", 2046), (1, 2046), ("2", 8192), (2, 8192)):
            with self.subTest(version=version):
                policy = self.resolve(self.model(model_name="text-embedding-ada-002", modelVersion=version))
                self.assertEqual(policy["max_input_tokens"], tokens)
                self.assertEqual(policy["model_revision"], f"text-embedding-ada-002:{version}")
                self.assertIsNone(policy["request_dimensions"])
        with self.assertRaisesRegex(ValueError, "documented limit"):
            self.resolve(self.model(
                model_name="text-embedding-ada-002", modelVersion="1",
                embedding_config={"max_input_tokens": 8192},
            ))
        unknown_version = self.model(model_name="text-embedding-ada-002", modelVersion="future")
        with self.assertRaisesRegex(ValueError, "version is not cataloged"):
            self.resolve(unknown_version)
        unknown_version["embedding_config"] = {
            "max_input_tokens": 1024,
            "model_revision": "administrator-verified-revision",
        }
        self.assertEqual(self.resolve(unknown_version)["max_input_tokens"], 1024)
        for version in (True, False, 0, [], {}, 1.5):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "version"):
                    self.resolve(self.model(model_name="text-embedding-ada-002", modelVersion=version))

    def test_known_model_limits_can_be_restricted_but_not_overstated(self):
        model = self.embedding_model(
            max_input_tokens=1024, max_batch_size=16, max_batch_tokens=4096,
        )
        policy = self.resolve(model)
        self.assertEqual(policy["max_input_tokens"], 1024)
        self.assertEqual(policy["max_batch_size"], 16)
        self.assertEqual(policy["max_batch_tokens"], 4096)
        for field, value in (
            ("max_input_tokens", 8193),
            ("max_batch_size", 2049),
            ("max_batch_tokens", 300001),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.resolve(self.embedding_model(**{field: value}))
        with self.assertRaisesRegex(ValueError, "maximum-length input"):
            self.resolve(self.embedding_model(max_batch_tokens=8191))

    def test_unknown_models_need_declared_dimensions_and_input_limits(self):
        for config in ({}, {"dimensions": 768}, {"max_input_tokens": 512}):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, "dimensions and max_input_tokens"):
                    self.resolve(self.embedding_model("private-model", **config))
        policy = self.resolve(self.embedding_model("private-model", dimensions=768, max_input_tokens=512))
        self.assertEqual(policy["dimensions"], 768)
        self.assertEqual(policy["default_dimensions"], 768)
        self.assertEqual(policy["min_dimensions"], 768)
        self.assertEqual(policy["max_dimensions"], 768)
        self.assertFalse(policy["supports_dimensions"])
        self.assertIsNone(policy["request_dimensions"])
        self.assertEqual(policy["max_input_tokens"], 512)
        self.assertEqual(policy["max_batch_size"], 16)
        self.assertEqual(policy["max_batch_tokens"], 8192)
        self.assertEqual(policy["tokenizer"], "conservative")
        self.assertEqual(policy["model_revision"], "")

    def test_only_explicit_legacy_imports_keep_historical_unknown_defaults(self):
        policy = self.resolve("historical-azure-deployment", legacy=True)
        self.assertEqual(policy["dimensions"], 1536)
        self.assertEqual(policy["max_input_tokens"], 8192)
        self.assertEqual(policy["tokenizer"], "cl100k_base")
        self.assertIsNone(policy["request_dimensions"])
        with self.assertRaises(ValueError):
            self.resolve("historical-azure-deployment")
        with self.assertRaises(ValueError):
            self.resolve("historical-azure-deployment", legacy="true")
        with self.assertRaises(ValueError):
            self.resolve(self.embedding_model("historical-azure-deployment", dimensions=False), legacy=True)
        model = self.embedding_model("text-embedding-3-large")
        self.assertEqual(self.resolve(model, legacy=True), self.resolve(model))

    def test_legacy_import_preserves_policy_revision_and_omitted_dimension_requests(self):
        for model in (
            {"deploymentName": "historical-private-deployment"},
            {"deploymentName": "private-deployment", "modelName": "private-model", "modelVersion": "r7"},
            {"deploymentName": "private-deployment", "modelName": "private-model", "context_window": "16384"},
            {"deploymentName": "ada-v1", "modelName": "text-embedding-ada-002", "modelVersion": "1"},
            {"deploymentName": "ada-v2", "modelName": "text-embedding-ada-002", "modelVersion": "2"},
            {"deploymentName": "small", "modelName": "text-embedding-3-small", "modelVersion": "1"},
            {"deploymentName": "small", "modelName": "text-embedding-3-small", "contextWindow": "4096"},
            {"deploymentName": "small", "modelName": "text-embedding-3-small", "maxTokens": 16384},
            {"deploymentName": "large", "modelName": "text-embedding-3-large"},
            {"deploymentName": "text-embedding-3-small"},
        ):
            with self.subTest(model=model):
                before = self.resolve(model, legacy=True)
                imported = {
                    **model, "id": "imported-model", "supportsEmbeddings": True,
                    "enabled_capabilities": [self.embeddings],
                }
                catalog = self.capabilities.get_model_catalog_capabilities(model, strict_identity=True)
                if not catalog or "embeddingPolicy" not in catalog:
                    imported["embedding_config"] = {
                        "dimensions": before["dimensions"],
                        "max_input_tokens": before["max_input_tokens"],
                    }
                normalized = self.connections.normalize_model_capability_fields(imported)
                after = self.resolve(normalized, legacy=True)
                self.assertEqual(before, after)
                self.assertIsNone(after["request_dimensions"])
                self.assertIsInstance(after["max_batch_tokens"], int)
                self.assertGreater(after["max_batch_tokens"], 0)
                for field in ("modelName", "modelVersion"):
                    self.assertEqual(normalized.get(field), model.get(field))
                self.assertEqual(self.resolve(normalized)["model_revision"], before["model_revision"])

    def test_legacy_context_aliases_follow_saved_precedence_and_conversion(self):
        fields = (
            "context_window", "contextWindow", "maxContextTokens",
            "context_length", "contextLength", "maxTokens",
        )
        for field in fields:
            for name in ("private-model", "text-embedding-3-small"):
                for value in (2048, " 4096 ", 16384, 4096.75, True):
                    with self.subTest(field=field, model=name, value=value):
                        model = self.model(model_name=name, **{field: value})
                        original = copy.deepcopy(model)
                        policy = self.resolve(model, legacy=True)
                        self.assertEqual(policy["max_input_tokens"], int(value))
                        self.assertIsInstance(policy["max_input_tokens"], int)
                        self.assertNotIsInstance(policy["max_input_tokens"], bool)
                        self.assertGreaterEqual(policy["max_batch_tokens"], policy["max_input_tokens"])
                        self.assertIsNone(policy["request_dimensions"])
                        self.assertEqual(model, original)
        for index, field in enumerate(fields):
            with self.subTest(first_positive_field=field):
                metadata = {key: 2048 + offset for offset, key in reversed(list(enumerate(fields)))}
                for skipped in fields[:index]:
                    metadata[skipped] = 0
                self.assertEqual(
                    self.resolve(self.model(model_name="private-model", **metadata), legacy=True)["max_input_tokens"],
                    2048 + index,
                )
        metadata = {
            "context_window": None,
            "contextWindow": "not-a-number",
            "maxContextTokens": float("nan"),
            "context_length": float("inf"),
            "contextLength": -1,
            "maxTokens": "3072",
        }
        self.assertEqual(self.resolve(self.model(**metadata), legacy=True)["max_input_tokens"], 3072)
        with self.assertRaisesRegex(ValueError, "max_input_tokens"):
            self.resolve(self.model(context_window=1048577, maxTokens=4096), legacy=True)

    def test_legacy_context_limits_override_catalog_only_during_import(self):
        for tokens in (1024, 16384, 524288):
            with self.subTest(tokens=tokens):
                model = self.embedding_model("text-embedding-3-small")
                model["context_window"] = tokens
                legacy_policy = self.resolve(model, legacy=True)
                current_policy = self.resolve(model)
                self.assertEqual(legacy_policy["max_input_tokens"], tokens)
                self.assertGreaterEqual(legacy_policy["max_batch_tokens"], tokens)
                self.assertEqual(current_policy["max_input_tokens"], 8192)
                self.assertEqual(legacy_policy["model_revision"], current_policy["model_revision"])
                self.assertIsNone(legacy_policy["request_dimensions"])
        unknown = self.model(
            model_name="private-model", supportsEmbeddings=True,
            embedding_config={"dimensions": 768}, context_window=4096,
        )
        with self.assertRaisesRegex(ValueError, "dimensions and max_input_tokens"):
            self.resolve(unknown)
        self.assertEqual(self.resolve(unknown, legacy=True)["max_input_tokens"], 4096)

    def test_canonical_context_overrides_remain_strict_even_with_legacy_aliases(self):
        model = self.embedding_model("text-embedding-3-small", max_input_tokens=1024)
        model["context_window"] = 4096
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.assertEqual(self.resolve(model, legacy=legacy)["max_input_tokens"], 1024)
                for value in (True, "1024", None, 8193):
                    with self.subTest(value=value):
                        invalid = copy.deepcopy(model)
                        invalid["embedding_config"]["max_input_tokens"] = value
                        with self.assertRaises(ValueError):
                            self.resolve(invalid, legacy=legacy)
                invalid = copy.deepcopy(model)
                invalid["embedding_config"]["contextWindow"] = 4096
                with self.assertRaisesRegex(ValueError, "unsupported fields"):
                    self.resolve(invalid, legacy=legacy)

    def test_legacy_context_getter_prefers_only_the_strict_canonical_limit(self):
        get_context = self.embedding_policy.get_legacy_embedding_context_tokens
        model = self.embedding_model(
            "text-embedding-3-large", dimensions=1024, max_input_tokens=2048,
            max_batch_size=2, max_batch_tokens=8192, model_revision="fixture-direct-revision",
            document_prefix="fixture-document-prefix", query_prefix="fixture-query-prefix",
            openai_compatible=False,
        )
        model.update(
            modelVersion="fixture-direct-version", api_key="fixture-secret",
            endpoint="https://private.example.invalid", supportsEmbeddings=True,
            context_window="4096", contextWindow=None, maxContextTokens=2048,
            context_length=0, contextLength=[], maxTokens=16384,
        )
        original = copy.deepcopy(model)
        self.assertEqual(get_context(model), 2048)
        self.assertIsInstance(get_context(model), int)
        self.assertEqual(model, original)
        for value in (None, {}, [], "", False):
            with self.subTest(value=value):
                self.assertIsNone(get_context(value))
        for config in (None, [], {}, {"dimensions": 1024}):
            with self.subTest(config=config):
                self.assertEqual(
                    get_context({"context_window": "4096", "embedding_config": config}),
                    4096,
                )
        self.assertEqual(get_context({
            "context_window": 1048577, "embedding_config": {"max_input_tokens": 2048},
        }), 2048)

    def test_resolved_apim_context_preserves_limits_without_direct_model_semantics(self):
        for root_limit, canonical_limit, expected in (
            (2048, None, 2048), (16384, None, 16384), (16384, 4096, 4096),
        ):
            with self.subTest(root_limit=root_limit, canonical_limit=canonical_limit):
                direct = self.embedding_model(
                    "text-embedding-3-large", dimensions=1024, max_batch_size=1,
                    max_batch_tokens=300000, model_revision="direct-model-revision",
                    document_prefix="direct document: ", query_prefix="direct query: ",
                    openai_compatible=False,
                )
                direct.update(context_window=str(root_limit), modelVersion="1")
                if canonical_limit is not None:
                    direct["embedding_config"]["max_input_tokens"] = canonical_limit
                apim = {
                    "deploymentName": "private-apim-deployment",
                    "embedding_config": {
                        "max_input_tokens": self.embedding_policy.get_legacy_embedding_context_tokens(direct),
                    },
                }
                policy = self.resolve(apim, legacy=True)
                self.assertEqual(policy["max_input_tokens"], expected)
                self.assertEqual(policy["dimensions"], 1536)
                self.assertIsNone(policy["request_dimensions"])
                self.assertEqual(policy["model_revision"], "")
                self.assertEqual(policy["document_prefix"], "")
                self.assertEqual(policy["query_prefix"], "")
                self.assertEqual(policy["max_batch_size"], 16)
                self.assertEqual(policy["max_batch_tokens"], expected * 16)
                self.assertEqual(policy["api"], "openai")

    def test_legacy_context_getter_rejects_invalid_canonical_limits_without_alias_fallback(self):
        get_context = self.embedding_policy.get_legacy_embedding_context_tokens
        for value in (None, True, False, 0, -1, "4096", 4096.0, [], {}, 1048577):
            with self.subTest(value=value):
                model = {
                    "context_window": 4096,
                    "embedding_config": {"max_input_tokens": value, "dimensions": 1024},
                }
                with self.assertRaisesRegex(ValueError, "max_input_tokens"):
                    get_context(model)
                with self.assertRaisesRegex(ValueError, "max_input_tokens"):
                    self.resolve({**model, "deploymentName": "private-apim"}, legacy=True)
        with self.assertRaisesRegex(ValueError, "max_input_tokens"):
            get_context({"context_window": 1048577, "maxTokens": 4096})

    def test_declared_custom_dimensions_are_fixed_output_metadata_not_a_resize_request(self):
        model = self.embedding_model(
            "custom-fixed-model", dimensions=768, max_input_tokens=2048,
        )
        model["supportsEmbeddings"] = True
        model = self.connections.normalize_model_capability_fields(model)
        self.assertTrue(self.connections.supports_model_capability(model, self.embeddings, "openai_compatible"))
        policy = self.resolve(model)
        self.assertEqual(policy["dimensions"], 768)
        self.assertFalse(policy["supports_dimensions"])
        self.assertIsNone(policy["request_dimensions"])
        self.assertEqual(policy["max_batch_tokens"], 32768)

    def test_config_validation_is_strict_and_does_not_mutate_or_echo_input(self):
        normalize = self.embedding_policy.normalize_embedding_config
        valid = {
            "dimensions": 768,
            "max_input_tokens": 512,
            "max_batch_size": 4,
            "max_batch_tokens": 2048,
            "model_revision": "  private-model:r2  ",
            "document_prefix": "document: \n",
            "query_prefix": "query: ",
            "openai_compatible": True,
        }
        original = copy.deepcopy(valid)
        normalized = normalize(valid)
        self.assertEqual(valid, original)
        self.assertIsNot(normalized, valid)
        self.assertEqual(normalized["model_revision"], "private-model:r2")
        self.assertEqual(normalized["document_prefix"], "document: \n")
        self.assertEqual(normalized["query_prefix"], "query: ")
        self.assertEqual(normalize({}), {})
        for value in (None, [], "", False, 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize(value)
        for field in ("api", "api_key", "endpoint", "input_type", "openapi", "tokenizer", "supports_dimensions"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError) as raised:
                    normalize({field: "fixture-private-value"})
                self.assertNotIn("fixture-private-value", str(raised.exception))
        for field in ("dimensions", "max_input_tokens", "max_batch_size", "max_batch_tokens"):
            for value in (None, True, False, 0, -1, 1.5, "1536", [], {}, 2**63):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        normalize({field: value})
        for field in ("model_revision", "document_prefix", "query_prefix"):
            for value in (None, True, 42, [], {}, "invalid\0value", "x" * 8193):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        normalize({field: value})
        for value in ("", "  ", "x" * 257):
            with self.subTest(revision=value):
                with self.assertRaises(ValueError):
                    normalize({"model_revision": value})
        for value in ("true", 1, None, []):
            with self.subTest(compatibility=value):
                with self.assertRaises(ValueError):
                    normalize({"openai_compatible": value})
        with self.assertRaises(ValueError):
            normalize({"max_input_tokens": 1024, "max_batch_tokens": 512})

    def test_prefixes_revisions_and_custom_batch_overrides_resolve_without_guessing(self):
        model = self.embedding_model(
            "private-model", dimensions=384, max_input_tokens=2048,
            max_batch_size=4, max_batch_tokens=4096,
            model_revision="private-model:r1", document_prefix="passage: ", query_prefix="query: ",
        )
        original = copy.deepcopy(model)
        policy = self.resolve(model)
        self.assertEqual(policy["document_prefix"], "passage: ")
        self.assertEqual(policy["query_prefix"], "query: ")
        self.assertEqual(policy["model_revision"], "private-model:r1")
        self.assertEqual(policy["max_batch_size"], 4)
        self.assertEqual(policy["max_batch_tokens"], 4096)
        self.assertEqual(model, original)
        policy["query_prefix"] = "changed"
        self.assertEqual(model, original)

    def test_malformed_catalog_policy_never_falls_back_to_legacy_defaults(self):
        original = self.capabilities.get_model_catalog_capabilities("text-embedding-3-small")
        base = original["embeddingPolicy"]
        policies = [
            None, [], "fixture-private-value", {}, {**base, "default_dimensions": True},
            {**base, "supports_dimensions": "true"}, {**base, "requires_input_type": 1},
            {**base, "min_dimensions": 2000}, {**base, "max_dimensions": 1000},
            {**base, "supports_dimensions": False}, {**base, "allowed_dimensions": []},
            {**base, "allowed_dimensions": [True, 1536]},
            {**base, "allowed_dimensions": [1536, 1536]},
            {**base, "allowed_dimensions": [512]},
            {**base, "max_input_tokens": "8192"}, {**base, "max_batch_tokens": 1},
            {**base, "tokenizer": "unknown"}, {**base, "api": "cohere-native"},
            {**base, "document_prefix": {}}, {**base, "model_revision": False},
            {**base, "model_context_tokens": 512}, {**base, "hosting_limits": []},
            {**base, "hosting_limits": {"azure": {"max_input_tokens": 9000}}},
            {**base, "versions": []}, {**base, "versions": {"1": {}}},
            {**base, "api_key": "fixture-private-value"},
        ]
        for policy in policies:
            with self.subTest(policy=policy):
                flags = {**original, "embeddingPolicy": policy}
                with mock.patch.object(self.capabilities, "_CATALOG_CACHE", {"invalid-model": flags}):
                    for legacy in (False, True):
                        with self.assertRaises(ValueError) as raised:
                            self.resolve("invalid-model", legacy=legacy)
                        self.assertNotIn("fixture-private-value", str(raised.exception))
                    status = self.connections.resolve_model_capability("invalid-model", self.embeddings)
                    self.assertFalse(status["supported"])
                    self.assertEqual(status["source"], "policy")
                    self.assertNotIn("fixture-private-value", status["reason"])

    def test_cohere_hosting_context_and_operation_contracts_remain_distinct(self):
        catalog = self.capabilities.get_model_catalog_capabilities("embed-v-4-0")["embeddingPolicy"]
        self.assertEqual(catalog["model_context_tokens"], 128000)
        self.assertEqual(catalog["hosting_limits"]["azure"]["max_input_tokens"], 512)
        for name in ("embed-v-4-0", "embed-v4.0"):
            with self.subTest(model=name):
                native = self.resolve(name)
                self.assertEqual(native["api"], "unsupported")
                self.assertIs(native["requires_input_type"], True)
                self.assertEqual(native["max_input_tokens"], 512)
                self.assertEqual(native["max_batch_size"], 96)
                self.assertEqual(native["max_batch_tokens"], 49152)
                self.assertEqual(native["allowed_dimensions"], [256, 512, 1024, 1536])
                self.assertIsNone(native["request_dimensions"])
                gateway = self.resolve(self.embedding_model(name, openai_compatible=True))
                self.assertEqual(gateway["api"], "openai")
                self.assertTrue(gateway["requires_input_type"])
                self.assertEqual(gateway["max_input_tokens"], 512)
                verified = self.resolve(self.embedding_model(
                    name, openai_compatible=True, max_input_tokens=128000,
                ))
                self.assertEqual(verified["max_input_tokens"], 128000)
                self.assertEqual(verified["max_batch_tokens"], 128000)
        with self.assertRaises(ValueError):
            self.resolve(self.embedding_model("embed-v4.0", max_input_tokens=128001, openai_compatible=True))
        for dimensions in (256, 512, 1024, 1536):
            with self.subTest(dimensions=dimensions):
                native = self.resolve(self.embedding_model("embed-v4.0", dimensions=dimensions))
                self.assertIsNone(native["request_dimensions"])
                gateway = self.resolve(self.embedding_model(
                    "embed-v4.0", dimensions=dimensions, openai_compatible=True,
                ))
                self.assertEqual(gateway["request_dimensions"], dimensions)
        with self.assertRaises(ValueError):
            self.resolve(self.embedding_model("embed-v4.0", dimensions=768, openai_compatible=True))

    def test_required_native_task_semantics_cannot_inherit_openai_compatibility(self):
        flags = self.capabilities.get_model_catalog_capabilities("text-embedding-3-small")
        flags["embeddingPolicy"]["requires_input_type"] = True
        with mock.patch.object(self.capabilities, "_CATALOG_CACHE", {"task-model": flags}):
            self.assertEqual(self.resolve("task-model")["api"], "unsupported")
            self.assertEqual(
                self.resolve(self.embedding_model("task-model", openai_compatible=True))["api"],
                "openai",
            )
        for name in ("text-embedding-3-small", "embed-v4.0"):
            with self.subTest(model=name):
                self.assertEqual(
                    self.resolve(self.embedding_model(name, openai_compatible=False))["api"],
                    "unsupported",
                )


class EmbeddingCatalogTests(IsolatedConnectionsTestCase):
    def test_verified_embedding_aliases_have_sourced_separate_output_flags(self):
        document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        source_ids = {source["id"] for source in document["sources"]}
        entries = [
            model for model in document["models"]
            if model.get("capabilities", {}).get("generatesEmbeddings") is True
        ]
        self.assertGreaterEqual(len(entries), 6)
        self.assertIn("generatesEmbeddings", document["capabilityFields"])
        for entry in entries:
            self.assertTrue(set(entry["sourceIds"]).issubset(source_ids))
            for name in [entry["id"], *entry["aliases"]]:
                with self.subTest(model=name):
                    flags = self.capabilities.get_model_catalog_capabilities(name, strict_identity=True)
                    self.assertIs(flags["generatesEmbeddings"], True)
                    self.assertIs(flags["generatesText"], False)
                    self.assertIs(flags["generatesImages"], False)
                    self.assertEqual(flags["embeddingPolicy"], entry["embeddingPolicy"])
                    policy = self.embedding_policy.resolve_embedding_policy(name)
                    self.assertGreater(policy["max_input_tokens"], 0)
        for name in (
            "Cohere-embed-v3-english", "embed-english-v3.0",
            "Cohere-embed-v3-multilingual", "embed-multilingual-v3.0",
        ):
            with self.subTest(model=name):
                policy = self.embedding_policy.resolve_embedding_policy(name)
                self.assertEqual(policy["dimensions"], 1024)
                self.assertEqual(policy["max_input_tokens"], 512)
                self.assertEqual(policy["api"], "unsupported")

    def test_nested_policies_return_independent_copies(self):
        policy = self.capabilities.get_model_catalog_capabilities("embed-v4.0")["embeddingPolicy"]
        policy["allowed_dimensions"].append(768)
        policy["hosting_limits"]["azure"]["max_input_tokens"] = 128000
        ada = self.capabilities.get_model_catalog_capabilities("text-embedding-ada-002")["embeddingPolicy"]
        ada["versions"]["1"]["max_input_tokens"] = 8192
        self.assertEqual(self.embedding_policy.resolve_embedding_policy("embed-v4.0")["max_input_tokens"], 512)
        self.assertNotIn(
            768, self.capabilities.get_model_catalog_capabilities("embed-v4.0")["embeddingPolicy"]["allowed_dimensions"]
        )
        self.assertEqual(self.embedding_policy.resolve_embedding_policy(
            {"modelName": "text-embedding-ada-002", "modelVersion": "1"}
        )["max_input_tokens"], 2046)

    def test_unknown_names_display_labels_and_snapshots_are_not_embedding_evidence(self):
        for model in (
            "some-embedding-model", "text-embedding-3-small-production",
            "text-embedding-3-small-2026-09-16", "embed-v4.0-unverified",
            {"id": "text-embedding-3-small"},
            {"displayName": "text-embedding-3-small"},
            {"displayName": "text-embedding-3-small", "deploymentName": "private-deployment"},
            {"modelName": "private-model", "deploymentName": "text-embedding-3-small"},
            {"modelName": "private-model", "behavior_name": "text-embedding-3-small"},
            {"deploymentName": "private-model", "name": "text-embedding-3-small"},
        ):
            with self.subTest(model=model):
                self.assertIsNone(self.capabilities.get_model_catalog_capabilities(model, strict_identity=True))
                support = self.connections.resolve_model_capability(model, self.embeddings)
                self.assertFalse(support["supported"])
                self.assertTrue(support["reason"])
        for model in (
            "TEXT_EMBEDDING_3_SMALL", {"deploymentName": "text-embedding-3-small"},
            {"modelName": " ", "behavior_name": "embed-v4.0", "displayName": "Any label"},
        ):
            with self.subTest(model=model):
                self.assertIsNotNone(self.capabilities.get_model_catalog_capabilities(model, strict_identity=True))


class EmbeddingCapabilityTests(IsolatedConnectionsTestCase):
    def embedding_model(self, name="text-embedding-3-small", **fields):
        return self.model(model_name=name, **fields)

    def test_capability_is_ungated_and_uses_the_existing_registration_contract(self):
        definition = self.connections.get_capability_definition(self.embeddings)
        self.assertEqual(definition.selection_key, "embedding_model_selection")
        self.assertEqual(definition.catalog_flag, "generatesEmbeddings")
        self.assertEqual(definition.supported_providers, ("aoai", "aifoundry", "new_foundry", "openai_compatible"))
        self.assertEqual(definition.api_routes, ("azure_openai", "openai"))
        self.assertEqual(definition.feature_flag, "")
        settings = self.settings([self.endpoint(models=[self.embedding_model()])])
        settings.update({
            "embedding_model_selection": self.selection(),
            "enable_multi_model_endpoints": False,
            "enable_image_generation": False,
        })
        self.assertTrue(self.connections.is_capability_enabled({}, self.embeddings))
        binding = self.connections.resolve_capability_binding(settings, self.embeddings)
        client = object()
        factory = mock.Mock(return_value=client)
        self.connections.register_capability_client_factory(self.embeddings, factory)
        self.assertIs(self.connections.create_capability_client(binding, settings), client)
        factory.assert_called_once_with(binding, settings)

    def test_eligibility_requires_a_supported_provider_and_operation_contract(self):
        for provider in ("aoai", "aifoundry", "new_foundry", "openai_compatible"):
            with self.subTest(provider=provider):
                self.assertTrue(self.connections.supports_model_capability(
                    self.embedding_model(), self.embeddings, provider,
                ))
                native = self.embedding_model("embed-v4.0", supportsEmbeddings=True)
                support = self.connections.resolve_model_capability(native, self.embeddings, provider)
                self.assertFalse(support["supported"])
                self.assertEqual(support["source"], "provider")
                self.assertIn("gateway", support["reason"])
                self.assertEqual(support["api"], "unsupported")
                native["embedding_config"] = {"openai_compatible": True}
                self.assertTrue(self.connections.supports_model_capability(native, self.embeddings, provider))
        for provider in ("unknown-provider", "cohere", "ollama"):
            with self.subTest(provider=provider):
                support = self.connections.resolve_model_capability(
                    self.embedding_model(supportsEmbeddings=True), self.embeddings, provider,
                )
                self.assertFalse(support["supported"])
                self.assertEqual(support["source"], "provider")

    def test_explicit_false_overrides_catalog_and_gateway_declarations(self):
        for field in ("supportsEmbeddings", "supports_embeddings"):
            for name in ("text-embedding-3-small", "embed-v4.0"):
                with self.subTest(field=field, model=name):
                    model = self.embedding_model(
                        name, **{field: False}, embedding_config={"openai_compatible": True},
                    )
                    status = self.connections.resolve_model_capability(model, self.embeddings)
                    self.assertFalse(status["supported"])
                    self.assertEqual(status["source"], "declared")
        for value in ("true", 1, False, None):
            flags = {"generatesEmbeddings": value}
            with mock.patch.object(self.capabilities, "_CATALOG_CACHE", {"unverified": flags}):
                self.assertFalse(self.connections.supports_model_capability("unverified", self.embeddings))
        for fields in (
            {"supportsEmbeddings": True, "supports_embeddings": False},
            {"supportsEmbeddings": False, "supports_embeddings": True},
            {"supportsEmbeddings": "true"},
            {"supportsEmbeddings": None},
            {"supports_embeddings": 1},
        ):
            with self.subTest(fields=fields):
                status = self.connections.resolve_model_capability(
                    self.embedding_model(**fields), self.embeddings,
                )
                self.assertFalse(status["supported"])
                self.assertEqual(status["source"], "declared")

    def test_unknown_declarations_require_limits_not_a_name_heuristic_or_publication(self):
        for model in (
            self.embedding_model("private-model", supportsEmbeddings=True),
            self.embedding_model("private-model", enabled_capabilities=[self.embeddings]),
            self.embedding_model("private-model", capabilities={"generatesEmbeddings": True}),
            self.embedding_model("private-model", embedding_config={"dimensions": 768, "max_input_tokens": 512}),
        ):
            with self.subTest(model=model):
                status = self.connections.resolve_model_capability(model, self.embeddings)
                self.assertFalse(status["supported"])
                self.assertTrue(status["reason"])
        model = self.embedding_model(
            "private-model", supportsEmbeddings=True,
            embedding_config={"dimensions": 768, "max_input_tokens": 512},
        )
        self.assertTrue(self.connections.supports_model_capability(model, self.embeddings, "openai_compatible"))
        self.assertFalse(self.connections.supports_model_capability(model, self.chat))

    def test_embedding_models_and_custom_provider_never_enter_chat_image_or_vision_choices(self):
        for name in (
            "text-embedding-ada-002", "text-embedding-3-small", "text-embedding-3-large",
            "embed-v4.0", "embed-english-v3.0", "embed-multilingual-v3.0",
        ):
            with self.subTest(model=name):
                model = self.embedding_model(
                    name, supportsChat=True, supportsImageGeneration=True, supportsVision=True,
                )
                status = self.connections.describe_model_capabilities(model)
                self.assertFalse(status[self.chat]["supported"])
                self.assertFalse(status[self.images]["supported"])
                self.assertFalse(status["vision"]["supported"])
                self.assertFalse(self.capabilities.is_vision_capable_model(model))
        for model in (
            self.model(supportsChat=True, supportsImageGeneration=True, supportsVision=True),
            self.model(model_name="legacy-private-chat"),
        ):
            for provider in ("openai_compatible", " OPENAI_COMPATIBLE "):
                with self.subTest(model=model, provider=provider):
                    endpoint = self.endpoint(provider=provider, models=[model])
                    self.assertEqual(self.connections.build_capability_model_catalog([endpoint], self.chat), [])
                    self.assertEqual(self.connections.build_capability_model_catalog([endpoint], self.images), [])
                    self.assertFalse(self.connections.describe_model_capabilities(model, provider)["vision"]["supported"])

    def test_publication_is_separate_from_model_support(self):
        for fields in (
            {"enabled_capabilities": []},
            {"enabled_capabilities": [self.chat, self.images]},
            {"enabled": False},
        ):
            with self.subTest(fields=fields):
                model = self.embedding_model(**fields)
                status = self.connections.describe_model_capabilities(model)[self.embeddings]
                self.assertTrue(status["supported"])
                self.assertFalse(status["available"])
        for fields in ({}, {"enabled_capabilities": [self.embeddings]}):
            self.assertTrue(self.connections.supports_model_capability(self.embedding_model(**fields), self.embeddings))

    def test_normalization_preserves_legacy_models_but_validates_embedding_metadata(self):
        normalize = self.connections.normalize_model_capability_fields
        legacy = self.model(model_name="private-legacy-chat")
        self.assertNotIn("embedding_config", normalize(legacy))
        self.assertNotIn("supportsEmbeddings", normalize(legacy))
        self.assertEqual(normalize({**legacy, "embedding_config": {}})["embedding_config"], {})
        model = self.embedding_model(
            "private-model", supportsEmbeddings=True,
            enabled_capabilities=[self.embeddings, self.embeddings],
            embedding_config={"dimensions": 768, "max_input_tokens": 512},
            capability_status={"embeddings": {"supported": False}},
        )
        original = copy.deepcopy(model)
        normalized = normalize(model)
        self.assertEqual(model, original)
        self.assertEqual(normalized["enabled_capabilities"], [self.embeddings])
        self.assertIs(normalized["supportsEmbeddings"], True)
        self.assertNotIn("capability_status", normalized)
        normalized["embedding_config"]["dimensions"] = 999
        self.assertEqual(model, original)
        for fields in (
            {"supportsEmbeddings": "true"}, {"supportsEmbeddings": 1},
            {"supports_embeddings": "false"},
            {"supportsEmbeddings": True},
            {"embedding_config": None}, {"embedding_config": []},
            {"embedding_config": {"dimensions": 0}},
            {"embedding_config": {"api_key": "fixture-secret"}},
        ):
            with self.subTest(fields=fields):
                error = self.assert_connection_error(
                    "invalid_model_selection", normalize, {**legacy, **fields},
                )
                self.assertNotIn("fixture-secret", error.public_message)
        self.assertEqual(normalize(self.embedding_model())["modelName"], "text-embedding-3-small")
        self.assertEqual(normalize(self.embedding_model("embed-v4.0"))["modelName"], "embed-v4.0")

    def test_picker_policies_are_safe_id_qualified_copies(self):
        model = self.embedding_model(
            embedding_config={
                "dimensions": 512, "model_revision": "fixture-private-revision",
                "document_prefix": "https://private.example.invalid/", "query_prefix": "fixture-private-prefix",
            },
            api_key="fixture-model-secret",
        )
        endpoints = [
            self.endpoint("resource-b", name="Zebra", models=[model]),
            self.endpoint("resource-a", name="Alpha", models=[model]),
            self.endpoint("native-only", models=[self.embedding_model("embed-v4.0")]),
            self.endpoint("unpublished", models=[self.embedding_model(enabled_capabilities=[])]),
        ]
        original = copy.deepcopy(endpoints)
        choices = self.connections.build_capability_model_catalog(endpoints, self.embeddings)
        self.assertEqual([choice["endpoint_id"] for choice in choices], ["resource-a", "resource-b"])
        self.assertTrue(all(choice["model_id"] == "shared-model" for choice in choices))
        self.assertEqual(choices[0]["embedding_policy"]["dimensions"], 512)
        self.assertEqual(choices[0]["embedding_policy"]["request_dimensions"], 512)
        payload = json.dumps(choices)
        for secret in (
            "fixture-api-key", "fixture-client-secret", "fixture-vault-secret-reference",
            "fixture-model-secret", "fixture-private-revision", "fixture-private-prefix",
            "private.example.invalid", "resource-one.example.invalid", "operation_settings",
        ):
            self.assertNotIn(secret, payload)
        choices[0]["embedding_policy"]["dimensions"] = 1
        self.assertEqual(choices[1]["embedding_policy"]["dimensions"], 512)
        self.assertEqual(endpoints, original)

    def test_three_defaults_resolve_independently_without_rebinding_by_model_name(self):
        endpoint = self.endpoint(models=[
            self.model("chat-model"), self.model("image-model", "gpt-image-1"),
            self.model("embedding-model", "text-embedding-3-small"),
        ])
        endpoint["connection"]["operation_settings"][self.embeddings] = {"api": "azure_openai"}
        settings = self.settings([endpoint])
        settings["default_model_selection"] = self.selection(model_id="chat-model")
        settings["image_generation_model_selection"] = self.selection(model_id="image-model")
        settings["embedding_model_selection"] = self.selection(model_id="embedding-model")
        for capability, model_id in (
            (self.chat, "chat-model"), (self.images, "image-model"), (self.embeddings, "embedding-model"),
        ):
            with self.subTest(capability=capability):
                binding = self.connections.resolve_capability_binding(settings, capability)
                self.assertEqual(binding.model["id"], model_id)
        binding = self.connections.resolve_capability_binding(settings, self.embeddings)
        self.assertEqual(binding.operation_settings, {"api": "azure_openai"})
        endpoint["models"][-1]["id"] = "replacement-model"
        resolved, reason = self.connections.resolve_capability_model_selection(
            settings["embedding_model_selection"], [endpoint], self.embeddings,
        )
        self.assertEqual(resolved, self.empty_selection)
        self.assertTrue(reason)

    def test_embedding_handoff_is_independent_and_never_restores_legacy_after_clear(self):
        marker = self.connections.EMBEDDING_MIGRATION_VERSION_KEY
        version = self.connections.EMBEDDING_MIGRATION_VERSION
        self.assertEqual(marker, "ai_connections_embedding_migration_version")
        self.assertEqual(version, 1)
        self.assertEqual(self.connections.EMBEDDING_SELECTION_KEY, "embedding_model_selection")
        for value in (version, version + 1):
            self.assertTrue(self.connections.embedding_connection_import_is_complete({marker: value}))
            self.assertTrue(self.connections.embedding_settings_use_connections({marker: value}))
            self.assertFalse(self.connections.image_settings_use_connections({marker: value}))
        for settings in (
            None, [], {}, {marker: 0}, {marker: True}, {marker: False},
            {marker: "1"}, {marker: 1.0}, {self.connections.IMAGE_MIGRATION_VERSION_KEY: 1},
            {self.connections.IMAGE_SELECTION_KEY: self.empty_selection},
        ):
            with self.subTest(settings=settings):
                self.assertFalse(self.connections.embedding_connection_import_is_complete(settings))
                self.assertFalse(self.connections.embedding_settings_use_connections(settings))
        for selection in (None, {}, self.empty_selection):
            settings = {
                "embedding_model_selection": selection,
                "embedding_model": {"selected": ["legacy-model"]},
                "azure_openai_embedding_endpoint": "https://legacy.example.invalid",
                "azure_openai_embedding_key": "fixture-legacy-key",
            }
            self.assertTrue(self.connections.embedding_settings_use_connections(settings))
            self.assert_connection_error(
                "model_configuration_unavailable", self.connections.resolve_capability_binding,
                settings, self.embeddings,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
