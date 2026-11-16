#!/usr/bin/env python3
# test_v2_admin_extraction_model_settings.py
"""
Functional test for V2 Admin Settings metadata extraction and vision model saves.
Version: 0.261.393
Implemented in: 0.261.393

This test ensures that selecting a deployed model (such as gpt-5.6-terra) for
Metadata Extraction and Multi-Modal Vision Analysis in the V2 Admin Settings UI
validates against configured AI Connections or classic deployments, saves both
the deployment name and the endpoint/model selection reference through
PATCH /api/v2/admin/settings, preserves duplicate deployment names across
connections, rejects invalid or ambiguous selections without partial writes,
and keeps other component-backed fields protected.
"""

import ast
import copy
import logging
import sys
import unittest
from functools import wraps
from pathlib import Path

from flask import Blueprint, Flask, jsonify, request
from werkzeug.test import Client

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TEST_ROOT = Path(__file__).resolve().parent

for _path in (str(TEST_ROOT), str(APP_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import functions_ai_connections as connections  # noqa: E402
from functions_model_capabilities import resolve_model_vision_support  # noqa: E402
from functions_model_endpoint_types import (  # noqa: E402
    find_enabled_model_endpoint_for_model_name,
    get_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)
from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.nav import ADMIN_NAV  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROUTE_SOURCE = APP_ROOT / "route_backend_v2.py"
ROUTE_TREE = ast.parse(ROUTE_SOURCE.read_text(encoding="utf-8"))


def _extract_route_functions(names):
    nodes = [
        copy.deepcopy(node)
        for node in ast.walk(ROUTE_TREE)
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    found = {node.name for node in nodes}
    if found != set(names):
        raise AssertionError(f"Missing route functions: {sorted(set(names) - found)}")
    nodes.sort(key=lambda node: node.lineno)
    return nodes


def make_terra_endpoint(
    endpoint_id="migrated-aoai",
    name="Migrated Azure OpenAI Endpoint",
    *,
    provider="aoai",
    enabled=True,
    models=None,
):
    if models is None:
        models = [
            {
                "id": "terra-model",
                "deploymentName": "gpt-5.6-terra",
                "modelName": "gpt-5.6-terra",
                "displayName": "gpt-5.6-terra",
                "enabled": True,
            },
            {
                "id": "text-only-model",
                "deploymentName": "gpt-5.3-chat",
                "modelName": "gpt-5.3-chat",
                "displayName": "gpt-5.3-chat",
                "enabled": True,
                "supportsVision": False,
            },
            {
                "id": "image-gen-only",
                "deploymentName": "gpt-image-1",
                "modelName": "gpt-image-1",
                "displayName": "gpt-image-1",
                "enabled": True,
                "enabled_capabilities": ["image_generation"],
            },
        ]
    return {
        "id": endpoint_id,
        "name": name,
        "provider": provider,
        "enabled": enabled,
        "connection": {
            "endpoint": f"https://{endpoint_id}.openai.azure.com",
            "openai_api_version": "2025-04-01-preview",
        },
        "auth": {"type": "managed_identity"},
        "models": copy.deepcopy(models),
    }


class ExtractionModelSettingsSaveTests(unittest.TestCase):
    def setUp(self):
        self.fields_module = import_app_module("admin_settings_fields")
        self.settings = {
            "enable_multi_model_endpoints": True,
            "model_endpoints": [make_terra_endpoint()],
            "enable_extract_meta_data": False,
            "metadata_extraction_model": "",
            "metadata_extraction_model_selection": {
                "endpoint_id": "",
                "model_id": "",
                "provider": "",
            },
            "enable_multimodal_vision": False,
            "multimodal_vision_model": "",
            "multimodal_vision_model_selection": {
                "endpoint_id": "",
                "model_id": "",
                "provider": "",
            },
        }
        self.writes = []
        self.fail_write = False
        self.admin = True

        bp = Blueprint("v2_admin_extraction_settings_test", __name__)

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

        class FakeScreeningError(Exception):
            status_code = 400
            code = "invalid_screening"
            public_message = "Invalid screening settings."

        namespace = {
            "bp": bp,
            "ADMIN_NAV": ADMIN_NAV,
            "VERSION": "0.261.393",
            "EMBEDDING_SELECTION_KEY": connections.EMBEDDING_SELECTION_KEY,
            "EMBEDDING_VECTOR_PROFILE_KEY": "embedding_vector_profile",
            "EMBEDDING_MIGRATION_VERSION_KEY": connections.EMBEDDING_MIGRATION_VERSION_KEY,
            "EMBEDDING_MIGRATION_NOTICE_KEY": "ai_connections_embedding_migration_notice",
            "SECRET_REDACTED_VALUE": "******",
            "ScreeningError": FakeScreeningError,
            "AIConnectionError": connections.AIConnectionError,
            "_ai_connection_error_response": lambda exc: (jsonify({"error": str(exc)}), 400),
            "get_settings": lambda **_kwargs: copy.deepcopy(self.settings),
            "update_settings": update_settings,
            "normalize_admin_settings_updates": self.fields_module.normalize_admin_settings_updates,
            "get_admin_settings_fields": self.fields_module.get_admin_settings_fields,
            "get_admin_section_status": self.fields_module.get_admin_section_status,
            "get_admin_section_guides": self.fields_module.get_admin_section_guides,
            "get_suppressed_capability_keys": self.fields_module.get_suppressed_capability_keys,
            "get_secret_field_keys": self.fields_module.get_secret_field_keys,
            "get_secret_storage_paths": self.fields_module.get_secret_storage_paths,
            "get_admin_settings_api_secret_fields": lambda: (),
            "redact_admin_settings_secrets_for_api": lambda values: copy.deepcopy(values),
            "resolve_admin_settings_secret_value": lambda _k, val, _cur: val,
            "sanitize_model_endpoints_for_frontend": lambda endpoints: copy.deepcopy(endpoints),
            "read_nested_setting": lambda *_args: None,
            "write_nested_setting": lambda *_args: None,
            "effective_capability_ids": lambda values: list(values or []),
            "get_app_role_requirements": list,
            "_build_branding_assets": lambda _settings: {},
            "_build_status_readouts": dict,
            "_build_endpoint_readouts": lambda _settings: {},
            "_build_runtime_flags": dict,
            "preflight_embedding_settings": lambda *_args: None,
            "_seed_connections_on_first_enable": lambda *_args: None,
            "validate_content_screening_settings": lambda *_args: None,
            "_log_governance_setting_changes": lambda *_args: None,
            "_refresh_branding_static_files": lambda: None,
            "ensure_m365_workflow_encryption_key": lambda _settings: {"status": "ready"},
            "supports_model_capability": connections.supports_model_capability,
            "resolve_model_vision_support": resolve_model_vision_support,
            "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
            "find_enabled_model_endpoint_for_model_name": find_enabled_model_endpoint_for_model_name,
            "get_model_endpoint_api_type": get_model_endpoint_api_type,
            "jsonify": jsonify,
            "request": request,
            "login_required": lambda function: function,
            "admin_required": admin_required,
            "swagger_route": lambda **_kwargs: lambda function: function,
            "get_auth_security": lambda: [],
            "log_event": lambda *_args, **_kwargs: None,
            "logging": logging,
        }
        nodes = _extract_route_functions({
            "_build_model_catalog",
            "_redact_admin_settings_for_v2",
            "v2_admin_get_settings",
            "v2_admin_patch_settings",
        })
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTE_SOURCE), "exec"), namespace)
        self.namespace = namespace
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = Client(self.app, self.app.response_class)

    def patch_settings(self, settings_payload):
        return self.client.patch(
            "/api/v2/admin/settings",
            json={"settings": settings_payload},
        )

    def test_saving_gpt_5_6_terra_for_metadata_and_vision_succeeds_and_reloads(self):
        assert_app_version_at_least("0.261.393")

        response = self.patch_settings({
            "enable_extract_meta_data": True,
            "metadata_extraction_model": "gpt-5.6-terra",
            "metadata_extraction_model_selection": {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
                "provider": "forged-provider",
            },
            "enable_multimodal_vision": True,
            "multimodal_vision_model": "gpt-5.6-terra",
            "multimodal_vision_model_selection": {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
                "provider": "forged-provider",
            },
        })
        body = response.get_json()
        self.assertEqual(200, response.status_code, body)
        self.assertTrue(body["success"])
        self.assertEqual("gpt-5.6-terra", self.settings["metadata_extraction_model"])
        self.assertEqual(
            {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
                "provider": "aoai",
            },
            self.settings["metadata_extraction_model_selection"],
        )
        self.assertEqual("gpt-5.6-terra", self.settings["multimodal_vision_model"])
        self.assertEqual(
            {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
                "provider": "aoai",
            },
            self.settings["multimodal_vision_model_selection"],
        )

        reloaded = self.client.get("/api/v2/admin/settings").get_json()
        self.assertEqual("gpt-5.6-terra", reloaded["settings"]["metadata_extraction_model"])
        self.assertEqual(
            "migrated-aoai",
            reloaded["settings"]["metadata_extraction_model_selection"]["endpoint_id"],
        )
        self.assertEqual("gpt-5.6-terra", reloaded["settings"]["multimodal_vision_model"])
        self.assertEqual(
            "migrated-aoai",
            reloaded["settings"]["multimodal_vision_model_selection"]["endpoint_id"],
        )

    def test_scalar_only_save_resolves_unique_connection_and_clears_cleanly(self):
        response = self.patch_settings({
            "enable_extract_meta_data": True,
            "metadata_extraction_model": "gpt-5.6-terra",
            "enable_multimodal_vision": True,
            "multimodal_vision_model": "gpt-5.6-terra",
        })
        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual(
            {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
                "provider": "aoai",
            },
            self.settings["metadata_extraction_model_selection"],
        )
        self.assertEqual(
            {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
                "provider": "aoai",
            },
            self.settings["multimodal_vision_model_selection"],
        )

        clear_response = self.patch_settings({
            "metadata_extraction_model": "",
            "multimodal_vision_model": "",
        })
        self.assertEqual(200, clear_response.status_code, clear_response.get_json())
        self.assertEqual("", self.settings["metadata_extraction_model"])
        self.assertEqual(
            {"endpoint_id": "", "model_id": "", "provider": ""},
            self.settings["metadata_extraction_model_selection"],
        )
        self.assertEqual("", self.settings["multimodal_vision_model"])
        self.assertEqual(
            {"endpoint_id": "", "model_id": "", "provider": ""},
            self.settings["multimodal_vision_model_selection"],
        )

    def test_duplicate_deployment_names_across_connections_stay_distinct(self):
        second_endpoint = make_terra_endpoint(
            endpoint_id="secondary-foundry",
            name="Secondary Foundry Endpoint",
            provider="new_foundry",
            models=[
                {
                    "id": "terra-foundry-model",
                    "deploymentName": "gpt-5.6-terra",
                    "modelName": "gpt-5.6-terra",
                    "displayName": "gpt-5.6-terra",
                    "enabled": True,
                }
            ],
        )
        self.settings["model_endpoints"].append(second_endpoint)

        catalog = self.client.get("/api/v2/admin/settings").get_json()["model_catalog"]
        terra_entries = [entry for entry in catalog if entry["deployment"] == "gpt-5.6-terra"]
        self.assertEqual(2, len(terra_entries), terra_entries)
        self.assertEqual(
            {"migrated-aoai", "secondary-foundry"},
            {entry["endpoint_id"] for entry in terra_entries},
        )
        self.assertEqual(
            {"terra-model", "terra-foundry-model"},
            {entry["model_id"] for entry in terra_entries},
        )

        # Ambiguous scalar-only save must be refused rather than guessing an endpoint.
        ambiguous = self.patch_settings({"metadata_extraction_model": "gpt-5.6-terra"})
        self.assertEqual(400, ambiguous.status_code)
        self.assertIn("metadata_extraction_model", ambiguous.get_json()["field_errors"])
        self.assertEqual([], self.writes)

        # Explicit selection reference disambiguates and saves the second connection.
        resolved = self.patch_settings({
            "metadata_extraction_model": "gpt-5.6-terra",
            "metadata_extraction_model_selection": {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
            },
            "multimodal_vision_model": "gpt-5.6-terra",
            "multimodal_vision_model_selection": {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
            },
        })
        self.assertEqual(200, resolved.status_code, resolved.get_json())
        self.assertEqual(
            {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
                "provider": "new_foundry",
            },
            self.settings["metadata_extraction_model_selection"],
        )
        self.assertEqual(
            {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
                "provider": "new_foundry",
            },
            self.settings["multimodal_vision_model_selection"],
        )

    def test_invalid_incompatible_or_disabled_selections_fail_atomically(self):
        # Text-only model is valid for metadata extraction, but rejected for vision.
        mixed = self.patch_settings({
            "enable_extract_meta_data": True,
            "metadata_extraction_model": "gpt-5.3-chat",
            "metadata_extraction_model_selection": {
                "endpoint_id": "migrated-aoai",
                "model_id": "text-only-model",
            },
            "enable_multimodal_vision": True,
            "multimodal_vision_model": "gpt-5.3-chat",
            "multimodal_vision_model_selection": {
                "endpoint_id": "migrated-aoai",
                "model_id": "text-only-model",
            },
        })
        self.assertEqual(400, mixed.status_code)
        field_errors = mixed.get_json()["field_errors"]
        self.assertIn("multimodal_vision_model", field_errors)
        self.assertNotIn("metadata_extraction_model", field_errors)
        self.assertEqual([], self.writes)
        self.assertFalse(self.settings["enable_extract_meta_data"])

        # Image-generation-only model is rejected for metadata extraction too.
        non_chat = self.patch_settings({
            "metadata_extraction_model": "gpt-image-1",
            "metadata_extraction_model_selection": {
                "endpoint_id": "migrated-aoai",
                "model_id": "image-gen-only",
            },
        })
        self.assertEqual(400, non_chat.status_code)
        self.assertIn("metadata_extraction_model", non_chat.get_json()["field_errors"])
        self.assertEqual([], self.writes)

        # Disabled endpoint or missing model is rejected.
        self.settings["model_endpoints"][0]["enabled"] = False
        disabled_ep = self.patch_settings({
            "metadata_extraction_model": "gpt-5.6-terra",
            "metadata_extraction_model_selection": {
                "endpoint_id": "migrated-aoai",
                "model_id": "terra-model",
            },
        })
        self.assertEqual(400, disabled_ep.status_code)
        self.assertIn("metadata_extraction_model", disabled_ep.get_json()["field_errors"])
        self.assertEqual([], self.writes)

    def test_classic_mode_saves_scalar_and_clears_stale_connection_selection(self):
        self.settings.update({
            "enable_multi_model_endpoints": False,
            "gpt_model": {
                "selected": [
                    {"deploymentName": "gpt-5.6-terra", "modelName": "gpt-5.6-terra"},
                ],
                "all": [],
            },
            "metadata_extraction_model_selection": {
                "endpoint_id": "stale-ep",
                "model_id": "stale-model",
                "provider": "aoai",
            },
            "multimodal_vision_model_selection": {
                "endpoint_id": "stale-ep",
                "model_id": "stale-model",
                "provider": "aoai",
            },
        })

        response = self.patch_settings({
            "metadata_extraction_model": "gpt-5.6-terra",
            "multimodal_vision_model": "gpt-5.6-terra",
        })
        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual("gpt-5.6-terra", self.settings["metadata_extraction_model"])
        self.assertEqual(
            {"endpoint_id": "", "model_id": "", "provider": ""},
            self.settings["metadata_extraction_model_selection"],
        )
        self.assertEqual("gpt-5.6-terra", self.settings["multimodal_vision_model"])
        self.assertEqual(
            {"endpoint_id": "", "model_id": "", "provider": ""},
            self.settings["multimodal_vision_model_selection"],
        )

    def test_unrelated_component_fields_and_persistence_failures_remain_guarded(self):
        rejected = self.patch_settings({
            "default_model_selection": {"endpoint_id": "migrated-aoai", "model_id": "terra-model"},
        })
        self.assertEqual(400, rejected.status_code)
        self.assertEqual(
            "default_model_selection cannot be changed through this endpoint.",
            rejected.get_json()["field_errors"].get("default_model_selection"),
        )
        self.assertEqual([], self.writes)

        self.fail_write = True
        failed = self.patch_settings({
            "metadata_extraction_model": "gpt-5.6-terra",
            "multimodal_vision_model": "gpt-5.6-terra",
        })
        self.assertEqual(503, failed.status_code)
        self.assertFalse(failed.get_json()["success"])

    def test_saved_selections_route_metadata_and_vision_to_chosen_connection(self):
        second_endpoint = make_terra_endpoint(
            endpoint_id="secondary-foundry",
            name="Secondary Foundry Endpoint",
            provider="new_foundry",
            models=[
                {
                    "id": "terra-foundry-model",
                    "deploymentName": "gpt-5.6-terra",
                    "modelName": "gpt-5.6-terra",
                    "displayName": "gpt-5.6-terra",
                    "enabled": True,
                }
            ],
        )
        self.settings["model_endpoints"].append(second_endpoint)

        response = self.patch_settings({
            "enable_extract_meta_data": True,
            "metadata_extraction_model": "gpt-5.6-terra",
            "metadata_extraction_model_selection": {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
            },
            "enable_multimodal_vision": True,
            "multimodal_vision_model": "gpt-5.6-terra",
            "multimodal_vision_model_selection": {
                "endpoint_id": "secondary-foundry",
                "model_id": "terra-foundry-model",
            },
        })
        self.assertEqual(200, response.status_code, response.get_json())

        doc_tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
        doc_nodes = [
            copy.deepcopy(node)
            for node in ast.walk(doc_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name
            in {
                "_normalize_model_endpoint_selection",
                "_build_model_endpoint_client_for_model",
                "resolve_vision_model_endpoint",
                "_resolve_metadata_extraction_client",
            }
        ]
        doc_nodes.sort(key=lambda node: node.lineno)
        built_clients = []

        def fake_build_client(auth_settings, provider, endpoint_url, api_version, deployment_name, **kwargs):
            built_clients.append({
                "auth": auth_settings,
                "provider": provider,
                "endpoint": endpoint_url,
                "api_version": api_version,
                "deployment": deployment_name,
                "endpoint_id": (kwargs.get("endpoint_config") or {}).get("id"),
            })
            return f"client:{provider}:{deployment_name}"

        doc_ns = {
            "normalize_model_endpoints": lambda values: (copy.deepcopy(values), False),
            "find_enabled_model_endpoint_for_model_name": find_enabled_model_endpoint_for_model_name,
            "require_model_capability": connections.require_model_capability,
            "keyvault_model_endpoint_get_helper": lambda cfg, *_a, **_k: copy.deepcopy(cfg),
            "SecretReturnType": type("SecretReturnType", (), {"VALUE": "value"}),
            "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
            "get_model_endpoint_api_type": get_model_endpoint_api_type,
            "infer_model_endpoint_protocol": lambda *_a: "azure_openai",
            "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": "azure_openai",
            "MODEL_ENDPOINT_PROVIDER_ALLOWLIST": {"aoai", "aifoundry", "new_foundry", "custom"},
            "_build_model_endpoint_client": fake_build_client,
            "build_model_endpoint_identity_headers": lambda *_a, **_k: {},
        }
        exec(compile(ast.Module(body=doc_nodes, type_ignores=[]), "functions_documents.py", "exec"), doc_ns)

        client, deployment = doc_ns["_resolve_metadata_extraction_client"](self.settings)
        self.assertEqual("client:new_foundry:gpt-5.6-terra", client)
        self.assertEqual("gpt-5.6-terra", deployment)
        self.assertEqual("secondary-foundry", built_clients[-1]["endpoint_id"])

        vision_ep, vision_model = doc_ns["resolve_vision_model_endpoint"](
            self.settings, self.settings["multimodal_vision_model"]
        )
        self.assertEqual("secondary-foundry", vision_ep["id"])
        self.assertEqual("terra-foundry-model", vision_model["id"])

        # Disabling the selected second endpoint fails closed rather than silently routing to the first endpoint.
        self.settings["model_endpoints"][1]["enabled"] = False
        with self.assertRaises(ValueError):
            doc_ns["_resolve_metadata_extraction_client"](self.settings)
        with self.assertRaises(ValueError):
            doc_ns["resolve_vision_model_endpoint"](
                self.settings, self.settings["multimodal_vision_model"]
            )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExtractionModelSettingsSaveTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
