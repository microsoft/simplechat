# test_image_provider_capabilities.py
"""
Functional tests for provider-qualified image generation and editing.
Version: 0.261.107
Implemented in: 0.261.107

Exercise the real JSON catalog and pure resolver without credentials, application
startup, discovery, or paid inference. Cloud availability is not an app-hosting gate.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Pure leaf modules are loaded after installing this standalone test's application path.
import functions_image_capabilities as images  # noqa: E402
from functions_model_capabilities import get_image_operation_profile  # noqa: E402


def endpoint(provider="custom", url="https://api.openai.com/v1", api_type="openai", **connection):
    return {
        "id": "image-connection",
        "provider": provider,
        "api_type": api_type,
        "connection": {"endpoint": url, **connection},
    }


def model(name="gpt-5.6-sol", **metadata):
    return {"id": "stable-id", "modelName": name, "deploymentName": "deployment", **metadata}


class ImageProviderCapabilityTests(unittest.TestCase):
    def test_gpt_tool_support_is_direct_openai_only(self):
        for name in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra", "gpt-5.4"):
            with self.subTest(model=name):
                direct = images.resolve_image_model_capability(model(name), endpoint())
                self.assertTrue(direct["supported"])
                self.assertEqual(direct["api"], "responses")
                self.assertEqual(direct["mode"], "masked")
                for provider in ("aoai", "aifoundry", "new_foundry"):
                    for domain in ("azure.com", "azure.us"):
                        azure = endpoint(provider, f"https://resource.openai.{domain}")
                        declared = model(name, supportsImageGeneration=True, image_generation_api="images")
                        rejected = images.resolve_image_model_capability(declared, azure)
                        self.assertFalse(rejected["supported"])
                        self.assertEqual(rejected["source"], "policy")

    def test_custom_api_style_cannot_disguise_an_azure_endpoint(self):
        for url in (
            "https://resource.openai.azure.com/openai/v1",
            "https://resource.services.ai.azure.us/openai/v1",
        ):
            support = images.resolve_image_model_capability(
                model(supportsImageGeneration=True, image_generation_api="responses"),
                endpoint(url=url, image_provider="openai"),
            )
            self.assertFalse(support["supported"])
            self.assertEqual(support["source"], "policy")

    def test_a_known_native_model_cannot_be_declared_on_the_wrong_provider(self):
        for name in ("MAI-Image-2.6", "FLUX.2-pro"):
            support = images.resolve_image_model_capability(
                model(name, supportsImageGeneration=True, image_generation_api="images"), endpoint(),
            )
            self.assertFalse(support["supported"])
        support = images.resolve_image_model_capability(
            model("gpt-image-2"),
            endpoint(url="https://resource.openai.azure.com", api_type="openai"),
        )
        self.assertFalse(support["supported"])
        self.assertIn("Azure OpenAI API type", support["reason"])

    def test_cloud_comes_from_endpoint_not_application_or_authority(self):
        with patch.dict(os.environ, {"AZURE_ENVIRONMENT": "usgovernment"}):
            self.assertEqual(images.resolve_image_model_capability(model(), endpoint())["cloud"], "commercial")
            azure = endpoint("aoai", "https://image.openai.azure.com")
            azure["auth"] = {"management_cloud": "government"}
            self.assertEqual(
                images.resolve_image_model_capability(model("gpt-image-2"), azure)["cloud"], "commercial",
            )
        with patch.dict(os.environ, {"AZURE_ENVIRONMENT": "public"}):
            support = images.resolve_image_model_capability(
                model("gpt-image-2"), endpoint("aoai", "https://image.openai.azure.us"),
            )
            self.assertTrue(support["supported"])
            self.assertEqual(support["cloud"], "government")
            self.assertEqual(support["availability"], "unknown")
            self.assertTrue(support["availability_reason"])

    def test_private_gateway_needs_explicit_compatible_evidence(self):
        gateway = endpoint(url="https://models.example.test/gateway")
        self.assertFalse(images.resolve_image_model_capability(model(), gateway)["supported"])
        declared_gateway = endpoint(url="https://models.example.test/gateway", image_provider="openai")
        support = images.resolve_image_model_capability(model(), declared_gateway)
        self.assertTrue(support["supported"])
        self.assertEqual(support["cloud"], "unknown")
        self.assertFalse(images.resolve_image_model_capability(
            model(), endpoint(url="https://api.openai.com.unrelated.example/v1"),
        )["supported"])

    def test_unrecognized_versions_need_explicit_operation_not_a_name_wildcard(self):
        unknown = model("gpt-99-future")
        self.assertFalse(images.resolve_image_model_capability(unknown, endpoint())["supported"])
        unknown["supportsImageGeneration"] = True
        self.assertFalse(images.resolve_image_model_capability(unknown, endpoint())["supported"])
        unknown["image_generation_api"] = "responses"
        support = images.resolve_image_model_capability(unknown, endpoint())
        self.assertTrue(support["supported"])
        self.assertEqual(support["source"], "declared")
        self.assertEqual(support["mode"], "regenerate")
        self.assertEqual(support["qualities"], [])
        unknown.update(supportsImageEditing=True, supportsImageMasking=True)
        self.assertEqual(images.resolve_image_model_capability(unknown, endpoint())["mode"], "masked")

    def test_unknown_mask_declaration_needs_editing(self):
        unknown = model(
            "private-image", supportsImageGeneration=True,
            image_generation_api="images", supportsImageMasking=True,
        )
        self.assertFalse(images.resolve_image_model_capability(unknown, endpoint())["supported"])

    def test_declarations_cannot_override_known_negative_image_api_facts(self):
        for name in ("o1", "gpt-5-mini", "gpt-5.3-codex"):
            for api in ("images", "responses"):
                for target in (endpoint(), endpoint(url="https://gateway.example.test/v1")):
                    with self.subTest(model=name, api=api, endpoint=target):
                        support = images.resolve_image_model_capability(
                            model(name, supportsImageGeneration=True, image_generation_api=api), target,
                        )
                        self.assertFalse(support["supported"])
                        self.assertEqual(support["source"], "catalog")
                        self.assertIn("known incompatibility", support["reason"])

    def test_image_profiles_are_version_and_provider_specific(self):
        for name in ("gpt-image-1", "gpt-image-1.5", "gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
            for provider, url in (
                ("custom", "https://api.openai.com/v1"),
                ("aoai", "https://image.openai.azure.com"),
                ("new_foundry", "https://image.services.ai.azure.com"),
            ):
                with self.subTest(model=name, provider=provider):
                    support = images.resolve_image_model_capability(model(name), endpoint(provider, url))
                    self.assertTrue(support["supported"])
                    self.assertEqual(support["api"], "images")
                    self.assertTrue(support["masking"])
        self.assertFalse(images.resolve_image_model_capability(model("gpt-image-99"), endpoint())["supported"])

    def test_known_dedicated_image_profile_overrides_a_stale_route(self):
        support = images.resolve_image_model_capability(
            model("gpt-image-2", image_generation_api="responses"),
            endpoint("aoai", "https://image.openai.azure.com"),
        )
        self.assertTrue(support["supported"])
        self.assertEqual(support["api"], "images")

    def test_source_editing_does_not_imply_masks_for_mai_or_flux(self):
        for name, api in (
            ("MAI-Image-2.5", "mai"), ("MAI-Image-2.5-Flash", "mai"),
            ("MAI-Image-2.5-Pro", "mai"), ("MAI-Image-2.6", "mai"),
            ("MAI-Image-2.6-Flash", "mai"), ("FLUX.2-pro", "flux"),
            ("FLUX.2-flex", "flux"), ("FLUX.1-Kontext-pro", "flux"),
        ):
            with self.subTest(model=name):
                support = images.resolve_image_model_capability(
                    model(name, supportsImageMasking=True),
                    endpoint("new_foundry", "https://images.services.ai.azure.com"),
                )
                self.assertTrue(support["supported"])
                self.assertEqual(support["api"], api)
                self.assertEqual(support["mode"], "edit")
                self.assertFalse(support["masking"])
                self.assertFalse(images.resolve_image_model_capability(model(name), endpoint())["supported"])

    def test_generation_only_flux_is_regeneration_not_a_reference_edit(self):
        support = images.resolve_image_model_capability(
            model("FLUX-1.1-pro"), endpoint("aifoundry", "https://images.services.ai.azure.com"),
        )
        self.assertTrue(support["supported"])
        self.assertEqual(support["mode"], "regenerate")
        self.assertFalse(support["editing"])

    def test_mai_limits_reject_gpt_presets_and_unsupported_rendering_options(self):
        support = images.resolve_image_model_capability(
            model("MAI-Image-2.6"), endpoint("new_foundry", "https://images.services.ai.azure.com"),
        )
        for size in support["sizes"]:
            images.validate_image_options(support, size=size)
            width, height = map(int, size.split("x"))
            self.assertGreaterEqual(min(width, height), 768)
            self.assertLessEqual(width * height, 1048576)
        for options in (
            {"size": "1536x1024"}, {"size": "512x512"}, {"quality": "high"},
            {"background": "transparent"}, {"quality": None},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                images.validate_image_options(support, **options)

    def test_retired_and_explicitly_disabled_models_are_not_enabled_by_catalog(self):
        retired = images.resolve_image_model_capability(
            model("dall-e-3", supportsImageGeneration=True), endpoint(),
        )
        self.assertFalse(retired["supported"])
        self.assertEqual(retired["availability"], "unavailable")
        disabled = images.resolve_image_model_capability(model(supportsImageGeneration=False), endpoint())
        self.assertFalse(disabled["supported"])
        self.assertEqual(disabled["source"], "declared")

    def test_catalog_profile_results_are_isolated(self):
        first = get_image_operation_profile("mai-images")
        first["sizes"].clear()
        self.assertTrue(get_image_operation_profile("mai-images")["sizes"])
        self.assertIsNone(get_image_operation_profile("not-a-profile"))

    def test_catalog_references_and_image_profile_limits(self):
        catalog = json.loads(APP_ROOT.joinpath("static", "json", "model_capabilities.json").read_text(encoding="utf-8"))
        profiles = catalog["imageOperationProfiles"]
        sources = {source["id"] for source in catalog["sources"]}
        identifiers = set()
        for item in catalog["models"]:
            self.assertNotIn(item["id"], identifiers)
            identifiers.add(item["id"])
            for profile_id in item.get("imageProfiles", {}).values():
                self.assertIn(profile_id, profiles)
        for profile in profiles.values():
            self.assertIn(profile["api"], images.IMAGE_APIS)
            self.assertTrue(set(profile["sourceIds"]) <= sources)
            self.assertIs(type(profile["editing"]), bool)
            self.assertIs(type(profile["masking"]), bool)
            self.assertTrue(not profile["masking"] or profile["editing"])
            self.assertEqual(profile["availability"]["government"], "unknown")
        schema = APP_ROOT.joinpath("static", "json", "schemas", "model_capabilities.schema.json")
        Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).validate(catalog)


if __name__ == "__main__":
    unittest.main()
