# test_yamcs_user_auth_rejection.py
#!/usr/bin/env python3
"""
Functional tests for private Yamcs credential repair after a confirmed provider 401.
Version: 0.261.107
Implemented in: 0.261.107

Use the real auth contract, ownership, identity, binding, and preflight services
with the existing deterministic external-service fixture. No real secrets or
server configuration are loaded.
"""

import json
import importlib
import sys
import types
from contextlib import contextmanager
from copy import deepcopy

import pytest

from test_action_auth_service_support import SECRET, YamcsAuthenticationError, auth_environment
from test_support.app_stubs import import_app_module
from test_yamcs_user_auth_runtime import service


@pytest.fixture
def env():
    with auth_environment() as environment:
        yield environment


@contextmanager
def actor_context(env, user_id):
    frame = env.execution.AgentExecutionFrame(
        identity=env.execution.ExecutionIdentity(user_id=user_id),
        caller={"id": "global-mission-agent", "owner_id": "another-user"},
        budget=env.execution.DelegationBudget(),
    )
    with env.execution.agent_execution(frame):
        yield


def preflight(env, action, actor="alice"):
    return env.state.preflight_action_auth(actor, {"action_ref": env.action_ref(action)})


def bound_identity(env, action, actor="alice"):
    requirement_id = action["credential_requirement"]["id"]
    return next(
        record["identity_id"] for record in env.state_store.records.values()
        if record.get("record_type") == "binding"
        and record.get("user_id") == actor and record.get("requirement_id") == requirement_id
    )


def reject_resolved_credentials(env, action, actor="alice"):
    with actor_context(env, actor):
        credentials = env.contract.resolve_action_auth_credentials(action)
        assert credentials
        credentials.clear()
        env.contract.invalidate_action_auth_credentials(action)
        with pytest.raises(env.contract.ActionCredentialsRequired) as rejected:
            env.contract.resolve_action_auth_credentials(action)
        assert rejected.value.to_payload()["requirements"][0]["reason"] == "authentication_rejected"


def test_confirmed_rejection_preserves_secrets_and_only_marks_actor_metadata(env):
    action = env.add_action()
    env.connect("alice", action)
    env.connect("bob", action, secret="synthetic-bob-private-password")
    identities_before = deepcopy(env.personal_identities.records)
    bob_bindings = {
        key: deepcopy(value) for key, value in env.state_store.records.items() if key[0] == "bob"
    }
    probes_before = len(env.validation_calls)
    reject_resolved_credentials(env, action)
    secret_reads = env.personal_identities.secret_reads

    response = preflight(env, action)
    assert response["status"] == "credentials_required"
    assert response["requirements"][0]["reason"] == "authentication_rejected"
    assert preflight(env, action, "bob")["status"] == "ready"
    assert env.personal_identities.records == identities_before
    assert all(env.state_store.records[key] == value for key, value in bob_bindings.items())
    assert env.personal_identities.secret_reads == secret_reads
    assert len(env.validation_calls) == probes_before
    assert not env.vault.deleted
    assert SECRET not in json.dumps(env.state_store.writes)
    assert "synthetic-bob-private-password" not in json.dumps(env.state_store.writes)
    assert SECRET not in json.dumps(response)


def test_rejected_revision_cannot_be_reused_through_an_equivalent_approved_action(env):
    first, second, third = env.add_action(), env.add_action(name="Archive"), env.add_action(name="Events")
    env.connect("alice", first)
    assert preflight(env, second)["status"] == "ready"
    assert bound_identity(env, first) == bound_identity(env, second)
    probes_before = len(env.validation_calls)
    reject_resolved_credentials(env, first)
    for action in (first, second, third):
        response = preflight(env, action)
        assert response["status"] == "credentials_required"
        assert response["requirements"][0]["reason"] == "authentication_rejected"
    assert len(env.validation_calls) == probes_before


def test_unrelated_destinations_and_profiles_keep_their_approved_binding(env):
    action = env.add_action()
    different_destination = env.add_action(endpoint="https://other-yamcs.example")
    different_profile = env.add_action(profile="http_basic")
    env.connect("alice", action)
    identity_id = bound_identity(env, action)
    env.connect("alice", different_destination, identity_id=identity_id)
    env.connect("alice", different_profile, identity_id=identity_id)
    probes_before = len(env.validation_calls)
    reject_resolved_credentials(env, action)
    assert preflight(env, different_destination)["status"] == "ready"
    assert preflight(env, different_profile)["status"] == "ready"
    assert len(env.validation_calls) == probes_before


def test_successful_explicit_probe_can_revalidate_without_replacing_the_secret(env):
    first, equivalent = env.add_action(), env.add_action(name="Archive")
    env.connect("alice", first)
    assert preflight(env, equivalent)["status"] == "ready"
    identity_id = bound_identity(env, first)
    identities_before = deepcopy(env.personal_identities.records)
    reject_resolved_credentials(env, first)
    request = preflight(env, first)
    probes_before = len(env.validation_calls)
    response = env.state.save_action_auth_credentials("alice", request["request_id"], {
        "requirement_id": first["credential_requirement"]["id"],
        "identity_id": identity_id,
        "confirm_destination": True,
    })
    assert response["status"] == "ready"
    assert len(env.validation_calls) == probes_before + 1
    assert env.personal_identities.records == identities_before
    assert preflight(env, first)["status"] == "ready"
    assert preflight(env, equivalent)["status"] == "ready"


def test_failed_explicit_probe_does_not_clear_rejection_or_overwrite_credentials(env):
    action = env.add_action()
    env.connect("alice", action)
    identity_id = bound_identity(env, action)
    reject_resolved_credentials(env, action)
    identities_before = deepcopy(env.personal_identities.records)
    request = preflight(env, action)

    def reject(_action, _credentials):
        raise YamcsAuthenticationError("synthetic-provider-credential-echo")

    env.validation_hook = reject
    with pytest.raises(env.state.ActionAuthValidationError) as failed:
        env.state.save_action_auth_credentials("alice", request["request_id"], {
            "requirement_id": action["credential_requirement"]["id"],
            "identity_id": identity_id,
            "credentials": {"username": "wrong-user", "password": "synthetic-wrong-password"},
            "confirm_destination": True,
        })
    assert failed.value.code == "action_auth_rejected"
    assert env.personal_identities.records == identities_before
    assert preflight(env, action)["requirements"][0]["reason"] == "authentication_rejected"
    assert SECRET not in json.dumps(env.state_store.writes)


def test_successful_replacement_clears_rejection_only_after_validation(env):
    action = env.add_action()
    env.connect("alice", action)
    identity_id = bound_identity(env, action)
    reject_resolved_credentials(env, action)
    request = preflight(env, action)
    replacement = "synthetic-replacement-private-password"
    observed_during_probe = []

    def observe(_action, _credentials):
        observed_during_probe.append(preflight(env, action)["requirements"][0]["reason"])

    env.validation_hook = observe
    response = env.state.save_action_auth_credentials("alice", request["request_id"], {
        "requirement_id": action["credential_requirement"]["id"],
        "identity_id": identity_id,
        "credentials": {"username": "alice-login", "password": replacement},
        "confirm_destination": True,
    })
    assert observed_during_probe == ["authentication_rejected"]
    assert response["status"] == "ready"
    with actor_context(env, "alice"):
        assert env.contract.resolve_action_auth_credentials(action)["password"] == replacement
    assert replacement not in json.dumps(env.state_store.writes)


def test_late_rejection_cannot_invalidate_a_newer_repaired_revision(env):
    action = env.add_action()
    env.connect("alice", action)
    identity_id = bound_identity(env, action)
    with actor_context(env, "alice"):
        old_credentials = env.contract.resolve_action_auth_credentials(action)
        assert old_credentials["password"] == SECRET
        old_credentials.clear()
        identity = env.identities.get_workspace_identity_metadata("personal", "alice", identity_id)
        env.identities.update_workspace_identity(
            "personal", "alice", identity_id,
            {"credentials": {"auth_type": "username_password", "username": "alice-login", "password": "synthetic-new-password"}},
            "alice", expected_etag=identity["_etag"],
        )
        env.connect("alice", action, identity_id=identity_id)
        repaired_bindings = {
            key: deepcopy(value) for key, value in env.state_store.records.items()
            if value.get("record_type") == "binding"
        }
        try:
            env.contract.invalidate_action_auth_credentials(action)
        except env.contract.ActionAuthConflict:
            pass
        assert all(env.state_store.records[key] == value for key, value in repaired_bindings.items())
        assert preflight(env, action)["status"] == "ready"
        assert env.contract.resolve_action_auth_credentials(action)["password"] == "synthetic-new-password"


def test_invalidation_without_an_authenticated_actor_fails_closed(env):
    action = env.add_action()
    env.connect("alice", action)
    before = deepcopy(env.state_store.records)
    with pytest.raises(PermissionError):
        env.contract.invalidate_action_auth_credentials(action)
    assert env.state_store.records == before


def test_resolution_receipt_cannot_be_reused_by_another_execution_or_actor(env):
    action = env.add_action()
    env.connect("alice", action)
    env.connect("bob", action)
    with actor_context(env, "alice"):
        credentials = env.contract.resolve_action_auth_credentials(action)
        credentials.clear()
    before = deepcopy(env.state_store.records)
    with actor_context(env, "alice"):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.invalidate_action_auth_credentials(action)
    with actor_context(env, "bob"):
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.invalidate_action_auth_credentials(action)
    assert env.state_store.records == before


def test_conditional_invalidation_never_overwrites_a_concurrent_binding_repair(env):
    action = env.add_action()
    env.connect("alice", action)

    def repair_before_write(body):
        if body.get("record_type") == "binding" and body.get("status") == "authentication_rejected":
            current = deepcopy(env.state_store.records[("alice", body["id"])])
            env.state_store.put(current)

    env.state_store.before_replace = repair_before_write
    with actor_context(env, "alice"):
        credentials = env.contract.resolve_action_auth_credentials(action)
        credentials.clear()
        with pytest.raises(env.contract.ActionAuthConflict):
            env.contract.invalidate_action_auth_credentials(action)
    assert preflight(env, action)["status"] == "ready"


def test_real_native_rejection_uses_private_actor_state_on_a_shared_plugin(env, service, monkeypatch):
    action = env.add_action(profile="api_key")
    env.connect("alice", action)
    env.connect("bob", action, secret="synthetic-bob-api-key")
    # Restore the real native transport after the fixture's successful setup probes.
    monkeypatch.delitem(sys.modules, "functions_yamcs_client")
    native_client = importlib.import_module("functions_yamcs_client")
    monkeypatch.setitem(sys.modules, "functions_yamcs_client", native_client)
    logger = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
    logger.plugin_function_logger = lambda _name: lambda function: function
    monkeypatch.setitem(sys.modules, "semantic_kernel_plugins.plugin_invocation_logger", logger)
    monkeypatch.delitem(sys.modules, "semantic_kernel_plugins.yamcs_plugin", raising=False)
    module = import_app_module("semantic_kernel_plugins.yamcs_plugin")
    monkeypatch.setattr(module, "log_event", env.log_event)
    plugin = module.YamcsPlugin(action)
    original_manifest = deepcopy(plugin.manifest)
    url = f"{action['endpoint']}/api/instances"
    service.routes[url] = (401, b"synthetic-provider-credential-echo", {})

    with actor_context(env, "alice"):
        with pytest.raises(env.contract.ActionCredentialsRequired) as rejected:
            plugin.list_instances()
    assert rejected.value.to_payload()["requirements"][0]["reason"] == "authentication_rejected"
    assert preflight(env, action)["status"] == "credentials_required"
    assert preflight(env, action, "bob")["status"] == "ready"
    del service.routes[url]
    with actor_context(env, "bob"):
        assert plugin.list_instances()["success"] is True
    assert [request["headers"]["x-api-key"] for request in service.requests] == [
        SECRET, "synthetic-bob-api-key",
    ]
    assert len(service.sessions) == 2 and service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)
    assert plugin.manifest == original_manifest
    assert SECRET not in json.dumps(env.state_store.writes)
    assert SECRET not in str(env.log_event.call_args_list)
    assert "synthetic-provider-credential-echo" not in str(env.log_event.call_args_list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
