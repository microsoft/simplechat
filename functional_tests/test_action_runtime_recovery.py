# test_action_runtime_recovery.py
"""
Actor-bound, pre-model action recovery and authorized reporting regressions.
Version: 0.261.347
Implemented in: 0.261.347

Runs the real recovery service and conditional interaction storage owner with
installed-SDK CosmosDict responses. No model, tool, or remote service is called.
"""

from copy import deepcopy
import importlib
from importlib.metadata import version
import json
import socket
import sys
import time
from types import ModuleType, SimpleNamespace

from flask import Blueprint, Flask, g, session
import pytest
import werkzeug

from test_support.app_stubs import stubbed_app_imports
from test_support.m365 import CosmosContainer


def seam(name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    return module


@pytest.fixture
def recovery_env(monkeypatch):
    with stubbed_app_imports():
        from functions_action_manifest import bind_action_origin
        from action_runtime_contracts import ActionLoadRequired, action_binding_key
        import functions_action_recovery as recovery
        import functions_action_credential_state as state

        monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("No network."))
        container = CosmosContainer("user_id")
        monkeypatch.setattr(state, "_container", container)
        app = Flask(__name__)
        app.secret_key = "offline-recovery-test"
        allowed = SimpleNamespace(conversation=True, action=True, group_role="Owner")
        settings = {
            "allow_user_plugins": True, "allow_group_plugins": True,
            "enable_group_workspaces": True, "enable_semantic_kernel": True,
            "per_user_semantic_kernel": True, "allow_group_agents": True,
        }
        monkeypatch.setattr(sys.modules["functions_settings"], "get_settings", lambda: settings)
        monkeypatch.setitem(sys.modules, "functions_governance", seam(
            "functions_governance", is_action_scope_access_allowed=lambda *args: True,
        ))
        monkeypatch.setitem(sys.modules, "functions_authentication", seam(
            "functions_authentication",
            get_current_user_id=lambda: session.get("user", {}).get("oid"),
            login_required=lambda function: function, user_required=lambda function: function,
        ))
        monkeypatch.setitem(sys.modules, "swagger_wrapper", seam(
            "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function,
            get_auth_security=lambda: [],
        ))

        def authorize(user_id, conversation_id):
            if not allowed.conversation or user_id != "alice" or conversation_id != "chat":
                raise PermissionError("Unavailable.")
            return {"id": "chat", "user_id": "alice"}

        # The public service seam is not a Cosmos-shaped double.
        credentials = importlib.import_module("functions_action_credentials")
        monkeypatch.setattr(credentials, "authorize_conversation", authorize)
        action = bind_action_origin({
            "id": "calendar", "name": "FED-calendar", "type": "m365_calendar",
            "additionalFields": {"m365_capabilities": {"create_calendar_invite": True}},
            "auth": {"key": "PRIVATE-SECRET"},
        }, "personal", "alice")
        healthy = bind_action_origin({"id": "mail", "name": "mail", "type": "m365_email"}, "personal", "alice")
        actions = [action, healthy]
        agent = {"id": "agent", "name": "FED agent", "actions_to_load": ["calendar", "mail"]}
        monkeypatch.setitem(sys.modules, "route_backend_chats", seam(
            "route_backend_chats", _resolve_canonical_chat_agent=lambda *args: deepcopy(agent),
        ))

        def load(kernel, names, values, *args, **kwargs):
            admitted = recovery.apply_action_recovery(actions)
            if any(item["id"] == "calendar" for item in admitted):
                raise ActionLoadRequired(deepcopy(actions), [action_binding_key(action)])

        monkeypatch.setitem(sys.modules, "semantic_kernel_loader", seam(
            "semantic_kernel_loader", load_agent_specific_plugins=load,
            load_agent_core_plugins=lambda *args: None,
        ))
        group = {"id": "team", "owner": {"id": "owner"}, "admins": ["manager"], "status": "active"}

        def group_role(user_id, group_id, allowed_roles):
            if not allowed.group_role:
                raise PermissionError("Membership removed.")
            return allowed.group_role

        monkeypatch.setitem(sys.modules, "functions_group", seam(
            "functions_group", assert_group_role=group_role,
            find_group_by_id=lambda group_id: deepcopy(group),
            get_user_role_in_group=lambda value, user_id: "Owner" if user_id == "owner" else "Admin",
        ))
        def resolve(user_id, reference, **kwargs):
            if not allowed.action or user_id != "alice":
                raise PermissionError("Access removed.")
            return deepcopy(action)

        monkeypatch.setitem(sys.modules, "functions_action_catalog", seam(
            "functions_action_catalog", resolve_action_manifest=resolve,
            _action_ref=lambda *parts: ":".join(parts),
        ))
        sent = []
        delivery = SimpleNamespace(fail=False)

        def notify(**kwargs):
            sent.append(kwargs)
            if delivery.fail:
                raise ConnectionError("PRIVATE-provider-detail")
            return {"id": kwargs["idempotency_key"]}

        monkeypatch.setitem(sys.modules, "functions_notifications", seam(
            "functions_notifications", create_notification=notify,
        ))
        monkeypatch.delitem(sys.modules, "route_backend_action_credentials", raising=False)
        routes = importlib.import_module("route_backend_action_credentials")
        bp = Blueprint("action_recovery_test", __name__)
        routes.register_route_backend_action_credentials(bp)
        app.register_blueprint(bp)
        # Match the existing test harness when the host has Flask 2/Werkzeug 3.
        monkeypatch.setattr(werkzeug, "__version__", version("werkzeug"), raising=False)
        client = app.test_client()
        with client.session_transaction() as browser:
            browser["user"] = {"oid": "alice"}
        context = client.get("/api/action-recovery/context").get_json()
        yield SimpleNamespace(
            recovery=recovery, state=state, actions=actions, action=action, healthy=healthy, agent=agent,
            app=app, client=client, headers={"X-CSRFToken": context["csrf_token"]},
            container=container, allowed=allowed, settings=settings, sent=sent, delivery=delivery,
            binding_key=action_binding_key,
        )


def body():
    return {
        "conversation_id": "chat", "message": "PRIVATE-PROMPT create a fixture event",
        "agent_info": {"id": "agent", "name": "FED agent"}, "action_recovery_nonce": "one-turn",
    }


def challenge(env):
    response = env.client.post("/api/chat/action-health", json={"request": body()}, headers=env.headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def admitted(env, dto, *, request_body=None, headers=None):
    value = request_body or {**body(), "action_recovery": {"id": dto["id"], "decision": "continue"}}
    with env.app.test_request_context("/api/chat/stream", method="POST", json=value, headers=headers or env.headers):
        session["user"] = {"oid": "alice"}
        session["action_credentials_csrf_token"] = env.headers["X-CSRFToken"]
        env.recovery.validate_recovery_agent(env.agent, value)
        result = env.recovery.apply_action_recovery(env.actions)
    return result


def test_recovery_blocks_and_projects_only_safe_authorized_diagnostics(recovery_env):
    env = recovery_env
    original = deepcopy(env.actions)
    dto = challenge(env)
    assert dto["type"] == "action_recovery_required"
    assert dto["all_actions_unavailable"] is False
    assert len(dto["actions"]) == 1
    assert dto["actions"][0]["edit_url"] == "/v2/workspace/actions/calendar"
    assert "PRIVATE-SECRET" not in json.dumps(dto)
    assert "PRIVATE-PROMPT" not in json.dumps(dto)
    assert env.actions == original
    assert env.sent == []
    raw = env.state.read("alice", dto["id"], record_type="action_recovery")
    assert type(raw) is dict and raw["_etag"]


def test_explicit_continue_is_request_local_and_single_use(recovery_env):
    from action_runtime_contracts import ActionRecoveryError

    env = recovery_env
    dto = challenge(env)
    result = admitted(env, dto)
    assert result == [env.healthy]
    assert len(env.actions) == 2
    with pytest.raises(ActionRecoveryError):
        admitted(env, dto)


@pytest.mark.parametrize("change", ["prompt", "agent", "manifest", "csrf", "conversation"])
def test_changed_or_forged_decisions_do_not_grant_exclusions(recovery_env, change):
    from action_runtime_contracts import ActionRecoveryError

    env = recovery_env
    dto = challenge(env)
    request_body = {**body(), "action_recovery": {"id": dto["id"], "decision": "continue"}}
    headers = env.headers
    if change == "prompt":
        request_body["message"] = "different"
    elif change == "agent":
        env.agent["instructions"] = "changed"
    elif change == "manifest":
        env.action["additionalFields"]["m365_capabilities"]["create_calendar_invite"] = False
    elif change == "csrf":
        headers = {"X-CSRFToken": "forged"}
    else:
        env.allowed.conversation = False
    with pytest.raises((ActionRecoveryError, PermissionError)):
        admitted(env, dto, request_body=request_body, headers=headers)


def test_expiry_and_cross_actor_reads_are_refused(recovery_env):
    env = recovery_env
    dto = challenge(env)
    with env.client.session_transaction() as browser:
        browser["user"] = {"oid": "mallory"}
    response = env.client.get(f"/api/action-recovery/{dto['id']}")
    assert response.status_code == 404
    with env.client.session_transaction() as browser:
        browser["user"] = {"oid": "alice"}
    item = env.state.read("alice", dto["id"], record_type="action_recovery")
    env.state.replace("alice", item, {"expires_at": time.time() - 1}, item["_etag"])
    response = env.client.get(f"/api/action-recovery/{dto['id']}")
    assert response.status_code == 410


def test_reports_are_explicit_deduplicable_and_never_include_private_content(recovery_env):
    env = recovery_env
    dto = challenge(env)
    path = f"/api/action-recovery/{dto['id']}/report"
    payload = {"action_key": dto["actions"][0]["key"]}
    for _ in range(2):
        response = env.client.post(path, json=payload, headers=env.headers)
        assert response.status_code == 200
        assert response.get_json() == {"reported": True}
    assert env.sent[0]["idempotency_key"] == env.sent[1]["idempotency_key"]
    assert env.sent[0]["strict"] is True
    assert env.sent[0]["assignment"] == {"personal_workspace_owner_id": "alice"}
    report = json.dumps(env.sent)
    assert "PRIVATE-SECRET" not in report and "PRIVATE-PROMPT" not in report
    assert '"conversation_id"' not in report


def test_uncertain_report_delivery_is_not_shown_as_reported(recovery_env):
    env = recovery_env
    dto = challenge(env)
    env.delivery.fail = True
    path = f"/api/action-recovery/{dto['id']}/report"
    payload = {"action_key": dto["actions"][0]["key"]}
    response = env.client.post(path, json=payload, headers=env.headers)
    assert response.status_code == 503
    assert "PRIVATE-provider" not in response.get_data(as_text=True)
    first_key = env.sent[0]["idempotency_key"]
    env.delivery.fail = False
    response = env.client.post(path, json=payload, headers=env.headers)
    assert response.get_json() == {"reported": True}
    assert env.sent[-1]["idempotency_key"] == first_key


def test_current_permission_is_required_for_reporting_and_editor_links(recovery_env):
    env = recovery_env
    dto = challenge(env)
    env.allowed.action = False
    response = env.client.post(f"/api/action-recovery/{dto['id']}/report",
        json={"action_key": dto["actions"][0]["key"]}, headers=env.headers)
    assert response.status_code == 404
    assert not env.sent


def test_group_and_global_remediation_use_actual_action_scope_and_role(recovery_env):
    from functions_action_manifest import bind_action_origin

    env = recovery_env
    with env.app.test_request_context():
        session["user"] = {"oid": "alice", "roles": []}
        group = bind_action_origin({"id": "action", "type": "http"}, "group", "team")
        env.allowed.group_role = "User"
        result = env.recovery._remediation(group, "alice")
        assert "edit_url" not in result and result["can_report"]
        env.allowed.group_role = "Admin"
        result = env.recovery._remediation(group, "alice")
        assert result["edit_url"] == "/v2/groups/team/actions/action"
        env.settings["require_owner_for_group_agent_management"] = True
        result = env.recovery._remediation(group, "alice")
        assert "edit_url" not in result
        global_action = bind_action_origin({"id": "global-action", "type": "http"}, "global", "global")
        result = env.recovery._remediation(global_action, "alice")
        assert "edit_url" not in result and result["can_report"]
        session["user"]["roles"] = ["Admin"]
        result = env.recovery._remediation(global_action, "alice")
        assert result["edit_url"] == "/v2/admin/actions/global-action"


def test_routes_require_csrf_and_exact_report_shape(recovery_env):
    env = recovery_env
    dto = challenge(env)
    response = env.client.post("/api/chat/action-health", json={"request": body()})
    assert response.status_code == 403
    response = env.client.post(f"/api/action-recovery/{dto['id']}/report",
        json={"action_key": dto["actions"][0]["key"], "recipient": "mallory"}, headers=env.headers)
    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert not env.sent


def test_changed_action_revision_refuses_an_old_report(recovery_env):
    env = recovery_env
    dto = challenge(env)
    env.action["description"] = "Changed after the incident."
    response = env.client.post(f"/api/action-recovery/{dto['id']}/report",
        json={"action_key": dto["actions"][0]["key"]}, headers=env.headers)
    assert response.status_code == 409
    assert not env.sent


def test_recovered_draft_is_restored_but_not_sent(recovery_env, monkeypatch):
    env = recovery_env
    dto = challenge(env)
    monkeypatch.setattr(sys.modules["semantic_kernel_loader"], "load_agent_specific_plugins", lambda *args, **kwargs: None)
    response = env.client.get(f"/api/action-recovery/{dto['id']}")
    assert response.status_code == 200
    restored = response.get_json()
    assert restored["recovery"]["ready"] is True
    assert restored["recovery"]["actions"] == []
    assert restored["pending_body"] == body()
    item = env.state.read("alice", dto["id"], record_type="action_recovery")
    assert item["status"] == "pending"
    assert not env.sent


def test_new_failure_requires_another_decision_and_all_unavailable_is_disclosed(recovery_env):
    env = recovery_env
    dto = challenge(env)
    env.action["_simplechat_load_failure"] = True
    with pytest.raises(PermissionError):
        admitted(env, dto)
    with env.app.test_request_context():
        session["user"] = {"oid": "alice"}
        from action_runtime_contracts import ActionLoadRequired

        error = ActionLoadRequired(env.actions, [env.binding_key(action) for action in env.actions])
        projected = env.recovery.recovery_payload(error, body(), check_only=True)
    assert projected["all_actions_unavailable"] is True
    assert len(projected["actions"]) == 2


def test_same_http_request_can_reuse_its_claim_but_etag_races_cannot(recovery_env, monkeypatch):
    from action_credential_contracts import ActionCredentialError

    env = recovery_env
    dto = challenge(env)
    value = {**body(), "action_recovery": {"id": dto["id"], "decision": "continue"}}
    with env.app.test_request_context(json=value, headers=env.headers):
        session["user"] = {"oid": "alice"}
        session["action_credentials_csrf_token"] = env.headers["X-CSRFToken"]
        first = env.recovery.apply_action_recovery(env.actions)
        second = env.recovery.apply_action_recovery(env.actions)
        assert first == second == [env.healthy]
    dto = env.client.post("/api/chat/action-health",
        json={"request": {**body(), "action_recovery_nonce": "new-turn"}}, headers=env.headers).get_json()
    original = env.container.replace_item
    attempts = []

    def race(item_id, **kwargs):
        if kwargs["body"].get("status") == "continued":
            attempts.append("continued")
            raise env.state.CosmosHttpResponseError(status_code=412, message="Concurrent decision.")
        return original(item_id, **kwargs)

    monkeypatch.setattr(env.container, "replace_item", race)
    with pytest.raises(ActionCredentialError):
        admitted(env, dto, request_body={
            **body(), "action_recovery_nonce": "new-turn",
            "action_recovery": {"id": dto["id"], "decision": "continue"},
        })
    assert attempts == ["continued"]
    current = env.state.read("alice", dto["id"], record_type="action_recovery")
    assert current["status"] == "pending"


@pytest.mark.parametrize("scope", ["group", "global"])
def test_reports_target_current_managers_not_the_group_audience(recovery_env, scope):
    from functions_action_manifest import bind_action_origin

    env = recovery_env
    # Change the trusted source before producing the incident.
    action = bind_action_origin(dict(env.action), scope, "team" if scope == "group" else "global")
    env.action.clear()
    env.action.update(action)
    env.action._action_origin = action._action_origin
    dto = challenge(env)
    response = env.client.post(f"/api/action-recovery/{dto['id']}/report",
        json={"action_key": dto["actions"][0]["key"]}, headers=env.headers)
    assert response.status_code == 200
    if scope == "group":
        assert {item["user_id"] for item in env.sent} == {"owner", "manager"}
        assert all(item["assignment"] is None for item in env.sent)
    else:
        assert env.sent[0]["assignment"] == {"roles": ["Admin"]}


@pytest.mark.parametrize("interaction", ["credentials", "sign_in"])
def test_health_defers_supported_authentication_to_the_existing_send_flow(recovery_env, monkeypatch, interaction):
    from action_credential_contracts import ActionCredentialsRequired
    from m365_interaction import M365SignInRequired

    env = recovery_env
    failure = (ActionCredentialsRequired({"id": "private-credential-request"}) if interaction == "credentials"
               else M365SignInRequired("m365_reconnect_required"))

    def blocked(*args, **kwargs):
        raise failure

    monkeypatch.setattr(sys.modules["semantic_kernel_loader"], "load_agent_specific_plugins", blocked)
    response = env.client.post("/api/chat/action-health", json={"request": body()}, headers=env.headers)
    assert response.status_code == 200
    assert response.get_json()["state"] == "not_checked"
    assert "private-credential-request" not in response.get_data(as_text=True)
    assert env.container.items == {}
    with env.app.test_request_context("/api/chat/stream", method="POST", json=body()):
        session["user"] = {"oid": "alice"}
        with pytest.raises(type(failure)):
            env.recovery.check_chat_actions(body(), admit=True)


def test_shared_admission_is_fail_closed_and_never_creates_a_personal_replay(recovery_env, monkeypatch):
    from action_runtime_contracts import ActionLoadRequired, ActionRecoveryError

    env = recovery_env
    value = {**body(), "m365_collaboration_message_id": "shared-turn"}
    env.allowed.conversation = False
    with env.app.test_request_context("/api/chat/stream", method="POST", json=value):
        session["user"] = {"oid": "alice"}
        with pytest.raises(ActionLoadRequired):
            env.recovery.check_chat_actions(value, admit=True)
        with pytest.raises(ActionRecoveryError):
            env.recovery.check_chat_actions({
                **value, "action_recovery": {"id": "forged", "decision": "continue"},
            }, admit=True)
        monkeypatch.setattr(sys.modules["semantic_kernel_loader"], "load_agent_specific_plugins", lambda *args, **kwargs: None)
        healthy = env.recovery.check_chat_actions(value, admit=True)
    assert healthy["state"] == "ready"
    assert env.container.items == {}


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_actual_chat_routes_pause_before_kernel_initialization_or_user_persistence(endpoint):
    from test_orchestration_result_imports import run_probe

    probe = r'''
import json, os, sys
from copy import deepcopy
from unittest.mock import Mock, patch
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

def check(value, message):
    if not value:
        raise AssertionError(message)

with patch.dict(os.environ, {"TENANT_ID": "fixture-tenant"}), offline_app_imports() as environment:
    import app as web
    import config
    import functions_action_catalog as catalog
    import functions_action_credential_state as state
    import functions_settings
    import functions_authentication as authentication
    import route_backend_chats as chats
    import semantic_kernel_loader as loader
    from action_runtime_contracts import ActionLoadRequired, action_binding_key
    from functions_action_manifest import bind_action_origin
    from test_action_personal_credentials import CredentialContainer
    from flask import session

    settings = {
        **functions_settings.get_settings(), "enable_semantic_kernel": True,
        "per_user_semantic_kernel": True, "allow_user_agents": True,
        "allow_user_plugins": True, "enable_user_workspace": True,
        "enable_content_safety": False, "enable_key_vault_secret_storage": False,
        "azure_openai_gpt_authentication_type": "key",
        "azure_openai_gpt_endpoint": "https://model.example.invalid",
        "azure_openai_gpt_api_version": "2024-10-21", "azure_openai_gpt_key": "fixture-only-key",
        "gpt_model": {"selected": [{"deploymentName": "fixture-model"}]},
    }
    agent = {"id": "fixture-agent", "name": "Fixture", "agent_type": "local",
             "actions_to_load": ["unavailable"]}
    action = bind_action_origin({
        "id": "unavailable", "name": "FED-calendar", "type": "m365_calendar",
    }, "personal", "owner")
    state.configure_action_credential_state(CredentialContainer("user_id"))
    with web.app.test_request_context():
        session["user"] = {"oid": "owner", "roles": ["User"]}
        chats._create_personal_conversation("owner", "recovery-web-chat")
    blocked = Mock(side_effect=AssertionError("Kernel initialization ran before the decision."))
    failed = Mock(side_effect=ActionLoadRequired([action], [action_binding_key(action)]))
    with patch.object(functions_settings, "get_settings", return_value=settings), \
         patch.object(chats, "get_settings", return_value=settings), \
         patch.object(chats, "_resolve_canonical_chat_agent", side_effect=lambda *args: deepcopy(agent)), \
         patch.object(authentication, "get_user_profile_image", return_value=None), \
         patch.object(catalog, "resolve_action_manifest", side_effect=lambda *args: deepcopy(action)), \
         patch.object(loader, "load_agent_core_plugins", return_value=None), \
         patch.object(loader, "load_agent_specific_plugins", failed), \
         patch.object(chats, "initialize_semantic_kernel", blocked):
        client = web.app.test_client()
        with client.session_transaction() as browser:
            browser["user"] = {"oid": "owner", "roles": ["User"]}
        context = client.get("/api/action-recovery/context")
        check(context.status_code == 200, "Recovery context was not authenticated.")
        headers = {"X-CSRFToken": context.get_json()["csrf_token"]}
        response = client.post(sys.argv[3], headers=headers, json={
            "conversation_id": "recovery-web-chat", "message": "PRIVATE unsent question",
            "agent_info": {"id": agent["id"], "name": agent["name"]},
        })
        text = response.get_data(as_text=True)
        if sys.argv[3] == "/api/chat":
            check(response.status_code == 409, "Nonstream route did not stop for recovery: " + text[-500:])
            event = response.get_json()
        else:
            check(response.status_code == 200, "Stream admission failed: " + text[-500:])
            events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
            event = next((value for value in events if value.get("type") == "action_recovery_required"), None)
        check(event and event["type"] == "action_recovery_required", "Route did not publish explicit recovery: " + text[-500:])
        check(event["all_actions_unavailable"], "Route hid the complete loss of capabilities.")
        check("PRIVATE unsent question" not in text, "Recovery event leaked its private checkpoint.")
        check(blocked.call_count == 0, "A kernel/model was initialized before the decision.")
        check(failed.call_count == 1, "Admission retried the failed loader.")
        check(not chats.cosmos_messages_container.items, "An unsent user turn was persisted.")
        incident = state.read("owner", event["id"], record_type="action_recovery")
        check(incident["status"] == "pending", "Route consumed consent without a choice.")
    check(not environment.network_attempts, "Admission attempted external I/O.")
print("PASS: actual chat admission preserves the unsent turn without starting a model")
'''
    run_probe(probe, (endpoint,), False)
