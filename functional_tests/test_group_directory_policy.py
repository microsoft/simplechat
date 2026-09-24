# test_group_directory_policy.py
"""
Functional test for the group directory creation policy and its hint.
Version: 0.261.147
Implemented in: 0.261.147

``group_creation_refusal`` is the one creation decision of the native group
directory, and ``build_group_directory_hints`` reports it as ``can_create``. This
test holds the decision to the classic gates across every combination of
``enable_group_workspaces``, ``enable_group_creation``,
``require_member_of_create_group`` (each on, off and missing) and the session's app
roles (a plain user, a ``CreateGroups`` holder, an ``Admin``, no roles, ``None`` and
no ``roles`` key at all):

- the classic decorator stack of ``POST /api/groups``
  (``create_group_role_required`` then ``enabled_required`` for creation and for
  workspaces), run for real, allows exactly what the policy allows, except where it
  crashes on ``None`` roles, which the policy refuses;
- the classic helper checks behind ``create_group_for_current_user``, run for real,
  allow exactly what the policy allows and refuse for the same reason.

The seam through the routes is pinned too: the ``group_directory`` hint in the
directory response always agrees with what ``POST /api/groups/directory`` does,
and the hint is published only there.
"""

import ast
import functools
import itertools
from pathlib import Path

import pytest
from flask import Flask, session

from test_support.group_directory_harness import group_directory_environment


MISSING = object()
FLAG_VALUES = {"on": True, "off": False, "missing": MISSING}
ROLE_CASES = {
    "user": ["User"],
    "creator": ["User", "CreateGroups"],
    "admin": ["Admin"],
    "no_roles": [],
    "none": None,
    "missing": MISSING,
}
COMBINATIONS = list(itertools.product(FLAG_VALUES, FLAG_VALUES, FLAG_VALUES, ROLE_CASES))
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
HELPER_REASONS = {
    "Group workspaces are disabled by configuration": "group_creation_disabled",
    "Group creation is disabled by configuration": "group_creation_disabled",
    "Insufficient permissions (CreateGroups role required)": "create_groups_role_required",
}


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def settings_for(workspaces, creation, require):
    settings = {}
    for key, value in (
        ("enable_group_workspaces", FLAG_VALUES[workspaces]),
        ("enable_group_creation", FLAG_VALUES[creation]),
        ("require_member_of_create_group", FLAG_VALUES[require]),
    ):
        if value is not MISSING:
            settings[key] = value
    return settings


def session_user(role_case):
    user = {"oid": "creator-1", "name": "Casey Creator", "preferred_username": "casey@example.test"}
    roles = ROLE_CASES[role_case]
    if roles is not MISSING:
        user["roles"] = roles
    return user


def session_roles(role_case):
    roles = ROLE_CASES[role_case]
    return None if roles is MISSING else roles


def legacy_decorator_outcome(env, settings, role_case):
    """Run the classic create gates exactly as ``api_create_group`` stacks them."""
    authentication = env.modules.authentication
    app = Flask("legacy_create_gates")
    app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")

    @app.route("/api/groups", methods=["POST"])
    @authentication.create_group_role_required
    @authentication.enabled_required("enable_group_creation")
    @authentication.enabled_required("enable_group_workspaces")
    def create():
        return "created", 201

    env.settings.clear()
    env.settings.update(settings)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = session_user(role_case)
    try:
        response = client.post("/api/groups")
    except TypeError:
        return "error"
    return "allowed" if response.status_code == 201 else "refused"


def legacy_helper_outcome(env, settings, role_case):
    """Run the checks ``create_group_for_current_user`` makes before creating."""
    namespace = env.operations_namespace
    env.settings.clear()
    env.settings.update(settings)
    with env.app.test_request_context("/api/groups", method="POST"):
        session["user"] = session_user(role_case)
        try:
            checked = namespace["_require_group_workspaces_enabled"]()
            namespace["_require_group_creation_enabled"](checked)
        except PermissionError as error:
            return HELPER_REASONS[str(error)]
    return None


@pytest.mark.parametrize("workspaces,creation,require,role_case", COMBINATIONS)
def test_the_policy_matches_the_classic_gates(env, workspaces, creation, require, role_case):
    settings = settings_for(workspaces, creation, require)
    policy = env.modules.policy
    refusal = policy.group_creation_refusal(settings, session_roles(role_case))
    helper = legacy_helper_outcome(env, settings, role_case)
    decorators = legacy_decorator_outcome(env, settings, role_case)

    assert refusal == helper
    if decorators == "error":
        # The classic decorator reads ``'CreateGroups' in None`` and raises; the
        # policy refuses, as the classic helper does.
        assert ROLE_CASES[role_case] is None and FLAG_VALUES[require] is True
        assert refusal is not None
    else:
        assert (refusal is None) == (decorators == "allowed")

    hints = policy.build_group_directory_hints(settings, session_roles(role_case))
    assert hints == {
        "schema_version": 1,
        "can_create": refusal is None,
        "can_request_to_join": FLAG_VALUES[workspaces] is True,
    }


def test_switched_off_creation_is_reported_before_a_missing_role(env):
    policy = env.modules.policy
    settings = {"enable_group_workspaces": True, "enable_group_creation": False, "require_member_of_create_group": True}
    assert policy.group_creation_refusal(settings, ["User"]) == policy.GROUP_CREATION_DISABLED
    settings["enable_group_creation"] = True
    assert policy.group_creation_refusal(settings, ["User"]) == policy.GROUP_CREATION_ROLE_REQUIRED
    assert policy.group_creation_refusal(settings, ["User", "CreateGroups"]) is None


def test_roles_that_are_not_a_list_of_names_count_as_no_roles(env):
    """Recorded divergence: the classic checks test ``'CreateGroups' in roles`` on
    whatever the session holds, so a bare string would pass a substring test there.
    The policy fails closed instead."""
    policy = env.modules.policy
    settings = {"enable_group_workspaces": True, "enable_group_creation": True, "require_member_of_create_group": True}
    for roles in ("CreateGroups", "User,CreateGroups", {"CreateGroups": True}, 7, [None, 3]):
        assert policy.group_creation_refusal(settings, roles) == policy.GROUP_CREATION_ROLE_REQUIRED
    assert policy.group_creation_refusal(settings, ("User", "CreateGroups")) is None
    assert policy.group_creation_refusal(settings, frozenset({"CreateGroups"})) is None


def test_settings_that_are_not_a_dict_refuse_everything(env):
    policy = env.modules.policy
    for settings in (None, [], "enable_group_creation"):
        assert policy.group_creation_refusal(settings, ["User", "CreateGroups"]) == policy.GROUP_CREATION_DISABLED
        assert policy.build_group_directory_hints(settings, ["User"]) == {
            "schema_version": 1, "can_create": False, "can_request_to_join": False,
        }


ROUTE_ROLE_CASES = ("user", "creator", "admin")
ROUTE_COMBINATIONS = list(itertools.product(FLAG_VALUES, FLAG_VALUES, ROUTE_ROLE_CASES))


@pytest.mark.parametrize("creation,require,role_case", ROUTE_COMBINATIONS)
def test_the_directory_hint_agrees_with_the_create_route(env, creation, require, role_case):
    env.settings.clear()
    env.settings.update(settings_for("on", creation, require))
    env.as_user("outsider-1", roles=ROLE_CASES[role_case])
    listed = env.directory()
    assert listed.status_code == 200
    can_create = listed.get_json()["group_directory"]["can_create"]

    created = env.create({"name": "Seam group"})
    refusal = env.modules.policy.group_creation_refusal(env.get_settings(), ROLE_CASES[role_case])
    if can_create:
        assert created.status_code == 201, created.get_json()
        assert refusal is None
    else:
        assert created.status_code == 403
        assert created.get_json()["error_code"] == refusal
        assert env.write_calls() == []


def test_with_group_workspaces_off_neither_route_answers(env):
    env.settings["enable_group_workspaces"] = False
    for response in (env.directory(), env.create({"name": "Nope"})):
        assert response.status_code == 400
        assert response.get_json() == {"error": "Enable Group Workspaces is disabled."}
    assert env.groups.queries == [] and env.write_calls() == []


@functools.lru_cache(maxsize=1)
def _application_trees():
    return tuple(
        (path.name, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(APP_ROOT.rglob("*.py"))
    )


def _references(name):
    """Files that define, import or read ``name``."""
    found = []
    for file_name, tree in _application_trees():
        for node in ast.walk(tree):
            if (
                (isinstance(node, ast.Name) and node.id == name)
                or (isinstance(node, ast.alias) and node.name == name)
                or (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name)
            ):
                found.append(file_name)
    return sorted(set(found))


def test_the_hint_is_published_only_by_the_directory_response():
    """Decision §2.2: the directory GET carries the hint; the V2 bootstrap does not."""
    assert _references("build_group_directory_hints") == [
        "functions_group_directory.py", "functions_group_directory_policy.py",
    ]
    bootstrap = (APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8")
    assert "group_directory" not in bootstrap


def test_the_create_route_and_the_hint_use_one_decision():
    """``group_creation_refusal`` gates native creation; the classic decorators are not stacked."""
    assert _references("group_creation_refusal") == [
        "functions_group_directory.py", "functions_group_directory_policy.py",
    ]
    route_source = (APP_ROOT / "route_backend_group_directory.py").read_text(encoding="utf-8")
    assert "create_group_role_required" not in route_source
    assert "enable_group_creation" not in route_source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
