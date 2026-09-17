# test_model_catalog_rebase_integration.py
"""
Offline regression tests for audited token and React V2 metadata coexistence.
Version: 0.261.122
Implemented in: 0.261.122

Protect the strict schema's three record kinds, historical source reviews,
provider-qualified image operations, and independent reasoning policy resolver.
Operation eligibility must never widen exact numeric-capacity matching or turn
unknown limits into a budget. No external services or Git history are required.
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


OPERATION_ONLY_IDS = {
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    "o1", "o3", "o3-mini", "o4-mini", "gpt-image-2", "gpt-image-1.5",
    "gpt-image-1", "gpt-image-1-mini", "dall-e-3", "gpt-6-astra",
    "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
    "MAI-Image-2.5", "MAI-Image-2.5-Flash", "MAI-Image-2.5-Pro",
    "MAI-Image-2.6", "MAI-Image-2.6-Flash",
    "FLUX.2-pro", "FLUX.2-flex", "FLUX.1-Kontext-pro", "FLUX-1.1-pro",
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
RESPONSES_IMAGE_IDS = {
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
    "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano",
    "gpt-5.2", "gpt-5.1", "gpt-5", "gpt-5-nano",
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-nano", "o3", "gpt-6-astra",
}
DIRECT_IMAGE_IDS = {
    "gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini",
    "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
}
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
        "image-profiles-openai-tools", "image-profiles-openai-images",
        "image-profiles-mai", "image-profiles-flux", "image-profiles-government",
        "openai-gpt6-astra",
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
        sol["imageProfiles"]["openai"] = "azure-images"
        models["gpt-image-1.5"]["imageLifecycle"]["openai"] = "current"
        models["o3-pro"]["reasoningPolicy"]["default_effort"] = "none"
        records.clear()

        self.assertEqual(
            capabilities.get_model_capability_catalog_records(), self.catalog["models"]
        )
        budget = capabilities.resolve_model_token_budget("gpt-5.6-sol", provider="openai")
        self.assertEqual(budget.context_window, 1050000)
        self.assertEqual(
            capabilities.get_model_catalog_capabilities("gpt-5.6-sol")["imageProfiles"],
            {"openai": "openai-responses"},
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

    def test_image_bindings_separate_publishers_and_hosting_contracts(self):
        for model_id in RESPONSES_IMAGE_IDS:
            self.assertEqual(self.models[model_id]["imageProfiles"], {"openai": "openai-responses"})
            self.assertTrue(self.models[model_id]["capabilities"]["imageGenerationTool"])
            self.assertFalse(self.models[model_id]["capabilities"]["generatesImages"])
        for model_id in DIRECT_IMAGE_IDS:
            self.assertEqual(self.models[model_id]["imageProfiles"], {
                "openai": "openai-images", "azure_openai": "azure-images",
            })
        for model_id in OPERATION_ONLY_IDS:
            if model_id.startswith("MAI-"):
                self.assertEqual(self.models[model_id]["provider"], "microsoft")
                self.assertEqual(self.models[model_id]["imageProfiles"], {"foundry": "mai-images"})
        for model_id, profile_id in (
            ("FLUX.2-pro", "flux-2-pro"), ("FLUX.2-flex", "flux-2-flex"),
            ("FLUX.1-Kontext-pro", "flux-kontext"), ("FLUX-1.1-pro", "flux-1.1"),
        ):
            self.assertEqual(self.models[model_id]["provider"], "blackforestlabs")
            self.assertEqual(self.models[model_id]["imageProfiles"], {"foundry": profile_id})
        self.assertEqual(self.sources["image-profiles-flux"]["provider"], "microsoft")
        self.assertEqual(self.models["gpt-image-1.5"]["imageLifecycle"], {
            "openai": "deprecated", "azure_openai": "limited_access_preview",
        })
        self.assertEqual(self.models["dall-e-3"]["imageLifecycle"], {
            "openai": "retired", "azure_openai": "retired",
        })

    def test_image_operation_profiles_remain_independent_and_isolated(self):
        for profile_id, api, editing, masking in (
            ("openai-responses", "responses", True, True),
            ("openai-images", "images", True, True),
            ("azure-images", "images", True, True),
            ("mai-images", "mai", True, False),
            ("flux-2-pro", "flux", True, False),
            ("flux-2-flex", "flux", True, False),
            ("flux-kontext", "flux", True, False),
            ("flux-1.1", "flux", False, False),
        ):
            with self.subTest(profile=profile_id):
                profile = capabilities.get_image_operation_profile(profile_id)
                self.assertEqual(profile, self.catalog["imageOperationProfiles"][profile_id])
                self.assertEqual((profile["api"], profile["editing"], profile["masking"]),
                                 (api, editing, masking))
                self.assertEqual(profile["availability"], {
                    "commercial": "documented", "government": "unknown", "unknown": "unknown",
                })
                profile["sizes"].clear()
                self.assertTrue(capabilities.get_image_operation_profile(profile_id)["sizes"])
        kontext = capabilities.get_image_operation_profile("flux-kontext")
        self.assertEqual(kontext["modelPath"], "flux-kontext-pro")
        self.assertEqual(kontext["transport"], "openai_images")
        self.assertEqual(kontext["maxReferenceImages"], 1)
        mai = capabilities.get_image_operation_profile("mai-images")
        self.assertEqual((mai["minDimension"], mai["maxPixels"]), (768, 1048576))

    def test_historical_metadata_reviews_are_not_relabelled_as_token_audits(self):
        for reviewed_at, source_ids in SOURCE_REVIEW_HISTORY.items():
            for source_id in source_ids:
                with self.subTest(source=source_id):
                    self.assertEqual(self.sources[source_id]["verifiedAt"], reviewed_at)
                    self.assertLessEqual(reviewed_at, self.catalog["lastUpdated"])

    def test_metadata_only_variants_reject_token_fields(self):
        audited = self.models["gpt-5.6-sol"]
        for model_id, field in product(
            ("gpt-4", "gpt-4o", "gpt-6-astra", "gpt-image-2"), TOKEN_METADATA_FIELDS
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
            (("imageProfiles", "private"), "openai-responses"),
            (("imageLifecycle",), {"openai": "unknown"}),
        ):
            with self.subTest(path=path):
                record = copy.deepcopy(self.models["gpt-6-astra"])
                target = record
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValidationError):
                    self.validate_model(record)

    def test_image_operation_schema_requires_true_positive_integers(self):
        for field, invalid in product(
            ("maxMaskBytes", "maxReferenceImages", "minDimension", "maxPixels"),
            (True, 0, -1, 1.0, 1.5, "1024"),
        ):
            with self.subTest(field=field, value=invalid):
                document = copy.deepcopy(self.catalog)
                document["imageOperationProfiles"]["openai-images"][field] = invalid
                with self.assertRaises(ValidationError):
                    self.validator.validate(document)

    def test_image_operation_schema_rejects_inconsistent_or_unbounded_metadata(self):
        for profile_id, changes in (
            ("mai-images", {"masking": True}),
            ("openai-images", {"editing": False}),
            ("openai-images", {"sourceIds": []}),
            ("openai-images", {"availability": {
                "commercial": "documented", "government": "unknown", "unknown": "documented",
            }}),
            ("openai-images", {"unexpected": True}),
            ("openai-images", {"sizes": ["0x1024"]}),
            ("openai-images", {"outputFormats": []}),
            ("openai-images", {"api": "guessed"}),
        ):
            with self.subTest(profile=profile_id, changes=changes):
                document = copy.deepcopy(self.catalog)
                document["imageOperationProfiles"][profile_id].update(changes)
                with self.assertRaises(ValidationError):
                    self.validator.validate(document)
        document = copy.deepcopy(self.catalog)
        del document["imageOperationProfiles"]["flux-2-pro"]["modelPath"]
        with self.assertRaises(ValidationError):
            self.validator.validate(document)

    def test_integrity_rejects_unresolved_metadata_sources_and_cross_host_profiles(self):
        for target in ("reasoning", "operation", "model", "profile", "host", "capability"):
            with self.subTest(target=target):
                document = copy.deepcopy(self.catalog)
                models = {record["id"]: record for record in document["models"]}
                if target == "reasoning":
                    models["o3-pro"]["reasoningPolicy"]["sourceIds"].append("missing")
                elif target == "operation":
                    document["imageOperationProfiles"]["openai-images"]["sourceIds"].append("missing")
                elif target == "model":
                    models["gpt-6-astra"]["sourceIds"].append("missing")
                elif target == "profile":
                    models["gpt-6-astra"]["imageProfiles"]["openai"] = "missing"
                elif target == "host":
                    models["gpt-6-astra"]["imageProfiles"] = {"azure_openai": "openai-responses"}
                else:
                    models["gpt-6-astra"]["capabilities"]["imageGenerationTool"] = False
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(document)

    def test_integrity_rejects_new_identity_provenance_and_dimension_corruption(self):
        for target in ("identity", "alias", "publisher", "date", "size", "capacity"):
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
                    sources["image-profiles-mai"]["provider"] = "openai"
                elif target == "date":
                    sources["image-profiles-mai"]["verifiedAt"] = "2099-01-01"
                elif target == "size":
                    document["imageOperationProfiles"]["mai-images"]["sizes"].append("512x512")
                else:
                    models["gpt-4"]["contextWindow"] = 128000
                with self.assertRaises(ValueError):
                    validate_catalog_integrity(document)


if __name__ == "__main__":
    unittest.main()
