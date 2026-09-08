# test_ai_connection_defaults_api.py
"""
Functional tests for capability-specific model-default API behavior.
Version: 0.261.105
Implemented in: 0.261.105

Mount the actual route functions with isolated storage and authentication seams;
exercise HTTP payloads without importing the application's Azure clients.
"""

import ast
import copy
import sys
import unittest
from functools import wraps
from pathlib import Path

from flask import Blueprint, Flask, jsonify, request
from werkzeug.test import Client

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

import functions_ai_connections as connections


ROUTE_SOURCE = APP_ROOT / "route_backend_v2.py"
ROUTE_TREE = ast.parse(ROUTE_SOURCE.read_text(encoding="utf-8"))
ROUTE_NAMES = {
    "_load_global_model_endpoints",
    "_capability_model_payload",
    "v2_admin_get_capability_model",
    "v2_admin_set_capability_model",
}
BASE = "/api/v2/admin/capability-models"


def endpoint(endpoint_id, name):
    return {
        "id": endpoint_id,
        "name": name,
        "provider": "aoai",
        "enabled": True,
        "connection": {"endpoint": "https://private-resource.example.test"},
        "auth": {"type": "api_key", "api_key": "synthetic-private-value"},
        "models": [
            {
                "id": "text", "deploymentName": "chat-model", "modelName": "gpt-4o",
                "enabled": True, "enabled_capabilities": ["chat"],
            },
            {
                "id": "image", "deploymentName": "same-image-name", "modelName": "gpt-image-1",
                "enabled": True, "enabled_capabilities": ["image_generation"],
            },
        ],
    }


class CapabilityDefaultApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "enable_multi_model_endpoints": True,
            "enable_image_generation": True,
            "model_endpoints": [endpoint("one", "First"), endpoint("two", "Second")],
            "default_model_selection": {"endpoint_id": "one", "model_id": "text", "provider": "aoai"},
        }
        self.writes = []
        self.fail_write = False
        self.admin = True
        bp = Blueprint("ai_connections_test", __name__)

        def admin_required(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not self.admin:
                    return jsonify({"error": "Forbidden"}), 403
                return function(*args, **kwargs)
            return wrapped

        def update_settings(updates):
            self.writes.append(copy.deepcopy(updates))
            if self.fail_write:
                return False
            self.settings.update(copy.deepcopy(updates))
            return True

        namespace = {
            "bp": bp,
            "get_settings": lambda: copy.deepcopy(self.settings),
            "update_settings": update_settings,
            "jsonify": jsonify,
            "request": request,
            "login_required": lambda function: function,
            "admin_required": admin_required,
            "swagger_route": lambda **_kwargs: lambda function: function,
            "get_auth_security": lambda: [],
            "log_event": lambda *_args, **_kwargs: None,
            "MIGRATION_NOTICE_KEY": "ai_connections_image_migration_notice",
        }
        for name in (
            "CAPABILITY_DEFINITIONS", "EMPTY_MODEL_SELECTION", "IMAGE_MIGRATION_VERSION",
            "IMAGE_MIGRATION_VERSION_KEY", "get_capability_definition",
            "normalize_capability_selection", "resolve_capability_model_selection",
            "build_capability_model_catalog", "is_capability_enabled",
        ):
            namespace[name] = getattr(connections, name)
        nodes = [
            copy.deepcopy(node) for node in ast.walk(ROUTE_TREE)
            if isinstance(node, ast.FunctionDef) and node.name in ROUTE_NAMES
        ]
        self.assertEqual(ROUTE_NAMES, {node.name for node in nodes})
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTE_SOURCE), "exec"), namespace)
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = Client(self.app, self.app.response_class)

    def put(self, capability, endpoint_id="one", model_id="image", provider="aoai"):
        return self.client.put(
            f"{BASE}/{capability}",
            json={"selection": {"endpoint_id": endpoint_id, "model_id": model_id, "provider": provider}},
        )

    def test_catalog_is_read_only_and_excludes_credentials_and_internal_urls(self):
        response = self.client.get(f"{BASE}/image_generation")
        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertEqual(2, len(data["choices"]))
        self.assertEqual({"one", "two"}, {item["endpoint_id"] for item in data["choices"]})
        self.assertNotIn("synthetic-private", response.get_data(as_text=True))
        self.assertNotIn("private-resource", response.get_data(as_text=True))
        self.assertEqual([], self.writes)

    def test_same_deployment_name_resolves_to_the_selected_connection(self):
        response = self.put("image_generation", "two", "image", provider="forged-provider")
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"endpoint_id": "two", "model_id": "image", "provider": "aoai"},
            self.settings[connections.IMAGE_SELECTION_KEY],
        )
        self.assertEqual("one", self.settings["default_model_selection"]["endpoint_id"])
        self.assertNotIn("model_endpoints", self.writes[0])

    def test_image_default_is_independent_from_irreversible_chat_mode(self):
        self.settings["enable_multi_model_endpoints"] = False
        image = self.put("image_generation")
        self.assertEqual(200, image.status_code)
        self.assertTrue(image.get_json()["enabled"])
        self.assertFalse(self.settings["enable_multi_model_endpoints"])
        chat = self.put("chat", model_id="text")
        self.assertEqual(400, chat.status_code)

    def test_one_dual_capable_record_can_serve_both_defaults(self):
        model = self.settings["model_endpoints"][0]["models"][0]
        model["supportsImageGeneration"] = True
        model["enabled_capabilities"] = ["chat", "image_generation"]
        self.assertEqual(200, self.put("image_generation", model_id="text").status_code)
        self.assertEqual(self.settings["default_model_selection"], self.settings[connections.IMAGE_SELECTION_KEY])
        self.assertEqual(2, len(self.settings["model_endpoints"][0]["models"]))

    def test_feature_can_be_configured_without_forcing_it_on(self):
        self.settings["enable_image_generation"] = False
        response = self.put("image_generation")
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.get_json()["enabled"])
        self.assertFalse(self.settings["enable_image_generation"])

    def test_image_model_cannot_be_selected_for_chat(self):
        response = self.put("chat", model_id="image")
        self.assertEqual(400, response.status_code)
        self.assertEqual([], self.writes)
        choices = self.client.get(f"{BASE}/chat").get_json()["choices"]
        self.assertEqual({"text"}, {item["model_id"] for item in choices})

    def test_image_only_connection_does_not_hide_a_same_named_text_model(self):
        builder = next(
            node for node in ast.walk(ROUTE_TREE)
            if isinstance(node, ast.FunctionDef) and node.name == "_build_model_catalog"
        )
        namespace = {
            "supports_model_capability": connections.supports_model_capability,
            "resolve_model_vision_support": lambda _model: (True, "catalog"),
        }
        exec(compile(ast.Module(body=[builder], type_ignores=[]), str(ROUTE_SOURCE), "exec"), namespace)
        catalog = namespace["_build_model_catalog"]({
            "model_endpoints": [
                {"id": "images", "provider": "aoai", "models": [{
                    "deploymentName": "shared-name", "modelName": "gpt-image-1",
                    "enabled_capabilities": ["image_generation"],
                }]},
                {"id": "chat", "provider": "aoai", "models": [{
                    "deploymentName": "shared-name", "modelName": "gpt-4o",
                }]},
            ],
        })
        self.assertEqual(1, len(catalog))
        self.assertEqual("chat", catalog[0]["endpoint_id"])

    def test_unsupported_or_non_global_reference_is_rejected(self):
        self.assertEqual(400, self.put("image_generation", "personal-endpoint").status_code)
        self.settings["model_endpoints"][0]["enabled"] = False
        self.assertEqual(400, self.put("image_generation").status_code)
        self.assertEqual(400, self.put("image_generation", "two", "text").status_code)
        self.assertEqual([], self.writes)

    def test_clear_is_explicit_and_does_not_reactivate_legacy(self):
        self.settings["image_gen_model"] = {"selected": [{"deploymentName": "old-image"}]}
        response = self.put("image_generation", "", "")
        self.assertEqual(200, response.status_code)
        self.assertEqual("", self.settings[connections.IMAGE_SELECTION_KEY]["endpoint_id"])
        self.assertTrue(connections.image_settings_use_connections(self.settings))
        self.assertEqual(1, self.settings[connections.IMAGE_MIGRATION_VERSION_KEY])

    def test_selecting_or_clearing_shared_default_retires_stale_import_errors(self):
        for endpoint_id, model_id in (("one", "image"), ("", "")):
            self.settings["ai_connections_image_migration_notice"] = {
                "status": "error", "message": "Old import failure",
            }
            response = self.put("image_generation", endpoint_id, model_id)
            self.assertEqual(200, response.status_code)
            self.assertEqual("complete", response.get_json()["migration"]["status"])
            self.assertEqual("complete", self.settings["ai_connections_image_migration_notice"]["status"])
            self.assertNotIn("Old import failure", response.get_data(as_text=True))

    def test_invalid_payload_and_partial_reference_are_rejected(self):
        self.assertEqual(400, self.client.put(f"{BASE}/image_generation", json=[]).status_code)
        self.assertEqual(400, self.put("image_generation", "one", "").status_code)
        self.assertEqual([], self.writes)

    def test_failed_write_is_not_successful(self):
        self.fail_write = True
        before = copy.deepcopy(self.settings)
        self.assertEqual(500, self.put("image_generation").status_code)
        self.assertEqual(before, self.settings)

    def test_future_capabilities_are_not_exposed_before_implementation(self):
        for capability in ("embeddings", "transcription", "speech", "computer_use"):
            self.assertEqual(404, self.client.get(f"{BASE}/{capability}").status_code)
            self.assertEqual(404, self.put(capability).status_code)
        self.assertEqual([], self.writes)

    def test_code_defined_extension_reuses_the_same_binding_api_and_factory(self):
        key = "test_voice_operation"
        definition = connections.CapabilityDefinition(
            key, "Test voice", "test_voice_selection", "",
            supported_providers=("aoai",), api_routes=("test_voice",),
            support_resolver=lambda model, _provider: bool(model.get("test_voice")),
        )
        connections.register_capability(
            definition, lambda binding, _settings: binding.model["deploymentName"]
        )
        self.addCleanup(connections.CAPABILITY_DEFINITIONS.pop, key, None)
        self.addCleanup(connections._CLIENT_FACTORIES.pop, key, None)
        self.settings["model_endpoints"][0]["models"].append({
            "id": "voice", "deploymentName": "Synthetic voice", "test_voice": True,
            "enabled_capabilities": [key],
        })
        response = self.put(key, model_id="voice")
        self.assertEqual(200, response.status_code)
        self.assertEqual("voice", response.get_json()["selection"]["model_id"])
        binding = connections.resolve_capability_binding(self.settings, key)
        self.assertEqual("Synthetic voice", connections.create_capability_client(binding, self.settings))
        self.assertEqual(1, len(response.get_json()["choices"]))

    def test_admin_guard_applies_to_both_routes(self):
        self.admin = False
        self.assertEqual(403, self.client.get(f"{BASE}/image_generation").status_code)
        self.assertEqual(403, self.put("image_generation").status_code)
        self.assertEqual([], self.writes)


if __name__ == "__main__":
    unittest.main()
