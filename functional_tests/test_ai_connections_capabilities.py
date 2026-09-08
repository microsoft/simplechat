# test_ai_connections_capabilities.py
"""
Pure functional tests for shared AI Connections capability and binding contracts.
Version: 0.261.105
Implemented in: 0.261.105

Exercise the real leaf modules and shipped catalog without Flask, settings-store,
Azure, or inference clients. Each test loads private module instances and restores
sys.modules, isolating catalog caches, capability definitions, and client factories.
"""

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
CATALOG_PATH = APP_ROOT / "static" / "json" / "model_capabilities.json"


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class IsolatedConnectionsTestCase(unittest.TestCase):
    def setUp(self):
        module_patch = mock.patch.dict(sys.modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        self.capabilities = _load_module(
            "functions_model_capabilities", "functions_model_capabilities.py"
        )
        self.connections = _load_module(
            "_test_ai_connections_capabilities", "functions_ai_connections.py"
        )
        self.chat = self.connections.CHAT_CAPABILITY
        self.images = self.connections.IMAGE_GENERATION_CAPABILITY
        self.empty_selection = {
            "endpoint_id": "",
            "model_id": "",
            "provider": "",
        }

    def model(self, model_id="shared-model", model_name="gpt-5.6-sol", **fields):
        model = {
            "id": model_id,
            "modelName": model_name,
            "deploymentName": "shared-deployment",
            "displayName": "Shared model",
            "enabled": True,
        }
        model.update(fields)
        return model

    def endpoint(self, endpoint_id="resource-one", models=None, **fields):
        endpoint = {
            "id": endpoint_id,
            "name": "Team Azure",
            "provider": "aoai",
            "enabled": True,
            "connection": {
                "endpoint": "https://resource-one.example.invalid/openai",
                "api_key": "fixture-api-key",
                "client_secret": "fixture-client-secret",
                "key_vault_secret_id": "fixture-vault-secret-reference",
                "operation_settings": {
                    "chat": {"api_version": "legacy-chat-version"},
                    "image_generation": {"api_version": "v1"},
                },
            },
            "models": [self.model()] if models is None else models,
        }
        endpoint.update(fields)
        return endpoint

    def selection(self, endpoint_id="resource-one", model_id="shared-model"):
        return {
            "endpoint_id": endpoint_id,
            "model_id": model_id,
            "provider": "aoai",
        }

    def settings(self, endpoints=None):
        return {
            "model_endpoints": [self.endpoint()] if endpoints is None else endpoints,
            "default_model_selection": self.selection(),
            "image_generation_model_selection": self.selection(),
            "enable_multi_model_endpoints": False,
            "enable_image_generation": True,
        }

    def assert_connection_error(self, code, function, *args, **kwargs):
        with self.assertRaises(self.connections.AIConnectionError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(str(raised.exception), raised.exception.public_message)
        return raised.exception


class CapabilityResolutionTests(IsolatedConnectionsTestCase):
    def test_leaf_modules_import_without_application_or_service_dependencies(self):
        original_import = __import__
        forbidden = {
            "app", "config", "flask", "azure", "openai", "semantic_kernel",
            "functions_settings", "functions_appinsights", "app_settings_cache",
        }

        def guarded_import(name, *args, **kwargs):
            if name.split(".")[0] in forbidden:
                raise AssertionError(f"Pure capability modules imported {name}")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            _load_module("functions_model_capabilities", "functions_model_capabilities.py")
            module = _load_module(
                "_test_ai_connections_import_boundary", "functions_ai_connections.py"
            )
            self.assertTrue(module.supports_model_capability("gpt-5.6-sol"))

    def test_verified_gpt_models_use_responses_without_native_image_output(self):
        models = (
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6",
            "gpt-5.5", "gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini",
            "gpt-5.4-nano", "gpt-5.2", "gpt-5.1", "gpt-5",
            "gpt-5-pro", "gpt-5-nano", "gpt-4o", "gpt-4o-mini",
            "gpt-4.1", "gpt-4.1-nano", "o3", "o3-mini",
        )
        for name in models:
            with self.subTest(model=name):
                flags = self.capabilities.get_model_catalog_capabilities(name)
                self.assertIs(flags["imageGenerationTool"], True)
                self.assertIs(flags["generatesImages"], False)
                support = self.connections.resolve_model_capability(name, self.images)
                self.assertEqual(
                    support,
                    {"supported": True, "source": "catalog", "reason": "", "api": "responses"},
                )
                self.assertTrue(self.connections.supports_model_capability(name, self.chat))

    def test_known_variants_do_not_inherit_parent_tool_support(self):
        models = (
            "gpt-5-mini", "gpt-4.1-mini", "o1", "o4-mini",
            "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex",
            "gpt-5.1-codex-mini", "gpt-5.1-codex-max", "gpt-5-codex",
            "gpt-chat-latest", "gpt-5.3-chat", "gpt-5.2-chat",
            "gpt-5.1-chat", "gpt-5-chat",
        )
        for name in models:
            with self.subTest(model=name):
                self.assertFalse(self.connections.supports_model_capability(name, self.images))
                self.assertTrue(self.connections.supports_model_capability(name, self.chat))

    def test_unverified_underlying_variants_cannot_inherit_verified_image_tools(self):
        models = (
            "gpt-4o-audio-preview", "gpt-4o-transcribe", "gpt-4o-realtime-preview",
            "gpt-4o-mini-transcribe", "gpt-5.6-sol-unknown-variant",
        )
        for name in models:
            with self.subTest(model=name):
                model = self.model(model_name=name, deploymentName="arbitrary-deployment")
                self.assertFalse(
                    self.connections.supports_model_capability(model, self.images),
                    "A known prefix does not verify an explicitly named underlying model variant.",
                )

    def test_aliases_and_model_snapshots_keep_verified_metadata(self):
        models = (
            "gpt-5.6", "GPT_5.6_Sol", "gpt-5.6-terra-2026-07-09",
            "gpt-5.6-luna-2026-07-09", "gpt-4o-2024-11-20",
        )
        for name in models:
            with self.subTest(model=name):
                self.assertTrue(
                    self.connections.supports_model_capability(
                        self.model(model_name=name, deploymentName="production"), self.images
                    )
                )

    def test_vision_and_function_calling_are_not_image_generation_evidence(self):
        model = self.model(
            model_name="local-vision-deployment",
            supportsVision=True,
            toolCalling=True,
            capabilities={"imageGenerationTool": True, "generatesImages": True},
        )
        description = self.connections.describe_model_capabilities(model)
        self.assertTrue(description["vision"]["supported"])
        self.assertTrue(description[self.chat]["supported"])
        self.assertFalse(description[self.images]["supported"])
        self.assertEqual(description[self.images]["source"], "unknown")

    def test_image_tool_support_does_not_require_vision(self):
        description = self.connections.describe_model_capabilities("o3-mini")
        self.assertTrue(description[self.images]["supported"])
        self.assertFalse(description["vision"]["supported"])
        self.assertTrue(description[self.chat]["supported"])

    def test_unknown_legacy_chat_aliases_remain_chat_only(self):
        for model in (
            "legacy-chat-prod", {"deploymentName": "old-team-model"},
            {"name": "private-llm"}, self.model(model_name="unknown-model"),
        ):
            with self.subTest(model=model):
                self.assertTrue(self.connections.supports_model_capability(model, self.chat))
                self.assertFalse(self.connections.supports_model_capability(model, self.images))
                support = self.connections.resolve_model_capability(model, self.chat)
                self.assertEqual(support["source"], "legacy")

    def test_reasoning_only_catalog_records_do_not_disable_legacy_chat(self):
        for name in ("gpt-4", "gpt-4.5", "gpt-35-turbo", "o1-mini", "o1-preview", "o3-pro"):
            with self.subTest(model=name):
                catalog = self.capabilities.get_model_catalog_capabilities(name)
                self.assertIn("reasoningPolicy", catalog)
                self.assertNotIn("generatesText", catalog)
                self.assertTrue(self.connections.supports_model_capability(name, self.chat))
                self.assertFalse(self.connections.supports_model_capability(name, self.images))

    def test_capability_identity_uses_nonblank_canonical_reasoning_metadata(self):
        for model in (
            {"modelName": " ", "behavior_name": "gpt-5.6-luna", "deploymentName": "production"},
            {"modelName": 17, "behavior_name": "gpt-5.6-luna", "deploymentName": "production"},
            {"modelName": " ", "deploymentName": "gpt-5.6-luna"},
        ):
            with self.subTest(model=model):
                self.assertTrue(self.connections.supports_model_capability(model, self.chat))
                self.assertTrue(self.connections.supports_model_capability(model, self.images))
        unknown = {
            "modelName": "unknown-private-model", "behavior_name": "gpt-5.6-luna",
            "deploymentName": "gpt-5.6-luna",
        }
        self.assertFalse(self.connections.supports_model_capability(unknown, self.images))

    def test_empty_models_do_not_gain_chat_or_image_support(self):
        for model in (None, {}, "", "  "):
            with self.subTest(model=model):
                self.assertFalse(self.connections.supports_model_capability(model, self.chat))
                self.assertFalse(self.connections.supports_model_capability(model, self.images))

    def test_direct_image_families_are_never_chat_or_text_vision_models(self):
        for name in (
            "gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini",
            "dall-e-3", "dalle-3", "dall-e-2", "GPT_IMAGE_1",
        ):
            with self.subTest(model=name):
                model = self.model(model_name=name, supportsChat=True, supportsVision=True)
                description = self.connections.describe_model_capabilities(model)
                self.assertFalse(description[self.chat]["supported"])
                self.assertFalse(description["vision"]["supported"])
                self.assertTrue(description[self.images]["supported"])
                self.assertEqual(description[self.images]["api"], "images")
                self.assert_connection_error(
                    "model_capability_unavailable",
                    self.connections.require_model_capability,
                    model,
                    self.chat,
                )

    def test_non_chat_model_families_do_not_gain_legacy_chat_support(self):
        for name in ("text-embedding-3-large", "whisper-1", "tts-1"):
            with self.subTest(model=name):
                self.assertFalse(self.connections.supports_model_capability(name, self.chat))
                self.assertFalse(self.connections.supports_model_capability(name, self.images))

    def test_native_non_openai_images_need_a_provider_compatible_adapter(self):
        flags = {"generatesText": False, "processesImages": True, "generatesImages": True}
        with mock.patch.object(self.capabilities, "_CATALOG_CACHE", {"vendor-image": flags}):
            model = self.model(model_name="vendor-image")
            support = self.connections.resolve_model_capability(model, self.images)
            self.assertFalse(support["supported"])
            self.assertEqual(support["source"], "provider")
            self.assertFalse(self.connections.supports_model_capability(model, self.chat))
            declared = {**model, "supportsImageGeneration": True, "image_generation_api": "images"}
            self.assertEqual(
                self.connections.resolve_model_capability(declared, self.images)["api"],
                "images",
            )

    def test_shipped_non_openai_image_models_do_not_imply_azure_image_apis(self):
        document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        native_models = [
            model for model in document["models"]
            if model.get("provider") != "openai"
            and model.get("capabilities", {}).get("generatesImages") is True
        ]
        self.assertTrue(native_models)
        for entry in native_models:
            for provider in ("aoai", "aifoundry", "new_foundry"):
                with self.subTest(model=entry["id"], provider=provider):
                    model = self.model(model_name=entry["id"])
                    support = self.connections.resolve_model_capability(
                        model, self.images, provider
                    )
                    self.assertFalse(support["supported"])
                    self.assertEqual(support["source"], "provider")
                    self.assertEqual(support["api"], "")
                    self.assertTrue(support["reason"])
                    self.assert_connection_error(
                        "model_capability_unavailable",
                        self.connections.require_model_capability,
                        model,
                        self.images,
                        provider,
                    )

    def test_only_boolean_catalog_image_tool_support_is_accepted(self):
        for flag in (False, "true", 1, None):
            with self.subTest(flag=flag):
                flags = {"generatesText": True, "imageGenerationTool": flag}
                with mock.patch.object(self.capabilities, "_CATALOG_CACHE", {"test-model": flags}):
                    self.assertFalse(
                        self.connections.supports_model_capability("test-model", self.images)
                    )

    def test_explicit_image_decisions_override_catalog_and_direct_families(self):
        for field in ("supportsImageGeneration", "supports_image_generation"):
            with self.subTest(field=field):
                for name in ("gpt-5.6-sol", "gpt-image-1"):
                    self.assertFalse(self.connections.supports_model_capability(
                        self.model(model_name=name, **{field: False}), self.images
                    ))
                for route in ("images", "responses"):
                    model = self.model(
                        model_name="private-compatible-model",
                        image_generation_api=route,
                        **{field: True},
                    )
                    support = self.connections.resolve_model_capability(model, self.images)
                    self.assertTrue(support["supported"])
                    self.assertEqual(support["source"], "declared")
                    self.assertEqual(support["api"], route)

    def test_explicit_unknown_image_support_defaults_to_responses(self):
        model = self.model(model_name="private-compatible-model", supportsImageGeneration=True)
        self.assertEqual(
            self.connections.resolve_model_capability(model, self.images)["api"], "responses"
        )
        self.assertIs(
            self.connections.require_model_capability(model, self.images), model
        )

    def test_image_support_cannot_enable_an_unimplemented_provider_adapter(self):
        model = self.model(model_name="gpt-image-1", supportsImageGeneration=True)
        for provider in ("unknown-provider", "ollama"):
            with self.subTest(provider=provider):
                support = self.connections.resolve_model_capability(model, self.images, provider)
                self.assertFalse(support["supported"])
                self.assertEqual(support["source"], "provider")
        for provider in ("aoai", "aifoundry", "new_foundry"):
            with self.subTest(provider=provider):
                self.assertTrue(
                    self.connections.supports_model_capability(model, self.images, provider)
                )

    def test_catalog_lookup_returns_a_copy(self):
        flags = self.capabilities.get_model_catalog_capabilities("gpt-5.6-sol")
        flags["imageGenerationTool"] = False
        self.assertTrue(
            self.capabilities.get_model_catalog_capabilities("gpt-5.6-sol")["imageGenerationTool"]
        )


class ModelAvailabilityTests(IsolatedConnectionsTestCase):
    def test_publication_is_distinct_from_technical_capability(self):
        model = self.model(enabled_capabilities=[self.images])
        description = self.connections.describe_model_capabilities(model)
        self.assertTrue(description[self.chat]["supported"])
        self.assertFalse(description[self.chat]["available"])
        self.assertTrue(description[self.images]["supported"])
        self.assertTrue(description[self.images]["available"])
        self.assertFalse(self.connections.supports_model_capability(model, self.chat))
        self.assert_connection_error(
            "model_capability_unavailable",
            self.connections.require_model_capability,
            model,
            self.chat,
        )

    def test_publication_does_not_establish_unproven_technical_support(self):
        model = self.model(
            model_name="unknown-chat-model",
            enabled_capabilities=[self.chat, self.images],
        )
        self.assertFalse(self.connections.supports_model_capability(model, self.images))
        self.assertTrue(self.connections.supports_model_capability(model, self.chat))

    def test_empty_publication_and_disabled_models_are_unavailable(self):
        for model in (
            self.model(enabled_capabilities=[]),
            self.model(enabled=False, enabled_capabilities=[self.chat, self.images]),
        ):
            with self.subTest(model=model):
                description = self.connections.describe_model_capabilities(model)
                for capability in (self.chat, self.images):
                    self.assertTrue(description[capability]["supported"])
                    self.assertFalse(description[capability]["available"])
                    self.assertFalse(
                        self.connections.supports_model_capability(model, capability)
                    )

    def test_legacy_models_without_publication_fields_stay_enabled(self):
        model = self.model()
        model.pop("enabled")
        for capability in (self.chat, self.images):
            self.assertTrue(self.connections.supports_model_capability(model, capability))

    def test_normalization_preserves_unrelated_metadata_without_mutating_input(self):
        model = self.model(
            enabled_capabilities=[self.images, self.chat, self.images],
            supportsChat=True,
            supportsImageGeneration=False,
            image_generation_api="images",
            responseLength=4096,
            custom_metadata={"label": "keep me"},
            capability_status={"chat": {"supported": False}},
        )
        original = copy.deepcopy(model)
        normalized = self.connections.normalize_model_capability_fields(model)
        self.assertEqual(model, original)
        self.assertIsNot(normalized, model)
        self.assertEqual(normalized["enabled_capabilities"], [self.images, self.chat])
        self.assertNotIn("capability_status", normalized)
        self.assertEqual(normalized["custom_metadata"], original["custom_metadata"])
        self.assertEqual(normalized["responseLength"], 4096)
        self.assertIs(normalized["supportsImageGeneration"], False)

    def test_normalization_rejects_invalid_flags_routes_and_publication(self):
        cases = [
            {"supportsChat": "true"},
            {"supportsChat": 1},
            {"supportsImageGeneration": "false"},
            {"supportsImageGeneration": None},
            {"enabled_capabilities": "chat"},
            {"enabled_capabilities": None},
            {"enabled_capabilities": [self.chat, "not-implemented"]},
            {"enabled_capabilities": [True]},
            {"image_generation_api": "chat"},
            {"image_generation_api": "https://untrusted.example.invalid"},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assert_connection_error(
                    "invalid_model_selection",
                    self.connections.normalize_model_capability_fields,
                    self.model(**fields),
                )
        self.assertEqual(
            self.connections.normalize_model_capability_fields(
                self.model(enabled_capabilities=[])
            )["enabled_capabilities"],
            [],
        )


class ProjectionAndSelectionTests(IsolatedConnectionsTestCase):
    def test_chat_and_image_projections_never_mutate_the_registry(self):
        endpoints = [
            self.endpoint(models=[
                self.model(),
                self.model("image-only", "gpt-image-1"),
                self.model("legacy-chat", "legacy-private-chat"),
                self.model("disabled", enabled=False),
            ]),
            self.endpoint("disabled-resource", enabled=False),
        ]
        original = copy.deepcopy(endpoints)
        chat = self.connections.filter_model_endpoints_by_capability(endpoints, self.chat)
        images = self.connections.filter_model_endpoints_by_capability(endpoints, self.images)
        self.assertEqual([model["id"] for model in chat[0]["models"]], ["shared-model", "legacy-chat"])
        self.assertEqual([model["id"] for model in images[0]["models"]], ["shared-model", "image-only"])
        self.assertEqual(endpoints, original)
        chat[0]["models"][0]["displayName"] = "changed projection"
        images[0]["connection"]["api_key"] = "changed projection key"
        self.assertEqual(endpoints, original)

    def test_preserve_empty_keeps_connection_identity_without_publishing_models(self):
        endpoints = [
            self.endpoint("image-resource", models=[self.model("image", "gpt-image-1")]),
            self.endpoint("disabled-resource", enabled=False),
            self.endpoint("empty-resource", models=[]),
            None,
            "invalid-record",
        ]
        self.assertEqual(
            self.connections.filter_model_endpoints_by_capability(endpoints, self.chat), []
        )
        projection = self.connections.filter_model_endpoints_by_capability(
            endpoints, self.chat, preserve_empty=True
        )
        self.assertEqual(
            [endpoint["id"] for endpoint in projection],
            ["image-resource", "disabled-resource", "empty-resource"],
        )
        self.assertTrue(all(endpoint["models"] == [] for endpoint in projection))

    def test_catalog_choices_keep_same_deployment_on_distinct_resources(self):
        endpoints = [
            self.endpoint("resource-b", name="Zebra resource"),
            self.endpoint("resource-a", name="Alpha resource"),
        ]
        choices = self.connections.build_capability_model_catalog(endpoints, self.images)
        self.assertEqual(
            [(choice["endpoint_id"], choice["model_id"]) for choice in choices],
            [("resource-a", "shared-model"), ("resource-b", "shared-model")],
        )
        self.assertEqual(
            [choice["deployment_name"] for choice in choices],
            ["shared-deployment", "shared-deployment"],
        )
        for choice in choices:
            resolved, reason = self.connections.resolve_capability_model_selection(
                choice, endpoints, self.images
            )
            self.assertIsNone(reason)
            self.assertEqual(resolved["endpoint_id"], choice["endpoint_id"])

    def test_public_catalog_and_descriptions_do_not_expose_secrets(self):
        model = self.model(api_key="fixture-model-secret", private_metadata={"secret": "private"})
        endpoint = self.endpoint(models=[model], auth={"password": "fixture-password"})
        original = copy.deepcopy(endpoint)
        choices = self.connections.build_capability_model_catalog([endpoint], self.images)
        description = self.connections.describe_model_capabilities(model)
        self.assertEqual(
            set(choices[0]),
            {"endpoint_id", "model_id", "provider", "connection_name", "label", "deployment_name", "capability"},
        )
        self.assertEqual(
            set(choices[0]["capability"]), {"supported", "source", "reason", "api"}
        )
        payload = json.dumps({"models": choices, "description": description})
        for secret in (
            "fixture-api-key", "fixture-client-secret", "fixture-vault-secret-reference",
            "fixture-model-secret", "fixture-password", "private_metadata",
            "resource-one.example.invalid", "operation_settings",
        ):
            self.assertNotIn(secret, payload)
        choices[0]["capability"]["supported"] = False
        self.assertEqual(endpoint, original)

    def test_idless_and_disabled_records_are_not_public_choices(self):
        endpoints = [
            self.endpoint("", models=[self.model()]),
            self.endpoint("empty-model", models=[{"modelName": "gpt-5.6-sol"}]),
            self.endpoint("disabled-endpoint", enabled=False),
            self.endpoint("disabled-model", models=[self.model(enabled=False)]),
            self.endpoint("legacy-id", models=[{
                "deploymentName": "gpt-5.6-sol",
                "enabled": True,
            }]),
        ]
        choices = self.connections.build_capability_model_catalog(endpoints, self.images)
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0]["endpoint_id"], "legacy-id")
        self.assertEqual(choices[0]["model_id"], "gpt-5.6-sol")

    def test_selection_uses_stored_provider_not_caller_connection_data(self):
        endpoints = [self.endpoint(provider="new_foundry")]
        selection = {
            "endpoint_id": " resource-one ",
            "model_id": " shared-model ",
            "provider": "caller-controlled-provider",
            "endpoint": "https://untrusted.example.invalid",
            "api_key": "caller-controlled-key",
        }
        original = copy.deepcopy(selection)
        resolved, reason = self.connections.resolve_capability_model_selection(
            selection, endpoints, self.images
        )
        self.assertIsNone(reason)
        self.assertEqual(resolved, {
            "endpoint_id": "resource-one",
            "model_id": "shared-model",
            "provider": "new_foundry",
        })
        self.assertEqual(selection, original)

    def test_invalidated_defaults_clear_without_choosing_another_model(self):
        valid_alternative = self.endpoint("other-resource", models=[self.model("other-model")])
        cases = [
            [],
            [self.endpoint(enabled=False)],
            [self.endpoint(models=[])],
            [self.endpoint(models=[self.model(enabled=False)])],
            [self.endpoint(models=[self.model(enabled_capabilities=[self.chat])])],
            [self.endpoint(models=[self.model(model_name="unknown-chat-model")])],
            [self.endpoint(provider="unsupported-provider")],
        ]
        for endpoints in cases:
            with self.subTest(endpoints=endpoints):
                endpoints = endpoints + [valid_alternative]
                original = copy.deepcopy(endpoints)
                resolved, reason = self.connections.resolve_capability_model_selection(
                    self.selection(), endpoints, self.images
                )
                self.assertEqual(resolved, self.empty_selection)
                self.assertTrue(reason)
                self.assertNotIn("fixture-api-key", reason)
                self.assertEqual(endpoints, original)

    def test_removed_default_does_not_rebind_by_deployment_name(self):
        endpoints = [
            self.endpoint(models=[self.model("replacement-id")]),
            self.endpoint("other-resource"),
        ]
        resolved, reason = self.connections.resolve_capability_model_selection(
            self.selection(), endpoints, self.images
        )
        self.assertEqual(resolved, self.empty_selection)
        self.assertTrue(reason)

    def test_empty_partial_and_non_mapping_selections_stay_empty(self):
        selections = (
            None, "", [], {}, self.empty_selection,
            {"endpoint_id": "resource-one"},
            {"model_id": "shared-model"},
        )
        for selection in selections:
            with self.subTest(selection=selection):
                resolved, reason = self.connections.resolve_capability_model_selection(
                    selection, [self.endpoint()], self.images
                )
                self.assertEqual(resolved, self.empty_selection)
                self.assertIsNone(reason)
                resolved["endpoint_id"] = "not-a-global-default"
                self.assertEqual(self.connections.EMPTY_MODEL_SELECTION, self.empty_selection)

    def test_binding_uses_independent_defaults_and_operation_profiles(self):
        endpoints = [self.endpoint(models=[
            self.model("chat-default"),
            self.model("image-default", "gpt-image-1"),
        ])]
        settings = self.settings(endpoints)
        settings["default_model_selection"] = self.selection(model_id="chat-default")
        settings["image_generation_model_selection"] = self.selection(model_id="image-default")
        original = copy.deepcopy(settings)
        chat = self.connections.resolve_capability_binding(settings, self.chat)
        images = self.connections.resolve_capability_binding(settings, self.images)
        self.assertEqual(chat.selection["model_id"], "chat-default")
        self.assertEqual(images.selection["model_id"], "image-default")
        self.assertEqual(chat.operation_settings, {"api_version": "legacy-chat-version"})
        self.assertEqual(images.operation_settings, {"api_version": "v1"})
        self.assertEqual(chat.endpoint["connection"]["api_key"], "fixture-api-key")
        self.assertEqual(images.endpoint["connection"]["api_key"], "fixture-api-key")
        images.endpoint["connection"]["api_key"] = "changed-binding-key"
        images.model["displayName"] = "changed-binding-model"
        images.selection["model_id"] = "changed-binding-selection"
        self.assertEqual(settings, original)

    def test_binding_resolves_the_exact_resource_and_current_credentials(self):
        endpoints = [self.endpoint(), self.endpoint("resource-two")]
        endpoints[1]["connection"]["api_key"] = "resource-two-original-key"
        settings = self.settings(endpoints)
        explicit = self.selection(endpoint_id="resource-two")
        binding = self.connections.resolve_capability_binding(settings, self.images, explicit)
        self.assertEqual(binding.endpoint["id"], "resource-two")
        self.assertEqual(binding.endpoint["connection"]["api_key"], "resource-two-original-key")
        endpoints[1]["connection"]["api_key"] = "resource-two-rotated-key"
        refreshed = self.connections.resolve_capability_binding(settings, self.images, explicit)
        self.assertEqual(refreshed.endpoint["connection"]["api_key"], "resource-two-rotated-key")
        self.assertEqual(binding.endpoint["connection"]["api_key"], "resource-two-original-key")

    def test_missing_binding_is_a_safe_configuration_error(self):
        settings = self.settings()
        settings["image_generation_model_selection"] = self.empty_selection.copy()
        error = self.assert_connection_error(
            "model_configuration_unavailable",
            self.connections.resolve_capability_binding,
            settings,
            self.images,
        )
        self.assertNotIn("fixture-api-key", error.public_message)
        self.assertIn("image generation", error.public_message.lower())

    def test_cleared_shared_selection_never_reactivates_legacy_image_settings(self):
        for selection in (None, {}, self.empty_selection):
            with self.subTest(selection=selection):
                settings = self.settings()
                settings.update({
                    "image_generation_model_selection": selection,
                    "image_gen_model": {"selected": ["dall-e-3"]},
                    "azure_openai_image_gen_endpoint": "https://legacy.example.invalid",
                    "azure_openai_image_gen_key": "legacy-fixture-key",
                })
                self.assertTrue(self.connections.image_settings_use_connections(settings))
                self.assert_connection_error(
                    "model_configuration_unavailable",
                    self.connections.resolve_capability_binding,
                    settings,
                    self.images,
                )

    def test_only_a_completed_integer_migration_marker_disables_legacy_fallback(self):
        marker = self.connections.IMAGE_MIGRATION_VERSION_KEY
        version = self.connections.IMAGE_MIGRATION_VERSION
        for value in (version, version + 1, version + 10):
            with self.subTest(marker=value):
                self.assertTrue(self.connections.image_connection_import_is_complete({marker: value}))
                self.assertTrue(self.connections.image_settings_use_connections({marker: value}))
        for settings in (
            None, [], {}, {marker: version - 1}, {marker: True},
            {marker: False}, {marker: str(version)}, {marker: float(version + 1)},
        ):
            with self.subTest(settings=settings):
                self.assertFalse(self.connections.image_connection_import_is_complete(settings))
                self.assertFalse(self.connections.image_settings_use_connections(settings))

    def test_operation_profile_validation_rejects_malformed_configuration(self):
        cases = (
            {"connection": ["invalid"]},
            {"connection": {"operation_settings": ["invalid"]}},
            {"connection": {"operation_settings": {self.images: ["invalid"]}}},
        )
        for endpoint in cases:
            with self.subTest(endpoint=endpoint):
                self.assert_connection_error(
                    "invalid_model_selection",
                    self.connections.get_connection_operation_settings,
                    endpoint,
                    self.images,
                )
        self.assertEqual(
            self.connections.get_connection_operation_settings({"connection": {}}, self.images),
            {},
        )


class CapabilityExtensionTests(IsolatedConnectionsTestCase):
    def test_only_implemented_capabilities_and_no_clients_ship_in_the_leaf_registry(self):
        self.assertEqual(set(self.connections.CAPABILITY_DEFINITIONS), {self.chat, self.images})
        self.assertEqual(self.connections._CLIENT_FACTORIES, {})

    def test_dummy_future_capability_reuses_catalog_binding_and_client_contracts(self):
        capability = "test_future_operation"
        selection_key = "test_future_model_selection"

        def support_resolver(model, provider):
            return {
                "supported": model.get("modelName") == "test-future-model",
                "source": "provider",
                "api": "test-future-api",
            }

        definition = self.connections.CapabilityDefinition(
            key=capability,
            label="Test future operation",
            selection_key=selection_key,
            catalog_flag="testFutureOutput",
            supported_providers=("new_foundry",),
            feature_flag="enable_test_future_operation",
            api_routes=("test-future-api",),
            support_resolver=support_resolver,
        )
        client = object()
        factory = mock.Mock(return_value=client)
        self.connections.register_capability(definition, client_factory=factory)
        endpoint = self.endpoint(
            provider="new_foundry",
            models=[self.model(
                model_name="test-future-model",
                enabled_capabilities=[capability],
            )],
        )
        settings = self.settings([endpoint])
        settings[selection_key] = self.selection()
        settings["enable_test_future_operation"] = True
        original = copy.deepcopy(settings)
        catalog = self.connections.build_capability_model_catalog([endpoint], capability)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["capability"]["api"], "test-future-api")
        self.assertFalse(self.connections.supports_model_capability(endpoint["models"][0], self.chat))
        binding = self.connections.resolve_capability_binding(settings, capability)
        self.assertEqual(binding.selection["provider"], "new_foundry")
        self.assertIs(self.connections.create_capability_client(binding, settings), client)
        factory.assert_called_once_with(binding, settings)
        self.assertEqual(settings, original)
        self.assertFalse(self.connections.supports_model_capability(
            endpoint["models"][0], capability, "aoai"
        ))

    def test_future_catalog_flag_and_boolean_support_resolver_are_reusable(self):
        definition = self.connections.CapabilityDefinition(
            "test_catalog_operation", "Test catalog operation",
            "test_catalog_selection", "testOutput",
        )
        self.connections.register_capability(definition)
        flags = {"generatesText": True, "testOutput": True}
        with mock.patch.object(self.capabilities, "_CATALOG_CACHE", {"test-model": flags}):
            self.assertTrue(self.connections.supports_model_capability(
                "test-model", definition.key
            ))
            self.assertFalse(self.connections.supports_model_capability(
                "unknown-model", definition.key
            ))
        boolean_definition = self.connections.CapabilityDefinition(
            "test_boolean_operation", "Test boolean operation",
            "test_boolean_selection", "unused",
            support_resolver=lambda model, provider: model == "test-supported",
        )
        self.connections.register_capability(boolean_definition)
        self.assertTrue(self.connections.supports_model_capability(
            "test-supported", boolean_definition.key
        ))
        self.assertFalse(self.connections.supports_model_capability(
            "test-unsupported", boolean_definition.key
        ))

    def test_dummy_future_adapter_can_omit_a_feature_flag_and_use_its_own_api(self):
        definition = self.connections.CapabilityDefinition(
            key="test_ungated_operation",
            label="Test ungated operation",
            selection_key="test_ungated_model_selection",
            catalog_flag="unused",
            api_routes=("test-custom-api",),
            support_resolver=lambda model, provider: {
                "supported": model.get("modelName") == "test-future-model",
                "api": "test-custom-api",
            },
        )
        client = object()
        factory = mock.Mock(return_value=client)
        self.connections.register_capability(definition, client_factory=factory)
        model = self.connections.normalize_model_capability_fields(self.model(
            model_name="test-future-model",
            enabled_capabilities=[definition.key],
        ))
        settings = self.settings([self.endpoint(models=[model])])
        settings["enable_image_generation"] = False
        settings[definition.selection_key] = self.selection()
        self.assertEqual(definition.feature_flag, "")
        self.assertEqual(
            self.connections.get_capability_definition(definition.key).api_routes,
            ("test-custom-api",),
        )
        self.assertTrue(self.connections.is_capability_enabled({}, definition.key))
        self.assertTrue(self.connections.is_capability_enabled(settings, definition.key))
        self.assertFalse(self.connections.is_capability_enabled(settings, self.chat))
        self.assertFalse(self.connections.is_capability_enabled(settings, self.images))
        binding = self.connections.resolve_capability_binding(settings, definition.key)
        self.assertIs(self.connections.create_capability_client(binding, settings), client)
        factory.assert_called_once_with(binding, settings)
        self.assertEqual(
            self.connections.resolve_model_capability(model, definition.key)["api"],
            "test-custom-api",
        )

    def test_image_client_gate_is_independent_of_chat_connections_mode(self):
        settings = self.settings()
        self.assertFalse(settings["enable_multi_model_endpoints"])
        binding = self.connections.resolve_capability_binding(settings, self.images)
        client = object()
        factory = mock.Mock(return_value=client)
        self.connections.register_capability_client_factory(self.images, factory)
        self.assertIs(self.connections.create_capability_client(binding, settings), client)
        settings["enable_image_generation"] = False
        self.assert_connection_error(
            "capability_disabled",
            self.connections.create_capability_client,
            binding,
            settings,
        )
        self.assertEqual(factory.call_count, 1)

    def test_client_creation_requires_an_implemented_adapter(self):
        settings = self.settings()
        binding = self.connections.resolve_capability_binding(settings, self.images)
        self.assert_connection_error(
            "unsupported_capability",
            self.connections.create_capability_client,
            binding,
            settings,
        )
        self.assert_connection_error(
            "unsupported_capability",
            self.connections.register_capability_client_factory,
            "not-implemented",
            lambda binding, settings: object(),
        )
        with self.assertRaises(TypeError):
            self.connections.register_capability_client_factory(self.images, object())

    def test_invalid_registration_does_not_mutate_the_registry(self):
        original = dict(self.connections.CAPABILITY_DEFINITIONS)
        with self.assertRaises(ValueError):
            self.connections.register_capability(original[self.chat])
        with self.assertRaises(ValueError):
            self.connections.register_capability({"key": "not-code-defined"})
        with self.assertRaises(ValueError):
            self.connections.register_capability(self.connections.CapabilityDefinition(
                "", "Missing key", "test_selection", "testFlag",
            ))
        for definition, factory in (
            (self.connections.CapabilityDefinition(
                "test_bad_factory", "Bad factory", "test_selection", "testFlag",
            ), "not-callable"),
            (self.connections.CapabilityDefinition(
                "test_bad_resolver", "Bad resolver", "test_selection", "testFlag",
                support_resolver="not-callable",
            ), None),
        ):
            with self.subTest(definition=definition):
                with self.assertRaises(TypeError):
                    self.connections.register_capability(definition, client_factory=factory)
        self.assertEqual(self.connections.CAPABILITY_DEFINITIONS, original)
        self.assertEqual(self.connections._CLIENT_FACTORIES, {})

    def test_malformed_future_support_descriptions_are_rejected(self):
        for index, result in enumerate((None, [], "yes", {"supported": "true"})):
            with self.subTest(result=result):
                definition = self.connections.CapabilityDefinition(
                    f"test_bad_support_{index}", "Bad support",
                    "test_selection", "unused",
                    support_resolver=lambda model, provider, value=result: value,
                )
                self.connections.register_capability(definition)
                self.assert_connection_error(
                    "invalid_model_selection",
                    self.connections.supports_model_capability,
                    "test-model",
                    definition.key,
                )

    def test_future_support_description_whitelists_public_fields(self):
        adapter_result = {
            "supported": True,
            "source": "test-adapter",
            "reason": "The adapter supports this operation.",
            "api": "test-custom-api",
            "connection": {
                "endpoint": "https://adapter-private.example.invalid",
                "api_key": "fixture-adapter-key",
            },
            "provider_error": "fixture-provider-private-detail",
        }
        original = copy.deepcopy(adapter_result)
        definition = self.connections.CapabilityDefinition(
            key="test_public_support",
            label="Test public support",
            selection_key="test_public_support_selection",
            catalog_flag="unused",
            support_resolver=lambda model, provider: adapter_result,
        )
        self.connections.register_capability(definition)
        model = self.model(enabled_capabilities=[definition.key])
        support = self.connections.resolve_model_capability(model, definition.key)
        expected = {
            field: adapter_result[field]
            for field in ("supported", "source", "reason", "api")
        }
        self.assertEqual(support, expected)
        choices = self.connections.build_capability_model_catalog(
            [self.endpoint(models=[model])], definition.key
        )
        description = self.connections.describe_model_capabilities(model)[definition.key]
        self.assertEqual(choices[0]["capability"], expected)
        self.assertEqual(description, {**expected, "available": True})
        payload = json.dumps({"models": choices, "description": description})
        for private_value in (
            "fixture-adapter-key", "adapter-private.example.invalid",
            "fixture-provider-private-detail", "provider_error",
        ):
            self.assertNotIn(private_value, payload)
        self.assertEqual(adapter_result, original)


class CatalogMetadataTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.models = {model["id"]: model for model in self.document["models"]}
        self.sources = {source["id"]: source for source in self.document["sources"]}

    def test_sources_and_model_identifiers_are_unique_and_resolvable(self):
        self.assertEqual(len(self.models), len(self.document["models"]))
        self.assertEqual(len(self.sources), len(self.document["sources"]))
        identifiers = []
        for model in self.models.values():
            identifiers.extend([model["id"]] + model.get("aliases", []))
            with self.subTest(model=model["id"]):
                source_ids = model.get("sourceIds") or model.get("reasoningPolicy", {}).get("sourceIds")
                self.assertTrue(source_ids)
                self.assertTrue(set(source_ids).issubset(self.sources))
                if "imageGenerationTool" in model.get("capabilities", {}):
                    self.assertIsInstance(model["capabilities"]["imageGenerationTool"], bool)
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_each_positive_tool_flag_has_a_model_specific_official_source(self):
        for model in self.models.values():
            if model.get("capabilities", {}).get("imageGenerationTool") is not True:
                continue
            with self.subTest(model=model["id"]):
                urls = [urlparse(self.sources[source]["url"]) for source in model["sourceIds"]]
                self.assertTrue(any(
                    url.hostname == "developers.openai.com"
                    and url.path == f"/api/docs/models/{model['id']}"
                    for url in urls
                ))
                self.assertIs(model["capabilities"]["generatesImages"], False)
                self.assertIn("azure-openai-responses", model["sourceIds"])

    def test_shared_catalog_entries_retain_image_and_reasoning_metadata(self):
        for name in ("gpt-4o", "gpt-4.1", "o1", "o3", "o3-mini", "o4-mini"):
            with self.subTest(model=name):
                self.assertIn("capabilities", self.models[name])
                self.assertIn("reasoningPolicy", self.models[name])
                self.assertTrue(self.models[name]["reasoningPolicy"]["sourceIds"])
        self.assertTrue(self.models["o3-mini"]["capabilities"]["imageGenerationTool"])
        self.assertFalse(self.models["o3-mini"]["capabilities"]["processesImages"])
        self.assertEqual(self.models["o3-mini"]["reasoningPolicy"]["status"], "supported")

    def test_image_models_distinguish_direct_output_from_hosted_orchestration(self):
        for name in ("gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"):
            with self.subTest(model=name):
                flags = self.models[name]["capabilities"]
                self.assertIs(flags["processesText"], True)
                self.assertIs(flags["processesImages"], True)
                self.assertIs(flags["generatesImages"], True)
                self.assertIs(flags["imageGenerationTool"], False)
                self.assertIs(flags["toolCalling"], False)
        self.assertIs(self.models["gpt-image-1.5"]["capabilities"]["generatesText"], True)
        for name in ("gpt-image-2", "gpt-image-1", "gpt-image-1-mini"):
            self.assertIs(self.models[name]["capabilities"]["generatesText"], False)

    def test_retired_dalle_metadata_is_not_a_live_availability_claim(self):
        model = self.models["dall-e-3"]
        self.assertEqual(model["lifecycle"], "retired")
        notes = " ".join(model["notes"])
        self.assertIn("2026-03-04", notes)
        self.assertIn("2026-05-12", notes)
        self.assertIn("non-functional", notes)
        self.assertIn("azure-openai-images", model["sourceIds"])
        self.assertIn("openai-deprecations", model["sourceIds"])

    def test_provider_api_and_backend_prerequisites_are_explicit(self):
        notes = " ".join(self.document["coverageNotes"])
        for requirement in (
            "api.openai.com", "v1 Responses", "2025-04-01-preview",
            "x-ms-oai-image-generation-deployment", "deployment-free",
            "-chat-latest",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, notes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
