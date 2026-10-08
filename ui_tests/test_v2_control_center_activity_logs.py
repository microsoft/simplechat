# test_v2_control_center_activity_logs.py
"""
Browser coverage for V2 Activity Logs.
Version: 0.261.296
Implemented in: 0.261.284
Redesigned in: 0.261.296

Uses local built assets and intercepted APIs, with the shared Azure Playwright
connection helper when a workspace is configured. Covers desktop and mobile.
Since 0.261.296 the page leads with Azure-portal-style filter pills, shows people and
workspaces by name, cross-filters from any person, activity or workspace in a row, keeps
saved views and display preferences on the account, and shows times in local time with a
remembered UTC toggle.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from test_v2_control_center_users import ORIGIN, UsersFixture

pytestmark = [pytest.mark.ui, pytest.mark.browser_context_args(timezone_id="America/New_York", locale="en-US")]

ADA = {"id": "user-1", "name": "Ada Admin", "email": "ada@example.test", "kind": "user", "resolved": True}
BO = {"id": "user-3", "name": "Bo Builder", "email": "bo@example.test", "kind": "user", "resolved": True}
RESEARCH = {"type": "group", "id": "group-1", "name": "Research", "resolved": True}
LIBRARY = {"type": "public", "id": "pub-1", "name": "Library", "resolved": True}
NO_WORKSPACE = {"type": "", "id": "", "name": "", "resolved": False}


def _row(record, label, category, summary, actor, workspace, detail="", facts=(), status=None):
    return record, {
        "activity_type": record["activity_type"], "label": label, "category": category, "summary": summary,
        "detail": detail, "facts": [{"label": key, "value": value} for key, value in facts], "status": status,
        "actor": actor, "workspace": workspace,
    }


FIRST_PAGE = [
    _row({"id": "record-1", "timestamp": "2026-10-01T12:00:00Z", "activity_type": "token_usage", "user_id": "user-1",
          "workspace_type": "group", "workspace_context": {"group_id": "group-1"}, "approval_id": "approval-1",
          "description": "<img src=x onerror=alert(1)>"},
         "Token usage", "tokens", "12,345 tokens · gpt-4o", ADA, RESEARCH,
         detail="Chat · prompt 12,000 · completion 345", facts=[("Model", "gpt-4o"), ("Total tokens", "12,345")]),
    _row({"id": "record-2", "timestamp": "2026-10-01T11:00:00Z", "activity_type": "group_status_change",
          "changed_by": {"user_id": "admin-2", "email": "ops@example.test"}, "group": {"group_id": "group-1"}},
         "Group status changed", "groups", "Active → Locked",
         {"id": "admin-2", "name": "", "email": "ops@example.test", "kind": "user", "resolved": False}, RESEARCH,
         detail="Audit hold"),
    _row({"id": "record-3", "timestamp": "2026-10-01T10:00:00Z", "activity_type": "document_creation", "user_id": "user-1",
          "workspace_type": "public", "workspace_context": {"public_workspace_id": "pub-1"}},
         "Document created", "documents", "report.pdf", ADA, LIBRARY, detail="PDF · 2.0 KB", status="failed"),
    _row({"id": "record-4", "timestamp": "2026-10-01T09:00:00Z", "activity_type": "index_auto_fix", "user_id": "system"},
         "Search index fields added", "data", "Added 2 fields to the group index",
         {"id": "", "name": "", "email": "", "kind": "system", "resolved": False}, NO_WORKSPACE),
]
SECOND_PAGE = [
    _row({"id": "record-5", "timestamp": "2026-09-30T08:00:00Z", "activity_type": "user_login", "user_id": "user-3"},
         "User login", "sign_in", "Signed in", BO, NO_WORKSPACE, detail="Method: azure_ad"),
]
TYPE_CATALOG = [
    {"activity_type": "user_login", "label": "User login", "category": "sign_in", "category_label": "Sign-in and consent"},
    {"activity_type": "token_usage", "label": "Token usage", "category": "tokens", "category_label": "Token usage"},
    {"activity_type": "document_creation", "label": "Document created", "category": "documents", "category_label": "Documents"},
    {"activity_type": "group_status_change", "label": "Group status changed", "category": "groups", "category_label": "Groups"},
]


def _today():
    return datetime.now(timezone.utc).date()


def _eventually(page, check, timeout_ms=5000, message="Timed out waiting for the expected server request."):
    """Wait for state the fixture records on the server side, which the browser cannot observe."""
    waited = 0
    while not check():
        if waited >= timeout_ms:
            raise AssertionError(message)
        page.wait_for_timeout(50)
        waited += 50


class ActivityFixture(UsersFixture):
    def __init__(self, page):
        self.fail = False
        self.empty = False
        self.allowed = True
        self.settings_fail = False
        self.console_errors = []
        self.settings = {}
        self.settings_posts = []
        super().__init__(page)
        page.on("pageerror", lambda error: self.console_errors.append(str(error)))

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/user/settings":
            if request.method == "GET" and self.settings_fail:
                route.fulfill(status=500, json={"error": "Settings are unavailable."})
            elif request.method == "GET":
                route.fulfill(json={"settings": self.settings})
            else:
                payload = json.loads(request.post_data or "{}")["settings"]
                self.settings_posts.append(payload)
                self.settings.update(payload)
                route.fulfill(json={"message": "Saved."})
        elif path in ("/api/v2/control-center/activity-logs/people", "/api/v2/control-center/activity-logs/workspaces"):
            self.requests.append((request.method, path, parsed.query))
            term = query.get("q", [""])[0].lower()
            if path.endswith("/people"):
                people = [{"id": person["id"], "display_name": person["name"], "email": person["email"]} for person in (ADA, BO)]
                route.fulfill(json={"people": [item for item in people if term in item["display_name"].lower() or term == item["id"]]})
            else:
                spaces = [{"type": item["type"], "id": item["id"], "name": item["name"]} for item in (RESEARCH, LIBRARY)]
                route.fulfill(json={"workspaces": [item for item in spaces if term in item["name"].lower() or term == item["id"]]})
        elif path.startswith("/api/v2/control-center/activity-logs"):
            self.requests.append((request.method, path, parsed.query))
            if self.fail:
                route.fulfill(status=500, json={"error": "Unable to load activity logs. Retry."})
            elif path.endswith("/summary"):
                route.fulfill(json={
                    "facets": [{"activity_type": "token_usage", "count": 30, "label": "Token usage", "category": "tokens"},
                               {"activity_type": "user_login", "count": 9, "label": "User login", "category": "sign_in"},
                               {"activity_type": "document_creation", "count": 3, "label": "Document created", "category": "documents"}],
                    "histogram": [{"date": "2026-09-30", "count": 22}, {"date": "2026-10-01", "count": 20}, {"date": "2026-10-02", "count": 0}],
                    "sample_size": 42, "sample_limit": 5000, "truncated": False, "bucket_days": 1, "type_catalog": TYPE_CATALOG,
                })
            elif path.endswith("/export.csv"):
                route.fulfill(content_type="text/csv", body="timestamp,id,user_id\n2026-10-01,record-1,user-1\n",
                              headers={"Content-Disposition": 'attachment; filename="activity_logs.csv"'})
            else:
                rows = [] if self.empty else SECOND_PAGE if "cursor" in query else FIRST_PAGE
                labels = {}
                if query.get("user_id") == ["user-1"]:
                    labels["person"] = {key: ADA[key] for key in ("id", "name", "email", "resolved")}
                if query.get("workspace_id") == ["group-1"]:
                    labels["workspace"] = RESEARCH
                route.fulfill(json={
                    "items": [record for record, _ in rows], "presentation": [view for _, view in rows],
                    "filter_labels": labels, "search_people": {"matched": 0, "truncated": False},
                    "next_cursor": None if "cursor" in query or self.empty else "test-cursor",
                    "snapshot": "2026-10-07T12:00:00",
                })
        elif path == "/api/v2/bootstrap" and not self.allowed:
            route.fulfill(json={
                "version": "0.261.296", "user": {"id": "reader", "display_name": "Reader", "is_admin": False, "roles": ["ControlCenterDashboardReader"]},
                "branding": {"app_title": "SimpleChat", "show_logo": False}, "features": {},
                "control_center": {"can_view_dashboard": True, "can_manage_users": False, "can_manage_groups": False,
                                   "can_manage_workspaces": False, "can_view_activity_logs": False, "can_run_maintenance": False},
                "catalogs": {"models": [], "agents": [], "prompts": []}, "scope": {"groups": [], "public_workspaces": []},
                "navigation": {"custom_pages": {"enabled": False, "items": []}, "external_links": {"enabled": False, "items": []}},
                "workspace": {"sections": {}}, "admin_nav": [], "notices": {"ai": {}, "web_search": {}}, "settings": {},
            })
        else:
            super()._route(route)

    def open(self, query="", mobile=False):
        self.page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2/control-center/activity-logs{query}", wait_until="networkidle")

    def page_queries(self):
        return [parse_qs(query) for _, path, query in self.requests if path.endswith("/activity-logs")]

    def assert_clean(self):
        super().assert_clean()
        assert not self.console_errors, self.console_errors


@pytest.fixture
def activity_ui(page):
    fixture = ActivityFixture(page)
    yield fixture
    fixture.assert_clean()


def test_first_viewport_shows_named_readable_rows(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    expect(page.get_by_role("heading", name="Activity Logs", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Date: Last 30 days")).to_be_visible()
    person = page.get_by_role("button", name="Show only activity by Ada Admin").first
    expect(person).to_be_visible()
    box = person.bounding_box()
    assert box and box["y"] + box["height"] < 900, "The first log row should be visible without scrolling."
    expect(page.get_by_role("button", name="Show only activity in Research (Group)").first).to_be_visible()
    table = page.get_by_role("table")
    expect(table.get_by_text("12,345 tokens · gpt-4o")).to_be_visible()
    expect(table.get_by_text("Chat · prompt 12,000 · completion 345")).to_be_visible()
    expect(page.get_by_role("button", name="Show only activity by ops@example.test")).to_be_visible()
    expect(table.get_by_text("Failed", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="System", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name=re.compile("user-1"))).to_have_count(0)
    expect(page.get_by_role("region", name="Activity trend").get_by_text("42 records", exact=False)).to_be_visible()
    latest = activity_ui.page_queries()[-1]
    assert latest["end_date"] == [_today().isoformat()]
    assert latest["start_date"] == [(_today() - timedelta(days=29)).isoformat()]


def test_cross_filters_from_rows_show_names_in_pills(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    page.get_by_role("button", name="Show only activity by Ada Admin").first.click()
    expect(page).to_have_url(re.compile(r"user_id=user-1"))
    expect(page.get_by_role("button", name="Person: Ada Admin")).to_be_visible()
    # The rows reload, so focus moves to the filter that was just set.
    expect(page.get_by_role("button", name="Person: Ada Admin")).to_be_focused()
    page.get_by_role("button", name="Show only activity in Research (Group)").first.click()
    expect(page).to_have_url(re.compile(r"workspace_type=group&workspace_id=group-1"))
    expect(page.get_by_role("button", name="Group: Research")).to_be_focused()
    page.get_by_role("button", name="Show only Token usage activity").click()
    expect(page).to_have_url(re.compile(r"activity_type=token_usage"))
    expect(page.get_by_role("button", name="Activity: Token usage")).to_be_focused()
    latest = activity_ui.page_queries()[-1]
    assert latest["user_id"] == ["user-1"] and latest["workspace_id"] == ["group-1"]
    assert latest["activity_type"] == ["token_usage"] and "cursor" not in latest
    page.get_by_role("button", name="Clear person filter").click()
    expect(page).not_to_have_url(re.compile(r"user_id="))
    expect(page.get_by_role("button", name="Person: Anyone")).to_be_focused()
    page.get_by_role("button", name="Reset filters").first.click()
    expect(page).to_have_url(f"{ORIGIN}/v2/control-center/activity-logs")
    expect(page.get_by_label("Search activity")).to_be_focused()


def test_search_keeps_what_is_typed_while_the_url_updates(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    search = page.get_by_label("Search activity")
    search.press_sequentially("Ada ")
    expect(page).to_have_url(re.compile(r"search=Ada(&|$)"))
    # The URL's echo of "Ada" must not trim the space the administrator is still typing after.
    search.press_sequentially("Admin")
    expect(page).to_have_url(re.compile(r"search=Ada\+Admin"))
    expect(search).to_have_value("Ada Admin")
    assert activity_ui.page_queries()[-1]["search"] == ["Ada Admin"]
    page.get_by_role("button", name="Reset filters").first.click()
    expect(search).to_have_value("")


def test_pickers_offer_filtering_by_the_id_of_something_removed(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    page.get_by_role("button", name="Person: Anyone").click()
    picker = page.get_by_role("combobox", name="Find a person")
    picker.fill("user-9")
    expect(page.get_by_text("No SimpleChat user matches.")).to_be_visible()
    expect(page.get_by_role("option", name=re.compile("Filter by user ID"))).to_be_visible()
    picker.press("Enter")
    expect(page).to_have_url(re.compile(r"user_id=user-9"))
    expect(page.get_by_role("button", name="Person: user-9")).to_be_focused()
    page.get_by_role("button", name="Workspace: Any").click()
    page.get_by_role("combobox", name="Find a group or public workspace").fill("pub-77")
    expect(page.get_by_role("option", name=re.compile("Filter by group ID"))).to_be_visible()
    page.get_by_role("option", name=re.compile("Filter by public workspace ID")).click()
    expect(page).to_have_url(re.compile(r"workspace_type=public&workspace_id=pub-77"))
    expect(page.get_by_role("button", name="Public workspace: pub-77")).to_be_visible()
    latest = activity_ui.page_queries()[-1]
    assert latest["user_id"] == ["user-9"] and latest["workspace_id"] == ["pub-77"]
    page.get_by_role("button", name="Person: user-9").click()
    page.get_by_role("combobox", name="Find a person").fill("jane doe")
    expect(page.get_by_text("No SimpleChat user matches.")).to_be_visible()
    expect(page.get_by_role("option")).to_have_count(0)


def test_pills_edit_filters_with_keyboard_pickers(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    page.get_by_role("button", name="Person: Anyone").click()
    person = page.get_by_role("combobox", name="Find a person")
    expect(person).to_be_focused()
    person.fill("bo")
    expect(page.get_by_role("option", name=re.compile("Bo Builder"))).to_be_visible()
    person.press("Enter")
    expect(page).to_have_url(re.compile(r"user_id=user-3"))
    expect(page.get_by_role("button", name="Person: Bo Builder")).to_be_focused()

    page.get_by_role("button", name="Workspace: Any").click()
    page.get_by_role("group", name="Workspace type").get_by_role("button", name="Groups").click()
    expect(page).to_have_url(re.compile(r"workspace_type=group"))
    page.get_by_role("combobox", name="Find a group").fill("res")
    page.get_by_role("option", name=re.compile("Research")).click()
    expect(page).to_have_url(re.compile(r"workspace_id=group-1"))
    expect(page.get_by_role("button", name="Group: Research")).to_be_visible()

    page.get_by_role("button", name="Date: Last 30 days").click()
    page.get_by_role("button", name="Last 7 days").click()
    expect(page).to_have_url(re.compile(r"range=7"))
    assert activity_ui.page_queries()[-1]["start_date"] == [(_today() - timedelta(days=6)).isoformat()]
    page.get_by_role("button", name="Date: Last 7 days").click()
    page.get_by_role("button", name="Custom range").click()
    page.get_by_label("Start date (UTC)").fill("2026-09-10")
    page.get_by_label("End date (UTC)").fill("2026-09-01")
    page.get_by_role("button", name="Apply range").click()
    expect(page.get_by_text("The end date must be on or after the start date.")).to_be_visible()
    page.get_by_label("End date (UTC)").fill("2026-09-20")
    page.get_by_role("button", name="Apply range").click()
    expect(page).to_have_url(re.compile(r"start_date=2026-09-10&end_date=2026-09-20"))
    expect(page.get_by_role("button", name="Date: Sep 10 – Sep 20, 2026 (UTC)")).to_be_visible()

    page.get_by_role("button", name="Activity: All").click()
    page.get_by_label("Find an activity type").fill("login")
    page.get_by_role("checkbox", name=re.compile("User login")).check()
    expect(page).to_have_url(re.compile(r"activity_type=user_login"))
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Activity: User login")).to_be_focused()

    page.get_by_role("button", name="Add filter").click()
    page.get_by_role("button", name="Model").click()
    page.get_by_label("Model or deployment name").fill("gpt-4o")
    page.get_by_role("button", name="Apply", exact=True).click()
    expect(page).to_have_url(re.compile(r"model=gpt-4o"))
    # The added pill stays put while the URL catches up, and keeps keyboard focus.
    expect(page.get_by_role("button", name="Model: gpt-4o")).to_be_focused()
    latest = activity_ui.page_queries()[-1]
    assert latest["user_id"] == ["user-3"] and latest["model"] == ["gpt-4o"]

    page.get_by_role("button", name="Add filter").click()
    page.get_by_role("button", name="Token type").click()
    expect(page.get_by_role("dialog", name="Filter by token type")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name=re.compile(r"^Token type:"))).to_have_count(0)
    expect(page.get_by_role("button", name="Add filter")).to_be_focused()
    expect(page).not_to_have_url(re.compile(r"token_type="))


def test_deep_links_render_as_named_pills(activity_ui):
    activity_ui.open("?date=2026-10-01&activity_type=user_login&workspace_type=group&workspace_id=group-1&group_id=group-1&user_id=user-1")
    page = activity_ui.page
    expect(page.get_by_role("button", name="Date: Oct 1, 2026 (UTC)")).to_be_visible()
    expect(page.get_by_role("button", name="Activity: User login")).to_be_visible()
    expect(page.get_by_role("button", name="Group: Research")).to_be_visible()
    expect(page.get_by_role("button", name="Person: Ada Admin")).to_be_visible()
    latest = activity_ui.page_queries()[-1]
    assert latest["start_date"] == ["2026-10-01"] and latest["end_date"] == ["2026-10-01"]
    assert latest["workspace_type"] == ["group"] and latest["workspace_id"] == ["group-1"]


def test_trend_drill_through_keyboard_and_top_activity(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    first_bar = page.get_by_role("button", name=re.compile(r"^Sep 30 \(UTC\): 22 records"))
    first_bar.focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("button", name=re.compile(r"^Oct 1 \(UTC\): 20 records"))).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"start_date=2026-10-01&end_date=2026-10-01"))
    expect(page.get_by_role("button", name="Date: Oct 1, 2026 (UTC)")).to_be_focused()
    page.get_by_role("button", name=re.compile(r"^Token usage: 30 records")).click()
    expect(page).to_have_url(re.compile(r"activity_type=token_usage"))
    page.get_by_role("button", name="Hide trend").click()
    expect(page.get_by_role("toolbar", name=re.compile("Activity by UTC date"))).to_have_count(0)
    _eventually(page, lambda: activity_ui.settings.get("v2ActivityLogPrefs", {}).get("showTrend") is False)
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("button", name="Show trend")).to_be_visible()


def test_detail_drawer_reads_as_who_where_what(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    opener = page.get_by_role("button", name=re.compile(r"^Open details: Token usage, Ada Admin"))
    opener.click()
    drawer = page.get_by_role("dialog", name="Activity details")
    expect(drawer).to_be_visible()
    for heading in ("Who", "Where", "Details", "Record"):
        expect(drawer.get_by_role("heading", name=heading, exact=True)).to_be_visible()
    expect(drawer.get_by_text("12,345 tokens · gpt-4o")).to_be_visible()
    expect(drawer.get_by_role("link", name="Open in Users")).to_have_attribute("href", "/v2/control-center/users?user_id=user-1")
    expect(drawer.get_by_role("link", name="Open group")).to_have_attribute("href", "/v2/control-center/groups?id=group-1")
    expect(drawer.get_by_role("link", name="View approval")).to_have_attribute("href", "/v2/approvals/all/approval-1?group_id=group-1")
    expect(drawer.get_by_text("2026-10-01 12:00:00 UTC")).to_be_visible()
    drawer.get_by_text("Raw JSON", exact=True).click()
    expect(drawer.locator("pre")).to_contain_text("<img src=x onerror=alert(1)>")
    expect(page.locator("img[src=x]")).to_have_count(0)
    drawer.get_by_role("button", name="Next record").click()
    expect(drawer.get_by_text("Active → Locked")).to_be_visible()
    expect(drawer.get_by_text("Record 2 of 4 on this page")).to_be_visible()
    page.keyboard.press("Escape")
    expect(drawer).not_to_be_visible()
    expect(opener).to_be_focused()
    opener.click()
    page.get_by_role("dialog", name="Activity details").get_by_role("button", name="Show only this person's activity").click()
    expect(page).to_have_url(re.compile(r"user_id=user-1"))
    expect(page.get_by_role("dialog", name="Activity details")).not_to_be_visible()
    expect(page.get_by_role("button", name="Person: Ada Admin")).to_be_focused()


def test_times_default_to_local_and_the_utc_choice_is_remembered(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    expect(page.get_by_role("table").get_by_text(re.compile(r"^Oct 1, 8:00:00\sAM$"))).to_be_visible()
    page.get_by_role("group", name="Show times in").get_by_role("button", name="UTC").click()
    expect(page.get_by_role("table").get_by_text("2026-10-01 12:00:00 UTC", exact=True)).to_be_visible()
    page.get_by_role("group", name="Row density").get_by_role("button", name="Compact").click()
    _eventually(page, lambda: activity_ui.settings.get("v2ActivityLogPrefs") == {
        "timeZone": "utc", "density": "compact", "showTrend": True})
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("table").get_by_text("2026-10-01 12:00:00 UTC", exact=True)).to_be_visible()
    expect(page.get_by_role("group", name="Row density").get_by_role("button", name="Compact")).to_have_attribute("aria-pressed", "true")


def test_saved_views_move_to_the_account_and_quick_views_apply(activity_ui):
    legacy = json.dumps([{"name": "Old view", "query": "start_date=2026-09-01&end_date=2026-09-30&activity_type=user_login"}])
    activity_ui.page.add_init_script(
        "if (!sessionStorage.getItem('seeded')) {"
        f" localStorage.setItem('simplechat.activity-views.admin-1', {json.dumps(legacy)});"
        " sessionStorage.setItem('seeded', '1'); }"
    )
    activity_ui.open()
    page = activity_ui.page
    page.wait_for_function("() => localStorage.getItem('simplechat.activity-views.admin-1') === null")
    assert [view["name"] for view in activity_ui.settings["v2ActivityLogSavedViews"]] == ["Old view"]

    page.get_by_role("button", name="Views").click()
    menu = page.get_by_role("dialog", name="Activity views")
    expect(menu.get_by_text("Saved to your account", exact=False)).to_be_visible()
    menu.get_by_role("button", name="Old view", exact=True).click()
    expect(page).to_have_url(re.compile(r"start_date=2026-09-01&end_date=2026-09-30&activity_type=user_login"))

    page.get_by_role("button", name="Views").click()
    menu = page.get_by_role("dialog", name="Activity views")
    menu.get_by_role("button", name="Recent sign-ins").click()
    expect(page).to_have_url(re.compile(r"range=7&activity_type=user_login"))

    page.get_by_role("button", name="Views").click()
    menu = page.get_by_role("dialog", name="Activity views")
    menu.get_by_label("Save the current filters as").fill("Weekly sign-ins")
    menu.get_by_role("button", name="Save view").click()

    def saved():
        return {view["name"]: view["query"] for view in activity_ui.settings.get("v2ActivityLogSavedViews", [])}

    _eventually(page, lambda: saved().get("Weekly sign-ins") == "range=7&activity_type=user_login")
    menu.get_by_role("button", name="Rename saved view Weekly sign-ins").click()
    menu.get_by_role("textbox", name="New name for Weekly sign-ins").fill("Sign-ins this week")
    menu.get_by_role("button", name="Save the new name for Weekly sign-ins").click()
    menu.get_by_role("button", name="Delete saved view Old view").click()
    _eventually(page, lambda: list(saved()) == ["Sign-ins this week"])
    page.reload(wait_until="networkidle")
    assert page.evaluate("localStorage.getItem('simplechat.activity-views.admin-1')") is None


def test_saved_views_are_locked_when_settings_cannot_load(activity_ui):
    """A save built on views that never loaded would replace the account's real views."""
    activity_ui.settings_fail = True
    activity_ui.page.add_init_script(
        "localStorage.setItem('simplechat.activity-views.admin-1',"
        " JSON.stringify([{name: 'Local view', query: 'range=7'}]));"
    )
    activity_ui.open()
    page = activity_ui.page
    page.get_by_role("button", name="Views").click()
    menu = page.get_by_role("dialog", name="Activity views")
    expect(menu.get_by_text("Your saved views could not be loaded.", exact=False)).to_be_visible()
    expect(menu.get_by_label("Save the current filters as")).to_have_count(0)
    menu.get_by_role("button", name="Recent sign-ins").click()
    expect(page).to_have_url(re.compile(r"range=7&activity_type=user_login"))
    assert not activity_ui.settings_posts
    assert page.evaluate("localStorage.getItem('simplechat.activity-views.admin-1')") is not None


def test_relative_ranges_follow_the_clock_on_refresh_and_export(activity_ui):
    page = activity_ui.page
    page.clock.set_fixed_time(datetime(2026, 10, 7, 23, 59, 30, tzinfo=timezone.utc))
    activity_ui.open("?range=today")
    expect(page.get_by_role("button", name="Date: Today")).to_be_visible()
    first = activity_ui.page_queries()[-1]
    assert first["start_date"] == first["end_date"] == ["2026-10-07"]

    page.clock.set_fixed_time(datetime(2026, 10, 8, 0, 0, 30, tzinfo=timezone.utc))
    page.get_by_role("button", name="Refresh", exact=True).click()
    _eventually(page, lambda: activity_ui.page_queries()[-1]["start_date"] == ["2026-10-08"],
                message="Refresh kept querying the previous UTC day.")
    assert activity_ui.page_queries()[-1]["end_date"] == ["2026-10-08"]

    page.clock.set_fixed_time(datetime(2026, 10, 9, 0, 0, 30, tzinfo=timezone.utc))
    with page.expect_download():
        page.get_by_role("button", name="Export CSV", exact=True).click()
    export_query = [parse_qs(query) for _, path, query in activity_ui.requests if path.endswith("export.csv")][-1]
    assert export_query["start_date"] == export_query["end_date"] == ["2026-10-09"]
    _eventually(page, lambda: activity_ui.page_queries()[-1]["start_date"] == ["2026-10-09"],
                message="The log did not move to the new UTC day after the export.")


def test_paging_export_empty_error_and_permission_gating(activity_ui):
    activity_ui.open()
    page = activity_ui.page
    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.get_by_role("button", name="Show only activity by Bo Builder")).to_be_visible()
    assert activity_ui.page_queries()[-1]["cursor"] == ["test-cursor"]
    page.get_by_role("button", name="Previous", exact=True).click()
    expect(page.get_by_role("button", name="Show only activity by Ada Admin").first).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("button", name="Export CSV", exact=True).click()
    assert download.value.suggested_filename == "activity_logs.csv"
    export_query = [parse_qs(query) for _, path, query in activity_ui.requests if path.endswith("export.csv")][-1]
    assert export_query["start_date"] == [(_today() - timedelta(days=29)).isoformat()]

    activity_ui.empty = True
    page.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.get_by_text("No activity matches these filters.")).to_be_visible()
    page.get_by_role("button", name="Widen to the last 90 days").click()
    expect(page).to_have_url(re.compile(r"range=90"))
    activity_ui.empty = False
    activity_ui.fail = True
    page.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    activity_ui.fail = False
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Show only activity by Ada Admin").first).to_be_visible()

    activity_ui.allowed = False
    activity_ui.requests.clear()
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("heading", name="Access unavailable")).to_be_visible()
    assert not activity_ui.requests


def test_mobile_layout_stacks_rows_without_overflow(activity_ui):
    activity_ui.open(mobile=True)
    page = activity_ui.page
    expect(page.get_by_role("button", name="Date: Last 30 days")).to_be_visible()
    expect(page.get_by_role("list", name="Activity records, newest first")).to_be_visible()
    expect(page.get_by_role("table")).to_have_count(0)
    page.get_by_role("button", name=re.compile(r"^Open details: Token usage, Ada Admin")).click()
    expect(page.get_by_role("dialog", name="Activity details")).to_be_visible()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Show only activity by Ada Admin").first.click()
    expect(page).to_have_url(re.compile(r"user_id=user-1"))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
