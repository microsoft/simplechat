# test_v2_shared_workspace_overview_counts.py
"""
Real-SPA regression tests for group/public overview counts.
Version: 0.261.312
Implemented in: 0.261.310

Uses the established Azure Playwright-compatible connection fixture and closed
HTTP boundary; validates totals, zero/failure badges, scope switches and refresh.
"""

import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, group_context
from ui_tests.fixtures.public_workspace import PublicWorkspaceFixture, public_context
from ui_tests.fixtures.workspace_authoring import connect_options  # noqa: F401


pytestmark = pytest.mark.ui

LABELS = {
    "documents": "Documents", "tags": "Tags", "prompts": "Prompts", "sync": "File sources",
    "agents": "Agents", "actions": "Actions", "workflows": "Workflows",
    "identities": "Identities", "endpoints": "Endpoints", "members": "Members",
}
TOTALS = {
    "documents": 17, "tags": 2, "prompts": 1001, "sync": 3, "agents": 4,
    "actions": 5, "workflows": 8, "identities": 6, "endpoints": 7, "members": 1201,
}


class OverviewCounts:
    """Count responses keep paginated totals distinct from their first page."""

    def _init_counts(self, kind):
        self.kind = kind
        self.counts = {
            self.first_id: dict(TOTALS),
            self.second_id: {**TOTALS, "documents": 29, "prompts": 502, "members": 41},
        }
        self.malformed_counts = set()

    def _dispatch(self, route, entry):
        if entry.method != "GET":
            super()._dispatch(route, entry)
            return
        path = entry.path
        match = re.fullmatch(
            r"/api/(?:groups|public-workspaces)/([^/]+)/(documents(?:/facets|/tags)?|prompts|membership/members|identities|file-sources|agents|actions|model-endpoints)",
            path,
        )
        if match:
            identifier, resource = match.groups()
        elif path.startswith("/api/group_documents"):
            identifier = entry.query.get("group_id", [""])[0]
            resource = "documents" + path.removeprefix("/api/group_documents")
        elif path == "/api/group/workflows":
            identifier = entry.query.get("group_id", [""])[0]
            resource = "workflows"
        else:
            super()._dispatch(route, entry)
            return
        if identifier not in self.counts:
            super()._dispatch(route, entry)
            return
        key = {
            "documents/facets": "documents", "documents/tags": "tags",
            "file-sources": "sync", "membership/members": "members", "model-endpoints": "endpoints",
        }.get(resource, resource)
        if (identifier, key) in self.malformed_counts:
            self._json(route, {"unexpected": True})
            return
        total = self.counts[identifier][key]
        row = {"id": "item", "group_id": identifier, "public_workspace_id": identifier}
        if resource == "documents/facets":
            payload = {
                "total": total, "untagged": total, "processing": 0, "errors": 0, "recent": 0,
                "shared_with_me": 0, "by_tag": {}, "by_classification": {},
            }
        elif resource == "documents/tags":
            payload = {"tags": [{"name": f"tag-{index}", "count": 1} for index in range(total)]}
        elif resource == "documents":
            payload = {
                "documents": [], "total_count": total,
                "page": int(entry.query.get("page", ["1"])[0]),
                "page_size": int(entry.query.get("page_size", ["1"])[0]),
            }
        elif resource == "prompts":
            payload = {
                "prompts": [{**row, "public_id": identifier}] if total else [],
                "total_count": total, "page": 1, "page_size": 1,
            }
        elif resource == "membership/members":
            payload = {
                "members": [{
                    "userId": "owner", "displayName": "Owner", "email": "",
                    "role": "Owner", "member_actions": [],
                }] if total else [],
                "total_count": total, "page": 1, "page_size": 1,
                "membership_management": {"schema_version": 1, "operations": []},
            }
        else:
            array_key = {
                "file-sources": "file_sources", "model-endpoints": "endpoints",
            }.get(resource, resource)
            payload = {array_key: [
                {
                    **row, "id": f"item-{index}", "config_revision": "revision",
                    "source_actions": [], "revision": "revision", "endpoint_actions": [],
                }
                for index in range(total)
            ]}
        self._json(route, payload)


class GroupOverviewFixture(OverviewCounts, GroupWorkspaceFixture):
    first_id = "group-a"
    second_id = "group-b"

    def __init__(self, page):
        super().__init__(page)
        self.active_group = self.first_id
        self._init_counts("group")


class PublicOverviewFixture(OverviewCounts, PublicWorkspaceFixture):
    first_id = "pub-a"
    second_id = "pub-b"

    def __init__(self, page):
        super().__init__(page)
        self.workspaces[self.first_id] = public_context(self.first_id, "Research library", role="Owner", file_sync=True)
        self.active_workspace = self.first_id
        self._init_counts("public")


@pytest.fixture(params=["group", "public"])
def overview_ui(request, page):
    fixture = GroupOverviewFixture(page) if request.param == "group" else PublicOverviewFixture(page)
    yield fixture
    fixture.assert_clean()


def open_overview(ui, **options):
    base = "groups" if ui.kind == "group" else "public"
    ui.open(f"/{base}/{ui.first_id}", **options)
    expect(ui.page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()


def badge(ui, section, count):
    return ui.page.get_by_label(f"{LABELS[section]} count: {count}", exact=True)


def nav(ui, label):
    ui.page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role("link", name=label, exact=True).click()


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844),
])
def test_overview_shows_available_resource_totals(overview_ui, theme, width, height):
    ui = overview_ui
    open_overview(ui, theme=theme, width=width, height=height)
    available = list(TOTALS) if ui.kind == "group" else ["documents", "prompts", "sync", "identities", "members"]
    for section in available:
        expect(badge(ui, section, TOTALS[section])).to_be_visible()
    expect(ui.page.get_by_role("img", name=re.compile("count unavailable$"))).to_have_count(0)
    for entry in ui.requests:
        if entry.path.endswith(("/prompts", "/membership/members")):
            assert entry.query.get("page_size") == ["1"]
    for label in ("Settings", "Activity", "Statistics"):
        expect(ui.page.get_by_label(re.compile(f"^{label} count"))).to_have_count(0)
    if ui.kind == "public":
        expect(ui.page.get_by_label(re.compile("^Tags count"))).to_have_count(0)
        for label in ("Agents", "Actions", "Workflows", "Endpoints"):
            expect(ui.page.get_by_label(re.compile(f"^{label} count"))).to_have_count(0)
    ui.assert_no_overflow()


@pytest.mark.parametrize("failure", ["http", "malformed"])
def test_partial_failure_keeps_successful_and_zero_counts(overview_ui, failure):
    ui = overview_ui
    ui.counts[ui.first_id]["members"] = 0
    prefix = "groups" if ui.kind == "group" else "public-workspaces"
    if failure == "http":
        ui.reject_next("GET", f"/api/{prefix}/{ui.first_id}/prompts")
    else:
        ui.malformed_counts.add((ui.first_id, "prompts"))
    open_overview(ui)
    expect(ui.page.get_by_role("img", name="Prompts count unavailable", exact=True)).to_be_visible()
    expect(badge(ui, "documents", 17)).to_be_visible()
    expect(badge(ui, "members", 0)).to_be_visible()
    expect(badge(ui, "prompts", 0)).to_have_count(0)


def test_switch_discards_old_workspace_counts_and_delayed_response(overview_ui):
    ui = overview_ui
    prefix = "groups" if ui.kind == "group" else "public-workspaces"
    open_overview(ui)
    expect(badge(ui, "prompts", 1001)).to_be_visible()
    nav(ui, "Documents")
    expect(ui.page.get_by_role("heading", name="Overview", exact=True)).to_have_count(0)
    ui.defer_next("GET", f"/api/{prefix}/{ui.first_id}/prompts")
    nav(ui, "Overview")
    expect(badge(ui, "documents", 17)).to_be_visible()
    expect(badge(ui, "members", 1201)).to_be_visible()
    assert ui.pending_responses
    picker = "Group workspace" if ui.kind == "group" else "Public Workspace"
    ui.page.get_by_role("combobox", name=picker, exact=True).select_option(ui.second_id)
    expect(badge(ui, "documents", 29)).to_be_visible()
    expect(badge(ui, "prompts", 502)).to_be_visible()
    ui.release_responses()
    expect(badge(ui, "prompts", 1001)).to_have_count(0)
    if ui.kind == "group":
        expect(badge(ui, "members", 41)).to_be_visible()
    else:
        expect(ui.page.get_by_label(re.compile("^Members count"))).to_have_count(0)
        assert not [
            entry for entry in ui.requests
            if ui.second_id in entry.path and "/membership/" in entry.path
        ]
    expect(badge(ui, "identities", 6)).to_have_count(0)
    connection_reads = [
        entry for entry in ui.requests
        if ui.second_id in entry.path and entry.path.endswith(("/identities", "/file-sources"))
    ]
    assert not connection_reads


def test_focus_revalidation_refreshes_counts_and_revokes_unavailable_sections(overview_ui):
    ui = overview_ui
    open_overview(ui)
    expect(badge(ui, "documents", 17)).to_be_visible()
    expect(badge(ui, "identities", 6)).to_be_visible()
    ui.counts[ui.first_id]["documents"] = 23
    contexts = ui.groups if ui.kind == "group" else ui.workspaces
    contexts[ui.first_id]["sections"]["identities"].update(enabled=False, can_manage=False, reason="No longer available.")
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(badge(ui, "documents", 23)).to_be_visible()
    expect(badge(ui, "identities", 6)).to_have_count(0)
    expect(ui.page.get_by_label("Identities (unavailable)", exact=True)).to_be_visible()


def test_group_return_to_overview_refreshes_after_resource_change(page):
    ui = GroupOverviewFixture(page)
    try:
        open_overview(ui)
        expect(badge(ui, "tags", 2)).to_be_visible()
        nav(ui, "Tags")
        expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
        ui.counts[ui.first_id]["tags"] = 3
        nav(ui, "Overview")
        expect(badge(ui, "tags", 3)).to_be_visible()
    finally:
        ui.assert_clean()


def test_group_call_agent_only_count_and_locked_card_gates(page):
    ui = GroupOverviewFixture(page)
    ui.groups[ui.first_id] = group_context(ui.first_id, "Research group", allow_group_plugins=False)
    ui.groups[ui.first_id]["sections"]["endpoints"].update(enabled=False, can_manage=False, reason="Not enabled.")
    try:
        open_overview(ui)
        expect(badge(ui, "actions", 1)).to_be_visible()
        expect(badge(ui, "endpoints", 7)).to_have_count(0)
        assert not [entry for entry in ui.requests if entry.path.endswith(("/actions", "/model-endpoints"))]
    finally:
        ui.assert_clean()
