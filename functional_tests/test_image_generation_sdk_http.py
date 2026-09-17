# test_image_generation_sdk_http.py
"""
Functional tests for image URLs, authentication, payloads, and output with the real OpenAI SDK.
Version: 0.261.107
Implemented in: 0.261.105

Uses the application's pinned openai==1.109.1 client and httpx.MockTransport. Only
HTTP is mocked: request construction, auth_headers, multipart encoding, response parsing,
and error handling execute in the installed SDK. Provider-qualified Custom image
coverage was added in 0.261.107. No provider services are contacted.
"""

import base64
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import openai
from flask import session

TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_ROOT))

# The reusable fixture isolates Cosmos, credential creation, and server-side secret resolution.
from test_ai_connection_image_runtime import (  # noqa: E402
    APP_ROOT,
    IMAGE_BASE64,
    IMAGE_BYTES,
    IMAGE_SOURCE,
    ImageRuntimeTestCase,
    connections,
    endpoint_auth,
    generation,
    image_edit,
    image_route,
    png_bytes,
    responses_image_response,
    shared_image_settings,
)


class ImageSdkHttpTests(ImageRuntimeTestCase):
    def setUp(self):
        super().setUp()
        self.requests = []
        self.status = 200
        self.response_override = None
        client_class = generation._ImageOpenAIClient

        def build_client(**kwargs):
            # Custom kwargs already own the mocked guarded transport; preserve that exact client.
            if "http_client" not in kwargs:
                kwargs["http_client"] = self.make_http_client()
            return client_class(**kwargs)

        self.constructor = self.stack.enter_context(patch.object(
            generation, "_ImageOpenAIClient", side_effect=build_client
        ))

    def handle_request(self, request):
        self.requests.append(request)
        body = self.response_override
        if body is None:
            body = (
                responses_image_response()
                if request.url.path.endswith("/responses")
                else {"created": 1, "data": [{"b64_json": IMAGE_BASE64}]}
            )
        return httpx.Response(self.status, json=body, headers={"x-request-id": "test-request-1"})

    def test_installed_sdk_matches_existing_application_requirement(self):
        requirement = next(
            line.strip().split("==", 1)[1]
            for line in APP_ROOT.joinpath("requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.startswith("openai==")
        )
        self.assertEqual(
            openai.__version__, requirement,
            f"The existing application requirement openai=={requirement} is missing from this interpreter.",
        )

    def test_custom_responses_urls_preserve_auto_and_exact_gateway_paths(self):
        cases = [
            ("https://api.openai.com", "auto", "/v1/responses"),
            ("https://api.openai.com/v1", "auto", "/v1/responses"),
            ("https://api.openai.com/v1/images/generations", "auto", "/v1/responses"),
            ("https://gateway.example/models/team/openai", "auto", "/models/team/openai/v1/responses"),
            ("https://gateway.example/api/projects/my-project", "auto", "/api/projects/my-project/v1/responses"),
            ("https://gateway.example/team/openai/v1/responses", "auto", "/team/openai/v1/responses"),
            ("https://gateway.example/exact/base", "exact", "/exact/base/responses"),
        ]
        for endpoint, url_mode, expected_path in cases:
            with self.subTest(endpoint=endpoint):
                settings = shared_image_settings(provider="custom")
                settings["model_endpoints"][0]["connection"].update({
                    "endpoint": endpoint, "url_mode": url_mode, "image_provider": "openai",
                })
                before = copy.deepcopy(settings)
                request_count = len(self.requests)
                result = generation.request_generated_image_source(settings, "A mountain")
                sent = self.requests[-1]
                self.assertEqual(result, IMAGE_SOURCE)
                self.assertEqual(sent.url.path, expected_path)
                self.assertEqual(sent.url.host, httpx.URL(endpoint).host)
                self.assertEqual(dict(sent.url.params), {})
                body = json.loads(sent.content)
                self.assertEqual(body["model"], "gpt-5.6-terra")
                self.assertEqual(body["tools"], [{"type": "image_generation"}])
                self.assertEqual(body["tool_choice"], {"type": "image_generation"})
                self.assertEqual(body["input"], "A mountain")
                self.assertEqual(sent.headers["authorization"], "Bearer resolved-connection-key")
                self.assertNotIn("api-key", sent.headers)
                self.assertNotIn("x-ms-oai-image-generation-deployment", sent.headers)
                self.assertEqual(len(self.requests), request_count + 1)
                self.assertTrue(self.custom_http_clients[-1].is_closed)
                self.assertEqual(settings, before)

    def test_custom_gateway_subscription_auth_and_identity_header_are_preserved(self):
        settings = shared_image_settings(provider="custom")
        endpoint = settings["model_endpoints"][0]
        endpoint["connection"]["endpoint"] = "https://gateway.example/controlled/team"
        endpoint["connection"]["image_provider"] = "openai"
        endpoint["auth"].update({"api_key_header": "api-key", "api_key_prefix": ""})
        endpoint["connection"]["operation_settings"]["image_generation"].update({
            "is_apim": True, "auth_header": "api-key", "image_deployment": "verified-backend",
        })
        settings.update({
            "model_endpoint_identity_header_enabled": True,
            "model_endpoint_identity_header_name": "x-test-identity",
            "model_endpoint_identity_header_value_type": "user_oid_tenant_id",
            "model_endpoint_identity_header_hmac_secret": "test-hmac-key",
        })
        with self.app.test_request_context():
            session["user"] = {"oid": "user-1", "tid": "tenant-1"}
            generation.request_generated_image_source(
                settings, "A mountain", size="1024x1536", quality="high", background="transparent"
            )
        sent = self.requests[-1]
        self.assertEqual(sent.url.path, "/controlled/team/v1/responses")
        self.assertEqual(sent.headers["api-key"], "resolved-connection-key")
        self.assertFalse(sent.headers.get("authorization"))
        self.assertNotIn("x-ms-oai-image-generation-deployment", sent.headers)
        self.assertEqual(dict(sent.url.params), {})
        self.assertEqual(json.loads(sent.content)["model"], "gpt-5.6-terra")
        self.assertEqual(len(sent.headers["x-test-identity"]), 64)
        self.assertNotIn("user-1", sent.headers["x-test-identity"])
        tool = json.loads(sent.content)["tools"][0]
        self.assertEqual(tool, {
            "type": "image_generation", "size": "1024x1536", "quality": "high", "background": "transparent",
        })
        self.assertNotIn("model", tool)

    def test_azure_gateway_subscription_header_does_not_add_a_bearer_key(self):
        settings = shared_image_settings(direct=True)
        settings["model_endpoints"][0]["connection"]["operation_settings"]["image_generation"].update({
            "is_apim": True, "auth_header": "ocp-apim-subscription-key",
        })
        generation.request_generated_image_source(settings, "A mountain")
        headers = self.requests[-1].headers
        self.assertEqual(headers["ocp-apim-subscription-key"], "resolved-connection-key")
        self.assertNotIn("api-key", headers)
        self.assertNotIn("authorization", headers)
        self.assertEqual(self.requests[-1].url.path, "/openai/deployments/selected-image/images/generations")

    def test_managed_identity_tokens_are_refreshed_as_strings_per_request(self):
        settings = shared_image_settings(direct=True)
        auth = {"type": "managed_identity", "managed_identity_client_id": "identity-1"}
        settings["model_endpoints"][0]["auth"] = auth
        self.token_provider.side_effect = ["token-one", "token-two"]
        client, deployment = generation.resolve_image_generation_client(settings)
        try:
            for _ in range(2):
                response = client.images.generate(
                    model=deployment, prompt="A mountain", n=1,
                )
                self.assertEqual(generation.extract_generated_image_source(response), IMAGE_SOURCE)
        finally:
            client.close()
        self.assertEqual([item.headers["authorization"] for item in self.requests], ["Bearer token-one", "Bearer token-two"])
        self.auth_runtime.resolve_credential_for_model_endpoint_auth.assert_called_once_with(auth)
        self.token_builder.assert_called_once_with(self.credential, "https://cognitiveservices.azure.com/.default")
        self.assertIsInstance(self.constructor.call_args.kwargs["api_key"], str)
        self.assertNotIn("api-key", self.requests[-1].headers)

    def test_foundry_service_principal_uses_stored_secret_and_endpoint_cloud(self):
        settings = shared_image_settings(direct=True, provider="new_foundry")
        settings["model_endpoints"][0]["auth"] = {
            "type": "service_principal", "tenant_id": "tenant-1", "client_id": "app-1",
            "client_secret": "vault-reference", "management_cloud": "government",
        }
        generation.request_generated_image_source(settings, "A mountain")
        auth = self.auth_runtime.resolve_credential_for_model_endpoint_auth.call_args.args[0]
        self.assertEqual(auth["client_secret"], "resolved-client-secret")
        self.assertEqual(auth["management_cloud"], "government")
        self.auth_runtime.resolve_foundry_scope_for_endpoint_auth.assert_not_called()
        self.token_builder.assert_called_once_with(self.credential, "https://cognitiveservices.azure.com/.default")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer fresh-token")
        self.assertEqual(settings["model_endpoints"][0]["auth"]["client_secret"], "vault-reference")

    def test_identity_audience_follows_endpoint_cloud_or_explicit_scope(self):
        cases = (
            ("aoai", "https://images.openai.azure.us", "managed_identity", "", "https://cognitiveservices.azure.us/.default"),
            ("new_foundry", "https://images.services.ai.azure.us", "service_principal", "", "https://cognitiveservices.azure.us/.default"),
            ("new_foundry", "https://images.services.ai.azure.com", "service_principal", "", "https://cognitiveservices.azure.com/.default"),
            ("aoai", "https://images.openai.azure.com", "managed_identity", "https://inference.example/.default", "https://inference.example/.default"),
        )
        for provider, url, auth_type, explicit_scope, expected_scope in cases:
            with self.subTest(provider=provider, endpoint=url, auth_type=auth_type, explicit_scope=explicit_scope):
                settings = shared_image_settings(direct=True, provider=provider)
                endpoint = settings["model_endpoints"][0]
                endpoint["connection"]["endpoint"] = url
                endpoint["auth"] = {
                    "type": auth_type,
                    "management_cloud": "public" if ".azure.us" in url else "government",
                }
                if auth_type == "service_principal":
                    endpoint["auth"].update({
                        "tenant_id": "tenant-1", "client_id": "app-1", "client_secret": "vault-reference",
                    })
                if explicit_scope:
                    endpoint["auth"]["foundry_scope"] = explicit_scope
                original = copy.deepcopy(settings)
                self.token_builder.reset_mock()
                opposite_app_scope = (
                    "https://cognitiveservices.azure.com/.default" if ".azure.us" in url
                    else "https://cognitiveservices.azure.us/.default"
                )
                with patch.object(sys.modules["config"], "cognitive_services_scope", opposite_app_scope):
                    generation.request_generated_image_source(settings, "Use the configured endpoint")
                self.token_builder.assert_called_once_with(self.credential, expected_scope)
                self.assertEqual(self.requests[-1].url.host, httpx.URL(url).host)
                self.assertEqual(self.requests[-1].url.path, "/openai/deployments/selected-image/images/generations")
                self.assertEqual(settings, original)
        self.auth_runtime.resolve_foundry_scope_for_endpoint_auth.assert_not_called()

    def test_custom_auth_headers_reach_images_and_responses_without_azure_credentials(self):
        auth_cases = (
            ({"type": "api_key", "api_key": "vault-reference"}, "authorization", "Bearer resolved-connection-key"),
            ({
                "type": "api_key", "api_key": "vault-reference",
                "api_key_header": "x-gateway-key", "api_key_prefix": "Token",
            }, "x-gateway-key", "Token resolved-connection-key"),
            ({"type": "bearer", "bearer_token": "fixture-image-token"}, "authorization", "Bearer fixture-image-token"),
            ({
                "type": "oauth2_client_credentials", "token_url": "https://identity.example/token",
                "client_id": "app-1", "client_secret": "vault-reference", "scope": "inference",
            }, "authorization", "Bearer fresh-oauth-token"),
        )
        with patch.object(endpoint_auth, "fetch_oauth2_client_credentials_token", return_value="fresh-oauth-token") as token:
            for direct in (False, True):
                for auth, header, expected in auth_cases:
                    with self.subTest(direct=direct, auth_type=auth["type"], header=header):
                        settings = shared_image_settings(direct=direct, provider="custom")
                        endpoint = settings["model_endpoints"][0]
                        endpoint["auth"] = dict(auth)
                        endpoint["models"][0]["enabled_capabilities"] = ["image_generation"]
                        original = copy.deepcopy(settings)
                        self.assertEqual(generation.request_generated_image_source(settings, "A mountain"), IMAGE_SOURCE)
                        sent = self.requests[-1]
                        self.assertEqual(sent.headers[header], expected)
                        self.assertEqual(len(sent.headers.get_list("authorization")), 1)
                        if header != "authorization":
                            self.assertEqual(sent.headers["authorization"], "")
                            self.assertEqual(self.constructor.call_args.kwargs["default_headers"]["Authorization"], "")
                        self.assertNotIn("api-key", sent.headers)
                        self.assertNotIn("x-ms-oai-image-generation-deployment", sent.headers)
                        self.assertEqual(dict(sent.url.params), {})
                        self.assertEqual(
                            sent.url.path, "/v1/images/generations" if direct else "/v1/responses"
                        )
                        self.assertEqual(
                            json.loads(sent.content)["model"], "gpt-image-1" if direct else "gpt-5.6-terra"
                        )
                        self.assertEqual(settings, original)
            self.assertEqual(token.call_count, 2)
            self.assertEqual(token.call_args.args[0]["client_secret"], "resolved-client-secret")
        self.auth_runtime.resolve_credential_for_model_endpoint_auth.assert_not_called()
        self.token_builder.assert_not_called()

    def test_azure_foundry_and_mislabeled_custom_gpt_never_reach_the_sdk(self):
        variants = []
        for provider in ("aoai", "aifoundry", "new_foundry"):
            for route in ("images", "responses"):
                settings = shared_image_settings(provider=provider)
                endpoint = settings["model_endpoints"][0]
                endpoint["models"][0]["image_generation_api"] = route
                endpoint["connection"]["operation_settings"]["image_generation"]["image_deployment"] = "selected-image"
                alternative = shared_image_settings(direct=True)["model_endpoints"][0]["models"][0]
                endpoint["models"].append({**alternative, "id": "available-image"})
                variants.append(settings)
        settings = shared_image_settings(provider="custom")
        settings["model_endpoints"][0]["connection"].update({
            "endpoint": "https://images.openai.azure.us", "image_provider": "openai",
        })
        variants.append(settings)
        settings = shared_image_settings(provider="custom")
        endpoint = settings["model_endpoints"][0]
        endpoint["connection"]["endpoint"] = "https://gateway.example/v1"
        endpoint["models"][0].pop("supportsImageGeneration")
        endpoint["models"][0].pop("image_generation_api")
        variants.append(settings)
        for settings in variants:
            with self.subTest(endpoint=settings["model_endpoints"][0]["connection"]["endpoint"]):
                original = copy.deepcopy(settings)
                with self.assertRaises(connections.AIConnectionError):
                    generation.request_generated_image_source(settings, "Do not use another image model")
                self.assertEqual(settings, original)
        self.assertEqual(self.requests, [])
        self.constructor.assert_not_called()
        self.secret_helper.assert_not_called()
        self.custom_http_factory.assert_not_called()

    def test_custom_native_images_use_model_names_without_azure_transport_metadata(self):
        settings = shared_image_settings(direct=True, provider="custom")
        before = copy.deepcopy(settings)
        result = generation.request_generated_image_source(settings, "A mountain", size="1024x1024")
        sent = self.requests[-1]
        self.assertEqual(sent.url, httpx.URL("https://api.openai.com/v1/images/generations"))
        self.assertEqual(json.loads(sent.content), {
            "model": "gpt-image-1", "prompt": "A mountain", "n": 1, "size": "1024x1024",
        })
        self.assertEqual(sent.headers["authorization"], "Bearer resolved-connection-key")
        self.assertNotIn("api-key", sent.headers)
        self.assertNotIn("x-ms-oai-image-generation-deployment", sent.headers)
        self.assertEqual(result, IMAGE_SOURCE)
        self.assertEqual(settings, before)

    def test_dedicated_images_keep_legacy_deployment_path_and_operation_version(self):
        settings = shared_image_settings(direct=True)
        settings["model_endpoints"][0]["connection"]["endpoint"] = "https://gateway.example/models/team/openai"
        result = generation.request_generated_image_source(settings, "A mountain", size="1024x1024")
        sent = self.requests[-1]
        self.assertEqual(sent.url.path, "/models/team/openai/deployments/selected-image/images/generations")
        self.assertEqual(dict(sent.url.params), {"api-version": "2025-04-01-preview"})
        self.assertEqual(sent.headers["api-key"], "resolved-connection-key")
        self.assertEqual(json.loads(sent.content), {
            "model": "selected-image", "prompt": "A mountain", "n": 1, "size": "1024x1024",
        })
        self.assertEqual(result, IMAGE_SOURCE)

    def test_new_shared_images_have_an_independent_modern_default(self):
        for operation_settings in (None, {}, {"image_generation": {}}):
            with self.subTest(operation_settings=operation_settings):
                settings = shared_image_settings(direct=True)
                connection = settings["model_endpoints"][0]["connection"]
                connection["api_version"] = "2024-05-01-preview"
                connection["openai_api_version"] = "2024-05-01-preview"
                connection.pop("operation_settings")
                if operation_settings is not None:
                    connection["operation_settings"] = operation_settings
                settings.update({
                    "enable_image_gen_apim": True,
                    "azure_openai_image_gen_api_version": "2023-12-01-preview",
                    "azure_apim_image_gen_api_version": "2024-02-15-preview",
                })
                before = copy.deepcopy(settings)
                generation.request_generated_image_source(settings, "A new shared image")
                sent = self.requests[-1]
                self.assertEqual(dict(sent.url.params), {"api-version": "2025-04-01-preview"})
                self.assertEqual(sent.url.host, "team-one.openai.azure.com")
                self.assertEqual(sent.url.path, "/openai/deployments/selected-image/images/generations")
                self.assertEqual(image_route.resolve_image_generation_api_version(settings), "2025-04-01-preview")
                self.assertEqual(image_edit.resolve_image_edit_capability(settings)["mode"], "masked")
                self.assertEqual(settings, before)

    def test_dated_images_key_auth_depends_on_transport_not_provider_label(self):
        for provider in ("aoai", "aifoundry", "new_foundry"):
            with self.subTest(provider=provider, operation="generate"):
                settings = shared_image_settings(direct=True, provider=provider)
                generation.request_generated_image_source(settings, "A mountain")
                sent = self.requests[-1]
                self.assertIn("/deployments/selected-image/images/generations", sent.url.path)
                self.assertEqual(sent.headers["api-key"], "resolved-connection-key")
                self.assertNotIn("authorization", sent.headers)
            with self.subTest(provider=provider, operation="edit"):
                client, deployment = generation.resolve_image_generation_client(settings)
                try:
                    client.images.edit(
                        model=deployment,
                        prompt="Make the sky blue",
                        image=("source.png", base64.b64decode(IMAGE_BASE64), "image/png"),
                    )
                finally:
                    client.close()
                sent = self.requests[-1]
                self.assertIn("/deployments/selected-image/images/edits", sent.url.path)
                self.assertEqual(sent.headers["api-key"], "resolved-connection-key")
                self.assertNotIn("authorization", sent.headers)

    def test_explicit_imported_image_api_versions_are_preserved(self):
        for imported_version in ("2024-05-01-preview", "2024-12-01-preview", "2025-04-01-preview"):
            with self.subTest(imported_version=imported_version):
                settings = shared_image_settings(direct=True)
                endpoint = settings["model_endpoints"][0]
                endpoint["models"][0]["enabled_capabilities"] = ["image_generation"]
                endpoint["connection"]["openai_api_version"] = "2023-03-15-preview"
                endpoint["connection"]["operation_settings"]["image_generation"]["api_version"] = imported_version
                settings["azure_openai_image_gen_api_version"] = "2026-01-01-preview"
                generation.request_generated_image_source(settings, "An imported image connection")
                self.assertEqual(dict(self.requests[-1].url.params), {"api-version": imported_version})
                self.assertEqual(image_route.resolve_image_generation_api_version(settings), imported_version)

    def test_apim_wire_auth_and_paths_are_preserved_for_both_image_routes(self):
        for direct in (False, True):
            for auth_header in (None, "api-key", "ocp-apim-subscription-key"):
                with self.subTest(direct=direct, auth_header=auth_header):
                    settings = shared_image_settings(
                        direct=direct, provider="new_foundry" if direct else "custom"
                    )
                    endpoint = settings["model_endpoints"][0]
                    connection = endpoint["connection"]
                    connection["endpoint"] = "https://gateway.example/models/published-images/openai"
                    profile = connection["operation_settings"]["image_generation"]
                    profile.update({"is_apim": True, "api_version": "2024-12-01-preview"})
                    if auth_header:
                        profile["auth_header"] = auth_header
                    if not direct:
                        connection["image_provider"] = "openai"
                        endpoint["auth"].update({
                            "api_key_header": auth_header or "api-key", "api_key_prefix": "",
                        })
                    generation.request_generated_image_source(settings, "Keep the published gateway")
                    sent = self.requests[-1]
                    self.assertEqual(sent.url.host, "gateway.example")
                    self.assertEqual(
                        sent.url.path,
                        "/models/published-images/openai/deployments/selected-image/images/generations"
                        if direct else "/models/published-images/openai/v1/responses",
                    )
                    self.assertEqual(
                        dict(sent.url.params),
                        {"api-version": "2024-12-01-preview"} if direct else {},
                    )
                    expected_header = auth_header or "api-key"
                    self.assertEqual(sent.headers[expected_header], "resolved-connection-key")
                    self.assertFalse(sent.headers.get("authorization"))
                    other_header = "api-key" if expected_header == "ocp-apim-subscription-key" else "ocp-apim-subscription-key"
                    self.assertNotIn(other_header, sent.headers)
                    self.assertNotIn("x-ms-oai-image-generation-deployment", sent.headers)
                    self.assertEqual(
                        json.loads(sent.content)["model"], "selected-image" if direct else "gpt-5.6-terra"
                    )

    def test_unmigrated_legacy_images_keep_their_sdk_route_but_gpt_is_rejected(self):
        settings = shared_image_settings()
        settings.pop(connections.IMAGE_SELECTION_KEY)
        generation.request_generated_image_source(settings, "Legacy image")
        self.assertEqual(self.requests[-1].url.path, "/openai/deployments/legacy-image/images/generations")
        self.assertEqual(dict(self.requests[-1].url.params), {"api-version": "2024-12-01-preview"})
        self.assertEqual(self.requests[-1].headers["api-key"], "legacy-key")
        settings.pop("azure_openai_image_gen_api_version")
        generation.request_generated_image_source(settings, "Legacy image without a saved version")
        self.assertEqual(dict(self.requests[-1].url.params), {"api-version": "2024-12-01-preview"})
        settings["image_gen_model"]["selected"] = [{
            "deploymentName": "legacy-gpt", "modelName": "gpt-5.6-terra",
        }]
        with self.assertRaises(connections.AIConnectionError) as caught:
            generation.request_generated_image_source(settings, "Legacy GPT image")
        self.assertEqual(caught.exception.code, "model_capability_unavailable")
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(request.url.path.endswith("/images/generations") for request in self.requests))
        self.secret_helper.assert_not_called()

    def test_masked_edit_keeps_actual_sdk_multipart_payload(self):
        settings = shared_image_settings(direct=True)
        mask_bytes = png_bytes()
        with patch.object(image_edit, "_finish_image_edit", return_value={"method": "edit"}):
            image_edit.request_image_edit(
                settings, {"file_name": "source.png", "bytes": IMAGE_BYTES, "mime_type": "image/png"},
                "Change the sky", mask={"bytes": mask_bytes}, quality="high", operation="edit",
            )
        sent = self.requests[-1]
        self.assertEqual(sent.url.path, "/openai/deployments/selected-image/images/edits")
        self.assertEqual(dict(sent.url.params), {"api-version": "2025-04-01-preview"})
        self.assertIn("multipart/form-data", sent.headers["content-type"])
        self.assertIn(b'name="image"; filename="source.png"', sent.content)
        self.assertIn(b'name="mask"; filename="mask.png"', sent.content)
        self.assertIn(b"selected-image", sent.content)
        self.assertIn(IMAGE_BYTES, sent.content)
        self.assertIn(mask_bytes, sent.content)
        self.assertIn(b'name="quality"', sent.content)
        self.assertIn(b"high", sent.content)
        self.assertNotIn(b'name="input_fidelity"', sent.content)
        self.assertEqual(len(self.requests), 1)

    def test_custom_gpt_masked_edits_use_responses_source_and_mask(self):
        settings = shared_image_settings(provider="custom")
        self.assertEqual(image_edit.resolve_image_edit_capability(settings)["mode"], "masked")
        mask_bytes = png_bytes()
        result = image_edit.request_image_edit(
            settings, {"file_name": "source.png", "bytes": IMAGE_BYTES, "mime_type": "image/png"},
            "Change the sky", mask={"bytes": mask_bytes}, quality="high", operation="edit",
        )
        sent = self.requests[-1]
        self.assertEqual(sent.url, httpx.URL("https://api.openai.com/v1/responses"))
        self.assertEqual(json.loads(sent.content), {
            "model": "gpt-5.6-terra",
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Change the sky"},
                    {"type": "input_image", "image_url": IMAGE_SOURCE},
                ],
            }],
            "tools": [{
                "type": "image_generation", "action": "edit", "quality": "high",
                "input_image_mask": {
                    "image_url": "data:image/png;base64," + base64.b64encode(mask_bytes).decode("ascii"),
                },
            }],
            "tool_choice": {"type": "image_generation"},
        })
        self.assertNotIn("api-key", sent.headers)
        self.assertNotIn("x-ms-oai-image-generation-deployment", sent.headers)
        self.assertEqual(result["method"], "edit")
        self.assertEqual(result["model"], "gpt-5.6-terra")
        self.assertEqual(result["bytes"], IMAGE_BYTES)
        self.assertEqual(len(self.requests), 1)

    def test_unsupported_masks_and_options_fail_before_transport_or_secret_resolution(self):
        settings = shared_image_settings(provider="custom")
        with self.assertRaises(image_route.ImageGenerationError) as invalid_options:
            generation.request_generated_image_source(settings, "A mountain", quality="unsupported-quality")
        self.assertEqual(invalid_options.exception.code, "invalid_image_request")
        self.assertEqual(invalid_options.exception.status_code, 400)
        with self.assertRaises(image_edit.ImageEditError) as invalid_mask:
            image_edit.request_image_edit(
                settings, None, "A mountain", mask={"bytes": png_bytes()}, operation="regenerate"
            )
        self.assertEqual(invalid_mask.exception.code, "unsupported_image_operation")
        self.assertEqual(invalid_mask.exception.status_code, 400)
        self.assertEqual(self.requests, [])
        self.constructor.assert_not_called()
        self.secret_helper.assert_not_called()

    def test_service_errors_never_retry_another_paid_route_or_expose_details(self):
        for status, detail, expected in (
            (429, {"code": "rate_limit_exceeded", "message": "private-key private-prompt"}, 429),
            (400, {"code": "BadRequest", "message": "x-ms-oai-image-generation-deployment required; private-key"}, 503),
            (400, {"code": "content_policy_violation", "message": "private-prompt"}, 400),
        ):
            with self.subTest(status=status):
                self.requests.clear()
                self.status = status
                self.response_override = {"error": detail}
                with self.assertRaises(image_route.ImageGenerationError) as caught:
                    generation.request_generated_image_source(shared_image_settings(provider="custom"), "private-prompt")
                payload, response_status = generation.image_generation_error_response(caught.exception)
                self.assertEqual(response_status, expected)
                self.assertEqual(len(self.requests), 1)
                self.assertTrue(self.requests[0].url.path.endswith("/responses"))
                self.assertEqual(self.requests[0].url.host, "api.openai.com")
                self.assertEqual(json.loads(self.requests[0].content)["model"], "gpt-5.6-terra")
                self.assertNotIn("x-ms-oai-image-generation-deployment", self.requests[0].headers)
                self.assertTrue(self.custom_http_clients[-1].is_closed)
                self.assertNotIn("private-key", json.dumps(payload))
                self.assertNotIn("private-prompt", json.dumps(payload))
        self.assertNotIn("private-key", str(self.logs.call_args_list))
        self.assertNotIn("private-prompt", str(self.logs.call_args_list))

    def test_sdk_incomplete_response_is_not_accepted_despite_image_bytes(self):
        self.response_override = responses_image_response(status="incomplete")
        with self.assertRaises(image_route.ImageGenerationError) as caught:
            generation.request_generated_image_source(shared_image_settings(provider="custom"), "A mountain")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(caught.exception.context["request_id"], "test-request-1")
        self.assertEqual(caught.exception.context["provider_status"], "incomplete")
        self.assertEqual(self.logs.call_args.kwargs["extra"]["route"], "responses")

    def test_whole_image_regeneration_decodes_a_displayable_sdk_result(self):
        result = image_edit.request_image_edit(
            shared_image_settings(provider="custom"), None, "A mountain", operation="regenerate"
        )
        self.assertEqual((result["width"], result["height"]), (1, 1))
        self.assertEqual(result["mime_type"], "image/png")
        self.assertEqual(result["method"], "regenerate")
        self.assertEqual(result["model"], "gpt-5.6-terra")
        self.assertEqual(result["bytes"], IMAGE_BYTES)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads(self.requests[0].content)["input"], "A mountain")


if __name__ == "__main__":
    unittest.main()
