# test_public_settings_policy.py
"""
Functional test for the native public workspace settings decision and its seam with the classic routes.
Version: 0.261.181
Implemented in: 0.261.181

``public_settings_decisions`` is the one decision behind the native public workspace
settings and insights routes and their ``settings_management`` block. This test holds
it, and the native routes built on it, to the classic routes' real outcomes, run for
real in ``test_support/public_settings_harness.py``:

- the name, description and hero color against ``PATCH /api/public_workspaces/<ws_id>``,
  and the logo against ``POST /api/public_workspaces/<ws_id>/logo``: the owner only, in
  every caller role and workspace status;
- downloads against ``PATCH /api/public_workspaces/<ws_id>/download-settings``: the owner
  or an admin, with the administrator's download capability;
- retention against ``POST /api/retention-policy/public/<ws_id>``: the owner or an admin;
- the activity and statistics reads against ``/activity`` and ``/stats``: the owner or an
  admin, and any stored role, respectively, with the native ``/insights/activity`` and
  ``/insights/stats``;
- the document count against ``/fileCount``, which answers every signed-in caller: the
  native ``/insights/file-count`` backs the owner's danger zone and is the owner's alone,
  pinned as the one read narrower than classic.

Admins and document managers are stored as bare ids or as ``{userId, ...}`` entries, and
every cell runs with both. In every cell the decision allows exactly what the classic
route allows, apart from the rules stricter than the classic routes, each pinned as the
only difference: profile and logo writes while the workspace is ``locked``, ``inactive``
or in a status this version doesn't recognize, and retention while public retention
policies are off. An allowed operation succeeds on the native route, and a refused one
is a 403 carrying the decision's reason.
"""

import ast
import itertools
from io import BytesIO
from pathlib import Path

import pytest

from test_support.public_settings_harness import png_bytes, public_settings_environment


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
WORKSPACE = "5b6d0c5e-4f3a-4b8e-9d2c-1a7e3f9b2c41"
# Assignment lists hold canonical workspace GUIDs, so the workspace under test has one.
OTHER_WORKSPACE = "d3b07384-d9a7-4f3b-8c2e-6f1a2b3c4d5e"
CALLERS = {
    "owner-1": "Owner",
    "admin-1": "Admin",
    "manager-1": "DocumentManager",
    "reader-1": "User",
}
# Admins and document managers as bare ids, and as the {userId, email, displayName}
# entries role changes store.
MEMBER_FORMATS = {
    "strings": {"admins": ("admin-1",), "managers": ("manager-1",)},
    "dicts": {"admins": (("admin-1", "dict"),), "managers": (("manager-1", "dict"),)},
}
STATUSES = ("active", "upload_disabled", "locked", "inactive", "archived")
READ_ONLY_STATUSES = ("locked", "inactive", "archived")


@pytest.fixture(scope="module")
def module_env():
    with public_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def prepare(env, caller, members="strings", *, status="active", **settings):
    env.reset()
    env.settings.update(settings)
    env.seed_workspace(WORKSPACE, status=status, **MEMBER_FORMATS[members])
    env.as_user(caller)


def decision(env, caller, operation):
    return env.modules.policy.public_settings_decisions(
        CALLERS[caller], env.stored_workspace(WORKSPACE), env.get_settings(),
    )[operation]


def allowed(response):
    return 200 <= response.status_code < 300


def assert_seam(classic_allows, reason, *, native_only=()):
    """The decision allows what the classic route allows, except the pinned native-only refusals."""
    if classic_allows and reason in native_only:
        return
    assert (reason is None) == classic_allows, (classic_allows, reason)


def assert_native_follows(env, response, reason):
    """The native route does exactly what the decision says."""
    body = response.get_json()
    if reason is None:
        assert allowed(response), body
    else:
        refusal = env.modules.settings.refusal(reason, env.stored_workspace(WORKSPACE))
        assert response.status_code == 403, body
        assert body == {"error": refusal.description, "error_code": reason}
    assert response.headers["Cache-Control"] == "no-store"


def logo_upload():
    return {"logo_file": (BytesIO(png_bytes()), "logo.png")}


# ---------------------------------------------------------------------------
# The profile and the logo
# ---------------------------------------------------------------------------

PROFILE_CELLS = list(itertools.product(CALLERS, MEMBER_FORMATS, STATUSES))


@pytest.mark.parametrize("caller,members,status", PROFILE_CELLS)
def test_profile_writes_follow_the_classic_update_route(env, caller, members, status):
    prepare(env, caller, members, status=status)
    classic = env.call("PATCH", f"/api/public_workspaces/{WORKSPACE}",
                       {"name": "Classic name", "description": "d", "heroColor": "#112233"}, legacy=True)

    prepare(env, caller, members, status=status)
    reasons = {operation: decision(env, caller, operation)
               for operation in ("edit_name", "edit_description", "edit_color")}
    assert len(set(reasons.values())) == 1, reasons
    native = env.call("PATCH", f"/api/public-workspaces/{WORKSPACE}/settings/profile", {
        "revision": env.revision("profile", WORKSPACE), "name": "Native name", "description": "d",
        "hero_color": "#112233",
    })

    assert_seam(allowed(classic), reasons["edit_name"], native_only=("public_workspace_status_unavailable",))
    if status in READ_ONLY_STATUSES and allowed(classic):
        assert reasons["edit_name"] == "public_workspace_status_unavailable"
    assert_native_follows(env, native, reasons["edit_name"])


@pytest.mark.parametrize("caller,members,status", PROFILE_CELLS)
def test_logo_writes_follow_the_classic_upload_route(env, caller, members, status):
    prepare(env, caller, members, status=status)
    classic = env.call("POST", f"/api/public_workspaces/{WORKSPACE}/logo", data=logo_upload(), legacy=True)

    prepare(env, caller, members, status=status)
    reason = decision(env, caller, "edit_logo")
    native = env.call("PUT", f"/api/public-workspaces/{WORKSPACE}/settings/logo",
                      data={**logo_upload(), "revision": env.revision("logo", WORKSPACE)})

    assert_seam(allowed(classic), reason, native_only=("public_workspace_status_unavailable",))
    if status in READ_ONLY_STATUSES and allowed(classic):
        assert reason == "public_workspace_status_unavailable"
    assert_native_follows(env, native, reason)


def test_no_creation_role_applies_to_the_profile_or_the_logo(env):
    """The classic update and logo routes carry no creation-role rule, so narrowing
    public workspace creation to a role changes neither decision."""
    prepare(env, "owner-1", require_member_of_create_public_workspace=True)
    assert decision(env, "owner-1", "edit_name") is None
    assert decision(env, "owner-1", "edit_logo") is None
    classic = env.call("PATCH", f"/api/public_workspaces/{WORKSPACE}", {"name": "Still allowed"}, legacy=True)
    assert classic.status_code == 200


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

CAPABILITIES = {
    "on": {"allow_public_workspace_file_downloads": True},
    "off": {"allow_public_workspace_file_downloads": False},
    "assigned": {"allow_public_workspace_file_downloads": True,
                 "require_public_workspace_assignment_for_file_downloads": True,
                 "file_download_allowed_public_workspace_ids": [WORKSPACE]},
    "unassigned": {"allow_public_workspace_file_downloads": True,
                   "require_public_workspace_assignment_for_file_downloads": True,
                   "file_download_allowed_public_workspace_ids": [OTHER_WORKSPACE]},
}
DOWNLOAD_CELLS = list(itertools.product(CALLERS, MEMBER_FORMATS, CAPABILITIES, ("active", "locked", "inactive")))


@pytest.mark.parametrize("caller,members,capability,status", DOWNLOAD_CELLS)
def test_download_writes_follow_the_classic_download_settings_route(env, caller, members, capability, status):
    prepare(env, caller, members, status=status, **CAPABILITIES[capability])
    classic = env.call("PATCH", f"/api/public_workspaces/{WORKSPACE}/download-settings",
                       {"disable_file_downloads": True}, legacy=True)

    prepare(env, caller, members, status=status, **CAPABILITIES[capability])
    reason = decision(env, caller, "edit_downloads")
    native = env.call("PATCH", f"/api/public-workspaces/{WORKSPACE}/settings/downloads", {
        "revision": env.revision("downloads", WORKSPACE), "disable_file_downloads": True,
    })

    assert_seam(allowed(classic), reason)
    if caller in ("owner-1", "admin-1"):
        # Each capability cell means what it says: an assigned GUID is allowed, and an
        # assignment elsewhere is refused for the capability, not for a bad id.
        assert (reason is None) == (capability in ("on", "assigned")), (capability, reason)
    assert_native_follows(env, native, reason)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

RETENTION_CELLS = list(itertools.product(CALLERS, MEMBER_FORMATS, (True, False), ("active", "locked", "inactive")))


@pytest.mark.parametrize("caller,members,retention_on,status", RETENTION_CELLS)
def test_retention_writes_follow_the_classic_retention_route(env, caller, members, retention_on, status):
    prepare(env, caller, members, status=status, enable_retention_policy_public=retention_on)
    classic = env.call("POST", f"/api/retention-policy/public/{WORKSPACE}", {
        "conversation_retention_days": 30, "document_retention_days": 30,
    }, legacy=True)

    prepare(env, caller, members, status=status, enable_retention_policy_public=retention_on)
    reason = decision(env, caller, "edit_retention")
    native = env.call("PATCH", f"/api/public-workspaces/{WORKSPACE}/settings/retention", {
        "revision": env.revision("retention", WORKSPACE), "conversation_retention_days": 30,
    })

    # The classic route checks no switch, so while public retention policies are off it
    # still accepts the owner and admins, which the native route refuses.
    assert_seam(allowed(classic), reason, native_only=("public_workspace_retention_disabled",))
    if not retention_on and caller in ("owner-1", "admin-1"):
        assert allowed(classic)
        assert reason == "public_workspace_retention_disabled"
    assert_native_follows(env, native, reason)


@pytest.mark.parametrize("caller", ["owner-1", "admin-1"])
def test_retention_needs_public_workspaces_on_where_the_classic_route_does_not(env, caller):
    prepare(env, caller, enable_public_workspaces=False)
    classic = env.call("POST", f"/api/retention-policy/public/{WORKSPACE}", {"conversation_retention_days": 30},
                       legacy=True)
    assert classic.status_code == 200
    assert decision(env, caller, "edit_retention") == "public_workspace_retention_disabled"
    native = env.call("PATCH", f"/api/public-workspaces/{WORKSPACE}/settings/retention", {
        "revision": env.revision("retention", WORKSPACE), "conversation_retention_days": 30,
    })
    assert native.status_code == 400
    assert native.get_json() == {"error": "Enable Public Workspaces is disabled."}


# ---------------------------------------------------------------------------
# The reads
# ---------------------------------------------------------------------------

READS = {
    "view_activity": ("/activity", "/insights/activity"),
    "view_stats": ("/stats", "/insights/stats"),
    "view_file_count": ("/fileCount", "/insights/file-count"),
}
READ_CELLS = list(itertools.product(CALLERS, MEMBER_FORMATS, READS, ("active", "locked", "inactive", "archived")))


@pytest.mark.parametrize("caller,members,operation,status", READ_CELLS)
def test_insight_reads_follow_the_classic_reads(env, caller, members, operation, status):
    classic_path, native_path = READS[operation]
    prepare(env, caller, members, status=status)
    reason = decision(env, caller, operation)
    classic = env.call("GET", f"/api/public_workspaces/{WORKSPACE}{classic_path}", legacy=True)
    native = env.call("GET", f"/api/public-workspaces/{WORKSPACE}{native_path}")

    if operation == "view_file_count":
        # The classic count answers every signed-in caller. The native count backs the
        # owner's danger zone, so it is the owner's alone: the one read narrower than classic.
        assert allowed(classic)
        assert reason == (None if caller == "owner-1" else "public_workspace_owner_required")
    else:
        assert_seam(allowed(classic), reason)
    assert_native_follows(env, native, reason)


@pytest.mark.parametrize("caller,members", list(itertools.product(CALLERS, MEMBER_FORMATS)))
def test_the_settings_read_needs_an_owner_or_admin_as_the_classic_settings_tab_does(env, caller, members):
    prepare(env, caller, members)
    response = env.settings_read(WORKSPACE)
    if caller in ("owner-1", "admin-1"):
        assert response.status_code == 200
        assert response.get_json()["settings"]["viewer_role"] == CALLERS[caller]
    else:
        assert response.status_code == 403
        assert response.get_json()["error_code"] == "public_workspace_manager_required"


@pytest.mark.parametrize("caller,status,retention_on", [
    ("owner-1", "active", True),
    ("owner-1", "locked", False),
    ("owner-1", "archived", True),
    ("admin-1", "inactive", True),
])
def test_the_settings_read_publishes_the_decision(env, caller, status, retention_on):
    prepare(env, caller, status=status, enable_retention_policy_public=retention_on)
    published = env.settings_read(WORKSPACE).get_json()["settings"]["settings_management"]
    assert published == env.modules.policy.build_public_settings_management(
        CALLERS[caller], env.stored_workspace(WORKSPACE), env.get_settings(),
    )


# ---------------------------------------------------------------------------
# The decision itself
# ---------------------------------------------------------------------------

def test_the_role_is_reported_before_the_status(env):
    policy = env.modules.policy
    locked = {"id": WORKSPACE, "status": "locked"}
    assert policy.public_settings_decisions("Admin", locked, {})["edit_name"] == "public_workspace_owner_required"
    assert policy.public_settings_decisions("Owner", locked, {})["edit_name"] == "public_workspace_status_unavailable"
    assert policy.public_settings_decisions("Admin", locked, {})["edit_logo"] == "public_workspace_owner_required"
    assert policy.public_settings_decisions("Owner", locked, {})["edit_logo"] == "public_workspace_status_unavailable"


@pytest.mark.parametrize("workspace", [
    {"id": WORKSPACE}, {"id": WORKSPACE, "status": "active"}, {"id": WORKSPACE, "status": "upload_disabled"},
], ids=["missing", "active", "upload_disabled"])
def test_only_active_and_upload_disabled_workspaces_can_change_the_profile(env, workspace):
    decisions = env.modules.policy.public_settings_decisions("Owner", workspace, {})
    for operation in ("edit_name", "edit_description", "edit_color", "edit_logo"):
        assert decisions[operation] is None, operation


@pytest.mark.parametrize("status", ["locked", "inactive", None, "", "archived", "unknown-status"])
def test_every_other_status_keeps_the_profile_and_logo_read_only(env, status):
    """Locked and inactive, as the classic page shows them; a status this version doesn't
    recognize fails closed, as the public workspace context does. The reads keep working,
    and only the status-restricted operations change."""
    decisions = env.modules.policy.public_settings_decisions("Owner", {"id": WORKSPACE, "status": status}, {})
    for operation in ("edit_name", "edit_description", "edit_color", "edit_logo"):
        assert decisions[operation] == "public_workspace_status_unavailable", operation
    assert decisions["view_activity"] is None and decisions["view_stats"] is None
    assert decisions["view_file_count"] is None


@pytest.mark.parametrize("role,expected", [
    ("Owner", {"view_activity": None, "view_stats": None, "view_file_count": None}),
    ("Admin", {"view_activity": None, "view_stats": None, "view_file_count": "public_workspace_owner_required"}),
    ("DocumentManager", {"view_activity": "public_workspace_manager_required", "view_stats": None,
                         "view_file_count": "public_workspace_owner_required"}),
    ("User", {"view_activity": "public_workspace_manager_required", "view_stats": "public_workspace_member_required",
              "view_file_count": "public_workspace_owner_required"}),
    (None, {"view_activity": "public_workspace_manager_required", "view_stats": "public_workspace_member_required",
            "view_file_count": "public_workspace_owner_required"}),
])
def test_the_reads_follow_the_classic_roles(env, role, expected):
    decisions = env.modules.policy.public_settings_decisions(role, {"id": WORKSPACE, "status": "inactive"}, {})
    assert {operation: decisions[operation] for operation in expected} == expected


def test_settings_that_are_not_a_dict_turn_off_every_gated_operation(env):
    decisions = env.modules.policy.public_settings_decisions("Owner", {"id": WORKSPACE}, None)
    assert decisions["edit_name"] is None
    assert decisions["edit_downloads"] == "public_workspace_downloads_not_enabled"
    assert decisions["edit_retention"] == "public_workspace_retention_disabled"


def test_a_workspace_that_is_not_a_dict_is_an_active_workspace_without_an_id(env):
    decisions = env.modules.policy.public_settings_decisions(
        "Owner", None, {"allow_public_workspace_file_downloads": True},
    )
    assert decisions["edit_name"] is None
    # The download capability needs a workspace id, which a missing workspace lacks.
    assert decisions["edit_downloads"] == "public_workspace_downloads_not_enabled"


def test_retention_needs_public_workspaces_and_the_public_retention_switch(env):
    enabled = env.modules.policy.public_retention_enabled
    assert enabled({"enable_public_workspaces": True, "enable_retention_policy_public": True})
    assert not enabled({"enable_public_workspaces": False, "enable_retention_policy_public": True})
    assert not enabled({"enable_public_workspaces": True})
    assert not enabled({"enable_public_workspaces": True, "enable_retention_policy_group": True})
    assert not enabled(None)


@pytest.mark.parametrize("caller", CALLERS)
def test_settings_management_lists_every_operation_once(env, caller):
    prepare(env, caller)
    workspace, settings = env.stored_workspace(WORKSPACE), env.get_settings()
    management = env.modules.policy.build_public_settings_management(CALLERS[caller], workspace, settings)
    operations = env.modules.policy.PUBLIC_SETTINGS_OPERATIONS
    assert management["schema_version"] == 1
    assert management["operations"] == [operation for operation in operations if operation in management["operations"]]
    assert set(management["operations"]).isdisjoint(management["reasons"])
    assert set(management["operations"]) | set(management["reasons"]) == set(operations)
    assert management["operations"] == env.modules.policy.public_settings_operations(
        CALLERS[caller], workspace, settings,
    )


def test_every_reason_has_reviewed_refusal_text(env):
    reasons = {
        value for name, value in vars(env.modules.policy).items()
        if name.startswith("PUBLIC_") and name.endswith(("_REQUIRED", "_UNAVAILABLE", "_NOT_ENABLED", "_DISABLED"))
    }
    assert reasons == set(env.modules.settings.REFUSAL_MESSAGES)
    for message in env.modules.settings.REFUSAL_MESSAGES.values():
        assert message.endswith(".") and "{" not in message


def _function(file_name, name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _called(function, name):
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        for node in ast.walk(function)
    )


def test_every_native_write_and_read_is_gated_by_the_one_decision():
    for name in ("update_public_profile", "replace_public_logo", "remove_public_logo",
                 "update_public_downloads", "update_public_retention"):
        assert _called(_function("functions_public_settings.py", name), "require_operation"), name
    for name in ("read_public_activity", "read_public_stats", "read_public_file_count"):
        assert _called(_function("functions_public_insights.py", name), "require_operation"), name
    assert _called(_function("functions_public_settings.py", "require_operation"), "public_settings_decisions")
    assert _called(_function("functions_public_settings.py", "build_public_settings"),
                   "build_public_settings_management")
    assert _called(_function("functions_workspace_context.py", "build_public_workspace_context"),
                   "build_public_settings_management")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
