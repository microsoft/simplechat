# test_image_chat_route_integration.py
"""
Functional test for the actual /api/chat Image-mode request path.
Version: 0.261.102
Implemented in: 0.261.102

Registers the complete production chat handler with its original Flask route decorator.
Local normalization, metadata, threading, title, image binding, SDK, and persistence logic
execute unchanged. Authentication, storage, telemetry, and inactive optional feature
services are isolated; all chat-model factories fail if called. No Cosmos or Azure
service is initialized, and image HTTP requests use the real SDK with MockTransport.
"""

import copy
import json
import logging
import math
import random
import re
import sys
import time
import traceback
import unittest
import uuid
from datetime import datetime
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import httpx
import werkzeug
from flask import Blueprint, g, jsonify, request, session

TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_ROOT))

# The shared fixture installs config/secret/credential seams before runtime imports.
from test_ai_connection_image_runtime import (  # noqa: E402
    IMAGE_BASE64,
    IMAGE_SOURCE,
    ImageRuntimeTestCase,
    connections,
    generation,
    image_route,
    load_route_functions,
    responses_image_response,
    shared_image_settings,
)
from functions_image_messages import build_image_message_documents  # noqa: E402
from functions_prompt_metadata import build_prompt_selection_metadata  # noqa: E402


class MemoryContainer:
    def __init__(self):
        self.documents = {}
        self.upserts = []

    def upsert_item(self, document):
        saved = copy.deepcopy(document)
        self.documents[saved["id"]] = saved
        self.upserts.append(saved)
        return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        document = self.documents[item]
        if document.get("conversation_id") != partition_key:
            raise PermissionError("Wrong test partition")
        return copy.deepcopy(document)

    def query_items(self, **kwargs):
        return []


def authenticated_test_user(function):
    """Authentication seam; route policy tests cover the production decorators."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if session.get("user", {}).get("oid") != "user-1":
            return jsonify({"error": "User not authenticated"}), 401
        return function(*args, **kwargs)
    return wrapped


class ImageChatRouteIntegrationTests(ImageRuntimeTestCase):
    def setUp(self):
        super().setUp()
        self.settings = shared_image_settings()
        self.settings["model_endpoints"][0]["models"][0]["enabled_capabilities"] = ["image_generation"]
        self.settings["default_model_selection"] = {}
        self.settings["gpt_model"] = {"selected": []}
        self.settings["azure_openai_gpt_endpoint"] = ""
        self.settings["azure_openai_gpt_key"] = ""
        self.settings["azure_apim_gpt_endpoint"] = ""
        self.settings["azure_apim_gpt_deployment"] = ""
        self.settings["azure_apim_gpt_subscription_key"] = ""
        self.requests = []
        self.message_store = MemoryContainer()
        self.conversation_store = MemoryContainer()
        self.conversation = {
            "id": "conversation-1",
            "user_id": "user-1",
            "title": "New Conversation",
            "last_grounded_document_refs": [{
                "document_id": "previous-document",
                "scope": "personal",
                "scope_id": "user-1",
            }],
        }
        self.forbidden_chat_calls = {
            name: Mock(side_effect=AssertionError(f"Image mode called unrelated chat helper {name}"))
            for name in (
                "AzureOpenAI", "OpenAI", "DefaultAzureCredential", "get_bearer_token_provider",
                "resolve_streaming_multi_endpoint_gpt_config", "build_model_endpoint_context",
                "build_model_endpoint_sync_chat_client", "build_semantic_kernel_chat_service_for_model",
                "initialize_semantic_kernel", "assess_history_only_answerability",
                "build_conversation_history_segments", "_resolve_reauthorized_continuity_decision",
            )
        }
        client_class = generation._ImageOpenAIClient

        def handle_image_request(http_request):
            self.requests.append(http_request)
            result = (
                responses_image_response()
                if http_request.url.path.endswith("/responses")
                else {"created": 1, "data": [{"b64_json": IMAGE_BASE64}]}
            )
            return httpx.Response(200, json=result)

        def build_image_client(**kwargs):
            return client_class(
                **kwargs,
                http_client=httpx.Client(transport=httpx.MockTransport(handle_image_request), trust_env=False),
            )

        self.stack.enter_context(patch.object(generation, "_ImageOpenAIClient", side_effect=build_image_client))
        self.namespace = self.build_chat_namespace()
        self.app.register_blueprint(self.namespace["bp"])
        # Match the repository's scoped compatibility shim for older developer Flask installs.
        if not hasattr(werkzeug, "__version__"):
            self.stack.enter_context(patch.object(werkzeug, "__version__", version("werkzeug"), create=True))

        @self.app.before_request
        def authenticate_fixture_user():
            session["user"] = {"oid": "user-1", "roles": ["User"]}

        self.client = self.app.test_client()

    def authorize_conversation(self, user_id, conversation_id):
        self.assertEqual(user_id, "user-1")
        self.assertEqual(conversation_id, "conversation-1")
        return self.conversation

    def build_chat_namespace(self):
        namespace = {
            **self.forbidden_chat_calls,
            "bp": Blueprint("image_chat_integration", __name__),
            "swagger_route": lambda **kwargs: lambda function: function,
            "get_auth_security": lambda: [],
            "login_required": authenticated_test_user,
            "user_required": authenticated_test_user,
            "get_settings": lambda: self.settings,
            "get_current_user_id": lambda: session.get("user", {}).get("oid"),
            "get_current_user_info": lambda: {
                "userId": "user-1", "displayName": "Image user", "email": "user@example.test",
            },
            "g": g, "request": request, "session": session, "jsonify": jsonify,
            "time": time, "random": random, "datetime": datetime, "math": math,
            "json": json, "logging": logging, "traceback": traceback, "re": re,
            "Any": Any, "Dict": Dict, "List": List,
            "FoundryAgentUserAuthenticationRequired": type("TestFoundryAuthenticationRequired", (Exception,), {}),
            "CLIENTS": {},
            "DEFAULT_CONVERSATION_TITLE": "New Conversation",
            "DOCUMENT_ACTION_TYPE_NONE": "none",
            "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
            "DOCUMENT_ACTION_TYPE_COMPARISON": "comparison",
            "ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH": "search",
            "ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE": "analyze",
            "ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE": "compare",
            "_get_authorized_chat_scope_context": Mock(return_value={
                "active_group_ids": [], "active_group_id": None,
                "active_public_workspace_ids": [], "active_public_workspace_id": None,
            }),
            "_authorize_personal_conversation_access": Mock(side_effect=self.authorize_conversation),
            "_resolve_or_create_authorized_personal_conversation": Mock(
                side_effect=lambda user_id, conversation_id: (
                    self.authorize_conversation(user_id, conversation_id), "conversation-1",
                )
            ),
            "_set_authorized_chat_request_context": Mock(),
            "_resolve_chat_upload_workspace_context": Mock(return_value={
                "effective_document_scope": None, "effective_selected_document_ids": [],
                "auto_linked_chat_upload_document_ids": [], "task_resolution": {},
            }),
            "_read_recent_assistant_messages": Mock(return_value=[]),
            "cosmos_messages_container": self.message_store,
            "cosmos_conversations_container": self.conversation_store,
            "ThoughtTracker": Mock(return_value=Mock(enabled=False)),
            "get_plugin_logger": Mock(return_value=Mock()),
            "invalidate_conversation_cache_for_item": Mock(),
            "log_chat_activity": Mock(),
            "debug_print": Mock(),
            "log_event": self.logs,
            "is_mixed_source_chat_search_enabled": Mock(return_value=False),
            "is_mixed_source_manifest_enabled": Mock(return_value=False),
            "is_source_review_enabled_for_user": Mock(return_value=False),
            "is_url_access_enabled_for_user": Mock(return_value=False),
            "extract_urls_from_text": Mock(return_value=[]),
            "normalize_mixed_source_correlation_id": lambda: uuid.uuid4().hex,
            "get_tabular_generated_output_format": Mock(return_value=""),
            "build_generated_file_output_guidance": Mock(return_value=""),
            "build_prompt_selection_metadata": build_prompt_selection_metadata,
            "build_model_endpoint_identity_headers": generation.build_model_endpoint_identity_headers,
            "resolve_selected_image_deployment_name": image_route.resolve_selected_image_deployment_name,
            "request_generated_image_source": generation.request_generated_image_source,
            "resolve_generated_image_bytes": generation.resolve_generated_image_bytes,
            "build_image_message_documents": build_image_message_documents,
            "ImageGenerationError": image_route.ImageGenerationError,
            "AIConnectionError": connections.AIConnectionError,
            "image_generation_error_log_context": generation.image_generation_error_log_context,
            "image_generation_error_response": generation.image_generation_error_response,
            "build_json_error_response": lambda message="Chat request failed", status_code=500, **extra: (
                jsonify({"error": message, **extra}), status_code,
            ),
        }
        load_route_functions(
            "functions_simplechat_operations.py", ("derive_conversation_title_from_message",), namespace,
        )
        load_route_functions("route_backend_chats.py", (
            "_metadata_item_count", "_safe_metadata_int", "_normalize_capability_action",
            "_normalize_conversation_task_document_ids", "_normalize_chat_document_context_contract",
            "_maybe_resolve_chat_source_manifest", "_source_review_metadata_used", "_deep_research_query_count",
            "_build_capability_usage_metadata", "_conversation_title_is_default", "_set_initial_conversation_title",
            "_resolve_pending_generated_file_format", "_resolve_generated_file_guidance_format",
            "_resolve_canonical_chat_agent", "_get_chat_agent_selection_name", "_has_chat_agent_selection",
            "_is_explicit_external_retrieval_requested", "_should_auto_merge_chat_upload_workspace_context",
            "_build_agent_selection_metadata", "_normalize_prior_grounded_document_refs",
            "_load_user_message_response_context", "_initialize_assistant_response_tracking",
            "_get_user_message_image_context", "_resolve_generated_image_bytes",
            "build_web_search_query_text", "chat_api",
        ), namespace, strip_decorators=False)
        return namespace

    def post_image(self, **overrides):
        return self.client.post("/api/chat", json={
            "conversation_id": "conversation-1",
            "message": "A mountain at sunrise",
            "image_generation": True,
            "hybrid_search": False,
            **overrides,
        })

    def assert_image_success(self, response, *, direct=False):
        self.assertEqual(response.status_code, 200, f"{response.get_json()}; {self.logs.call_args_list}")
        payload = response.get_json()
        deployment = "selected-image" if direct else "selected-gpt"
        self.assertEqual(payload["image_url"], IMAGE_SOURCE)
        self.assertEqual(payload["model_deployment_name"], deployment)
        self.assertEqual(payload["conversation_id"], "conversation-1")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].url.host, "team-one.openai.azure.com")
        self.assertEqual(
            self.requests[0].url.path,
            "/openai/deployments/selected-image/images/generations" if direct else "/openai/v1/responses",
        )
        self.assertEqual(dict(self.requests[0].url.params), {"api-version": "2025-04-01-preview"} if direct else {})
        self.assertEqual(json.loads(self.requests[0].content)["model"], deployment)
        image = self.message_store.documents[payload["message_id"]]
        user = self.message_store.documents[payload["user_message_id"]]
        self.assertEqual(image["role"], "image")
        self.assertEqual(image["model_deployment_name"], deployment)
        self.assertEqual(image["metadata"]["thread_info"]["thread_id"], user["metadata"]["thread_info"]["thread_id"])
        self.assertEqual(image["metadata"]["user_info"], user["metadata"]["user_info"])
        self.assertEqual(self.conversation_store.documents["conversation-1"]["title"], "A mountain at sunrise")
        self.namespace["_resolve_or_create_authorized_personal_conversation"].assert_called_once_with("user-1", "conversation-1")
        for forbidden in self.forbidden_chat_calls.values():
            forbidden.assert_not_called()

    def test_actual_chat_image_mode_works_without_any_usable_chat_default(self):
        self.assertFalse(self.settings["enable_multi_model_endpoints"])
        self.assertEqual(self.settings["gpt_model"]["selected"], [])
        self.assert_image_success(self.post_image())

    def test_actual_chat_image_mode_accepts_a_new_direct_image_only_connection(self):
        endpoint = self.settings["model_endpoints"][0]
        model = shared_image_settings(direct=True)["model_endpoints"][0]["models"][0]
        model["enabled_capabilities"] = ["image_generation"]
        endpoint["models"] = [model]
        endpoint["connection"].pop("operation_settings")
        self.assert_image_success(self.post_image(), direct=True)

    def test_actual_chat_image_mode_ignores_broken_unrelated_apim_chat_configuration(self):
        self.settings["enable_gpt_apim"] = True
        self.assert_image_success(self.post_image(image_generation="true"))

    def test_actual_chat_image_selection_remains_global_and_server_resolved(self):
        other = copy.deepcopy(self.settings["model_endpoints"][0])
        other["id"] = "other-image-connection"
        other["connection"]["endpoint"] = "https://other-image.openai.azure.com"
        self.settings["model_endpoints"].append(other)
        before = copy.deepcopy(self.settings)
        self.assert_image_success(self.post_image(
            model_endpoint_id="unavailable-chat-connection",
            model_id="unavailable-chat-model",
            model_deployment="unavailable-chat-deployment",
            image_generation_model_selection={
                "endpoint_id": "other-image-connection", "model_id": "stable-model", "provider": "aoai",
            },
        ))
        self.assertEqual(self.settings, before)

    def test_actual_chat_image_mode_does_not_revive_legacy_after_shared_default_clear(self):
        shared_selection = copy.deepcopy(self.settings[connections.IMAGE_SELECTION_KEY])
        self.settings[connections.IMAGE_SELECTION_KEY] = {}
        response = self.post_image(image_generation_model_selection=shared_selection)
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertEqual(response.get_json()["error_code"], "model_configuration_unavailable")
        self.assertEqual(self.requests, [])
        self.assertFalse(any(item["role"] == "image" for item in self.message_store.documents.values()))
        self.secret_helper.assert_not_called()
        for forbidden in self.forbidden_chat_calls.values():
            forbidden.assert_not_called()


if __name__ == "__main__":
    unittest.main()
