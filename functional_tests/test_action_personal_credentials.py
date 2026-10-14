# test_action_personal_credentials.py
"""Backend functional tests for actor-bound personal action credentials.

Version: 0.261.333
Implemented in: 0.261.333

Exercises real storage owners, identity CRUD, resolver, schema and Flask routes
with installed-SDK CosmosDict point responses and conditional ETags. No network.
"""

from copy import deepcopy
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace

from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.core import MatchConditions
from flask import Blueprint, Flask, jsonify, session
import pytest
from jsonschema import Draft7Validator
import requests

from test_support.app_stubs import APP_ROOT, stubbed_app_imports
from test_support.m365 import CosmosContainer


class CredentialContainer(CosmosContainer):
    """SDK-default conditional point/write responses; queries remain plain JSON."""

    def delete_item(self, item, partition_key, *, etag=None, match_condition=None):
        current = self.read_item(item, partition_key)
        if etag is not None and (match_condition != MatchConditions.IfNotModified or current["_etag"] != etag):
            raise CosmosHttpResponseError(status_code=412, message="Conditional delete conflict.")
        return super().delete_item(item, partition_key)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        values = {item["name"]: item["value"] for item in parameters or []}
        rows = [
            deepcopy(dict(row)) for (partition, _id), row in self.items.items()
            if partition == partition_key
        ]
        if "credential_request" in query:
            rows = [
                row for row in rows if row.get("record_type") == "credential_request"
                and row.get("conversation_id") == values["@conversation"]
                and row.get("status") in {"pending", "ready", "saving"} and row["expires_at"] > values["@now"]
            ]
        if "credential_binding" in query:
            rows = [
                row for row in rows if row.get("record_type") == "credential_binding"
                and row.get("identity_id") == values["@identity"]
            ]
        elif "@conversation" in values and "credential_request" not in query:
            rows = [row for row in rows if row.get("conversation_id") == values["@conversation"]]
        return rows


def module(name, **values):
    value = ModuleType(name)
    value.__dict__.update(values)
    return value


def manifest(*, scope="global", service="api_key", proxy=False):
    from functions_action_manifest import bind_action_origin

    slots = {}
    if service:
        slots["service"] = {"source": "personal", "auth_type": service}
    if proxy:
        slots["proxy"] = {"source": "personal", "auth_type": "username_password"}
    return bind_action_origin({
        "id": "mission", "name": "mission", "type": "yamcs", "description": "Read mission telemetry.",
        "endpoint": "https://mission.example.invalid", "metadata": {},
        "auth": {"type": "key" if service else "NoAuth", "key": "", "identity": ""},
        "additionalFields": {"instance": "sim", "auth_method": service or "none", "enable_basic_auth": proxy},
        "credential_requirements": {"version": 1, "slots": slots},
    }, scope, "global" if scope == "global" else "team" if scope == "group" else "alice")


@pytest.fixture
def environment(monkeypatch):
    with stubbed_app_imports():
        state = importlib.import_module("functions_action_credential_state")
        credentials = importlib.import_module("functions_action_credentials")
        contracts = importlib.import_module("action_credential_contracts")
        store, identities = CredentialContainer("user_id"), CredentialContainer("user_id")
        monkeypatch.setattr(state, "_container", store)
        vault, deleted = {}, []

        def store_secret(**kwargs):
            key = kwargs["secret_name"]
            vault[key] = kwargs["secret_value"]
            return key

        def discard(names, *args, **kwargs):
            for name in names:
                deleted.append(name)
                vault.pop(name, None)

        config = module("config", **{
            f"cosmos_{scope}_workspace_identities_container": identities
            for scope in ("personal", "group", "global", "public")
        })
        monkeypatch.setitem(sys.modules, "config", config)
        monkeypatch.setitem(sys.modules, "functions_keyvault", module(
            "functions_keyvault", SecretReturnType=SimpleNamespace(VALUE="value", TRIGGER="trigger", NAME="name"),
            ui_trigger_word="Stored_In_KeyVault", store_secret_in_key_vault=store_secret,
            retrieve_secret_from_key_vault_by_full_name=lambda name: vault[name],
            keyvault_identity_discard_staged_helper=discard,
            keyvault_identity_cleanup_helper=lambda *args, **kwargs: None,
            keyvault_identity_delete_helper=lambda *args, **kwargs: None,
        ))
        monkeypatch.delitem(sys.modules, "functions_workspace_identities", raising=False)
        identity_owner = importlib.import_module("functions_workspace_identities")
        app = Flask(__name__)
        app.secret_key = "local-test-only"

        def login(function):
            def wrapped(*args, **kwargs):
                if not session.get("user"):
                    return jsonify({"error": "login"}), 401
                return function(*args, **kwargs)
            wrapped.__name__ = function.__name__
            return wrapped

        monkeypatch.setitem(sys.modules, "functions_authentication", module(
            "functions_authentication", get_current_user_id=lambda: (session.get("user") or {}).get("oid"),
            get_current_user_id_or_none=lambda: (session.get("user") or {}).get("oid"),
            get_current_user_info=lambda: session.get("user"), login_required=login, user_required=login,
        ))
        monkeypatch.setitem(sys.modules, "swagger_wrapper", module(
            "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function,
            get_auth_security=lambda: [],
        ))
        current = manifest()
        auth = SimpleNamespace(user="alice", available=True, owned=True)

        def authorize(user_id, conversation_id):
            if not auth.owned or user_id != "alice" or conversation_id != "chat":
                raise LookupError()
            return {"id": "chat", "user_id": "alice"}

        def resolve(user_id, reference):
            if not auth.available or user_id != "alice" or reference != credentials.manifest_reference(current):
                raise PermissionError()
            return deepcopy(current)

        monkeypatch.setattr(credentials, "authorize_conversation", authorize)
        monkeypatch.setattr(credentials, "authorized_manifest", resolve)
        monkeypatch.setattr(credentials, "actor_context", lambda: (auth.user, "chat", None))
        monkeypatch.delitem(sys.modules, "route_backend_action_credentials", raising=False)
        routes = importlib.import_module("route_backend_action_credentials")
        monkeypatch.setattr(routes, "authorize_conversation", authorize)
        bp = Blueprint("credentials", __name__)
        routes.register_route_backend_action_credentials(bp)
        app.register_blueprint(bp)
        client = app.test_client()
        with client.session_transaction() as browser:
            browser["user"] = {"oid": "alice"}
        descriptor = {"mode": "chat", "checkpoint_id": "checkpoint-test", "agent_reference": {"id": "agent"}}
        env = SimpleNamespace(
            state=state, credentials=credentials, contracts=contracts, identities=identities, store=store,
            identity_owner=identity_owner, app=app, client=client, current=current, auth=auth, routes=routes,
            vault=vault, deleted=deleted, descriptor=descriptor,
        )
        yield env
        sys.modules.pop("functions_workspace_identities", None)
        sys.modules.pop("route_backend_action_credentials", None)


def challenge(env):
    with env.credentials.credential_continuation(env.descriptor):
        with pytest.raises(env.contracts.ActionCredentialsRequired) as stopped:
            env.credentials.resolve_personal_credentials(env.current)
    return stopped.value.credential_request


def entry(slot="service", *, identity_id=None, secret="PRIVATE_API_KEY"):
    value = {"slot": slot, "name": "Mission access", "credentials": {"auth_type": "api_key", "secret": secret}}
    if identity_id:
        value.update(identity_id=identity_id)
        value.pop("name")
    return value


def submit(env, dto, entries=None):
    return env.credentials.submit_credentials("alice", dto["id"], dto["etag"], entries or [entry()])


def test_sdk_owner_conditional_request_binding_and_safe_resolution(environment):
    env = environment
    dto = challenge(env)
    assert dto["status"] == "pending"
    assert dto["destination_label"] == "mission.example.invalid"
    assert type(env.state.read("alice", dto["id"])) is dict
    assert isinstance(env.store.read_item(dto["id"], "alice"), CosmosDict)
    ready = submit(env, dto)
    assert ready["status"] == "ready"
    identity_count = len(env.identities.items)
    replay = submit(env, dto)
    assert replay == ready
    assert len(env.identities.items) == identity_count
    resolved = env.credentials.resolve_personal_credentials(env.current)
    assert resolved["auth"]["key"] == "PRIVATE_API_KEY"
    assert env.current["auth"]["key"] == ""
    assert "PRIVATE_API_KEY" not in json.dumps(list(env.store.items.values()), default=str)
    assert "PRIVATE_API_KEY" not in json.dumps(ready)
    assert all(set(row) == {"id", "name", "auth_type", "etag"} for row in ready["identities"])
    with pytest.raises(env.contracts.ActionCredentialError):
        env.state.claim_request("alice", env.state.read("alice", dto["id"]), dto["etag"])
    claimed = env.state.claim_request("alice", env.state.read("alice", dto["id"]), ready["etag"])
    assert claimed["status"] == "continuing"
    with pytest.raises(env.contracts.ActionCredentialError):
        env.state.claim_request("alice", env.state.read("alice", dto["id"]), ready["etag"])


@pytest.mark.parametrize("scope", ["global", "group", "personal"])
def test_actor_is_private_and_destination_contract_changes_invalidate(environment, scope):
    env = environment
    env.current.clear()
    env.current.update(manifest(scope=scope))
    # Preserve the server-established immutable origin when replacing test JSON.
    env.current._action_origin = manifest(scope=scope).action_origin
    dto = challenge(env)
    submit(env, dto)
    env.auth.user = "bob"
    with env.credentials.credential_continuation(env.descriptor), pytest.raises(PermissionError):
        env.credentials.resolve_personal_credentials(env.current)
    env.auth.user = "alice"
    env.current["endpoint"] = "https://another.example.invalid"
    with pytest.raises(env.contracts.ActionCredentialError) as error:
        env.credentials.authorize_request("alice", dto["id"])
    assert error.value.code == "action_destination_changed"


def test_binding_revision_requires_explicit_rotation_and_confirm(environment):
    env = environment
    dto = challenge(env)
    ready = submit(env, dto)
    identity = ready["identities"][0]
    updated = env.identity_owner.update_workspace_identity_conditional(
        "personal", "alice", identity["id"], {"credentials": {"auth_type": "api_key", "secret": "ROTATED"}},
        "alice", identity["etag"],
    )
    next_request = challenge(env)
    assert next_request["reason"] == "identity_changed"
    entry_value = entry(identity_id=identity["id"], secret="ROTATED_AGAIN")
    entry_value["expected_identity_etag"] = updated["_etag"]
    rotated = submit(env, next_request, [entry_value])
    repeated = submit(env, next_request, [entry_value])
    assert rotated == repeated
    resolved = env.credentials.resolve_personal_credentials(env.current)
    assert resolved["auth"]["key"] == "ROTATED_AGAIN"
    env.identity_owner.delete_workspace_identity("personal", "alice", identity["id"], "alice")
    assert env.state.binding("alice", env.credentials.manifest_reference(env.current), "service")["confirmed"] is False


def test_keyvault_existing_policy_keeps_secrets_out_of_state_and_manifest(environment, monkeypatch):
    env = environment
    monkeypatch.setattr(env.identity_owner, "get_settings", lambda: {
        "enable_key_vault_secret_storage": True, "key_vault_name": "configured-vault",
        "enable_key_vault_secret_expiration_reminders": True,
        "key_vault_secret_expiration_require_expiration": True,
    })
    dto = challenge(env)
    submit(env, dto)
    assert list(env.vault.values()) == ["PRIVATE_API_KEY"]
    assert "PRIVATE_API_KEY" not in json.dumps(list(env.identities.items.values()))
    resolved = env.credentials.resolve_personal_credentials(env.current)
    assert resolved["auth"]["key"] == "PRIVATE_API_KEY"


def test_submission_failure_recovers_without_duplicate_identity(environment, monkeypatch):
    env = environment
    dto = challenge(env)
    original = env.state.save_binding

    def unavailable(*args, **kwargs):
        raise CosmosHttpResponseError(status_code=503, message="Provider outage")

    monkeypatch.setattr(env.state, "save_binding", unavailable)
    with pytest.raises(CosmosHttpResponseError):
        submit(env, dto)
    assert len(env.identities.items) == 1
    pending = env.state.read("alice", dto["id"])
    env.state.replace("alice", pending, {"saving_until": 0}, pending["_etag"])
    monkeypatch.setattr(env.state, "save_binding", original)
    ready = submit(env, dto)
    assert ready["status"] == "ready"
    assert len(env.identities.items) == 1


def test_credential_api_csrf_ownership_no_store_cancel_and_no_workspace_gate(environment, monkeypatch):
    env = environment
    dto = challenge(env)
    path = f"/api/action-credentials/{dto['id']}"
    response = env.client.get(path)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    token = response.json["csrf_token"]
    pending = env.client.get("/api/action-credentials/pending?conversation_id=chat")
    assert len(pending.json["requests"]) == 1
    forbidden = env.client.post(path + "/submit", json={"expected_etag": dto["etag"], "slots": [entry()]})
    assert forbidden.status_code == 403
    saved = env.client.post(
        path + "/submit", headers={"X-CSRFToken": token},
        json={"expected_etag": dto["etag"], "slots": [entry()]},
    )
    assert saved.status_code == 200
    ready = saved.json["credential_request"]
    assert "PRIVATE_API_KEY" not in saved.get_data(as_text=True)
    env.auth.owned = False
    denied = env.client.get(path)
    assert denied.status_code == 404
    env.auth.owned = True
    cancelled = env.client.post(
        path + "/cancel", headers={"X-CSRFToken": token}, json={"expected_etag": ready["etag"]},
    )
    assert cancelled.json["credential_request"]["status"] == "cancelled"
    continuation = env.client.post(
        path + "/continue", headers={"X-CSRFToken": token}, json={"expected_etag": cancelled.json["credential_request"]["etag"]},
    )
    assert continuation.status_code == 409


def test_contract_schema_primary_proxy_and_shared_compatibility(environment):
    env = environment
    schema = json.loads((APP_ROOT / "static" / "json" / "schemas" / "plugin.schema.json").read_text())
    validator = Draft7Validator(schema)
    for service in ("api_key", "bearer_token", "username_password"):
        value = manifest(service=service)
        env.contracts.validate_credential_requirements(value)
        stripped = {key: val for key, val in value.items() if key not in {"scope", "scope_id", "is_global", "is_group"}}
        errors = list(validator.iter_errors(stripped))
        assert errors == []
    proxy = manifest(service=None, proxy=True)
    slots = env.contracts.validate_credential_requirements(proxy)
    assert set(slots) == {"proxy"}
    both = manifest(service="api_key", proxy=True)
    assert set(env.contracts.validate_credential_requirements(both)) == {"service", "proxy"}
    for service in ("username_password", "bearer_token"):
        with pytest.raises(ValueError):
            env.contracts.validate_credential_requirements(manifest(service=service, proxy=True))
    both["auth"]["key"] = "SHARED"
    with pytest.raises(ValueError):
        env.contracts.validate_credential_requirements(both)
    shared = manifest()
    shared["credential_requirements"]["slots"] = {}
    shared["auth"]["key"] = "SHARED"
    assert env.contracts.validate_credential_requirements(shared) == {}
    both["credential_requirements"]["version"] = 2
    with pytest.raises(ValueError):
        env.contracts.credential_slots(both)


@pytest.mark.parametrize("status,expected", [(401, ["service", "proxy"]), (407, ["proxy"]), (403, []), (429, []), (503, [])])
def test_provider_status_classification_is_structured_not_exception_text(environment, status, expected):
    adapter = environment.contracts.ADAPTERS["yamcs"]
    value = manifest(service="api_key", proxy=True)
    error = RuntimeError("401 password=PRIVATE")
    error.response = SimpleNamespace(status_code=status)
    assert adapter.rejected_slots(value, error) == expected
    assert adapter.rejected_slots(value, RuntimeError("401 Unauthorized")) == []


@pytest.mark.parametrize("error_type", [ValueError, ImportError, requests.exceptions.InvalidHeader])
def test_personal_provider_validation_errors_never_disclose_credentials(environment, monkeypatch, error_type):
    env = environment
    pending = challenge(env)
    submit(env, pending)
    monkeypatch.setitem(sys.modules, "semantic_kernel_plugins.plugin_invocation_logger", module(
        "semantic_kernel_plugins.plugin_invocation_logger",
        plugin_function_logger=lambda *args, **kwargs: lambda function: function,
    ))
    plugin_module = importlib.import_module("semantic_kernel_plugins.yamcs_plugin")

    def fail_connection(self):
        raise error_type("Provider rejected PRIVATE_API_KEY for PRIVATE_PRINCIPAL.")

    monkeypatch.setattr(plugin_module.YamcsPlugin, "_connect", fail_connection)
    plugin = plugin_module.YamcsPlugin(env.current)
    result = plugin._run("read-test", lambda client: {"success": True})
    assert result["success"] is False
    assert "PRIVATE_API_KEY" not in json.dumps(result)
    assert "PRIVATE_PRINCIPAL" not in json.dumps(result)


@pytest.mark.parametrize("service,proxy,status,expected", [
    ("username_password", False, 401, ["service"]),
    ("bearer_token", False, 401, ["service"]),
    ("api_key", True, 401, ["service", "proxy"]),
    ("api_key", True, 407, ["proxy"]),
    (None, True, 407, ["proxy"]),
    ("username_password", False, 403, []),
    ("api_key", True, 503, []),
])
def test_real_yamcs_sdk_handshake_and_proxy_transport_status(environment, monkeypatch, service, proxy, status, expected):
    env = environment
    value = manifest(service=service, proxy=proxy)
    env.current.clear()
    env.current.update(value)
    env.current._action_origin = value.action_origin
    dto = challenge(env)
    entries = []
    for required in dto["requirements"]:
        auth_type = required["auth_type"]
        auth = {"auth_type": auth_type}
        auth.update({"username": "PRIVATE_PRINCIPAL", "password": "PRIVATE_PASSWORD"}
                    if auth_type == "username_password" else {"secret": "PRIVATE_SECRET"})
        entries.append({"slot": required["slot"], "name": required["slot"], "credentials": auth})
    submit(env, dto, entries)
    calls, closed = [], []
    original_close = requests.Session.close

    def transport(session, method, url, **kwargs):
        calls.append({"method": method, "url": url, "headers": dict(session.headers), "data": kwargs.get("data")})
        response = requests.Response()
        response.status_code = status
        response._content = b"PRIVATE_PASSWORD PRIVATE_PRINCIPAL PRIVATE_SECRET 401 Unauthorized"
        return response

    def close(session):
        closed.append(session)
        original_close(session)

    monkeypatch.setattr(requests.Session, "request", transport)
    monkeypatch.setattr(requests.Session, "close", close)
    monkeypatch.setitem(sys.modules, "semantic_kernel_plugins.plugin_invocation_logger", module(
        "semantic_kernel_plugins.plugin_invocation_logger",
        plugin_function_logger=lambda *args, **kwargs: lambda function: function,
    ))
    plugin = importlib.import_module("semantic_kernel_plugins.yamcs_plugin").YamcsPlugin(env.current)
    assert calls == [], "Merely loading an unused action must never acquire credentials or contact YAMCS."
    with env.credentials.credential_continuation(env.descriptor):
        if expected:
            with pytest.raises(env.contracts.ActionCredentialsRequired) as paused:
                result = plugin._run("probe", lambda client: {"success": bool(client.ctx.request("get", "/probe"))})
                pytest.fail(f"The connector returned instead of challenging: {result}")
            assert [item["slot"] for item in paused.value.credential_request["requirements"]] == expected
            assert paused.value.credential_request["reason"] == "credentials_rejected"
            assert "PRIVATE_" not in json.dumps(paused.value.event)
        else:
            result = plugin._run("probe", lambda client: {"success": bool(client.ctx.request("get", "/probe"))})
            assert result["success"] is False
            assert "PRIVATE_" not in json.dumps(result)
    assert len(calls) == 1
    assert closed, "A failed initial credentials login must close its session too."
    if service == "username_password":
        assert calls[0]["url"].endswith("/auth/token")
        assert calls[0]["data"]["username"] == "PRIVATE_PRINCIPAL"
    elif service == "api_key":
        assert calls[0]["headers"]["x-api-key"] == "PRIVATE_SECRET"
        assert calls[0]["headers"]["Authorization"].startswith("Basic ")
    assert "PRIVATE_" not in json.dumps(list(env.store.items.values()), default=str)
    assert env.current["auth"]["key"] == ""


def test_frozen_submit_selection_and_classic_preparation_failure_are_retryable(environment, monkeypatch):
    env = environment
    dto = challenge(env)
    original = env.state.save_binding
    monkeypatch.setattr(env.state, "save_binding", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        submit(env, dto)
    saving = env.state.read("alice", dto["id"])
    assert env.credentials.safe_request(saving, env.current)["status"] == "pending"
    assert env.credentials.safe_request(saving, env.current)["etag"] == dto["etag"]
    env.state.replace("alice", saving, {"saving_until": 0}, saving["_etag"])
    altered = entry()
    altered["name"] = "Changed selection"
    with pytest.raises(env.contracts.ActionCredentialError):
        submit(env, dto, [altered])
    assert len(env.identities.items) == 1
    monkeypatch.setattr(env.state, "save_binding", original)
    ready = submit(env, dto)
    path = f"/api/action-credentials/{dto['id']}"
    token = env.client.get(path).json["csrf_token"]
    # A missing retained thread is a preparation failure, never a whole-message replay.
    response = env.client.post(path + "/continue", headers={"X-CSRFToken": token},
                               json={"expected_etag": ready["etag"]})
    assert response.status_code >= 400
    assert env.state.read("alice", dto["id"])["status"] == "ready"


def test_lifecycle_deletes_only_owned_ephemeral_conversation_state(environment):
    env = environment
    dto = challenge(env)
    submit(env, dto)
    env.state.checkpoint("alice", "checkpoint-local", "chat", {"history": "retained"})
    env.state.checkpoint("alice", "checkpoint-other", "other-chat", {"history": "retained"})
    env.state.create("bob", {"id": "bob-row", "record_type": "credential_checkpoint", "conversation_id": "chat"})
    env.state.delete_private_state("alice", conversation_id="chat")
    remaining = list(env.store.items.values())
    assert all(row.get("conversation_id") != "chat" for row in remaining if row["user_id"] == "alice")
    assert env.state.binding("alice", env.credentials.manifest_reference(env.current), "service")
    assert any(row["user_id"] == "bob" for row in remaining)
    env.state.delete_private_state("alice")
    assert all(row["user_id"] == "bob" for row in env.store.items.values())


def test_full_user_private_purge_removes_all_lifecycle_records_and_preserves_other_actors(environment):
    env = environment
    dto = challenge(env)
    submit(env, dto)
    env.state.checkpoint("alice", "thread-one", "chat", {"root": {"history": "retained"}})
    env.state.checkpoint("alice", "thread-two", "another-chat", {"child": {"history": "retained"}})
    env.state.create("bob", {
        "id": "bob-binding", "record_type": "credential_binding", "confirmed": True,
    })
    before = [row for row in env.store.items.values() if row["user_id"] == "alice"]
    assert {row["record_type"] for row in before} == {
        "credential_binding", "credential_request", "credential_checkpoint",
    }
    env.state.delete_private_state("alice")
    assert len(env.store.items) == 1
    assert env.state.read("bob", "bob-binding")["confirmed"] is True
    env.state.delete_private_state("alice")
    assert len(env.store.items) == 1


def test_destination_restore_requires_explicit_binding_reconfirmation_before_secret_use(environment, monkeypatch):
    env = environment
    original = challenge(env)
    submit(env, original)
    reference = env.credentials.manifest_reference(env.current)
    identity_id = env.state.binding("alice", reference, "service")["identity_id"]
    identity = env.identity_owner.get_workspace_identity("personal", "alice", identity_id)
    # The backup/restore allowlist omits the entire private container. A restored
    # identity/action does not restore challenge, checkpoint or binding authority.
    destination = CredentialContainer("user_id")
    monkeypatch.setattr(env.state, "_container", destination)
    with pytest.raises(LookupError):
        env.state.read("alice", original["id"])
    assert env.state.binding("alice", reference, "service") is None
    env.descriptor["checkpoint_id"] = "destination-checkpoint"
    pending = challenge(env)
    assert pending["status"] == "pending" and pending["reason"] == "setup_required"
    assert identity_id in {choice["id"] for choice in pending["identities"]}
    before = len(env.identities.items)
    ready = submit(env, pending, [{"slot": "service", "identity_id": identity_id}])
    assert ready["status"] == "ready" and len(env.identities.items) == before
    resolved = env.credentials.resolve_personal_credentials(env.current)
    assert resolved["auth"]["key"] == "PRIVATE_API_KEY"
    current_identity = env.identity_owner.get_workspace_identity("personal", "alice", identity_id)
    assert current_identity["_etag"] == identity["_etag"]
    # An explicitly unconfirmed imported binding also cannot reuse even an
    # otherwise matching destination fingerprint and identity revision.
    bound = env.state.binding("alice", reference, "service")
    env.state.replace("alice", bound, {"confirmed": False}, bound["_etag"])
    unconfirmed = challenge(env)
    assert unconfirmed["reason"] == "binding_changed"
    submit(env, unconfirmed, [{"slot": "service", "identity_id": identity_id}])
    assert env.state.binding("alice", reference, "service")["confirmed"] is True


def test_lost_identity_write_responses_keep_committed_keyvault_references(environment, monkeypatch):
    env = environment
    monkeypatch.setattr(env.identity_owner, "get_settings", lambda: {
        "enable_key_vault_secret_storage": True, "key_vault_name": "configured-vault",
    })
    real_create, real_replace = env.identities.create_item, env.identities.replace_item

    def lost_create(*args, **kwargs):
        real_create(*args, **kwargs)
        raise CosmosHttpResponseError(status_code=503, message="Lost response")

    monkeypatch.setattr(env.identities, "create_item", lost_create)
    dto = challenge(env)
    ready = submit(env, dto)
    assert len(env.identities.items) == 1
    assert list(env.vault.values()) == ["PRIVATE_API_KEY"]
    identity = ready["identities"][0]

    def lost_replace(*args, **kwargs):
        real_replace(*args, **kwargs)
        raise CosmosHttpResponseError(status_code=503, message="Lost response")

    monkeypatch.setattr(env.identities, "replace_item", lost_replace)
    rotated = env.identity_owner.update_workspace_identity_conditional(
        "personal", "alice", identity["id"], {"credentials": {"auth_type": "api_key", "secret": "NEW_SECRET"}},
        "alice", identity["etag"], operation_id="rotate-once",
    )
    repeated = env.identity_owner.update_workspace_identity_conditional(
        "personal", "alice", identity["id"], {"credentials": {"auth_type": "api_key", "secret": "NEW_SECRET"}},
        "alice", identity["etag"], operation_id="rotate-once",
    )
    assert rotated["_etag"] == repeated["_etag"]
    assert "NEW_SECRET" in env.vault.values()
    assert not env.deleted


def test_untrusted_origin_is_never_authority_for_personal_secret_resolution(environment):
    env = environment
    dto = challenge(env)
    submit(env, dto)
    forged = dict(env.current)
    forged.update(scope="global", scope_id="global", user_id="alice")
    with pytest.raises(env.contracts.ActionCredentialError) as stopped:
        env.credentials.resolve_personal_credentials(forged)
    assert stopped.value.code == "trusted_origin_required"
