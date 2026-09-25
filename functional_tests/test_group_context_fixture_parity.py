# test_group_context_fixture_parity.py
"""
Parity between the group workspace context the V2 browser fixtures serve and the real builder.
Version: 0.261.174
Implemented in: 0.261.157
The screening_management hint: 0.261.173
The workflow_management hint: 0.261.174

Every group browser suite builds its selected-group context from
`ui_tests/fixtures/group_workspace.py::group_context`, directly or through a per-section fixture that
recomputes it. A context the fixture invents -- a reason the server never sends, a section it would
never open, a hint it would never grant or would always send -- lets a browser test pass while
proving nothing about production. This test runs the real context route and
`build_group_workspace_context` (`functions_workspace_context.py`), in the harness
`test_v2_group_workspace_context.py` uses, against the fixture, and requires them to agree on every
top-level field and every section the real context reports, walking the union of both sides' keys
so a section or hint only one side has fails. That covers every field the V2 client reads today:

- `role`, `status`, `can_manage_workspace` and the envelope (`schema_version`, `enabled`);
- every section, including `members`: `enabled`, `can_manage`, `reason` and `group`;
- `native_delegation`, `document_permissions` and `document_queries`;
- every hint: `document_management`, `document_collaboration`, `screening_management`,
  `prompt_management`, `action_management`, `agent_management`, `identity_management`,
  `endpoint_management`, `file_source_management`, `workflow_management` and `settings_management`.

The workspace metadata (`workspace`, `scope` and `viewer_id`) may differ in value but not in keys.

It covers every group role and every status, including one the server does not recognize, for the
deployment the fixture models (`MODELLED_SETTINGS`): every group capability on, File Sync on for the
group, governance allowing everything, the administrator's group downloads allowed, group retention
off and no CreateGroups role requirement. The fixture models no other settings, except the three
variants its per-section fixtures claim (`VARIANTS`): metadata extraction on (the document suites),
group plugins off (the actions suite) and group agents off (the agents suite). Those are compared
too, and so is every context a per-section fixture seeds or recomputes. A non-member and a missing
group are refused with the server's own status and text, and the reason constants the browser
suites assert are the server's texts.
"""

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_support.agent_delegation import execute_functions  # noqa: E402
from test_v2_group_workspace_context import environment as environment, read_as  # noqa: E402,F401 - the real builder's harness
from ui_tests.fixtures import group_workspace as fixture_module  # noqa: E402
from ui_tests.fixtures.group_actions import GroupActionsFixture  # noqa: E402
from ui_tests.fixtures.group_agents import GroupAgentsFixture  # noqa: E402
from ui_tests.fixtures.group_document_collaboration import GroupDocumentCollaborationFixture  # noqa: E402
from ui_tests.fixtures.group_document_management import GroupDocumentManagementFixture  # noqa: E402
from ui_tests.fixtures.group_documents import GroupDocumentsFixture  # noqa: E402
from ui_tests.fixtures.group_members import GroupMembersFixture  # noqa: E402
from ui_tests.fixtures.group_prompts import GroupPromptsFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402

_PYTEST_FIXTURES = (environment,)


ROLE_USERS = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "reader"}
KNOWN_STATUSES = ("active", "locked", "upload_disabled", "inactive")
# "archived" is stored on no real group. The server reports any unrecognized value as "unknown", and
# so does the fixture.
STATUSES = (*KNOWN_STATUSES, "archived")

# The deployment `group_context` models. The harness's own settings already switch every group
# capability on; the administrator's group downloads are the one addition.
MODELLED_SETTINGS = {
    "enable_group_workspaces": True,
    "enable_semantic_kernel": True,
    "per_user_semantic_kernel": True,
    "allow_group_agents": True,
    "allow_group_plugins": True,
    "allow_group_custom_endpoints": True,
    "enable_multi_model_endpoints": True,
    "allow_group_workflows": True,
    "allow_group_workspace_file_downloads": True,
}

# The only departures from MODELLED_SETTINGS a fixture claims. Each is a `group_context` keyword
# named for the server setting it models, so one dict configures both sides.
VARIANTS = {
    "modelled": {},
    "extraction-on": {"enable_extract_meta_data": True},
    "plugins-off": {"allow_group_plugins": False},
    "agents-off": {"allow_group_agents": False},
    "group-downloads-disabled": {"disable_file_downloads": True},
}
EXTRACTION_ON = VARIANTS["extraction-on"]

# The four settings capability switches `settings_management` reads. Each entry is the `group_context`
# switches, the real settings they stand for, and the session app roles the real read runs under --
# `holds_create_groups_role` is a session role on the server, not a setting, so it configures the roles
# rather than the settings dict. The switch test compares the WHOLE context under each switch (walking
# every field as the main 4x5 test does), not just `settings_management`: `allow_group_workspace_file_downloads`
# also moves `document_permissions.can_download` and the `download` operation in `document_management`, and
# the fixture models all three, so a browser test that turns downloads off never sees a Download the server
# would refuse.
SETTINGS_SWITCHES = {
    "downloads-off": (
        {"allow_group_workspace_file_downloads": False},
        {"allow_group_workspace_file_downloads": False},
        ("User",),
    ),
    "retention-on": (
        {"enable_retention_policy_group": True},
        {"enable_retention_policy_group": True},
        ("User",),
    ),
    "create-role-required-lacking": (
        {"require_member_of_create_group": True, "holds_create_groups_role": False},
        {"require_member_of_create_group": True},
        ("User",),
    ),
    "create-role-required-holding": (
        {"require_member_of_create_group": True, "holds_create_groups_role": True},
        {"require_member_of_create_group": True},
        ("User", "CreateGroups"),
    ),
}

# The workspace metadata may differ in value, but not in keys. Every other top-level field either side
# sends is compared value for value, and so is every section the real context reports, so a section,
# hint or field the builder gains is covered as soon as it exists.
METADATA_FIELDS = frozenset({"viewer_id", "scope", "workspace"})
# The fields the V2 client reads today. The comparison is not limited to them; the envelope test only
# checks the server still sends each one, so none can drop out of the comparison unnoticed.
CLIENT_READ_FIELDS = (
    "schema_version", "enabled", "role", "status", "can_manage_workspace",
    "sections", "native_delegation", "document_permissions", "document_queries",
    "document_management", "document_collaboration", "screening_management", "prompt_management",
    "action_management", "agent_management", "identity_management", "endpoint_management",
    "file_source_management", "workflow_management", "settings_management",
)


@pytest.fixture
def modelled(environment):  # noqa: F811 - the imported harness fixture
    environment.settings.update(MODELLED_SETTINGS)
    # The harness answers the group download predicate with True whatever the settings say. Run the
    # real one, so the download bits and settings_management read the same deployment.
    namespace = {}
    execute_functions("functions_settings.py", {
        "is_group_workspace_file_download_enabled", "is_group_workspace_file_download_admin_enabled",
        "_get_workspace_policy_target_id", "normalize_file_download_allowed_group_ids",
    }, namespace)
    environment.downloads.side_effect = namespace["is_group_workspace_file_download_enabled"]
    return environment


def real_context(env, role, status, **settings):
    group_overrides = {}
    for key in ("disable_file_downloads",):
        if key in settings:
            group_overrides[key] = settings.pop(key)
    env.settings.update(settings)
    env.records["group-a"]["status"] = status
    for key, value in group_overrides.items():
        env.records["group-a"][key] = value
    response = read_as(env, ROLE_USERS[role])
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def fixture_context(role, status, **settings):
    return fixture_module.group_context(
        "group-a", "Workspace A", role=role, status=status, viewer=ROLE_USERS[role], **settings,
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
# group_context against the builder, for every role, status and modelled variant.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
@pytest.mark.parametrize("variant", list(VARIANTS))
def test_the_fixture_context_is_the_server_context(modelled, variant, role, status):
    real = real_context(modelled, role, status, **VARIANTS[variant])
    found = differences(real, fixture_context(role, status, **VARIANTS[variant]))
    assert not found, describe(found)


@pytest.mark.parametrize("status", STATUSES)
def test_the_envelope_and_workspace_keys_match(modelled, status):
    real = real_context(modelled, "Owner", status)
    fixture = fixture_context("Owner", status)
    assert set(fixture) == set(real), (
        f"only on the server: {sorted(set(real) - set(fixture))}; only in the fixture: {sorted(set(fixture) - set(real))}"
    )
    assert set(CLIENT_READ_FIELDS) <= set(real) - METADATA_FIELDS
    assert fixture["workspace"].keys() == real["workspace"].keys()
    assert fixture["workspace"]["owner"].keys() == real["workspace"]["owner"].keys()
    assert fixture["scope"].keys() == real["scope"].keys()
    assert (fixture["scope"]["kind"], real["scope"]["kind"]) == ("group", "group")
    assert fixture["viewer_id"] == real["viewer_id"] == "owner"


def test_the_reason_constants_are_the_servers_texts(modelled):
    """The browser suites assert these constants, so each must be what the server sends."""
    assert real_context(modelled, "Owner", "inactive")["sections"]["documents"]["reason"] == (
        fixture_module.GROUP_INACTIVE_REASON
    )
    assert real_context(modelled, "Owner", "archived")["sections"]["members"]["reason"] == (
        fixture_module.GROUP_STATUS_UNKNOWN_REASON
    )
    reader = real_context(modelled, "User", "active")
    assert reader["sections"]["identities"]["reason"] == fixture_module.GROUP_CONNECTIONS_ROLE_REASON
    assert reader["sections"]["sync"]["reason"] == fixture_module.GROUP_CONNECTIONS_ROLE_REASON
    for section in ("settings", "activity", "statistics"):
        assert reader["sections"][section]["reason"] == fixture_module.GROUP_SETTINGS_MANAGER_REASON
    no_plugins = real_context(modelled, "Owner", "active", allow_group_plugins=False)
    assert no_plugins["sections"]["actions"]["reason"] == fixture_module.GROUP_ACTIONS_DISABLED_REASON
    no_agents = real_context(modelled, "Owner", "active", allow_group_agents=False)
    assert no_agents["sections"]["agents"]["reason"] == fixture_module.GROUP_AGENTS_DISABLED_REASON
    downloads_disabled = real_context(modelled, "Owner", "active", disable_file_downloads=True)
    assert downloads_disabled["document_permissions"]["can_download"] is False
    assert "download" not in downloads_disabled["document_management"]["operations"]


def real_context_as(env, role, status, *, roles=("User",), **settings):
    """The whole context the real builder sends for a role, status, settings and the caller's session
    app roles. The switch test needs the session-role seam because `holds_create_groups_role` is a
    session role on the server, not a setting, so it can't go through `real_context`'s fixed ["User"]."""
    group_overrides = {}
    for key in ("disable_file_downloads",):
        if key in settings:
            group_overrides[key] = settings.pop(key)
    env.settings.update(settings)
    env.records["group-a"]["status"] = status
    for key, value in group_overrides.items():
        env.records["group-a"][key] = value
    with env.client.session_transaction() as state:
        state["user"] = {"oid": ROLE_USERS[role], "roles": list(roles)}
    response = env.client.get("/api/v2/workspaces/group/group-a")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


@pytest.mark.parametrize("switch", list(SETTINGS_SWITCHES))
def test_settings_management_tracks_each_capability_switch(modelled, switch):
    """Each `group_context` settings switch moves the WHOLE context exactly as the real policy does
    under the setting or session role it stands for -- not just `settings_management`. Downloads-off,
    for one, also has to empty `document_permissions.can_download` and the `download` operation, and
    the walk catches any other field a switch moves that the fixture would otherwise miss."""
    fixture_switches, real_settings, roles = SETTINGS_SWITCHES[switch]
    served = fixture_context("Owner", "active", **fixture_switches)
    real = real_context_as(modelled, "Owner", "active", roles=roles, **real_settings)
    found = differences(real, served)
    assert not found, f"{switch}:\n{describe(found)}"


def test_an_unrecognized_status_is_reported_as_unknown_by_both():
    assert fixture_context("Owner", "archived") == fixture_context("Owner", "unknown")
    assert fixture_context("Owner", "archived")["status"] == "unknown"


def test_the_fixture_context_is_a_fresh_copy_each_time():
    """Tests edit the contexts they are served, so no two calls may share state."""
    first = fixture_context("Owner", "active")
    second = fixture_context("Owner", "active")
    first["sections"]["documents"]["enabled"] = False
    first["document_management"]["operations"].clear()
    first["settings_management"]["reasons"].clear()
    assert second == fixture_context("Owner", "active")
    assert deepcopy(second) == second
    switched_off = fixture_context("Owner", "active", allow_group_agents=False)
    switched_off["action_management"]["operations"].append("create")
    assert switched_off["agent_management"]["operations"] == []


# --------------------------------------------------------------------------
# Every context a per-section fixture seeds or recomputes.
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


SEEDED = [
    pytest.param(fixture_module.GroupWorkspaceFixture, "group-a", "Owner", {}, id="shell-group-a"),
    pytest.param(fixture_module.GroupWorkspaceFixture, "group-b", "User", {}, id="shell-group-b"),
    # The read-only documents fixture views both groups as an ordinary member.
    pytest.param(GroupDocumentsFixture, "group-a", "User", EXTRACTION_ON, id="documents-group-a"),
    pytest.param(GroupDocumentsFixture, "group-b", "User", EXTRACTION_ON, id="documents-group-b"),
    pytest.param(GroupDocumentManagementFixture, "group-a", "Owner", EXTRACTION_ON, id="document-management-group-a"),
    pytest.param(GroupDocumentManagementFixture, "group-b", "DocumentManager", EXTRACTION_ON,
                 id="document-management-group-b"),
    pytest.param(GroupDocumentCollaborationFixture, "group-a", "Owner", EXTRACTION_ON, id="collaboration-group-a"),
    pytest.param(GroupDocumentCollaborationFixture, "group-b", "DocumentManager", EXTRACTION_ON,
                 id="collaboration-group-b"),
    pytest.param(GroupPromptsFixture, "group-a", "Owner", {}, id="prompts-group-a"),
    pytest.param(GroupPromptsFixture, "group-b", "User", {}, id="prompts-group-b"),
    pytest.param(GroupActionsFixture, "group-a", "Owner", {}, id="actions-group-a"),
    pytest.param(GroupActionsFixture, "group-b", "User", {}, id="actions-group-b"),
    pytest.param(GroupActionsFixture, "group-c", "Owner", VARIANTS["plugins-off"], id="actions-group-c"),
    pytest.param(GroupAgentsFixture, "group-a", "Owner", {}, id="agents-group-a"),
    pytest.param(GroupAgentsFixture, "group-b", "User", {}, id="agents-group-b"),
    pytest.param(GroupAgentsFixture, "group-c", "Owner", VARIANTS["agents-off"], id="agents-group-c"),
]


@pytest.mark.parametrize("fixture_class,group_id,role,variant", SEEDED)
def test_every_seeded_per_section_context_is_the_servers(modelled, fixture_class, group_id, role, variant):
    served = built(fixture_class).groups[group_id]
    real = real_context(modelled, role, "active", **variant)
    found = differences(real, served)
    assert not found, describe(found)


SETTERS = {
    "set_action_policy": (
        fixture_module.GroupWorkspaceFixture,
        lambda fixture, role, status: fixture.set_action_policy("group-a", role=role, status=status), {},
    ),
    "set_policy": (
        GroupDocumentManagementFixture,
        lambda fixture, role, status: fixture.set_policy("group-a", role=role, status=status), EXTRACTION_ON,
    ),
    "configure_group": (
        GroupDocumentCollaborationFixture,
        lambda fixture, role, status: fixture.configure_group("group-a", role=role, status=status), EXTRACTION_ON,
    ),
    "set_prompt_policy": (
        GroupPromptsFixture,
        lambda fixture, role, status: fixture.set_prompt_policy("group-a", role=role, status=status), {},
    ),
    "set_viewer_role": (
        GroupMembersFixture,
        lambda fixture, role, status: fixture.set_viewer_role("group-a", role, status=status), {},
    ),
}


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
@pytest.mark.parametrize("setter", list(SETTERS))
def test_every_per_section_recomputation_is_the_servers(modelled, setter, role, status):
    fixture_class, apply, variant = SETTERS[setter]
    served = built(fixture_class, lambda fixture: apply(fixture, role, status)).groups["group-a"]
    found = differences(real_context(modelled, role, status, **variant), served)
    assert not found, describe(found)


# --------------------------------------------------------------------------
# Refusals: a non-member and a missing group.
# --------------------------------------------------------------------------

class _FakeRoute:
    def __init__(self, url):
        self.request = type("Request", (), {"url": url})()
        self.status = None
        self.payload = None

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def fixture_read(fixture, group_id):
    path = f"/api/v2/workspaces/group/{group_id}"
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, ApiRequest(method="GET", path=path, query={}, body=None))
    return route.status, route.payload


def test_a_non_member_is_refused_with_the_servers_answer(modelled):
    response = read_as(modelled, "outsider")
    fixture = built(fixture_module.GroupWorkspaceFixture)
    fixture.denied_groups.add("group-a")
    assert fixture_read(fixture, "group-a") == (response.status_code, response.get_json()) == (
        403, {"error": "You do not have access to the selected group."},
    )


def test_a_missing_group_is_refused_with_the_servers_answer(modelled):
    response = read_as(modelled, "owner", group_id="group-missing")
    fixture = built(fixture_module.GroupWorkspaceFixture)
    assert fixture_read(fixture, "group-missing") == (response.status_code, response.get_json()) == (
        404, {"error": fixture_module.GROUP_CONTEXT_NOT_FOUND_ERROR},
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
