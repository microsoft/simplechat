# test_agent_delegation_permissions.py
"""Executable authorization and atomic-binding regressions for Call agent.

Version: 0.261.093
Implemented in: 0.261.093

Runs the real scoped resolver, catalogue, binding patch, and extracted Flask
handlers/decorators against mocked external services, without Azure credentials.
"""

import builtins
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from flask import Flask, session

from test_support.agent_delegation import (
    CosmosHttpResponseError,
    MatchConditions,
    delegation_environment,
    delegation_route_app,
    manifest,
    reference,
)


@pytest.fixture
def environment():
    with delegation_environment() as value:
        yield value


def prepare_call(services, scope="personal", scope_id="actor", target=None):
    target = target or reference("target-id", scope, scope_id)
    caller = services.add_agent("caller-id", scope, scope_id, actions_to_load=["action-id"])
    action = services.add_action(scope, scope_id, target)
    target_record = services.add_agent(target["id"], target["scope_type"], target["scope_id"])
    return caller, action, target_record


def test_runtime_preserves_long_stored_action_identifiers(environment):
    helper, services = environment
    action_id = "11111111-1111-4111-8111-111111111111_" + "a" * 100
    caller = services.add_agent("caller-id", actions_to_load=[action_id])
    services.add_agent()
    services.add_action(id=action_id)
    _, action, target = helper.resolve_delegation_call(
        action_id, caller_agent=caller, user_id="actor",
    )
    assert action["id"] == action_id
    assert target["id"] == "target-id"


@pytest.mark.parametrize("scope,scope_id,target_scope,target_id,merge,allowed", [
    ("personal", "actor", "personal", "actor", False, True),
    ("personal", "actor", "personal", "other-user", True, False),
    ("personal", "actor", "group", "group-a", True, False),
    ("personal", "actor", "global", "global", True, True),
    ("personal", "actor", "global", "global", False, False),
    ("group", "group-a", "group", "group-a", False, True),
    ("group", "group-a", "group", "group-b", True, False),
    ("group", "group-a", "personal", "actor", True, False),
    ("group", "group-a", "global", "global", True, True),
    ("group", "group-a", "global", "global", False, False),
    ("global", "global", "global", "global", False, True),
    ("global", "global", "personal", "actor", True, False),
    ("global", "global", "group", "group-a", True, False),
])
def test_runtime_and_save_enforce_source_matrix(
    environment, scope, scope_id, target_scope, target_id, merge, allowed,
):
    helper, services = environment
    services.settings["merge_global_semantic_kernel_with_workspace"] = merge
    target = reference("target-id", target_scope, target_id)
    _, action, _ = prepare_call(services, scope, scope_id, target)
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["user"] = {"oid": "actor", "roles": ["Admin"]}
        if allowed:
            _, actual_action, actual_target = helper.resolve_delegation_call(
                "action-id", caller_agent=reference("caller-id", scope, scope_id), user_id="actor",
            )
            assert actual_action["id"] == "action-id"
            assert helper.agent_reference(actual_target) == target
            assert helper.validate_agent_action_for_scope(
                action, user_id="actor", scope_type=scope, scope_id=scope_id,
            )["additionalFields"]["target_agent"] == target
        else:
            with pytest.raises(PermissionError):
                helper.resolve_delegation_call(
                    "action-id", caller_agent=reference("caller-id", scope, scope_id), user_id="actor",
                )
            with pytest.raises(PermissionError):
                helper.validate_agent_action_for_scope(
                    action, user_id="actor", scope_type=scope, scope_id=scope_id,
                )


def test_exact_id_survives_renames_and_never_falls_back_to_same_name(environment):
    helper, services = environment
    caller, action, target = prepare_call(services)
    action["name"], target["name"] = "renamed_action", "renamed_target"
    services.add_agent("same-name-decoy", name="renamed_target")
    _, resolved_action, resolved_target = helper.resolve_delegation_call(
        "action-id", caller_agent=reference("caller-id"), user_id="actor",
    )
    assert resolved_action["name"] == "renamed_action"
    assert resolved_target["id"] == "target-id"
    del services.records["agents", "personal"]["actor", "target-id"]
    with pytest.raises(LookupError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )
    assert services.containers["agents", "personal"].read_item.call_args.kwargs == {
        "item": "target-id", "partition_key": "actor",
    }
    caller["actions_to_load"] = ["renamed_action"]
    with pytest.raises(PermissionError, match="not attached"):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )


def test_current_caller_is_reread_and_client_attachment_is_not_trusted(environment):
    helper, services = environment
    caller, _, _ = prepare_call(services)
    stale = {**caller, "actions_to_load": ["action-id"]}
    caller["actions_to_load"] = []
    with pytest.raises(PermissionError, match="not attached"):
        helper.resolve_delegation_call("action-id", caller_agent=stale, user_id="actor")
    services.containers["actions", "personal"].query_items.assert_not_called()
    caller["actions_to_load"] = ["action-id"]
    _, _, target = helper.resolve_delegation_call("action-id", caller_agent=stale, user_id="actor")
    assert target["id"] == "target-id"
    assert services.containers["agents", "personal"].read_item.call_count == 3


@pytest.mark.parametrize("actor", [None, "", " ", "system", "creator", 123])
def test_execution_requires_current_authenticated_owner_not_stored_creator(environment, actor):
    helper, services = environment
    prepare_call(services)
    with pytest.raises((PermissionError, ValueError)):
        helper.resolve_delegation_call("action-id", caller_agent=reference("caller-id"), user_id=actor)
    assert all(not container.read_item.called for container in services.containers.values())


def test_shared_calls_apply_policies_to_actor_not_creator(environment):
    helper, services = environment
    caller, action, target = prepare_call(services, "group", "group-a")
    for record in (caller, action, target):
        record["created_by"] = "creator"
    helper.resolve_delegation_call(
        "action-id", caller_agent=reference("caller-id", "group", "group-a"), user_id="actor",
    )
    assert all(call.args[0] == "actor" for call in services.groups.assert_group_role.call_args_list)
    assert all(call.args[1] == "actor" for call in services.governance.ensure_governance_access.call_args_list)
    services.governance.ensure_action_type_access.assert_called_once_with(
        "governance_group_actions", "actor", "agent", "group",
    )


@pytest.mark.parametrize("scope,scope_id,flag", [
    ("personal", "actor", "enable_semantic_kernel"),
    ("personal", "actor", "allow_user_agents"),
    ("personal", "actor", "allow_user_plugins"),
    ("group", "group-a", "enable_group_workspaces"),
    ("group", "group-a", "allow_group_agents"),
    ("group", "group-a", "allow_group_plugins"),
])
def test_current_enablement_flags_block_calls(environment, scope, scope_id, flag):
    helper, services = environment
    prepare_call(services, scope, scope_id)
    services.settings[flag] = False
    with pytest.raises(PermissionError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id", scope, scope_id), user_id="actor",
        )


@pytest.mark.parametrize("scope,scope_id,feature", [
    ("personal", "actor", "governance_user_agents"),
    ("personal", "actor", "governance_user_actions"),
    ("group", "group-a", "governance_group_agents"),
    ("group", "group-a", "governance_group_actions"),
])
def test_current_governance_denial_blocks_calls(environment, scope, scope_id, feature):
    helper, services = environment
    prepare_call(services, scope, scope_id)
    services.denied_features.add(feature)
    with pytest.raises(PermissionError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id", scope, scope_id), user_id="actor",
        )


def test_group_membership_is_revalidated_after_revocation(environment):
    helper, services = environment
    prepare_call(services, "group", "group-a")
    caller = reference("caller-id", "group", "group-a")
    helper.resolve_delegation_call("action-id", caller_agent=caller, user_id="actor")
    services.roles.pop(("actor", "group-a"))
    with pytest.raises(PermissionError):
        helper.resolve_delegation_call("action-id", caller_agent=caller, user_id="actor")
    assert services.groups.assert_group_role.call_count == 3


@pytest.mark.parametrize("scope,scope_id,owner_field", [
    ("personal", "actor", "user_id"), ("group", "group-a", "group_id"),
])
def test_loaded_target_ownership_is_verified(environment, scope, scope_id, owner_field):
    helper, services = environment
    _, _, target = prepare_call(services, scope, scope_id)
    target[owner_field] = "someone-else"
    with pytest.raises(PermissionError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id", scope, scope_id), user_id="actor",
        )


@pytest.mark.parametrize("scope,scope_id,stored_fields", [
    ("personal", "actor", {"is_global": True, "is_group": True, "group_id": "unrelated-group"}),
    ("group", "group-a", {"is_global": True, "is_group": False, "user_id": "creator"}),
    ("global", "global", {"is_global": False, "is_group": True, "user_id": "creator", "group_id": "unrelated-group"}),
])
def test_resolved_agent_canonical_scope_overwrites_inapplicable_stored_identity(
    environment, scope, scope_id, stored_fields,
):
    helper, services = environment
    services.add_agent("target-id", scope, scope_id, **stored_fields)
    result = helper.resolve_delegation_agent(
        reference("target-id", scope, scope_id), user_id="actor",
    )
    assert result["scope_type"] == scope
    assert result["scope_id"] == scope_id
    assert result["is_global"] is (scope == "global")
    assert result["is_group"] is (scope == "group")
    assert result["user_id"] == ("actor" if scope == "personal" else None)
    assert result["group_id"] == ("group-a" if scope == "group" else None)


@pytest.mark.parametrize("kind,field,value,exception", [
    ("target", "is_enabled", False, LookupError),
    ("target", "is_enabled", "true", LookupError),
    ("target", "agent_type", "unsupported", ValueError),
    ("target", "id", "wrong-id", LookupError),
    ("caller", "is_enabled", False, LookupError),
    ("caller", "agent_type", "new_foundry", PermissionError),
    ("action", "is_enabled", False, PermissionError),
    ("action", "endpoint", "https://override.invalid", ValueError),
    ("action", "additionalFields", {"target_agent": {"id": "incomplete"}}, ValueError),
])
def test_unavailable_and_malformed_current_records_fail_closed(environment, kind, field, value, exception):
    helper, services = environment
    caller, action, target = prepare_call(services)
    {"caller": caller, "action": action, "target": target}[kind][field] = value
    with pytest.raises(exception):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )


def test_missing_and_ambiguous_action_ids_do_not_use_other_actions(environment):
    helper, services = environment
    prepare_call(services)
    services.records["actions", "personal"].clear()
    services.add_action(id="same-name-decoy")
    with pytest.raises(LookupError, match="unavailable"):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )
    services.add_action()
    services.add_action("global", "global", reference("global-target", "global", "global"))
    with pytest.raises(LookupError, match="ambiguous"):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )


def test_global_action_cannot_smuggle_private_target(environment):
    helper, services = environment
    prepare_call(services)
    services.records["actions", "personal"].clear()
    services.add_action("global", "global", reference())
    with pytest.raises(PermissionError, match="workspace"):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )
    services.containers["agents", "personal"].read_item.assert_called_once_with(
        item="caller-id", partition_key="actor",
    )


@pytest.mark.parametrize("deny", ["action", "target", "caller"])
def test_global_item_policies_are_rechecked_for_current_actor(environment, deny):
    helper, services = environment
    prepare_call(services, "global", "global")
    if deny == "action":
        services.denied_actions.add("action-id")
    else:
        services.denied_agents.add("target-id" if deny == "target" else "caller-id")
    with pytest.raises(PermissionError):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id", "global", "global"), user_id="actor",
        )
    assert all(call.args[1] == "actor" for call in services.governance.ensure_governance_access.call_args_list)


def test_direct_self_reference_is_denied(environment):
    helper, services = environment
    prepare_call(services)
    services.records["actions", "personal"]["actor", "action-id"]["additionalFields"]["target_agent"] = reference("caller-id")
    with pytest.raises(ValueError, match="itself"):
        helper.resolve_delegation_call(
            "action-id", caller_agent=reference("caller-id"), user_id="actor",
        )


def test_catalogue_returns_only_safe_authorized_projection(environment):
    helper, services = environment
    services.add_agent(instructions="private prompt", endpoint="https://internal.invalid",
                       auth={"key": "private-key"}, other_settings={"secret": "private-value"})
    services.add_agent("global-allowed", "global", "global", display_name="A global")
    services.add_agent("global-denied", "global", "global")
    services.add_agent("disabled", is_enabled=False)
    services.add_agent("unsupported", agent_type="unknown")
    services.add_agent("other-user", "personal", "other-user")
    services.add_agent("other-group", "group", "group-a")
    services.denied_agents.add("global-denied")
    result = helper.build_agent_delegation_catalog("actor", "personal")
    assert result["can_manage"] is True
    assert result["scope_id"] == "actor"
    assert [target["id"] for target in result["targets"]] == ["global-allowed", "target-id"]
    allowed_fields = {
        "id", "name", "display_name", "description", "agent_type",
        "scope_type", "scope_id", "is_global", "is_group", "group_id",
    }
    assert all(set(target) <= allowed_fields for target in result["targets"])
    encoded = json.dumps(result)
    for sensitive in ("instructions", "endpoint", "auth", "other_settings", "private", "internal.invalid"):
        assert sensitive not in encoded
    services.containers["agents", "personal"].query_items.assert_called_once_with(
        query="SELECT * FROM c WHERE c.user_id = @scope_id",
        parameters=[{"name": "@scope_id", "value": "actor"}], partition_key="actor",
    )


def test_catalogue_labels_are_strings_even_for_legacy_nonstring_values(environment):
    helper, services = environment
    services.add_agent(name=123, display_name=["Legacy", "label"], description={"summary": "Legacy description"})
    result = helper.build_agent_delegation_catalog("actor", "personal")
    target = result["targets"][0]
    assert target["name"] == "123"
    assert isinstance(target["display_name"], str)
    assert isinstance(target["description"], str)


@pytest.mark.parametrize("reason", ["role", "plugin-disabled", "action-governance", "owner-only"])
def test_catalogue_management_hint_does_not_grant_write_permission(environment, reason):
    helper, services = environment
    services.add_agent(scope="group", scope_id="group-a")
    if reason == "role":
        services.roles["actor", "group-a"] = "User"
    elif reason == "plugin-disabled":
        services.settings["allow_group_plugins"] = False
    elif reason == "action-governance":
        services.denied_features.add("governance_group_actions")
    else:
        services.settings["require_owner_for_group_agent_management"] = True
        services.roles["actor", "group-a"] = "Admin"
    result = helper.build_agent_delegation_catalog("actor", "group", "group-a")
    assert result["can_manage"] is False
    assert [target["id"] for target in result["targets"]] == ["target-id"]


@pytest.mark.parametrize("scope,scope_id,flag", [
    ("personal", "actor", "allow_user_plugins"), ("group", "group-a", "allow_group_plugins"),
])
def test_catalogue_plugin_disable_flags_clear_management_hint(environment, scope, scope_id, flag):
    helper, services = environment
    services.add_agent(scope=scope, scope_id=scope_id)
    services.settings[flag] = False
    result = helper.build_agent_delegation_catalog(
        "actor", scope, scope_id if scope == "group" else None,
    )
    assert result["can_manage"] is False
    assert len(result["targets"]) == 1
    services.governance.ensure_action_type_access.assert_not_called()


def test_catalogue_merge_policy_and_global_management_permission(environment):
    helper, services = environment
    services.add_agent()
    services.add_agent("global", "global", "global")
    services.settings["merge_global_semantic_kernel_with_workspace"] = False
    assert [item["id"] for item in helper.build_agent_delegation_catalog("actor", "personal")["targets"]] == ["target-id"]
    with pytest.raises(PermissionError):
        helper.build_agent_delegation_catalog("actor", "global")
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["user"] = {"oid": "actor", "roles": ["Admin"]}
        result = helper.build_agent_delegation_catalog("actor", "global")
        assert result["can_manage"] is True
        assert [item["id"] for item in result["targets"]] == ["global"]


def test_catalogue_filters_malformed_targets_instead_of_failing_valid_selection(environment):
    helper, services = environment
    services.add_agent()
    services.add_agent("invalid/id")
    result = helper.build_agent_delegation_catalog("actor", "personal")
    assert [target["id"] for target in result["targets"]] == ["target-id"]
    services.appinsights.log_event.assert_called_once()


@pytest.mark.parametrize("scope,scope_id", [
    ("personal", "actor"), ("group", "group-a"), ("global", "global"),
])
def test_atomic_binding_patch_preserves_other_actions_config_and_secrets(environment, scope, scope_id):
    helper, services = environment
    caller, _, _ = prepare_call(services, scope, scope_id)
    caller.update({
        "actions_to_load": ["ordinary-id", "action-id", "legacy_name"],
        "instructions": "private prompt", "azure_openai_gpt_key": "private-key",
        "model_endpoint_id": "private-model", "assigned_knowledge": [{"id": "knowledge"}],
        "other_settings": {"action_capabilities": {"ordinary-id": {"write": False}}},
    })
    original = deepcopy(caller)
    services.add_action(scope, scope_id, reference("target-id", scope, scope_id), id="new-action")
    payload = {"action_ids": ["new-action", "new-action"], "expected_actions_to_load": original["actions_to_load"]}
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["user"] = {"oid": "actor", "roles": ["Admin"]}
        result = helper.update_agent_delegation_bindings(
            "actor", scope, "caller-id", payload, scope_id if scope == "group" else None,
        )
    assert result["actions_to_load"] == ["ordinary-id", "legacy_name", "new-action"]
    container = services.containers["agents", scope]
    container.patch_item.assert_called_once()
    patch_arguments = container.patch_item.call_args.kwargs
    assert patch_arguments["item"] == "caller-id"
    assert patch_arguments["partition_key"] == ("caller-id" if scope == "global" else scope_id)
    assert patch_arguments["etag"] == original["_etag"]
    assert patch_arguments["match_condition"] is MatchConditions.IfNotModified
    operations = {operation["path"]: operation for operation in patch_arguments["patch_operations"]}
    assert set(operations) == {
        "/actions_to_load", "/modified_by", "/modified_at",
        "/updated_at" if scope == "global" else "/last_updated",
    }
    assert all(operation["op"] == "set" for operation in operations.values())
    assert operations["/actions_to_load"]["value"] == result["actions_to_load"]
    assert operations["/modified_by"]["value"] == "actor"
    container.upsert_item.assert_not_called()
    container.replace_item.assert_not_called()
    assert caller == original
    assert "private" not in json.dumps(result)
    assert builtins.kernel_reload_needed is True
    services.activity.log_agent_update.assert_called_once()
    if scope == "personal":
        services.cache.bump_chat_bootstrap_user_cache_version.assert_called_once_with(
            "actor", reason="agent_delegation_updated",
        )
    else:
        services.cache.bump_chat_bootstrap_global_cache_version.assert_called_once_with(
            reason="agent_delegation_updated",
        )


@pytest.mark.parametrize("hidden_reason", ["disabled", "denied"])
def test_binding_patch_preserves_global_actions_omitted_from_workspace_lists(environment, hidden_reason):
    helper, services = environment
    caller, _, _ = prepare_call(services)
    caller["actions_to_load"] = ["ordinary-id", "hidden-global", "action-id"]
    services.add_action(
        "global", "global", reference("global-target", "global", "global"),
        id="hidden-global", is_enabled=hidden_reason != "disabled",
    )
    if hidden_reason == "denied":
        services.denied_actions.add("hidden-global")
    result = helper.update_agent_delegation_bindings(
        "actor", "personal", "caller-id",
        {"action_ids": ["action-id"], "expected_actions_to_load": caller["actions_to_load"]},
    )
    assert result["actions_to_load"] == ["ordinary-id", "hidden-global", "action-id"]
    services.containers["agents", "personal"].patch_item.assert_called_once()


@pytest.mark.parametrize("scope,scope_id", [
    ("personal", "actor"), ("group", "group-a"), ("global", "global"),
])
def test_binding_patch_can_remove_visible_disabled_owned_actions(environment, scope, scope_id):
    helper, services = environment
    caller, action, _ = prepare_call(services, scope, scope_id)
    action["is_enabled"] = False
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["user"] = {"oid": "actor", "roles": ["Admin"]}
        result = helper.update_agent_delegation_bindings(
            "actor", scope, "caller-id",
            {"action_ids": [], "expected_actions_to_load": caller["actions_to_load"]},
            scope_id if scope == "group" else None,
        )
    assert result["actions_to_load"] == []


@pytest.mark.parametrize("payload", [
    None, {}, {"action_ids": []},
    {"action_ids": [], "expected_actions_to_load": [], "instructions": "overwrite"},
    {"action_ids": "action-id", "expected_actions_to_load": []},
    {"action_ids": [None], "expected_actions_to_load": []},
    {"action_ids": [" "], "expected_actions_to_load": []},
    {"action_ids": [], "expected_actions_to_load": "action-id"},
])
def test_binding_payload_rejects_extra_fields_and_malformed_arrays(environment, payload):
    helper, services = environment
    prepare_call(services)
    with pytest.raises(ValueError):
        helper.update_agent_delegation_bindings("actor", "personal", "caller-id", payload)
    assert all(not container.patch_item.called for container in services.containers.values())


@pytest.mark.parametrize("reason", ["stale", "reordered", "missing-etag", "cosmos-412"])
def test_binding_conflicts_do_not_overwrite_or_invalidate_cache(environment, reason):
    helper, services = environment
    caller, _, _ = prepare_call(services)
    expected = ["action-id"]
    if reason == "stale":
        expected = []
    elif reason == "reordered":
        caller["actions_to_load"] = ["ordinary", "action-id"]
        expected = ["action-id", "ordinary"]
    elif reason == "missing-etag":
        caller.pop("_etag")
    else:
        services.containers["agents", "personal"].patch_item.side_effect = CosmosHttpResponseError(412)
    with pytest.raises(helper.AgentDelegationConflictError):
        helper.update_agent_delegation_bindings(
            "actor", "personal", "caller-id",
            {"action_ids": [], "expected_actions_to_load": expected},
        )
    assert services.containers["agents", "personal"].patch_item.call_count == (1 if reason == "cosmos-412" else 0)
    services.activity.log_agent_update.assert_not_called()
    services.cache.bump_chat_bootstrap_user_cache_version.assert_not_called()
    services.cache.bump_chat_bootstrap_global_cache_version.assert_not_called()
    assert builtins.kernel_reload_needed is False


@pytest.mark.parametrize("exact_expected", [True, False])
def test_binding_compare_preserves_expected_duplicates_but_deduplicates_selection(environment, exact_expected):
    helper, services = environment
    caller, _, _ = prepare_call(services)
    original = ["ordinary", "action-id", "ordinary", "action-id"]
    caller["actions_to_load"] = original[:]
    expected = original[:] if exact_expected else ["ordinary", "action-id"]
    payload = {"action_ids": ["action-id", "action-id"], "expected_actions_to_load": expected}
    if exact_expected:
        result = helper.update_agent_delegation_bindings("actor", "personal", "caller-id", payload)
        assert result["actions_to_load"] == ["ordinary", "ordinary", "action-id"]
        assert caller["actions_to_load"] == original
        assert payload["expected_actions_to_load"] == original
    else:
        with pytest.raises(helper.AgentDelegationConflictError):
            helper.update_agent_delegation_bindings("actor", "personal", "caller-id", payload)
        services.containers["agents", "personal"].patch_item.assert_not_called()


def test_unknown_selected_action_is_rejected_without_losing_ordinary_bindings(environment):
    helper, services = environment
    prepare_call(services)
    with pytest.raises(ValueError, match="available"):
        helper.update_agent_delegation_bindings(
            "actor", "personal", "caller-id",
            {"action_ids": ["unknown"], "expected_actions_to_load": ["action-id"]},
        )
    services.containers["agents", "personal"].patch_item.assert_not_called()


@pytest.mark.parametrize("role,owner_only,allowed", [
    ("Owner", True, True), ("Admin", True, False), ("Admin", False, True),
    ("DocumentManager", False, False), ("User", False, False),
])
def test_binding_writes_honor_current_group_management_role(environment, role, owner_only, allowed):
    helper, services = environment
    prepare_call(services, "group", "group-a")
    services.roles["actor", "group-a"] = role
    services.settings["require_owner_for_group_agent_management"] = owner_only
    payload = {"action_ids": [], "expected_actions_to_load": ["action-id"]}
    if allowed:
        helper.update_agent_delegation_bindings("actor", "group", "caller-id", payload, "group-a")
    else:
        with pytest.raises(PermissionError):
            helper.update_agent_delegation_bindings("actor", "group", "caller-id", payload, "group-a")
        services.containers["agents", "group"].patch_item.assert_not_called()
    roles = services.groups.assert_group_role.call_args.kwargs["allowed_roles"]
    assert roles == (("Owner",) if owner_only else ("Owner", "Admin"))


def test_global_binding_requires_current_admin_even_when_removing_all_actions(environment):
    helper, services = environment
    prepare_call(services, "global", "global")
    with pytest.raises(PermissionError):
        helper.update_agent_delegation_bindings(
            "actor", "global", "caller-id",
            {"action_ids": [], "expected_actions_to_load": ["action-id"]},
        )
    services.containers["agents", "global"].patch_item.assert_not_called()


def test_explicit_group_scope_does_not_read_or_change_active_group(environment):
    helper, services = environment
    assert helper.resolve_delegation_group_scope("actor", "group-b") == "group-b"
    assert helper.resolve_delegation_scope("actor", "group", "group-b") == ("group", "group-b")
    services.groups.require_active_group.assert_not_called()
    services.settings_module.get_user_settings.assert_not_called()
    services.settings_module.update_user_settings.assert_not_called()
    services.groups.update_active_group_for_user.assert_not_called()
    assert helper.resolve_delegation_group_scope("actor") == "group-a"
    services.groups.require_active_group.assert_called_once_with(
        "actor", allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
    )
    services.roles.pop(("actor", "group-b"))
    with pytest.raises(PermissionError):
        helper.resolve_delegation_group_scope("actor", "group-b")


ROUTES = [
    ("GET", "/api/plugins/agent-targets"),
    ("PATCH", "/api/user/agents/caller-id/agent-actions"),
    ("PATCH", "/api/group/agents/caller-id/agent-actions?group_id=group-a"),
    ("PATCH", "/api/admin/agents/caller-id/agent-actions"),
]


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("roles,status", [(None, 401), ([], 403)])
def test_real_route_decorators_reject_unauthenticated_or_unprivileged_users(environment, method, path, roles, status):
    helper, services = environment
    app, namespace = delegation_route_app(helper, services)
    client = app.test_client()
    if roles is not None:
        with client.session_transaction() as current:
            current["user"] = {"oid": "actor", "roles": roles}
    response = client.open(path, method=method, json={})
    assert response.status_code == status
    assert all(not container.mock_calls for container in services.containers.values())
    assert namespace["swagger_route"].call_count == 4
    assert namespace["bpa"].before_request_funcs[None][0]._simplechat_auth_policy == ("login_required",)
    assert namespace["bpap"].before_request_funcs[None][0]._simplechat_auth_policy == ("login_required",)


def test_real_admin_route_rejects_user_and_feature_guard_rejects_disabled_agents(environment):
    helper, services = environment
    app, _ = delegation_route_app(helper, services)
    client = app.test_client()
    with client.session_transaction() as current:
        current["user"] = {"oid": "actor", "roles": ["User"]}
    assert client.patch("/api/admin/agents/caller-id/agent-actions", json={}).status_code == 403
    services.settings["enable_semantic_kernel"] = False
    assert client.get("/api/plugins/agent-targets").status_code == 400
    assert client.patch("/api/user/agents/caller-id/agent-actions", json={}).status_code == 400
    assert all(not container.patch_item.called for container in services.containers.values())


@pytest.mark.parametrize("error,status", [
    (PermissionError("private policy"), 403),
    (LookupError("private resource"), 404),
    (ValueError("private malformed data"), 400),
    (CosmosHttpResponseError(503, "private provider credentials"), 503),
])
@pytest.mark.parametrize("catalogue", [True, False])
def test_handlers_map_errors_to_safe_response_statuses(environment, error, status, catalogue):
    helper, services = environment
    app, namespace = delegation_route_app(helper, services)
    name = "build_agent_delegation_catalog" if catalogue else "update_agent_delegation_bindings"
    namespace[name] = Mock(side_effect=error)
    client = app.test_client()
    with client.session_transaction() as current:
        current["user"] = {"oid": "actor", "roles": ["User"]}
    response = (
        client.get("/api/plugins/agent-targets") if catalogue
        else client.patch("/api/user/agents/caller-id/agent-actions", json={})
    )
    assert response.status_code == status
    assert "private" not in response.get_data(as_text=True)
    assert set(response.get_json()) == {"error"}


def test_binding_handler_returns_conflict_and_uses_authenticated_actor(environment):
    helper, services = environment
    prepare_call(services)
    app, _ = delegation_route_app(helper, services)
    client = app.test_client()
    with client.session_transaction() as current:
        current["user"] = {"oid": "actor", "roles": ["User"]}
    response = client.patch(
        "/api/user/agents/caller-id/agent-actions?user_id=creator",
        json={"action_ids": [], "expected_actions_to_load": []},
    )
    assert response.status_code == 409
    services.containers["agents", "personal"].read_item.assert_called_once_with(
        item="caller-id", partition_key="actor",
    )
    services.containers["agents", "personal"].patch_item.assert_not_called()


def test_group_catalogue_and_binding_endpoints_use_explicit_group_without_switching(environment):
    helper, services = environment
    prepare_call(services, "group", "group-b")
    app, _ = delegation_route_app(helper, services)
    client = app.test_client()
    with client.session_transaction() as current:
        current["user"] = {"oid": "actor", "roles": ["User"]}
    catalogue = client.get("/api/plugins/agent-targets?scope=group&group_id=group-b")
    assert catalogue.status_code == 200
    assert catalogue.get_json()["scope_id"] == "group-b"
    response = client.patch(
        "/api/group/agents/caller-id/agent-actions?group_id=group-b",
        json={"action_ids": [], "expected_actions_to_load": ["action-id"]},
    )
    assert response.status_code == 200
    assert response.get_json()["actions_to_load"] == []
    assert services.containers["agents", "group"].patch_item.call_args.kwargs["partition_key"] == "group-b"
    services.groups.require_active_group.assert_not_called()
    services.settings_module.update_user_settings.assert_not_called()
    services.groups.update_active_group_for_user.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
