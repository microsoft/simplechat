# test_group_action_named_group_test_resolution.py
"""
Functional test for the M4 §8 B5 named-group action-test resolver.

Version: 0.261.137
Implemented in: 0.261.137

A group-scoped action *test* must target the group named in the request body's
top-level ``group_id``, never the account's stale active group. Before this fix,
both ``_load_existing_plugin_for_test`` and ``_resolve_action_identity_context``
resolved ``require_active_group``, so a saved-action test launched from group B's
page while group A was selected looked in A, and an unsaved test bound identity
and secret context to A.

These tests execute the real resolvers unchanged over injected group-membership
and storage seams. They prove: a present ``group_id`` is authoritative and never
falls back to the active group; the ``test`` capability is reauthorized in that
group through the one policy predicate (so a reader, a locked group, or an
unknown group is refused); a ``group_id`` sent with a non-group action is
refused; and, with no ``group_id``, the legacy active-group path is unchanged.
"""

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least


ACTIVE_SETTINGS = {
    "enable_group_workspaces": True,
    "enable_semantic_kernel": True,
    "per_user_semantic_kernel": True,
    "allow_group_agents": True,
    "allow_group_plugins": True,
    "require_owner_for_group_agent_management": False,
}


def _group(status="active", **roles):
    return {"id": "grp", "status": status, "roles": dict(roles)}


class Model:
    """A tiny group/action world the real resolvers run against."""

    def __init__(self):
        # editor is an Admin in A, only a User in B; owner owns both.
        self.groups = {
            "group-a": _group(owner="Owner", editor="Admin"),
            "group-b": _group(owner="Owner", editor="User"),
            "locked-b": _group(status="locked", owner="Owner"),
        }
        # A saved action stored in each group's partition.
        self.saved = {
            ("group-a", "act"): {"id": "act", "name": "act", "type": "openapi", "group_id": "group-a"},
            ("group-b", "act"): {"id": "act", "name": "act", "type": "openapi", "group_id": "group-b"},
        }
        self.require_active_group = Mock(return_value="group-a")
        self.settings = dict(ACTIVE_SETTINGS)

    def find_group_by_id(self, group_id):
        found = self.groups.get(group_id)
        return dict(found, id=group_id) if found else None

    def get_user_role_in_group(self, group, user_id):
        return (group or {}).get("roles", {}).get(user_id)

    def assert_group_role(self, user_id, group_id, allowed_roles=("Owner", "Admin")):
        group = self.groups.get(group_id)
        if not group:
            raise LookupError("Group not found")
        role = self.get_user_role_in_group(group, user_id)
        if not role:
            raise PermissionError("Not a member")
        if role.lower() not in {r.lower() for r in allowed_roles}:
            raise PermissionError("Insufficient role")
        return role

    def get_group_action(self, group_id, identifier, return_type=None):
        record = self.saved.get((group_id, identifier))
        return dict(record) if record else None


def _load_policy(monkeypatch):
    monkeypatch.setitem(sys.modules, "functions_governance", module_stub(
        "functions_governance", is_action_scope_access_allowed=lambda *a, **k: True,
    ))
    spec = importlib.util.spec_from_file_location(
        "functions_group_action_policy", APP_ROOT / "functions_group_action_policy.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "functions_group_action_policy", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def resolvers(monkeypatch):
    model = Model()
    policy = _load_policy(monkeypatch)

    def bind_action_origin(plugin, scope_type, scope_id):
        bound = dict(plugin)
        bound["_origin"] = (scope_type, scope_id)
        return bound

    def get_action_origin(plugin):
        origin = plugin.get("_origin")
        if not origin:
            return None
        return SimpleNamespace(scope_type=origin[0], scope_id=origin[1], action_id=plugin.get("id"))

    namespace = {
        "str": str, "dict": dict, "isinstance": isinstance,
        "find_group_by_id": model.find_group_by_id,
        "get_user_role_in_group": model.get_user_role_in_group,
        "assert_group_role": model.assert_group_role,
        "require_active_group": model.require_active_group,
        "get_settings": lambda: model.settings,
        "group_action_management_operations": policy.group_action_management_operations,
        "get_group_action": model.get_group_action,
        "get_global_action": Mock(return_value=None),
        "get_personal_action": Mock(return_value=None),
        "get_legacy_personal_action_record": Mock(return_value=None),
        "bind_action_origin": bind_action_origin,
        "get_action_origin": get_action_origin,
        "SecretReturnType": SimpleNamespace(NAME="name", VALUE="value"),
        "LEGACY_ACTION_PREFIX": "legacy::",
        "WORKSPACE_IDENTITY_SCOPE_GROUP": "group",
        "WORKSPACE_IDENTITY_SCOPE_GLOBAL": "global",
        "WORKSPACE_IDENTITY_SCOPE_PERSONAL": "personal",
        "session": {},
    }
    execute_functions("route_backend_plugins.py", {
        "_resolve_group_for_test",
        "_resolve_action_identity_context",
        "_load_existing_plugin_for_test",
    }, namespace)
    return SimpleNamespace(model=model, ns=namespace)


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.137")


# --------------------------------------------------------------------------
# _resolve_group_for_test: the named group is authoritative
# --------------------------------------------------------------------------

def test_named_group_is_used_without_touching_the_active_group(resolvers):
    resolve = resolvers.ns["_resolve_group_for_test"]
    assert resolve("owner", "group-b") == "group-b"
    resolvers.model.require_active_group.assert_not_called()


def test_reader_in_the_named_group_is_refused(resolvers):
    # 'editor' is only a User in group-b, so the test capability is refused there,
    # even though the same account is an Admin in the (irrelevant) active group A.
    with pytest.raises(PermissionError):
        resolvers.ns["_resolve_group_for_test"]("editor", "group-b")
    resolvers.model.require_active_group.assert_not_called()


def test_locked_named_group_is_refused(resolvers):
    with pytest.raises(PermissionError):
        resolvers.ns["_resolve_group_for_test"]("owner", "locked-b")


def test_unknown_named_group_is_refused(resolvers):
    with pytest.raises(PermissionError):
        resolvers.ns["_resolve_group_for_test"]("owner", "ghost")


def test_blank_group_id_is_refused(resolvers):
    with pytest.raises(PermissionError):
        resolvers.ns["_resolve_group_for_test"]("owner", "   ")


# --------------------------------------------------------------------------
# _load_existing_plugin_for_test: load from the named group's partition
# --------------------------------------------------------------------------

def test_saved_action_loads_from_the_named_group_not_the_active_group(resolvers):
    load = resolvers.ns["_load_existing_plugin_for_test"]
    plugin = load({"scope": "group", "id": "act"}, "owner", requested_group_id="group-b")
    assert plugin["_origin"] == ("group", "group-b")
    resolvers.model.require_active_group.assert_not_called()


def test_saved_action_test_from_a_group_where_caller_is_a_reader_is_refused(resolvers):
    load = resolvers.ns["_load_existing_plugin_for_test"]
    with pytest.raises(PermissionError):
        load({"scope": "group", "id": "act"}, "editor", requested_group_id="group-b")
    # It never fell back to group A, where 'editor' is an Admin.
    resolvers.model.require_active_group.assert_not_called()


def test_saved_action_test_without_group_id_uses_the_active_group(resolvers):
    load = resolvers.ns["_load_existing_plugin_for_test"]
    plugin = load({"scope": "group", "id": "act"}, "owner")
    assert plugin["_origin"] == ("group", "group-a")
    resolvers.model.require_active_group.assert_called_once_with("owner")


# --------------------------------------------------------------------------
# _resolve_action_identity_context: named group for identity + secret scope
# --------------------------------------------------------------------------

def test_identity_of_a_saved_action_resolves_to_the_named_group(resolvers):
    resolve = resolvers.ns["_resolve_action_identity_context"]
    existing = {"id": "act", "_origin": ("group", "group-b")}
    scope_type, scope_id = resolve({"action_scope": "group", "group_id": "group-b"}, existing, "owner")
    assert (scope_type, scope_id) == ("group", "group-b")
    resolvers.model.require_active_group.assert_not_called()


def test_saved_action_from_another_group_is_refused(resolvers):
    resolve = resolvers.ns["_resolve_action_identity_context"]
    existing = {"id": "act", "_origin": ("group", "group-a")}
    with pytest.raises(PermissionError):
        resolve({"action_scope": "group", "group_id": "group-b"}, existing, "owner")


def test_group_id_with_a_non_group_action_is_refused(resolvers):
    resolve = resolvers.ns["_resolve_action_identity_context"]
    with pytest.raises(PermissionError):
        resolve({"action_scope": "personal", "group_id": "group-b"}, None, "owner")


def test_unsaved_group_test_from_a_reader_group_is_refused(resolvers):
    resolve = resolvers.ns["_resolve_action_identity_context"]
    with pytest.raises(PermissionError):
        resolve({"action_scope": "group", "group_id": "group-b"}, None, "editor")
    resolvers.model.require_active_group.assert_not_called()


def test_unsaved_group_test_without_group_id_uses_the_active_group(resolvers):
    resolve = resolvers.ns["_resolve_action_identity_context"]
    scope_type, scope_id = resolve({"action_scope": "group"}, None, "owner")
    assert (scope_type, scope_id) == ("group", "group-a")
    resolvers.model.require_active_group.assert_called_once_with("owner")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
