# test_v2_cross_scope_journeys.py
"""M11 cross-scope journeys: one session moving between personal, group and public workspaces, with
each scope reading only its own routes.

Version: 0.261.185
Implemented in: 0.261.185

These journeys drive the real SPA across all three workspace scopes in one session (one bootstrap,
one fixture) and prove the isolation the whole shared-workspaces programme rests on: a personal read
never carries a group or public id, a group page never reaches a personal or public route, and a
public page never reaches a personal or group route. The composite fixture answers every scope while
keeping every unserved route a trap, so a leak fails the run rather than rendering.

Coverage of M11 contract sec 2.2 (cross-scope journeys):
    personal -> group -> public -> back, each read stays in scope . test_navigation_keeps_every_read_in_its_own_scope
    the group picker moves within the group scope ............... test_the_group_picker_stays_in_the_group_scope
    the public picker moves within the public scope ............ test_the_public_picker_stays_in_the_public_scope
    a public deep link never reads the active group ........... test_a_public_deep_link_never_reads_the_active_group
    Settings activation turns public on, others untouched .... test_settings_activation_turns_public_on_without_the_other_scopes

Future rows (M11 contract sec 3.1 public-directory gaps, tracked but not built here):
    G1 DocumentManager can request access ................ building (decision, not in these journeys)
    G2 saved directory lists ............................ building
    G3 bulk directory actions ........................... building
    G4 chat from the directory (visible or all) ......... building
    G5 directory-wide search ............................ declined (decision 29)
When M10C integrates its public settings, activity and statistics sections, no cross-scope journey
changes: the public isolation here is by route family, not by section.
"""

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.cross_scope_journeys import cross_scope_journeys_ui  # noqa: F401
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui


def _is_personal(path):
    return path == "/api/documents" or path.startswith("/api/documents/")


def _is_group(path):
    return (
        path.startswith("/api/group")
        or path.startswith("/api/groups")
        or path.startswith("/api/v2/workspaces/group/")
    )


def _is_public(path):
    return path.startswith("/api/public") or path.startswith("/api/v2/workspaces/public/")


def _api_reads_since(ui, marker):
    return [entry.path for entry in ui.requests[marker:]
            if entry.method == "GET" and entry.path.startswith("/api/")]


def refocus(ui):
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")


def test_navigation_keeps_every_read_in_its_own_scope(cross_scope_journeys_ui):
    ui = cross_scope_journeys_ui

    # Personal: the My Workspace documents view reads only personal document routes -- never a group
    # or public route, and (asserted in the fixture) never with a group or public id on the query.
    marker = len(ui.requests)
    ui.open("/workspace/documents")
    expect(ui.page.get_by_role("button", name="Details for Personal Alpha", exact=True)).to_be_visible()
    reads = _api_reads_since(ui, marker)
    assert any(_is_personal(path) for path in reads), reads
    assert not [path for path in reads if _is_group(path) or _is_public(path)], reads

    # Group: opening the already-active group reads its context and never a personal or public route.
    marker = len(ui.requests)
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    reads = _api_reads_since(ui, marker)
    assert any(_is_group(path) for path in reads), reads
    assert not [path for path in reads if _is_personal(path) or _is_public(path)], reads

    # Public: the public documents view reads only public routes, identifying the workspace by path.
    marker = len(ui.requests)
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    reads = _api_reads_since(ui, marker)
    assert any(_is_public(path) for path in reads), reads
    assert not [path for path in reads if _is_personal(path) or _is_group(path)], reads

    # Back to personal: returning to My Workspace still reads only personal routes -- the group and
    # public visits left no active selection that retargets a personal read.
    marker = len(ui.requests)
    ui.open("/workspace/documents")
    expect(ui.page.get_by_role("button", name="Details for Personal Alpha", exact=True)).to_be_visible()
    reads = _api_reads_since(ui, marker)
    assert any(_is_personal(path) for path in reads), reads
    assert not [path for path in reads if _is_group(path) or _is_public(path)], reads


def test_the_group_picker_stays_in_the_group_scope(cross_scope_journeys_ui):
    ui = cross_scope_journeys_ui
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    marker = len(ui.requests)
    ui.page.get_by_role("combobox", name="Group workspace", exact=True).select_option("group-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/group-b")
    # Switching group activates the target and reads its context, and touches no other scope.
    active = [entry for entry in ui.writes if entry.path == "/api/groups/setActive"]
    assert active and active[-1].body == {"groupId": "group-b"}
    reads = _api_reads_since(ui, marker)
    assert not [path for path in reads if _is_personal(path) or _is_public(path)], reads


def test_the_public_picker_stays_in_the_public_scope(cross_scope_journeys_ui):
    ui = cross_scope_journeys_ui
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    marker = len(ui.requests)
    ui.page.get_by_role("combobox", name="Public Workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    expect(ui.page.get_by_role("button", name="Details for Read-only brief", exact=True)).to_be_visible()
    # Selecting the other public workspace activates it and reads it by id, and touches no other scope.
    active = [entry for entry in ui.writes if entry.path == "/api/public_workspaces/setActive"]
    assert active and active[-1].body == {"workspaceId": "pub-b"}
    assert ui.active_public == "pub-b"
    reads = _api_reads_since(ui, marker)
    assert not [path for path in reads if _is_personal(path) or _is_group(path)], reads


def test_a_public_deep_link_never_reads_the_active_group(cross_scope_journeys_ui):
    ui = cross_scope_journeys_ui
    # group-a is the active group. A public deep link must resolve the public workspace by its own id
    # and never fall back to reading the active group's documents.
    assert ui.active_group == "group-a"
    marker = len(ui.requests)
    ui.open("/public/pub-a/documents")
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    reads = _api_reads_since(ui, marker)
    assert any(path.startswith("/api/public-workspaces/pub-a/documents") for path in reads), reads
    assert not [path for path in reads if _is_group(path) or _is_personal(path)], reads


def test_settings_activation_turns_public_on_without_the_other_scopes(cross_scope_journeys_ui):
    ui = cross_scope_journeys_ui
    # Public workspaces are disabled deployment-wide, but personal and group are unaffected.
    ui.public_enabled = False
    ui.open("/public")
    expect(ui.page.get_by_text("Public Workspaces are not enabled", exact=True)).to_be_visible()
    ui.open("/workspace/documents")
    expect(ui.page.get_by_role("button", name="Details for Personal Alpha", exact=True)).to_be_visible()
    ui.open("/groups/group-a")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    # An administrator enables public workspaces in Settings: a refocus on the public surface picks it
    # up without a reload, and the personal and group scopes were never involved in the activation.
    ui.public_enabled = True
    ui.open("/public")
    refocus(ui)
    expect(ui.page.get_by_text("Public Workspaces are not enabled", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("combobox", name="Public Workspace", exact=True)).to_be_visible()
