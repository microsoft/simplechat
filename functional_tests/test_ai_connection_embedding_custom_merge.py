# test_ai_connection_embedding_custom_merge.py
"""
Regression coverage for embeddings merged with the Custom/image foundation.
Version: 0.261.122
Implemented in: 0.261.108

Preserve legacy embedding references while sharing Custom URL, credential, and
network-policy contracts. All inference requests use an isolated HTTP transport.
"""

import copy
import json
import socket
import subprocess
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
import model_endpoint_clients
from test_ai_connection_embedding_runtime import (
    custom_settings, load_guarded_endpoint_runtime, response_body, runtime,
)


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
    @classmethod
    def setUpClass(cls):
        cls.endpoint_runtime = load_guarded_endpoint_runtime()

    def generate(
        self, settings, *, addresses=("93.184.216.34",), response_status=200,
        identity_headers=None, hydration_error=None,
    ):
        """Keep factory, request and DNS guards real; replace TCP/HTTP and TLS-file I/O."""
        requests = []

        def handle(transport, request):
            connection = transport._pool._network_backend.connect_tcp(
                request.url.host, request.url.port or (443 if request.url.scheme == "https" else 80),
            )
            connection.close()
            requests.append(request)
            if response_status == 302:
                return httpx.Response(302, headers={"location": "https://redirect.example.test/embeddings"})
            return httpx.Response(200, json=response_body([[1, 2, 3]]))

        transport_factory = Mock(wraps=model_endpoint_clients.build_custom_openai_sync_http_client)
        hydrate = Mock(side_effect=hydration_error or (lambda endpoint, *args, **kwargs: copy.deepcopy(endpoint)))
        self.requests = requests
        self.factory = transport_factory
        self.hydrate = hydrate
        vault = types.SimpleNamespace(
            SecretReturnType=types.SimpleNamespace(VALUE="value"),
            keyvault_model_endpoint_get_helper=hydrate,
        )
        ssl_context = httpx.create_ssl_context(verify=True, trust_env=False)
        with (
            patch.dict(sys.modules, {
                "functions_keyvault": vault,
                "functions_model_endpoint_runtime": self.endpoint_runtime,
            }),
            patch.object(self.endpoint_runtime, "build_custom_openai_sync_http_client", transport_factory),
            patch.object(httpx.HTTPTransport, "handle_request", handle),
            patch("httpcore.SyncBackend.connect_tcp", return_value=Mock()) as dial,
            patch("socket.getaddrinfo", side_effect=lambda host, port, *args, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
                for address in addresses
            ]),
            patch("socket.socket.connect", side_effect=AssertionError("Embedding tests must not connect to a network")),
            patch.object(model_endpoint_clients, "build_custom_endpoint_ssl_context", return_value=ssl_context),
            patch.object(runtime, "build_model_endpoint_identity_headers", return_value=identity_headers or {}) as identity,
        ):
            result = runtime.generate_embedding_batch(["text"], settings=settings, max_retries=0)
        self.dial = dial
        self.identity = identity
        transport_factory.assert_called_once()
        self.assertTrue(hydrate.call_args.kwargs["strict"])
        self.assertEqual(hydrate.call_args.kwargs["scope"], "global")
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
        for api_type, auth_type in (
            ("anthropic", "api_key"), ("gemini", "api_key"),
            ("openai", "oauth2_client_credentials"), ("azure_openai", "oauth2_client_credentials"),
        ):
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

    def test_operation_overrides_preserve_api_version_request_identity_and_embedding_suffix(self):
        for provider, api_type in (
            ("custom", "openai"), ("custom", "azure_openai"), ("openai_compatible", "openai"),
        ):
            settings = canonical_settings(api_type) if provider == "custom" else custom_settings()
            endpoint = settings["model_endpoints"][0]
            endpoint["connection"]["operation_settings"] = {"embeddings": {
                "api": api_type,
                "endpoint": (
                    "https://override.example.test/edge/v1/embeddings"
                    if provider == "custom" else "https://override.example.test/edge/v1"
                ),
                "api_version": "2025-01-01-preview" if api_type == "azure_openai" else "v1",
            }}
            with self.subTest(provider=provider, api_type=api_type):
                before = copy.deepcopy(settings)
                profile = resolve_embedding_profile(settings)
                _, requests, _ = self.generate(settings, identity_headers={"X-SimpleChat-Actor": "fixture-user"})
                request = requests[0]
                self.assertEqual(request.url.host, "override.example.test")
                self.assertEqual(request.url.path.count("/embeddings"), 1)
                expected_path = (
                    "/edge/v1/openai/deployments/embed-prod/embeddings"
                    if api_type == "azure_openai" else "/edge/v1/embeddings"
                )
                self.assertEqual(request.url.path, expected_path)
                self.assertEqual(json.loads(request.content)["model"], profile.deployment)
                self.assertEqual(request.headers["x-simplechat-actor"], "fixture-user")
                self.assertEqual(request.url.params.get("api-version"), profile.api_version if api_type == "azure_openai" else None)
                self.assertEqual(settings, before)
                self.identity.assert_called_once()
                self.assertEqual(self.identity.call_args.args, (settings,))
                runtime_endpoint = self.identity.call_args.kwargs["endpoint_config"]
                self.assertEqual(runtime_endpoint["id"], endpoint["id"])
                self.assertEqual(runtime_endpoint["models"][0]["id"], endpoint["models"][0]["id"])

    def test_incompatible_operation_api_and_version_never_construct_a_client(self):
        for provider, operation in (
            ("custom", {"api": "azure_openai", "api_version": "2025-01-01-preview"}),
            ("custom", {"api": "openai", "api_version": "2025-01-01-preview"}),
            ("openai_compatible", {"api": "azure_openai", "api_version": "2025-01-01-preview"}),
            ("openai_compatible", {"api": "openai", "api_version": "2025-01-01-preview"}),
        ):
            settings = canonical_settings() if provider == "custom" else custom_settings()
            settings["model_endpoints"][0]["connection"]["operation_settings"] = {"embeddings": operation}
            with self.subTest(provider=provider, operation=operation):
                with self.assertRaises(AIConnectionError):
                    self.generate(settings)
                self.factory.assert_not_called()
                self.assertEqual(self.requests, [])

    def test_operation_auth_header_respects_saved_header_and_prefix_precedence(self):
        for operation_header, stored, expected_header, prefix in (
            ("authorization", {}, "authorization", "Bearer"),
            ("authorization", {"api_key_header": ""}, "authorization", "Bearer"),
            ("authorization", {"api_key_header": "", "api_key_prefix": ""}, "authorization", ""),
            ("Ocp-Apim-Subscription-Key", {}, "ocp-apim-subscription-key", ""),
            ("api-key", {"api_key_prefix": "Token"}, "api-key", "Token"),
            ("authorization", {"api_key_header": "X-Stored-Key", "api_key_prefix": "Stored"}, "x-stored-key", "Stored"),
        ):
            for provider in ("custom", "openai_compatible"):
                settings = canonical_settings() if provider == "custom" else custom_settings()
                endpoint = settings["model_endpoints"][0]
                endpoint["connection"]["operation_settings"] = {"embeddings": {"auth_header": operation_header}}
                endpoint["auth"].update(stored)
                with self.subTest(provider=provider, operation_header=operation_header, stored=stored):
                    _, requests, _ = self.generate(settings)
                    expected = f"{prefix} synthetic-key" if prefix else "synthetic-key"
                    self.assertEqual(requests[0].headers[expected_header], expected)
                    self.assertEqual(len(requests[0].headers.get_list(expected_header)), 1)
                    if expected_header != "authorization":
                        self.assertNotIn("synthetic-key", requests[0].headers.get("authorization", ""))

    def test_bearer_auth_does_not_turn_an_operation_header_into_a_second_credential(self):
        settings = canonical_settings()
        endpoint = settings["model_endpoints"][0]
        endpoint["auth"] = {"type": "bearer", "bearer_token": "synthetic-bearer"}
        endpoint["connection"]["operation_settings"] = {"embeddings": {"auth_header": "api-key"}}
        _, requests, _ = self.generate(settings)
        self.assertEqual(requests[0].headers["authorization"], "Bearer " + endpoint["auth"]["bearer_token"])
        self.assertNotIn("api-key", requests[0].headers)
        self.assertEqual(len(requests[0].headers.get_list("authorization")), 1)

    def test_shared_factory_rejects_mixed_dns_and_redirects_before_followup_requests(self):
        for settings in (custom_settings(), canonical_settings()):
            with self.subTest(provider=settings["model_endpoints"][0]["provider"], blocked_by="mixed DNS"):
                with self.assertRaises(AIConnectionError):
                    self.generate(settings, addresses=("93.184.216.34", "10.0.0.9"))
                self.assertEqual(self.requests, [])
            with self.subTest(provider=settings["model_endpoints"][0]["provider"], blocked_by="redirect"):
                with self.assertRaises(AIConnectionError):
                    self.generate(settings, response_status=302)
                self.assertEqual(len(self.requests), 1)
                self.assertNotEqual(self.requests[0].url.host, "redirect.example.test")

    def test_strict_saved_credential_failure_never_constructs_a_client(self):
        for settings in (custom_settings(), canonical_settings(), canonical_settings("azure_openai")):
            with self.subTest(provider=settings["model_endpoints"][0]["provider"]):
                with self.assertRaises(AIConnectionError) as raised:
                    self.generate(settings, hydration_error=RuntimeError("PRIVATE credential could not be hydrated"))
                self.assertTrue(self.hydrate.call_args.kwargs["strict"])
                self.factory.assert_not_called()
                self.assertEqual(self.requests, [])
                self.assertNotIn("PRIVATE", str(raised.exception))

    def test_profile_import_remains_independent_of_config_and_runtime_clients(self):
        code = (
            "import builtins,sys; "
            f"sys.path.insert(0,{str(ROOT / 'application' / 'single_app')!r}); "
            "original_import=builtins.__import__\n"
            "def guarded_import(name,*args,**kwargs):\n"
            "    if name in {'config','model_endpoint_clients','functions_model_endpoint_runtime'}:\n"
            "        raise AssertionError('Profile imported runtime dependency: '+name)\n"
            "    return original_import(name,*args,**kwargs)\n"
            "builtins.__import__=guarded_import\n"
            "import functions_embedding_profile\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
