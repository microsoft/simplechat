# test_group_settings_policy.py
"""
Functional test for the native group settings policy and its seam with the classic routes.
Version: 0.261.157
Implemented in: 0.261.154
Unrecognized statuses fail closed for the profile and logo: 0.261.157

``group_settings_decisions`` is the one decision behind the native group settings and
insights routes and their ``settings_management`` block. This test holds it, and the
native routes built on it, to the classic routes' real outcomes, run for real in
``test_support/group_settings_harness.py``:

- the name, description and hero color against ``PATCH /api/groups/<group_id>``: the
  owner, and the ``CreateGroups`` app role when ``require_member_of_create_group`` is
  on, across every group role, that switch on, off and missing, and a plain user, a
  ``CreateGroups`` holder and an ``Admin`` app role;
- the logo against ``POST /api/groups/<group_id>/logo``: the owner only;
- downloads against ``PATCH /api/groups/<group_id>/download-settings``: the owner or
  an admin, with the administrator's download capability;
- retention against ``POST /api/retention-policy/group/<group_id>``: the owner or an
  admin, with group workspaces and group retention policies on;
- the activity, statistics and file count reads against ``/activity``, ``/stats`` and
  ``/fileCount``.

In every cell an allowed operation succeeds on the native route, and a refused one is a
403 carrying the decision's reason. The one rule stricter than the classic routes is
pinned as the only difference: profile and logo writes while the group is ``locked`` or
``inactive``, which the classic manage page makes read-only but the classic routes accept.
"""

import ast
import itertools
from io import BytesIO
from pathlib import Path

import pytest

from test_support.group_settings_harness import group_settings_environment, png_bytes


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
GROUP = "5b6d0c5e-4f3a-4b8e-9d2c-1a7e3f9b2c41"
# Assignment lists hold canonical group GUIDs, so the group under test has one.
OTHER_GROUP = "d3b07384-d9a7-4f3b-8c2e-6f1a2b3c4d5e"
MISSING = object()
CALLERS = {
    "owner-1": "Owner",
    "admin-1": "Admin",
    "manager-1": "DocumentManager",
    "member-1": "User",
    "outsider-1": None,
}
SESSION_ROLES = {"user": ["User"], "creator": ["User", "CreateGroups"], "app_admin": ["Admin"]}
NARROWING = {"on": True, "off": False, "missing": MISSING}
STATUSES = ("active", "upload_disabled", "locked", "inactive")
READ_ONLY_STATUSES = ("locked", "inactive")


@pytest.fixture(scope="module")
def module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def prepare(env, caller, session="user", *, narrowing=MISSING, status="active", **settings):
    env.reset()
    if narrowing is MISSING:
        env.settings.pop("require_member_of_create_group", None)
    else:
        env.settings["require_member_of_create_group"] = narrowing
    env.settings.update(settings)
    env.seed_group(GROUP, status=status)
    env.as_user(caller, SESSION_ROLES[session])


def decision(env, caller, session, operation):
    return env.modules.policy.group_settings_decisions(
        CALLERS[caller], env.stored_group(GROUP), env.get_settings(), SESSION_ROLES[session],
    )[operation]


def allowed(response):
    return 200 <= response.status_code < 300


def assert_native_follows(env, response, caller, reason):
    """The native route does exactly what the decision says."""
    body = response.get_json()
    if caller == "outsider-1":
        assert response.status_code == 403, body
        assert body == {"error": "You do not have access to the selected group.", "error_code": "group_access_denied"}
    elif reason is None:
        assert allowed(response), body
    else:
        assert response.status_code == 403, body
        assert body == {"error": env.modules.settings.REFUSAL_MESSAGES[reason], "error_code": reason}
    assert response.headers["Cache-Control"] == "no-store"


def assert_seam(classic_allows, reason, caller, *, native_only=None):
    """The decision allows what the classic route allows, except the pinned native-only refusals."""
    if caller == "outsider-1":
        assert not classic_allows
        return
    if native_only is not None and classic_allows and reason == native_only:
        return
    assert (reason is None) == classic_allows, (classic_allows, reason)


def logo_upload():
    return {"logo_file": (BytesIO(png_bytes()), "logo.png")}


# ---------------------------------------------------------------------------
# The profile: name, description and hero color
# ---------------------------------------------------------------------------

PROFILE_CELLS = list(itertools.product(CALLERS, NARROWING, SESSION_ROLES, STATUSES))


@pytest.mark.parametrize("caller,narrowing,session,status", PROFILE_CELLS)
def test_profile_writes_follow_the_classic_rename_route(env, caller, narrowing, session, status):
    prepare(env, caller, session, narrowing=NARROWING[narrowing], status=status)
    classic = env.call("PATCH", f"/api/groups/{GROUP}", {"name": "Classic name", "description": "d", "heroColor": "#112233"})

    prepare(env, caller, session, narrowing=NARROWING[narrowing], status=status)
    reasons = {operation: decision(env, caller, session, operation)
               for operation in ("edit_name", "edit_description", "edit_color")}
    assert len(set(reasons.values())) == 1, reasons
    reason = reasons["edit_name"]
    native = env.call("PATCH", f"/api/groups/{GROUP}/settings/profile", {
        "revision": env.revision("profile", GROUP), "name": "Native name", "description": "d", "hero_color": "#112233",
    })

    assert_seam(allowed(classic), reason, caller, native_only="group_status_unavailable")
    if status in READ_ONLY_STATUSES and allowed(classic):
        assert reason == "group_status_unavailable"
    assert_native_follows(env, native, caller, reason)


def test_the_creation_role_rule_ignores_the_creation_switches(env):
    """As in the classic decorator, only the narrowing and the role decide; creation being off does not."""
    prepare(env, "owner-1", "user", narrowing=False, enable_group_creation=False)
    assert decision(env, "owner-1", "user", "edit_name") is None
    prepare(env, "owner-1", "user", narrowing=True, enable_group_creation=False)
    assert decision(env, "owner-1", "user", "edit_name") == "create_groups_role_required"
    prepare(env, "owner-1", "creator", narrowing=True, enable_group_creation=False)
    assert decision(env, "owner-1", "creator", "edit_name") is None


# ---------------------------------------------------------------------------
# The logo
# ---------------------------------------------------------------------------

LOGO_CELLS = list(itertools.product(CALLERS, STATUSES, (False, True)))


@pytest.mark.parametrize("caller,status,narrowed", LOGO_CELLS)
def test_logo_writes_follow_the_classic_upload_route(env, caller, status, narrowed):
    """The logo needs only the owner: narrowing creation to CreateGroups never applies to it."""
    prepare(env, caller, "user", narrowing=narrowed, status=status)
    classic = env.call("POST", f"/api/groups/{GROUP}/logo", data=logo_upload())

    prepare(env, caller, "user", narrowing=narrowed, status=status)
    reason = decision(env, caller, "user", "edit_logo")
    native = env.call("PUT", f"/api/groups/{GROUP}/settings/logo",
                      data={**logo_upload(), "revision": env.revision("logo", GROUP)})

    assert_seam(allowed(classic), reason, caller, native_only="group_status_unavailable")
    if status in READ_ONLY_STATUSES and allowed(classic):
        assert reason == "group_status_unavailable"
    assert_native_follows(env, native, caller, reason)


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

CAPABILITIES = {
    "on": {"allow_group_workspace_file_downloads": True},
    "off": {"allow_group_workspace_file_downloads": False},
    "assigned": {"allow_group_workspace_file_downloads": True, "require_group_assignment_for_file_downloads": True,
                 "file_download_allowed_group_ids": [GROUP]},
    "unassigned": {"allow_group_workspace_file_downloads": True, "require_group_assignment_for_file_downloads": True,
                   "file_download_allowed_group_ids": [OTHER_GROUP]},
}
DOWNLOAD_CELLS = list(itertools.product(CALLERS, CAPABILITIES, ("active", "locked", "inactive")))


@pytest.mark.parametrize("caller,capability,status", DOWNLOAD_CELLS)
def test_download_writes_follow_the_classic_download_settings_route(env, caller, capability, status):
    prepare(env, caller, "user", status=status, **CAPABILITIES[capability])
    classic = env.call("PATCH", f"/api/groups/{GROUP}/download-settings", {"disable_file_downloads": True})

    prepare(env, caller, "user", status=status, **CAPABILITIES[capability])
    reason = decision(env, caller, "user", "edit_downloads")
    native = env.call("PATCH", f"/api/groups/{GROUP}/settings/downloads", {
        "revision": env.revision("downloads", GROUP), "disable_file_downloads": True,
    })

    assert_seam(allowed(classic), reason, caller)
    if caller in ("owner-1", "admin-1"):
        # Each capability cell means what it says: an assigned GUID is allowed, and
        # an assignment elsewhere is refused for the capability, not for a bad id.
        assert (reason is None) == (capability in ("on", "assigned")), (capability, reason)
    assert_native_follows(env, native, caller, reason)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

RETENTION_CELLS = list(itertools.product(CALLERS, (True, False), ("active", "locked", "inactive")))


@pytest.mark.parametrize("caller,retention_on,status", RETENTION_CELLS)
def test_retention_writes_follow_the_classic_retention_route(env, caller, retention_on, status):
    prepare(env, caller, "user", status=status, enable_retention_policy_group=retention_on)
    classic = env.call("POST", f"/api/retention-policy/group/{GROUP}", {
        "conversation_retention_days": 30, "document_retention_days": 30,
    })

    prepare(env, caller, "user", status=status, enable_retention_policy_group=retention_on)
    reason = decision(env, caller, "user", "edit_retention")
    native = env.call("PATCH", f"/api/groups/{GROUP}/settings/retention", {
        "revision": env.revision("retention", GROUP), "conversation_retention_days": 30,
    })

    # Both routes refuse while group retention policies are off, the classic one first of all.
    assert_seam(allowed(classic), reason, caller)
    if not retention_on:
        assert classic.status_code == 403
        assert classic.get_json()["error_code"] == "group_retention_disabled"
    assert_native_follows(env, native, caller, reason)


@pytest.mark.parametrize("caller", CALLERS)
def test_retention_needs_group_workspaces_on_both_routes(env, caller):
    prepare(env, caller, "user", enable_group_workspaces=False)
    classic = env.call("POST", f"/api/retention-policy/group/{GROUP}", {"conversation_retention_days": 30})
    native = env.call("PATCH", f"/api/groups/{GROUP}/settings/retention", {"conversation_retention_days": 30})
    for response in (classic, native):
        assert response.status_code == 400
        assert response.get_json() == {"error": "Enable Group Workspaces is disabled."}
    assert env.write_calls() == []


# ---------------------------------------------------------------------------
# The reads
# ---------------------------------------------------------------------------

READS = {
    "view_activity": ("/activity", "/insights/activity"),
    "view_stats": ("/stats", "/insights/stats"),
    "view_file_count": ("/fileCount", "/insights/file-count"),
}
READ_CELLS = list(itertools.product(CALLERS, READS, ("active", "locked", "inactive")))


@pytest.mark.parametrize("caller,operation,status", READ_CELLS)
def test_insight_reads_follow_the_classic_reads(env, caller, operation, status):
    classic_path, native_path = READS[operation]
    prepare(env, caller, "user", status=status)
    classic = env.call("GET", f"/api/groups/{GROUP}{classic_path}")
    reason = decision(env, caller, "user", operation)
    native = env.call("GET", f"/api/groups/{GROUP}{native_path}")

    assert_seam(allowed(classic), reason, caller)
    assert_native_follows(env, native, caller, reason)


@pytest.mark.parametrize("caller", CALLERS)
def test_the_settings_read_needs_an_owner_or_admin_as_the_classic_settings_tab_does(env, caller):
    prepare(env, caller)
    response = env.settings_read(GROUP)
    if caller in ("owner-1", "admin-1"):
        assert response.status_code == 200
        assert response.get_json()["settings"]["viewer_role"] == CALLERS[caller]
    elif caller == "outsider-1":
        assert response.status_code == 403
        assert response.get_json()["error_code"] == "group_access_denied"
    else:
        assert response.status_code == 403
        assert response.get_json()["error_code"] == "group_manager_required"


# ---------------------------------------------------------------------------
# The decision itself
# ---------------------------------------------------------------------------

def test_the_role_is_reported_before_the_creation_role_and_the_creation_role_before_the_status(env):
    policy = env.modules.policy
    narrowed = {"require_member_of_create_group": True, "allow_group_workspace_file_downloads": True}
    locked = {"id": GROUP, "status": "locked"}
    assert policy.group_settings_decisions("Admin", locked, narrowed, ["User"])["edit_name"] == "group_owner_required"
    assert policy.group_settings_decisions("Owner", locked, narrowed, ["User"])["edit_name"] == "create_groups_role_required"
    assert policy.group_settings_decisions("Owner", locked, narrowed, ["CreateGroups"])["edit_name"] == "group_status_unavailable"
    assert policy.group_settings_decisions("Owner", locked, narrowed, ["User"])["edit_logo"] == "group_status_unavailable"
    assert policy.group_settings_decisions("Admin", locked, narrowed, ["User"])["edit_logo"] == "group_owner_required"


@pytest.mark.parametrize("roles", [None, "CreateGroups", {"CreateGroups": True}, [None, 5]])
def test_roles_that_are_not_a_list_of_names_count_as_no_roles(env, roles):
    decisions = env.modules.policy.group_settings_decisions(
        "Owner", {"id": GROUP}, {"require_member_of_create_group": True}, roles,
    )
    assert decisions["edit_name"] == "create_groups_role_required"


@pytest.mark.parametrize("group", [{"id": GROUP}, {"id": GROUP, "status": "active"}, {"id": GROUP, "status": "upload_disabled"}],
                         ids=["missing", "active", "upload_disabled"])
def test_only_active_and_upload_disabled_groups_can_change_the_profile(env, group):
    decisions = env.modules.policy.group_settings_decisions("Owner", group, {}, ["User"])
    assert decisions["edit_name"] is None and decisions["edit_logo"] is None


@pytest.mark.parametrize("status", ["locked", "inactive", None, "", "archived", "unknown-status"])
def test_every_other_status_keeps_the_profile_and_logo_read_only(env, status):
    """Locked and inactive, as the classic page makes them; a status this version doesn't
    recognize fails closed, as the workspace context and adding a member do. The reads keep
    working, and only the status-restricted operations change."""
    decisions = env.modules.policy.group_settings_decisions("Owner", {"id": GROUP, "status": status}, {}, ["User"])
    for operation in ("edit_name", "edit_description", "edit_color", "edit_logo"):
        assert decisions[operation] == "group_status_unavailable", operation
    assert decisions["view_activity"] is None and decisions["view_stats"] is None
    assert decisions["view_file_count"] is None


def test_settings_that_are_not_a_dict_turn_off_every_gated_operation(env):
    decisions = env.modules.policy.group_settings_decisions("Owner", {"id": GROUP}, None, ["User"])
    assert decisions["edit_name"] is None
    assert decisions["edit_downloads"] == "group_downloads_not_enabled"
    assert decisions["edit_retention"] == "group_retention_disabled"


def test_retention_needs_group_workspaces_and_the_group_retention_switch(env):
    enabled = env.modules.policy.group_retention_enabled
    assert enabled({"enable_group_workspaces": True, "enable_retention_policy_group": True})
    assert not enabled({"enable_group_workspaces": False, "enable_retention_policy_group": True})
    assert not enabled({"enable_group_workspaces": True})
    assert not enabled(None)


@pytest.mark.parametrize("caller", CALLERS)
def test_settings_management_lists_every_operation_once(env, caller):
    prepare(env, caller)
    management = env.modules.policy.build_group_settings_management(
        CALLERS[caller], env.stored_group(GROUP), env.get_settings(), ["User"],
    )
    operations = env.modules.policy.GROUP_SETTINGS_OPERATIONS
    assert management["schema_version"] == 1
    assert management["operations"] == [operation for operation in operations if operation in management["operations"]]
    assert set(management["operations"]).isdisjoint(management["reasons"])
    assert set(management["operations"]) | set(management["reasons"]) == set(operations)
    assert management["operations"] == env.modules.policy.group_settings_operations(
        CALLERS[caller], env.stored_group(GROUP), env.get_settings(), ["User"],
    )


@pytest.mark.parametrize("caller,session,narrowing,status", [
    ("owner-1", "user", False, "active"),
    ("owner-1", "user", True, "active"),
    ("owner-1", "creator", True, "locked"),
    ("admin-1", "user", False, "inactive"),
])
def test_the_settings_read_publishes_the_decision(env, caller, session, narrowing, status):
    prepare(env, caller, session, narrowing=narrowing, status=status, enable_retention_policy_group=False)
    published = env.settings_read(GROUP).get_json()["settings"]["settings_management"]
    assert published == env.modules.policy.build_group_settings_management(
        CALLERS[caller], env.stored_group(GROUP), env.get_settings(), SESSION_ROLES[session],
    )


def _function(file_name, name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _called(function, name):
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        for node in ast.walk(function)
    )


def test_every_native_write_and_read_is_gated_by_the_one_decision():
    for name in ("update_group_profile", "replace_group_logo", "remove_group_logo",
                 "update_group_downloads", "update_group_retention"):
        assert _called(_function("functions_group_settings.py", name), "require_operation"), name
    for name in ("read_group_activity", "read_group_stats", "read_group_file_count"):
        assert _called(_function("functions_group_insights.py", name), "require_operation"), name
    assert _called(_function("functions_group_settings.py", "require_operation"), "group_settings_decisions")
    assert _called(_function("functions_group_settings.py", "build_group_settings"), "build_group_settings_management")
    assert _called(_function("functions_workspace_context.py", "build_group_workspace_context"),
                   "build_group_settings_management")
