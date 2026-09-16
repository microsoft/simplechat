# test_content_screening_settings_api.py
"""
Functional tests for content screening settings and authenticated API contracts.
Version: 0.261.122
Implemented in: 0.261.106

Uses the existing unittest/Flask runners with isolated application service mocks.
No Azure configuration, credentials, model requests or storage accounts are used.
"""

import ast
import copy
import hashlib
import importlib.metadata
import importlib.util
import logging
import sys
import types
import unittest
from contextlib import ExitStack
from functools import wraps
from pathlib import Path
from unittest.mock import Mock, patch

from azure.core import MatchConditions
from flask import Blueprint, Flask, jsonify, session
import werkzeug


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(APP_DIR))

from content_screening import access, service
from content_screening.contracts import (
    ContentUnit,
    InspectionResult,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    hash_payload,
)
from content_screening.policies import compose_policy, default_policy
from app_settings_store import AppSettingsStore, COSMOS_METADATA_FIELDS, SETTINGS_REVISION_FIELD
from functional_tests.test_app_settings_store_consistency import FakeCosmos
from functional_tests.test_content_screening_reviews import MemoryEvidence, MemoryStore, module
from functional_tests.test_support.app_stubs import import_app_module


PRIVATE = "private-policy-provider-canary"
SCANNER_MODEL = {"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"}


def activation_policy(*, ai_enabled=True):
    policy = default_policy()
    policy.update({
        "enabled": True,
        "rules": [{
            "id": "required", "name": "Required check", "type": "literal",
            "enabled": True, "severity": "high", "category": "sensitive", "values": [PRIVATE],
        }],
        "allowed_models": [copy.deepcopy(SCANNER_MODEL)],
    })
    policy["ai"].update({
        "enabled": ai_enabled, "model_selection": copy.deepcopy(SCANNER_MODEL),
        "instructions": "Check the complete source for sensitive information.",
    })
    return policy


def settings_functions(**overrides):
    """Execute the actual settings functions without importing application config."""
    names = {
        "validate_content_screening_settings", "update_settings",
        "sanitize_settings_for_user", "sanitize_settings_for_logging",
        "coerce_multi_model_endpoint_enablement",
    }
    tree = ast.parse((APP_DIR / "functions_settings.py").read_text(encoding="utf-8"))
    selected = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    namespace = {
        "ScreeningConfigurationError": ScreeningConfigurationError,
        "ScreeningConflictError": ScreeningConflictError,
        "ScreeningError": ScreeningError,
        "ScreeningValidationError": ScreeningValidationError,
        "copy": copy, "logging": logging, "log_event": Mock(),
        "COSMOS_METADATA_FIELDS": COSMOS_METADATA_FIELDS,
        "SETTINGS_REVISION_FIELD": SETTINGS_REVISION_FIELD,
        "TABULAR_GENERATION_BACKEND_SETTING_KEYS": set(),
        "get_public_workspace_label_context": lambda _settings: {},
        "sanitize_model_endpoints_for_frontend": lambda _endpoints: [],
        "is_tabular_processing_enabled": lambda value: value.get("enable_enhanced_citations", False),
    }
    for name in (
        "normalize_group_workflow_assignment_settings", "normalize_agents_page_promoted_popular_settings",
        "normalize_document_access_index_required_settings", "normalize_inbound_mcp_settings",
        "normalize_public_workspace_display_settings", "normalize_key_vault_reminder_settings",
        "normalize_model_endpoint_identity_header_settings",
    ):
        namespace[name] = lambda _settings: None
    namespace.update(overrides)
    exec(compile(selected, str(APP_DIR / "functions_settings.py"), "exec"), namespace)
    return namespace


class ScreeningSettingsTests(unittest.TestCase):
    def setUp(self):
        self.current = {
            "id": "app_settings", "_etag": "settings-etag",
            "enable_content_screening": False, "enable_enhanced_citations": False,
        }
        self.cosmos = FakeCosmos()
        self.cosmos.document = self.current
        self.container = Mock(wraps=self.cosmos)
        self.container.upsert_item = Mock(side_effect=AssertionError("Unconditional settings writes are forbidden."))
        self.settings_store = AppSettingsStore(self.container)
        self.functions = settings_functions(
            get_settings=lambda **kwargs: copy.deepcopy(self.current),
            cosmos_settings_container=self.container,
            _get_app_settings_store=lambda: self.settings_store,
        )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.original_validation = service.validate_screening_configuration
        self.validate = self.stack.enter_context(patch.object(service, "validate_screening_configuration"))

    def test_activation_is_off_by_default_and_schema_declares_prerequisite(self):
        admin_settings_fields = import_app_module("admin_settings_fields")
        field = admin_settings_fields.get_field_definition("enable_content_screening")
        self.assertIs(field["default"], False)
        self.assertEqual(field["depends_on"], {"key": "enable_enhanced_citations", "equals": True})
        tree = ast.parse((APP_DIR / "functions_settings.py").read_text(encoding="utf-8"))
        default_values = [
            value.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == "enable_content_screening"
            and isinstance(value, ast.Constant)
        ]
        self.assertIn(False, default_values)

    def test_partial_schema_updates_cannot_disable_required_citations(self):
        admin_settings_fields = import_app_module("admin_settings_fields")
        _updates, errors, _warnings = admin_settings_fields.normalize_admin_settings_updates(
            {"enable_content_screening": True}, self.current,
        )
        self.assertIn("enable_content_screening", errors)
        _updates, errors, _warnings = admin_settings_fields.normalize_admin_settings_updates(
            {"enable_enhanced_citations": False},
            {"enable_content_screening": True, "enable_enhanced_citations": True},
        )
        self.assertIn("enable_enhanced_citations", errors)
        _updates, errors, _warnings = admin_settings_fields.normalize_admin_settings_updates(
            {"enable_content_screening": False, "enable_enhanced_citations": False},
            {"enable_content_screening": True, "enable_enhanced_citations": True},
        )
        self.assertEqual(errors, {})

    def test_enable_validates_policy_and_working_storage_before_any_write(self):
        self.assertFalse(self.functions["update_settings"]({"enable_content_screening": True}))
        self.validate.assert_not_called()
        self.container.replace_item.assert_not_called()
        self.current["enable_enhanced_citations"] = True
        self.validate.side_effect = ScreeningConfigurationError()
        self.assertFalse(self.functions["update_settings"]({"enable_content_screening": True}))
        self.assertIs(self.validate.call_args.kwargs["check_storage"], True)
        self.container.replace_item.assert_not_called()
        self.assertIs(self.current["enable_content_screening"], False)

    def test_generic_settings_activation_cannot_bypass_current_model_binding_validation(self):
        self.current["enable_enhanced_citations"] = True
        repository = Mock()
        repository.get_policy.return_value = {"policy": activation_policy()}
        validate_model = Mock(side_effect=ScreeningConfigurationError(PRIVATE))
        self.validate.side_effect = self.original_validation
        with patch.dict(sys.modules, {
            "content_screening.repository": module(
                "content_screening.repository", get_repository=lambda: repository,
            ),
            "content_screening.model": module(
                "content_screening.model", validate_model_bindings=validate_model,
            ),
        }):
            self.assertFalse(self.functions["update_settings"]({"enable_content_screening": True}))
        validate_model.assert_called_once()
        settings = validate_model.call_args.kwargs["settings"]
        selection = validate_model.call_args.args[0]["ai_checks"][0]["model_selection"]
        self.assertIs(settings["enable_content_screening"], True)
        self.assertEqual(selection, SCANNER_MODEL)
        self.container.replace_item.assert_not_called()
        self.container.upsert_item.assert_not_called()
        self.assertIs(self.current["enable_content_screening"], False)
        self.assertNotIn(PRIVATE, str(self.functions["log_event"].call_args_list))

    def test_successful_activation_and_dependency_changes_are_conditional(self):
        self.current["enable_enhanced_citations"] = True
        self.assertTrue(self.functions["update_settings"]({"enable_content_screening": True}))
        call = self.container.replace_item.call_args
        self.assertEqual(call.kwargs["etag"], "settings-etag")
        self.assertEqual(call.kwargs["match_condition"], MatchConditions.IfNotModified)
        self.assertIs(call.kwargs["body"]["enable_content_screening"], True)
        self.container.upsert_item.assert_not_called()
        self.current["enable_content_screening"] = True
        self.container.reset_mock()
        self.assertFalse(self.functions["update_settings"]({"enable_enhanced_citations": False}))
        self.container.replace_item.assert_not_called()

    def test_dependency_validation_uses_fresh_settings_after_a_conditional_write_race(self):
        self.current["enable_enhanced_citations"] = True

        def activate_screening():
            AppSettingsStore(self.cosmos).write(
                lambda current: {**current, "enable_content_screening": True},
            )

        self.cosmos.before_replace = activate_screening
        self.assertFalse(self.functions["update_settings"]({"enable_enhanced_citations": False}))
        self.assertIs(self.cosmos.document["enable_content_screening"], True)
        self.assertIs(self.cosmos.document["enable_enhanced_citations"], True)
        self.assertEqual(self.cosmos.writes, 1)

    def test_disable_is_not_a_document_release_or_policy_reset(self):
        self.current.update({"enable_content_screening": True, "enable_enhanced_citations": True})
        self.assertTrue(self.functions["update_settings"]({"enable_content_screening": False}))
        self.validate.assert_not_called()
        saved = self.container.replace_item.call_args.kwargs["body"]
        self.assertIs(saved["enable_content_screening"], False)
        self.assertIs(saved["enable_enhanced_citations"], True)

    def test_stale_or_provider_failures_are_safe_and_never_upsert(self):
        self.current["enable_enhanced_citations"] = True
        self.container.replace_item.side_effect = RuntimeError(PRIVATE)
        self.assertFalse(self.functions["update_settings"]({"enable_content_screening": True}))
        self.assertNotIn(PRIVATE, str(self.functions["log_event"].call_args_list))
        self.container.upsert_item.assert_not_called()
        self.container.replace_item.side_effect = None
        self.validate.side_effect = RuntimeError(PRIVATE)
        self.assertFalse(self.functions["update_settings"]({"enable_content_screening": True}))
        self.assertNotIn(PRIVATE, str(self.functions["log_event"].call_args_list))

    def test_generic_settings_cannot_store_policies_or_expose_old_accidental_values(self):
        value = {"content_screening_policy": {"rules": [PRIVATE]}}
        self.assertFalse(self.functions["update_settings"](value))
        self.container.upsert_item.assert_not_called()
        sanitized = self.functions["sanitize_settings_for_user"]({
            **value, "enable_content_screening": True, "office_docs_key": PRIVATE,
        })
        self.assertIs(sanitized["enable_content_screening"], True)
        self.assertNotIn(PRIVATE, str(sanitized))
        self.assertNotIn(PRIVATE, str(self.functions["sanitize_settings_for_logging"](value)))


class ApiStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.policies = {}

    def get(self, item_id, partition_key):
        return copy.deepcopy(self.records.get(item_id))

    def get_policy(self, scope_type, scope_id):
        return copy.deepcopy(self.policies.get((scope_type, scope_id)))

    def save_policy(self, scope_type, scope_id, policy, actor_id, *, etag=None):
        previous = self.policies.get((scope_type, scope_id))
        if previous and previous["_etag"] != etag or not previous and etag is not None:
            raise ScreeningConflictError()
        self.policies[(scope_type, scope_id)] = self.version({"policy": policy})
        return self.get_policy(scope_type, scope_id)

    def query_documents(self, scope_type, scope_id=None, *, document_ids=None, **kwargs):
        field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[scope_type]
        return {
            "items": [
                copy.deepcopy(value) for value in self.documents.values()
                if value.get(field) == scope_id and value["id"] in document_ids
            ],
            "continuation": None,
        }


def auth_decorator(role=None):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user:
                return jsonify({"error": "Authentication required."}), 401
            if role == "Admin" and "Admin" not in user.get("roles", []):
                return jsonify({"error": "Forbidden."}), 403
            if role == "User" and not {"User", "Admin"} & set(user.get("roles", [])):
                return jsonify({"error": "Forbidden."}), 403
            return function(*args, **kwargs)
        return wrapped
    return decorate


class ScreeningApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        if not hasattr(werkzeug, "__version__"):
            # Flask 2's test user-agent reads metadata removed by Werkzeug 3.
            self.stack.enter_context(patch.object(
                werkzeug, "__version__", importlib.metadata.version("werkzeug"), create=True,
            ))
        self.repository = ApiStore()
        self.storage = MemoryEvidence()
        self.settings = {
            "enable_content_screening": False, "enable_enhanced_citations": False,
            "office_docs_key": PRIVATE, "content_screening_policy": {"pattern": PRIVATE},
        }
        self.logs = Mock()
        self.settings_helpers = settings_functions()
        self.auth = module(
            "functions_authentication",
            get_current_user_id=lambda: (session.get("user") or {}).get("oid"),
            login_required=auth_decorator(), user_required=auth_decorator("User"),
            admin_required=auth_decorator("Admin"),
            user_required_blueprint=lambda: auth_decorator("User")(lambda: None),
        )
        self.jobs = module(
            "content_screening.jobs",
            create_scan_job=Mock(side_effect=lambda actor, selection, **kwargs: {
                "id": "job", "status": "queued", "selection": selection,
                "counts": {"total": 3, "queued": 3},
                "policy": {"pattern": PRIVATE}, "provider_error": PRIVATE,
            }),
            request_scan_job_action=Mock(),
            enqueue_document_scan=Mock(),
        )
        self.engine = Mock(return_value=InspectionResult(
            "pass", "sample-fingerprint", "policy-fingerprint", findings=[], units_total=1,
        ))
        self.stack.enter_context(patch.dict(sys.modules, {
            "functions_authentication": self.auth,
            "functions_settings": module(
                "functions_settings", get_settings=lambda **kwargs: copy.deepcopy(self.settings),
                cosmos_settings_container=types.SimpleNamespace(read_item=lambda **kwargs: copy.deepcopy(self.settings)),
                update_settings=Mock(return_value=True),
                validate_content_screening_settings=self.settings_helpers["validate_content_screening_settings"],
                sanitize_settings_for_user=self.settings_helpers["sanitize_settings_for_user"],
            ),
            "functions_appinsights": module("functions_appinsights", log_event=self.logs),
            "swagger_wrapper": module(
                "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function,
                get_auth_security=lambda: [],
            ),
            "content_screening.repository": module("content_screening.repository", get_repository=lambda: self.repository),
            "content_screening.storage": module("content_screening.storage", ScreeningStorage=lambda: self.storage),
            "content_screening.jobs": self.jobs,
            "content_screening.engine": module("content_screening.engine", inspect_content=self.engine),
        }))
        self.route = self.load("screening_backend_tests", "route_backend_content_screening.py")
        self.frontend = self.load("screening_frontend_tests", "route_frontend_content_screening.py")
        self.app = Flask(__name__)
        self.app.secret_key = "local-functional-test-only"
        backend = Blueprint("backend_content_screening", __name__)
        frontend = Blueprint("frontend_content_screening", __name__)
        self.route.register_route_backend_content_screening(backend)
        self.frontend.register_route_frontend_content_screening(frontend)
        self.app.register_blueprint(backend)
        self.app.register_blueprint(frontend)
        self.client = self.app.test_client()
        self.login()
        self.subject = Subject("personal", "owner", "document", "1")
        self.units = [ContentUnit("unit", PRIVATE, {"kind": "page", "page_number": 1})]
        fingerprint = content_fingerprint(self.units)
        self.repository.create({
            "id": "scan", "partition_key": "scan", "kind": "scan",
            "scope_key": self.subject.scope_key, "subject": self.subject.to_dict(),
            "content_fingerprint": fingerprint, "policy_fingerprint": "policy-fingerprint",
            "state": "pending_review", "review_required": True, "finding_count": 1,
            "units_ref": self.storage.write(self.subject, "units", [unit.to_dict() for unit in self.units]),
            "source_ref": self.storage.write(self.subject, "original", f"<script>{PRIVATE}</script>".encode()),
            "original_file_name": "review.html", "policy": {"pattern": PRIVATE},
        })
        self.repository.documents["document"] = self.repository.version({
            "id": "document", "user_id": "owner", "version": "1", "file_name": PRIVATE,
            "content_screening": {
                "scan_id": "scan", "review_id": "scan", "state": "pending_review",
                "content_fingerprint": fingerprint, "source_revision": "1", "finding_count": 1,
            },
        })

    @staticmethod
    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, APP_DIR / filename)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    def login(self, actor="owner", roles=None):
        with self.client.session_transaction() as value:
            value["user"] = {"oid": actor, "roles": roles or ["User"]}

    def test_every_route_is_denied_without_a_session(self):
        with self.client.session_transaction() as value:
            value.clear()
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            url = str(rule).replace("<scope_type>", "personal").replace("<scope_id>", "owner")
            url = url.replace("<scan_id>", "scan").replace("<job_id>", "job")
            method = next(method for method in ("GET", "POST", "PUT") if method in rule.methods)
            with self.subTest(url=url, method=method):
                self.assertEqual(self.client.open(url, method=method, json={}).status_code, 401)

    def test_private_evidence_requires_scope_even_for_all_workspace_admin(self):
        self.login("admin", ["Admin"])
        response = self.client.get("/api/content-screening/reviews/scan/units")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.storage.reads, 0)
        self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.login()
        response = self.client.get("/api/content-screening/reviews/scan/units")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"][0]["text"], PRIVATE)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_original_download_is_attachment_only_sanitized_and_never_cached(self):
        self.repository.records["scan"]["original_file_name"] = "../../untrusted\r\nfile<script>.html"
        metadata = self.client.get("/api/content-screening/reviews/scan").json
        download = metadata["downloads"]["original"]
        self.assertEqual(download["url"], "/api/content-screening/reviews/scan/downloads/original")
        self.assertIn("download_original", metadata["allowed_actions"])
        response = self.client.get(download["url"], headers={"If-None-Match": "*", "Range": "bytes=0-1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, f"<script>{PRIVATE}</script>".encode())
        self.assertEqual(response.content_type, "application/octet-stream")
        disposition = response.headers["Content-Disposition"]
        self.assertTrue(disposition.startswith("attachment;"))
        self.assertIn(download["file_name"], disposition)
        for unsafe in ("\r", "\n", "/", "\\", "<", ">"):
            self.assertNotIn(unsafe, disposition)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertNotIn("ETag", response.headers)
        self.assertIn("sandbox", response.headers["Content-Security-Policy"])

    def test_download_routes_deny_admin_private_access_and_source_overrides(self):
        for kind in ("original", "clean"):
            path = f"/api/content-screening/reviews/scan/downloads/{kind}"
            self.login("admin", ["Admin"])
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn(PRIVATE, response.get_data(as_text=True))
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.login()
            for query in ("source_ref=other", "allow_quarantined=true", "scan_id=other"):
                with self.subTest(kind=kind, query=query):
                    self.assertEqual(self.client.get(f"{path}?{query}").status_code, 400)
        self.assertEqual(self.storage.reads, 0)

    def test_original_download_cannot_return_replaced_source_or_revoked_scope(self):
        source_read = self.storage.read_bytes

        def replace_source(reference, subject):
            content = source_read(reference, subject)
            self.repository.records["scan"]["source_ref"] = {"private_source": "changed"}
            return content

        with patch.object(self.storage, "read_bytes", side_effect=replace_source):
            response = self.client.get("/api/content-screening/reviews/scan/downloads/original")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_clean_attachment_requires_exact_active_release_and_has_no_original_fallback(self):
        url = "/api/content-screening/reviews/scan/downloads/clean"
        with patch.object(access, "read_available_document_bytes") as read:
            self.assertEqual(self.client.get(url).status_code, 404)
            read.assert_not_called()
        content = b"Reviewed clean text"
        active_blob = {
            "container": "user-documents", "path": "owner/document/screened/scan/clean.txt",
            "etag": "active-etag", "content_hash": hashlib.sha256(content).hexdigest(),
        }
        scan = self.repository.records["scan"]
        scan.update({"state": "cleared", "sanitized": True, "publication": {"active_blob": active_blob}})
        document = self.repository.documents["document"]
        document["file_name"] = "clean.txt"
        document["content_screening"].update({
            "state": "cleared", "active_blob": active_blob, "sanitized": True,
            "policy_fingerprint": scan["policy_fingerprint"], "canonical_ref": scan["units_ref"],
        })
        metadata = self.client.get("/api/content-screening/reviews/scan").json
        self.assertEqual(metadata["downloads"]["clean"]["url"], url)
        self.assertIn("download_clean", metadata["allowed_actions"])
        with patch.object(access, "read_available_document_bytes", return_value=(copy.deepcopy(document), content)) as read:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, content)
            self.assertIn("attachment;", response.headers["Content-Disposition"])
            self.assertEqual(response.content_type, "application/octet-stream")
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            read.assert_called_once()
        document["content_screening"]["scan_id"] = "replacement-scan"
        with patch.object(access, "read_available_document_bytes") as read:
            self.assertEqual(self.client.get(url).status_code, 404)
            read.assert_not_called()
        self.assertEqual(self.storage.reads, 0)

    def test_missing_source_keeps_metadata_only_review_actions(self):
        self.repository.records["scan"].update({
            "state": "scan_error", "units_ref": None, "result_ref": None, "source_ref": None,
        })
        metadata = self.client.get("/api/content-screening/reviews/scan")
        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.json["allowed_actions"], ["reject", "delete"])
        self.assertEqual(metadata.json["evidence"], {"units_available": False, "findings_available": False})
        for suffix in ("units", "findings", "downloads/original", "downloads/clean"):
            response = self.client.get(f"/api/content-screening/reviews/scan/{suffix}")
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.assertEqual(self.storage.reads, 0)

    def seed_tombstone(self, subject=None, deleted_by="owner"):
        subject = subject or self.subject
        self.repository.documents.pop(subject.document_id, None)
        self.repository.records["scan"].update({
            "subject": subject.to_dict(), "scope_key": subject.scope_key, "state": "deleted",
            "deleted_by": deleted_by, "deletion_started_at": "2026-09-16T15:00:00+00:00",
            "deleted_at": "2026-09-16T15:01:00+00:00",
            "units_ref": None, "result_ref": None, "source_ref": None,
            "original_file_name": None, "policy": {}, "review_decision": None,
        })
        return self.repository.get_scan("scan")

    def test_terminal_delete_http_responses_still_require_scope_and_are_safe_tombstones(self):
        tombstone = self.seed_tombstone()
        path = "/api/content-screening/reviews/scan"
        body = {"etag": tombstone["_etag"], "action": "delete", "reason": "Confirm completed deletion."}
        with patch.dict(sys.modules, {
            "functions_approvals": module(
                "functions_approvals", resolve_content_screening_approval=Mock(),
            ),
        }), patch.object(service, "delete_screened_document", wraps=service.delete_screened_document) as delete:
            self.login("admin", ["Admin"])
            self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post(f"{path}/decision", json=body).status_code, 403)
            delete.assert_not_called()

            self.login()
            responses = [
                self.client.get(path),
                self.client.post(f"{path}/decision", json=body),
                self.client.post(f"{path}/decision", json=body),
            ]
            for response in responses:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["state"], "deleted")
                self.assertEqual(response.json["allowed_actions"], [])
                self.assertFalse(any(response.json["downloads"].values()))
                self.assertFalse(any(response.json["evidence"].values()))
                self.assertFalse({"policy", "source_ref", "units_ref", "result_ref"} & set(response.json))
                self.assertNotIn(PRIVATE, response.get_data(as_text=True))
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(delete.call_count, 2)
            self.assertEqual(self.repository.get_scan("scan"), tombstone)
            self.assertEqual(self.storage.reads, 0)

    def test_terminal_delete_rechecks_current_group_and_public_roles_before_the_helper(self):
        path = "/api/content-screening/reviews/scan"
        for scope_type in ("group", "public"):
            with self.subTest(scope=scope_type):
                roles = {"manager": "DocumentManager"}

                def group_role(actor_id, scope_id, *, allowed_roles):
                    if scope_id != "team" or roles.get(actor_id) not in allowed_roles:
                        raise PermissionError()
                    return roles[actor_id]

                tombstone = self.seed_tombstone(Subject(scope_type, "team", "document", "1"), "manager")
                body = {"etag": tombstone["_etag"], "action": "delete", "reason": "Confirm completed cleanup."}
                with patch.dict(sys.modules, {
                    "functions_group": module("functions_group", assert_group_role=group_role),
                    "functions_public_workspaces": module(
                        "functions_public_workspaces",
                        find_public_workspace_by_id=lambda scope: {"id": scope},
                        get_user_role_in_public_workspace=lambda workspace, actor: roles.get(actor),
                    ),
                    "functions_approvals": module(
                        "functions_approvals", resolve_content_screening_approval=Mock(),
                    ),
                }), patch.object(service, "delete_screened_document", wraps=service.delete_screened_document) as delete:
                    self.login("manager")
                    self.assertEqual(self.client.get(path).status_code, 200)
                    self.assertEqual(self.client.post(f"{path}/decision", json=body).status_code, 200)
                    delete.assert_called_once()

                    roles["manager"] = "User"
                    self.login("manager", ["Admin"])
                    self.assertEqual(self.client.get(path).status_code, 403)
                    self.assertEqual(self.client.post(f"{path}/decision", json=body).status_code, 403)
                    self.assertEqual(delete.call_count, 1)
                    self.assertEqual(self.storage.reads, 0)

    def test_remediation_contract_is_queued_and_has_no_http_inline_bypass(self):
        self.settings.update({"enable_content_screening": True, "enable_enhanced_citations": True})
        policy = default_policy()
        policy.update({"enabled": True, "rules": [{
            "id": "sensitive", "name": "Sensitive", "type": "literal", "values": [PRIVATE],
            "enabled": True, "severity": "high", "category": "sensitive",
        }]})
        body = {
            "etag": self.repository.records["scan"]["_etag"],
            "edits": [{
                "action": "remove_span", "unit_id": "unit", "content_hash": self.units[0].content_hash,
                "start": 0, "end": 1,
            }],
        }
        with patch.dict(sys.modules, {
            "functions_approvals": module(
                "functions_approvals", resolve_content_screening_approval=Mock(),
            ),
        }), patch.object(service, "get_effective_policy", return_value=compose_policy(policy)), \
                patch.object(service, "validate_screening_configuration"), \
                patch.object(service, "inspect_scan") as inspect:
            response = self.client.post("/api/content-screening/reviews/scan/remediate", json=body)
            self.assertEqual(response.status_code, 202)
            candidate = response.json
            self.assertEqual(candidate["state"], "pending_scan")
            self.assertEqual(candidate["candidate_of"], "scan")
            self.assertIsNone(candidate["outcome"])
            self.assertFalse(candidate["coverage"]["complete"])
            self.assertFalse({"approve_with_flags", "approve_clean"} & set(candidate["allowed_actions"]))
            self.jobs.enqueue_document_scan.assert_called_once_with(
                self.subject, "owner", scan_id=candidate["id"], repository=self.repository,
            )
            inspect.assert_not_called()
            stored = self.repository.get_scan(candidate["id"])
            self.assertEqual(
                self.storage.read_json(stored["units_ref"], self.subject)[0]["text"],
                self.units[0].text[1:],
            )
            refreshed = self.client.get(f"/api/content-screening/reviews/{candidate['id']}")
            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(refreshed.json["state"], "pending_scan")
            rejected = self.client.post("/api/content-screening/reviews/scan/remediate", json={
                **body, "run_inline": True,
            })
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(self.jobs.enqueue_document_scan.call_count, 1)
            inspect.assert_not_called()

    def test_activation_rejects_invalid_current_baseline_binding_before_settings_write(self):
        self.login("admin", ["Admin"])
        self.settings["enable_enhanced_citations"] = True
        self.repository.policies[("global", "global")] = {"policy": activation_policy()}
        validate_model = Mock(side_effect=ScreeningConfigurationError(PRIVATE))
        with patch.dict(sys.modules, {
            "content_screening.model": module(
                "content_screening.model", validate_model_bindings=validate_model,
            ),
        }):
            response = self.client.put("/api/content-screening/configuration", json={"enabled": True})
        self.assertEqual(response.status_code, 503)
        validate_model.assert_called_once()
        settings = validate_model.call_args.kwargs["settings"]
        selection = validate_model.call_args.args[0]["ai_checks"][0]["model_selection"]
        self.assertIs(settings["enable_content_screening"], True)
        self.assertEqual(selection, SCANNER_MODEL)
        self.route.update_settings.assert_not_called()
        self.assertIs(self.settings["enable_content_screening"], False)
        self.engine.assert_not_called()
        self.assertNotIn(PRIVATE, response.get_data(as_text=True))

    def test_activation_preflights_only_selected_ai_checks_without_inference(self):
        self.login("admin", ["Admin"])
        self.settings["enable_enhanced_citations"] = True
        for ai_enabled in (True, False):
            with self.subTest(ai_enabled=ai_enabled):
                self.repository.policies[("global", "global")] = {
                    "policy": activation_policy(ai_enabled=ai_enabled),
                }
                validate_model = Mock()
                storage = Mock()
                build_client = Mock(return_value=object())
                self.route.update_settings.reset_mock()
                with patch.dict(sys.modules, {
                    "content_screening.model": module(
                        "content_screening.model", validate_model_bindings=validate_model,
                    ),
                    "content_screening.storage": module(
                        "content_screening.storage", ScreeningStorage=lambda **kwargs: storage,
                    ),
                    "config": module(
                        "config", build_enhanced_citations_blob_service_client=build_client,
                    ),
                }):
                    response = self.client.put("/api/content-screening/configuration", json={"enabled": True})
                self.assertEqual(response.status_code, 200)
                self.assertIs(response.json["enabled"], True)
                if ai_enabled:
                    validate_model.assert_called_once()
                    self.assertEqual(
                        validate_model.call_args.args[0]["ai_checks"][0]["model_selection"], SCANNER_MODEL,
                    )
                else:
                    validate_model.assert_not_called()
                storage.validate_connection.assert_called_once()
                build_client.assert_called_once()
                self.route.update_settings.assert_called_once_with({"enable_content_screening": True})
                self.engine.assert_not_called()
                self.assertNotIn(PRIVATE, response.get_data(as_text=True))

    def test_configuration_status_and_review_metadata_never_dump_settings_or_paths(self):
        for url in (
            "/api/content-screening/configuration",
            "/api/content-screening/reviews/scan",
            "/api/content-screening/status?scope_type=personal&scope_id=owner&document_id=document",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(PRIVATE, response.get_data(as_text=True))

    def test_configuration_update_reads_a_fresh_snapshot_before_validation(self):
        self.login("admin", ["Admin"])
        self.settings["enable_enhanced_citations"] = True
        stale = {**self.settings, "enable_enhanced_citations": False}
        with patch.object(self.route, "get_settings", return_value=stale), \
                    patch.object(self.route, "validate_content_screening_settings") as validate:
                response = self.client.put("/api/content-screening/configuration", json={"enabled": True})
        self.assertEqual(response.status_code, 200)
        self.assertIs(validate.call_args.args[1]["enable_enhanced_citations"], True)
        response = self.client.get("/api/content-screening/status?scope_type=personal&scope_id=other&document_id=document")
        self.assertEqual(response.status_code, 403)

    def test_unknown_fields_bad_offsets_and_stale_etags_are_rejected(self):
        for body in (
            {"etag": "etag", "edits": [], "source_ref": PRIVATE},
            {"etag": "etag", "edits": [], "approved": True},
            {"subject": self.subject.to_dict(), "edits": []},
        ):
            response = self.client.post("/api/content-screening/reviews/scan/preview", json=body)
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/content-screening/reviews/scan/preview", json={"etag": "stale", "edits": []})
        self.assertEqual(response.status_code, 409)
        response = self.client.get("/api/content-screening/reviews/scan/units?page_size=101")
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/content-screening/reviews/scan/decision", json={
            "etag": "stale", "action": {}, "reason": "reviewed",
        })
        self.assertEqual(response.status_code, 400)

    def test_rule_policies_are_separate_and_inheritance_never_contains_baseline_values(self):
        from content_screening.policies import default_policy

        policy = default_policy()
        policy.update({
            "enabled": True,
            "rules": [{
                "id": "private-baseline", "name": PRIVATE, "type": "literal", "values": [PRIVATE],
                "enabled": True, "severity": "high", "category": "sensitive",
            }],
        })
        self.repository.policies[("global", "global")] = {"policy": policy, "_etag": "global-etag"}
        response = self.client.get("/api/content-screening/policies/personal/owner")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["inherited_summary"]["rule_count"], 1)
        self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.assertEqual(self.client.get("/api/content-screening/policies/global/global").status_code, 403)

    def test_policy_preview_runs_only_editable_checks_and_never_writes_records(self):
        from content_screening.policies import default_policy

        baseline = default_policy()
        baseline.update({"enabled": True, "rules": [{
            "id": "baseline", "name": PRIVATE, "type": "literal", "values": [PRIVATE],
            "enabled": True, "severity": "high", "category": "sensitive",
        }]})
        self.repository.policies[("global", "global")] = {"policy": baseline, "_etag": "etag"}
        addition = default_policy()
        addition.update({"enabled": True, "rules": [{
            "id": "my-rule", "name": "Example", "type": "literal", "values": ["example"],
            "enabled": True, "severity": "low", "category": "custom",
        }]})
        before = copy.deepcopy(self.repository.records)
        response = self.client.post("/api/content-screening/policies/personal/owner/test", json={
            "policy": addition, "sample_text": "An example sample.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PRIVATE, str(self.engine.call_args))
        self.assertEqual(self.repository.records, before)
        self.assertFalse(self.logs.called)
        tested_policy = self.engine.call_args.args[2]
        self.assertLessEqual(tested_policy["limits"]["max_windows"], 32)
        self.assertLessEqual(tested_policy["limits"]["max_runtime_seconds"], 30)

    def test_policy_writes_use_etag_and_models_cannot_bypass_baseline_allowlist(self):
        from content_screening.policies import default_policy

        policy = default_policy()
        self.repository.policies[("personal", "owner")] = {"policy": policy, "_etag": "current"}
        response = self.client.put("/api/content-screening/policies/personal/owner", json={
            "policy": policy, "etag": "stale",
        })
        self.assertEqual(response.status_code, 409)
        policy["allowed_models"] = [{"endpoint_id": "unapproved", "model_id": "model"}]
        response = self.client.put("/api/content-screening/policies/personal/owner", json={
            "policy": policy, "etag": "current",
        })
        self.assertEqual(response.status_code, 400)

    def test_global_jobs_require_admin_and_only_return_operational_fields(self):
        response = self.client.post("/api/content-screening/scans", json={"all_workspaces": True})
        self.assertEqual(response.status_code, 403)
        self.jobs.create_scan_job.assert_not_called()
        self.login("admin", ["Admin"])
        response = self.client.post("/api/content-screening/scans", json={"all_workspaces": True})
        self.assertEqual(response.status_code, 202)
        self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.assertIs(self.jobs.create_scan_job.call_args.kwargs["is_admin"], True)
        self.assertEqual(response.json["state"], "queued")
        self.assertEqual(response.json["counters"], {"total": 3, "queued": 3})

    def test_job_detail_and_items_omit_subject_evidence_and_provider_errors(self):
        self.repository.create({
            "id": "job", "partition_key": "job", "kind": "job", "status": "failed",
            "selection": {"scope_type": "personal", "scope_id": "owner"},
            "error_code": PRIVATE, "source_ref": PRIVATE, "policy": {"values": [PRIVATE]},
        })
        self.repository.create({
            "id": "work", "partition_key": "job", "kind": "work_item", "status": "failed",
            "job_id": "job", "subject": {"evidence": PRIVATE}, "error_code": PRIVATE,
        })
        for url in ("/api/content-screening/scans/job", "/api/content-screening/scans/job/items"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.login("other")
        self.assertEqual(self.client.get("/api/content-screening/scans/job/items").status_code, 403)

    def test_unexpected_errors_never_echo_or_log_provider_messages(self):
        with patch.object(self.route, "_repository", side_effect=RuntimeError(PRIVATE)):
            response = self.client.get("/api/content-screening/reviews/scan")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(PRIVATE, response.get_data(as_text=True))
        self.assertNotIn(PRIVATE, str(self.logs.call_args_list))

    def test_classic_entry_sanitizes_settings_even_after_enrollment_is_disabled(self):
        with patch.object(self.frontend, "render_template", return_value="review shell") as render:
            response = self.client.get("/content-review")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PRIVATE, str(render.call_args))
        self.assertIn("no-store", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
