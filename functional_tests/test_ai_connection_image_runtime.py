# test_ai_connection_image_runtime.py
"""
Functional tests for shared image bindings, persistence, proposals, editing, and admin tests.
Version: 0.261.105
Implemented in: 0.261.105

Application storage, secret retrieval, and credentials are isolated before runtime imports.
No Azure inference, provisioning, or Cosmos initialization is performed.
"""

import ast
import base64
import copy
import json
import logging
import sys
import textwrap
import types
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from flask import Flask, jsonify, request
from openai import BadRequestError, RateLimitError

TEST_ROOT = Path(__file__).resolve().parent
APP_ROOT = TEST_ROOT.parent.joinpath("application", "single_app")
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(APP_ROOT))

# Application paths and import seams must be installed before loading runtime modules.
from test_support.app_stubs import import_app_module, stubbed_config  # noqa: E402
import functions_ai_connections as connections  # noqa: E402
import functions_image_api_route as image_route  # noqa: E402
import functions_image_edit as image_edit  # noqa: E402


generation = import_app_module("functions_image_generation")
IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
IMAGE_SOURCE = f"data:image/png;base64,{IMAGE_BASE64}"


def shared_image_settings(*, direct=False, provider="aoai"):
    model = {
        "id": "stable-model",
        "deploymentName": "selected-image" if direct else "selected-gpt",
        "modelName": "gpt-image-1" if direct else "gpt-5.6-terra",
        "supportsImageGeneration": True,
        "image_generation_api": "images" if direct else "responses",
        "enabled": True,
    }
    return {
        "enable_image_generation": True,
        "enable_multi_model_endpoints": False,
        connections.IMAGE_SELECTION_KEY: {
            "endpoint_id": "team-one",
            "model_id": "stable-model",
            "provider": provider,
        },
        "model_endpoints": [{
            "id": "team-one",
            "name": "Team Azure",
            "provider": provider,
            "enabled": True,
            "connection": {
                "endpoint": "https://team-one.openai.azure.com",
                "api_version": "2023-03-15-preview",
                "operation_settings": {
                    "image_generation": {
                        "api_version": "2025-04-01-preview",
                        "is_apim": False,
                    },
                },
            },
            "auth": {"type": "api_key", "api_key": "vault-reference"},
            "models": [model],
        }],
        "image_gen_model": {"selected": [{"deploymentName": "legacy-image", "modelName": "dall-e-3"}]},
        "azure_openai_image_gen_endpoint": "https://legacy.openai.azure.com",
        "azure_openai_image_gen_key": "legacy-key",
        "azure_openai_image_gen_api_version": "2024-12-01-preview",
    }


def responses_image_response(**overrides):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "selected-gpt",
        "output": [{
            "id": "ig_test",
            "type": "image_generation_call",
            "status": "completed",
            "result": IMAGE_BASE64,
        }],
        **overrides,
    }


def load_route_functions(file_name, names, namespace, *, strip_decorators=True):
    """Execute the actual selected handlers without importing the application's startup graph."""
    tree = ast.parse(APP_ROOT.joinpath(file_name).read_text(encoding="utf-8-sig"))
    selected = []
    for name in names:
        node = next(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef) and item.name == name)
        node = copy.deepcopy(node)
        if strip_decorators:
            node.decorator_list = []
        selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), file_name, "exec"), namespace)
    return namespace


class ImageRuntimeTestCase(unittest.TestCase):
    """Reusable import/HTTP seams for unit and real-SDK transport coverage."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.messages = Mock()
        self.stack.enter_context(stubbed_config(
            cognitive_services_scope="https://cognitiveservices.azure.com/.default",
            cosmos_messages_container=self.messages,
        ))
        self.secret_helper = Mock(side_effect=self.resolve_secret)
        keyvault = types.ModuleType("functions_keyvault")
        keyvault.SecretReturnType = types.SimpleNamespace(VALUE="value")
        keyvault.keyvault_model_endpoint_get_helper = self.secret_helper
        runtime = types.ModuleType("functions_model_endpoint_runtime")
        self.credential = Mock()
        runtime.resolve_credential_for_model_endpoint_auth = Mock(return_value=self.credential)
        runtime.resolve_foundry_scope_for_endpoint_auth = Mock(return_value="https://ai.azure.us/.default")
        self.auth_runtime = runtime
        self.stack.enter_context(patch.dict(sys.modules, {
            "functions_image_generation": generation,
            "functions_keyvault": keyvault,
            "functions_model_endpoint_runtime": runtime,
        }))
        self.logs = self.stack.enter_context(patch.object(generation, "log_event"))
        self.token_provider = Mock(return_value="fresh-token")
        self.token_builder = self.stack.enter_context(patch.object(
            generation, "get_bearer_token_provider", return_value=self.token_provider
        ))
        factories = connections._CLIENT_FACTORIES
        previous = factories.get(connections.IMAGE_GENERATION_CAPABILITY)
        self.stack.callback(
            lambda: factories.pop(connections.IMAGE_GENERATION_CAPABILITY, None)
            if previous is None else factories.update({connections.IMAGE_GENERATION_CAPABILITY: previous})
        )
        connections.register_capability_client_factory(
            connections.IMAGE_GENERATION_CAPABILITY, generation.build_image_connection_client
        )
        self.app = Flask(__name__)
        self.app.secret_key = "test-only-session-key"

    @staticmethod
    def resolve_secret(endpoint, endpoint_id, *, scope, return_type):
        assert endpoint_id == endpoint["id"]
        assert scope == "global"
        assert return_type == "value"
        if endpoint.get("auth", {}).get("api_key") == "vault-reference":
            endpoint["auth"]["api_key"] = "resolved-connection-key"
        if endpoint.get("auth", {}).get("client_secret") == "vault-reference":
            endpoint["auth"]["client_secret"] = "resolved-client-secret"
        return endpoint

    def mock_client(self):
        client = Mock()
        client.images.generate.return_value = {"data": [{"b64_json": IMAGE_BASE64}]}
        client.responses.create.return_value = responses_image_response()
        factory = self.stack.enter_context(patch.object(generation, "_ImageOpenAIClient", return_value=client))
        return client, factory

    def admin_namespace(self, settings):
        namespace = {
            "get_settings": Mock(return_value=settings),
            "IMAGE_SELECTION_KEY": connections.IMAGE_SELECTION_KEY,
            "jsonify": jsonify,
            "log_event": self.logs,
            "image_generation_error_log_context": generation.image_generation_error_log_context,
            "image_generation_error_response": generation.image_generation_error_response,
            "request_generated_image_source": generation.request_generated_image_source,
            "resolve_admin_settings_secret_value": Mock(return_value="unmasked-legacy-key"),
        }
        load_route_functions("route_backend_settings.py", (
            "_resolve_test_payload_secret",
            "_resolve_admin_settings_test_secrets",
            "_image_connection_test_error_response",
            "_test_image_gen_connection",
            "run_admin_settings_connection_test",
        ), namespace)
        namespace["ADMIN_SETTINGS_CONNECTION_TESTS"] = {"image": namespace["_test_image_gen_connection"]}
        return namespace


class SharedImageRuntimeTests(ImageRuntimeTestCase):
    def test_chat_image_mode_does_not_require_text_client_initialization(self):
        source = APP_ROOT.joinpath("route_backend_chats.py").read_text(encoding="utf-8")
        setup = source.split("# GPT & Image generation APIM or direct", 1)[1].split(
            "# region 1 - Load or Create Conversation", 1
        )[0].rstrip()
        function_source = (
            "def run_setup():\n"
            + textwrap.indent(textwrap.dedent(setup), "    ")
            + "\n    return gpt_client, gpt_model, tabular_model_context\n"
        )
        namespace = {
            "settings": shared_image_settings(),
            "image_gen_enabled": True, "data": {}, "request_agent_info": None,
            "frontend_gpt_model": None, "user_id": "user-1", "conversation_id": "conversation-1",
            "active_group_ids": [], "logging": logging,
            "_has_chat_agent_selection": lambda value: False,
            "build_model_endpoint_identity_headers": Mock(return_value={}),
            "resolve_streaming_multi_endpoint_gpt_config": Mock(),
            "build_model_endpoint_context": Mock(return_value={"model_deployment": "text-deployment"}),
            "_resolve_legacy_chat_reasoning_model_name": Mock(return_value="gpt-4o"),
            "AzureOpenAI": Mock(return_value="text-client"),
            "debug_print": Mock(), "log_event": self.logs,
            "build_json_error_response": Mock(return_value="initialization-failed"),
        }
        exec(compile(function_source, "image_chat_setup_test", "exec"), namespace)
        for chat_switch in (False, True):
            namespace["settings"]["enable_multi_model_endpoints"] = chat_switch
            self.assertEqual(namespace["run_setup"](), (None, "", None))
        namespace["AzureOpenAI"].assert_not_called()
        namespace["resolve_streaming_multi_endpoint_gpt_config"].assert_not_called()
        namespace["build_model_endpoint_context"].assert_not_called()
        namespace["_resolve_legacy_chat_reasoning_model_name"].assert_not_called()
        namespace["image_gen_enabled"] = False
        namespace["settings"].update({
            "enable_multi_model_endpoints": False,
            "gpt_model": {"selected": [{"deploymentName": "text-deployment"}]},
            "azure_openai_gpt_key": "text-key",
        })
        self.assertEqual(
            namespace["run_setup"](),
            ("text-client", "text-deployment", {"model_deployment": "text-deployment"}),
        )
        namespace["AzureOpenAI"].assert_called_once()
        namespace["_resolve_legacy_chat_reasoning_model_name"].assert_called_once()
        namespace["settings"]["enable_multi_model_endpoints"] = True
        namespace["resolve_streaming_multi_endpoint_gpt_config"].return_value = (
            "shared-text-client", "text-deployment", "aoai", "https://chat.example.test",
            {"type": "api_key"}, "2025-04-01-preview", "text-endpoint", "text-model",
            None, None, None, "gpt-5.6-luna",
        )
        self.assertEqual(
            namespace["run_setup"](),
            ("shared-text-client", "text-deployment", {"model_deployment": "text-deployment"}),
        )
        namespace["_resolve_legacy_chat_reasoning_model_name"].assert_called_once()

    def test_registered_factory_returns_client_only_and_images_ignore_chat_gate(self):
        settings = shared_image_settings()
        client, constructor = self.mock_client()
        binding = connections.resolve_capability_binding(settings, "image_generation")
        self.assertIs(connections.create_capability_client(binding, settings), client)
        self.assertEqual(generation.request_generated_image_source(settings, "Draw a mountain"), IMAGE_SOURCE)
        arguments = client.responses.create.call_args.kwargs
        self.assertEqual(arguments["model"], "selected-gpt")
        self.assertEqual(arguments["tools"], [{"type": "image_generation"}])
        self.assertEqual(arguments["tool_choice"], {"type": "image_generation"})
        self.assertEqual(constructor.call_args.kwargs["base_url"], "https://team-one.openai.azure.com/openai/v1/")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {})
        self.assertEqual(constructor.call_args.kwargs["max_retries"], 0)
        client.images.generate.assert_not_called()

    def test_registered_factory_enforces_the_image_capability_gate(self):
        settings = shared_image_settings()
        settings["enable_image_generation"] = False
        _, constructor = self.mock_client()
        binding = connections.resolve_capability_binding(settings, "image_generation")
        with self.assertRaises(connections.AIConnectionError) as caught:
            connections.create_capability_client(binding, settings)
        self.assertEqual(caught.exception.code, "capability_disabled")
        constructor.assert_not_called()
        self.secret_helper.assert_not_called()

    def test_imported_image_only_models_choose_routes_without_a_connection_api(self):
        settings = shared_image_settings()
        endpoint = settings["model_endpoints"][0]
        endpoint["models"][0]["enabled_capabilities"] = ["image_generation"]
        dedicated = shared_image_settings(direct=True)["model_endpoints"][0]["models"][0]
        dedicated.update({"id": "dedicated-image", "enabled_capabilities": ["image_generation"]})
        endpoint["models"].append(dedicated)
        client, constructor = self.mock_client()

        self.assertEqual(generation.request_generated_image_source(settings, "Use selected GPT"), IMAGE_SOURCE)
        self.assertEqual(client.responses.create.call_args.kwargs["model"], "selected-gpt")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {})
        settings[connections.IMAGE_SELECTION_KEY]["model_id"] = "dedicated-image"
        self.assertEqual(generation.request_generated_image_source(settings, "Use selected image"), IMAGE_SOURCE)
        self.assertEqual(client.images.generate.call_args.kwargs["model"], "selected-image")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {"api-version": "2025-04-01-preview"})
        self.assertEqual(image_edit.resolve_image_edit_capability(settings)["mode"], "masked")
        self.assertNotIn("api", endpoint["connection"]["operation_settings"]["image_generation"])
        for model in endpoint["models"]:
            self.assertFalse(connections.supports_model_capability(model, "chat", "aoai"))
            self.assertTrue(connections.supports_model_capability(model, "image_generation", "aoai"))

    def test_stored_global_secret_is_resolved_without_mutating_registry(self):
        settings = shared_image_settings()
        before = copy.deepcopy(settings)
        _, constructor = self.mock_client()
        generation.request_generated_image_source(settings, "Draw a mountain")
        self.assertEqual(settings, before)
        self.assertEqual(constructor.call_args.kwargs["api_key"], "resolved-connection-key")
        self.assertEqual(self.secret_helper.call_args.args[1], "team-one")
        self.assertEqual(self.secret_helper.call_args.kwargs, {"scope": "global", "return_type": "value"})

    def test_rotated_key_is_read_for_each_request(self):
        settings = shared_image_settings()
        _, constructor = self.mock_client()
        generation.request_generated_image_source(settings, "First image")
        settings["model_endpoints"][0]["auth"]["api_key"] = "rotated-key"
        generation.request_generated_image_source(settings, "Second image")
        self.assertEqual(constructor.call_args.kwargs["api_key"], "rotated-key")
        self.assertEqual(self.secret_helper.call_count, 2)

    def test_cleared_missing_disabled_and_forged_selections_never_reactivate_legacy(self):
        _, constructor = self.mock_client()
        variants = []
        for value in (None, {}, {"endpoint_id": "", "model_id": "", "provider": ""}):
            settings = shared_image_settings()
            settings[connections.IMAGE_SELECTION_KEY] = value
            variants.append(settings)
        settings = shared_image_settings()
        settings.pop(connections.IMAGE_SELECTION_KEY)
        settings[connections.IMAGE_MIGRATION_VERSION_KEY] = connections.IMAGE_MIGRATION_VERSION
        variants.append(settings)
        for field, value in (("endpoint_id", "personal-endpoint"), ("model_id", "other-model"), ("provider", "new_foundry")):
            settings = shared_image_settings()
            settings[connections.IMAGE_SELECTION_KEY][field] = value
            variants.append(settings)
        for target in ("endpoint", "model"):
            settings = shared_image_settings()
            entry = settings["model_endpoints"][0]
            (entry if target == "endpoint" else entry["models"][0])["enabled"] = False
            variants.append(settings)
        settings = shared_image_settings()
        settings["model_endpoints"][0]["models"][0]["enabled_capabilities"] = ["chat"]
        variants.append(settings)
        settings = shared_image_settings()
        settings["model_endpoints"][0]["models"][0].pop("deploymentName")
        variants.append(settings)
        bootstrap = load_route_functions(
            "route_backend_v2.py", ("_build_capabilities",),
            {"resolve_image_edit_capability": image_edit.resolve_image_edit_capability},
        )
        for settings in variants:
            with self.subTest(selection=settings.get(connections.IMAGE_SELECTION_KEY)):
                before = copy.deepcopy(settings)
                self.assertEqual(image_route.resolve_selected_image_model_name(settings), "")
                capability = image_edit.resolve_image_edit_capability(settings)
                self.assertFalse(capability["enabled"])
                self.assertTrue(capability["reason"])
                projection = bootstrap["_build_capabilities"](settings)["image_edit"]
                self.assertEqual(projection["model_name"], "")
                self.assertEqual(projection["reason"], capability["reason"])
                self.assertNotIn("vault-reference", json.dumps(projection))
                with self.assertRaises(connections.AIConnectionError):
                    image_route.resolve_selected_image_deployment_name(settings)
                with self.assertRaises(connections.AIConnectionError):
                    generation.request_generated_image_source(settings, "Do not use legacy")
                self.assertEqual(settings, before)
        constructor.assert_not_called()
        self.secret_helper.assert_not_called()

    def test_unestablished_gpt_capability_is_not_inferred_from_its_name(self):
        settings = shared_image_settings()
        model = settings["model_endpoints"][0]["models"][0]
        model.pop("supportsImageGeneration")
        model["modelName"] = "gpt-not-a-verified-image-tool-model"
        _, constructor = self.mock_client()
        with self.assertRaises(connections.AIConnectionError):
            generation.request_generated_image_source(settings, "Draw a mountain")
        constructor.assert_not_called()

    def test_legacy_and_shared_direct_images_keep_their_versions(self):
        client, constructor = self.mock_client()
        settings = shared_image_settings(direct=True)
        generation.request_generated_image_source(settings, "Shared image")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {"api-version": "2025-04-01-preview"})
        self.assertIn("/openai/deployments/selected-image/", constructor.call_args.kwargs["base_url"])
        self.assertEqual(settings["model_endpoints"][0]["connection"]["api_version"], "2023-03-15-preview")
        settings.pop(connections.IMAGE_SELECTION_KEY)
        generation.request_generated_image_source(settings, "Legacy image")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {"api-version": "2024-12-01-preview"})
        self.assertEqual(constructor.call_args.kwargs["api_key"], "legacy-key")
        self.assertEqual(client.images.generate.call_args.kwargs["model"], "legacy-image")
        client.responses.create.assert_not_called()

    def test_no_arbitrary_image_backend_or_cross_connection_selection(self):
        settings = shared_image_settings()
        image_model = shared_image_settings(direct=True)["model_endpoints"][0]["models"][0]
        settings["model_endpoints"][0]["models"].append({**image_model, "id": "image-one"})
        settings["model_endpoints"].append({
            **copy.deepcopy(settings["model_endpoints"][0]),
            "id": "other-resource",
            "connection": {"endpoint": "https://other-resource.openai.azure.com"},
        })
        _, constructor = self.mock_client()
        generation.request_generated_image_source(settings, "Use provider default")
        self.assertNotIn("x-ms-oai-image-generation-deployment", constructor.call_args.kwargs["default_headers"])
        profile = settings["model_endpoints"][0]["connection"]["operation_settings"]["image_generation"]
        profile["image_deployment"] = "selected-image"
        generation.request_generated_image_source(settings, "Use explicitly stored backend")
        self.assertEqual(constructor.call_args.kwargs["default_headers"]["x-ms-oai-image-generation-deployment"], "selected-image")
        profile["image_deployment"] = "selected-gpt"
        with self.assertRaises(connections.AIConnectionError):
            generation.request_generated_image_source(settings, "Do not use GPT as image backend")
        self.assertEqual(constructor.call_count, 2)

    def test_migrated_images_profile_does_not_force_selected_gpt_onto_images(self):
        settings = shared_image_settings()
        settings["model_endpoints"][0]["connection"]["operation_settings"]["image_generation"]["api"] = "images"
        client, _ = self.mock_client()
        generation.request_generated_image_source(settings, "Draw a mountain")
        client.responses.create.assert_called_once()
        client.images.generate.assert_not_called()

    def test_non_successful_tools_and_refusals_never_produce_a_success(self):
        client, _ = self.mock_client()
        variants = [
            responses_image_response(status="incomplete"),
            responses_image_response(status="failed"),
            responses_image_response(output=[{"type": "image_generation_call", "status": "failed", "result": IMAGE_BASE64}]),
            responses_image_response(output=[{"type": "image_generation_call", "status": "in_progress", "result": IMAGE_BASE64}]),
            responses_image_response(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "private provider text"}]}]),
            responses_image_response(output=[{"type": "message", "content": [{"type": "output_text", "text": "I could draw it."}]}]),
            responses_image_response(output=[{"type": "image_generation_call", "status": "completed", "result": "not-base64"}]),
            responses_image_response(output=responses_image_response()["output"] + [{"type": "image_generation_call", "status": "failed"}]),
        ]
        for response in variants:
            client.responses.create.return_value = response
            with self.subTest(response=response), self.assertRaises(image_route.ImageGenerationError):
                generation.request_generated_image_source(shared_image_settings(), "Draw a mountain")
        client.images.generate.assert_not_called()

    def test_error_categories_and_logs_do_not_expose_provider_messages(self):
        cases = [
            (429, "rate_limit_exceeded", None, "private-prompt private-key", 429),
            (400, "content_policy_violation", "prompt", "private-prompt private-key", 400),
            (400, "invalid_request_error", "model", "private-prompt private-key", 503),
            (400, "BadRequest", None, "x-ms-oai-image-generation-deployment is required; private-key", 503),
            (400, "invalid_prompt", "prompt", "private-prompt private-key", 400),
            (404, "DeploymentNotFound", None, "private-prompt private-key", 503),
        ]
        for status, code, parameter, message, expected in cases:
            response = httpx.Response(status, request=httpx.Request("POST", "https://private.example/responses"))
            error_class = RateLimitError if status == 429 else BadRequestError
            exc = error_class(message, response=response, body={"code": code, "param": parameter, "message": message})
            payload, actual_status = generation.image_generation_error_response(exc)
            self.assertEqual(actual_status, expected)
            serialized = json.dumps([payload, generation.image_generation_error_log_context(exc)])
            self.assertNotIn("private-prompt", serialized)
            self.assertNotIn("private-key", serialized)
            self.assertNotIn("private.example", serialized)
            self.assertEqual(bool(payload.get("rate_limited")), status == 429)

    def test_generated_image_download_failure_is_not_an_invalid_prompt(self):
        for source in ("", "https:", "file:///private/image", "data:image/png;base64,not-base64"):
            with self.subTest(source=source), self.assertRaises(image_route.ImageGenerationError):
                generation.resolve_generated_image_bytes(source)
        failure = generation.requests.HTTPError("private image URL ?sig=private-key")
        with patch.object(generation.requests, "get", side_effect=failure):
            with self.assertRaises(image_route.ImageGenerationError) as caught:
                generation.resolve_generated_image_bytes("https://images.example/generated.png")
        payload, status = generation.image_generation_error_response(caught.exception)
        self.assertEqual(status, 502)
        self.assertNotIn("private-key", json.dumps(payload))

    def test_persistence_records_selected_deployment_proposal_and_thread_metadata(self):
        settings = shared_image_settings()
        proposal = generation.normalize_image_proposal({"visualId": "figure-1", "prompt": "A mountain", "title": "Mountain"})
        with patch.object(generation, "request_generated_image_source", return_value=IMAGE_SOURCE):
            result = generation.generate_chat_image_message(
                settings=settings, user_id="user-1", conversation_id="conversation-1",
                prompt=" A mountain ", user_info={"user_id": "user-1"},
                thread_id="thread-1", previous_thread_id="thread-0",
                proposal=proposal, source_assistant_message_id="assistant-1",
            )
        stored = self.messages.upsert_item.call_args.args[0]
        self.assertEqual(stored["model_deployment_name"], "selected-gpt")
        self.assertEqual(result["model_deployment_name"], "selected-gpt")
        self.assertEqual(stored["prompt"], "A mountain")
        self.assertEqual(stored["metadata"]["image_proposal"]["source_assistant_message_id"], "assistant-1")
        self.assertIn("approved_at", stored["metadata"]["image_proposal"])
        self.assertEqual(stored["metadata"]["thread_info"]["previous_thread_id"], "thread-0")
        self.assertEqual(stored["metadata"]["user_info"], {"user_id": "user-1"})

    def test_persistence_resolves_deployment_before_generation(self):
        settings = shared_image_settings()
        settings[connections.IMAGE_SELECTION_KEY] = None
        with patch.object(generation, "request_generated_image_source") as generate:
            with self.assertRaises(connections.AIConnectionError):
                generation.generate_chat_image_message(
                    settings=settings, user_id="user-1", conversation_id="conversation-1", prompt="A mountain"
                )
        generate.assert_not_called()
        self.messages.upsert_item.assert_not_called()

    def test_blob_and_chunk_persistence_keep_existing_metadata(self):
        upload = Mock(return_value={
            "content": "/api/image/new-image", "filename": "figure-1.png",
            "file_content_source": "blob", "blob_container": "images", "blob_path": "user-1/image",
            "mime_type": "image/png", "image_size": 70,
        })
        operations = types.ModuleType("functions_simplechat_operations")
        operations.upload_chat_image_bytes_for_user = upload
        self.stack.enter_context(patch.dict(sys.modules, {"functions_simplechat_operations": operations}))
        with patch.object(generation, "request_generated_image_source", return_value=IMAGE_SOURCE):
            result = generation.generate_chat_image_message(
                settings=shared_image_settings(), user_id="user-1", conversation_id="conversation-1",
                prompt="A mountain", proposal={"visualId": "figure-1"}, store_in_blob=True,
            )
        self.assertEqual(result["image_url"], "/api/image/new-image")
        self.assertEqual(upload.call_args.kwargs["image_bytes"], base64.b64decode(IMAGE_BASE64))
        self.assertEqual(upload.call_args.kwargs["file_name"], "figure-1.png")
        self.assertTrue(result["image_message"]["metadata"]["is_blob_backed"])
        self.assertEqual(result["image_message"]["metadata"]["original_size"], 70)
        self.messages.reset_mock()
        large_source = "data:image/png;base64," + "A" * 2_000_000
        with patch.object(generation, "request_generated_image_source", return_value=large_source):
            generation.generate_chat_image_message(
                settings=shared_image_settings(), user_id="user-1", conversation_id="conversation-1",
                prompt="A mountain", proposal={"visualId": "large-figure"},
            )
        documents = [call.args[0] for call in self.messages.upsert_item.call_args_list]
        self.assertGreater(len(documents), 1)
        self.assertTrue(documents[0]["metadata"]["is_chunked"])
        self.assertEqual(documents[0]["metadata"]["image_proposal"]["visualId"], "large-figure")
        self.assertEqual(documents[1]["role"], "image_chunk")
        self.assertEqual(documents[1]["parent_message_id"], documents[0]["id"])

    def test_all_whole_image_regeneration_uses_shared_request(self):
        for direct in (False, True):
            settings = shared_image_settings(direct=direct)
            if direct:
                settings["model_endpoints"][0]["models"][0]["modelName"] = "dall-e-3"
            with patch.object(generation, "request_generated_image_source", return_value=IMAGE_SOURCE) as generate:
                with patch.object(image_edit, "_finish_image_edit", return_value={"method": "regenerate"}) as finish:
                    result = image_edit.request_image_edit(settings, {}, "New mountain", quality="high")
            self.assertEqual(result["method"], "regenerate")
            generate.assert_called_once_with(settings, "New mountain", size="", quality="high", background="")
            self.assertEqual(finish.call_args.kwargs["deployment"], "selected-image" if direct else "selected-gpt")

    def test_shared_masked_edit_uses_operation_version_and_existing_edit_payload(self):
        settings = shared_image_settings(direct=True)
        settings["azure_openai_image_gen_api_version"] = "2020-01-01"
        self.assertEqual(image_edit.resolve_image_edit_capability(settings)["mode"], "masked")
        client, _ = self.mock_client()
        client.images.edit.return_value = {"data": [{"b64_json": IMAGE_BASE64}]}
        with patch.object(image_edit, "_finish_image_edit", return_value={"method": "edit"}):
            result = image_edit.request_image_edit(
                settings, {"file_name": "source.png", "bytes": b"source", "mime_type": "image/png"},
                "Change the sky", mask={"bytes": b"mask"}, quality="high",
            )
        self.assertEqual(result["method"], "edit")
        arguments = client.images.edit.call_args.kwargs
        self.assertEqual(arguments["model"], "selected-image")
        self.assertEqual(arguments["mask"], ("mask.png", b"mask", "image/png"))
        self.assertEqual(arguments["extra_body"], {"quality": "high", "input_fidelity": "high"})
        client.responses.create.assert_not_called()
        client.images.generate.assert_not_called()

    def test_editor_handles_cleared_selection_without_breaking_bootstrap(self):
        settings = shared_image_settings()
        settings[connections.IMAGE_SELECTION_KEY] = {}
        capability = image_edit.resolve_image_edit_capability(settings)
        self.assertFalse(capability["enabled"])
        self.assertTrue(capability["reason"])
        with self.assertRaises(connections.AIConnectionError):
            image_edit.request_image_edit(settings, {}, "New mountain")

    def test_admin_shared_reference_uses_stored_globals_and_ignores_payload_secrets(self):
        settings = shared_image_settings()
        settings["enable_image_generation"] = False
        before = copy.deepcopy(settings)
        namespace = self.admin_namespace(settings)
        _, constructor = self.mock_client()
        with self.app.app_context():
            response, status = namespace["run_admin_settings_connection_test"]({
                "test_type": "image", "selection": copy.deepcopy(settings[connections.IMAGE_SELECTION_KEY]),
                "direct": {"endpoint": "https://forged.example", "key": "forged-key"},
                "model_endpoints": [{"id": "team-one", "auth": {"api_key": "forged-key"}}],
            })
        self.assertEqual(status, 200)
        self.assertEqual(settings, before)
        self.assertEqual(constructor.call_args.kwargs["api_key"], "resolved-connection-key")
        self.assertNotIn("forged.example", constructor.call_args.kwargs["base_url"])
        self.assertEqual(set(response.get_json()), {"message"})
        namespace["resolve_admin_settings_secret_value"].assert_not_called()

    def test_admin_legacy_draft_keeps_redacted_secret_resolution_and_gateway_path(self):
        settings = shared_image_settings()
        namespace = self.admin_namespace(settings)
        client, constructor = self.mock_client()
        with self.app.app_context():
            _, status = namespace["run_admin_settings_connection_test"]({
                "test_type": "image", "enable_apim": True,
                "apim": {
                    "endpoint": "https://gateway.example/models/team", "deployment": "legacy-gateway-image",
                    "api_version": "2024-12-01-preview", "subscription_key": "redacted",
                },
            })
        self.assertEqual(status, 200)
        self.assertEqual(constructor.call_args.kwargs["api_key"], "unmasked-legacy-key")
        self.assertEqual(
            constructor.call_args.kwargs["base_url"],
            "https://gateway.example/models/team/openai/deployments/legacy-gateway-image/",
        )
        self.assertEqual(client.images.generate.call_args.kwargs["model"], "legacy-gateway-image")

    def test_admin_rejects_forged_and_cleared_references_without_legacy_fallback(self):
        settings = shared_image_settings()
        namespace = self.admin_namespace(settings)
        _, constructor = self.mock_client()
        for selection in (None, {}, {"endpoint_id": "private", "model_id": "stable-model", "provider": "aoai"}):
            with self.app.app_context():
                response, status = namespace["run_admin_settings_connection_test"]({
                    "test_type": "image", "selection": selection,
                    "direct": {"endpoint": "https://forged.example", "key": "forged-key"},
                })
            self.assertEqual(status, 503)
            self.assertIn("error_code", response.get_json())
        constructor.assert_not_called()

    def test_admin_secret_resolution_failure_is_safe(self):
        namespace = self.admin_namespace(shared_image_settings())
        namespace["resolve_admin_settings_secret_value"].side_effect = RuntimeError("private-key in Key Vault response")
        with self.app.app_context():
            response, status = namespace["run_admin_settings_connection_test"]({
                "test_type": "image", "direct": {"key": "redacted"},
            })
        self.assertEqual(status, 502)
        self.assertNotIn("private-key", json.dumps(response.get_json()))
        self.assertNotIn("private-key", str(self.logs.call_args_list))

    def test_edit_errors_preserve_the_shared_editor_exception_contract(self):
        client, _ = self.mock_client()
        response = httpx.Response(429, request=httpx.Request("POST", "https://images.example/edits"))
        client.images.edit.side_effect = RateLimitError(
            "private-key private-prompt", response=response, body={"code": "rate_limit_exceeded"}
        )
        with self.assertRaises(image_edit.ImageEditError) as caught:
            image_edit.request_image_edit(
                shared_image_settings(direct=True),
                {"file_name": "source.png", "bytes": b"source", "mime_type": "image/png"},
                "Change the sky",
            )
        payload, status = generation.image_generation_error_response(caught.exception)
        self.assertEqual(status, 429)
        self.assertTrue(payload["rate_limited"])
        self.assertNotIn("private-key", str(self.logs.call_args_list))
        self.assertNotIn("private-prompt", str(caught.exception))

    def test_proposal_configuration_failure_is_not_relabelled_as_bad_prompt(self):
        settings = shared_image_settings()
        errors = [
            (connections.AIConnectionError("Select a compatible image model.", "model_configuration_unavailable"), 503),
            (ValueError("private invalid prompt"), 400),
            (image_route.ImageGenerationError("Please try again later.", "image_rate_limited", 429), 429),
        ]
        namespace = {
            "request": request, "jsonify": jsonify, "logging": logging, "datetime": datetime,
            "get_settings": lambda: settings, "image_generation_is_enabled": generation.image_generation_is_enabled,
            "get_current_user_id": lambda: "user-1", "get_current_user_info": lambda: {},
            "_authorize_personal_conversation_access": Mock(return_value={"id": "conversation-1"}),
            "normalize_image_proposal": generation.normalize_image_proposal,
            "AIConnectionError": connections.AIConnectionError,
            "CosmosResourceNotFoundError": type("NotFoundForTest", (Exception,), {}),
            "image_generation_error_response": generation.image_generation_error_response,
            "image_generation_error_log_context": generation.image_generation_error_log_context,
            "log_event": self.logs,
        }
        load_route_functions("route_backend_chats.py", ("generate_image_from_proposal",), namespace)
        for error, expected in errors:
            namespace["generate_chat_image_message"] = Mock(side_effect=error)
            with self.app.test_request_context(json={
                "conversation_id": "conversation-1", "proposal": {"prompt": "A mountain"},
            }):
                response, status = namespace["generate_image_from_proposal"]()
            self.assertEqual(status, expected)
            self.assertNotIn("private invalid prompt", json.dumps(response.get_json()))
        self.assertNotIn("private invalid prompt", str(self.logs.call_args_list))


if __name__ == "__main__":
    unittest.main()
