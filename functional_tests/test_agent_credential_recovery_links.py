# test_agent_credential_recovery_links.py
"""Permission-aware agent credential recovery in chat JSON and SSE errors.

Version: 0.261.434
Implemented in: 0.261.429
Assertion safety reviewed in: 0.261.434

Real personal/global owners use installed-SDK point responses. Group cases run
the production membership, status, governance and editor access policy. Only the
group domain getter is replaced; no live credentials or external I/O are used.
"""

import ast
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, session
import pytest

from agent_credential_contracts import AgentCredentialReentryRequired
from functions_agent_credential_recovery import model_configuration_error_payload
from functions_model_endpoint_validation import ModelEndpointValidationError
from test_agent_credential_owner_runtime import owners
from test_support.group_agent_harness import ROLE_USER, environment as group_environment
from test_support.versioning import assert_app_version_at_least
from test_workspace_authoring_backend import environment


ROOT = Path(__file__).resolve().parents[1]


def _failure(scope="user", owner_id="actor", agent_id="agent-a", **kwargs):
    return AgentCredentialReentryRequired(
        agent_id=agent_id, scope=scope, owner_id=owner_id, **kwargs,
    )


def _payload(app, error, user_id="actor", roles=("User",)):
    with app.test_request_context("/api/chat/stream"):
        session["user"] = {"oid": user_id, "roles": list(roles)}
        return model_configuration_error_payload(error)


def _group_getter(monkeypatch, group_id="group-a", agent_id="agent-a"):
    getter = Mock(return_value={
        "id": agent_id, "group_id": group_id, "agent_actions": ["edit"],
        "azure_openai_gpt_key": "synthetic-private-key",
        "_agent_credential_bindings": {"private": "synthetic-private-binding"},
    })
    monkeypatch.setitem(sys.modules, "functions_group_agents", SimpleNamespace(
        get_group_agent=getter, SecretReturnType=SimpleNamespace(NAME="NAME"),
    ))
    return getter


def test_implementation_version():
    assert_app_version_at_least("0.261.429")


@pytest.mark.parametrize("scope", ["personal", "global"])
def test_real_credential_failure_links_to_its_authorized_owner_editor(owners, scope):
    env, modules, containers = owners
    module = modules[scope]
    record = {
        "id": "agent-a", "name": "agent-a", "azure_openai_gpt_key": "legacy-private-key",
    }
    if scope == "personal":
        record["user_id"] = "actor"
    containers[scope].create_item(record)
    with pytest.raises(AgentCredentialReentryRequired) as raised:
        if scope == "personal":
            module.get_personal_agent("actor", record["id"], return_type=module.SecretReturnType.VALUE)
        else:
            module.get_global_agent(record["id"], return_type=module.SecretReturnType.VALUE)
    error = raised.value
    payload = _payload(env.app, error, roles=("Admin",) if scope == "global" else ("User",))
    recovery = payload["agent_credential_recovery"]
    base = "/v2/workspace" if scope == "personal" else "/v2/admin"
    assert recovery == {
        "scope": scope, "can_edit": True,
        "edit_url": f"{base}/agents/agent-a?section=model",
    }
    assert error.agent_id == record["id"]
    assert "legacy-private-key" not in json.dumps(payload)
    assert "_agent_credential_bindings" not in json.dumps(payload)
    assert env.services.secret_reads == []
    assert env.services.secret_writes == []


@pytest.mark.parametrize("flag", ["enable_semantic_kernel", "enable_user_workspace", "allow_user_agents"])
def test_personal_editor_link_respects_current_authoring_flags(owners, flag):
    env, _modules, containers = owners
    containers["personal"].create_item({"id": "agent-a", "user_id": "actor"})
    env.services.settings[flag] = False
    payload = _payload(env.app, _failure())
    assert payload["agent_credential_recovery"] == {"scope": "personal", "can_edit": False}
    assert "contact a site administrator" in payload["error"]


def test_personal_governance_denial_and_foreign_owner_never_get_a_link(owners):
    env, _modules, containers = owners
    containers["personal"].create_item({"id": "agent-a", "user_id": "actor"})
    env.services.denied_features.add("governance_user_agents")
    denied = _payload(env.app, _failure())
    foreign = _payload(env.app, _failure(owner_id="another-user"))
    assert denied["agent_credential_recovery"]["can_edit"] is False
    assert "agent_credential_recovery" not in foreign
    assert "another-user" not in json.dumps(foreign)


@pytest.mark.parametrize("role,can_edit", [
    ("Owner", True), ("Admin", True), ("DocumentManager", False), ("User", False),
])
def test_group_recovery_uses_real_role_policy_not_stored_action_hints(group_environment, monkeypatch, role, can_edit):
    env = group_environment
    getter = _group_getter(monkeypatch)
    payload = _payload(env.app, _failure("group", "group-a"), user_id=ROLE_USER[role])
    recovery = payload["agent_credential_recovery"]
    assert recovery["scope"] == "group"
    assert recovery["can_edit"] is can_edit
    if can_edit:
        assert recovery["edit_url"] == "/v2/groups/group-a/agents/agent-a?section=model"
        getter.assert_called_once_with("group-a", "agent-a", return_type="NAME")
    else:
        assert "edit_url" not in recovery
        assert "contact a group owner" in payload["error"]
        getter.assert_not_called()
    serialized = json.dumps(payload)
    assert "synthetic-private" not in serialized
    assert "_agent_credential_bindings" not in serialized


@pytest.mark.parametrize("user_id,can_edit", [("owner", True), ("admin", False)])
def test_group_owner_only_policy_is_respected(group_environment, monkeypatch, user_id, can_edit):
    env = group_environment
    env.settings["require_owner_for_group_agent_management"] = True
    _group_getter(monkeypatch)
    payload = _payload(env.app, _failure("group", "group-a"), user_id=user_id)
    assert payload["agent_credential_recovery"]["can_edit"] is can_edit


@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp", "inactive-grp", "haunted-grp", "missing"])
def test_group_status_or_missing_group_prevents_an_editor_link(group_environment, monkeypatch, group_id):
    env = group_environment
    getter = _group_getter(monkeypatch, group_id)
    payload = _payload(env.app, _failure("group", group_id), user_id="owner")
    assert payload["agent_credential_recovery"] == {"scope": "group", "can_edit": False}
    getter.assert_not_called()


@pytest.mark.parametrize("denial", ["membership", "governance", "feature", "workspace"])
def test_revoked_group_access_cannot_be_replaced_by_a_site_admin_claim(group_environment, monkeypatch, denial):
    env = group_environment
    getter = _group_getter(monkeypatch)
    if denial == "membership":
        env.groups["group-a"]["owner"] = {"id": "someone-else"}
    elif denial == "governance":
        env.governance.is_governance_access_allowed.return_value = False
    elif denial == "feature":
        env.settings["allow_group_agents"] = False
    else:
        env.settings["enable_group_workspaces"] = False
    payload = _payload(env.app, _failure("group", "group-a"), user_id="owner", roles=("Admin",))
    assert payload["agent_credential_recovery"]["can_edit"] is False
    getter.assert_not_called()


@pytest.mark.parametrize("change", ["missing", "agent-id", "group-id"])
def test_missing_or_mismatched_canonical_group_record_never_gets_a_link(group_environment, monkeypatch, change):
    env = group_environment
    getter = _group_getter(monkeypatch)
    if change == "missing":
        getter.return_value = None
    elif change == "agent-id":
        getter.return_value["id"] = "different-agent"
    else:
        getter.return_value["group_id"] = "different-group"
    payload = _payload(env.app, _failure("group", "group-a"), user_id="owner")
    assert payload["agent_credential_recovery"] == {"scope": "group", "can_edit": False}
    assert "different-" not in json.dumps(payload)


def test_current_global_admin_only_gets_global_editor_link(owners):
    env, _modules, containers = owners
    containers["global"].create_item({"id": "agent-a", "name": "global-agent"})
    ordinary = _payload(env.app, _failure("global", "global"))
    admin = _payload(env.app, _failure("global", "global"), roles=("Admin",))
    assert ordinary["agent_credential_recovery"] == {"scope": "global", "can_edit": False}
    assert "contact a site administrator" in ordinary["error"]
    assert admin["agent_credential_recovery"]["edit_url"] == "/v2/admin/agents/agent-a?section=model"


@pytest.mark.parametrize("scope,owner_id", [("user", "actor"), ("global", "global")])
def test_missing_agent_never_gets_a_link(owners, scope, owner_id):
    env, _modules, _containers = owners
    payload = _payload(env.app, _failure(scope, owner_id), roles=("Admin",))
    assert payload["agent_credential_recovery"]["can_edit"] is False
    assert "edit_url" not in payload["agent_credential_recovery"]


@pytest.mark.parametrize("agent_id", ["..", ".", "agent/other", "agent\\other", "x?scope=global", "x\n", "x#fragment"])
def test_invalid_resource_metadata_cannot_become_a_navigation_target(owners, agent_id):
    env, _modules, _containers = owners
    payload = _payload(env.app, _failure(agent_id=agent_id))
    assert "agent_credential_recovery" not in payload
    assert "edit_url" not in json.dumps(payload)


def test_agent_ids_are_encoded_and_no_credentials_are_sent(owners):
    env, _modules, containers = owners
    containers["personal"].create_item({
        "id": "agent:a%value", "user_id": "actor", "azure_openai_gpt_key": "never-send-this",
    })
    payload = _payload(env.app, _failure(agent_id="agent:a%value", incomplete=True))
    assert payload["agent_credential_recovery"]["edit_url"] == (
        "/v2/workspace/agents/agent%3Aa%25value?section=model"
    )
    assert payload["error"].startswith("Agent connection settings need updating.")
    assert "never-send-this" not in json.dumps(payload)


def _chat_error_handlers():
    """Execute the actual JSON/SSE catch bodies without importing cloud bootstrap."""
    source = ROOT / "application" / "single_app" / "route_backend_chats.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    handlers = [
        node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name) and node.type.id == "ModelEndpointValidationError"
    ]
    assert len(handlers) == 2
    for index, handler in enumerate(handlers):
        function = ast.FunctionDef(
            name=f"handler_{index}",
            args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="error")], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=deepcopy(handler.body), decorator_list=[],
        )
        namespace = {
            "json": json, "jsonify": jsonify, "logging": logging, "log_event": Mock(),
            "model_configuration_error_payload": model_configuration_error_payload,
        }
        compiled = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        exec(compile(compiled, str(source), "exec"), namespace)
        yield namespace[function.name], any(isinstance(node, ast.Yield) for node in ast.walk(function))


@pytest.mark.parametrize("agent_error", [True, False])
def test_actual_chat_json_and_sse_catches_keep_the_recovery_envelope(owners, agent_error):
    env, _modules, containers = owners
    containers["personal"].create_item({"id": "agent-a", "user_id": "actor"})
    error = _failure() if agent_error else ModelEndpointValidationError("Approved model connection is invalid.")
    for handler, streaming in _chat_error_handlers():
        with env.app.test_request_context("/api/chat/stream"):
            session["user"] = {"oid": "actor", "roles": ["User"]}
            result = handler(error)
            if streaming:
                frames = list(result)
                assert len(frames) == 1
                payload = json.loads(frames[0].removeprefix("data: ").strip())
                done = payload.pop("done")
                assert done is True
            else:
                response, status = result
                payload = response.get_json()
                assert status == 400
        assert payload["error_code"] == "model_configuration_invalid"
        if agent_error:
            assert payload["agent_credential_recovery"]["can_edit"] is True
        else:
            assert payload == {"error": error.public_message, "error_code": "model_configuration_invalid"}


def test_background_errors_do_not_advertise_viewer_permissions():
    error = _failure("group", "group-a")
    payload = model_configuration_error_payload(error)
    app = Flask("recovery-no-viewer")
    app.secret_key = "synthetic-test-session"
    anonymous = _payload(app, error, user_id=None)
    assert "agent_credential_recovery" not in payload
    assert "agent_credential_recovery" not in anonymous
