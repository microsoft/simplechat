# test_ai_connection_embedding_runtime.py
"""
Functional coverage for embedding profiles and provider-independent inference.
Version: 0.261.108
Implemented in: 0.261.106

Exercise the actual profile resolver, SDK wire format, response validation, and
retry boundaries with synthetic credentials and no Azure or provider requests.
"""

import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from azure.core.exceptions import ClientAuthenticationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.app_stubs import import_app_module
from functions_ai_connections import AIConnectionError, EMBEDDING_SELECTION_KEY
from functions_embedding_profile import resolve_embedding_profile
from functions_ai_connection_migration import build_embedding_connection_migration


runtime = import_app_module("functions_embeddings")


def custom_settings():
    return {
        EMBEDDING_SELECTION_KEY: {"endpoint_id": "custom", "model_id": "embed", "provider": "openai_compatible"},
        "model_endpoints": [{
            "id": "custom", "provider": "openai_compatible", "enabled": True,
            "connection": {"endpoint": "https://embedding.example.test/gateway/v1"},
            "auth": {"type": "api_key", "api_key": "synthetic-key"},
            "models": [{
                "id": "embed", "deploymentName": "embed-prod", "modelName": "private-encoder",
                "enabled": True, "supportsEmbeddings": True, "enabled_capabilities": ["embeddings"],
                "embedding_config": {"dimensions": 3, "max_input_tokens": 128, "max_batch_tokens": 256},
            }],
        }],
    }


def response_body(vectors, *, indexes=None, usage=True):
    payload = {
        "object": "list", "model": "embed-prod",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in zip(indexes if indexes is not None else range(len(vectors)), vectors)
        ],
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 5, "total_tokens": 5}
    return payload


class EmbeddingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.settings = custom_settings()
        self.profile = resolve_embedding_profile(self.settings)

    def client(self, handler):
        return runtime._EmbeddingOpenAIClient(
            base_url=self.profile.base_url, api_key="synthetic-key", auth_header="authorization",
            max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def generate(self, handler, texts=None, **kwargs):
        with patch.object(runtime, "create_capability_client", return_value=self.client(handler)):
            return runtime.generate_embedding_batch(
                texts or ["first", "second"], settings=self.settings, **kwargs,
            )

    def test_custom_base_path_order_and_aggregate_usage_are_preserved(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=response_body([[2.0, 3.0, 4.0], [1.0, 2.0, 3.0]], indexes=[1, 0]))

        results = self.generate(handler)
        self.assertEqual(str(requests[0].url), "https://embedding.example.test/gateway/v1/embeddings")
        self.assertEqual(requests[0].headers["authorization"], "Bearer synthetic-key")
        self.assertEqual(
            json.loads(requests[0].content),
            {"model": "embed-prod", "input": ["first", "second"], "encoding_format": "float"},
        )
        self.assertEqual(results[0][0], [1.0, 2.0, 3.0])
        self.assertEqual(sum(result[1]["total_tokens"] for result in results), 5)
        self.assertEqual(results[0][0].profile_id, self.profile.profile_id)

    def test_usage_absence_does_not_lose_provenance(self):
        results = self.generate(lambda _: httpx.Response(200, json=response_body([[1, 2, 3]], usage=False)), ["first"])
        self.assertIsNone(results[0][1])
        self.assertEqual(results[0][0].profile_id, self.profile.profile_id)
        self.assertEqual(json.loads(json.dumps(results[0][0])), [1, 2, 3])

    def test_rejects_wrong_count_duplicate_index_wrong_dimensions_and_nonfinite_values(self):
        for body in (
            response_body([[1, 2, 3]]),
            response_body([[1, 2, 3], [1, 2, 3]], indexes=[0, 0]),
            response_body([[1, 2], [1, 2, 3]]),
            response_body([[1, True, 3], [1, 2, 3]]),
        ):
            with self.subTest(body=body), self.assertRaises(AIConnectionError):
                self.generate(lambda _, payload=body: httpx.Response(200, json=payload))
        for vector in ([1.0, float("nan"), 2.0], [1.0, float("inf"), 2.0]):
            with self.assertRaises(AIConnectionError):
                runtime._validate_vector(vector, 3)

    def test_rejects_unindexed_response_items(self):
        response = types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[1, 2, 3])], usage=None)
        with self.assertRaises(AIConnectionError):
            runtime.normalize_embedding_response(response, 1, self.profile)

    def test_empty_inputs_do_not_make_requests_and_invalid_limits_are_rejected(self):
        with patch.object(runtime, "create_capability_client") as factory:
            self.assertEqual(runtime.generate_embedding_batch([], settings=self.settings), [])
            factory.assert_not_called()
        for kwargs in ({"batch_size": 0}, {"batch_size": True}, {"max_retries": -1}, {"initial_delay": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(AIConnectionError):
                runtime.generate_embedding_batch(["text"], settings=self.settings, **kwargs)

    def test_input_prefixes_are_purpose_specific_and_never_send_input_type(self):
        self.settings["model_endpoints"][0]["models"][0]["embedding_config"].update(
            document_prefix="passage: ", query_prefix="query: ",
        )
        sent = []

        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json=response_body([[1, 2, 3]]))

        self.generate(handler, ["text"], purpose="query")
        self.generate(handler, ["text"], purpose="document")
        self.assertEqual([item["input"] for item in sent], [["query: text"], ["passage: text"]])
        self.assertTrue(all("input_type" not in item for item in sent))

    def test_oversized_input_fails_before_client_creation(self):
        with patch.object(runtime, "create_capability_client") as factory, self.assertRaises(AIConnectionError):
            runtime.generate_embedding_batch(["x" * 129], settings=self.settings)
        factory.assert_not_called()

    def test_retry_delay_and_exhaustion_are_bounded(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "busy"}})

        delay = Mock(return_value=2.0)
        with patch.object(runtime.time, "sleep") as sleep, self.assertRaises(AIConnectionError) as raised:
            self.generate(handler, ["text"], max_retries=2, retry_delay=delay)
        self.assertEqual(raised.exception.code, "embedding_rate_limited")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(delay.call_count, 2)

    def test_provider_errors_do_not_leak_provider_message(self):
        with self.assertRaises(AIConnectionError) as raised:
            self.generate(lambda _: httpx.Response(401, json={"error": {"message": "secret-provider-detail"}}))
        self.assertNotIn("secret-provider-detail", str(raised.exception))

    def test_credential_rotation_does_not_change_profile_but_model_changes_do(self):
        settings = copy.deepcopy(self.settings)
        settings["model_endpoints"][0]["auth"]["api_key"] = "rotated-synthetic-key"
        self.assertEqual(resolve_embedding_profile(settings).profile_id, self.profile.profile_id)
        settings["model_endpoints"][0]["models"][0]["modelName"] = "different-encoder"
        self.assertNotEqual(resolve_embedding_profile(settings).profile_id, self.profile.profile_id)

    def test_project_and_credential_bearing_custom_urls_are_rejected(self):
        for endpoint in (
            "https://resource.services.ai.azure.com/api/projects/project",
            "https://user:password@example.test/v1",
            "https://example.test/v1?api-key=secret",
        ):
            settings = copy.deepcopy(self.settings)
            settings["model_endpoints"][0]["connection"]["endpoint"] = endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(AIConnectionError):
                resolve_embedding_profile(settings)

    def test_foundry_requires_explicit_inference_base_and_keeps_project_endpoint(self):
        settings = copy.deepcopy(self.settings)
        endpoint = settings["model_endpoints"][0]
        endpoint["provider"] = "new_foundry"
        endpoint["connection"] = {
            "endpoint": "https://resource.services.ai.azure.com/api/projects/project",
            "operation_settings": {"embeddings": {"api": "openai", "endpoint": "https://resource.openai.azure.com/openai/v1/"}},
        }
        resolved = resolve_embedding_profile(settings)
        self.assertEqual(resolved.base_url, "https://resource.openai.azure.com/openai/v1/")
        self.assertIn("/api/projects/", endpoint["connection"]["endpoint"])

    def test_azure_versioned_url_preserves_gateway_prefix_and_escapes_deployment(self):
        settings = copy.deepcopy(self.settings)
        endpoint = settings["model_endpoints"][0]
        endpoint["provider"] = "aoai"
        endpoint["models"][0]["deploymentName"] = "embed/production"
        endpoint["connection"]["operation_settings"] = {
            "embeddings": {"api": "azure_openai", "api_version": "2024-06-01", "is_apim": True},
        }
        resolved = resolve_embedding_profile(settings)
        self.assertEqual(resolved.base_url, "https://embedding.example.test/gateway/v1/openai/deployments/embed%2Fproduction/")
        self.assertEqual(resolved.api_version, "2024-06-01")

    def test_identity_token_refreshes_per_request(self):
        tokens = Mock(side_effect=["token-one", "token-two"])
        with runtime._EmbeddingOpenAIClient(
            base_url=self.profile.base_url, api_key="", auth_header="authorization", token_provider=tokens,
        ) as client:
            self.assertEqual(client.auth_headers, {"Authorization": "Bearer token-one"})
            self.assertEqual(client.auth_headers, {"Authorization": "Bearer token-two"})

    def test_factory_hydrates_saved_global_credentials_and_disables_redirects(self):
        helper = Mock(side_effect=lambda endpoint, *args, **kwargs: {
            **endpoint, "auth": {"type": "api_key", "api_key": "hydrated-synthetic-key"},
        })
        vault = types.SimpleNamespace(
            SecretReturnType=types.SimpleNamespace(VALUE="value"),
            keyvault_model_endpoint_get_helper=helper,
        )
        with patch.dict(sys.modules, {"functions_keyvault": vault}):
            with runtime.build_embedding_connection_client(self.profile.binding, self.settings) as client:
                self.assertEqual(str(client.base_url), self.profile.base_url)
                self.assertEqual(client.auth_headers, {"Authorization": "Bearer hydrated-synthetic-key"})
                self.assertFalse(client._client.follow_redirects)
                self.assertNotIn("api-version", client.default_query)
        self.assertEqual(helper.call_args.args[1], "custom")
        self.assertEqual(helper.call_args.kwargs["scope"], "global")
        self.assertEqual(self.settings["model_endpoints"][0]["auth"]["api_key"], "synthetic-key")

    def test_apim_import_preserves_the_explicit_legacy_chunk_budget(self):
        for deployment in ("text-embedding-3-small", "internal-gateway-embedding"):
            for limit in (512, 16384):
                with self.subTest(deployment=deployment, limit=limit):
                    legacy = {
                        "enable_embedding_apim": True,
                        "azure_apim_embedding_endpoint": "https://gateway.example.test/prefix",
                        "azure_apim_embedding_api_version": "2024-06-01",
                        "azure_apim_embedding_deployment": deployment,
                        "azure_apim_embedding_subscription_key": "synthetic-key",
                        "embedding_model": {"selected": [{
                            "deploymentName": "unrelated-direct-deployment", "contextWindow": str(limit),
                        }]},
                    }
                    previous = resolve_embedding_profile(legacy)
                    imported = resolve_embedding_profile({**legacy, **build_embedding_connection_migration(legacy)})
                    self.assertEqual(previous.policy["max_input_tokens"], limit)
                    self.assertEqual(imported.policy, previous.policy)
                    self.assertEqual(imported.profile_id, previous.profile_id)
                    self.assertEqual(imported.deployment, deployment)

    def test_factory_preserves_versioned_apim_auth_header_and_api_version(self):
        self.settings["model_endpoints"][0]["provider"] = "aoai"
        self.settings["model_endpoints"][0]["connection"]["operation_settings"] = {
            "embeddings": {
                "api": "azure_openai", "api_version": "2024-06-01",
                "is_apim": True, "auth_header": "Ocp-Apim-Subscription-Key",
            },
        }
        profile = resolve_embedding_profile(self.settings)
        vault = types.SimpleNamespace(
            SecretReturnType=types.SimpleNamespace(VALUE="value"),
            keyvault_model_endpoint_get_helper=lambda endpoint, *args, **kwargs: endpoint,
        )
        with patch.dict(sys.modules, {"functions_keyvault": vault}):
            with runtime.build_embedding_connection_client(profile.binding, self.settings) as client:
                self.assertEqual(client.auth_headers, {"Ocp-Apim-Subscription-Key": "synthetic-key"})
                self.assertEqual(client.default_query, {"api-version": "2024-06-01"})

    def test_factory_reports_secret_failures_without_exposing_details(self):
        vault = types.SimpleNamespace(
            SecretReturnType=types.SimpleNamespace(VALUE="value"),
            keyvault_model_endpoint_get_helper=Mock(side_effect=ValueError("sensitive-vault-address")),
        )
        with patch.dict(sys.modules, {"functions_keyvault": vault}), self.assertRaises(AIConnectionError) as raised:
            runtime.build_embedding_connection_client(self.profile.binding, self.settings)
        self.assertEqual(raised.exception.code, "embedding_connection_unavailable")
        self.assertNotIn("sensitive-vault", str(raised.exception))

    def test_request_time_azure_credential_failure_is_normalized(self):
        handler = Mock()
        client = runtime._EmbeddingOpenAIClient(
            api_key="", auth_header="authorization", base_url=self.profile.base_url,
            token_provider=Mock(side_effect=ClientAuthenticationError("sensitive-auth-details")),
            max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with patch.object(runtime, "create_capability_client", return_value=client), self.assertRaises(AIConnectionError) as raised:
            runtime.generate_embedding_batch(["text"], settings=self.settings)
        self.assertEqual(raised.exception.code, "embedding_authentication_failed")
        self.assertNotIn("sensitive-auth", str(raised.exception))
        handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
