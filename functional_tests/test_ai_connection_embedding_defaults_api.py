# test_ai_connection_embedding_defaults_api.py
"""
Functional tests for embedding defaults and administrator save boundaries.
Version: 0.261.106
Implemented in: 0.261.106

Mount the actual Flask handlers and pure profile/preflight collaborators with
in-memory settings, vector-store inspection and Key Vault seams. No cloud
clients, inference probes, or application bootstrap are imported.
"""

import ast
import copy
import logging
import sys
import unittest
import uuid
from functools import wraps
from pathlib import Path

from flask import Blueprint, Flask, jsonify, redirect, request
from werkzeug.test import Client

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

import functions_ai_connections as connections
from functions_ai_connection_migration import (
    EMBEDDING_MIGRATION_NOTICE_KEY,
    MIGRATION_NOTICE_KEY,
    build_embedding_connection_migration,
    preserve_legacy_embedding_form_settings,
)
from functions_embedding_profile import EMBEDDING_VECTOR_PROFILE_KEY, resolve_embedding_profile


CAPABILITY_URL = "/api/v2/admin/capability-models/embeddings"
ENDPOINT_URL = "/api/v2/admin/model-endpoints"
LEGACY_URL = "/api/v2/admin/model-selection/embedding"
SETTINGS_URL = "/api/v2/admin/settings"
ROUTE_SOURCE = APP_ROOT / "route_backend_v2.py"
CLASSIC_SOURCE = APP_ROOT / "route_frontend_admin_settings.py"


def load_functions(path, names, namespace, constants=()):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [
        copy.deepcopy(node) for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names)
    nodes[:0] = [
        copy.deepcopy(node) for node in tree.body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants
            for target in node.targets
        )
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


def embedding_endpoint(endpoint_id="one", provider="aoai"):
    return {
        "id": endpoint_id,
        "name": f"Connection {endpoint_id}",
        "provider": provider,
        "enabled": True,
        "connection": {
            "endpoint": f"https://private-{endpoint_id}.openai.azure.com/openai/v1",
            "operation_settings": {"embeddings": {"api": "openai"}},
        },
        "auth": {"type": "api_key", "api_key": "synthetic-api-secret"},
        "models": [
            {
                "id": "embedding",
                "deploymentName": "same-vector-deployment",
                "modelName": "text-embedding-3-small",
                "enabled": True,
                "enabled_capabilities": ["embeddings"],
            },
            {
                "id": "chat",
                "deploymentName": "chat-deployment",
                "modelName": "gpt-4o",
                "enabled_capabilities": ["chat"],
            },
            {
                "id": "image",
                "deploymentName": "image-deployment",
                "modelName": "gpt-image-1",
                "enabled_capabilities": ["image_generation"],
            },
        ],
    }


def selection(endpoint_id="one", model_id="embedding", provider="aoai"):
    return {"endpoint_id": endpoint_id, "model_id": model_id, "provider": provider}


class AdminApiHarness:
    def __init__(self):
        self.settings = {
            "enable_multi_model_endpoints": False,
            "enable_image_generation": False,
            "model_endpoints": [embedding_endpoint(), embedding_endpoint("two")],
            "default_model_selection": selection("two", "chat"),
            connections.IMAGE_SELECTION_KEY: selection("two", "image"),
            connections.IMAGE_MIGRATION_VERSION_KEY: 1,
            MIGRATION_NOTICE_KEY: {"status": "complete", "message": "Image-only notice"},
            "ai_connection_default_notices": {"image_generation": "Retained image notice"},
        }
        self.writes = []
        self.events = []
        self.flashes = []
        self.inspections = []
        self.fence_calls = []
        self.embedding_vectors_written = False
        self.raw_reads = 0
        self.logged_in = True
        self.admin = True
        self.fail_write = False
        self.write_error = None
        self.inspection_error = None
        self.cached_settings = None

        def login_required(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not self.logged_in:
                    return jsonify({"error": "Authentication required"}), 401
                return function(*args, **kwargs)
            return wrapped

        def admin_required(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not self.admin:
                    return jsonify({"error": "Forbidden"}), 403
                return function(*args, **kwargs)
            return wrapped

        def read_settings():
            self.raw_reads += 1
            return copy.deepcopy(self.settings)

        def update_settings(updates):
            self.events.append("commit")
            self.writes.append(copy.deepcopy(updates))
            if self.write_error:
                raise self.write_error
            if self.fail_write:
                return False
            self.settings.update(copy.deepcopy(updates))
            return True

        def inspect_stores(settings, profile):
            self.inspections.append((copy.deepcopy(settings), profile.profile_id))
            if self.inspection_error:
                raise self.inspection_error

        def acquire_fence(*_args, **_kwargs):
            self.fence_calls.append("acquire")
            return {"embedding_vectors_written": self.embedding_vectors_written}

        def release_fence(*_args, **_kwargs):
            self.fence_calls.append("release")
            return True

        def stage_secret(endpoint, _scope_value, *, scope, existing_endpoint, stage_new_secrets):
            assert scope == "global"
            assert stage_new_secrets is True
            self.events.append("stage")
            return copy.deepcopy(endpoint)

        self.bp = Blueprint("embedding_admin_test", __name__)
        namespace = dict(vars(connections))
        namespace.update({
            "bp": self.bp,
            "copy": copy,
            "logging": logging,
            "uuid": uuid,
            "jsonify": jsonify,
            "request": request,
            "redirect": redirect,
            "url_for": lambda _endpoint: "/admin/settings",
            "flash": lambda message, level: self.flashes.append((message, level)),
            "login_required": login_required,
            "admin_required": admin_required,
            "swagger_route": lambda **_kwargs: lambda function: function,
            "get_auth_security": lambda: [],
            "get_settings": lambda: copy.deepcopy(
                self.cached_settings if self.cached_settings is not None else self.settings
            ),
            "read_embedding_settings": read_settings,
            "update_settings": update_settings,
            "log_event": lambda *_args, **_kwargs: None,
            "resolve_embedding_profile": resolve_embedding_profile,
            "EMBEDDING_VECTOR_PROFILE_KEY": EMBEDDING_VECTOR_PROFILE_KEY,
            "EMBEDDING_MIGRATION_NOTICE_KEY": EMBEDDING_MIGRATION_NOTICE_KEY,
            "MIGRATION_NOTICE_KEY": MIGRATION_NOTICE_KEY,
            "inspect_empty_embedding_stores": inspect_stores,
            "_runtime_containers": lambda: (None, None, None),
            "acquire_data_management_search_write_fence": acquire_fence,
            "release_data_management_search_write_fence": release_fence,
            "preserve_legacy_embedding_form_settings": preserve_legacy_embedding_form_settings,
            "normalize_model_endpoints": lambda endpoints: (copy.deepcopy(endpoints), False),
            "sanitize_model_endpoints_for_frontend": lambda endpoints: [
                {key: copy.deepcopy(value) for key, value in endpoint.items() if key != "auth"}
                for endpoint in endpoints
            ],
            "keyvault_model_endpoint_save_helper": stage_secret,
            "keyvault_model_endpoint_cleanup_helper": lambda *_args, **_kwargs: self.events.append("cleanup"),
            "keyvault_model_endpoint_delete_helper": lambda *_args, **_kwargs: self.events.append("delete"),
            "normalize_admin_settings_updates": lambda updates, _current: (copy.deepcopy(updates), {}, []),
            "get_admin_settings_api_secret_fields": lambda: [],
            "get_secret_field_keys": lambda: set(),
            "_seed_connections_on_first_enable": lambda *_args: self.events.append("seed"),
            "_refresh_branding_static_files": lambda: None,
            "_redact_admin_settings_for_v2": lambda updates: copy.deepcopy(updates),
        })
        load_functions(
            APP_ROOT / "functions_embedding_compatibility.py",
            {
                "embedding_settings_changed", "_selected_connection_snapshot",
                "_optional_profile", "_previous_profile", "preflight_embedding_settings",
                "_check_embedding_write_history",
                "active_embedding_profile", "embedding_compatibility_status",
            },
            namespace,
        )
        actual_preflight = namespace["preflight_embedding_settings"]

        def preflight(current, candidate):
            self.events.append("preflight")
            return actual_preflight(current, candidate)

        namespace["preflight_embedding_settings"] = preflight
        load_functions(
            APP_ROOT / "functions_settings.py",
            {
                "normalize_default_model_selection", "resolve_model_selection",
                "resolve_default_model_selection", "resolve_metadata_extraction_model_selection",
                "merge_model_endpoint_auth", "merge_model_endpoint_payload",
            },
            namespace,
            constants={"EMPTY_DEFAULT_MODEL_SELECTION"},
        )
        load_functions(
            ROUTE_SOURCE,
            {
                "_load_global_model_endpoints", "_ai_connection_error_response",
                "_find_model_endpoint", "_model_endpoint_response", "_persist_global_model_endpoints",
                "_read_model_catalog", "_normalize_model_deployment", "normalize_model_catalog",
                "_capability_model_payload", "v2_admin_get_capability_model", "v2_admin_set_capability_model",
                "v2_admin_get_model_selection", "v2_admin_set_model_selection",
                "v2_admin_list_model_endpoints", "v2_admin_get_model_endpoint",
                "v2_admin_create_model_endpoint", "v2_admin_update_model_endpoint",
                "v2_admin_delete_model_endpoint", "v2_admin_patch_settings",
            },
            namespace,
            constants={"MODEL_CATALOG_KINDS"},
        )
        self.namespace = namespace
        self.app = Flask(__name__)
        self.app.register_blueprint(self.bp)
        self.client = Client(self.app, self.app.response_class)

    def activate(self):
        self.settings[connections.EMBEDDING_SELECTION_KEY] = selection()
        self.settings[connections.EMBEDDING_MIGRATION_VERSION_KEY] = 1
        self.settings[EMBEDDING_VECTOR_PROFILE_KEY] = resolve_embedding_profile(self.settings).as_state()

    def put(self, reference=None):
        return self.client.put(CAPABILITY_URL, json={"selection": reference or selection()})

    def classic_save(self, endpoints, updates=None, form_data=None):
        tree = ast.parse(CLASSIC_SOURCE.read_text(encoding="utf-8"))
        admin = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "admin_settings"
        )
        save_block = next(
            node for node in ast.walk(admin)
            if isinstance(node, ast.Try) and any(
                isinstance(statement, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "embedding_settings"
                    for target in statement.targets
                ) for statement in node.body
            )
        )
        wrapper = ast.parse(
            "def save_classic(new_settings, parsed_model_endpoints, form_data, existing_endpoints_by_id):\n"
            "    return settings_saved\n"
        ).body[0]
        wrapper.body.insert(0, copy.deepcopy(save_block))
        namespace = dict(self.namespace)
        namespace.update({
            "new_settings": {"model_endpoints": copy.deepcopy(endpoints), **(updates or {})},
            "parsed_model_endpoints": copy.deepcopy(endpoints),
            "form_data": form_data or {},
            "existing_endpoints_by_id": {
                endpoint["id"]: endpoint for endpoint in self.settings["model_endpoints"]
            },
        })
        exec(compile(ast.fix_missing_locations(ast.Module(
            body=[wrapper], type_ignores=[]
        )), str(CLASSIC_SOURCE), "exec"), namespace)
        with self.app.test_request_context("/admin/settings", method="POST"):
            return namespace["save_classic"](
                namespace["new_settings"], namespace["parsed_model_endpoints"],
                namespace["form_data"], namespace["existing_endpoints_by_id"],
            )


class EmbeddingDefaultApiTests(unittest.TestCase):
    def setUp(self):
        self.api = AdminApiHarness()

    def test_global_default_is_independent_from_chat_and_images(self):
        before = copy.deepcopy(self.api.settings)
        response = self.api.put(selection("two", provider="forged-provider"))
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json["enabled"])
        self.assertEqual(selection("two"), response.json["selection"])
        for key in (
            "default_model_selection", connections.IMAGE_SELECTION_KEY,
            connections.IMAGE_MIGRATION_VERSION_KEY, MIGRATION_NOTICE_KEY,
            "enable_multi_model_endpoints", "enable_image_generation", "model_endpoints",
        ):
            self.assertEqual(before[key], self.api.settings[key])
            self.assertNotIn(key, self.api.writes[0])
        self.assertEqual("complete", response.json["migration"]["status"])
        self.assertEqual("configured", response.json["compatibility"]["status"])
        self.assertEqual(1536, response.json["compatibility"]["dimensions"])

    def test_catalog_is_read_only_non_network_and_redacts_private_metadata(self):
        self.api.activate()
        self.api.settings["model_endpoints"][0]["models"][0]["embedding_config"] = {
            "document_prefix": "private-prefix-secret",
            "query_prefix": "private-query-secret",
            "model_revision": "private-model-revision",
        }
        before = copy.deepcopy(self.api.settings)
        response = self.api.client.get(CAPABILITY_URL)
        self.assertEqual(200, response.status_code)
        self.assertEqual({"one", "two"}, {choice["endpoint_id"] for choice in response.json["choices"]})
        self.assertTrue(all(choice["model_id"] == "embedding" for choice in response.json["choices"]))
        self.assertTrue(all(choice["embedding_policy"]["dimensions"] == 1536 for choice in response.json["choices"]))
        self.assertIsNone(response.json["migration"])
        for private_value in (
            "synthetic-api-secret", "private-one.openai", "private-prefix-secret",
            "private-query-secret", "private-model-revision",
        ):
            self.assertNotIn(private_value, response.get_data(as_text=True))
        self.assertEqual(before, self.api.settings)
        self.assertEqual([], self.api.writes)
        self.assertEqual([], self.api.inspections)
        self.assertEqual([], self.api.fence_calls)
        self.assertEqual(0, self.api.raw_reads)

    def test_foundry_project_url_is_not_an_embedding_choice_or_default(self):
        endpoint = self.api.settings["model_endpoints"][0]
        endpoint["provider"] = "new_foundry"
        endpoint["connection"]["endpoint"] = "https://resource.services.ai.azure.com/api/projects/project"
        self.api.settings[connections.EMBEDDING_SELECTION_KEY] = selection(provider="new_foundry")
        self.assertTrue(connections.supports_model_capability(endpoint["models"][0], "embeddings", "new_foundry"))
        response = self.api.client.get(CAPABILITY_URL)
        self.assertEqual(200, response.status_code)
        self.assertEqual(connections.EMPTY_MODEL_SELECTION, response.json["selection"])
        self.assertIn("inference endpoint", response.json["reason"])
        self.assertEqual(["two"], [choice["endpoint_id"] for choice in response.json["choices"]])
        rejected = self.api.put(selection(provider="new_foundry"))
        self.assertEqual(400, rejected.status_code)
        self.assertEqual("embedding_inference_endpoint_required", rejected.json["code"])
        self.assertEqual([], self.api.writes)
        self.assertEqual([], self.api.inspections)

    def test_imported_default_reports_effective_legacy_limits_with_only_safe_policy_fields(self):
        self.api.settings.update({
            "azure_openai_embedding_endpoint": "https://legacy-limit.openai.azure.com",
            "azure_openai_embedding_authentication_type": "key",
            "azure_openai_embedding_key": "private-legacy-secret",
            "embedding_model": {"selected": [{
                "deploymentName": "legacy-limited",
                "modelName": "text-embedding-3-small",
                "contextWindow": "512",
                "embedding_config": {
                    "model_revision": "private-legacy-revision",
                    "document_prefix": "private-legacy-document-prefix",
                    "query_prefix": "private-legacy-query-prefix",
                },
            }], "all": []},
        })
        self.api.settings.update(build_embedding_connection_migration(self.api.settings))
        selected = self.api.settings[connections.EMBEDDING_SELECTION_KEY]
        profile = resolve_embedding_profile(self.api.settings)
        self.assertTrue(profile.legacy)
        self.assertEqual(512, profile.policy["max_input_tokens"])
        generic_choice = next(
            choice for choice in connections.build_capability_model_catalog(
                self.api.settings["model_endpoints"], "embeddings"
            )
            if choice["endpoint_id"] == selected["endpoint_id"]
        )
        self.assertNotEqual(512, generic_choice["embedding_policy"]["max_input_tokens"])
        before = copy.deepcopy(self.api.settings)
        response = self.api.client.get(CAPABILITY_URL)
        self.assertEqual(200, response.status_code)
        choice = next(
            choice for choice in response.json["choices"]
            if choice["endpoint_id"] == selected["endpoint_id"]
        )
        self.assertEqual(512, choice["embedding_policy"]["max_input_tokens"])
        self.assertEqual(set(generic_choice["embedding_policy"]), set(choice["embedding_policy"]))
        self.assertNotIn("private-legacy", response.get_data(as_text=True))
        self.assertNotIn("legacy-limit.openai.azure.com", response.get_data(as_text=True))
        self.assertEqual(before, self.api.settings)
        self.assertEqual([], self.api.writes)
        self.assertEqual([], self.api.inspections)
        self.assertEqual([], self.api.fence_calls)

    def test_foundry_explicit_resource_inference_endpoint_is_selectable(self):
        endpoint = self.api.settings["model_endpoints"][0]
        endpoint["provider"] = "aifoundry"
        endpoint["connection"]["endpoint"] = "https://resource.services.ai.azure.com/api/projects/project"
        endpoint["connection"]["operation_settings"]["embeddings"]["endpoint"] = (
            "https://resource.services.ai.azure.com/openai/v1"
        )
        response = self.api.put(selection(provider="aifoundry"))
        self.assertEqual(200, response.status_code)
        self.assertEqual("aifoundry", response.json["selection"]["provider"])

    def test_custom_manual_model_requires_explicit_policy(self):
        endpoint = self.api.settings["model_endpoints"][0]
        endpoint["provider"] = "openai_compatible"
        endpoint["connection"]["endpoint"] = "https://gateway.example.test/inference/v1"
        model = endpoint["models"][0]
        model.update(modelName="private-embedding-model", supportsEmbeddings=True)
        self.assertEqual(400, self.api.put(selection(provider="openai_compatible")).status_code)
        self.assertEqual([], self.api.writes)
        model["embedding_config"] = {"dimensions": 768, "max_input_tokens": 512}
        response = self.api.put(selection(provider="openai_compatible"))
        self.assertEqual(200, response.status_code)
        self.assertEqual("openai_compatible", response.json["selection"]["provider"])
        self.assertEqual(768, response.json["compatibility"]["dimensions"])

    def test_cataloged_native_only_model_requires_explicit_gateway_attestation(self):
        endpoint = self.api.settings["model_endpoints"][0]
        endpoint["provider"] = "openai_compatible"
        endpoint["connection"]["endpoint"] = "https://gateway.example.test/v1"
        model = endpoint["models"][0]
        model.update(modelName="embed-v-4-0", supportsEmbeddings=True)
        rejected = self.api.put(selection(provider="openai_compatible"))
        self.assertEqual(400, rejected.status_code)
        self.assertEqual("invalid_model_selection", rejected.json["code"])
        self.assertEqual(
            ["two"],
            [choice["endpoint_id"] for choice in self.api.client.get(CAPABILITY_URL).json["choices"]],
        )
        self.assertEqual([], self.api.writes)
        model["embedding_config"] = {"openai_compatible": True}
        response = self.api.put(selection(provider="openai_compatible"))
        self.assertEqual(200, response.status_code)
        choice = next(choice for choice in response.json["choices"] if choice["endpoint_id"] == "one")
        self.assertEqual(512, choice["embedding_policy"]["max_input_tokens"])

    def test_invalid_embedding_limits_cannot_be_saved(self):
        for config in (
            {"dimensions": True}, {"dimensions": 0}, {"dimensions": 2000},
            {"max_input_tokens": 9000}, {"max_input_tokens": 512, "max_batch_tokens": 1},
        ):
            with self.subTest(config=config):
                self.api.settings["model_endpoints"][0]["models"][0]["embedding_config"] = config
                self.assertEqual(400, self.api.put().status_code)
                self.assertEqual([], self.api.writes)

    def test_custom_endpoint_and_operation_validation_cannot_be_overridden_by_support_flag(self):
        endpoint = self.api.settings["model_endpoints"][0]
        endpoint["provider"] = "openai_compatible"
        endpoint["models"][0]["supportsEmbeddings"] = True
        for url, operation in (
            ("http://remote.example.test/v1", {"api": "openai"}),
            ("https://gateway.example.test/v1?api-key=private-query-value", {"api": "openai"}),
            ("https://gateway.example.test/v1", {"api": "azure_openai"}),
            ("https://gateway.example.test/v1", {"api": "cohere"}),
        ):
            with self.subTest(url=url, operation=operation):
                endpoint["connection"] = {"endpoint": url, "operation_settings": {"embeddings": operation}}
                response = self.api.put(selection(provider="openai_compatible"))
                self.assertEqual(400, response.status_code)
                self.assertNotIn("private-query-value", response.get_data(as_text=True))
                self.assertEqual([], self.api.writes)

    def test_scope_publication_and_model_capability_are_validated(self):
        self.assertEqual(400, self.api.put(selection("personal-only")).status_code)
        self.assertEqual(400, self.api.put(selection(model_id="chat")).status_code)
        for change in ({"enabled": False}, {"enabled_capabilities": []}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.api.settings["model_endpoints"][0]["models"][0])
                self.api.settings["model_endpoints"][0]["models"][0].update(change)
                self.assertEqual(400, self.api.put().status_code)
                self.api.settings["model_endpoints"][0]["models"][0] = original
        self.assertEqual([], self.api.writes)

    def test_selection_parse_failures_return_safe_codes_without_completing_import(self):
        before = copy.deepcopy(self.api.settings)
        for payload in (
            None, [], {}, {"selection": []}, {"selection": "not-an-object"},
            {"selection": {"endpoint_id": "one", "model_id": ""}},
            {"selection": {"endpoint_id": "", "model_id": "embedding"}},
            {"selection": {"endpoint_id": False, "model_id": False}},
            {"selection": {"endpoint_id": 0, "model_id": 0}},
            {"selection": {"endpoint_id": [], "model_id": {}}},
            {"selection": {**selection(), "provider": []}},
            {"selection": selection("missing-connection")},
        ):
            with self.subTest(payload=payload):
                response = self.api.client.put(CAPABILITY_URL, json=payload)
                self.assertEqual(400, response.status_code)
                self.assertEqual("invalid_model_selection", response.json["code"])
                self.assertTrue(response.json["error"])
                self.assertEqual(before, self.api.settings)
                self.assertEqual([], self.api.writes)
        response = self.api.client.put(
            CAPABILITY_URL, data='{"selection":', content_type="application/json"
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_model_selection", response.json["code"])
        self.assertEqual([], self.api.writes)

    def test_clear_retires_embedding_notice_without_erasing_vector_provenance(self):
        self.api.activate()
        baseline = copy.deepcopy(self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
        self.api.settings[EMBEDDING_MIGRATION_NOTICE_KEY] = {
            "status": "error", "message": "Earlier import failure", "imported_connections": 2,
        }
        self.api.settings["azure_openai_embedding_endpoint"] = "https://legacy.openai.azure.com"
        response = self.api.put(dict(connections.EMPTY_MODEL_SELECTION))
        self.assertEqual(200, response.status_code)
        self.assertEqual(connections.EMPTY_MODEL_SELECTION, response.json["selection"])
        self.assertEqual("complete", response.json["migration"]["status"])
        self.assertEqual(2, response.json["migration"]["imported_connections"])
        self.assertEqual(baseline, self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertNotIn(EMBEDDING_VECTOR_PROFILE_KEY, self.api.writes[-1])
        self.assertTrue(connections.embedding_settings_use_connections(self.api.settings))
        self.assertEqual("unavailable", response.json["compatibility"]["status"])
        self.assertEqual({"image_generation": "Retained image notice"}, self.api.settings["ai_connection_default_notices"])

    def test_failed_write_does_not_complete_import_or_change_selection(self):
        self.api.settings[EMBEDDING_MIGRATION_NOTICE_KEY] = {"status": "error", "message": "Import failed"}
        before = copy.deepcopy(self.api.settings)
        self.api.fail_write = True
        self.assertEqual(500, self.api.put().status_code)
        self.assertEqual(before, self.api.settings)
        self.assertNotIn(connections.EMBEDDING_MIGRATION_VERSION_KEY, self.api.settings)

    def test_safe_guard_errors_are_mapped_without_raw_provider_messages(self):
        for code, status in (
            ("embedding_rebuild_required", 409), ("settings_conflict", 409),
            ("embedding_profile_mismatch", 409), ("embedding_profile_changed", 409),
            ("embedding_dimensions_mismatch", 409), ("embedding_policy_invalid", 400),
            ("embedding_compatibility_unavailable", 503),
        ):
            with self.subTest(code=code):
                self.api.write_error = connections.AIConnectionError("Reload or rebuild before changing embeddings.", code)
                response = self.api.put()
                self.assertEqual(status, response.status_code)
                self.assertEqual(code, response.json["code"])
                self.assertNotIn(connections.EMBEDDING_SELECTION_KEY, self.api.settings)
        self.api.write_error = RuntimeError("provider-token=synthetic-private-value")
        response = self.api.put()
        self.assertEqual(500, response.status_code)
        self.assertNotIn("synthetic-private-value", response.get_data(as_text=True))

    def test_selection_uses_authoritative_settings_not_a_stale_cache(self):
        self.api.cached_settings = copy.deepcopy(self.api.settings)
        self.api.settings["model_endpoints"] = []
        self.assertEqual(400, self.api.put().status_code)
        self.assertEqual([], self.api.writes)
        self.assertEqual(1, self.api.raw_reads)

    def test_success_response_reads_the_committed_baseline(self):
        self.api.activate()
        update = self.api.namespace["update_settings"]

        def commit_with_baseline(updates):
            saved = update(updates)
            self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY] = resolve_embedding_profile(self.api.settings).as_state()
            return saved

        self.api.namespace["update_settings"] = commit_with_baseline
        response = self.api.put(selection("two"))
        self.assertEqual(200, response.status_code)
        self.assertEqual("configured", response.json["compatibility"]["status"])
        self.assertEqual(2, self.api.raw_reads)

    def test_legacy_catalog_contract_remains_until_embedding_import(self):
        catalog = [{"deploymentName": "legacy-vector", "modelName": "text-embedding-3-small"}]
        self.api.settings["embedding_model"] = {"selected": catalog, "all": catalog}
        self.api.settings[EMBEDDING_MIGRATION_NOTICE_KEY] = {"status": "error", "message": "Import failed"}
        self.assertEqual(catalog[0], self.api.client.get(LEGACY_URL).json["selected"])
        self.assertEqual(200, self.api.client.put(LEGACY_URL, json={"selected": catalog[0]}).status_code)
        self.assertFalse(connections.embedding_settings_use_connections(self.api.settings))
        self.api.activate()
        writes = len(self.api.writes)
        for url in (LEGACY_URL, "/api/v2/admin/model-selection/EMBEDDING"):
            for method, kwargs in (("get", {}), ("put", {"json": {"selected": catalog[0]}})):
                with self.subTest(url=url, method=method):
                    response = getattr(self.api.client, method)(url, **kwargs)
                    self.assertEqual(409, response.status_code)
                    self.assertEqual("embedding_catalog_migrated", response.json["code"])
        self.assertEqual(writes, len(self.api.writes))

    def test_settings_patch_cannot_change_references_migration_or_baseline(self):
        for key in (
            connections.EMBEDDING_SELECTION_KEY, EMBEDDING_VECTOR_PROFILE_KEY,
            connections.EMBEDDING_MIGRATION_VERSION_KEY, EMBEDDING_MIGRATION_NOTICE_KEY,
        ):
            with self.subTest(key=key):
                response = self.api.client.patch(SETTINGS_URL, json={"settings": {key: {}, "app_title": "Changed"}})
                self.assertEqual(400, response.status_code)
                self.assertIn(key, response.json["field_errors"])
        self.assertEqual([], self.api.writes)
        self.assertEqual([], self.api.events)

    def test_legacy_settings_preflight_precedes_chat_migration_secret_staging(self):
        self.api.settings.update({
            "azure_openai_embedding_endpoint": "https://old.openai.azure.com",
            "embedding_model": {"selected": [{"deploymentName": "legacy-vector", "modelName": "text-embedding-3-small"}]},
        })
        self.api.inspection_error = connections.AIConnectionError("Rebuild existing vectors first.", "embedding_rebuild_required")
        response = self.api.client.patch(SETTINGS_URL, json={"settings": {
            "azure_openai_embedding_endpoint": "https://new.openai.azure.com",
            "enable_multi_model_endpoints": True,
        }})
        self.assertEqual(409, response.status_code)
        self.assertEqual(["preflight"], self.api.events)
        self.assertEqual([], self.api.writes)

    def test_invalid_settings_are_safe_and_admin_guards_are_retained(self):
        self.api.settings = None
        for method, url, kwargs in (
            ("get", CAPABILITY_URL, {}), ("put", CAPABILITY_URL, {"json": {"selection": selection()}}),
            ("get", LEGACY_URL, {}), ("put", LEGACY_URL, {"json": {"selected": None}}),
            ("get", ENDPOINT_URL, {}), ("get", f"{ENDPOINT_URL}/one", {}),
        ):
            with self.subTest(method=method, url=url):
                self.assertEqual(503, getattr(self.api.client, method)(url, **kwargs).status_code)
        self.api.admin = False
        self.assertEqual(403, self.api.client.get(CAPABILITY_URL).status_code)
        self.assertEqual(403, self.api.put().status_code)
        self.api.logged_in = False
        self.assertEqual(401, self.api.client.get(CAPABILITY_URL).status_code)
        self.assertEqual([], self.api.writes)


class EmbeddingEndpointSaveTests(unittest.TestCase):
    def setUp(self):
        self.api = AdminApiHarness()
        self.api.activate()

    def test_removed_disabled_or_unpublished_default_is_cleared_but_baseline_remains(self):
        for change in ("delete", "disable_endpoint", "delete_model", "unpublish", "disable_model"):
            with self.subTest(change=change):
                api = AdminApiHarness()
                api.activate()
                baseline = copy.deepcopy(api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
                endpoint = copy.deepcopy(api.settings["model_endpoints"][0])
                if change == "delete":
                    response = api.client.delete(f"{ENDPOINT_URL}/one")
                else:
                    if change == "disable_endpoint":
                        endpoint["enabled"] = False
                    elif change == "delete_model":
                        endpoint["models"] = endpoint["models"][1:]
                    elif change == "unpublish":
                        endpoint["models"][0]["enabled_capabilities"] = []
                    else:
                        endpoint["models"][0]["enabled"] = False
                    response = api.client.patch(f"{ENDPOINT_URL}/one", json=endpoint)
                self.assertEqual(200, response.status_code)
                self.assertEqual(connections.EMPTY_MODEL_SELECTION, api.settings[connections.EMBEDDING_SELECTION_KEY])
                self.assertEqual(baseline, api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
                self.assertIn("embeddings", api.settings["ai_connection_default_notices"])
                self.assertEqual("Retained image notice", api.settings["ai_connection_default_notices"]["image_generation"])
                self.assertTrue(connections.embedding_settings_use_connections(api.settings))
                self.assertLess(api.events.index("preflight"), api.events.index("stage"))
                self.assertLess(api.events.index("commit"), api.events.index("cleanup"))
                self.assertEqual([], api.inspections)

    def test_same_id_vector_space_edits_are_rejected_before_any_secret_write(self):
        for change in ("dimensions", "model", "endpoint", "prefix"):
            with self.subTest(change=change):
                endpoint = copy.deepcopy(self.api.settings["model_endpoints"][0])
                endpoint["auth"]["api_key"] = "draft-secret-must-not-be-stored"
                if change == "dimensions":
                    endpoint["models"][0]["embedding_config"] = {"dimensions": 1024}
                elif change == "model":
                    endpoint["models"][0]["modelName"] = "text-embedding-3-large"
                elif change == "endpoint":
                    endpoint["connection"]["endpoint"] = "https://different.openai.azure.com/openai/v1"
                else:
                    endpoint["models"][0]["embedding_config"] = {"document_prefix": "new prefix"}
                self.api.events.clear()
                self.api.inspection_error = connections.AIConnectionError("Rebuild existing vectors first.", "embedding_rebuild_required")
                before = copy.deepcopy(self.api.settings)
                response = self.api.client.patch(f"{ENDPOINT_URL}/one", json=endpoint)
                self.assertEqual(409, response.status_code)
                self.assertEqual("embedding_rebuild_required", response.json["code"])
                self.assertEqual(["preflight"], self.api.events)
                self.assertEqual([], self.api.writes)
                self.assertEqual(before, self.api.settings)

    def test_invalid_selected_operation_cannot_be_saved(self):
        endpoint = copy.deepcopy(self.api.settings["model_endpoints"][0])
        endpoint["provider"] = "new_foundry"
        endpoint["connection"]["endpoint"] = "https://resource.services.ai.azure.com/api/projects/project"
        response = self.api.client.patch(f"{ENDPOINT_URL}/one", json=endpoint)
        self.assertEqual(400, response.status_code)
        self.assertEqual("embedding_inference_endpoint_required", response.json["code"])
        self.assertNotIn("stage", self.api.events)
        self.assertEqual([], self.api.writes)

    def test_write_history_rejection_is_coded_before_credentials_or_store_inspection(self):
        self.api.embedding_vectors_written = True
        endpoint = copy.deepcopy(self.api.settings["model_endpoints"][0])
        endpoint["models"][0]["embedding_config"] = {"dimensions": 1024}
        response = self.api.client.patch(f"{ENDPOINT_URL}/one", json=endpoint)
        self.assertEqual(409, response.status_code)
        self.assertEqual("embedding_rebuild_required", response.json["code"])
        self.assertEqual(["acquire", "release"], self.api.fence_calls)
        self.assertEqual([], self.api.inspections)
        self.assertNotIn("stage", self.api.events)
        self.assertEqual([], self.api.writes)

    def test_credential_rotation_preserves_profile_and_blank_secrets(self):
        baseline = copy.deepcopy(self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
        response = self.api.client.patch(f"{ENDPOINT_URL}/one", json={"auth": {"api_key": ""}})
        self.assertEqual(200, response.status_code)
        self.assertEqual("synthetic-api-secret", self.api.settings["model_endpoints"][0]["auth"]["api_key"])
        response = self.api.client.patch(f"{ENDPOINT_URL}/one", json={"auth": {"api_key": "rotated-secret"}})
        self.assertEqual(200, response.status_code)
        self.assertEqual(baseline, self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertEqual([], self.api.inspections)
        self.assertEqual(selection(), self.api.settings[connections.EMBEDDING_SELECTION_KEY])
        self.assertNotIn("rotated-secret", response.get_data(as_text=True))

    def test_late_guard_conflict_does_not_cleanup_live_credentials_or_claim_success(self):
        before = copy.deepcopy(self.api.settings)
        self.api.write_error = connections.AIConnectionError("Reload before saving.", "settings_conflict")
        response = self.api.client.patch(f"{ENDPOINT_URL}/one", json={"auth": {"api_key": "new-secret"}})
        self.assertEqual(409, response.status_code)
        self.assertIn("stage", self.api.events)
        self.assertNotIn("cleanup", self.api.events)
        self.assertNotIn("delete", self.api.events)
        self.assertEqual(before, self.api.settings)

    def test_classic_preflight_blocks_before_staging_and_flashes_actionable_error(self):
        endpoints = copy.deepcopy(self.api.settings["model_endpoints"])
        endpoints[0]["models"][0]["embedding_config"] = {"dimensions": 1024}
        self.api.inspection_error = connections.AIConnectionError(
            "Rebuild document and fact-memory vectors before switching.", "embedding_rebuild_required"
        )
        response = self.api.classic_save(endpoints)
        self.assertEqual(302, response.status_code)
        self.assertEqual(["preflight"], self.api.events)
        self.assertEqual([], self.api.writes)
        self.assertTrue(any("Rebuild document" in message and level == "danger" for message, level in self.api.flashes))

    def test_classic_preserves_omitted_legacy_recovery_values(self):
        self.api.settings.update({
            "azure_openai_embedding_endpoint": "https://retained.openai.azure.com",
            "azure_openai_embedding_key": "retained-secret",
            "enable_embedding_apim": True,
            "embedding_model": {"selected": [{"deploymentName": "retained-vector"}], "all": []},
        })
        before = copy.deepcopy(self.api.settings)
        self.assertIs(self.api.classic_save(
            self.api.settings["model_endpoints"],
            updates={
                "azure_openai_embedding_endpoint": "", "azure_openai_embedding_key": "",
                "enable_embedding_apim": False, "embedding_model": {"selected": [], "all": []},
            },
        ), True)
        for key in (
            "azure_openai_embedding_endpoint", "azure_openai_embedding_key",
            "enable_embedding_apim", "embedding_model", EMBEDDING_VECTOR_PROFILE_KEY,
        ):
            self.assertEqual(before[key], self.api.settings[key])
            self.assertNotIn(key, self.api.writes[-1])
        self.assertLess(self.api.events.index("preflight"), self.api.events.index("stage"))

    def test_classic_clears_unavailable_selection_without_touching_baseline(self):
        baseline = copy.deepcopy(self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertIs(self.api.classic_save(self.api.settings["model_endpoints"][1:]), True)
        self.assertEqual(connections.EMPTY_MODEL_SELECTION, self.api.settings[connections.EMBEDDING_SELECTION_KEY])
        self.assertEqual(baseline, self.api.settings[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertIn("embeddings", self.api.settings["ai_connection_default_notices"])

    def test_classic_failed_final_guard_has_safe_flash_and_no_success(self):
        self.api.write_error = connections.AIConnectionError("Reload before saving.", "settings_conflict")
        response = self.api.classic_save(self.api.settings["model_endpoints"])
        self.assertEqual(302, response.status_code)
        self.assertTrue(any(level == "danger" for _message, level in self.api.flashes))
        self.assertFalse(any(level == "success" for _message, level in self.api.flashes))

    def test_classic_get_does_not_persist_normalized_connections(self):
        tree = ast.parse(CLASSIC_SOURCE.read_text(encoding="utf-8"))
        admin = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "admin_settings"
        )
        self.assertTrue(any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "deepcopy"
            for node in ast.walk(admin)
        ))
        for node in ast.walk(admin):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "update_settings" and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                self.assertNotIn("model_endpoints", [
                    key.value for key in node.args[0].keys if isinstance(key, ast.Constant)
                ])


if __name__ == "__main__":
    unittest.main()
