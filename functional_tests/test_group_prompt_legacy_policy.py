# test_group_prompt_legacy_policy.py
"""
Pin the tightened legacy group-prompt route policy and the phantom role.
Version: 0.261.136
Implemented in: 0.261.136

The M0 parity baseline recorded that the group prompt UI permits only manager
roles while the legacy CRUD route helper admitted ordinary ``User`` membership,
and set the boundary: preserve V1's Owner/Admin/DocumentManager edit eligibility
and do not expose new ``User`` edits as an accidental V2 migration change. M3
tightens the legacy write routes to O/A/D to match that boundary and the policy
public prompts already enforce, while the legacy reads keep the four-role
default.

This test pins that decision two ways so it cannot silently regress:

* Behaviourally, the real ``require_active_group`` enforcement refuses a ``User``
  when the manager role set is supplied and admits a ``User`` under the default
  read set.
* Structurally, the three legacy write routes pass the manager role set and the
  two legacy read routes do not.

It also proves ``PromptManager`` -- a role that exists only in the V1 template's
``canManageGroupPrompts()`` helper -- appears in no server-side role list.
"""

import ast
import socket
import sys
from copy import deepcopy
from functools import wraps
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify
from typing import Iterable

from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least

APP_DIR = Path(APP_ROOT)
LEGACY_FILE = "route_backend_group_prompts.py"
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "member"}


def _group():
    return {
        "id": "grp",
        "name": "Group grp",
        "status": "active",
        "owner": {"id": "owner"},
        "admins": ["admin"],
        "documentManagers": ["manager"],
        "users": [{"userId": "member"}],
    }


@pytest.fixture
def resolver(monkeypatch):
    """Exec the real active-group enforcement and the legacy helper together."""
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in this test."))
        scoped.setattr(socket, "create_connection", network)

        group_doc = _group()
        settings_module = module_stub(
            "functions_settings",
            get_user_settings=lambda user_id: {"settings": {"activeGroupOid": "grp"}},
        )

        group_namespace = {
            "Iterable": Iterable,
            "functions_settings": settings_module,
            "find_group_by_id": lambda group_id: deepcopy(group_doc) if group_id == "grp" else None,
        }
        execute_functions("functions_group.py", {
            "get_user_role_in_group", "assert_group_role", "require_active_group",
        }, group_namespace)

        route_namespace = {
            "jsonify": jsonify,
            "require_active_group": group_namespace["require_active_group"],
            "GROUP_PROMPT_MEMBER_ROLES": ("Owner", "Admin", "DocumentManager", "User"),
            "GROUP_PROMPT_WRITE_ROLES": MANAGER_ROLES,
        }
        execute_functions(
            LEGACY_FILE, {"_get_active_group_or_error", "_is_active_group_member"}, route_namespace,
        )
        helper = route_namespace["_get_active_group_or_error"]

        app = Flask("legacy_group_prompt_policy")

        def resolve(*args, **kwargs):
            with app.app_context():
                return helper(*args, **kwargs)

        yield resolve


def _status(result):
    """Return the HTTP status the helper produced, or None when it resolved."""
    _group_id, error = result
    return None if error is None else error[1]


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.136")


# --------------------------------------------------------------------------
# Behavioural: the enforcement the legacy routes rely on
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_manager_roles_pass_the_write_gate(resolver, role):
    group_id, error = resolver(ROLE_USER[role], allowed_roles=MANAGER_ROLES)
    assert error is None
    assert group_id == "grp"


def test_user_is_refused_the_write_gate(resolver):
    assert _status(resolver("member", allowed_roles=MANAGER_ROLES)) == 403


def _message(result):
    _group_id, error = result
    return error[0].get_json()["error"]


def test_a_member_refused_a_write_is_told_it_is_a_role_problem(resolver):
    """Tightening the writes made a new 403 reachable by members.

    Before the fix, members could never be refused here, so the helper's
    single "not a member" message was never shown to one. Now a member who
    lacks the role would be told they are not a member, which is false and
    sends them looking for a membership problem that does not exist.
    """
    message = _message(resolver("member", allowed_roles=MANAGER_ROLES))

    assert "not a member" not in message
    assert "owners, admins, and document managers" in message


def test_a_non_member_is_still_told_they_are_not_a_member(resolver):
    """The role message must not leak to someone outside the group."""
    message = _message(resolver("stranger", allowed_roles=MANAGER_ROLES))

    assert message == "You are not a member of the active group"


def test_a_non_member_read_keeps_the_original_message(resolver):
    message = _message(resolver("stranger"))

    assert message == "You are not a member of the active group"


@pytest.mark.parametrize("role", ("Owner", "Admin", "DocumentManager", "User"))
def test_default_read_gate_still_admits_every_member(resolver, role):
    group_id, error = resolver(ROLE_USER[role])
    assert error is None
    assert group_id == "grp"


# --------------------------------------------------------------------------
# Structural: which legacy routes actually carry the manager set
# --------------------------------------------------------------------------

def _legacy_routes():
    tree = ast.parse((APP_DIR / LEGACY_FILE).read_text(encoding="utf-8"))
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                methods = []
                for keyword in decorator.keywords:
                    if keyword.arg == "methods" and isinstance(keyword.value, ast.List):
                        methods = [element.value for element in keyword.value.elts]
                routes.append((decorator.args[0].value, tuple(methods), node))
    return routes


def _passes_manager_roles(function):
    """True when the function calls the helper with allowed_roles=GROUP_PROMPT_WRITE_ROLES."""
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_get_active_group_or_error"
        ):
            for keyword in node.keywords:
                if (
                    keyword.arg == "allowed_roles"
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "GROUP_PROMPT_WRITE_ROLES"
                ):
                    return True
    return False


def test_write_role_constant_is_the_manager_set():
    tree = ast.parse((APP_DIR / LEGACY_FILE).read_text(encoding="utf-8"))
    values = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "GROUP_PROMPT_WRITE_ROLES"
                    for target in node.targets)
            and isinstance(node.value, (ast.Tuple, ast.List))
        ):
            values = tuple(element.value for element in node.value.elts)
    assert values == MANAGER_ROLES, (
        "GROUP_PROMPT_WRITE_ROLES must be exactly Owner/Admin/DocumentManager -- "
        "no User, and no phantom PromptManager."
    )


def test_legacy_writes_carry_the_manager_set_and_reads_do_not():
    checked_writes = 0
    checked_reads = 0
    for path, methods, function in _legacy_routes():
        if not path.startswith("/api/group_prompts"):
            continue
        for method in methods:
            if method in ("POST", "PATCH", "DELETE"):
                checked_writes += 1
                assert _passes_manager_roles(function), (
                    f"legacy {method} {path} must pass allowed_roles=GROUP_PROMPT_WRITE_ROLES"
                )
            elif method == "GET":
                checked_reads += 1
                assert not _passes_manager_roles(function), (
                    f"legacy {method} {path} must keep the four-role default"
                )
    assert checked_writes == 3, "expected the three legacy write routes"
    assert checked_reads == 2, "expected the two legacy read routes"


# --------------------------------------------------------------------------
# The phantom role
# --------------------------------------------------------------------------

def test_prompt_manager_role_exists_nowhere_on_the_server():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if "PromptManager" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], (
        "PromptManager is a V1 template-only role. It must not appear in any "
        f"server-side module, but was found in: {offenders}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
