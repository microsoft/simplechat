# test_action_auth_state.py
"""Functional tests for private credential state, ownership, and concurrency.

Version: 0.261.107
Implemented in: 0.261.107

Runs real state and identity helpers with deterministic Cosmos/Key Vault doubles,
including conditional claims, validation-before-storage, and invocation isolation.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

import pytest
from flask import session

from test_action_auth_service_support import (
    SECRET,
    YamcsAuthenticationError,
    auth_environment,
)


@pytest.fixture
def env():
    with auth_environment() as environment:
        yield environment


def credentials(action, **values):
    return {
        "requirement_id": action["credential_requirement"]["id"], "confirm_destination": True,
        "credentials": {"username": "alice-login", "password": SECRET}, **values,
    }


def pending(env, action, actor="alice"):
    return env.state.preflight_action_auth(actor, {"action_ref": env.action_ref(action)})


def test_initial_request_is_metadata_only_and_does_not_read_secrets(env):
    identity = env.identity()
    action = env.add_action()
    response = pending(env, action)
    requirement = response["requirements"][0]
    assert response["status"] == "credentials_required"
    assert requirement["reason"] == "approval_required"
    assert requirement["identities"] == [{"id": identity["id"], "name": "Yamcs", "auth_type": "username_password"}]
    assert env.personal_identities.secret_reads == 0
    assert not env.vault.reads and not env.validation_calls
    assert SECRET not in json.dumps(env.state_store.writes)
    assert "alice-login" not in json.dumps(response)
    assert "credentials" not in env.state_store.writes[-1]


@pytest.mark.parametrize("profile,auth_type,fields", [
    ("yamcs_login", "username_password", {"username", "password"}),
    ("http_basic", "username_password", {"username", "password"}),
    ("bearer_token", "bearer_token", {"secret"}),
    ("api_key", "api_key", {"secret"}),
])
def test_all_registered_profiles_bind_and_resolve_exact_native_identity_fields(env, profile, auth_type, fields):
    action = env.add_action(profile=profile)
    state = pending(env, action)
    assert {field["name"] for field in state["requirements"][0]["fields"]} == fields
    ready = env.connect("alice", action)
    assert ready["status"] == "ready"
    frame = env.execution.AgentExecutionFrame(env.execution.ExecutionIdentity("alice"), {}, env.execution.DelegationBudget())
    with env.execution.agent_execution(frame):
        credentials = env.contract.resolve_action_auth_credentials(action)
    assert set(credentials) == {"auth_type", *fields}
    assert credentials["auth_type"] == auth_type
    assert SECRET not in json.dumps(env.state_store.writes)


def test_new_destination_requires_confirmation_before_existing_identity_read(env):
    action = env.add_action()
    identity = env.identity()
    state = pending(env, action)
    with pytest.raises(ValueError):
        env.state.save_action_auth_credentials("alice", state["request_id"], {
            "requirement_id": action["credential_requirement"]["id"], "identity_id": identity["id"],
        })
    assert env.personal_identities.secret_reads == 0 and not env.validation_calls
    response = env.state.save_action_auth_credentials("alice", state["request_id"], {
        "requirement_id": action["credential_requirement"]["id"], "identity_id": identity["id"], "confirm_destination": True,
    })
    assert response["status"] == "ready"
    assert env.validation_calls[0][1]["password"] == SECRET
    assert len(env.personal_identities.records) == 1
    assert SECRET not in json.dumps(env.state_store.writes)


def test_binding_reuse_is_destination_profile_specific_and_rename_stable(env):
    action = env.add_action()
    env.connect("alice", action)
    calls = len(env.validation_calls)
    reused = env.add_action(name="Other telemetry")
    assert pending(env, reused)["status"] == "ready"
    assert len(env.validation_calls) == calls
    other_destination = env.add_action(endpoint="https://other.example")
    assert pending(env, other_destination)["requirements"][0]["reason"] == "approval_required"
    other_profile = env.add_action(profile="http_basic")
    assert pending(env, other_profile)["requirements"][0]["reason"] == "approval_required"
    action["name"] = "Renamed action"
    action["credential_requirement"]["identity_name"] = "Admin renamed requirement"
    env.actions["global"].put(action)
    assert pending(env, action)["status"] == "ready"
    assert next(iter(env.personal_identities.records.values()))["name"] == "Yamcs"


def test_equivalent_assigned_requirements_need_one_connection(env):
    first, second = env.add_action(), env.add_action(name="Archive telemetry")
    agent = env.add_agent([first["id"], second["id"]])
    state = env.state.preflight_action_auth("alice", {"agent_info": agent})
    assert len(state["requirements"]) == 2
    response = env.state.save_action_auth_credentials("alice", state["request_id"], credentials(first))
    assert response["status"] == "ready" and not response["requirements"]
    assert len(env.validation_calls) == 1
    assert len(env.personal_identities.records) == 1


def test_ambiguous_names_never_choose_or_overwrite_first_identity(env):
    first, second = env.identity(), env.identity(secret="different-synthetic-password")
    action = env.add_action()
    state = pending(env, action)
    assert state["requirements"][0]["reason"] == "ambiguous"
    env.state.save_action_auth_credentials("alice", state["request_id"], {
        "requirement_id": action["credential_requirement"]["id"], "identity_id": second["id"], "confirm_destination": True,
    })
    assert env.validation_calls[-1][1]["password"] == "different-synthetic-password"
    assert env.personal_identities.read_item(item=first["id"], partition_key="alice")["auth"]["password"] == SECRET


def test_incompatible_name_is_not_overwritten(env):
    old = env.identity(auth_type="api_key")
    action = env.add_action()
    state = pending(env, action)
    assert state["requirements"][0]["reason"] == "incompatible"
    with pytest.raises(ValueError):
        env.state.save_action_auth_credentials("alice", state["request_id"], credentials(action, identity_id=old["id"]))
    assert not env.validation_calls
    assert env.personal_identities.read_item(item=old["id"], partition_key="alice")["auth"] == old["auth"]


def test_cross_user_requests_and_identity_substitution_are_denied(env):
    action = env.add_action()
    alice = pending(env, action)
    bob_identity = env.identity("bob")
    for operation in (env.state.get_action_auth_request, env.state.cancel_action_auth_request):
        with pytest.raises(LookupError):
            operation("bob", alice["request_id"])
    with pytest.raises(LookupError):
        env.state.save_action_auth_credentials("bob", alice["request_id"], credentials(action))
    with pytest.raises(LookupError):
        env.state.save_action_auth_credentials("alice", alice["request_id"], {
            "requirement_id": action["credential_requirement"]["id"], "identity_id": bob_identity["id"], "confirm_destination": True,
        })
    assert not env.validation_calls
    assert env.personal_identities.secret_reads == 0


def test_forged_binding_owner_never_resolves_another_persons_identity(env):
    action = env.add_action()
    env.connect("bob", action)
    bob_binding = next(
        deepcopy(record) for record in env.state_store.records.values()
        if record["record_type"] == env.state.BINDING_RECORD_TYPE
    )
    required = env.state._requirement(env.catalog.resolve_action_manifest("alice", env.action_ref(action)))
    bob_binding["id"] = env.state._binding_id("alice", required["requirement_id"])
    env.state_store.records["alice", bob_binding["id"]] = bob_binding
    reads = env.personal_identities.secret_reads
    with pytest.raises(LookupError):
        pending(env, action)
    assert env.personal_identities.secret_reads == reads


def test_action_change_before_or_during_validation_does_not_store(env):
    action = env.add_action()
    state = pending(env, action)

    def change_destination(*args):
        changed = deepcopy(action)
        changed["endpoint"] = "https://other.example"
        changed["additionalFields"]["server_url"] = changed["endpoint"]
        env.actions["global"].put(changed)

    env.validation_hook = change_destination
    with pytest.raises(env.contract.ActionAuthConflict, match="changed"):
        env.state.save_action_auth_credentials("alice", state["request_id"], credentials(action))
    assert not env.personal_identities.records
    assert env.state_store.read_item(item=state["request_id"], partition_key="alice")["save_claim"] is None
    previous_calls = len(env.validation_calls)
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.save_action_auth_credentials("alice", state["request_id"], credentials(action))
    assert len(env.validation_calls) == previous_calls


def test_changed_identity_revision_fails_before_credentials_are_sent(env):
    action, identity = env.add_action(), env.identity()
    state = pending(env, action)
    env.identities.update_workspace_identity("personal", "alice", identity["id"], {
        "credentials": {"auth_type": "username_password", "password": "new-good-password"},
    }, "alice", expected_etag=identity["_etag"])
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.save_action_auth_credentials("alice", state["request_id"], {
            "requirement_id": action["credential_requirement"]["id"], "identity_id": identity["id"], "confirm_destination": True,
        })
    assert not env.validation_calls


def test_failed_validation_preserves_good_credential_and_releases_save_claim(env):
    action, identity = env.add_action(), env.identity()
    state = pending(env, action)

    def reject(*args):
        raise YamcsAuthenticationError(SECRET)

    env.validation_hook = reject
    with pytest.raises(env.state.ActionAuthValidationError) as failure:
        env.state.save_action_auth_credentials("alice", state["request_id"], credentials(
            action, identity_id=identity["id"], credentials={"username": "wrong-user", "password": "bad-password"},
        ))
    assert failure.value.code == "action_auth_rejected"
    assert SECRET not in str(failure.value)
    assert env.personal_identities.read_item(item=identity["id"], partition_key="alice") == identity
    assert env.state_store.read_item(item=state["request_id"], partition_key="alice")["save_claim"] is None


def test_duplicate_save_does_not_replace_credentials_or_revalidate(env):
    action = env.add_action()
    state = pending(env, action)
    env.state.save_action_auth_credentials("alice", state["request_id"], credentials(action))
    before = deepcopy(env.personal_identities.records)
    response = env.state.save_action_auth_credentials("alice", state["request_id"], credentials(
        action, credentials={"username": "different", "password": "different-secret"},
    ))
    assert response["status"] == "ready"
    assert env.personal_identities.records == before
    assert len(env.validation_calls) == 1


def test_conditional_save_claim_blocks_parallel_duplicate(env):
    action = env.add_action()
    state = pending(env, action)
    started, finish = threading.Event(), threading.Event()

    def validate(*args):
        started.set()
        assert finish.wait(5)

    env.validation_hook = validate
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(env.state.save_action_auth_credentials, "alice", state["request_id"], credentials(action))
        assert started.wait(5)
        try:
            with pytest.raises(env.contract.ActionAuthConflict) as error:
                env.state.save_action_auth_credentials("alice", state["request_id"], credentials(action))
            assert error.value.code == "action_auth_busy"
        finally:
            finish.set()
        assert future.result()["status"] == "ready"
    assert len(env.validation_calls) == 1 and len(env.personal_identities.records) == 1


def test_separate_request_race_cannot_overwrite_new_binding(env):
    action = env.add_action()
    first, second = pending(env, action), pending(env, action)
    barrier = threading.Barrier(2)
    env.validation_hook = lambda *args: barrier.wait(timeout=5)

    def save(state, secret):
        try:
            return env.state.save_action_auth_credentials("alice", state["request_id"], credentials(
                action, credentials={"username": "alice", "password": secret},
            ))
        except env.contract.ActionAuthConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, first, "first-good-password"), pool.submit(save, second, "second-good-password")]
        results = [future.result() for future in futures]
    assert sum(isinstance(result, dict) and result["status"] == "ready" for result in results) == 1
    assert results.count("conflict") == 1
    assert 1 <= len(env.personal_identities.records) <= 2
    bindings = [
        row for row in env.state_store.records.values()
        if row["record_type"] == "binding" and row.get("status") == "active"
    ]
    assert len(bindings) == 1
    identity = env.personal_identities.records["alice", bindings[0]["identity_id"]]
    assert bindings[0]["identity_revision"] == identity["_etag"]


def test_execution_claim_is_single_use_and_drops_chat_fields(env):
    action = env.add_action()
    ready = env.connect("alice", action)
    payload = {
        "action_ref": env.action_ref(action), "action_auth_request_id": ready["request_id"],
        "message": SECRET, "history": [{"content": SECRET}], "user_id": "bob", "credentials": SECRET,
    }
    receipt = env.state.authorize_action_auth_execution("alice", payload)
    assert receipt["receipt_id"]
    with pytest.raises(env.contract.ActionAuthConflict) as error:
        env.state.authorize_action_auth_execution("alice", payload)
    assert error.value.code == "action_auth_already_used"
    assert SECRET not in json.dumps(env.state_store.writes)


def test_parallel_continuation_only_one_claim_succeeds(env):
    action = env.add_action()
    ready = env.connect("alice", action)
    barrier = threading.Barrier(2)
    original = env.state._revalidate

    def revalidate(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result

    def claim():
        try:
            return env.state.authorize_action_auth_execution("alice", {
                "action_ref": env.action_ref(action), "action_auth_request_id": ready["request_id"],
            })
        except env.contract.ActionAuthConflict:
            return "conflict"

    with patch.object(env.state, "_revalidate", side_effect=revalidate), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim), pool.submit(claim)]
        results = [future.result() for future in futures]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("conflict") == 1


def test_cancel_is_idempotent_and_does_not_delete_saved_identity(env):
    action = env.add_action()
    ready = env.connect("alice", action)
    assert env.state.cancel_action_auth_request("alice", ready["request_id"])["status"] == "cancelled"
    assert env.state.cancel_action_auth_request("alice", ready["request_id"])["status"] == "cancelled"
    assert len(env.personal_identities.records) == 1
    with pytest.raises(env.contract.ActionAuthConflict) as error:
        env.state.authorize_action_auth_execution("alice", {
            "action_ref": env.action_ref(action), "action_auth_request_id": ready["request_id"],
        })
    assert error.value.code == "action_auth_cancelled"


def test_cancelling_inflight_validation_prevents_secret_persistence(env):
    action = env.add_action()
    state = pending(env, action)
    started, finish = threading.Event(), threading.Event()

    def validate(*args):
        started.set()
        assert finish.wait(5)

    env.validation_hook = validate
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(env.state.save_action_auth_credentials, "alice", state["request_id"], credentials(action))
        assert started.wait(5)
        try:
            assert env.state.cancel_action_auth_request("alice", state["request_id"])["status"] == "cancelled"
        finally:
            finish.set()
        with pytest.raises(env.contract.ActionAuthConflict) as error:
            future.result()
    assert error.value.code == "action_auth_cancelled"
    assert not env.personal_identities.records
    assert all(record["record_type"] == env.state.REQUEST_RECORD_TYPE for record in env.state_store.records.values())


def test_expiry_and_record_type_are_enforced(env):
    action = env.add_action()
    state = pending(env, action)
    with patch.object(env.state, "_now", return_value=env.state._now() + 901):
        with pytest.raises(env.contract.ActionAuthConflict) as error:
            env.state.get_action_auth_request("alice", state["request_id"])
    assert error.value.code == "action_auth_expired"
    ready = env.connect("bob", action)
    binding = next(record for record in env.state_store.records.values() if record["record_type"] == env.state.BINDING_RECORD_TYPE)
    assert binding["ttl"] == -1
    with pytest.raises(LookupError):
        env.state.get_action_auth_request("bob", binding["id"])
    assert ready["status"] == "ready"


def test_runtime_reloads_actor_binding_without_mutating_shared_manifest(env):
    action = env.add_action()
    env.connect("alice", action, secret="alice-private-password")
    env.connect("bob", action, secret="bob-private-password")
    original = deepcopy(action)

    def resolve(actor):
        frame = env.execution.AgentExecutionFrame(
            env.execution.ExecutionIdentity(actor), {}, env.execution.DelegationBudget(),
        )
        with env.execution.agent_execution(frame):
            return env.contract.resolve_action_auth_credentials(action)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve, ("alice", "bob")))
    assert results == [
        {"auth_type": "username_password", "username": "alice-login", "password": "alice-private-password"},
        {"auth_type": "username_password", "username": "bob-login", "password": "bob-private-password"},
    ]
    assert action == original
    assert "alice-private-password" not in json.dumps(env.state_store.writes)
    assert "bob-private-password" not in json.dumps(env.state_store.writes)


def test_runtime_actor_must_be_trusted_and_consistent(env):
    action = env.add_action()
    with pytest.raises(PermissionError):
        env.contract.resolve_action_auth_credentials(action)
    for actor in ("system", "", " alice "):
        with pytest.raises(PermissionError):
            env.state.preflight_action_auth(actor, {"action_ref": env.action_ref(action)})
    frame = env.execution.AgentExecutionFrame(env.execution.ExecutionIdentity("bob"), {}, env.execution.DelegationBudget())
    with env.app.test_request_context(), env.execution.agent_execution(frame):
        session["user"] = {"oid": "alice", "roles": ["User"]}
        with pytest.raises(PermissionError):
            env.contract.resolve_action_auth_credentials(action)


def test_runtime_revalidates_destination_after_key_vault_read(env):
    env.settings.update(enable_key_vault_secret_storage=True, key_vault_name="test-vault")
    action = env.add_action()
    env.connect("alice", action)
    original_get = env.vault.get_secret

    def retrieve(reference):
        value = original_get(reference)
        changed = deepcopy(action)
        changed["endpoint"] = "https://different.example"
        changed["additionalFields"]["server_url"] = changed["endpoint"]
        env.actions["global"].put(changed)
        return value

    frame = env.execution.AgentExecutionFrame(env.execution.ExecutionIdentity("alice"), {}, env.execution.DelegationBudget())
    with patch.object(env.vault, "get_secret", side_effect=retrieve), env.execution.agent_execution(frame):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.resolve_action_auth_credentials(action)


def test_stale_shared_plugin_instance_cannot_use_changed_runtime_target(env):
    action = env.add_action()
    env.connect("alice", action)
    changed = deepcopy(action)
    changed["additionalFields"]["instance"] = "new-instance"
    env.actions["global"].put(changed)
    reads = env.personal_identities.secret_reads
    frame = env.execution.AgentExecutionFrame(env.execution.ExecutionIdentity("alice"), {}, env.execution.DelegationBudget())
    with env.execution.agent_execution(frame):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.resolve_action_auth_credentials(action)
    assert env.personal_identities.secret_reads == reads


def test_runtime_missing_credentials_carries_canonical_control_identity(env):
    action = env.add_action()
    frame = env.execution.AgentExecutionFrame(env.execution.ExecutionIdentity("bob"), {}, env.execution.DelegationBudget())
    with env.execution.agent_execution(frame):
        with pytest.raises(env.contract.ActionCredentialsRequired) as error:
            env.contract.resolve_action_auth_credentials(action)
    assert error.value.action_ref == env.action_ref(action)
    assert error.value.auth_response["requirements"][0]["action_id"] == action["id"]
    assert not env.state_store.records


def test_noninteractive_gate_does_not_create_a_challenge(env):
    action = env.add_action()
    with pytest.raises(env.contract.ActionCredentialsRequired) as error:
        env.state.authorize_action_auth_execution("alice", {"action_ref": env.action_ref(action)})
    assert error.value.auth_response["request_id"] is None and not env.state_store.records
    env.connect("alice", action)
    before = len(env.state_store.records)
    assert env.state.authorize_action_auth_execution("alice", {"action_ref": env.action_ref(action)})["uses_personal_credentials"]
    assert len(env.state_store.records) == before


def test_revoke_and_delete_only_invalidate_owner_bindings(env):
    action = env.add_action()
    env.connect("alice", action)
    env.connect("bob", action)
    alice_identity = next(record for (owner, _), record in env.personal_identities.records.items() if owner == "alice")
    bob_before = {key: deepcopy(record) for key, record in env.state_store.records.items() if key[0] == "bob"}
    env.identities.delete_workspace_identity("personal", "alice", alice_identity["id"], "alice")
    assert pending(env, action)["status"] == "credentials_required"
    assert {key: record for key, record in env.state_store.records.items() if key[0] == "bob"} == bob_before
    assert pending(env, action, "bob")["status"] == "ready"


def test_key_vault_policy_and_failed_conditional_update_preserve_good_secret(env):
    env.settings.update(enable_key_vault_secret_storage=True, key_vault_name="test-vault")
    identity = env.identity()
    original_reference = identity["auth"]["password_secret_name"]
    assert env.vault.values[original_reference] == SECRET
    assert SECRET not in json.dumps(identity)
    env.personal_identities.fail_replace = True
    with pytest.raises(env.contract.ActionAuthConflict):
        env.identities.update_workspace_identity("personal", "alice", identity["id"], {
            "credentials": {"auth_type": "username_password", "password": "replacement-password"},
        }, "alice", expected_etag=identity["_etag"])
    assert env.vault.values == {original_reference: SECRET}
    assert len(env.vault.deleted) == 1
    assert env.personal_identities.read_item(item=identity["id"], partition_key="alice") == identity


def test_enabled_broken_key_vault_never_falls_back_to_cosmos(env):
    env.settings["enable_key_vault_secret_storage"] = True
    with pytest.raises(env.contract.ActionAuthStorageError):
        env.identity()
    assert not env.personal_identities.records
    env.settings["key_vault_name"] = "test-vault"
    env.vault.fail_set = True
    with pytest.raises(env.contract.ActionAuthStorageError):
        env.identity()
    assert not env.personal_identities.records
    assert SECRET not in str(env.log_event.call_args_list)


def test_disabled_or_failed_key_vault_reads_cannot_be_used_as_passwords(env):
    env.settings.update(enable_key_vault_secret_storage=True, key_vault_name="test-vault")
    identity = env.identity()
    env.vault.fail_get = True
    with pytest.raises(env.contract.ActionAuthStorageError):
        env.identities.get_workspace_identity_auth("personal", "alice", identity["id"])
    env.vault.fail_get = False
    env.settings["enable_key_vault_secret_storage"] = False
    with pytest.raises(env.contract.ActionAuthStorageError):
        env.identities.get_workspace_identity_auth("personal", "alice", identity["id"])
    assert SECRET not in str(env.log_event.call_args_list)


def test_incomplete_identity_is_not_advertised_as_reusable(env):
    identity = env.identity()
    identity["auth"]["username"] = ""
    env.personal_identities.put(identity)
    state = pending(env, env.add_action())
    assert state["requirements"][0]["reason"] == "incompatible"
    assert not state["requirements"][0]["identities"]


@pytest.mark.parametrize("reference", [
    "bob--identity--user--workspace-identity-owned-password",
    "alice--plugin--user--workspace-identity-owned-password",
    "alice--identity--global--workspace-identity-owned-password",
    "alice--identity--user--workspace-identity-another-password",
])
def test_private_secret_reference_must_match_owner_source_scope_and_identity(env, reference):
    env.settings.update(enable_key_vault_secret_storage=True, key_vault_name="test-vault")
    identity = env.identity()
    identity["auth"] = {"auth_type": "username_password", "username": "alice", "password_secret_name": reference}
    env.personal_identities.put(identity)
    with pytest.raises(PermissionError):
        env.identities.get_workspace_identity_auth("personal", "alice", identity["id"])
    assert not env.vault.reads


def test_failed_identity_create_cleans_staged_key_vault_secret(env):
    env.settings.update(enable_key_vault_secret_storage=True, key_vault_name="test-vault")
    env.personal_identities.fail_create = True
    with pytest.raises(Exception):
        env.identity()
    assert not env.personal_identities.records
    assert not env.vault.values and len(env.vault.deleted) == 1
