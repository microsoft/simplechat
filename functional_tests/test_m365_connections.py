# test_m365_connections.py
"""
Functional tests for encrypted Microsoft 365 workflow connections.
Version: 0.261.034
Implemented in: 0.261.029

Uses real MSAL authorization-code/cache logic with a scoped HTTP fake, real
AES-GCM, and conditional Cosmos fakes. Covers state/nonce/PKCE, wrong and guest
accounts, key rotation/corruption, refresh races, disconnect fencing, and
explicit workflow binding without owner/caller/application-token fallback.
"""

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

import msal
from flask import Flask, session


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

# The application source-path setup is intentionally test-local.
import functions_m365_approvals as approvals
import functions_m365_connections as connections
import functions_m365_execution as execution
from test_support.m365 import Clock, CosmosContainer, Notifications, WORKFLOW_REVIEW


def encoded_json(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode("utf-8")).decode("ascii").rstrip("=")


class HttpResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.headers = {}
        self.text = json.dumps(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("Unexpected HTTP failure.")


class MsalHttp:
    """No network: supplies issuer metadata and a token-endpoint response."""

    def __init__(self, config):
        self.config = config
        self.nonce = None
        self.claim_overrides = {}
        self.error = None
        self.posts = []
        self.refresh_token = True
        self.home_user = "user-a"
        self.home_tenant = config.tenant_id
        self.scope_transform = lambda scopes: scopes

    def get(self, url, **kwargs):
        if "/.well-known/openid-configuration" not in url:
            raise AssertionError(f"Unexpected MSAL metadata URL: {urlsplit(url).path}")
        return HttpResponse({
            "authorization_endpoint": f"{self.config.authority}/oauth2/v2.0/authorize",
            "token_endpoint": f"{self.config.authority}/oauth2/v2.0/token",
            "issuer": f"{self.config.authority}/v2.0",
            "jwks_uri": f"{self.config.authority}/discovery/v2.0/keys",
            "response_types_supported": ["code"],
            "subject_types_supported": ["pairwise"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "tenant_region_scope": "NA",
        })

    def post(self, url, data=None, **kwargs):
        self.posts.append(copy.deepcopy(data))
        if self.error:
            return HttpResponse(self.error, status=400)
        now = int(time.time())
        claims = {
            "aud": self.config.client_id, "iss": f"{self.config.authority}/v2.0",
            "iat": now, "nbf": now - 60, "exp": now + 3600,
            "oid": "user-a", "tid": self.config.tenant_id, "sub": "subject-a",
            "preferred_username": "user-a@example.test", "name": "Test User",
            "nonce": self.nonce, **self.claim_overrides,
        }
        payload = {
            "access_token": "access-token-must-stay-server-side",
            "id_token": f"{encoded_json({'alg': 'none'})}.{encoded_json(claims)}.",
            "client_info": encoded_json({"uid": self.home_user, "utid": self.home_tenant}),
            "token_type": "Bearer", "expires_in": 3600,
            "scope": self.scope_transform(data.get("scope", "")),
        }
        if self.refresh_token:
            payload["refresh_token"] = "refresh-token-must-stay-server-side"
        return HttpResponse(payload)


class M365ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.config = connections.M365IdentityConfig(
            client_id="client-a", tenant_id="tenant-a",
            authority="https://login.microsoftonline.com/tenant-a",
            graph_resource="https://graph.microsoft.com", cloud="azurecloud",
        )
        self.keys = {
            "version1": connections.M365EncryptionKey(b"a" * 32, "version1", "workflow-token-key"),
            "version2": connections.M365EncryptionKey(b"b" * 32, "version2", "workflow-token-key"),
        }
        self.active_key = "version1"
        self.clock = Clock()
        self.container = CosmosContainer("user_id")
        self.http = MsalHttp(self.config)
        self.clients = []
        self.service = connections.M365ConnectionService(
            container_factory=lambda: self.container,
            key_provider=self.key_provider, config_provider=lambda: self.config,
            msal_factory=self.msal_factory, clock=self.clock,
            workflow_authorizer=execution.validate_m365_workflow_context,
        )
        self.approvals = approvals.M365ApprovalService(
            container_factory=lambda: self.approval_container,
            notification_sender=Notifications(), decision_validator=lambda approval: True,
            clock=self.clock,
        )
        self.approval_container = CosmosContainer()
        for target, name, value in (
            (connections, "_service", self.service),
            (connections, "_log_failure", lambda *args, **kwargs: None),
            (approvals, "_service", self.approvals),
            (execution, "_workflow_validator", lambda context: True),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def key_provider(self, version=None, name=None):
        if name is not None and name != "workflow-token-key":
            raise connections.M365ConnectionError("m365_key_unavailable", "The key is unavailable.")
        key = self.keys.get(version or self.active_key)
        if key is None:
            raise connections.M365ConnectionError("m365_key_unavailable", "The key is unavailable.")
        return key

    def msal_factory(self, cache, config):
        client = msal.ConfidentialClientApplication(
            config.client_id, authority=config.authority, token_cache=cache,
            client_credential="unit-test-only", http_client=self.http,
            instance_discovery=False,
        )
        self.clients.append(client)
        return client

    def begin(self, sources=None, scopes=None):
        result = self.service.start_connection(
            "user-a", "tenant-a", sources or ["email"],
            f"https://simplechat.example.test{connections.CONNECTION_CALLBACK_PATH}",
            "session-binding-for-user-a", scopes=scopes,
        )
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        self.http.nonce = query["nonce"][0]
        return result, query

    def connect(self, sources=None, scopes=None):
        started, query = self.begin(sources, scopes)
        connected = self.service.complete_connection(
            "user-a", "tenant-a", {"state": query["state"][0], "code": "one-use-code"},
            "session-binding-for-user-a",
        )
        return connected, started, query

    def workflow(self, connected, sources=None, approve=True):
        ctx = execution.M365ExecutionContext(
            actor_user_id="workflow-owner", data_user_id="user-a", tenant_id="tenant-a",
            conversation_id="conversation-a", shared=False, request_id="request-a",
            workflow_id="workflow-a", workflow_fingerprint="material-revision-a",
            connection_id=connected["id"], run_id="run-a",
            action_configs={"action-a": {"source": "email"}},
        )
        binding = self.approvals.create_workflow_binding(
            ctx, sources or ["email"], connected, review=WORKFLOW_REVIEW,
        )
        if approve:
            self.approvals.decide(binding["id"], "user-a", {"choice": "approve"})
        return replace(ctx, binding_id=binding["id"])

    def test_real_msal_code_flow_has_state_nonce_pkce_and_encrypted_cache(self):
        connected, started, query = self.connect()
        raw = self.container.read_item(connected["id"], "user-a")
        key = self.key_provider(raw["encrypted_cache"]["key_version"])
        plaintext = connections.decrypt_m365_cache(raw["encrypted_cache"], raw, key)
        self.assertEqual(connected["status"], "connected")
        self.assertEqual(connected["generation"], 1)
        self.assertIn("offline_access", query["scope"][0].split())
        self.assertEqual(query["code_challenge_method"], ["S256"])
        verifier = self.http.posts[-1]["code_verifier"]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        self.assertEqual(query["code_challenge"], [challenge])
        self.assertIn("refresh-token-must-stay-server-side", plaintext)
        self.assertNotIn("refresh-token-must-stay-server-side", json.dumps(list(self.container.items.values())))
        self.assertNotIn("access-token-must-stay-server-side", json.dumps(connected))
        self.assertNotIn("encrypted_cache", connected)
        self.assertEqual(self.approval_container.items, {})

    def test_crypto_rejects_corruption_wrong_key_and_every_account_binding_field(self):
        connected, _started, _query = self.connect()
        raw = self.container.read_item(connected["id"], "user-a")
        original = raw["encrypted_cache"]
        for field_name in connections._BINDING_FIELDS:
            with self.subTest(field=field_name):
                wrong = {**raw, field_name: f"wrong-{field_name}"}
                with self.assertRaises(connections.M365ConnectionError):
                    connections.decrypt_m365_cache(original, wrong, self.keys["version1"])
        for field_name in ("ciphertext", "nonce", "key_name", "key_version", "version"):
            corrupted = {**original, field_name: "corrupted"}
            with self.subTest(envelope_field=field_name):
                with self.assertRaises(connections.M365ConnectionError):
                    connections.decrypt_m365_cache(corrupted, raw, self.keys["version1"])
        same_version_wrong_key = connections.M365EncryptionKey(b"c" * 32, "version1", "workflow-token-key")
        with self.assertRaises(connections.M365ConnectionError):
            connections.decrypt_m365_cache(original, raw, same_version_wrong_key)

    def test_replay_state_and_session_binding_are_rejected(self):
        _connected, _started, query = self.connect()
        before = len(self.http.posts)
        with self.assertRaises(connections.M365ConnectionError):
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "replayed"},
                "session-binding-for-user-a",
            )
        _started, fresh_query = self.begin()
        with self.assertRaises(connections.M365ConnectionError):
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": fresh_query["state"][0], "code": "stolen"},
                "different-browser-session",
            )
        self.assertEqual(len(self.http.posts), before)

    def test_msal_nonce_validation_is_not_a_stub(self):
        _started, query = self.begin()
        self.http.claim_overrides = {"nonce": "wrong-nonce"}
        with self.assertRaises(connections.M365ConnectionError) as failure:
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "nonce-test"},
                "session-binding-for-user-a",
            )
        self.assertEqual(failure.exception.code, "m365_auth_validation_failed")

    def test_wrong_oid_wrong_tenant_and_guest_are_rejected(self):
        for claims in ({"oid": "user-b"}, {"tid": "tenant-b"}, {"acct": 1}):
            with self.subTest(claims=claims):
                self.http.claim_overrides = claims
                _started, query = self.begin()
                with self.assertRaises(connections.M365ConnectionError) as failure:
                    self.service.complete_connection(
                        "user-a", "tenant-a", {"state": query["state"][0], "code": "wrong-account"},
                        "session-binding-for-user-a",
                    )
                self.assertEqual(failure.exception.code, "m365_account_mismatch")
        self.http.claim_overrides = {}
        self.http.home_tenant = "home-tenant-b"
        _started, query = self.begin()
        with self.assertRaises(connections.M365ConnectionError):
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "guest-home"},
                "session-binding-for-user-a",
            )

    def test_expired_flow_and_disconnect_during_flow_never_exchange_code(self):
        started, query = self.begin()
        self.clock.advance(seconds=connections.AUTH_FLOW_SECONDS)
        with self.assertRaises(connections.M365ConnectionError):
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "expired"},
                "session-binding-for-user-a",
            )
        started, query = self.begin()
        self.service.disconnect(started["connection_id"], "user-a", "tenant-a")
        with self.assertRaises(connections.M365ConnectionError):
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "disconnected"},
                "session-binding-for-user-a",
            )
        self.assertEqual(self.http.posts, [])

    def test_oauth_error_is_safe_and_offline_consent_required(self):
        _started, query = self.begin()
        self.http.error = {"error": "access_denied", "error_description": "sensitive-provider-diagnostics"}
        with self.assertRaises(connections.M365ConnectionError) as failure:
            self.service.complete_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "denied"},
                "session-binding-for-user-a",
            )
        self.assertNotIn("sensitive-provider-diagnostics", json.dumps(failure.exception.payload))
        self.http.error = None
        self.http.refresh_token = False
        with self.assertRaises(connections.M365ConnectionError) as offline:
            self.connect()
        self.assertEqual(offline.exception.code, "m365_offline_consent_required")

    def test_connection_never_grants_workflow_authorization(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected, approve=False)
        with self.assertRaises(approvals.M365ApprovalRequired) as pending:
            connections.get_m365_access_token(["Mail.Read"], context=ctx)
        self.assertEqual(pending.exception.request_type, approvals.TYPE_WORKFLOW_RUN_AS)
        no_binding = connections.get_m365_access_token(["Mail.Read"], context=replace(ctx, binding_id=None))
        self.assertNotIn("access_token", no_binding)
        self.assertEqual(no_binding["error"], "m365_run_as_required")
        no_context = connections.get_m365_access_token(["Mail.Read"])
        self.assertEqual(no_context["error"], "not_logged_in")
        no_run = connections.get_m365_access_token(["Mail.Read"], context=replace(ctx, run_id=None))
        self.assertEqual(no_run["error"], "m365_run_context_required")

    def test_missing_or_malformed_authorizer_fails_before_credentials_or_storage(self):
        ctx = execution.M365ExecutionContext(
            "workflow-owner", "user-a", "tenant-a",
            request_id="request-a", workflow_id="workflow-a", run_id="run-a",
            workflow_fingerprint="revision-a", connection_id="connection-a", binding_id="binding-a",
        )
        invalid_results = (
            None, True, {}, {"binding": None}, {"binding": {}},
            {"binding": {"sources": []}}, {"binding": {"sources": "email"}},
            {"binding": {"sources": ["unknown"]}}, {"binding": {"sources": [{}]}},
        )
        callbacks = [None, object(), *(Mock(return_value=value) for value in invalid_results)]
        for callback in callbacks:
            with self.subTest(callback=callback):
                io = Mock(side_effect=AssertionError("Unconfigured authorization reached an I/O dependency."))
                service = connections.M365ConnectionService(
                    container_factory=io, key_provider=io, config_provider=io, msal_factory=io,
                    workflow_authorizer=callback,
                )
                with patch.object(connections, "_service", service):
                    result = connections.get_m365_access_token(["Mail.Read"], context=ctx)
                self.assertEqual(result["error"], "m365_authorization_unavailable")
                self.assertNotIn("access_token", result)
                io.assert_not_called()

    def test_owner_wiring_preserves_service_dependencies_and_rejects_missing_callback(self):
        with patch.object(self.service, "workflow_authorizer", None):
            connections.configure_m365_connection_authorization(execution.validate_m365_workflow_context)
            configured = connections.get_m365_connection_service()
            self.assertIs(configured, self.service)
            self.assertIs(configured.workflow_authorizer, execution.validate_m365_workflow_context)
            with self.assertRaises(TypeError):
                connections.configure_m365_connection_authorization(None)
            self.assertIs(configured.workflow_authorizer, execution.validate_m365_workflow_context)

    def test_live_authorization_runs_before_and_after_refresh(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        events = []
        original_factory = self.service.msal_factory

        def authorize(context):
            events.append("authorize")
            return execution.validate_m365_workflow_context(context)

        def refresh(cache, config):
            events.append("refresh")
            return original_factory(cache, config)

        self.service.workflow_authorizer = authorize
        self.service.msal_factory = refresh
        result = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        self.assertIn("access_token", result)
        self.assertEqual(events, ["authorize", "refresh", "authorize"])

    def test_binding_revoked_during_refresh_never_releases_the_acquired_token(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        original_factory = self.service.msal_factory

        def revoke_during_refresh(cache, config):
            client = original_factory(cache, config)
            original_acquire = client.acquire_token_silent_with_error

            def acquire(*args, **kwargs):
                token = original_acquire(*args, **kwargs)
                self.approvals.revoke_workflow_binding(ctx.binding_id, ctx.data_user_id)
                return token

            client.acquire_token_silent_with_error = acquire
            return client

        self.service.msal_factory = revoke_during_refresh
        result = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        saved = self.container.read_item(connected["id"], "user-a")
        self.assertEqual(result["error"], "m365_run_as_invalid")
        self.assertNotIn("access_token", result)
        self.assertIsNone(saved["refresh_lease"])

    def test_manual_or_scheduled_context_uses_only_approved_data_user(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        token = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        self.assertEqual(token, {"access_token": "access-token-must-stay-server-side"})
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        with app.test_request_context("/"):
            session["user"] = {"oid": "triggering-user", "tid": "tenant-a", "roles": ["Admin"]}
            result = connections.get_m365_access_token(["Mail.Read"], context=ctx)
            current = dict(session["user"])
        self.assertIn("access_token", result)
        self.assertEqual(current["oid"], "triggering-user")
        wrong = connections.get_m365_access_token(["Mail.Read"], context=replace(ctx, data_user_id="user-b"))
        self.assertNotIn("access_token", wrong)

    def test_workflow_source_and_material_revision_limit_token_access(self):
        connected, _started, _query = self.connect(["calendar", "email"])
        ctx = self.workflow(connected, sources=["calendar"])
        denied = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        self.assertEqual(denied["error"], "m365_binding_scope_mismatch")
        changed = connections.get_m365_access_token(["Calendars.Read"], context=replace(ctx, workflow_fingerprint="changed"))
        self.assertNotIn("access_token", changed)
        with patch.object(execution, "_workflow_validator", lambda context: False):
            access_revoked = connections.get_m365_access_token(["Calendars.Read"], context=ctx)
        self.assertEqual(access_revoked["error"], "m365_workflow_not_authorized")

    def test_disconnect_during_refresh_cannot_resurrect_cache(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        original_factory = self.service.msal_factory
        def racing_factory(cache, config):
            client = original_factory(cache, config)
            original_acquire = client.acquire_token_silent_with_error
            def acquire(*args, **kwargs):
                result = original_acquire(*args, **kwargs)
                self.service.disconnect(connected["id"], "user-a", "tenant-a")
                return result
            client.acquire_token_silent_with_error = acquire
            return client
        self.service.msal_factory = racing_factory
        result = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        raw = self.container.read_item(connected["id"], "user-a")
        self.assertNotIn("access_token", result)
        self.assertEqual(raw["status"], "disconnected")
        self.assertIsNone(raw["encrypted_cache"])
        self.assertGreater(raw["generation"], connected["generation"])

    def test_parallel_refreshes_use_a_conditional_lease(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        entered = threading.Event()
        release = threading.Event()
        original_factory = self.service.msal_factory
        def slow_factory(cache, config):
            client = original_factory(cache, config)
            original_acquire = client.acquire_token_silent_with_error
            def acquire(*args, **kwargs):
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("Refresh was not released.")
                return original_acquire(*args, **kwargs)
            client.acquire_token_silent_with_error = acquire
            return client
        self.service.msal_factory = slow_factory
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(connections.get_m365_access_token, ["Mail.Read"], ctx)
            entered_ok = entered.wait(timeout=5)
            second = connections.get_m365_access_token(["Mail.Read"], context=ctx)
            release.set()
            first_result = first.result(timeout=5)
        self.assertTrue(entered_ok)
        self.assertEqual(second["error"], "m365_connection_busy")
        self.assertIn("access_token", first_result)

    def test_key_rotation_uses_version_binding_without_reauthorizing_workflow(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        self.active_key = "version2"
        rotated = self.service.rotate_connection_key(connected["id"], "user-a", "tenant-a")
        raw = self.container.read_item(connected["id"], "user-a")
        self.assertEqual(raw["encrypted_cache"]["key_version"], "version2")
        self.assertEqual(rotated["generation"], connected["generation"])
        del self.keys["version1"]
        result = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        self.assertIn("access_token", result)

    def test_reconnect_invalidates_old_binding_generation(self):
        connected, _started, _query = self.connect()
        ctx = self.workflow(connected)
        reconnected, _started, _query = self.connect()
        old = connections.get_m365_access_token(["Mail.Read"], context=ctx)
        self.assertGreater(reconnected["generation"], connected["generation"])
        self.assertNotIn("access_token", old)

    def test_direct_session_exact_account_no_first_account_or_connection_fallback(self):
        connected, _started, _query = self.connect()
        raw = self.container.read_item(connected["id"], "user-a")
        cache = connections.decrypt_m365_cache(raw["encrypted_cache"], raw, self.keys["version1"])
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        ctx = execution.M365ExecutionContext("user-a", "user-a", "tenant-a", request_id="direct-request")
        with app.test_request_context("/"):
            session["user"] = {"oid": "user-a", "tid": "tenant-a"}
            session["token_cache"] = cache
            direct = connections.get_m365_access_token(["Mail.Read"], context=ctx)
            legacy_security = connections.get_m365_access_token(["SecurityEvents.Read.All"], context=ctx)
            session["user"]["oid"] = "user-b"
            mismatched = connections.get_m365_access_token(["Mail.Read"], context=ctx)
            no_match = connections.get_m365_access_token(["Mail.Read"])
        self.assertIn("access_token", direct)
        self.assertIn("access_token", legacy_security)
        self.assertEqual(mismatched["error"], "m365_principal_mismatch")
        self.assertEqual(no_match["error"], "m365_account_mismatch")

    def test_missing_workflow_scopes_return_safe_reconnect_requirements(self):
        connected, _started, _query = self.connect(scopes=["Mail.Read"])
        ctx = self.workflow(connected)
        missing = connections.get_m365_access_token(["Mail.Send"], context=ctx)
        self.assertEqual(missing["error"], "m365_consent_required")
        self.assertEqual(missing["scopes"], ["Mail.Send"])
        self.assertEqual(missing["profile_url"], "/profile")
        self.assertNotIn("access_token", missing)
        with self.assertRaises(ValueError):
            self.service.start_connection(
                "user-a", "tenant-a", ["email"],
                f"https://simplechat.example.test{connections.CONNECTION_CALLBACK_PATH}",
                "session-binding-for-user-a", scopes=["SecurityEvents.Read.All"],
            )

    def test_source_selection_includes_all_supported_operations_without_extra_checkboxes(self):
        expected = {
            "calendar": {"Calendars.Read", "Calendars.ReadWrite", "MailboxSettings.Read", "User.ReadBasic.All"},
            "email": {"Mail.Read", "Mail.ReadWrite", "Mail.Send", "User.ReadBasic.All"},
            "onedrive": {"Files.Read.All", "Sites.Read.All"},
            "spo": {"Files.Read.All", "Sites.Read.All"},
        }
        for source, scopes in expected.items():
            with self.subTest(source=source):
                _started, query = self.begin([source])
                granted = {value.rsplit("/", 1)[-1] for value in query["scope"][0].split()}
                self.assertTrue(scopes.issubset(granted))
                if source in {"onedrive", "spo"}:
                    self.assertNotIn("Mail.Send", granted)
                    self.assertNotIn("Calendars.ReadWrite", granted)

    def begin_chat(self):
        session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}
        result = self.service.start_chat_connection(
            "user-a", "tenant-a", "chat-request", "chat-conversation",
            ["User.Read", "Files.Read.All", "Sites.Read.All"],
            f"https://simplechat.example.test{connections.CHAT_CALLBACK_PATH}",
        )
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        self.http.nonce = query["nonce"][0]
        return result, query

    def test_chat_connection_uses_real_pkce_and_session_cache_without_workflow_storage_or_key_vault(self):
        self.service.key_provider = Mock(side_effect=AssertionError("Interactive chat does not require Key Vault."))
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        with app.test_request_context():
            started, query = self.begin_chat()
            original_user = copy.deepcopy(session["user"])
            completed = self.service.complete_chat_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "chat-code"},
            )
            cached = session["token_cache"]
            current_user = copy.deepcopy(session["user"])
            flow_present = connections.CHAT_AUTH_SESSION_KEY in session
            token = connections.get_m365_access_token(["Files.Read.All"], include_auth_url=False)
            with self.assertRaises(connections.M365ConnectionError) as replay:
                self.service.complete_chat_connection(
                    "user-a", "tenant-a", {"state": query["state"][0], "code": "chat-code"},
                )
        self.assertEqual(completed, {"request_id": "chat-request", "conversation_id": "chat-conversation"})
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(query["state"][0].startswith(connections.CHAT_AUTH_STATE_PREFIX))
        self.assertIn("code_verifier", self.http.posts[0])
        self.assertIn("refresh-token-must-stay-server-side", cached)
        self.assertNotIn("access-token-must-stay-server-side", json.dumps(started))
        self.assertNotIn("access-token-must-stay-server-side", json.dumps(completed))
        self.assertIn("access_token", token)
        self.assertEqual(current_user, original_user)
        self.assertFalse(flow_present)
        self.assertEqual(replay.exception.code, "m365_auth_state_invalid")
        self.assertEqual(self.container.items, {})
        self.assertEqual(self.approval_container.items, {})
        self.service.key_provider.assert_not_called()

    def test_profile_reconnect_repairs_interactive_cache_without_a_saved_request_or_workflow(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        self.service.key_provider = Mock(side_effect=AssertionError("Profile chat reconnect must not use Key Vault."))
        with app.test_request_context():
            session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"], "name": "Original user"}
            session["token_cache"] = "broken-cache"
            original_user = copy.deepcopy(session["user"])
            status_before = self.service.read_chat_connection("user-a", "tenant-a")
            begin = self.service.start_profile_chat_connection(
                "user-a", "tenant-a", ["spo"], f"https://simplechat.example.test{connections.CHAT_CALLBACK_PATH}",
            )
            query = parse_qs(urlsplit(begin["authorization_url"]).query)
            self.http.nonce = query["nonce"][0]
            cache_before_callback = session["token_cache"]
            completed = self.service.complete_chat_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "profile-chat-code"},
            )
            status_after = self.service.read_chat_connection("user-a", "tenant-a")
            user_after = dict(session["user"])
            metadata = session[connections.CHAT_CONNECTION_SESSION_KEY]
        self.assertEqual(status_before["status"], "reconnect_required")
        self.assertEqual(cache_before_callback, "broken-cache")
        self.assertEqual(completed, {"return_to": "profile"})
        self.assertEqual(status_after["status"], "available")
        self.assertEqual(status_after["sources"], ["spo"])
        self.assertIn("connected_at", status_after)
        self.assertEqual(original_user, user_after)
        self.assertNotIn("request_id", metadata)
        self.assertEqual(self.container.items, {})
        self.assertEqual(self.approval_container.items, {})
        self.assertNotIn("access-token", json.dumps(status_after))
        self.assertNotIn("refresh-token", json.dumps(status_after))
        self.service.key_provider.assert_not_called()

    def test_failed_profile_reconnect_preserves_previous_sign_in_and_reconnect_marker(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        context = execution.M365ExecutionContext("user-a", "user-a", "tenant-a", request_id="request")
        with app.test_request_context():
            _begin, query = self.begin_chat()
            self.service.complete_chat_connection("user-a", "tenant-a", {"state": query["state"][0], "code": "first"})
            previous_cache = session["token_cache"]
            connections.mark_m365_chat_reconnect_required(context)
            blocked = connections.get_m365_access_token(["Files.Read.All"], context=context)
            clients_before = len(self.clients)
            self.service.read_chat_connection("user-a", "tenant-a")
            self.assertEqual(len(self.clients), clients_before)
            reconnect = self.service.start_profile_chat_connection(
                "user-a", "tenant-a", ["spo"], f"https://simplechat.example.test{connections.CHAT_CALLBACK_PATH}",
            )
            query = parse_qs(urlsplit(reconnect["authorization_url"]).query)
            self.http.nonce = query["nonce"][0]
            self.http.claim_overrides = {"oid": "different-user"}
            with self.assertRaises(connections.M365ConnectionError):
                self.service.complete_chat_connection(
                    "user-a", "tenant-a", {"state": query["state"][0], "code": "wrong-user"},
                )
            cached = session["token_cache"]
            failed_status = self.service.read_chat_connection("user-a", "tenant-a")
            self.http.claim_overrides = {}
            reconnect = self.service.start_profile_chat_connection(
                "user-a", "tenant-a", ["spo"], f"https://simplechat.example.test{connections.CHAT_CALLBACK_PATH}",
            )
            query = parse_qs(urlsplit(reconnect["authorization_url"]).query)
            self.http.nonce = query["nonce"][0]
            self.service.complete_chat_connection(
                "user-a", "tenant-a", {"state": query["state"][0], "code": "renewed"},
            )
            renewed = connections.get_m365_access_token(["Files.Read.All"], context=context)
            marker = session.get(connections.CHAT_RECONNECT_SESSION_KEY)
        self.assertEqual(blocked["error"], "m365_reconnect_required")
        self.assertEqual(cached, previous_cache)
        self.assertEqual(failed_status["status"], "reconnect_required")
        self.assertIn("access_token", renewed)
        self.assertIsNone(marker)

    def test_chat_reconnect_marker_never_fences_a_workflow_or_another_principal(self):
        connected, _started, _query = self.connect()
        workflow = self.workflow(connected)
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        with app.test_request_context():
            session["user"] = {"oid": "user-a", "tid": "tenant-a"}
            connections.mark_m365_chat_reconnect_required(workflow)
            after_workflow = session.get(connections.CHAT_RECONNECT_SESSION_KEY)
            other = execution.M365ExecutionContext("other", "other", "tenant-a", request_id="other")
            connections.mark_m365_chat_reconnect_required(other)
            after_other = session.get(connections.CHAT_RECONNECT_SESSION_KEY)
            own = execution.M365ExecutionContext("user-a", "user-a", "tenant-a", request_id="own")
            connections.mark_m365_chat_reconnect_required(own)
            result = connections.get_m365_access_token(["Mail.Read"], context=workflow)
        self.assertIsNone(after_workflow)
        self.assertIsNone(after_other)
        self.assertIn("access_token", result)

    def test_profile_reconnect_validates_sources_before_any_auth_or_storage_io(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        for sources in (None, [], ["unknown"], [{}], "spo", ["spo"] * 5):
            with self.subTest(sources=sources), app.test_request_context():
                session["user"] = {"oid": "user-a", "tid": "tenant-a"}
                with self.assertRaises(connections.M365ConnectionError) as raised:
                    self.service.start_profile_chat_connection(
                        "user-a", "tenant-a", sources,
                        f"https://simplechat.example.test{connections.CHAT_CALLBACK_PATH}",
                    )
                self.assertEqual(raised.exception.code, "m365_sources_invalid")
        self.assertEqual(self.clients, [])
        self.assertEqual(self.container.items, {})

    def test_callbacks_accept_previously_consented_scope_supersets_in_every_cloud(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        configurations = (
            self.config,
            connections.M365IdentityConfig(
                "client-a", "tenant-a", "https://login.microsoftonline.us/tenant-a",
                "https://graph.microsoft.us", "usgovernment",
            ),
            connections.M365IdentityConfig(
                "client-a", "tenant-a", "https://identity.example.test/tenant-a",
                "https://graph.example.test:8443/graph", "custom",
            ),
        )
        for config in configurations:
            self.config = self.http.config = config
            for qualified in (False, True):
                def scope_superset(requested):
                    names = [scope.rsplit("/", 1)[-1] for scope in requested.split()]
                    names += ["User.ReadWrite", "Directory.Read.All", "Tasks.Read", "Mail.Send"]
                    names += [f"PreviouslyGranted.Permission{index}" for index in range(35)]
                    return " ".join(
                        f"{config.graph_resource}/{name}" if qualified else name
                        for name in names
                    )

                self.http.scope_transform = scope_superset
                for callback in ("chat", "workflow"):
                    with self.subTest(cloud=config.cloud, qualified=qualified, callback=callback):
                        if callback == "chat":
                            with app.test_request_context():
                                _started, query = self.begin_chat()
                                completed = self.service.complete_chat_connection(
                                    "user-a", "tenant-a",
                                    {"state": query["state"][0], "code": "scope-superset"},
                                )
                                token = connections.get_m365_access_token(
                                    ["User.Read", "Files.Read.All", "Sites.Read.All"], include_auth_url=False,
                                )
                                cached = session.get("token_cache")
                                current_user = dict(session["user"])
                            self.assertEqual(completed["request_id"], "chat-request")
                            self.assertIsInstance(cached, str)
                            self.assertIn("access_token", token)
                            self.assertEqual(current_user["oid"], "user-a")
                            self.assertNotIn("token_cache", completed)
                        else:
                            connected, _started, _query = self.connect(sources=["spo"])
                            self.assertEqual(connected["status"], "connected")
                            self.assertEqual(connected["sources"], ["spo"])
                            self.assertEqual(
                                set(connected["authorized_scopes"]), {"User.Read", "Files.Read.All", "Sites.Read.All"},
                            )
                        self.assertNotIn("Directory.Read.All", self.http.posts[-1]["scope"])
                        self.assertNotIn("User.ReadWrite", self.http.posts[-1]["scope"])
                        self.assertNotIn("Tasks.Read", self.http.posts[-1]["scope"])
        self.assertEqual(self.approval_container.items, {})

    def test_extra_returned_grants_do_not_expand_a_narrow_workflow_connection(self):
        self.http.scope_transform = lambda requested: f"{requested} User.ReadWrite Directory.Read.All Mail.Send Calendars.ReadWrite"
        connected, _started, _query = self.connect(scopes=["Mail.Read"])
        context = self.workflow(connected)
        result = connections.get_m365_access_token(["Mail.Send"], context=context)
        self.assertEqual(result["error"], "m365_consent_required")
        self.assertNotIn("access_token", result)
        self.assertEqual(set(connected["authorized_scopes"]), {"User.Read", "Mail.Read"})

    def test_callbacks_reject_missing_or_wrong_resource_grants_without_publishing_credentials(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        for replacement in (
            "",
            "Directory.Read.All",
            "https://graph.microsoft.us/Sites.Read.All",
            "https://graph.microsoft.com.attacker.test/Sites.Read.All",
            "https://graph.microsoft.com/other/Sites.Read.All",
            "http://graph.microsoft.com/Sites.Read.All",
        ):
            def incomplete_scopes(requested):
                granted = [scope for scope in requested.split() if not scope.endswith("/Sites.Read.All")]
                return " ".join([*granted, replacement])

            self.http.scope_transform = incomplete_scopes
            for callback in ("chat", "workflow"):
                with self.subTest(replacement=replacement, callback=callback):
                    if callback == "chat":
                        with app.test_request_context():
                            _started, query = self.begin_chat()
                            with self.assertRaises(connections.M365ConnectionError) as raised:
                                self.service.complete_chat_connection(
                                    "user-a", "tenant-a", {"state": query["state"][0], "code": "missing-scope"},
                                )
                            self.assertNotIn("token_cache", session)
                    else:
                        _started, query = self.begin(["spo"])
                        cache_writer = Mock()
                        with self.assertRaises(connections.M365ConnectionError) as raised:
                            self.service.complete_connection(
                                "user-a", "tenant-a", {"state": query["state"][0], "code": "missing-scope"},
                                "session-binding-for-user-a", cache_writer=cache_writer,
                            )
                        saved = self.service.current_connection("user-a", "tenant-a")
                        self.assertEqual(saved["status"], "disconnected")
                        self.assertEqual(saved["authorized_scopes"], [])
                        cache_writer.assert_not_called()
                    self.assertEqual(raised.exception.code, "m365_consent_required")

    def test_requested_scope_allowlist_is_not_expanded_by_the_callback_fix(self):
        for scope in ("User.ReadWrite", "Directory.Read.All", "Tasks.Read", "https://graph.microsoft.us/Files.Read.All"):
            with self.subTest(scope=scope), self.assertRaises(connections.M365ConnectionError):
                self.service.start_connection(
                    "user-a", "tenant-a", ["spo"],
                    f"https://simplechat.example.test{connections.CONNECTION_CALLBACK_PATH}",
                    "session-binding-for-user-a", scopes=[scope],
                )
        self.assertEqual(self.clients, [])
        self.assertEqual(self.http.posts, [])
        self.assertEqual(self.container.items, {})

    def test_grant_validation_requires_a_scope_response_and_the_exact_requested_permission(self):
        for returned in (
            None, "", [], ["Files.Read.All"], 42,
            "openid profile email offline_access", "Files.ReadWrite.All",
        ):
            with self.subTest(returned=returned), self.assertRaises(connections.M365ConnectionError) as raised:
                connections._require_granted_scopes(["Files.Read.All"], returned, self.config)
            self.assertEqual(raised.exception.code, "m365_consent_required")
        connections._require_granted_scopes(
            ["Files.Read.All", "Sites.Read.All"],
            "  files.read.all  https://GRAPH.MICROSOFT.COM/Sites.Read.All openid profile email Directory.Read.All  ",
            self.config,
        )

    def test_other_cloud_grants_cannot_satisfy_government_or_custom_requests(self):
        for config in (
            connections.M365IdentityConfig(
                "client-a", "tenant-a", "https://login.microsoftonline.us/tenant-a",
                "https://graph.microsoft.us", "usgovernment",
            ),
            connections.M365IdentityConfig(
                "client-a", "tenant-a", "https://identity.example.test/tenant-a",
                "https://graph.example.test:8443/graph", "custom",
            ),
        ):
            with self.subTest(cloud=config.cloud), self.assertRaises(connections.M365ConnectionError) as raised:
                connections._require_granted_scopes(
                    ["Files.Read.All"], "openid https://graph.microsoft.com/Files.Read.All", config,
                )
            self.assertEqual(raised.exception.code, "m365_consent_required")

    def test_chat_connection_rejects_wrong_user_tenant_nonce_and_guest_claims(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        for claims in ({"oid": "another-user"}, {"tid": "another-tenant"}, {"acct": 1}, {"nonce": "wrong"}):
            with self.subTest(claims=claims), app.test_request_context():
                _started, query = self.begin_chat()
                self.http.claim_overrides = claims
                with self.assertRaises(connections.M365ConnectionError):
                    self.service.complete_chat_connection(
                        "user-a", "tenant-a", {"state": query["state"][0], "code": "wrong-account"},
                    )
                self.assertNotIn("token_cache", session)
                self.http.claim_overrides = {}

    def test_chat_connection_expiry_and_cross_session_callbacks_fail_before_token_exchange(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        with app.test_request_context():
            _started, query = self.begin_chat()
            self.clock.advance(seconds=connections.AUTH_FLOW_SECONDS + 1)
            with self.assertRaises(connections.M365ConnectionError) as expired:
                self.service.complete_chat_connection(
                    "user-a", "tenant-a", {"state": query["state"][0], "code": "expired"},
                )
        with app.test_request_context():
            session["user"] = {"oid": "user-a", "tid": "tenant-a"}
            with self.assertRaises(connections.M365ConnectionError) as absent:
                self.service.complete_chat_connection(
                    "user-a", "tenant-a", {"state": query["state"][0], "code": "another-session"},
                )
        self.assertEqual(expired.exception.code, "m365_auth_state_invalid")
        self.assertEqual(absent.exception.code, "m365_auth_state_invalid")
        self.assertEqual(self.http.posts, [])

    def test_chat_callback_rejects_malformed_state_without_consuming_the_valid_flow(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        with app.test_request_context():
            _started, query = self.begin_chat()
            for state in ("m365-chat-short", "m365-chat-" + "\u00e9" * 43, "m365-chat-" + "a" * 200):
                with self.subTest(state_length=len(state)), self.assertRaises(connections.M365ConnectionError) as raised:
                    self.service.complete_chat_connection("user-a", "tenant-a", {"state": state, "code": "invalid"})
                self.assertEqual(raised.exception.code, "m365_auth_state_invalid")
            saved_state = session[connections.CHAT_AUTH_SESSION_KEY]["flow"]["state"]
        self.assertEqual(saved_state, query["state"][0])
        self.assertEqual(self.http.posts, [])

    def test_chat_preflight_prompts_for_selected_remote_sources_before_model_execution(self):
        context = execution.M365ExecutionContext("user-a", "user-a", "tenant-a", request_id="request")
        manifests = [
            {"id": "calendar", "type": "m365_calendar"},
            {"id": "files", "type": "m365_sharepoint"},
            {"id": "native", "type": "custom"},
        ]
        with patch.object(connections, "get_m365_access_token", return_value={
            "error": "interactive_auth_required", "message": "Connect first.",
        }) as acquire:
            with self.assertRaises(connections.M365SignInRequired) as pending:
                connections.preflight_m365_chat_authentication(manifests, context)
        self.assertEqual(pending.exception.payload["sources"], ["calendar", "spo"])
        self.assertIn("Calendars.ReadWrite", pending.exception.payload["scopes"])
        self.assertIn("Files.Read.All", pending.exception.payload["scopes"])
        self.assertNotIn("Mail.Send", pending.exception.payload["scopes"])
        self.assertIs(acquire.call_args.kwargs["context"], context)
        self.assertFalse(acquire.call_args.kwargs["include_auth_url"])

    def test_snapshot_only_preflight_does_not_force_a_remote_connection(self):
        context = execution.M365ExecutionContext("user-a", "user-a", "tenant-a", request_id="request")
        with patch.object(connections, "get_m365_access_token") as acquire:
            result = connections.preflight_m365_chat_authentication([{
                "id": "files", "type": "m365_sharepoint", "enabled_functions": ["read_file_chunk", "analyze_file"],
            }], context)
        self.assertIsNone(result)
        acquire.assert_not_called()

    def test_chat_preflight_recovers_empty_or_invalid_session_cache_with_explicit_connection(self):
        app = Flask(__name__)
        app.secret_key = "unit-test-only"
        context = execution.M365ExecutionContext("user-a", "user-a", "tenant-a", request_id="request")
        for cache in ("{}", "invalid-cache"):
            with self.subTest(cache=cache), app.test_request_context():
                session["user"] = {"oid": "user-a", "tid": "tenant-a"}
                session["token_cache"] = cache
                with self.assertRaises(connections.M365SignInRequired) as pending:
                    connections.preflight_m365_chat_authentication([{
                        "id": "calendar", "type": "m365_calendar",
                    }], context)
                self.assertEqual(pending.exception.payload["sources"], ["calendar"])
                self.assertTrue(pending.exception.payload["auth_required"])
                self.assertEqual(session["token_cache"], cache)
        self.assertEqual(self.http.posts, [])

    def test_profile_connection_can_publish_only_its_verified_cache_to_the_live_session(self):
        _started, query = self.begin()
        cache_writer = Mock()
        result = self.service.complete_connection(
            "user-a", "tenant-a", {"state": query["state"][0], "code": "profile-code"},
            "session-binding-for-user-a", cache_writer=cache_writer,
        )
        self.assertEqual(result["status"], "connected")
        cache_writer.assert_called_once()
        self.assertIn("refresh-token-must-stay-server-side", cache_writer.call_args.args[0])
        self.assertNotIn("refresh-token-must-stay-server-side", json.dumps(result))

    def test_corrupt_serialized_cache_does_not_become_an_empty_signed_in_cache(self):
        for serialized in ("[]", "not-json", '{"Account": []}', '{"RefreshToken": {"entry": "invalid"}}'):
            with self.subTest(serialized=serialized):
                with self.assertRaises(connections.M365ConnectionError):
                    connections.deserialize_m365_cache(serialized)

    def test_cloud_scopes_are_explicit_and_never_fall_back_to_public(self):
        for config in (
            connections.M365IdentityConfig("client-a", "tenant-a", "https://login.microsoftonline.us/tenant-a", "https://graph.microsoft.us", "usgovernment"),
            connections.M365IdentityConfig("client-a", "tenant-a", "https://identity.example.test/tenant-a", "https://graph.example.test", "custom"),
        ):
            normalized = connections.normalize_m365_scopes(["Files.Read.All"], config)
            self.assertEqual(normalized, [f"{config.graph_resource}/Files.Read.All"])
            with self.assertRaises(connections.M365ConnectionError):
                connections.normalize_m365_scopes(["https://graph.microsoft.com/Files.Read.All"], config)
        with self.assertRaises(connections.M365ConnectionError):
            connections.M365IdentityConfig("client-a", "tenant-a", "https://login.microsoftonline.com/common", "https://graph.microsoft.com", "azurecloud")

    def test_missing_key_blocks_connect_before_msal_and_has_no_plaintext_fallback(self):
        def unavailable(*args):
            raise connections.M365ConnectionError("m365_key_vault_required", "Configure Key Vault first.")
        self.service.key_provider = unavailable
        with self.assertRaises(connections.M365ConnectionError):
            self.begin()
        self.assertEqual(self.clients, [])
        self.assertEqual(self.container.items, {})

    def test_default_msal_factory_uses_pinned_graph_authority_without_public_discovery(self):
        owner = types.ModuleType("config")
        owner.CLIENT_SECRET = "unit-test-only"
        cache = msal.SerializableTokenCache()
        with patch.dict(sys.modules, {"config": owner}), patch(
            "msal.ConfidentialClientApplication",
        ) as constructor:
            client = connections._default_msal_factory(cache, self.config)
            constructor.assert_called_once_with(
                self.config.client_id, authority=self.config.authority,
                client_credential="unit-test-only", token_cache=cache,
                instance_discovery=False,
            )
            self.assertIs(client, constructor.return_value)

    def test_default_key_provider_requires_explicit_key_vault_reference(self):
        config_stub = types.ModuleType("config")
        config_stub.KEY_VAULT_DOMAIN = ".vault.azure.net"
        settings_stub = types.ModuleType("functions_settings")
        settings_stub.get_settings = lambda: {
            "enable_key_vault_secret_storage": True, "key_vault_name": "test-vault",
        }
        vault_stub = types.ModuleType("functions_keyvault")
        vault_stub.get_keyvault_credential = lambda settings: "test-credential"
        properties = types.SimpleNamespace(
            enabled=True, expires_on=None, not_before=None, version="version1",
        )
        secret = types.SimpleNamespace(
            value=base64.b64encode(b"a" * 32).decode("ascii"), properties=properties,
        )
        client = types.SimpleNamespace(get_secret=lambda name, version=None: secret)
        with patch.dict(sys.modules, {
            "config": config_stub, "functions_settings": settings_stub, "functions_keyvault": vault_stub,
        }), patch.dict(os.environ, {connections.KEY_SECRET_ENV: ""}), patch(
            "azure.keyvault.secrets.SecretClient", return_value=client,
        ) as constructor:
            with self.assertRaises(connections.M365ConnectionError):
                connections._default_key_provider()
            constructor.assert_not_called()
            os.environ[connections.KEY_SECRET_ENV] = "workflow-token-key"
            key = connections._default_key_provider("version1", "workflow-token-key")
            self.assertEqual(key.key, b"a" * 32)
            self.assertEqual(key.version, "version1")
            constructor.assert_called_once_with(
                vault_url="https://test-vault.vault.azure.net", credential="test-credential",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
