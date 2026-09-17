# test_action_auth_service_rejection.py
"""Functional tests for actor-private provider authentication rejection repair.

Version: 0.261.107
Implemented in: 0.261.107

Confirmed provider rejection invalidates only the credential revision actually
resolved by this invocation. Preflight never silently reuses a rejected revision;
only an explicit successful probe or replacement clears its rejection.
"""

import json
from contextvars import copy_context
from copy import deepcopy

import pytest
from flask import session

from test_action_auth_service_support import SECRET, YamcsAuthenticationError, auth_environment


@pytest.fixture
def env():
    with auth_environment() as environment:
        yield environment


def frame(env, actor="alice"):
    return env.execution.AgentExecutionFrame(
        env.execution.ExecutionIdentity(actor), {}, env.execution.DelegationBudget(),
    )


def preflight(env, action, actor="alice"):
    return env.state.preflight_action_auth(actor, {"action_ref": env.action_ref(action)})


def reject(env, action, actor="alice"):
    with env.execution.agent_execution(frame(env, actor)):
        env.contract.resolve_action_auth_credentials(action)
        assert env.contract.invalidate_action_auth_credentials(action) is None


def resolve_in_frame(env, action, invocation):
    with env.execution.agent_execution(invocation):
        return env.contract.resolve_action_auth_credentials(action)


def invalidate_in_frame(env, action, invocation):
    with env.execution.agent_execution(invocation):
        return env.contract.invalidate_action_auth_credentials(action)


def repair(env, action, identity_id, *, credentials=None):
    state = preflight(env, action)
    payload = {
        "requirement_id": action["credential_requirement"]["id"],
        "identity_id": identity_id,
        "confirm_destination": True,
    }
    if credentials is not None:
        payload["credentials"] = credentials
    return env.state.save_action_auth_credentials("alice", state["request_id"], payload)


def own_identity(env, actor="alice"):
    return next(
        deepcopy(record) for (owner, _), record in env.personal_identities.records.items() if owner == actor
    )


def assert_repair_needed(env, action):
    state = preflight(env, action)
    assert state["status"] == "credentials_required"
    assert state["requirements"][0]["reason"] == "authentication_rejected"
    return state


def test_confirmed_rejection_is_actor_private_metadata_only(env):
    action = env.add_action()
    env.connect("alice", action)
    env.connect("bob", action)
    identities_before = deepcopy(env.personal_identities.records)
    bob_before = {key: deepcopy(value) for key, value in env.state_store.records.items() if key[0] == "bob"}
    reads = env.personal_identities.secret_reads
    reject(env, action)
    after_resolution_reads = env.personal_identities.secret_reads
    state = assert_repair_needed(env, action)
    assert after_resolution_reads == reads + 1
    assert env.personal_identities.secret_reads == after_resolution_reads
    assert env.personal_identities.records == identities_before
    assert {key: value for key, value in env.state_store.records.items() if key[0] == "bob"} == bob_before
    assert preflight(env, action, "bob")["status"] == "ready"
    assert SECRET not in json.dumps(state)
    assert SECRET not in json.dumps(env.state_store.writes)
    assert SECRET not in str(env.log_event.call_args_list)


def test_rejection_blocks_equivalent_action_reuse_but_not_other_destinations(env):
    first, equivalent = env.add_action(), env.add_action(name="Equivalent")
    another = env.add_action(name="Other destination", endpoint="https://other.example")
    env.connect("alice", first)
    env.connect("alice", equivalent)
    identity = own_identity(env)
    repair(env, another, identity["id"])
    calls = len(env.validation_calls)
    reject(env, first)
    assert_repair_needed(env, first)
    assert_repair_needed(env, equivalent)
    assert_repair_needed(env, env.add_action(name="New equivalent"))
    assert preflight(env, another)["status"] == "ready"
    assert len(env.validation_calls) == calls


def test_runtime_rejection_control_preserves_reason_and_canonical_action(env):
    action = env.add_action()
    env.connect("alice", action)
    reject(env, action)
    invocation = frame(env)
    with env.execution.agent_execution(invocation):
        with pytest.raises(env.contract.ActionCredentialsRequired) as failure:
            env.contract.resolve_action_auth_credentials(action)
        invocation.budget.require_authentication(failure.value)
        with pytest.raises(env.contract.ActionCredentialsRequired):
            invocation.budget.raise_authentication_requirement(invocation.identity)
    assert failure.value.action_ref == env.action_ref(action)
    assert failure.value.to_payload()["requirements"][0]["reason"] == "authentication_rejected"


def test_successful_explicit_recheck_clears_rejection_without_replacing_secret(env):
    first, second = env.add_action(), env.add_action(name="Equivalent")
    env.connect("alice", first)
    env.connect("alice", second)
    identity = own_identity(env)
    reject(env, first)
    calls = len(env.validation_calls)
    assert repair(env, first, identity["id"])["status"] == "ready"
    assert len(env.validation_calls) == calls + 1
    assert own_identity(env) == identity
    for action in (first, second):
        assert preflight(env, action)["status"] == "ready"
    assert len(env.validation_calls) == calls + 1


def test_failed_explicit_recheck_keeps_rejection_and_original_secret(env):
    action = env.add_action()
    env.connect("alice", action)
    identity = own_identity(env)
    reject(env, action)

    def failure(*args):
        raise YamcsAuthenticationError(SECRET)

    env.validation_hook = failure
    with pytest.raises(env.state.ActionAuthValidationError):
        repair(env, action, identity["id"])
    assert own_identity(env) == identity
    assert_repair_needed(env, action)


def test_successful_replacement_uses_new_revision_and_unblocks_equivalent_actions(env):
    first, second = env.add_action(), env.add_action(name="Equivalent")
    env.connect("alice", first)
    env.connect("alice", second)
    identity = own_identity(env)
    reject(env, first)
    assert repair(env, first, identity["id"], credentials={
        "username": "alice", "password": "replacement-private-password",
    })["status"] == "ready"
    assert own_identity(env)["_etag"] != identity["_etag"]
    assert own_identity(env)["auth"]["password"] == "replacement-private-password"
    assert preflight(env, second)["status"] == "ready"
    assert "replacement-private-password" not in json.dumps(env.state_store.writes)


def test_late_failure_cannot_invalidate_a_newly_validated_identity_revision(env):
    action = env.add_action()
    env.connect("alice", action)
    identity = own_identity(env)
    with env.execution.agent_execution(frame(env)):
        env.contract.resolve_action_auth_credentials(action)
        env.identities.update_workspace_identity("personal", "alice", identity["id"], {
            "credentials": {"auth_type": "username_password", "password": "new-good-password"},
        }, "alice", expected_etag=identity["_etag"])
        assert repair(env, action, identity["id"])["status"] == "ready"
        bindings_before = deepcopy(env.state_store.records)
        env.contract.invalidate_action_auth_credentials(action)
        assert env.state_store.records == bindings_before
    assert preflight(env, action)["status"] == "ready"


def test_late_failure_cannot_undo_successful_probe_of_the_same_identity_revision(env):
    action = env.add_action()
    env.connect("alice", action)
    identity = own_identity(env)
    old_context, old_invocation = copy_context(), frame(env)
    old_context.run(resolve_in_frame, env, action, old_invocation)
    reject(env, action)
    assert repair(env, action, identity["id"])["status"] == "ready"
    before = deepcopy(env.state_store.records)
    assert old_context.run(invalidate_in_frame, env, action, old_invocation) is None
    assert env.state_store.records == before
    assert own_identity(env) == identity
    assert preflight(env, action)["status"] == "ready"


def test_invalidation_requires_matching_actor_and_invocation_scope(env):
    action = env.add_action()
    env.connect("alice", action)
    before = deepcopy(env.state_store.records)
    with pytest.raises(PermissionError):
        env.contract.invalidate_action_auth_credentials(action)
    with env.execution.agent_execution(frame(env, "alice")):
        env.contract.resolve_action_auth_credentials(action)
    with env.execution.agent_execution(frame(env, "bob")):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.invalidate_action_auth_credentials(action)
    assert env.state_store.records == before
    with env.app.test_request_context():
        session["user"] = {"oid": "alice", "roles": ["User"]}
        env.contract.resolve_action_auth_credentials(action)
    with env.app.test_request_context():
        session["user"] = {"oid": "alice", "roles": ["User"]}
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.invalidate_action_auth_credentials(action)
    assert env.state_store.records == before


@pytest.mark.parametrize("change", ["destination", "profile", "identity"])
def test_rebinding_failed_action_does_not_erase_rejection_for_other_bindings(env, change):
    first, second = env.add_action(), env.add_action(name="Equivalent")
    env.connect("alice", first)
    env.connect("alice", second)
    identity = own_identity(env)
    reject(env, first)
    updated = deepcopy(first)
    if change == "destination":
        updated["endpoint"] = "https://other.example"
        updated["additionalFields"]["server_url"] = updated["endpoint"]
    elif change == "profile":
        updated["credential_requirement"]["profile"] = "http_basic"
    else:
        identity = env.identity(name="Different personal account", secret="other-private-password")
    updated = env.contract.normalize_action_credential_requirement(updated)
    env.actions["global"].put(updated)
    assert repair(env, updated, identity["id"])["status"] == "ready"
    assert preflight(env, updated)["status"] == "ready"
    assert_repair_needed(env, second)


def test_explicit_probe_clears_retained_rejection_without_affecting_new_destination(env):
    first, second = env.add_action(), env.add_action(name="Equivalent")
    env.connect("alice", first)
    env.connect("alice", second)
    identity = own_identity(env)
    reject(env, first)
    updated = deepcopy(first)
    updated["endpoint"] = "https://another.example"
    updated["additionalFields"]["server_url"] = updated["endpoint"]
    env.actions["global"].put(updated)
    assert repair(env, updated, identity["id"])["status"] == "ready"
    assert_repair_needed(env, second)
    assert repair(env, second, identity["id"])["status"] == "ready"
    calls = len(env.validation_calls)
    assert preflight(env, updated)["status"] == "ready"
    assert preflight(env, second)["status"] == "ready"
    assert len(env.validation_calls) == calls
    assert own_identity(env) == identity


def test_repair_preserves_ready_bindings_in_the_same_selected_agent_request(env):
    first, second = env.add_action(), env.add_action(name="Equivalent")
    env.connect("alice", first)
    env.connect("alice", second)
    identity = own_identity(env)
    reject(env, first)
    updated = deepcopy(first)
    updated["endpoint"] = "https://another.example"
    updated["additionalFields"]["server_url"] = updated["endpoint"]
    env.actions["global"].put(updated)
    assert repair(env, updated, identity["id"])["status"] == "ready"
    agent = env.add_agent([first["id"], second["id"]])
    state = env.state.preflight_action_auth("alice", {"agent_info": agent})
    assert [required["action_id"] for required in state["requirements"]] == [second["id"]]
    response = env.state.save_action_auth_credentials("alice", state["request_id"], {
        "requirement_id": second["credential_requirement"]["id"],
        "identity_id": identity["id"],
        "confirm_destination": True,
    })
    assert response["status"] == "ready"
    receipt = env.state.authorize_action_auth_execution("alice", {
        "agent_info": agent, "action_auth_request_id": state["request_id"],
    })
    assert receipt["receipt_id"]


def test_successful_probe_does_not_erase_a_concurrently_reported_rejection(env):
    first, second, third = env.add_action(), env.add_action(name="Second"), env.add_action(name="Third")
    for action in (first, second, third):
        env.connect("alice", action)
    identity = own_identity(env)
    old_context, old_invocation = copy_context(), frame(env)
    old_context.run(resolve_in_frame, env, third, old_invocation)
    reject(env, first)

    def reject_concurrently(*args):
        old_context.run(invalidate_in_frame, env, third, old_invocation)

    env.validation_hook = reject_concurrently
    with pytest.raises(env.contract.ActionAuthConflict):
        repair(env, second, identity["id"])
    env.validation_hook = None
    assert own_identity(env) == identity
    assert_repair_needed(env, second)
    assert_repair_needed(env, third)


def test_healthy_bound_preflight_never_repeatedly_probes_the_provider(env):
    action = env.add_action()
    env.connect("alice", action)
    calls = len(env.validation_calls)
    for _ in range(3):
        assert preflight(env, action)["status"] == "ready"
    assert len(env.validation_calls) == calls
