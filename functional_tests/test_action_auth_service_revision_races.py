# test_action_auth_service_revision_races.py
"""Regression tests for probed identity revisions and delayed revocation.

Version: 0.261.107
Implemented in: 0.261.107

An approval cannot adopt a concurrently replaced credential revision, and a
completed older identity update cannot revoke a newer validated binding.
"""

from copy import deepcopy
from unittest.mock import patch

import pytest

from test_action_auth_service_support import SECRET, auth_environment


@pytest.fixture(params=[False, True], ids=["cosmos-secrets", "key-vault-secrets"])
def env(request):
    with auth_environment() as environment:
        environment.settings["enable_key_vault_secret_storage"] = request.param
        if request.param:
            environment.settings["key_vault_name"] = "test-vault"
        yield environment


def pending(env, action):
    return env.state.preflight_action_auth("alice", {"action_ref": env.action_ref(action)})


def credentials(action, *, identity_id=None, password=None):
    payload = {"requirement_id": action["credential_requirement"]["id"], "confirm_destination": True}
    if identity_id:
        payload["identity_id"] = identity_id
    if password is not None:
        payload["credentials"] = {"username": "alice", "password": password}
    return payload


def assert_current_secret(env, identity_id, expected):
    current = env.identities.get_workspace_identity_auth("personal", "alice", identity_id)
    assert current["password"] == expected
    stored = env.personal_identities.read_item(item=identity_id, partition_key="alice")
    if env.settings["enable_key_vault_secret_storage"]:
        reference = stored["auth"]["password_secret_name"]
        assert env.vault.values[reference] == expected
        assert reference not in env.vault.deleted
    return stored


def assert_no_approved_binding(env, action):
    assert not any(
        row.get("record_type") == "binding" and row.get("status") == "active"
        and row.get("action_id") == action["id"]
        for row in env.state_store.records.values()
    )


def test_unbound_approval_never_binds_revision_replaced_during_probe(env):
    action, identity = env.add_action(), env.identity()
    request = pending(env, action)

    def edit_during_probe(manifest, identity_auth):
        assert identity_auth["password"] == SECRET
        env.identities.update_workspace_identity("personal", "alice", identity["id"], {
            "credentials": {"auth_type": "username_password", "password": "concurrent-replacement"},
        }, "alice", expected_etag=identity["_etag"])

    env.validation_hook = edit_during_probe
    with pytest.raises(env.contract.ActionAuthConflict):
        env.state.save_action_auth_credentials("alice", request["request_id"], credentials(
            action, identity_id=identity["id"],
        ))
    assert_current_secret(env, identity["id"], "concurrent-replacement")
    assert_no_approved_binding(env, action)
    assert env.state_store.read_item(item=request["request_id"], partition_key="alice")["save_claim"] is None
    assert [call[1]["password"] for call in env.validation_calls] == [SECRET]


def test_replacement_approval_pins_exact_successful_update_response(env):
    action, identity = env.add_action(), env.identity()
    request = pending(env, action)
    original_update = env.identities.update_workspace_identity
    responses = {}

    def update_then_replace(*args, **kwargs):
        tested = original_update(*args, **kwargs)
        responses["tested"] = deepcopy(tested)
        responses["replacement"] = original_update("personal", "alice", identity["id"], {
            "credentials": {"auth_type": "username_password", "password": "later-replacement"},
        }, "alice", expected_etag=tested["_etag"])
        return tested

    with patch.object(env.identities, "update_workspace_identity", side_effect=update_then_replace):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.state.save_action_auth_credentials("alice", request["request_id"], credentials(
                action, identity_id=identity["id"], password="tested-replacement",
            ))
    current = assert_current_secret(env, identity["id"], "later-replacement")
    assert responses["tested"]["_etag"] != current["_etag"] == responses["replacement"]["_etag"]
    assert_no_approved_binding(env, action)
    assert [call[1]["password"] for call in env.validation_calls] == ["tested-replacement"]


def test_new_identity_approval_pins_create_response_and_keeps_committed_replacement(env):
    action = env.add_action()
    request = pending(env, action)
    original_create = env.identities.create_workspace_identity
    created = {}

    def create_then_replace(*args, **kwargs):
        tested = original_create(*args, **kwargs)
        created.update(deepcopy(tested))
        env.identities.update_workspace_identity("personal", "alice", tested["id"], {
            "credentials": {"auth_type": "username_password", "password": "later-committed-secret"},
        }, "alice", expected_etag=tested["_etag"])
        return tested

    with patch.object(env.identities, "create_workspace_identity", side_effect=create_then_replace):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.state.save_action_auth_credentials("alice", request["request_id"], credentials(
                action, password="tested-created-secret",
            ))
    current = assert_current_secret(env, created["id"], "later-committed-secret")
    assert current["_etag"] != created["_etag"]
    assert_no_approved_binding(env, action)
    assert [call[1]["password"] for call in env.validation_calls] == ["tested-created-secret"]


def test_binding_conflict_does_not_delete_a_committed_identity_secret(env):
    action = env.add_action()
    request = pending(env, action)
    with patch.object(env.state, "_write_binding", side_effect=env.contract.ActionAuthConflict()):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.state.save_action_auth_credentials("alice", request["request_id"], credentials(
                action, password="committed-but-unlinked",
            ))
    assert len(env.personal_identities.records) == 1
    identity = next(iter(env.personal_identities.records.values()))
    assert_current_secret(env, identity["id"], "committed-but-unlinked")
    assert_no_approved_binding(env, action)


def test_delayed_update_revocation_cannot_revoke_newer_validated_binding(env):
    action, identity = env.add_action(), env.identity()
    env.connect("alice", action, identity_id=identity["id"])
    env.connect("bob", action, secret="bob-private-secret")
    bob_before = {key: deepcopy(value) for key, value in env.state_store.records.items() if key[0] == "bob"}
    original_revoke = env.state.revoke_action_identity_bindings
    sequence = {"entered": False}

    def delay_first_revocation(user_id, identity_id, **kwargs):
        if sequence["entered"]:
            return original_revoke(user_id, identity_id, **kwargs)
        sequence["entered"] = True
        revision_a = env.identities.get_workspace_identity_metadata("personal", user_id, identity_id)["_etag"]
        updated_b = env.identities.update_workspace_identity("personal", user_id, identity_id, {
            "credentials": {"auth_type": "username_password", "password": "validated-revision-b"},
        }, user_id, expected_etag=revision_a)
        request_b = pending(env, action)
        ready_b = env.state.save_action_auth_credentials(user_id, request_b["request_id"], credentials(
            action, identity_id=identity_id,
        ))
        assert ready_b["status"] == "ready"
        sequence["revision_b"] = updated_b["_etag"]
        sequence["binding_b"] = next(
            deepcopy(row) for (owner, _), row in env.state_store.records.items()
            if owner == user_id and row.get("record_type") == "binding" and row.get("action_id") == action["id"]
        )
        return original_revoke(user_id, identity_id, **kwargs)

    with patch.object(env.state, "revoke_action_identity_bindings", side_effect=delay_first_revocation):
        updated_a = env.identities.update_workspace_identity("personal", "alice", identity["id"], {
            "credentials": {"auth_type": "username_password", "password": "revision-a"},
        }, "alice", expected_etag=identity["_etag"])
    assert updated_a["_etag"] != sequence["revision_b"]
    current = env.state_store.read_item(item=sequence["binding_b"]["id"], partition_key="alice")
    assert current == sequence["binding_b"]
    assert current["status"] == "active" and current["identity_revision"] == sequence["revision_b"]
    assert pending(env, action)["status"] == "ready"
    assert_current_secret(env, identity["id"], "validated-revision-b")
    assert {key: value for key, value in env.state_store.records.items() if key[0] == "bob"} == bob_before


def test_explicit_full_revocation_and_delete_still_remove_current_approval(env):
    action, identity = env.add_action(), env.identity()
    env.connect("alice", action, identity_id=identity["id"])
    env.state.revoke_action_identity_bindings("alice", identity["id"])
    assert pending(env, action)["status"] == "credentials_required"
    env.connect("alice", action, identity_id=identity["id"])
    env.identities.delete_workspace_identity("personal", "alice", identity["id"], "alice")
    assert pending(env, action)["status"] == "credentials_required"
    assert not env.personal_identities.records
