# test_action_auth_service_continuation.py
"""Functional tests for new-chat continuation and private identity refresh.

Version: 0.261.107
Implemented in: 0.261.107

A null preflight can materialize once into its actor's unstarted personal chat.
Check again refreshes private identity metadata without changing the approved
action, destination, profile, or execution selection.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

import pytest

from test_action_auth_service_support import SECRET, auth_environment


@pytest.fixture
def env():
    with auth_environment() as environment:
        yield environment


def new_conversation(env, identifier="new-chat", actor="alice"):
    return env.conversations.put({"id": identifier, "user_id": actor, "chat_type": "new"})


def ready_selection(env, *, agent=False):
    action = env.add_action()
    env.connect("alice", action)
    selection = {"agent_info": env.add_agent([action["id"]])} if agent else {"action_ref": env.action_ref(action)}
    ready = env.state.preflight_action_auth("alice", {**selection, "conversation_id": None})
    assert ready["status"] == "ready"
    return action, selection, ready


def payload(selection, ready, conversation_id="new-chat"):
    return {
        **selection, "conversation_id": conversation_id, "action_auth_request_id": ready["request_id"],
        "message": SECRET, "history": [{"role": "user", "content": SECRET}],
    }


@pytest.mark.parametrize("agent", [False, True])
def test_null_preflight_materializes_once_into_owned_personal_chat(env, agent):
    _, selection, ready = ready_selection(env, agent=agent)
    new_conversation(env)
    result = env.state.authorize_action_auth_execution("alice", payload(selection, ready))
    assert result["receipt_id"]
    stored = env.state_store.read_item(item=ready["request_id"], partition_key="alice")
    assert stored["status"] == "claimed"
    assert stored["snapshot"]["conversation"] == {
        "id": "new-chat", "kind": "personal", "source_id": "new-chat", "owner_user_id": "alice",
    }
    assert stored["snapshot"]["selection"]["conversation_id"] == "new-chat"
    assert SECRET not in json.dumps(env.state_store.writes)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", payload(selection, ready))


def test_initial_draft_attachments_do_not_block_new_chat_materialization(env):
    _, selection, ready = ready_selection(env)
    new_conversation(env)
    for role in ("file", "image", "image_chunk"):
        env.messages.put({"id": role, "conversation_id": "new-chat", "role": role, "content": SECRET})
    assert env.state.authorize_action_auth_execution("alice", payload(selection, ready))["receipt_id"]
    assert all(query["query"].startswith("SELECT TOP 1 c.id") for query in env.messages.queries)
    assert SECRET not in json.dumps(env.state_store.writes)


@pytest.mark.parametrize("role", ["user", "assistant", "system", "tool", None])
def test_null_preflight_cannot_move_into_an_existing_chat_turn(env, role):
    _, selection, ready = ready_selection(env)
    new_conversation(env)
    message = {"id": "prior-message", "conversation_id": "new-chat", "content": SECRET}
    if role:
        message["role"] = role
    env.messages.put(message)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", {
            **payload(selection, ready), "new_chat": True, "skip_action_auth": True,
        })
    stored = env.state_store.read_item(item=ready["request_id"], partition_key="alice")
    assert stored["status"] == "pending" and stored["snapshot"]["conversation"]["id"] is None
    assert SECRET not in json.dumps(env.state_store.writes)


def test_null_preflight_cannot_bind_another_actors_conversation(env):
    _, selection, ready = ready_selection(env)
    new_conversation(env, actor="bob")
    with pytest.raises(PermissionError):
        env.state.authorize_action_auth_execution("alice", payload(selection, ready))
    assert not env.messages.queries


@pytest.mark.parametrize("visible", [True, False])
def test_null_personal_preflight_cannot_silently_become_shared(env, visible):
    _, selection, ready = ready_selection(env)
    env.shared_conversations.put({
        "id": "shared", "source_conversation_id": "source", "created_by_user_id": "alice",
        "participants": ["alice", "bob"],
    })
    env.conversations.put({"id": "source", "user_id": "alice", "collaboration_conversation_id": "shared"})
    request = payload(selection, ready, "shared" if visible else "source")
    if visible:
        request["conversation_kind"] = "collaboration"
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", request)
    assert not env.messages.queries


def test_null_transition_does_not_permit_changed_selection_or_configuration(env):
    action, selection, ready = ready_selection(env)
    new_conversation(env)
    other = env.add_action(endpoint="https://other.example")
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", payload(
            {"action_ref": env.action_ref(other)}, ready,
        ))
    action["additionalFields"]["instance"] = "different-instance"
    env.actions["global"].put(action)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", payload(selection, ready))
    assert not env.messages.queries


def test_unclaimed_materialization_pins_conversation_for_the_later_stream(env):
    _, selection, ready = ready_selection(env)
    new_conversation(env)
    new_conversation(env, "other-chat")
    assert env.state.authorize_action_auth_execution("alice", payload(selection, ready), claim=False)["receipt_id"] is None
    stored = env.state_store.read_item(item=ready["request_id"], partition_key="alice")
    assert stored["status"] == "pending" and stored["snapshot"]["conversation"]["id"] == "new-chat"
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", payload(selection, ready, "other-chat"))
    env.messages.put({"id": "prepared-message", "conversation_id": "new-chat", "role": "user", "content": SECRET})
    assert env.state.authorize_action_auth_execution("alice", payload(selection, ready))["receipt_id"]


def test_existing_conversation_preflight_cannot_switch_to_another_empty_chat(env):
    action = env.add_action()
    env.connect("alice", action)
    new_conversation(env, "original")
    new_conversation(env, "new-chat")
    selection = {"action_ref": env.action_ref(action)}
    ready = env.state.preflight_action_auth("alice", {**selection, "conversation_id": "original"})
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.authorize_action_auth_execution("alice", payload(selection, ready))


def test_failed_history_lookup_never_allows_materialization(env):
    _, selection, ready = ready_selection(env)
    new_conversation(env)
    env.messages.fail_query = True
    with pytest.raises(env.contract.ActionAuthStorageError):
        env.state.authorize_action_auth_execution("alice", payload(selection, ready))
    assert env.state_store.read_item(item=ready["request_id"], partition_key="alice")["status"] == "pending"


def test_conversation_mutation_during_history_check_fails_closed(env):
    _, selection, ready = ready_selection(env)
    new_conversation(env)
    original = env.messages.query_items

    def change_owner(**kwargs):
        env.conversations.put({"id": "new-chat", "user_id": "bob", "chat_type": "new"})
        return original(**kwargs)

    with patch.object(env.messages, "query_items", side_effect=change_owner):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.state.authorize_action_auth_execution("alice", payload(selection, ready))
    assert env.state_store.read_item(item=ready["request_id"], partition_key="alice")["status"] == "pending"


def test_concurrent_materializations_claim_only_one_conversation(env):
    _, selection, ready = ready_selection(env)
    for identifier in ("first", "second"):
        new_conversation(env, identifier)
    barrier = threading.Barrier(2)
    original = env.state._revalidate

    def revalidate(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result

    def claim(identifier):
        try:
            return env.state.authorize_action_auth_execution("alice", payload(selection, ready, identifier))
        except env.contract.ActionAuthConflict:
            return "conflict"

    with patch.object(env.state, "_revalidate", side_effect=revalidate), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, identifier) for identifier in ("first", "second")]
        results = [future.result() for future in futures]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("conflict") == 1
    stored = env.state_store.read_item(item=ready["request_id"], partition_key="alice")
    assert stored["status"] == "claimed"
    assert stored["snapshot"]["conversation"]["id"] in ("first", "second")


def test_check_again_discovers_new_manual_identity_without_reading_credentials(env):
    action = env.add_action()
    client = env.client()
    state = client.post("/api/action-auth/preflight", json={"action_ref": env.action_ref(action)}).json
    identity = env.identity()
    response = client.get(f"/api/action-auth/requests/{state['request_id']}")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["requirements"][0]["reason"] == "approval_required"
    assert response.json["requirements"][0]["identities"][0]["id"] == identity["id"]
    assert env.personal_identities.secret_reads == 0
    assert SECRET not in response.get_data(as_text=True)


def test_check_again_refreshes_manual_identity_revision_before_explicit_probe(env):
    action, identity = env.add_action(), env.identity()
    state = env.state.preflight_action_auth("alice", {"action_ref": env.action_ref(action)})
    updated = env.identities.update_workspace_identity("personal", "alice", identity["id"], {
        "credentials": {"auth_type": "username_password", "password": "manually-updated-password"},
    }, "alice", expected_etag=identity["_etag"])
    response = env.state.get_action_auth_request("alice", state["request_id"])
    assert response["status"] == "credentials_required"
    stored = env.state_store.read_item(item=state["request_id"], partition_key="alice")
    assert stored["candidate_revisions"][action["credential_requirement"]["id"]][identity["id"]] == updated["_etag"]
    assert not env.validation_calls
    response = env.state.save_action_auth_credentials("alice", state["request_id"], {
        "requirement_id": action["credential_requirement"]["id"], "identity_id": identity["id"], "confirm_destination": True,
    })
    assert response["status"] == "ready"
    assert env.validation_calls[-1][1]["password"] == "manually-updated-password"


def test_check_again_can_repair_deleted_previously_saved_identity(env):
    action = env.add_action()
    ready = env.connect("alice", action)
    identity = next(iter(env.personal_identities.records.values()))
    env.identities.delete_workspace_identity("personal", "alice", identity["id"], "alice")
    response = env.state.get_action_auth_request("alice", ready["request_id"])
    assert response["status"] == "credentials_required"
    assert response["requirements"][0]["reason"] == "missing"
    stored = env.state_store.read_item(item=ready["request_id"], partition_key="alice")
    assert not stored["binding_receipts"] and not stored["saved_requirements"]
    response = env.state.save_action_auth_credentials("alice", ready["request_id"], {
        "requirement_id": action["credential_requirement"]["id"], "confirm_destination": True,
        "credentials": {"username": "alice", "password": "replacement-password"},
    })
    assert response["status"] == "ready"


def test_check_again_never_refreshes_an_action_destination_change(env):
    action = env.add_action()
    state = env.state.preflight_action_auth("alice", {"action_ref": env.action_ref(action)})
    before = deepcopy(env.state_store.records)
    action["endpoint"] = "https://changed.example"
    action["additionalFields"]["server_url"] = action["endpoint"]
    env.actions["global"].put(action)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.get_action_auth_request("alice", state["request_id"])
    assert env.state_store.records == before


def test_check_again_does_not_clear_provider_rejection(env):
    action = env.add_action()
    ready = env.connect("alice", action)
    invocation = env.execution.AgentExecutionFrame(env.execution.ExecutionIdentity("alice"), {}, env.execution.DelegationBudget())
    with env.execution.agent_execution(invocation):
        env.contract.resolve_action_auth_credentials(action)
        env.contract.invalidate_action_auth_credentials(action)
    calls = len(env.validation_calls)
    response = env.state.get_action_auth_request("alice", ready["request_id"])
    assert response["status"] == "credentials_required"
    assert response["requirements"][0]["reason"] == "authentication_rejected"
    assert len(env.validation_calls) == calls
