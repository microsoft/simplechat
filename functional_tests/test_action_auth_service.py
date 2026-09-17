# test_action_auth_service.py
"""Functional tests for private authentication APIs and authorized selection.

Version: 0.261.107
Implemented in: 0.261.107

Exercises real Flask routes, raw governed action discovery, collaboration source
mapping, and bounded delegation/orchestration requirement collection.
"""

import json
import uuid
from copy import deepcopy

import pytest
from flask import session

from test_action_auth_service_support import (
    SECRET,
    YamcsAuthenticationError,
    YamcsConnectionError,
    YamcsPermissionError,
    auth_environment,
)


@pytest.fixture
def env():
    with auth_environment() as environment:
        yield environment


def preflight(client, env, action, **context):
    return client.post("/api/action-auth/preflight", json={"action_ref": env.action_ref(action), **context})


def save(client, state, action, **values):
    return client.post(f"/api/action-auth/requests/{state['request_id']}/credentials", json={
        "requirement_id": action["credential_requirement"]["id"], "confirm_destination": True,
        "credentials": {"username": "private-user", "password": SECRET}, **values,
    })


def test_routes_authenticate_actor_and_are_never_cacheable(env):
    action = env.add_action()
    guest = preflight(env.client(None), env, action)
    assert guest.status_code == 401
    assert guest.headers["Cache-Control"] == "no-store"
    client = env.client()
    response = preflight(client, env, action)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["requirements"][0]["auth_type"] == "username_password"
    stored = save(client, response.json, action)
    assert stored.status_code == 200 and stored.json["status"] == "ready"
    assert SECRET not in json.dumps(stored.json)
    assert SECRET not in json.dumps(env.state_store.writes)
    assert len(env.personal_identities.records) == 1


def test_private_requests_are_not_readable_or_mutable_by_other_participants(env):
    action = env.add_action()
    alice, bob = env.client("alice"), env.client("bob")
    state = preflight(alice, env, action).json
    url = f"/api/action-auth/requests/{state['request_id']}"
    for response in (bob.get(url), bob.post(f"{url}/cancel", json={}), save(bob, state, action)):
        assert response.status_code == 404
        assert response.headers["Cache-Control"] == "no-store"
        assert not response.json.get("requirements")
    assert not env.validation_calls


@pytest.mark.parametrize("field,value", [
    ("user_id", "bob"), ("owner_id", "bob"), ("message", SECRET),
    ("credentials", {"password": SECRET}), ("schema", {"fields": []}), ("url", "https://attacker.example"),
])
def test_preflight_rejects_nonselection_fields(env, field, value):
    action = env.add_action()
    response = preflight(env.client(), env, action, **{field: value})
    assert response.status_code == 400
    assert SECRET not in response.get_data(as_text=True)
    assert not env.state_store.records


@pytest.mark.parametrize("values", [
    {"confirm_destination": False}, {"target_url": "https://attacker.example"},
    {"user_id": "bob"}, {"fields": []},
    {"credentials": {"username": "alice", "password": SECRET, "auth_type": "username_password"}},
    {"credentials": {"username": "alice", "password": SECRET, "endpoint": "https://attacker.example"}},
])
def test_credentials_endpoint_rejects_owner_url_schema_and_extra_form_values(env, values):
    action, client = env.add_action(), env.client()
    state = preflight(client, env, action).json
    response = save(client, state, action, **values)
    assert response.status_code == 400
    assert not env.validation_calls and not env.personal_identities.records


@pytest.mark.parametrize("error,status,code", [
    (YamcsAuthenticationError, 422, "action_auth_rejected"),
    (YamcsPermissionError, 403, "action_auth_permission_denied"),
    (YamcsConnectionError, 503, "action_auth_connection_failed"),
])
def test_safe_type_specific_connector_failures(env, error, status, code):
    action, client = env.add_action(), env.client()
    state = preflight(client, env, action).json

    def reject(*args):
        raise error(SECRET)

    env.validation_hook = reject
    response = save(client, state, action)
    assert response.status_code == status
    assert response.json["error_code"] == code
    assert SECRET not in response.get_data(as_text=True)
    assert SECRET not in str(env.log_event.call_args_list)
    assert response.headers["Cache-Control"] == "no-store"
    assert not env.personal_identities.records


def test_storage_failure_has_explicit_safe_error(env):
    action, client = env.add_action(), env.client()
    state = preflight(client, env, action).json
    env.settings["enable_key_vault_secret_storage"] = True
    response = save(client, state, action)
    assert response.status_code == 503
    assert response.json["error_code"] == "action_auth_storage_unavailable"
    assert not env.personal_identities.records
    env.config.cosmos_personal_action_auth_container = None
    response = preflight(client, env, action)
    assert response.status_code == 503
    assert "unavailable" in response.json["error"]


def test_identity_cosmos_failures_are_safe_storage_outcomes(env):
    action, client = env.add_action(), env.client()
    state = preflight(client, env, action).json
    env.personal_identities.fail_create = True
    response = save(client, state, action)
    assert response.status_code == 503
    assert response.json["error_code"] == "action_auth_storage_unavailable"
    assert SECRET not in response.get_data(as_text=True)
    assert not env.personal_identities.records


def test_no_requirement_is_ready_without_a_state_store_or_identity_permission(env):
    legacy = env.actions["global"].put({
        "id": str(uuid.uuid4()), "name": "Existing anonymous action", "type": "yamcs",
        "endpoint": "http://localhost:8090", "auth": {"type": "NoAuth"},
    })
    env.config.cosmos_personal_action_auth_container = None
    env.settings.update(allow_user_plugins=False, enable_user_workspace=False)
    response = preflight(env.client(), env, legacy)
    assert response.status_code == 200
    assert response.json == {
        "status": "ready", "request_id": None, "uses_personal_credentials": False,
        "shared_conversation": False, "sharing_notice": None, "requirements": [],
    }
    assert env.state.authorize_action_auth_execution("alice", {"action_ref": env.action_ref(legacy), "message": SECRET}) is None
    assert env.personal_identities.secret_reads == 0


def test_missing_execution_requirement_creates_private_control_not_chat_state(env):
    action = env.add_action()
    with env.app.test_request_context():
        session["user"] = {"oid": "bob", "roles": ["User"]}
        with pytest.raises(env.contract.ActionCredentialsRequired) as error:
            env.state.authorize_action_auth_execution("bob", {
                "action_ref": env.action_ref(action), "message": SECRET, "messages": [{"role": "user", "content": SECRET}],
            })
    response = error.value.to_payload()
    assert response["request_id"] and response["requirements"]
    assert response["error_code"] == "action_credentials_required"
    assert SECRET not in json.dumps(env.state_store.writes)
    assert not env.conversations.records


def test_personal_conversation_owner_is_rechecked(env):
    action = env.add_action()
    env.conversations.put({"id": "alice-conversation", "user_id": "alice"})
    response = preflight(env.client("bob"), env, action, conversation_id="alice-conversation")
    assert response.status_code == 403 and not env.state_store.records


def test_collaboration_uses_submitter_not_source_owner_and_notices_ready_state(env):
    action = env.add_action()
    env.connect("alice", action)
    env.shared_conversations.put({
        "id": "shared", "source_conversation_id": "source", "created_by_user_id": "alice",
        "participants": ["alice", "bob"],
    })
    env.conversations.put({"id": "source", "user_id": "alice", "collaboration_conversation_id": "shared"})
    bob = env.client("bob")
    state = preflight(bob, env, action, conversation_id="shared", conversation_kind="collaboration").json
    assert state["status"] == "credentials_required"
    assert state["shared_conversation"] and state["sharing_notice"] == env.contract.ACTION_AUTH_SHARING_NOTICE
    request = env.state_store.read_item(item=state["request_id"], partition_key="bob")
    assert request["user_id"] == "bob"
    assert request["snapshot"]["conversation"]["owner_user_id"] == "alice"
    assert request["snapshot"]["conversation"]["source_id"] == "source"
    ready = save(bob, state, action)
    assert ready.status_code == 200 and ready.json["status"] == "ready"
    assert ready.json["shared_conversation"] and ready.json["sharing_notice"]
    # Source IDs are resolved to the same visible actor-private conversation.
    with env.app.test_request_context():
        session["user"] = {"oid": "bob", "roles": ["User"]}
        receipt = env.state.authorize_action_auth_execution("bob", {
            "action_ref": env.action_ref(action), "conversation_id": "source",
            "action_auth_request_id": state["request_id"],
        })
    assert receipt["receipt_id"]
    assert env.validation_calls[-1][1]["username"] == "private-user"


def test_membership_revocation_invalidates_card_before_secret_delivery(env):
    action = env.add_action()
    env.shared_conversations.put({"id": "shared", "created_by_user_id": "alice", "participants": ["alice", "bob"]})
    client = env.client("bob")
    state = preflight(client, env, action, conversation_id="shared", conversation_kind="collaboration").json
    env.shared_conversations.put({"id": "shared", "created_by_user_id": "alice", "participants": ["alice"]})
    response = save(client, state, action)
    assert response.status_code == 403 and not env.validation_calls


def test_only_assigned_actions_are_collected_without_hydrating_getters(env):
    assigned = env.add_action()
    env.add_action(name="Unrelated protected action", endpoint="https://unrelated.example")
    selection = env.add_agent([assigned["id"]])
    response = env.state.preflight_action_auth("alice", {"agent_info": selection})
    assert [item["action_id"] for item in response["requirements"]] == [assigned["id"]]
    assert env.personal_identities.secret_reads == 0
    assert "functions_global_actions" not in env.state.__dict__


def test_id_selection_never_falls_back_to_a_same_name_agent(env):
    action = env.add_action()
    selection = env.add_agent([action["id"]])
    selection["id"] = str(uuid.uuid4())
    with pytest.raises(LookupError):
        env.state.preflight_action_auth("alice", {"agent_info": selection})
    assert not env.state_store.records


def test_assigned_scoped_action_references_are_supported(env):
    action = env.add_action()
    selection = env.add_agent([env.action_ref(action)])
    state = env.state.preflight_action_auth("alice", {"agent_info": selection})
    assert [item["action_id"] for item in state["requirements"]] == [action["id"]]


def test_reachable_authorized_delegation_is_collected_and_denials_are_private(env):
    action = env.add_action()
    child = env.add_agent([action["id"]], name="Child")
    delegate = env.actions["global"].put({
        "id": str(uuid.uuid4()), "name": "call_child", "type": "agent", "endpoint": "internal://agent",
        "auth": {"type": "user"}, "additionalFields": {"target_agent": {key: child[key] for key in ("id", "scope_type", "scope_id")}},
    })
    root = env.add_agent([delegate["id"]])
    state = env.state.preflight_action_auth("alice", {"agent_info": root})
    assert state["requirements"][0]["action_id"] == action["id"]
    env.denied_agents.add(child["id"])
    denied = env.state.preflight_action_auth("alice", {"agent_info": root})
    assert denied["status"] == "ready" and not denied["requirements"] and denied["request_id"] is None
    assert "Child" not in json.dumps(denied)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.get_action_auth_request("alice", state["request_id"])


def test_cycles_and_depth_limits_do_not_collect_unreachable_actions(env):
    actions = [env.add_action(name=f"At depth {depth}", endpoint=f"https://host{depth}.example") for depth in range(5)]
    agents = [env.add_agent([action["id"]], name=f"Agent {index}") for index, action in enumerate(actions)]
    for index, parent in enumerate(agents):
        target = agents[(index + 1) % len(agents)]
        call = env.actions["global"].put({
            "id": str(uuid.uuid4()), "name": f"delegate_{index}", "type": "agent",
            "endpoint": "internal://agent", "auth": {"type": "user"},
            "additionalFields": {"target_agent": {key: target[key] for key in ("id", "scope_type", "scope_id")}},
        })
        current = env.agents["global"].read_item(item=parent["id"], partition_key=parent["id"])
        current["actions_to_load"].append(call["id"])
        env.agents["global"].put(current)
    state = env.state.preflight_action_auth("alice", {"agent_info": agents[0]})
    assert {item["action_id"] for item in state["requirements"]} == {action["id"] for action in actions[:4]}


def test_action_governance_is_rechecked_without_leaking_denied_details(env):
    action = env.add_action()
    state = env.state.preflight_action_auth("alice", {"action_ref": env.action_ref(action)})
    env.denied_actions.add(action["id"])
    response = env.client().get(f"/api/action-auth/requests/{state['request_id']}")
    assert response.status_code == 403
    assert SECRET not in response.get_data(as_text=True) and "Telemetry" not in response.get_data(as_text=True)


def test_existing_owned_plan_collects_agent_and_direct_action_requirements_only(env):
    action = env.add_action()
    agent_action = env.add_action(name="Agent tool", endpoint="https://another.example")
    agent = env.add_agent([agent_action["id"]], name="Planner-selected agent")
    env.conversations.put({"id": "conversation", "user_id": "alice"})
    env.runs["run"] = {
        "id": "run", "user_id": "alice", "conversation_id": "conversation", "revision": 1,
        "status": "awaiting_approval", "seeds": {"agent": agent},
        "user_message": SECRET, "history": [{"content": SECRET}],
        "plan": {"plan_id": "plan", "revision": 1, "steps": [
            {"id": "tool", "capability_id": "action_invoke", "arguments": {"action_ref": env.action_ref(action), "task": SECRET}},
            {"id": "agent", "capability_id": "agent_invoke", "arguments": {"agent_name": agent["name"], "task": SECRET}},
        ]},
    }
    state = env.state.preflight_action_auth("alice", {"run_id": "run"})
    assert {item["action_id"] for item in state["requirements"]} == {action["id"], agent_action["id"]}
    assert SECRET not in json.dumps(env.state_store.writes)
    with pytest.raises(PermissionError):
        env.state.preflight_action_auth("bob", {"run_id": "run"})
    env.runs["run"]["revision"] = 2
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.get_action_auth_request("alice", state["request_id"])


def test_active_run_cannot_start_another_credential_continuation(env):
    env.conversations.put({"id": "conversation", "user_id": "alice"})
    env.runs["run"] = {
        "id": "run", "user_id": "alice", "conversation_id": "conversation", "started_at": "already-started",
        "plan": {"steps": []},
    }
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.preflight_action_auth("alice", {"run_id": "run", "conversation_id": "conversation"})


def test_changed_selection_cannot_claim_an_existing_request(env):
    action, other = env.add_action(), env.add_action(endpoint="https://other.example")
    ready = env.connect("alice", action)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", {
            "action_ref": env.action_ref(other), "action_auth_request_id": ready["request_id"],
        })
