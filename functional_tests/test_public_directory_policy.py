# test_public_directory_policy.py
"""
Functional test for the public directory creation policy and its ``can_create`` hint (M10A).
Version: 0.261.179
Implemented in: 0.261.179

``public_creation_refusal`` is the one creation decision the native public directory
publishes, and ``build_public_directory_hints`` reports it as ``can_create``. Unlike a
group, a public workspace has no native create route: the V2 Create affordance reuses the
classic ``POST /api/public_workspaces`` unchanged, whose gate is two decorators
(``create_public_workspace_role_required`` then ``enabled_required("enable_public_workspaces")``).
So the refusal is only the hint's decision -- there is no second native gate that also reads it --
and this test holds it to the classic decorators across every combination of
``enable_public_workspaces`` and ``require_member_of_create_public_workspace`` (each on, off and
missing) and the session's app roles (a plain user, a ``CreatePublicWorkspaces`` holder, an
``Admin``, no roles, ``None`` and no ``roles`` key):

- the classic decorator stack, run for real, allows exactly what the policy allows, except where it
  crashes on ``None`` roles, which the policy refuses;
- the ``public_directory`` hint the directory GET carries always agrees with what the classic create
  route would do for the same caller, and the hint is published only by that directory response.
"""

import ast
import functools
import itertools
from pathlib import Path

import pytest
from flask import Flask

from test_support.public_directory_harness import public_directory_environment


MISSING = object()
FLAG_VALUES = {"on": True, "off": False, "missing": MISSING}
ROLE_CASES = {
    "user": ["User"],
    "creator": ["User", "CreatePublicWorkspaces"],
    "admin": ["Admin"],
    "no_roles": [],
    "none": None,
    "missing": MISSING,
}
COMBINATIONS = list(itertools.product(FLAG_VALUES, FLAG_VALUES, ROLE_CASES))
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


@pytest.fixture(scope="module")
def module_env():
    with public_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def settings_for(workspaces, require):
    settings = {}
    for key, value in (
        ("enable_public_workspaces", FLAG_VALUES[workspaces]),
        ("require_member_of_create_public_workspace", FLAG_VALUES[require]),
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
    """Run the classic create gates exactly as ``api_create_public_workspace`` stacks them."""
    authentication = env.modules.authentication
    app = Flask("legacy_public_create_gates")
    app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")

    @app.route("/api/public_workspaces", methods=["POST"])
    @authentication.create_public_workspace_role_required
    @authentication.enabled_required("enable_public_workspaces")
    def create():
        return "created", 201

    env.settings.clear()
    env.settings.update(settings)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = session_user(role_case)
    try:
        response = client.post("/api/public_workspaces")
    except TypeError:
        return "error"
    return "allowed" if response.status_code == 201 else "refused"


@pytest.mark.parametrize("workspaces,require,role_case", COMBINATIONS)
def test_the_policy_matches_the_classic_gates(env, workspaces, require, role_case):
    settings = settings_for(workspaces, require)
    policy = env.modules.policy
    refusal = policy.public_creation_refusal(settings, session_roles(role_case))
    decorators = legacy_decorator_outcome(env, settings, role_case)

    if decorators == "error":
        # The classic decorator reads ``'CreatePublicWorkspaces' in None`` and raises; the policy
        # refuses instead, failing closed on roles it cannot read.
        assert ROLE_CASES[role_case] is None and FLAG_VALUES[require] is True
        assert refusal is not None
    else:
        assert (refusal is None) == (decorators == "allowed")

    hints = policy.build_public_directory_hints(settings, session_roles(role_case))
    assert hints == {"schema_version": 1, "can_create": refusal is None}


def test_switched_off_workspaces_are_reported_before_a_missing_role(env):
    policy = env.modules.policy
    settings = {"enable_public_workspaces": False, "require_member_of_create_public_workspace": True}
    assert policy.public_creation_refusal(settings, ["User"]) == policy.PUBLIC_CREATION_DISABLED
    settings["enable_public_workspaces"] = True
    assert policy.public_creation_refusal(settings, ["User"]) == policy.PUBLIC_CREATION_ROLE_REQUIRED
    assert policy.public_creation_refusal(settings, ["User", "CreatePublicWorkspaces"]) is None


def test_roles_that_are_not_a_list_of_names_count_as_no_roles(env):
    """The policy fails closed: only a real collection of role names satisfies the requirement."""
    policy = env.modules.policy
    settings = {"enable_public_workspaces": True, "require_member_of_create_public_workspace": True}
    for roles in ("CreatePublicWorkspaces", "User,CreatePublicWorkspaces", {"CreatePublicWorkspaces": True}, 7, [None, 3]):
        assert policy.public_creation_refusal(settings, roles) == policy.PUBLIC_CREATION_ROLE_REQUIRED
    assert policy.public_creation_refusal(settings, ("User", "CreatePublicWorkspaces")) is None
    assert policy.public_creation_refusal(settings, frozenset({"CreatePublicWorkspaces"})) is None


def test_settings_that_are_not_a_dict_refuse_everything(env):
    policy = env.modules.policy
    for settings in (None, [], "enable_public_workspaces"):
        assert policy.public_creation_refusal(settings, ["User", "CreatePublicWorkspaces"]) == policy.PUBLIC_CREATION_DISABLED
        assert policy.build_public_directory_hints(settings, ["User"]) == {
            "schema_version": 1, "can_create": False,
        }


ROUTE_ROLE_CASES = ("user", "creator", "admin")
ROUTE_COMBINATIONS = list(itertools.product(FLAG_VALUES, ROUTE_ROLE_CASES))


@pytest.mark.parametrize("require,role_case", ROUTE_COMBINATIONS)
def test_the_directory_hint_agrees_with_the_classic_create_gate(env, require, role_case):
    env.settings.clear()
    env.settings.update(settings_for("on", require))
    env.as_user("outsider-1", roles=ROLE_CASES[role_case])
    listed = env.directory()
    assert listed.status_code == 200
    can_create = listed.get_json()["public_directory"]["can_create"]

    # The classic create route is reused unchanged, so its own decorator stack is the ground truth.
    decorators = legacy_decorator_outcome(env, settings_for("on", require), role_case)
    assert can_create == (decorators == "allowed")


def test_with_public_workspaces_off_the_directory_refuses_before_the_container(env):
    env.settings["enable_public_workspaces"] = False
    env.public_workspaces.calls.clear()
    response = env.directory()
    assert response.status_code == 400
    assert response.get_json() == {"error": "Enable Public Workspaces is disabled."}
    assert env.public_workspaces.calls == []


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
    """The directory GET carries the hint; the V2 bootstrap does not."""
    assert _references("build_public_directory_hints") == [
        "functions_public_directory.py", "functions_public_directory_policy.py",
    ]
    bootstrap = (APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8")
    assert "public_directory" not in bootstrap


def test_the_refusal_lives_only_in_the_policy_and_creation_stays_classic():
    """Public has no native create route, so the refusal is only the hint's decision.

    Unlike the group directory, where ``group_creation_refusal`` also gates a native create route,
    ``public_creation_refusal`` is referenced only by the policy module: the V2 Create affordance
    reuses the classic ``POST /api/public_workspaces`` unchanged, and the directory GET route does
    not stack any creation gate of its own.
    """
    assert _references("public_creation_refusal") == ["functions_public_directory_policy.py"]

    classic = (APP_ROOT / "route_backend_public_workspaces.py").read_text(encoding="utf-8")
    assert "create_public_workspace_role_required" in classic
    assert 'enabled_required("enable_public_workspaces")' in classic

    directory_route = (APP_ROOT / "route_backend_public_directory.py").read_text(encoding="utf-8")
    assert "create_public_workspace_role_required" not in directory_route


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
