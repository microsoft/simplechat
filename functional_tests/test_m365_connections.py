# test_m365_connections.py
"""
Functional tests for encrypted Microsoft 365 workflow connections.
Version: 0.261.029
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
from unittest.mock import patch

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
            "scope": data.get("scope", ""),
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

    def begin(self, sources=None):
        result = self.service.start_connection(
            "user-a", "tenant-a", sources or ["email"],
            f"https://simplechat.example.test{connections.CONNECTION_CALLBACK_PATH}",
            "session-binding-for-user-a",
        )
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        self.http.nonce = query["nonce"][0]
        return result, query

    def connect(self, sources=None):
        started, query = self.begin(sources)
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
        connected, _started, _query = self.connect()
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
