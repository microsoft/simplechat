# test_v2_workflow_run_tracker_spa.py
"""
UI test for the V2 app-shell workflow run tracker in the real production SPA.
Version: 0.261.239
Implemented in: 0.261.239

This test ensures that the one run tracker the V2 app shell owns starts and stops at the right
moments in the real built SPA, served from `application/single_app/static/v2` with every server
route stubbed at the network layer:

- it never reads run status before the app has started, or after the app failed to start, even
  when a later bootstrap refresh succeeds behind the error page;
- it never reads run status when the feature flags are off, and the chat keeps Phase 5's static
  run links;
- moving between pages never starts a second tracker;
- a delivery that lands during the page session raises one desktop notification and marks that
  chat unread, and a reload never announces it again.

Refs #1546 (Phase 6), #1543 (Chat Orchestration Workflows), #1610 (6b-1, the server half).

Build the SPA first:
npm --prefix .\\application\\v2_ui run build
Run: python -m pytest .\\ui_tests\\test_v2_workflow_run_tracker_spa.py -q
"""

import copy
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONAL_TESTS = ROOT / "functional_tests"
for _entry in (ROOT, FUNCTIONAL_TESTS, ROOT / "ui_tests" / "fixtures"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.fixtures.workflow_editor import SPA_INDEX, WORKFLOW_ID  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ORIGIN, OWNER_ID, STATIC_ROOT  # noqa: E402
from ui_tests.test_v2_notifications_bell import FAKE_BROWSER  # noqa: E402
from ui_tests.test_v2_orchestration_workflow_run_links import (  # noqa: E402
    FOOTNOTE,
    SPA_CHAT_ID,
    SPA_HREF,
    SPA_RUN_ID,
    SPA_WORKFLOW_NAME,
    SPA_WORKFLOW_RUN_ID,
    ChatRunLinksFixture,
)
from ui_tests.test_v2_workflow_run_card import delivered, status_row  # noqa: E402


pytestmark = pytest.mark.ui

IMPLEMENTED_IN = "0.261.239"
STATUS_PATH = "/api/v2/orchestration/workflow-runs/status"
BOOTSTRAP_PATH = "/api/v2/bootstrap"
CHAT_PATH = f"/chat?conversationId={SPA_CHAT_ID}"
CHECKED_AT = datetime(2026, 1, 5, 9, 10, 0, tzinfo=timezone.utc)

DIGEST_CHAT = "digest-chat"
DIGEST_TITLE = "Weekly digest chat"
DIGEST_RUN = "digest-run"
DIGEST_NAME = "Weekly digest"
BUDGET_CHAT = "budget-chat"
BUDGET_TITLE = "Budget review"
BUDGET_RUN = "budget-run"
BUDGET_NAME = "Monthly budget"

# Hide the page and show it again without moving focus, so the tracker checks again at once.
RECHECK = """() => {
    const env = window.__harnessEnv;
    env.visible = false;
    document.dispatchEvent(new Event('visibilitychange'));
    env.visible = true;
    document.dispatchEvent(new Event('visibilitychange'));
}"""
NOTIFICATIONS = "() => window.Notification.instances.map(({title, body, tag}) => ({title, body, tag}))"


def require_fresh_bundle():
    """The build check the fixture's open() makes, for loads that can't wait for network idle."""
    if not SPA_INDEX.is_file():
        pytest.fail("Build the real V2 SPA before running the run tracker UI tests.")
    expected_js = os.getenv("SIMPLECHAT_UI_EXPECTED_JS", "")
    expected_css = os.getenv("SIMPLECHAT_UI_EXPECTED_CSS", "")
    if expected_js or expected_css:
        if not expected_js or not expected_css:
            pytest.fail("Set both SIMPLECHAT_UI_EXPECTED_JS and SIMPLECHAT_UI_EXPECTED_CSS.")
        index = SPA_INDEX.read_text(encoding="utf-8")
        for filename, attribute, suffix in ((expected_js, "src", "js"), (expected_css, "href", "css")):
            if not re.fullmatch(rf"[A-Za-z0-9_.-]+\.{suffix}", filename):
                pytest.fail("Expected build assets must be local filenames.")
            asset = STATIC_ROOT / "v2" / "assets" / filename
            reference = f"/static/v2/assets/{filename}"
            if not asset.is_file() or not re.search(rf'{attribute}=["\']{re.escape(reference)}["\']', index):
                pytest.fail("The explicitly released SPA assets are missing or have changed.")
        return
    built = SPA_INDEX.stat().st_mtime
    source_root = ROOT / "application" / "v2_ui" / "src"
    if any(source.stat().st_mtime > built for source in source_root.rglob("*") if source.is_file()):
        pytest.fail("The production V2 bundle is stale; rebuild it before running this suite.")


def wait_for(page, predicate, message, timeout=10):
    """Poll a fixture-side condition. Route handlers only run during Playwright calls."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail(message)
        page.wait_for_timeout(50)


def running_tag(page, label):
    return page.get_by_role("img", name=label, exact=True)


def rail_row(page, title):
    return page.locator("li").filter(has=page.get_by_role("button", name=f"Actions for {title}", exact=True))


def unread_dot(page, title):
    return rail_row(page, title).locator('span[aria-label="Unread"]')


def digest_row(status="running", **overrides):
    """The run another chat started, as 6b-1's status route projects it."""
    return status_row(
        status, conversation=DIGEST_CHAT, run=DIGEST_RUN, step="digest-step", orun="digest-orun",
        name=DIGEST_NAME, workflow_id=WORKFLOW_ID, **overrides,
    )


class TrackerSpaFixture(ChatRunLinksFixture):
    """The real chat page whose plan started a saved workflow, with 6b-1's status route."""

    def __init__(self, page):
        super().__init__(page)
        self.tracker_flags = True
        self.desktop_notifications = False
        self.hold_bootstrap = False
        self.status_rows = []
        self.status_served = 0
        for identifier, title, updated in (
            (DIGEST_CHAT, DIGEST_TITLE, "2026-09-05T11:00:00Z"),
            (BUDGET_CHAT, BUDGET_TITLE, "2026-09-05T10:00:00Z"),
        ):
            self.conversations.append({
                "id": identifier, "title": title, "user_id": OWNER_ID, "last_updated": updated,
            })
            self.messages[identifier] = [{
                "id": f"{identifier}-message", "role": "user", "content": f"An earlier message in {title}.",
                "conversation_id": identifier, "timestamp": updated,
            }]

    def _bootstrap(self):
        payload = super()._bootstrap()
        if self.tracker_flags:
            payload["features"].update({
                "allow_user_workflows": True, "enable_chat_orchestration_workflow_runs": True,
            })
        if self.desktop_notifications:
            payload["features"]["enable_desktop_notifications"] = True
        return payload

    def _dispatch(self, route, entry):
        if entry.method == "GET" and entry.path == BOOTSTRAP_PATH and self.hold_bootstrap:
            self.pending_responses.append((route, entry))
        elif entry.method == "GET" and entry.path == STATUS_PATH:
            self._status(route, entry)
        else:
            super()._dispatch(route, entry)

    def _status(self, route, entry):
        """Answer the batched status read: one chat's runs, or every run still worth tracking."""
        if set(entry.query) - {"conversation_id"} or len(entry.query.get("conversation_id", [])) > 1:
            self.unexpected_requests.append(f"GET {entry.path} {entry.query}")
        conversation = (entry.query.get("conversation_id") or [None])[0]
        runs = [row for row in self.status_rows if conversation in (None, row["conversation_id"])]
        checked_at = self.next_checked_at()
        self.status_served += 1
        self._json(route, {
            "available": True, "runs": copy.deepcopy(runs), "checked_at": checked_at, "truncated": False,
        })

    def next_checked_at(self):
        """The `checked_at` the next status read answers with: one second later per read."""
        moment = CHECKED_AT + timedelta(seconds=self.status_served)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def status_requests(self):
        return [entry for entry in self.requests if entry.method == "GET" and entry.path == STATUS_PATH]

    @property
    def global_reads(self):
        return [entry for entry in self.status_requests if entry.query == {}]

    @property
    def bootstrap_requests(self):
        return [entry for entry in self.requests if entry.method == "GET" and entry.path == BOOTSTRAP_PATH]

    @property
    def held_bootstraps(self):
        return [entry for _, entry in self.pending_responses if entry.path == BOOTSTRAP_PATH]

    def load(self, path, *, font_size="m"):
        """Open a page without waiting for network idle, so a held response can't stall the load."""
        require_fresh_bundle()
        self.preferences.update({
            "darkModeEnabled": False, "v2RailCollapsed": False, "v2WorkspaceRailCollapsed": False,
            "fontSizePreference": font_size,
        })
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(f"{ORIGIN}/v2{path}", wait_until="commit")

    def assert_real_spa(self):
        assert any(path.endswith(".js") for path in self.loaded_assets), "Real SPA JavaScript was not loaded."
        assert any(path.endswith(".css") for path in self.loaded_assets), "Production CSS was not loaded."


@pytest.fixture
def tracker_ui(page):
    fixture = TrackerSpaFixture(page)
    yield fixture
    fixture.assert_clean()


def test_the_tracker_waits_for_the_app_to_start(tracker_ui):
    """While the bootstrap is still loading, nothing reads run status; once it loads, one read does."""
    ui = tracker_ui
    page = ui.page
    ui.hold_bootstrap = True
    ui.load(CHAT_PATH)
    wait_for(page, lambda: ui.held_bootstraps, "The app never asked for its bootstrap.")
    page.wait_for_timeout(1000)
    assert not ui.status_requests, [entry.query for entry in ui.status_requests]

    ui.hold_bootstrap = False
    ui.release_responses()
    expect(page.get_by_role("region", name="Started workflows", exact=True)).to_be_visible()
    wait_for(page, lambda: ui.global_reads, "The tracker never read run status after the app started.")
    page.wait_for_timeout(1000)
    assert len(ui.global_reads) == 1, ui.global_reads
    ui.assert_real_spa()


def test_the_tracker_stays_off_after_the_app_fails_to_start(tracker_ui):
    """A bootstrap refresh that succeeds behind the error page never starts the tracker."""
    ui = tracker_ui
    page = ui.page
    ui.reject_next("GET", BOOTSTRAP_PATH, status=503)
    ui.load(CHAT_PATH)
    heading = page.get_by_role("heading", name="Could not start SimpleChat", exact=True)
    expect(heading).to_be_visible()

    # The app refreshes its bootstrap when the window gains focus; that refresh succeeds here.
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")
    wait_for(page, lambda: len(ui.bootstrap_requests) >= 2, "The app never refreshed its bootstrap.")
    page.wait_for_timeout(1000)
    expect(heading).to_be_visible()
    assert not ui.status_requests, [entry.query for entry in ui.status_requests]
    ui.assert_real_spa()


def test_flags_off_keeps_phase_5_links_and_reads_no_status(tracker_ui):
    """Without both feature flags the answer keeps its static run links, and nothing polls."""
    ui = tracker_ui
    page = ui.page
    ui.tracker_flags = False
    ui.open(CHAT_PATH)
    region = page.get_by_role("region", name="Started workflows", exact=True)
    expect(region).to_be_visible()
    expect(region).to_contain_text(FOOTNOTE)
    expect(region.get_by_role("link", name=f"Open run of {SPA_WORKFLOW_NAME}", exact=True)).to_have_attribute(
        "href", f"/v2{SPA_HREF}",
    )
    expect(region.get_by_role("button", name="Check now", exact=True)).to_have_count(0)
    assert ui.link_reads == [{"conversation_id": [SPA_CHAT_ID]}]
    page.wait_for_timeout(1000)
    assert not ui.status_requests, [entry.query for entry in ui.status_requests]


def test_moving_between_pages_never_starts_a_second_tracker(tracker_ui):
    """Following the run link and coming back re-reads the chat's runs but never restarts the tracker."""
    ui = tracker_ui
    page = ui.page
    ui.status_rows = [status_row(
        "completed", conversation=SPA_CHAT_ID, run=SPA_WORKFLOW_RUN_ID, step="run_review", orun=SPA_RUN_ID,
        name=SPA_WORKFLOW_NAME, workflow_id=WORKFLOW_ID,
        delivery=delivered(run=SPA_WORKFLOW_RUN_ID, conversation=SPA_CHAT_ID),
    )]
    ui.open(CHAT_PATH)
    region = page.get_by_role("region", name="Started workflows", exact=True)
    expect(region).to_contain_text("Results were posted to this chat.")
    expect(region).to_contain_text("Checked")
    page.wait_for_timeout(1000)
    assert len(ui.global_reads) == 1, ui.global_reads

    link = region.get_by_role("link", name=f"Open run of {SPA_WORKFLOW_NAME}", exact=True)
    link.focus()
    page.keyboard.press("Enter")
    expect(page).to_have_url(f"{ORIGIN}/v2{SPA_HREF}")
    history = page.get_by_role("list", name="Workflow run history", exact=True)
    expect(history.locator('li[aria-current="true"]')).to_have_count(1)

    page.go_back()
    expect(page).to_have_url(f"{ORIGIN}/v2{CHAT_PATH}")
    region = page.get_by_role("region", name="Started workflows", exact=True)
    expect(region).to_contain_text("Results were posted to this chat.")
    page.wait_for_timeout(1000)
    assert len(ui.global_reads) == 1, ui.global_reads
    assert not [entry for entry in ui.writes if entry.path != "/api/user/settings"], ui.writes


def test_a_delivery_is_announced_once_and_never_again_after_a_reload(tracker_ui):
    """A delivery seen landing raises one notification and an unread dot; a reload repeats neither."""
    ui = tracker_ui
    page = ui.page
    ui.desktop_notifications = True
    ui.preferences["desktopNotificationsEnabled"] = True
    # The open chat is a plain one, so the only status reads are the tracker's own.
    ui.messages[SPA_CHAT_ID] = [{
        "id": "spa-user", "role": "user", "content": "A plain question.",
        "conversation_id": SPA_CHAT_ID, "timestamp": "2026-09-16T11:59:00Z",
    }]
    # The window is visible but not focused, so the page isn't being watched.
    page.add_init_script(script=f"({FAKE_BROWSER})({json.dumps({'visible': True, 'focused': False})})")
    ui.status_rows = [digest_row(delivery={"status": "pending"})]
    # A non-default font size proves the user's settings loaded; the notification needs them.
    ui.load(CHAT_PATH, font_size="l")
    expect(page.locator("html")).to_have_attribute("data-font-size", "l")
    expect(rail_row(page, DIGEST_TITLE).get_by_role("img", name=f"Running {DIGEST_NAME}", exact=True)).to_be_visible()
    ui.assert_real_spa()

    ui.status_rows = [digest_row(
        "completed",
        delivery=delivered(run=DIGEST_RUN, conversation=DIGEST_CHAT, generation=1, at=ui.next_checked_at()),
    )]
    page.evaluate(RECHECK)
    wait_for(page, lambda: page.evaluate(NOTIFICATIONS), "The delivery raised no desktop notification.")
    expect(unread_dot(page, DIGEST_TITLE)).to_have_count(1)
    expect(running_tag(page, f"Running {DIGEST_NAME}")).to_have_count(0)
    page.wait_for_timeout(300)
    notifications = page.evaluate(NOTIFICATIONS)
    assert notifications == [{
        "title": "SimpleChat", "body": DIGEST_TITLE, "tag": f"simplechat-conversation-{DIGEST_CHAT}",
    }]

    # The real server marks the digest chat unread too. The fixture leaves the flag off, so any
    # unread dot after the reload can only come from the client settling the delivery again.
    ui.status_rows.append(status_row(
        "running", conversation=BUDGET_CHAT, run=BUDGET_RUN, step="budget-step", orun="budget-orun",
        name=BUDGET_NAME, workflow_id=WORKFLOW_ID, delivery={"status": "pending"},
    ))
    ui.defer_next("GET", STATUS_PATH)
    page.reload(wait_until="commit")
    expect(page.locator("html")).to_have_attribute("data-font-size", "l")
    expect(rail_row(page, DIGEST_TITLE)).to_have_count(1)
    wait_for(page, lambda: ui.pending_responses, "The tracker never read run status after the reload.")
    held = [entry for _, entry in ui.pending_responses]
    assert [(entry.path, entry.query) for entry in held] == [(STATUS_PATH, {})], held
    ui.release_responses()
    # The first read after the reload landed: it shows the other chat's run in flight.
    expect(rail_row(page, BUDGET_TITLE).get_by_role("img", name=f"Running {BUDGET_NAME}", exact=True)).to_be_visible()
    page.wait_for_timeout(500)
    notifications = page.evaluate(NOTIFICATIONS)
    assert notifications == []
    expect(unread_dot(page, DIGEST_TITLE)).to_have_count(0)


def test_tracker_spa_version_is_at_least_the_implementation():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
