# test_ai_connection_embedding_discovery.py
"""
Functional tests for embedding discovery and chat-test capability isolation.
Version: 0.261.108
Implemented in: 0.261.106

Exercise the actual global/personal/group Flask discovery and chat-test handlers
with synthetic ARM/Foundry deployments. No Azure or inference service is called.
"""

import copy
import logging
import re
import sys
import unittest
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

from flask import Blueprint, Flask, jsonify, request
from werkzeug.test import Client

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

import functions_ai_connections as connections
from functions_model_capabilities import get_model_catalog_capabilities
from functions_model_endpoint_diagnostics import SanitizedModelEndpointError
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model
from functions_model_endpoint_validation import ModelEndpointValidationError, validate_custom_model_endpoint
from admin_settings_secret_utils import is_admin_settings_redacted_secret
from test_ai_connection_embedding_defaults_api import load_functions


def deployment(name, model_name, *, state="Succeeded", version=None):
    return SimpleNamespace(
        name=name,
        properties=SimpleNamespace(
            provisioning_state=state,
            model=SimpleNamespace(name=model_name, version=version),
        ),
    )


class EmbeddingDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.admin = True
        self.logged_in = True
        self.group_authorized = True
        self.flags = {
            "allow_user_custom_endpoints": True,
            "allow_group_custom_endpoints": True,
            "enable_group_workspaces": True,
        }
        self.arm_calls = []
        self.foundry_calls = []
        self.inference_calls = []
        self.resolved_scopes = []
        self.group_roles = []
        self.discovery_error = None
        self.inference_error = None
        self.resolution_error = None
        self.stored_endpoint = None
        self.deployments = [
            deployment("chat", "gpt-4o"),
            deployment("reasoning", "o3"),
            deployment("image", "gpt-image-1"),
            deployment("vectors", "text-embedding-3-small"),
            deployment("ada-v1", "text-embedding-ada-002", version="1"),
            deployment("native-only", "embed-v-4-0"),
            deployment("disabled-vectors", "text-embedding-3-small", state="Failed"),
            deployment("speech", "whisper"),
        ]
        self.foundry_deployments = [
            {"name": "vectors", "modelName": "text-embedding-3-small"},
            {"name": "ada-v1", "model": {"name": "text-embedding-ada-002", "version": "1"}},
            {"name": "native-only", "modelName": "embed-v-4-0"},
            {"name": "chat", "modelName": "gpt-4o"},
        ]
        self.payload = {
            "provider": "aoai",
            "connection": {
                "endpoint": "https://synthetic.openai.azure.com",
                "api_version": "2024-05-01-preview",
            },
            "auth": {"type": "managed_identity"},
            "management": {"subscription_id": "synthetic-subscription", "resource_group": "synthetic-group"},
            "model": {"deploymentName": "chat", "modelName": "gpt-4o"},
        }

        def guard(allowed):
            def decorate(function):
                @wraps(function)
                def wrapped(*args, **kwargs):
                    if not allowed():
                        return jsonify({"error": "Access denied"}), 403
                    return function(*args, **kwargs)
                return wrapped
            return decorate

        def resolve_payload(payload, scope, *, for_chat_test=False):
            self.resolved_scopes.append(scope)
            if self.resolution_error:
                raise self.resolution_error
            if self.stored_endpoint is not None:
                return {**copy.deepcopy(self.stored_endpoint), "model": copy.deepcopy(payload.get("model", {}))}
            return copy.deepcopy(payload)

        def build_arm(subscription_id, _auth):
            self.arm_calls.append(subscription_id)
            if self.discovery_error:
                raise self.discovery_error
            return SimpleNamespace(deployments=SimpleNamespace(
                list=lambda **_kwargs: list(self.deployments)
            ))

        def fetch_foundry(endpoint, api_version, _auth, *, project_name):
            self.foundry_calls.append((endpoint, api_version, project_name))
            if self.discovery_error:
                raise self.discovery_error
            return copy.deepcopy(self.foundry_deployments)

        def build_inference(*args, **kwargs):
            self.inference_calls.append((args, kwargs))
            if self.inference_error:
                raise self.inference_error
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(choices=[{"synthetic": "chat response"}])
            )))

        def assert_group_role(_user_id, _group_id, allowed_roles=None):
            self.group_roles.append(allowed_roles)
            if not self.group_authorized:
                raise PermissionError("synthetic-private-membership-error")

        bp = Blueprint("embedding_discovery_test", __name__)
        namespace = {
            "bp": bp,
            "logging": logging,
            "re": re,
            "jsonify": jsonify,
            "request": request,
            "log_event": lambda *_args, **_kwargs: None,
            "describe_model_capabilities": connections.describe_model_capabilities,
            "supports_model_capability": connections.supports_model_capability,
            "get_model_catalog_capabilities": get_model_catalog_capabilities,
            "AIConnectionError": connections.AIConnectionError,
            "ModelEndpointValidationError": ModelEndpointValidationError,
            "SanitizedModelEndpointError": SanitizedModelEndpointError,
            "get_model_endpoint_api_type": get_model_endpoint_api_type,
            "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
            "validate_custom_model_endpoint": validate_custom_model_endpoint,
            "is_admin_settings_redacted_secret": is_admin_settings_redacted_secret,
            "get_settings": lambda: dict(self.flags),
            "get_auth_security": lambda: [],
            "swagger_route": lambda **_kwargs: lambda function: function,
            "login_required": guard(lambda: self.logged_in),
            "user_required": lambda function: function,
            "admin_required": guard(lambda: self.admin),
            "enabled_required": lambda key: guard(lambda: self.flags[key]),
            "resolve_request_endpoint_payload": resolve_payload,
            "build_cognitive_services_client": build_arm,
            "fetch_foundry_project_deployments": fetch_foundry,
            "infer_model_endpoint_protocol": lambda *_args: "azure_openai",
            "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": "azure_openai",
            "build_inference_client": build_inference,
            "get_current_user_id": lambda: "authorized-user",
            "require_active_group": lambda _user_id: "authorized-group",
            "assert_group_role": assert_group_role,
        }
        load_functions(
            APP_ROOT / "route_backend_models.py",
            {
                "log_models_debug", "log_models_exception", "build_safe_error_response",
                "build_group_access_error_response", "extract_provisioning_state", "is_deployment_enabled",
                "handle_fetch_model_list", "handle_test_model_connection", "test_model_inference_connection",
                "fetch_model_list", "fetch_model_list_user", "fetch_model_list_group",
                "test_model_connection", "test_model_connection_user", "test_model_connection_group",
            },
            namespace,
        )
        self.namespace = namespace
        app = Flask(__name__)
        app.register_blueprint(bp)
        self.client = Client(app, app.response_class)

    def use_actual_payload_resolver(self, credential_reads):
        self.namespace.update({
            "resolve_endpoint_by_id": lambda _user_id, _scope, _endpoint_id: copy.deepcopy(self.stored_endpoint),
            "SecretReturnType": SimpleNamespace(VALUE="value"),
        })

        def hydrate(endpoint, endpoint_id, **_kwargs):
            credential_reads.append(endpoint_id)
            return copy.deepcopy(endpoint)

        self.namespace["keyvault_model_endpoint_get_helper"] = hydrate
        load_functions(
            APP_ROOT / "functions_settings.py",
            {"merge_model_endpoint_auth", "merge_model_endpoint_payload"},
            self.namespace,
        )
        load_functions(
            APP_ROOT / "route_backend_models.py",
            {"resolve_request_endpoint_payload", "resolve_endpoint_scope_value"},
            self.namespace,
        )

    def test_azure_discovery_includes_embedding_models_and_preserves_other_capabilities(self):
        response = self.client.post("/api/models/fetch", json=self.payload)
        self.assertEqual(200, response.status_code)
        models = {model["deploymentName"]: model for model in response.json["models"]}
        self.assertEqual({"chat", "reasoning", "image", "vectors", "ada-v1", "native-only"}, set(models))
        vector_status = models["vectors"]["capability_status"]
        self.assertTrue(vector_status["embeddings"]["available"])
        self.assertFalse(vector_status["chat"]["available"])
        self.assertFalse(vector_status["image_generation"]["available"])
        self.assertTrue(models["chat"]["capability_status"]["chat"]["available"])
        self.assertTrue(models["image"]["capability_status"]["image_generation"]["available"])
        self.assertFalse(models["native-only"]["capability_status"]["embeddings"]["available"])
        self.assertFalse(models["native-only"]["capability_status"]["chat"]["available"])
        self.assertIn("gateway", models["native-only"]["capability_status"]["embeddings"]["reason"].lower())
        self.assertEqual("1", models["ada-v1"]["modelVersion"])
        self.assertNotIn("synthetic-subscription", response.get_data(as_text=True))
        self.assertEqual([], self.inference_calls)

    def test_discovery_connection_test_counts_enabled_embedding_deployments(self):
        response = self.client.post("/api/models/test-connection", json=self.payload)
        self.assertEqual(200, response.status_code)
        self.assertEqual(6, response.json["count"])
        self.assertEqual([], self.inference_calls)

    def test_foundry_results_use_the_same_capability_metadata_and_model_version(self):
        for provider in ("aifoundry", "new_foundry"):
            with self.subTest(provider=provider):
                payload = {**self.payload, "provider": provider}
                response = self.client.post("/api/models/fetch", json=payload)
                self.assertEqual(200, response.status_code)
                models = {model["deploymentName"]: model for model in response.json["models"]}
                self.assertTrue(models["vectors"]["capability_status"]["embeddings"]["available"])
                self.assertFalse(models["vectors"]["capability_status"]["chat"]["available"])
                self.assertFalse(models["native-only"]["capability_status"]["embeddings"]["available"])
                self.assertFalse(models["native-only"]["capability_status"]["chat"]["available"])
                self.assertEqual("1", models["ada-v1"]["modelVersion"])
        self.assertEqual([], self.arm_calls)
        self.assertEqual([], self.inference_calls)

    def test_custom_connections_are_manual_and_cannot_pass_azure_discovery(self):
        payload = {**self.payload, "provider": "openai_compatible", "auth": {"type": "api_key"}}
        for path in ("/api/models/fetch", "/api/models/test-connection"):
            with self.subTest(path=path):
                response = self.client.post(path, json=payload)
                self.assertEqual(400, response.status_code)
                self.assertEqual("model_discovery_unsupported", response.json["code"])
                self.assertIn("manually configured", response.json["error"])
        self.assertEqual([], self.arm_calls)
        self.assertEqual([], self.foundry_calls)
        self.assertEqual([], self.inference_calls)

    def test_embedding_or_image_models_do_not_pass_the_chat_test(self):
        for model in (
            {"deploymentName": "vector-alias", "modelName": "text-embedding-3-small"},
            {"deploymentName": "vector-alias", "modelName": "embed-v-4-0"},
            {"deploymentName": "image-alias", "modelName": "gpt-image-1"},
            {"deploymentName": "manual", "supportsEmbeddings": True, "enabled_capabilities": ["embeddings"]},
        ):
            with self.subTest(model=model):
                response = self.client.post("/api/models/test-model", json={**self.payload, "model": model})
                self.assertEqual(400, response.status_code)
                self.assertEqual("model_capability_unavailable", response.json["code"])
        self.assertEqual([], self.inference_calls)

    def test_custom_provider_cannot_be_mislabeled_as_a_chat_model(self):
        for path in ("/api/models/test-model", "/api/user/models/test-model", "/api/group/models/test-model"):
            with self.subTest(path=path):
                response = self.client.post(path, json={
                    **self.payload, "provider": "openai_compatible",
                    "model": {"deploymentName": "gpt-4o", "supportsChat": True},
                })
                self.assertEqual(400, response.status_code)
                self.assertEqual("model_capability_unavailable", response.json["code"])
                self.assertIn("embeddings only", response.json["error"])
        self.assertEqual([], self.inference_calls)

    def test_saved_custom_chat_probes_are_rejected_before_hydrating_credentials(self):
        credential_reads = []
        self.use_actual_payload_resolver(credential_reads)
        self.stored_endpoint = {
            **self.payload, "id": "saved-custom", "provider": "openai_compatible",
            "models": [{
                "id": "chat", "deploymentName": "chat", "modelName": "gpt-4o",
                "supportsChat": True, "enabled_capabilities": ["chat"],
            }],
        }
        for override in ({}, {"provider": "aoai"}, {"provider": " OPENAI_COMPATIBLE "}):
            with self.subTest(override=override):
                response = self.client.post("/api/models/test-model", json={
                    "endpoint_id": "saved-custom", "model": {"id": "chat", "deploymentName": "chat"},
                    **override,
                })
                self.assertEqual(400, response.status_code)
                self.assertEqual("model_capability_unavailable", response.json["code"])
                self.assertIn("embeddings only", response.json["error"])
        self.assertEqual([], credential_reads)
        self.assertEqual([], self.inference_calls)

    def test_custom_draft_cannot_reuse_a_saved_azure_connection_for_chat(self):
        credential_reads = []
        self.use_actual_payload_resolver(credential_reads)
        self.stored_endpoint = {**self.payload, "id": "saved-azure"}
        response = self.client.post("/api/models/test-model", json={
            "endpoint_id": "saved-azure", "provider": "openai_compatible",
            "model": self.payload["model"],
        })
        self.assertEqual(400, response.status_code)
        self.assertEqual("model_capability_unavailable", response.json["code"])
        self.assertEqual([], credential_reads)
        self.assertEqual([], self.inference_calls)
        response = self.client.post("/api/models/test-model", json={
            "endpoint_id": "saved-azure", "model": self.payload["model"],
        })
        self.assertEqual(200, response.status_code)
        self.assertEqual(["saved-azure"], credential_reads)
        self.assertEqual(1, len(self.inference_calls))

    def test_chat_model_selection_parse_errors_are_coded(self):
        for model in ("invalid", [], {}, {"deploymentName": False}, {"deploymentName": ["chat"]}):
            with self.subTest(model=model):
                response = self.client.post("/api/models/test-model", json={**self.payload, "model": model})
                self.assertEqual(400, response.status_code)
                self.assertEqual("invalid_model_selection", response.json["code"])
                self.assertTrue(response.json["error"])
        self.assertEqual([], self.inference_calls)

    def test_persisted_embedding_metadata_cannot_be_overridden_by_a_chat_test_payload(self):
        self.stored_endpoint = {
            **self.payload,
            "models": [{
                "id": "stored-vector", "deploymentName": "generic-alias",
                "modelName": "text-embedding-3-small", "enabled_capabilities": ["embeddings"],
            }],
        }
        forged_model = {
            "id": "stored-vector", "deploymentName": "generic-alias",
            "modelName": "gpt-4o", "supportsChat": True,
        }
        for path in ("/api/models/test-model", "/api/user/models/test-model", "/api/group/models/test-model"):
            with self.subTest(path=path):
                response = self.client.post(path, json={"endpoint_id": "saved", "model": forged_model})
                self.assertEqual(400, response.status_code)
                self.assertEqual("model_capability_unavailable", response.json["code"])
        self.assertEqual([], self.inference_calls)

    def test_unrelated_manual_chat_aliases_remain_supported(self):
        response = self.client.post("/api/models/test-model", json={
            **self.payload, "model": {"deploymentName": "existing-manual-chat"},
        })
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json["success"])
        self.assertEqual(1, len(self.inference_calls))

    def test_discovery_and_chat_failures_do_not_return_provider_errors(self):
        self.discovery_error = RuntimeError("https://private-provider?token=synthetic-secret")
        response = self.client.post("/api/models/fetch", json=self.payload)
        self.assertEqual(400, response.status_code)
        self.assertNotIn("synthetic-secret", response.get_data(as_text=True))
        self.inference_error = RuntimeError("api-key=synthetic-secret")
        response = self.client.post("/api/models/test-model", json=self.payload)
        self.assertEqual(400, response.status_code)
        self.assertNotIn("synthetic-secret", response.get_data(as_text=True))

    def test_unavailable_stored_settings_are_reported_safely(self):
        self.resolution_error = RuntimeError("synthetic-private-settings-error")
        for path in ("/api/models/fetch", "/api/models/test-model", "/api/models/test-connection"):
            with self.subTest(path=path):
                response = self.client.post(path, json=self.payload)
                self.assertEqual(400, response.status_code)
                self.assertNotIn("synthetic-private", response.get_data(as_text=True))
        self.assertEqual([], self.arm_calls)
        self.assertEqual([], self.inference_calls)

    def test_admin_scope_and_workspace_gates_are_unchanged(self):
        self.admin = False
        for path in ("/api/models/fetch", "/api/models/test-model", "/api/models/test-connection"):
            self.assertEqual(403, self.client.post(path, json=self.payload).status_code)
        self.flags["allow_user_custom_endpoints"] = False
        self.assertEqual(403, self.client.post("/api/user/models/fetch", json=self.payload).status_code)
        self.assertEqual(403, self.client.post("/api/user/models/test-model", json=self.payload).status_code)
        self.flags["enable_group_workspaces"] = False
        self.assertEqual(403, self.client.post("/api/group/models/fetch", json=self.payload).status_code)
        self.assertEqual([], self.resolved_scopes)
        self.assertEqual([], self.arm_calls)
        self.assertEqual([], self.inference_calls)

    def test_group_membership_is_checked_before_discovery_or_inference(self):
        self.group_authorized = False
        for path in ("/api/group/models/fetch", "/api/group/models/test-model"):
            response = self.client.post(path, json=self.payload)
            self.assertEqual(403, response.status_code)
            self.assertNotIn("synthetic-private", response.get_data(as_text=True))
        self.assertIn(("Owner", "Admin"), self.group_roles)
        self.assertEqual([], self.resolved_scopes)
        self.assertEqual([], self.arm_calls)
        self.assertEqual([], self.inference_calls)

    def test_non_object_requests_are_rejected_before_any_provider_call(self):
        for path in ("/api/models/fetch", "/api/models/test-model", "/api/models/test-connection"):
            with self.subTest(path=path):
                self.assertEqual(400, self.client.post(path, json=["invalid"]).status_code)
        self.assertEqual([], self.arm_calls)
        self.assertEqual([], self.foundry_calls)
        self.assertEqual([], self.inference_calls)


if __name__ == "__main__":
    unittest.main()
