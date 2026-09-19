# test_m365_routes.py
"""
Functional tests for Microsoft 365 Profile, approval, and audit routes.
Version: 0.261.034
Implemented in: 0.261.029

Imports the real route module with scoped authentication/logging I/O seams.
Exercises exact subject/object scope, CSRF, safe errors, callback registration,
unified decisions, private audit, and user-only notification targeting.
"""

import ast
import copy
import functools
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from azure.cosmos import exceptions
from flask import Blueprint, Flask, jsonify, session
from werkzeug.test import Client


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

# Tests initialize their own source path before importing real application code.
import functions_m365_approvals as approvals
import functions_m365_connections as connections
import functions_m365_execution as execution
from test_support.m365 import Clock, CosmosContainer, Notifications


def module_stub(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


def login_guard(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "not_logged_in"}), 401
        return function(*args, **kwargs)
    return wrapped


def user_guard(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        if not set(session.get("user", {}).get("roles", [])) & {"User", "Admin"}:
            return jsonify({"error": "forbidden"}), 403
        return function(*args, **kwargs)
    return wrapped


def blueprint_guard():
    @login_guard
    @user_guard
    def guard():
        return None
    guard._simplechat_auth_policy = ("login_required", "user_required")
    return guard


class M365RouteTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.container = CosmosContainer()
        self.service = approvals.M365ApprovalService(
            container_factory=lambda: self.container, notification_sender=Notifications(),
            decision_validator=lambda approval: True, clock=self.clock,
        )
        self.connection_container = CosmosContainer("user_id")
        self.connection_config = connections.M365IdentityConfig(
            "client-a", "tenant-a", "https://login.microsoftonline.com/tenant-a",
            "https://graph.microsoft.com", "azurecloud",
        )
        self.connection_service = connections.M365ConnectionService(
            container_factory=lambda: self.connection_container,
            config_provider=lambda: self.connection_config,
        )
        for target, name, value in (
            (approvals, "_service", self.service),
            (connections, "_service", self.connection_service),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location(
            "m365_test_route_backend", APP_DIR / "route_backend_m365.py",
        )
        self.routes = importlib.util.module_from_spec(spec)
        dependencies = {
            "functions_appinsights": module_stub("functions_appinsights", log_event=lambda *args, **kwargs: None),
            "functions_authentication": module_stub(
                "functions_authentication", login_required=login_guard, user_required=user_guard,
                user_required_blueprint=blueprint_guard,
            ),
            "swagger_wrapper": module_stub(
                "swagger_wrapper",
                swagger_route=lambda **kwargs: lambda function: function,
                get_auth_security=lambda: [],
            ),
        }
        with patch.dict(sys.modules, dependencies):
            spec.loader.exec_module(self.routes)
        self.app = Flask(__name__)
        self.app.secret_key = "unit-test-only"
        blueprint = Blueprint("backend_m365", __name__)
        self.routes.register_route_backend_m365(blueprint)
        self.app.register_blueprint(blueprint)
        self.client = Client(self.app, response_wrapper=self.app.response_class)
        self.sign_in()

    def set_session(self, values):
        serializer = self.app.session_interface.get_signing_serializer(self.app)
        self.client.set_cookie(self.app.config["SESSION_COOKIE_NAME"], serializer.dumps(values))

    def sign_in(self, user_id="user-a", tenant_id="tenant-a", roles=None):
        self.set_session({
            "user": {
                "oid": user_id, "tid": tenant_id,
                "roles": roles if roles is not None else ["User"],
            }
        })
        response = self.client.get("/api/m365/preferences")
        self.csrf = response.get_json().get("csrf_token")

    def context(self, **changes):
        values = {
            "actor_user_id": "user-a", "data_user_id": "user-a", "tenant_id": "tenant-a",
            "conversation_id": "conversation-a", "shared": True, "audience_version": "audience-1",
            "request_id": "request-a", "action_configs": {"action-a": {"source": "email"}},
        }
        values.update(changes)
        return execution.M365ExecutionContext(**values)

    def pending(self, **changes):
        with self.assertRaises(approvals.M365ApprovalRequired) as raised:
            self.service.authorize_sources(self.context(**changes), {"email": "always"})
        return raised.exception.approval_id

    def test_every_new_route_requires_login_and_user_with_blueprint_guard(self):
        self.set_session({})
        response = self.client.get("/api/m365/preferences")
        self.assertEqual(response.status_code, 401)
        self.sign_in(roles=[])
        forbidden = self.client.get("/api/m365/connections")
        self.assertEqual(forbidden.status_code, 403)
        policies = [
            getattr(guard, "_simplechat_auth_policy", None)
            for guard in self.app.before_request_funcs["backend_m365"]
        ]
        self.assertIn(("login_required", "user_required"), policies)
        routes = {rule.rule: rule for rule in self.app.url_map.iter_rules()}
        self.assertEqual(routes["/api/m365/connections/callback"].methods, {"GET", "HEAD", "OPTIONS"})

    def test_waiting_requests_supply_csrf_without_loading_profile(self):
        jobs = CosmosContainer("user_id")
        self.set_session({"user": {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}})
        with patch.dict(sys.modules, {
            "config": module_stub("config", cosmos_m365_execution_runs_container=jobs),
        }):
            response = self.client.get("/api/m365/requests")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.get_json()["csrf_token"]), 32)

    def test_mutations_require_csrf_and_no_cross_site_browser_requests(self):
        data = {"sources": {"email": "always"}}
        missing = self.client.patch("/api/m365/preferences", json=data)
        cross_site = self.client.patch(
            "/api/m365/preferences", json=data,
            headers={"X-M365-CSRF-Token": self.csrf, "Sec-Fetch-Site": "cross-site"},
        )
        valid = self.client.patch(
            "/api/m365/preferences", json=data, headers={"X-M365-CSRF-Token": self.csrf},
        )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(cross_site.status_code, 403)
        self.assertEqual(valid.status_code, 200)

    def test_preferences_never_accept_identity_grants_or_expiry_fields(self):
        for payload in (
            {"user_id": "user-b", "sources": {"email": "always"}},
            {"sources": {"email": {"grant": "forged", "expires_at": "2999-01-01"}}},
            {"access_token": "must-not-be-persisted"},
        ):
            response = self.client.patch(
                "/api/m365/preferences", json=payload, headers={"X-M365-CSRF-Token": self.csrf},
            )
            self.assertEqual(response.status_code, 400)
        preferences = self.service.get_preferences("user-a")
        self.assertEqual(preferences["sources"]["email"], "ask")
        self.assertNotIn("must-not-be-persisted", json.dumps(list(self.container.items.values())))

    def test_preferences_persist_only_explicit_confirmed_iana_timezone(self):
        initial = self.client.get("/api/m365/preferences")
        self.assertIsNone(initial.get_json()["preferences"]["timezone"])
        missing_csrf = self.client.patch("/api/m365/preferences", json={"timezone": "UTC"})
        invalid = self.client.patch(
            "/api/m365/preferences", json={"timezone": "Not/A_Timezone"},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        saved = self.client.patch(
            "/api/m365/preferences", json={"timezone": "America/New_York"},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        read = self.client.get("/api/m365/preferences")
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["preferences"]["timezone"], "America/New_York")
        self.assertEqual(read.get_json()["preferences"]["timezone"], "America/New_York")
        self.sign_in("user-b")
        other = self.client.get("/api/m365/preferences")
        self.assertIsNone(other.get_json()["preferences"]["timezone"])

    def test_non_subject_admin_cannot_read_or_decide_approval(self):
        approval_id = self.pending()
        self.sign_in("other-admin", roles=["Admin"])
        read = self.client.get(f"/api/m365/approvals/{approval_id}")
        decision = self.client.post(
            f"/api/m365/approvals/{approval_id}/decision",
            json={"decisions": {"email": {"duration": "no"}}},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        self.assertEqual(read.status_code, 404)
        self.assertEqual(decision.status_code, 404)
        still_pending = self.service.get_approval(approval_id, "user-a")
        self.assertEqual(still_pending["status"], "pending")

    def test_wrong_tenant_cannot_decide_even_with_same_object_id(self):
        approval_id = self.pending()
        self.sign_in("user-a", "tenant-b")
        response = self.client.post(
            f"/api/m365/approvals/{approval_id}/decision",
            json={"decisions": {"email": {"duration": "no"}}},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 403)

    def test_get_does_not_decide_and_inline_and_approvals_use_same_record(self):
        approval_id = self.pending()
        read = self.client.get(f"/api/m365/approvals/{approval_id}")
        self.assertEqual(read.get_json()["status"], "pending")
        data = {"decisions": {"email": {"duration": "today", "timezone": "America/New_York"}}}
        decided = self.client.post(
            f"/api/m365/approvals/{approval_id}/decision",
            json=data, headers={"X-M365-CSRF-Token": self.csrf},
        )
        record = self.service.get_approval(approval_id, "user-a")
        with self.app.test_request_context("/", headers={"X-M365-CSRF-Token": "csrf-test"}):
            session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}
            session["m365_csrf_token"] = "csrf-test"
            response, status = self.routes.m365_approval_decision_response(
                approvals.sanitize_m365_approval(record), "user-a", data,
            )
        self.assertEqual(decided.status_code, 200)
        self.assertTrue(decided.get_json()["transition_applied"])
        self.assertEqual(status, 200)
        self.assertFalse(response.get_json()["approval"]["transition_applied"])
        self.assertEqual(response.get_json()["execution_status"], "queued")

    def test_approvals_no_choice_does_not_inherit_legacy_comment_requirement(self):
        approval_id = self.pending()
        approval = self.service.get_approval(approval_id, "user-a")
        with self.app.test_request_context("/", headers={"X-M365-CSRF-Token": "csrf-test"}):
            session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}
            session["m365_csrf_token"] = "csrf-test"
            response, status = self.routes.m365_approval_decision_response(
                approvals.sanitize_m365_approval(approval), "user-a", {}, deny=True,
            )
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["approval"]["status"], "denied")
        tree = ast.parse((APP_DIR / "route_backend_control_center.py").read_text(encoding="utf-8"))
        for name in ("api_admin_deny_request", "api_deny_request"):
            function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
            dispatch = next(
                node for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "m365_approval_decision_response"
            )
            comment_guard = next(
                node for node in ast.walk(function)
                if isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not) and isinstance(node.test.operand, ast.Name)
                and node.test.operand.id == "comment"
            )
            self.assertLess(dispatch.lineno, comment_guard.lineno)

    def test_audit_revalidates_exact_conversation_and_has_no_credential_details(self):
        approval_id = self.pending()
        self.service.decide(approval_id, "user-a", {"decisions": {"email": {"duration": "always", "timezone": "UTC"}}})
        self.service.authorize_sources(self.context(), {"email": "always"})
        seen = []
        def authorize(user_id, conversation_id):
            seen.append((user_id, conversation_id))
            return user_id == "user-a" and conversation_id == "conversation-a"
        self.routes.configure_m365_routes(conversation_authorizer=authorize)
        forbidden = self.client.get("/api/m365/conversations/conversation-b/audit")
        allowed = self.client.get("/api/m365/conversations/conversation-a/audit")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(seen, [("user-a", "conversation-b"), ("user-a", "conversation-a")])
        self.assertNotIn("connection_id", allowed.get_data(as_text=True))
        self.assertNotIn("source_generations", allowed.get_data(as_text=True))

    def test_missing_validator_is_a_visible_dependency_not_approval_success(self):
        approval_id = self.pending()
        self.service.decision_validator = None
        response = self.client.post(
            f"/api/m365/approvals/{approval_id}/decision",
            json={"decisions": {"email": {"duration": "no"}}},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "m365_approval_validation_unavailable")

    def test_fatal_authorization_dependency_is_retryable_not_an_approval_decision(self):
        approval_id = self.pending()
        for code in (
            "m365_authorization_unavailable",
            "m365_preflight_unavailable",
            "m365_action_selection_unavailable",
        ):
            with self.subTest(code=code):
                with patch.object(
                    self.service, "decision_validator",
                    side_effect=approvals.M365PolicyError(code, "Authorization is temporarily unavailable."),
                ):
                    response = self.client.post(
                        f"/api/m365/approvals/{approval_id}/decision",
                        json={"decisions": {"email": {"duration": "no"}}},
                        headers={"X-M365-CSRF-Token": self.csrf},
                    )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json()["error"], code)
        unchanged = self.service.get_approval(approval_id, "user-a")
        self.assertEqual(unchanged["status"], "pending")

    def test_dependency_errors_do_not_reveal_sdk_or_configuration_text(self):
        with patch.object(
            self.container, "read_item",
            side_effect=exceptions.CosmosHttpResponseError(status_code=503, message="private-key-secret-connection-string"),
        ):
            response = self.client.get("/api/m365/preferences")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-key-secret-connection-string", response.get_data(as_text=True))

    def test_connection_identity_is_bound_to_current_user_and_not_request_body(self):
        invalid_connect = self.client.post(
            "/api/m365/connections/connect",
            json={"sources": ["email"], "user_id": "user-b"},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        foreign_disconnect = self.client.post(
            "/api/m365/connections/disconnect", json={"connection_id": "foreign-connection"},
            headers={"X-M365-CSRF-Token": self.csrf},
        )
        self.assertEqual(invalid_connect.status_code, 400)
        self.assertEqual(foreign_disconnect.status_code, 404)
        self.assertEqual(self.connection_container.items, {})

    def test_callbacks_use_public_https_behind_app_service_and_keep_local_development(self):
        dependencies = {
            "config": module_stub("config", LOGIN_REDIRECT_URL=None),
            "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
        }
        with patch.dict(sys.modules, dependencies):
            with self.app.test_request_context(base_url="http://simplechat.example.test"):
                deployed = self.routes._callback_uri()
            with self.app.test_request_context(base_url="http://localhost:5000"):
                local = self.routes._callback_uri()
            dependencies["config"].LOGIN_REDIRECT_URL = "https://public.example.test/getAToken"
            with self.app.test_request_context(base_url="http://internal.example.test"):
                configured = self.routes._callback_uri()
        self.assertEqual(deployed, "https://simplechat.example.test/api/m365/connections/callback")
        self.assertEqual(local, "http://localhost:5000/api/m365/connections/callback")
        self.assertEqual(configured, "https://public.example.test/api/m365/connections/callback")

    def test_stale_csrf_has_a_specific_retriable_code_without_mutating_preferences(self):
        response = self.client.patch(
            "/api/m365/preferences", json={"sources": {"email": "always"}},
            headers={"X-M365-CSRF-Token": "stale-token"},
        )
        preferences = self.service.get_preferences("user-a")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "m365_csrf_invalid")
        self.assertEqual(preferences["sources"]["email"], "ask")

    def chat_request_dependencies(self, jobs):
        config = module_stub(
            "config", LOGIN_REDIRECT_URL=None,
            cosmos_m365_execution_runs_container=jobs,
            cosmos_conversations_container=CosmosContainer("id"),
        )
        spec = importlib.util.spec_from_file_location(
            "m365_test_chat_resume", APP_DIR / "functions_m365_request_resume.py",
        )
        resume = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "config": config,
            "functions_appinsights": module_stub("functions_appinsights", log_event=Mock()),
        }):
            spec.loader.exec_module(resume)
        return {
            "config": config,
            "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
            "functions_m365_request_resume": resume,
        }

    def test_chat_connect_uses_saved_own_scopes_and_never_accepts_caller_authority(self):
        jobs = CosmosContainer("user_id")
        jobs.create_item(body={
            "id": "request", "type": "m365_execution_request",
            "user_id": "user-a", "actor_user_id": "user-a", "conversation_id": "conversation",
            "status": "awaiting_sign_in", "required_scopes": ["Files.Read.All", "Sites.Read.All"],
        })
        dependencies = self.chat_request_dependencies(jobs)
        begin = Mock(return_value={"authorization_url": "https://login.microsoftonline.com/tenant-a/authorize"})
        with patch.dict(sys.modules, dependencies), patch.object(self.connection_service, "start_chat_connection", begin):
            missing_csrf = self.client.post("/api/m365/requests/request/connect", json={})
            invalid = self.client.post(
                "/api/m365/requests/request/connect",
                json={"user_id": "user-b", "scopes": ["Mail.Send"]},
                headers={"X-M365-CSRF-Token": self.csrf},
            )
            connected = self.client.post(
                "/api/m365/requests/request/connect", json={},
                headers={"X-M365-CSRF-Token": self.csrf},
            )
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(connected.status_code, 200)
        begin.assert_called_once_with(
            "user-a", "tenant-a", "request", "conversation",
            ["Files.Read.All", "Sites.Read.All"], "http://localhost/getAToken",
        )

    def test_chat_connect_rejects_other_subjects_workflows_and_completed_requests(self):
        for changes in (
            {"actor_user_id": "other-actor"},
            {"workflow_id": "workflow"},
            {"status": "completed"},
        ):
            with self.subTest(changes=changes):
                jobs = CosmosContainer("user_id")
                jobs.create_item(body={
                    "id": "request", "type": "m365_execution_request",
                    "user_id": "user-a", "actor_user_id": "user-a", "conversation_id": "conversation",
                    "status": "awaiting_sign_in", "required_scopes": ["Files.Read.All"], **changes,
                })
                with patch.dict(sys.modules, self.chat_request_dependencies(jobs)), \
                     patch.object(self.connection_service, "start_chat_connection") as begin:
                    result = self.client.post(
                        "/api/m365/requests/request/connect", json={},
                        headers={"X-M365-CSRF-Token": self.csrf},
                    )
                self.assertIn(result.status_code, (400, 403))
                begin.assert_not_called()

    def test_chat_connect_hides_requests_owned_by_another_user(self):
        jobs = CosmosContainer("user_id")
        jobs.create_item(body={
            "id": "request", "type": "m365_execution_request",
            "user_id": "user-b", "actor_user_id": "user-b", "conversation_id": "private-conversation",
            "status": "awaiting_sign_in", "required_scopes": ["Files.Read.All"],
        })
        with patch.dict(sys.modules, self.chat_request_dependencies(jobs)), \
             patch.object(self.connection_service, "start_chat_connection") as begin:
            response = self.client.post(
                "/api/m365/requests/request/connect", json={},
                headers={"X-M365-CSRF-Token": self.csrf},
            )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private-conversation", response.get_data(as_text=True))
        begin.assert_not_called()

    def test_registered_chat_callback_returns_no_store_for_success_and_failure(self):
        for result in ("connected", "invalid"):
            with self.subTest(result=result), self.app.test_request_context(
                "/getAToken?state=m365-chat-state&code=opaque",
            ):
                session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}
                with patch.object(self.routes, "_complete_chat_connection") as complete:
                    if result == "connected":
                        complete.return_value = self.app.response_class(status=302, headers={"Location": "/chats"})
                    else:
                        complete.side_effect = approvals.M365PolicyError("m365_auth_state_invalid", "Connect again.")
                    response = self.routes.complete_m365_chat_connection_callback()
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")
                self.assertEqual(response.headers["Pragma"], "no-cache")
                self.assertEqual(response.status_code, 302 if result == "connected" else 400)

    def test_chat_callback_returns_to_original_visible_conversation_without_running_a_request(self):
        jobs = CosmosContainer("user_id")
        jobs.create_item(body={
            "id": "request", "type": "m365_execution_request",
            "user_id": "user-a", "actor_user_id": "user-a", "conversation_id": "backing-conversation",
            "status": "awaiting_sign_in",
        })
        dependencies = self.chat_request_dependencies(jobs)
        authorize = Mock(return_value=(
            {"id": "backing-conversation"}, {"collaboration_conversation_id": "visible-conversation"}, {},
        ))
        dependencies["functions_m365_runtime"] = module_stub(
            "functions_m365_runtime", _conversation_access=authorize,
        )
        with patch.dict(sys.modules, dependencies), patch.object(
            self.connection_service, "complete_chat_connection",
            return_value={"request_id": "request", "conversation_id": "backing-conversation"},
        ) as complete:
            result = self.client.get("/api/m365/connections/callback?state=m365-chat-state&code=opaque")
        self.assertEqual(result.status_code, 302)
        self.assertEqual(
            result.headers["Location"],
            "/chats?conversationId=visible-conversation&m365_request_id=request&m365_auth=connected",
        )
        complete.assert_called_once_with("user-a", "tenant-a", {"state": "m365-chat-state", "code": "opaque"})
        authorize.assert_called_once_with("user-a", "backing-conversation")
        saved = jobs.read_item("request", "user-a")
        self.assertEqual(saved["status"], "awaiting_sign_in")

    def test_connection_profile_and_approval_responses_are_not_cached(self):
        for path in ("/api/m365/preferences", "/api/m365/connections", "/api/m365/chat/connection"):
            response = self.client.get(path)
            self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_profile_chat_reconnect_uses_current_subject_sources_and_fixed_callback(self):
        dependencies = {
            "config": module_stub("config", LOGIN_REDIRECT_URL=None),
            "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
        }
        begin = Mock(return_value={"authorization_url": "https://login.microsoftonline.com/tenant-a/authorize"})
        with patch.dict(sys.modules, dependencies), patch.object(self.connection_service, "start_profile_chat_connection", begin):
            missing = self.client.post("/api/m365/chat/connection/connect", json={"sources": ["spo"]})
            for payload in ({"sources": ["spo"], "user_id": "user-b"}, {"sources": ["spo"], "redirect_uri": "https://foreign.test"}, {"scopes": ["Mail.Send"]}):
                invalid = self.client.post(
                    "/api/m365/chat/connection/connect", json=payload,
                    headers={"X-M365-CSRF-Token": self.csrf},
                )
                self.assertEqual(invalid.status_code, 400)
            valid = self.client.post(
                "/api/m365/chat/connection/connect", json={"sources": ["spo", "email"]},
                headers={"X-M365-CSRF-Token": self.csrf},
            )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(valid.status_code, 200)
        begin.assert_called_once_with("user-a", "tenant-a", ["spo", "email"], "http://localhost/getAToken")
        self.assertEqual(self.connection_container.items, {})

    def test_profile_callback_does_not_read_or_replay_any_chat_request(self):
        jobs = CosmosContainer("user_id")
        dependencies = self.chat_request_dependencies(jobs)
        resume = Mock(side_effect=AssertionError("Profile reconnect must not resume past requests."))
        dependencies["functions_m365_request_resume"].get_m365_chat_request = resume
        dependencies["functions_m365_runtime"] = module_stub("functions_m365_runtime", _conversation_access=resume)
        with patch.dict(sys.modules, dependencies), patch.object(
            self.connection_service, "complete_chat_connection", return_value={"return_to": "profile"},
        ):
            response = self.client.get("/api/m365/connections/callback?state=m365-chat-validstate&code=opaque")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/profile?tab=settings&m365_chat_connection=connected#m365-chat-connection")
        self.assertEqual(jobs.items, {})
        resume.assert_not_called()

    def test_profile_chat_connection_is_private_and_does_not_expose_cache_contents(self):
        self.set_session({
            "user": {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]},
            "token_cache": "private-corrupted-token-material",
        })
        response = self.client.get("/api/m365/chat/connection")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["connection"], {"status": "reconnect_required", "sources": []})
        self.assertNotIn("private-corrupted", response.get_data(as_text=True))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.set_session({})
        anonymous = self.client.get("/api/m365/chat/connection")
        self.assertEqual(anonymous.status_code, 401)

    def test_verified_workflow_reconnect_clears_an_interactive_rejection_marker(self):
        with self.app.test_request_context():
            session["token_cache"] = "old-cache"
            session[connections.CHAT_RECONNECT_SESSION_KEY] = {"user_id": "user-a", "tenant_id": "tenant-a"}
            self.routes._publish_verified_workflow_cache_to_session("verified-cache")
            cached = session["token_cache"]
            marker = session.get(connections.CHAT_RECONNECT_SESSION_KEY)
        self.assertEqual(cached, "verified-cache")
        self.assertIsNone(marker)

    def test_real_notification_helper_only_targets_subject_and_deduplicates(self):
        notification_container = CosmosContainer("user_id")
        logger = Mock()
        spec = importlib.util.spec_from_file_location(
            "m365_test_notifications", APP_DIR / "functions_notifications.py",
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "config": module_stub("config", cosmos_notifications_container=notification_container),
            "functions_appinsights": module_stub("functions_appinsights", log_event=logger),
            "functions_group": module_stub("functions_group", find_group_by_id=lambda value: None),
            "functions_debug": module_stub("functions_debug", debug_print=lambda *args, **kwargs: None),
            "functions_public_workspaces": module_stub(
                "functions_public_workspaces",
                find_public_workspace_by_id=lambda value: None, get_user_public_workspaces=lambda value: [],
            ),
        }):
            spec.loader.exec_module(module)
        approval_id = self.pending()
        approval = self.service.get_approval(approval_id, "user-a")
        first = module.create_m365_approval_notification(approval)
        second = module.create_m365_approval_notification(approval)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(notification_container.items), 1)
        self.assertEqual(first["user_id"], "user-a")
        self.assertEqual(first["scope"], "personal")
        self.assertEqual(first["link_url"], f"/approvals?m365_approval={approval_id}")
        self.assertIsNone(first["assignment"])
        self.assertIsNone(first["group_id"])
        self.assertNotIn("context", first["metadata"])
        updated = module.create_m365_approval_notification({**approval, "status": "approved"})
        self.assertEqual(len(notification_container.items), 1)
        self.assertEqual(updated["metadata"]["status"], "approved")
        self.assertEqual(updated["link_url"], first["link_url"])
        repeated = module.create_m365_approval_notification({**approval, "status": "approved"})
        self.assertEqual(repeated["id"], updated["id"])
        self.assertEqual(len(notification_container.items), 1)
        logger.assert_not_called()
        for operation in ("create_item", "delete_item"):
            for status in (403, 429, 500):
                with self.subTest(operation=operation, status=status), patch.object(
                    notification_container, operation,
                    side_effect=exceptions.CosmosHttpResponseError(status_code=status),
                ):
                    failed = module.create_m365_approval_notification({**approval, "status": "approved"})
                self.assertIsNone(failed)
        self.assertEqual(logger.call_count, 6)
        cancel_id = self.pending(request_id="cancel-request")
        cancel_record = self.service.get_approval(cancel_id, "user-a")
        module.create_m365_approval_notification(cancel_record)
        module.create_m365_approval_notification({**cancel_record, "status": "cancelled"})
        statuses = [
            item["metadata"]["status"] for item in notification_container.items.values()
            if item["metadata"]["approval_id"] == cancel_id
        ]
        self.assertEqual(statuses, ["cancelled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
