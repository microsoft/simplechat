#!/usr/bin/env python3
# test_v2_admin_file_sync_targets.py
"""
Browser coverage for managing File Sync sources on behalf of another workspace in V2.
Version: 0.261.445
Implemented in: 0.261.445

The classic File Sync card has a block for each kind of workspace: search for a user, a group
or a public workspace, or paste an ID, then open that target's sources. The V2 card now has the
same three blocks. Exercise them against the built application with the administrator File Sync
routes intercepted: a search that is too short is not sent, a search lists matches, choosing one
fills the ID, and Manage sources opens the shared file sources workbench over the administrator
routes -- listing, adding and syncing a source -- with the server's refusal of an edit shown in
the editor and the draft kept. A failed search and a malformed pasted ID are reported, a kind of
workspace that is off in the saved settings is not offered, and the controls never overflow on
a phone.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

# Fixtures stay under ui_tests; the import also registers Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

SECTIONS = {"knowledge": ("file-sync-section",)}
ARTIFACTS = "v2_admin_file_sync_targets"
GROUP_BASE = "/api/admin/file-sync/group/group-1"
USER_BASE = "/api/admin/file-sync/personal/user-9"

OPTIONS = {
    "source_types": [
        {"value": "smb", "label": "SMB Share", "visible": True},
        {"value": "azure_files", "label": "Azure Files", "visible": True},
        {"value": "azure_blob", "label": "Azure Blob Storage", "visible": True},
    ],
    "eligible_identity_ids": {"smb": [], "azure_files": [], "azure_blob": []},
    "schedule": {"min_interval_minutes": 15, "max_interval_minutes": 10080},
    "limits": {"max_sources": 10},
    "recursive_allowed": True,
    "default_remote_delete_policy": "ignore",
}


def source_record(source_id, name, unc_path):
    """A source as the administrator list route projects it: no config revision, no actions."""
    return {
        "id": source_id,
        "name": name,
        "source_type": "smb",
        "enabled": True,
        "recursive": True,
        "connection": {"unc_path": unc_path, "selected_paths": []},
        "filters": {},
        "schedule": {"enabled": False, "interval_minutes": 60},
        "remote_delete_policy": "ignore",
        "identity_id": "",
        "credentials": {"auth_type": "anonymous", "password_stored": False, "secret_stored": False},
    }


class FileSyncAdminApi:
    """The administrator File Sync and identity routes, answering from memory."""

    def __init__(self, ui):
        self.ui = ui
        self.searches = []
        self.writes = []
        self.search_error = False
        self.group_sources = [source_record("source-1", "Quarterly share", "\\\\files\\reports")]
        self.user_sources = []
        ui.extra_routes.update({
            ("GET", "/api/admin/file-sync/groups/search"): lambda route: self.search(route, "groups"),
            ("GET", "/api/admin/file-sync/users/search"): lambda route: self.search(route, "users"),
            ("GET", f"{GROUP_BASE}/sources"): lambda route: route.fulfill(json={"sources": self.group_sources}),
            ("POST", f"{GROUP_BASE}/sources"): self.create_group_source,
            ("GET", f"{GROUP_BASE}/source-options"): lambda route: route.fulfill(json=OPTIONS),
            ("GET", "/api/admin/workspace-identities/group/group-1/identities"):
                lambda route: route.fulfill(json={"identities": []}),
            ("PATCH", f"{GROUP_BASE}/sources/source-1"): self.refuse_edit,
            ("POST", f"{GROUP_BASE}/sources/source-1/sync"): self.sync,
            ("GET", f"{GROUP_BASE}/sources/source-1/runs"): lambda route: route.fulfill(json={"runs": []}),
            ("GET", f"{USER_BASE}/sources"): lambda route: route.fulfill(json={"sources": self.user_sources}),
            ("GET", f"{USER_BASE}/source-options"): lambda route: route.fulfill(json=OPTIONS),
            ("GET", "/api/admin/workspace-identities/personal/user-9/identities"):
                lambda route: route.fulfill(json={"identities": []}),
        })

    def search(self, route, key):
        query = parse_qs(urlsplit(route.request.url).query)["q"][0]
        self.searches.append((key, query))
        if self.search_error:
            route.fulfill(status=500, json={"error": "The directory search failed."})
        elif key == "groups":
            route.fulfill(json={"groups": [
                {"id": "group-1", "name": "Finance", "description": "Finance team"},
                {"id": "group-2", "name": "Finance Ops", "description": ""},
            ]})
        else:
            route.fulfill(json={"users": [
                {"id": "user-1", "displayName": "Jane Doe", "email": "jane@contoso.test"},
            ]})

    def create_group_source(self, route):
        body = json.loads(route.request.post_data or "{}")
        self.writes.append(("POST", f"{GROUP_BASE}/sources", body))
        created = source_record("source-2", body["name"], body["connection"]["unc_path"])
        self.group_sources = [created, *self.group_sources]
        route.fulfill(status=201, json={"source": created})

    def refuse_edit(self, route):
        self.writes.append(("PATCH", f"{GROUP_BASE}/sources/source-1", json.loads(route.request.post_data or "{}")))
        route.fulfill(status=403, json={"error": "You do not have permission to perform this File Sync operation."})

    def sync(self, route):
        self.writes.append(("POST", f"{GROUP_BASE}/sources/source-1/sync", None))
        route.fulfill(status=202, json={"run": {"id": "run-1", "status": "queued"}})

    def written(self, method, path):
        matches = [body for (verb, target, body) in self.writes if verb == method and target == path]
        assert matches, f"No {method} {path} was sent: {self.writes}"
        return matches[-1]


@pytest.fixture
def targets_ui(page):
    fixture = AdminSettingsFixture(page, sections=SECTIONS)
    fixture.settings.update({
        "enable_file_sync": True,
        "enable_redis_cache": True,
        "enable_file_sync_personal": True,
        "enable_file_sync_group": True,
        "enable_file_sync_public": False,
        "file_sync_visible_source_types": ["smb", "azure_files", "azure_blob"],
    })
    fixture.api = FileSyncAdminApi(fixture)
    yield fixture
    fixture.assert_clean()


def region(page, heading):
    return page.get_by_role("region", name=heading, exact=True)


def forget_status(ui, status):
    """A refusal the test provoked on purpose is logged by the browser; it is not a defect."""
    ui.errors[:] = [error for error in ui.errors if f"status of {status}" not in error]


@pytest.mark.parametrize("width", [1440, 390])
def test_each_kind_of_workspace_has_its_own_search_and_manage_controls(targets_ui, width):
    targets_ui.open(width=width, ready_region="File Sync")
    page = targets_ui.page

    for heading in ("User sources", "Group sources", "Public workspace sources"):
        expect(region(page, heading)).to_be_visible()

    users = region(page, "User sources")
    expect(users.get_by_label("Search users", exact=True)).to_be_enabled()
    expect(users.get_by_label("User ID", exact=True)).to_be_enabled()
    # Nothing is chosen yet, so there is nothing to manage.
    expect(users.get_by_role("button", name="Manage sources")).to_be_disabled()
    expect(users.get_by_text("No user selected.", exact=True)).to_be_visible()

    # Public workspaces are off in the saved settings, so they say so instead of offering a
    # manager the server would refuse.
    public = region(page, "Public workspace sources")
    expect(public.get_by_text(re.compile("Public workspaces is off in the saved settings"))).to_be_visible()
    expect(public.get_by_label("Search public workspaces", exact=True)).to_be_disabled()
    expect(public.get_by_role("button", name="Manage sources")).to_be_disabled()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    targets_ui.capture(f"manager-{width}", ARTIFACTS)


def test_a_search_picks_a_group_and_its_sources_can_be_listed_added_and_synced(targets_ui):
    ui, api = targets_ui, targets_ui.api
    ui.open(width=1440, ready_region="File Sync")
    page = ui.page
    groups = region(page, "Group sources")
    search = groups.get_by_label("Search groups", exact=True)

    # A query the server would answer with nothing is not sent.
    search.fill("f")
    groups.get_by_role("button", name="Search", exact=True).click()
    expect(groups.get_by_text("Type at least 2 characters to search.", exact=True)).to_be_visible()
    assert api.searches == []

    search.fill("fin")
    search.press("Enter")
    expect(groups.get_by_text("2 matches. Choose one.", exact=True)).to_be_visible()
    assert api.searches == [("groups", "fin")]
    groups.get_by_role("button", name=re.compile(r"^Finance\b.*Finance team")).click()
    expect(groups.get_by_text("Selected: Finance (Finance team)", exact=True)).to_be_visible()
    expect(groups.get_by_label("Group ID", exact=True)).to_have_value("group-1")
    groups.get_by_role("button", name="Manage sources").click()

    dialog = page.get_by_role("dialog", name="Manage group sync sources")
    expect(dialog.get_by_text("Finance (Finance team) (group-1)", exact=True)).to_be_visible()
    expect(dialog.get_by_text("Quarterly share", exact=True)).to_be_visible()
    # The sources belong to the group, not to the administrator, so the page does not send
    # them to a documents page of their own.
    expect(dialog.get_by_role("link", name="Documents")).to_have_count(0)

    dialog.get_by_role("button", name="New file source", exact=True).click()
    editor = page.get_by_role("dialog", name="New file source")
    editor.get_by_label("Name", exact=True).fill("Policies share")
    editor.get_by_label("Network path").fill("\\\\files\\policies")
    editor.get_by_label("Enter credentials directly", exact=True).check()
    editor.get_by_label("Authentication method", exact=True).select_option("anonymous")
    editor.get_by_role("button", name="Create source", exact=True).click()
    expect(page.get_by_role("dialog", name="New file source")).to_have_count(0)
    expect(dialog.get_by_text("Policies share", exact=True)).to_be_visible()
    created = api.written("POST", f"{GROUP_BASE}/sources")
    assert created["name"] == "Policies share" and created["source_type"] == "smb"
    assert created["credentials"] == {"auth_type": "anonymous"}
    assert "expected_config_revision" not in created

    dialog.get_by_role("button", name="Sync Quarterly share now", exact=True).click()
    expect(page.get_by_text("Sync started for Quarterly share", exact=True)).to_be_visible()
    api.written("POST", f"{GROUP_BASE}/sources/source-1/sync")

    # The server refuses an edit to a workspace the administrator does not manage. Its reason
    # is shown in the editor, and what was typed is kept.
    dialog.get_by_role("button", name="Edit Quarterly share", exact=True).click()
    editor = page.get_by_role("dialog", name="Edit file source")
    editor.get_by_label("Name", exact=True).fill("Quarterly share v2")
    editor.get_by_role("button", name="Save changes", exact=True).click()
    expect(editor.get_by_role("alert")).to_contain_text("You do not have permission to perform this File Sync operation.")
    expect(editor.get_by_label("Name", exact=True)).to_have_value("Quarterly share v2")
    assert "expected_config_revision" not in api.written("PATCH", f"{GROUP_BASE}/sources/source-1")
    forget_status(ui, 403)

    editor.get_by_role("button", name="Cancel", exact=True).click()
    page.get_by_role("button", name="Discard", exact=True).click()
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    # Focus goes back to the control that opened the manager.
    expect(groups.get_by_role("button", name="Manage sources")).to_be_focused()


def test_a_failed_search_is_reported_and_a_pasted_id_is_checked_before_it_is_used(targets_ui):
    ui, api = targets_ui, targets_ui.api
    ui.open(width=1440, ready_region="File Sync")
    page = ui.page
    users = region(page, "User sources")

    api.search_error = True
    users.get_by_label("Search users", exact=True).fill("ja")
    users.get_by_role("button", name="Search", exact=True).click()
    expect(users.get_by_role("alert")).to_contain_text("The directory search failed.")
    forget_status(ui, 500)

    # An ID that could name another route is refused rather than put in a URL.
    users.get_by_label("User ID", exact=True).fill("a/b")
    expect(users.get_by_text("Target ID: a/b", exact=True)).to_be_visible()
    users.get_by_role("button", name="Manage sources").click()
    expect(users.get_by_role("alert").filter(has_text="That ID is not valid.")).to_be_visible()
    expect(page.get_by_role("dialog")).to_have_count(0)

    users.get_by_label("User ID", exact=True).fill("user-9")
    users.get_by_role("button", name="Manage sources").click()
    dialog = page.get_by_role("dialog", name="Manage user sync sources")
    expect(dialog.get_by_text("user-9", exact=True)).to_be_visible()
    expect(dialog.get_by_text("No file sources yet", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="New file source", exact=True)).to_be_visible()
    ui.capture("user-manager", ARTIFACTS)


def test_a_kind_of_workspace_switched_on_only_in_the_draft_is_not_offered(targets_ui):
    ui = targets_ui
    ui.settings["enable_file_sync"] = False
    ui.open(width=1440, ready_region="File Sync")
    card = region(ui.page, "File Sync")

    card.get_by_text("Enable File Sync", exact=True).click()
    for heading in ("User sources", "Group sources", "Public workspace sources"):
        section = region(ui.page, heading)
        expect(section.get_by_text(re.compile("File Sync is not on in the saved settings"))).to_be_visible()
        expect(section.get_by_role("button", name="Manage sources")).to_be_disabled()


def test_no_kind_of_workspace_is_offered_while_redis_cache_is_off(targets_ui):
    # The server treats File Sync as off without Redis, so it would refuse every target.
    ui = targets_ui
    ui.settings["enable_redis_cache"] = False
    ui.open(width=1440, ready_region="File Sync")

    for heading in ("User sources", "Group sources", "Public workspace sources"):
        section = region(ui.page, heading)
        expect(section.get_by_text(re.compile("Redis Cache is off in the saved settings"))).to_be_visible()
        expect(section.get_by_label(re.compile("^Search "))).to_be_disabled()
        expect(section.get_by_role("button", name="Manage sources")).to_be_disabled()
