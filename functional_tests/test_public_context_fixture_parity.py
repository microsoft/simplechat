# test_public_context_fixture_parity.py
"""
Parity between the public workspace context the V2 browser fixtures serve and the real builder.
Version: 0.261.186
Implemented in: 0.261.168
settings_management, the public settings decision (M10C): 0.261.185
the Settings, Activity and Statistics manage sections and the settings switches (M10C R5): 0.261.185
Reader downloads: the M3A read fixture models a downloads-off workspace, so its seeded context is
held against the server's for that same per-workspace switch (a reader gets no download): 0.261.186

Every public browser suite builds its selected-workspace context from
`ui_tests/fixtures/public_workspace.py::public_context`, directly or through the per-suite fixtures
that recompute it: M3B's `set_policy` (document management) and M3C's `configure_workspace`
(generated-artifact review). A context the fixture invents -- a section the server never opens, a
permission it never grants, a reason it never sends -- lets a browser test pass while proving nothing
about production. This test runs the real context route and `build_public_workspace_context`
(`functions_workspace_context.py`) against the fixture, and requires them to agree on every top-level
field and every section the real context reports, walking the union of both sides' keys so a
section or hint only one side has fails. That covers every field the V2 client reads:

- `role`, `status`, `can_manage_workspace` and the envelope (`schema_version`, `enabled`);
- every section: `enabled`, `can_manage`, `reason` and `group`, including the Settings, Activity and
  Statistics sections M10C adds to the "manage" group beside Members;
- `document_permissions` and `document_queries`;
- the hints: `document_management`, `document_collaboration`, `prompt_management`,
  `identity_management`, `file_source_management`, `membership_management` and, since M10C,
  `settings_management`, the public settings decision the native settings and insights routes
  enforce.

The workspace metadata (`workspace`, `scope` and `viewer_id`) may differ in value but not in keys.

It covers every role, every status and one the server does not recognize, for the deployment the
fixture models (`MODELLED_SETTINGS`): public workspaces on, metadata extraction on, and the
administrator's public downloads allowed. The settings switches the M10C settings suite passes
(the administrator's downloads, public retention and the workspace's own downloads) are walked the
same way. It runs in the harness `test_v2_group_workspace_context.py`
uses for the group builder (the real context module with its service seams stubbed and no network),
with the real public role, status and download functions in place of that harness's public stubs.
A missing workspace is refused with the server's own status and text. The fixture's denied
workspace answers with the builder's refusal branch, which today's role rules never reach, since
every authenticated caller reads a public workspace as at least a User; it stays as a robustness
scenario for the client, and this test holds it to the builder's text.

M9A resolves the read-only M3A leftover the M9B verification pinned as a strict xfail: the builder
now opens the documents section with `section(True, manager)`, so a manager of an active workspace
manages it, matching the group builder, and the registry drops the sections public workspaces will
never have (agents, actions, endpoints and workflows). M9C opens the prompts section the same way
and publishes a `prompt_management` hint from `public_prompt_management_operations`. The fixture
serves the server's value, and this test walks the union of both sides' keys, so a section or hint
only one side lists fails.

M10B opens the identities and sync sections and publishes `identity_management` and
`file_source_management` hints from their operations. File Sync for the workspace is the sole gate:
with it off both sections stay closed and their hints empty; with it on a manager of an active
workspace manages them. The parity run is parametrized over File Sync off and on, so both
deployments are held to the fixture, and the reason-constants test pins the "requires File Sync" and
manager-only texts the sections send.
"""

import ast
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_support.agent_delegation import APP_ROOT, execute_functions  # noqa: E402
from test_v2_group_workspace_context import environment  # noqa: E402,F401 - the real builder's harness
from ui_tests.fixtures import public_workspace as fixture_module  # noqa: E402
from ui_tests.fixtures.public_document_collaboration import PublicDocumentCollaborationFixture  # noqa: E402
from ui_tests.fixtures.public_document_management import PublicDocumentManagementFixture  # noqa: E402
from ui_tests.fixtures.public_documents import PublicDocumentsFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402


ROLE_USERS = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "reader"}
KNOWN_STATUSES = ("active", "locked", "upload_disabled", "inactive")
# "archived" is stored on no real workspace. The server reports any unrecognized value as "unknown",
# and so does the fixture.
STATUSES = (*KNOWN_STATUSES, "archived")

# The deployment `public_context` models.
MODELLED_SETTINGS = {
    "enable_public_workspaces": True,
    "enable_extract_meta_data": True,
    "allow_public_workspace_file_downloads": True,
}

METADATA_FIELDS = frozenset({"viewer_id", "scope", "workspace"})
# The fields the V2 client reads. The comparison is not limited to them; the envelope test only checks
# the server still sends each one, so none can drop out of the comparison unnoticed. The public
# Settings, Activity and Statistics sections (M10C) take their controls from settings_management.
CLIENT_READ_FIELDS = (
    "schema_version", "enabled", "role", "status", "can_manage_workspace", "sections",
    "document_permissions", "document_queries", "document_management", "document_collaboration",
    "prompt_management", "identity_management", "file_source_management",
    "membership_management",
    "settings_management",
)
WORKSPACE_ID = "pub-a"
WORKSPACE_NAME = "Research library"


@pytest.fixture
def public(environment, monkeypatch):  # noqa: F811 - the imported harness fixture
    env = environment
    env.settings.update(MODELLED_SETTINGS)
    env.public_records = {
        WORKSPACE_ID: {
            "id": WORKSPACE_ID, "name": WORKSPACE_NAME, "description": "Published knowledge",
            "owner": {"userId": "owner", "displayName": "Owner", "email": "owner@example.test"},
            "admins": ["admin"], "documentManagers": ["manager"], "status": "active",
            "heroColor": "#123456",
        },
    }
    # The group harness stubs the public lookups the context module imports. Put the real role,
    # status and download functions in their place, reading these records. The download assignment
    # list is parsed by the real File Sync normalizer, as in the application.
    namespace = {"json": json}
    execute_functions("functions_public_workspaces.py", {
        "get_user_role_in_public_workspace", "check_public_workspace_status_allows_operation",
    }, namespace)
    execute_functions("functions_settings.py", {
        "is_public_workspace_file_download_enabled", "is_public_workspace_file_download_admin_enabled",
        "_get_workspace_policy_target_id", "normalize_file_download_allowed_public_workspace_ids",
        "normalize_file_sync_allowed_public_workspace_ids",
    }, namespace)
    for name in (
        "get_user_role_in_public_workspace", "check_public_workspace_status_allows_operation",
        "is_public_workspace_file_download_enabled",
    ):
        monkeypatch.setattr(env.helper, name, namespace[name])
    monkeypatch.setattr(env.helper, "find_public_workspace_by_id", Mock(
        side_effect=lambda workspace_id: deepcopy(env.public_records.get(workspace_id)),
    ))
    # File Sync is the sole gate on the identities and sync sections and their management hints
    # (M10B). The group harness stubs it out; drive it from a flag `real_context` toggles, so the
    # identities-and-sync-off and -on deployments are both held to the fixture.
    env.file_sync_on = False
    monkeypatch.setattr(
        env.helper, "is_file_sync_enabled_for_public_workspace",
        lambda settings, workspace_id, **kwargs: bool(env.file_sync_on),
    )

    # The real public route body, with the harness's authentication and settings decorators.
    route_namespace = {
        **env.namespace, "bp": Blueprint("backend_v2_public", __name__),
        "build_public_workspace_context": env.helper.build_public_workspace_context,
    }
    tree = ast.parse((APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8"))
    route = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "v2_public_workspace_context"
    )
    exec(compile(ast.Module(body=[route], type_ignores=[]), "route_backend_v2.py", "exec"), route_namespace)
    app = Flask("public_context_parity")
    app.config.update(TESTING=True, SECRET_KEY="fixture-only-session-signing")
    app.register_blueprint(route_namespace["bp"])
    env.public_client = app.test_client()
    return env


def read_as(env, user_id, workspace_id=WORKSPACE_ID):
    with env.public_client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": ["User"]}
    return env.public_client.get(f"/api/v2/workspaces/public/{workspace_id}")


def real_context(env, role, status, file_sync=False):
    env.public_records[WORKSPACE_ID]["status"] = status
    env.file_sync_on = file_sync
    response = read_as(env, ROLE_USERS[role])
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"
    return response.get_json()


def fixture_context(role, status, file_sync=False):
    return fixture_module.public_context(
        WORKSPACE_ID, WORKSPACE_NAME, role=role, status=status, viewer=ROLE_USERS[role], file_sync=file_sync,
    )


def _walk(path, server, served, found):
    if isinstance(server, dict) and isinstance(served, dict):
        for key in sorted(set(server) | set(served)):
            _walk(f"{path}.{key}", server.get(key, "<absent>"), served.get(key, "<absent>"), found)
    elif server != served:
        found.append((path, server, served))


def differences(real, fixture):
    """Every value the fixture serves differently, as a dotted path, walking the union of both sides'
    keys at every level: a field or section only one side has is a difference too."""
    found = []
    for field in sorted((set(real) | set(fixture)) - METADATA_FIELDS):
        _walk(field, real.get(field, "<absent>"), fixture.get(field, "<absent>"), found)
    return found


def describe(found):
    return "\n".join(f"{field}:\n  server:  {server!r}\n  fixture: {served!r}" for field, server, served in found)


# --------------------------------------------------------------------------
# public_context against the builder, for every role and status.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("file_sync", [False, True], ids=["file-sync-off", "file-sync-on"])
@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_the_fixture_context_is_the_server_context(public, role, status, file_sync):
    found = differences(
        real_context(public, role, status, file_sync), fixture_context(role, status, file_sync),
    )
    assert not found, describe(found)


@pytest.mark.parametrize("status", STATUSES)
def test_the_envelope_and_workspace_keys_match(public, status):
    real = real_context(public, "Owner", status)
    fixture = fixture_context("Owner", status)
    assert set(fixture) == set(real), (
        f"only on the server: {sorted(set(real) - set(fixture))}; only in the fixture: {sorted(set(fixture) - set(real))}"
    )
    assert set(CLIENT_READ_FIELDS) <= set(real) - METADATA_FIELDS
    assert fixture["workspace"].keys() == real["workspace"].keys()
    assert fixture["workspace"]["owner"].keys() == real["workspace"]["owner"].keys()
    assert fixture["scope"].keys() == real["scope"].keys()
    assert (fixture["scope"]["kind"], real["scope"]["kind"]) == ("public", "public")
    assert fixture["viewer_id"] == real["viewer_id"] == "owner"


def test_the_reason_constants_are_the_servers_texts(public):
    """The browser suites and the shell show these reasons, so each must be what the server sends."""
    assert real_context(public, "User", "active")["sections"]["tags"]["reason"] == (
        fixture_module.PUBLIC_SECTION_UNAVAILABLE_REASON
    )
    assert real_context(public, "Owner", "inactive")["sections"]["documents"]["reason"] == (
        fixture_module.PUBLIC_INACTIVE_REASON
    )
    assert real_context(public, "Owner", "archived")["sections"]["documents"]["reason"] == (
        fixture_module.PUBLIC_STATUS_UNKNOWN_REASON
    )
    # M10B: File Sync gates the identities and sync sections. A manager of an active workspace with
    # File Sync off sees the "requires File Sync" text; a reader sees the manager-only text.
    manager_off = real_context(public, "Owner", "active", file_sync=False)
    assert manager_off["sections"]["identities"]["reason"] == fixture_module.PUBLIC_IDENTITIES_UNAVAILABLE_REASON
    assert manager_off["sections"]["sync"]["reason"] == fixture_module.PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON
    reader = real_context(public, "User", "active", file_sync=True)
    assert reader["sections"]["identities"]["reason"] == fixture_module.PUBLIC_CONNECTIONS_MANAGER_REASON
    assert reader["sections"]["sync"]["reason"] == fixture_module.PUBLIC_CONNECTIONS_MANAGER_REASON


def test_an_unrecognized_status_is_reported_as_unknown_by_both():
    assert fixture_context("Owner", "archived") == fixture_context("Owner", "unknown")
    assert fixture_context("Owner", "archived")["status"] == "unknown"


# The membership hint and Members section the native context adds (M10A). These are the exact
# operations functions_public_membership_policy.public_membership_operations grants, pinned against
# the real builder so the fixture, the server and the policy cannot drift apart. A reader gets no
# operations; adds and role changes need a status that takes members; the owner alone transfers.
MEMBERSHIP_HINT = {
    ("Owner", "active"): ["add_member", "review_requests", "change_role", "remove_member", "transfer_ownership"],
    ("Admin", "active"): ["add_member", "review_requests", "change_role", "remove_member"],
    ("Admin", "upload_disabled"): ["add_member", "review_requests", "change_role", "remove_member"],
    ("Admin", "locked"): ["review_requests", "remove_member"],
    ("Owner", "inactive"): ["review_requests", "remove_member", "transfer_ownership"],
    ("DocumentManager", "active"): [],
    ("User", "active"): [],
}


@pytest.mark.parametrize("role,status", list(MEMBERSHIP_HINT))
def test_the_membership_hint_is_the_policy(public, role, status):
    real = real_context(public, role, status)
    assert real["membership_management"] == {"schema_version": 1, "operations": MEMBERSHIP_HINT[(role, status)]}
    assert real["membership_management"] == fixture_context(role, status)["membership_management"]


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_the_members_section_opens_in_every_viewable_status(public, role, status):
    """Members is a manage-group section every member may open when the workspace is viewable; its
    can_manage is navigation only, set for a manager of an active workspace, like the server's."""
    members = real_context(public, role, status)["sections"]["members"]
    viewable = status in ("active", "locked", "upload_disabled")
    assert members["group"] == "manage"
    assert members["enabled"] is viewable
    assert members["can_manage"] is bool(viewable and status == "active" and role in ("Owner", "Admin"))
    assert members == fixture_context(role, status)["sections"]["members"]


def test_the_fixture_context_is_a_fresh_copy_each_time():
    """Tests edit the contexts they are served, so no two calls may share state."""
    first = fixture_context("Owner", "active")
    second = fixture_context("Owner", "active")
    first["sections"]["documents"]["enabled"] = False
    first["document_management"]["operations"].clear()
    first["document_collaboration"]["operations"].clear()
    first["settings_management"]["operations"].clear()
    first["settings_management"]["reasons"]["edit_name"] = "changed"
    first["document_permissions"]["can_view"] = False
    assert second == fixture_context("Owner", "active")


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_the_settings_hint_is_the_public_settings_decision(public, role, status):
    """settings_management is build_public_settings_management for the caller's role, the stored
    workspace and the current settings, and the fixture serves the same hint."""
    real = real_context(public, role, status)
    expected = public.helper.build_public_settings_management(
        role, deepcopy(public.public_records[WORKSPACE_ID]), deepcopy(public.settings),
    )
    assert real["settings_management"] == expected
    assert fixture_context(role, status)["settings_management"] == expected


@pytest.mark.parametrize("changes,operation,reason", [
    ({"enable_retention_policy_public": True}, "edit_retention", None),
    ({"allow_public_workspace_file_downloads": False}, "edit_downloads", "public_workspace_downloads_not_enabled"),
    ({"require_public_workspace_assignment_for_file_downloads": True,
      "file_download_allowed_public_workspace_ids": ["pub-other"]}, "edit_downloads",
     "public_workspace_downloads_not_enabled"),
    ({"require_public_workspace_assignment_for_file_downloads": True,
      "file_download_allowed_public_workspace_ids": [WORKSPACE_ID]}, "edit_downloads", None),
])
def test_the_settings_hint_follows_the_deployment_switches(public, changes, operation, reason):
    """Outside the modelled deployment the hint still is the decision: retention opens with the public
    retention switch, and downloads follow the administrator's capability for this workspace."""
    public.settings.update(changes)
    management = real_context(public, "Owner", "active")["settings_management"]
    assert (operation in management["operations"]) is (reason is None)
    assert management["reasons"].get(operation) == reason


# The Settings, Activity and Statistics sections the native context adds beside Members (M10C R5).
# Each opens by the public settings decision -- Settings and Activity to the owner or an admin,
# Statistics to any stored role -- in every status that lets the caller view the workspace. Only
# Settings carries can_manage, for a manager of an active workspace; it is navigation only.
MANAGE_SECTION_RULES = {
    # section: (roles it opens to, whether a manager of an active workspace manages it, closed reason)
    "settings": (("Owner", "Admin"), True, "public_workspace_manager_required"),
    "activity": (("Owner", "Admin"), False, "public_workspace_manager_required"),
    "statistics": (("Owner", "Admin", "DocumentManager"), False, "public_workspace_member_required"),
}


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_the_settings_activity_and_statistics_sections_follow_the_decision(public, role, status):
    real = real_context(public, role, status)
    served = fixture_context(role, status)
    messages = public.helper.PUBLIC_SETTINGS_REFUSAL_MESSAGES
    viewable = status in ("active", "locked", "upload_disabled")
    status_reason = (
        None if viewable
        else fixture_module.PUBLIC_INACTIVE_REASON if status == "inactive"
        else fixture_module.PUBLIC_STATUS_UNKNOWN_REASON
    )
    for section_id, (roles, manages, reason) in MANAGE_SECTION_RULES.items():
        enabled = viewable and role in roles
        expected = {
            "group": "manage", "enabled": enabled,
            "can_manage": bool(enabled and status == "active" and manages),
            "reason": None if enabled else status_reason or messages[reason],
        }
        assert real["sections"][section_id] == expected, section_id
        assert served["sections"][section_id] == expected, section_id


def test_the_manage_section_reasons_are_the_policys_texts(public):
    """A closed Settings, Activity or Statistics section shows the text its route refuses with."""
    messages = public.helper.PUBLIC_SETTINGS_REFUSAL_MESSAGES
    assert fixture_module.PUBLIC_SETTINGS_MANAGER_REASON == messages["public_workspace_manager_required"]
    assert fixture_module.PUBLIC_SETTINGS_MEMBER_REASON == messages["public_workspace_member_required"]
    sections = real_context(public, "User", "active")["sections"]
    assert sections["settings"]["reason"] == fixture_module.PUBLIC_SETTINGS_MANAGER_REASON
    assert sections["activity"]["reason"] == fixture_module.PUBLIC_SETTINGS_MANAGER_REASON
    assert sections["statistics"]["reason"] == fixture_module.PUBLIC_SETTINGS_MEMBER_REASON


# The deployments the settings suite serves besides the modelled one: the administrator's downloads
# off, public retention on, and the workspace's own downloads off, alone and together.
SWITCH_VARIANTS = [
    pytest.param({"allow_public_workspace_file_downloads": False}, {}, id="downloads-admin-off"),
    pytest.param({"enable_retention_policy_public": True}, {}, id="retention-on"),
    pytest.param({}, {"disable_file_downloads": True}, id="workspace-downloads-off"),
    pytest.param(
        {"allow_public_workspace_file_downloads": False, "enable_retention_policy_public": True},
        {"disable_file_downloads": True}, id="all-switched",
    ),
]


@pytest.mark.parametrize("settings_changes,workspace_changes", SWITCH_VARIANTS)
@pytest.mark.parametrize("status", KNOWN_STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_every_settings_switch_variant_is_the_servers(public, role, status, settings_changes, workspace_changes):
    """The switches the settings fixture passes to public_context change every field they change on the
    server -- the settings hint, the download permission and the download operation -- and nothing else."""
    public.settings.update(settings_changes)
    public.public_records[WORKSPACE_ID].update(workspace_changes)
    served = fixture_module.public_context(
        WORKSPACE_ID, WORKSPACE_NAME, role=role, status=status, viewer=ROLE_USERS[role],
        **settings_changes, **workspace_changes,
    )
    found = differences(real_context(public, role, status), served)
    assert not found, describe(found)


# --------------------------------------------------------------------------
# Every context a per-suite fixture seeds or recomputes.
# --------------------------------------------------------------------------

class _FakeContext:
    def route(self, *args, **kwargs):
        pass

    def on(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()
        self.url = "about:blank"

    def on(self, *args, **kwargs):
        pass


def built(fixture_class, *steps):
    fixture = fixture_class(_FakePage())
    for step in steps:
        step(fixture)
    return fixture


# Every seeded context, as the role it serves, in an active workspace. The M3A read fixture models a
# downloads-off public workspace (its reader sees no Download and its list reports downloads off), so
# the server side is fed the same per-workspace switch and must agree that a reader gets no download
# capability. The other suites model the deployment's default, downloads on.
SEEDED = [
    pytest.param(fixture_module.PublicWorkspaceFixture, "pub-a", "User", {}, id="shell-pub-a"),
    pytest.param(fixture_module.PublicWorkspaceFixture, "pub-b", "User", {}, id="shell-pub-b"),
    pytest.param(PublicDocumentsFixture, "pub-a", "User", {"disable_file_downloads": True}, id="documents-pub-a"),
    pytest.param(PublicDocumentsFixture, "pub-b", "User", {"disable_file_downloads": True}, id="documents-pub-b"),
    pytest.param(PublicDocumentManagementFixture, "pub-a", "DocumentManager", {}, id="management-pub-a"),
    pytest.param(PublicDocumentManagementFixture, "pub-b", "DocumentManager", {}, id="management-pub-b"),
    pytest.param(PublicDocumentCollaborationFixture, "pub-a", "DocumentManager", {}, id="collaboration-pub-a"),
    pytest.param(PublicDocumentCollaborationFixture, "pub-b", "DocumentManager", {}, id="collaboration-pub-b"),
]


@pytest.mark.parametrize("fixture_class,workspace_id,role,workspace_changes", SEEDED)
def test_every_seeded_per_suite_context_is_the_servers(public, fixture_class, workspace_id, role, workspace_changes):
    served = built(fixture_class).workspaces[workspace_id]
    public.public_records[WORKSPACE_ID].update(workspace_changes)
    found = differences(real_context(public, role, "active"), served)
    assert not found, describe(found)


SETTERS = {
    "set_policy": (
        PublicDocumentManagementFixture,
        lambda fixture, role, status: fixture.set_policy(WORKSPACE_ID, role=role, status=status),
    ),
    "configure_workspace": (
        PublicDocumentCollaborationFixture,
        lambda fixture, role, status: fixture.configure_workspace(WORKSPACE_ID, role=role, status=status),
    ),
}


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
@pytest.mark.parametrize("setter", list(SETTERS))
def test_every_per_suite_recomputation_is_the_servers(public, setter, role, status):
    fixture_class, apply = SETTERS[setter]
    served = built(fixture_class, lambda fixture: apply(fixture, role, status)).workspaces[WORKSPACE_ID]
    found = differences(real_context(public, role, status), served)
    assert not found, describe(found)


# --------------------------------------------------------------------------
# Refusals and the one access rule: a missing workspace, and who reads a public workspace.
# --------------------------------------------------------------------------

class _FakeRoute:
    def __init__(self, url):
        self.request = type("Request", (), {"url": url})()
        self.status = None
        self.payload = None

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def fixture_read(fixture, workspace_id):
    path = f"/api/v2/workspaces/public/{workspace_id}"
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, ApiRequest(method="GET", path=path, query={}, body=None))
    return route.status, route.payload


def test_a_missing_workspace_is_refused_with_the_servers_answer(public):
    response = read_as(public, "owner", workspace_id="pub-missing")
    fixture = built(fixture_module.PublicWorkspaceFixture)
    assert fixture_read(fixture, "pub-missing") == (response.status_code, response.get_json()) == (
        404, {"error": fixture_module.PUBLIC_CONTEXT_NOT_FOUND_ERROR},
    )


def test_any_authenticated_caller_reads_a_public_workspace_as_a_user(public):
    """No role rule refuses a public workspace today, so a stranger is served the reader's context."""
    stranger = read_as(public, "stranger")
    assert stranger.status_code == 200
    assert stranger.get_json()["role"] == "User"
    assert not differences(stranger.get_json(), fixture_context("User", "active"))


def test_the_denied_answer_is_the_builders_refusal(public, monkeypatch):
    """The fixture's denied workspace is the builder's refusal branch, reached here by a role the
    current rules never produce."""
    monkeypatch.setattr(public.helper, "get_user_role_in_public_workspace", lambda _workspace, _user_id: None)
    response = read_as(public, "reader")
    fixture = built(fixture_module.PublicWorkspaceFixture)
    fixture.denied_workspaces.add(WORKSPACE_ID)
    assert fixture_read(fixture, WORKSPACE_ID) == (response.status_code, response.get_json()) == (
        403, {"error": fixture_module.PUBLIC_CONTEXT_DENIED_ERROR},
    )


# --------------------------------------------------------------------------
# The M3A leftover, now resolved: an active workspace's manager manages the documents section.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", list(fixture_module.PUBLIC_MANAGER_ROLES))
def test_an_active_public_manager_can_manage_the_documents_section(public, role):
    real = real_context(public, role, "active")
    assert "upload" in real["document_management"]["operations"]
    assert real["sections"]["documents"]["can_manage"] is True


@pytest.mark.parametrize("role", list(fixture_module.PUBLIC_MANAGER_ROLES))
def test_an_active_public_manager_can_manage_the_prompts_section(public, role):
    real = real_context(public, role, "active")
    assert real["prompt_management"]["operations"] == ["create", "edit", "delete"]
    assert real["sections"]["prompts"]["enabled"] is True
    assert real["sections"]["prompts"]["can_manage"] is True


@pytest.mark.parametrize("status", ("locked", "upload_disabled"))
def test_a_reader_sees_the_prompts_section_open_without_management(public, status):
    real = real_context(public, "User", status)
    assert real["sections"]["prompts"]["enabled"] is True
    assert real["sections"]["prompts"]["can_manage"] is False
    assert real["prompt_management"]["operations"] == []


# --------------------------------------------------------------------------
# M10B: the identities and sync sections and their management hints, gated on File Sync.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", list(fixture_module.PUBLIC_MANAGER_ROLES))
def test_an_active_public_manager_manages_connections_when_file_sync_on(public, role):
    real = real_context(public, role, "active", file_sync=True)
    assert real["sections"]["identities"]["enabled"] is True
    assert real["sections"]["identities"]["can_manage"] is True
    assert real["sections"]["sync"]["enabled"] is True
    assert real["sections"]["sync"]["can_manage"] is True
    assert real["identity_management"]["operations"] == ["create", "edit", "delete"]
    assert real["file_source_management"]["operations"] == ["create", "edit", "delete", "sync", "test"]


@pytest.mark.parametrize("role", list(fixture_module.PUBLIC_MANAGER_ROLES))
def test_a_manager_has_no_connections_when_file_sync_off(public, role):
    real = real_context(public, role, "active", file_sync=False)
    assert real["sections"]["identities"]["enabled"] is False
    assert real["sections"]["sync"]["enabled"] is False
    assert real["identity_management"]["operations"] == []
    assert real["file_source_management"]["operations"] == []


@pytest.mark.parametrize("status", ("locked", "upload_disabled"))
def test_connections_are_read_only_off_an_active_workspace_even_with_file_sync(public, status):
    """A non-active status is read-only: the sections may not open and no write is advertised, even
    when File Sync is on."""
    real = real_context(public, "Owner", status, file_sync=True)
    assert real["sections"]["identities"]["can_manage"] is False
    assert real["sections"]["sync"]["can_manage"] is False
    assert real["identity_management"]["operations"] == []
    assert real["file_source_management"]["operations"] == []


def test_a_reader_never_manages_connections_even_with_file_sync(public):
    real = real_context(public, "User", "active", file_sync=True)
    assert real["sections"]["identities"]["enabled"] is False
    assert real["sections"]["sync"]["enabled"] is False
    assert real["identity_management"]["operations"] == []
    assert real["file_source_management"]["operations"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
