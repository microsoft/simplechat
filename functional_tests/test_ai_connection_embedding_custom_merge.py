# test_ai_connection_embedding_custom_merge.py
"""
Regression coverage for embeddings merged with the Custom/image foundation.
Version: 0.261.108
Implemented in: 0.261.108

Preserve legacy embedding references while sharing Custom URL, credential, and
network-policy contracts. All inference requests use an isolated HTTP transport.
"""

import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

from functions_ai_connections import AIConnectionError, describe_model_capabilities, supports_model_capability
from functions_embedding_profile import resolve_embedding_profile
from functions_model_endpoint_types import custom_endpoint_validation_view
from test_ai_connection_embedding_runtime import custom_settings, response_body, runtime


def canonical_settings(api_type="openai"):
    settings = custom_settings()
    endpoint = settings["model_endpoints"][0]
    endpoint["provider"] = "custom"
    endpoint["api_type"] = api_type
    endpoint["name"] = "Canonical Custom"
    endpoint["connection"] = {
        "endpoint": "https://models.example.test/gateway",
        "url_mode": "auto",
    }
    if api_type == "azure_openai":
        endpoint["connection"]["api_version"] = "2024-06-01"
    settings["embedding_model_selection"]["provider"] = "custom"
    return settings


class CustomEmbeddingMergeTests(unittest.TestCase):
    def generate(self, settings):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=response_body([[1, 2, 3]]))

        client = httpx.Client(
            transport=httpx.MockTransport(handle), follow_redirects=False, trust_env=False,
        )
        transport_factory = Mock(return_value=client)
        vault = types.SimpleNamespace(
            SecretReturnType=types.SimpleNamespace(VALUE="value"),
            keyvault_model_endpoint_get_helper=lambda endpoint, *args, **kwargs: endpoint,
        )
        try:
            with (
                patch.dict(sys.modules, {
                    "functions_keyvault": vault,
                    "model_endpoint_clients": types.SimpleNamespace(build_custom_openai_sync_http_client=transport_factory),
                }),
                patch("functions_model_endpoint_validation.resolve_custom_model_endpoint_addresses", return_value=("93.184.216.34",)),
            ):
                result = runtime.generate_embedding_batch(["text"], settings=settings)
        finally:
            client.close()
        return result, requests, transport_factory

    def test_custom_openai_uses_request_model_name_and_shared_url_policy(self):
        settings = canonical_settings()
        profile = resolve_embedding_profile(settings)
        self.assertEqual(profile.deployment, "private-encoder")
        self.assertEqual(profile.base_url, "https://models.example.test/gateway/v1/")
        result, requests, factory = self.generate(settings)
        self.assertEqual(str(requests[0].url), "https://models.example.test/gateway/v1/embeddings")
        self.assertEqual(json.loads(requests[0].content)["model"], "private-encoder")
        self.assertEqual(result[0][0], [1, 2, 3])
        self.assertFalse(factory.call_args.kwargs["allow_private"])
        self.assertFalse(factory.call_args.kwargs["allow_insecure"])

    def test_custom_azure_uses_deployment_name_api_version_and_key_header(self):
        settings = canonical_settings("azure_openai")
        _, requests, _ = self.generate(settings)
        self.assertEqual(
            str(requests[0].url),
            "https://models.example.test/gateway/openai/deployments/embed-prod/embeddings?api-version=2024-06-01",
        )
        self.assertEqual(json.loads(requests[0].content)["model"], "embed-prod")
        self.assertEqual(requests[0].headers["api-key"], "synthetic-key")
        self.assertNotIn("synthetic-key", requests[0].headers.get("authorization", ""))

    def test_legacy_alias_keeps_exact_url_wire_identifier_and_stored_metadata(self):
        settings = custom_settings()
        original = copy.deepcopy(settings)
        before = resolve_embedding_profile(settings)
        _, requests, _ = self.generate(settings)
        self.assertEqual(str(requests[0].url), "https://embedding.example.test/gateway/v1/embeddings")
        self.assertEqual(json.loads(requests[0].content)["model"], "embed-prod")
        self.assertEqual(settings, original)
        self.assertEqual(resolve_embedding_profile(settings).profile_id, before.profile_id)
        view = custom_endpoint_validation_view(settings["model_endpoints"][0])
        self.assertEqual(view["provider"], "custom")
        self.assertEqual(view["connection"]["url_mode"], "exact")
        self.assertEqual(view["models"][0]["modelName"], "embed-prod")
        self.assertEqual(settings["model_endpoints"][0]["models"][0]["modelName"], "private-encoder")

    def test_exact_custom_base_and_bearer_auth_remain_explicit(self):
        settings = canonical_settings()
        endpoint = settings["model_endpoints"][0]
        endpoint["connection"]["url_mode"] = "exact"
        endpoint["auth"] = {"type": "bearer", "bearer_token": "synthetic-bearer"}
        _, requests, _ = self.generate(settings)
        self.assertEqual(str(requests[0].url), "https://models.example.test/gateway/embeddings")
        self.assertEqual(requests[0].headers["authorization"], "Bearer synthetic-bearer")

    def test_custom_auth_header_is_preserved_without_a_second_bearer_credential(self):
        settings = canonical_settings()
        settings["model_endpoints"][0]["auth"].update(api_key_header="x-model-key", api_key_prefix="Token")
        _, requests, _ = self.generate(settings)
        self.assertEqual(requests[0].headers["x-model-key"], "Token synthetic-key")
        self.assertNotIn("synthetic-key", requests[0].headers.get("authorization", ""))

    def test_native_api_types_and_oauth_do_not_implicitly_enable_embeddings(self):
        for api_type, auth_type in (("anthropic", "api_key"), ("gemini", "api_key"), ("openai", "oauth2_client_credentials")):
            settings = canonical_settings(api_type)
            endpoint = settings["model_endpoints"][0]
            endpoint["auth"]["type"] = auth_type
            with self.subTest(api_type=api_type, auth_type=auth_type):
                self.assertFalse(supports_model_capability(endpoint["models"][0], "embeddings", "custom", endpoint=endpoint))
                with self.assertRaises(AIConnectionError):
                    resolve_embedding_profile(settings)
        for auth_type in ("bearer", "oauth2_client_credentials", "managed_identity"):
            settings = custom_settings()
            settings["model_endpoints"][0]["auth"]["type"] = auth_type
            with self.subTest(legacy_alias_auth=auth_type), self.assertRaises(AIConnectionError):
                resolve_embedding_profile(settings)

    def test_embedding_only_models_do_not_gain_image_support_from_custom_overrides(self):
        settings = canonical_settings()
        endpoint = settings["model_endpoints"][0]
        model = endpoint["models"][0]
        model.update(modelName="text-embedding-3-small", supportsImageGeneration=True, image_generation_api="responses")
        description = describe_model_capabilities(model, "custom", endpoint=endpoint)
        self.assertTrue(description["embeddings"]["supported"])
        self.assertFalse(description["image_generation"]["supported"])
        self.assertFalse(description["image_generation"]["available"])
        self.assertFalse(description["chat"]["supported"])

    def test_alias_cannot_bypass_custom_network_policy(self):
        for settings in (custom_settings(), canonical_settings()):
            for url in ("https://127.0.0.1/v1", "https://169.254.169.254/v1", "http://models.example.test/v1"):
                source = copy.deepcopy(settings)
                source["model_endpoints"][0]["connection"]["endpoint"] = url
                with self.subTest(provider=source["model_endpoints"][0]["provider"], url=url):
                    with self.assertRaises(AIConnectionError):
                        self.generate(source)

    def test_private_http_and_certificate_options_use_explicit_global_permissions(self):
        settings = canonical_settings()
        settings.update(
            allow_private_custom_model_endpoints=True,
            allow_insecure_custom_model_endpoints=True,
            custom_model_endpoint_ca_bundle_path="C:\\certs\\ca.pem",
        )
        settings["model_endpoints"][0]["connection"].update(
            endpoint="http://10.0.0.4/inference", url_mode="exact",
            client_cert_path="C:\\certs\\client.pem", client_key_path="C:\\certs\\client.key",
        )
        _, requests, factory = self.generate(settings)
        self.assertEqual(str(requests[0].url), "http://10.0.0.4/inference/embeddings")
        self.assertEqual(factory.call_args.kwargs, {
            "allow_private": True, "allow_insecure": True,
            "ca_bundle_path": "C:\\certs\\ca.pem",
            "client_cert": ("C:\\certs\\client.pem", "C:\\certs\\client.key"),
        })


if __name__ == "__main__":
    unittest.main()
