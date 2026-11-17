# test_v2_notifications_page.py
"""
Browser regressions for the V2 Notifications page: filters, search, numbered paging and the
entry points that lead to it.
Version: 0.261.448
Implemented in: 0.261.448

Classic's `/notifications` page filters and searches only the page it has fetched, so its totals
and page links describe the wrong list. The V2 page sends the read filter and the search to the
server with the page it asks for, and the server applies them before it pages. These tests run
the real rail, bell panel, account menu, Notifications page, stores and notification runtime,
bundled by fixtures/notifications_page, in a browser router with the application's `/v2` base.
Only HTTP answers are replaced, and the stand-in server answers the way
route_backend_notifications.py does: it filters and searches the whole list, then pages it.
The existing Azure Playwright connection fixture also supports a local browser; no live
application data is read or modified.
"""

import copy
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Imported through the package: a bare `harness_build` would collide with the orchestration
# fixture module of the same name when both suites run in one session.
from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.fixtures.v2_notification_stubs import (  # noqa: E402
    notification_count_payload,
    workflow_alert_document,
)


pytestmark = pytest.mark.ui

FIXTURE = ROOT / "ui_tests" / "fixtures" / "notifications_page"
BUNDLE = FIXTURE / "harness.bundle.js"
V2_SOURCE = ROOT / "application" / "v2_ui" / "src"
STATIC = ROOT / "application" / "single_app" / "static"
# What draws the page, the entry points to it and the controls they share.
WATCHED_SOURCES = [
    *sorted((V2_SOURCE / "components" / "notifications").glob("*.tsx")),
    *sorted((V2_SOURCE / "styles").glob("*.css")),
    V2_SOURCE / "pages" / "NotificationsPage.tsx",
    V2_SOURCE / "lib" / "notificationsPage.ts",
    V2_SOURCE / "lib" / "useNotificationsList.ts",
    V2_SOURCE / "components" / "layout" / "Sidebar.tsx",
    V2_SOURCE / "components" / "layout" / "NotificationPanel.tsx",
    V2_SOURCE / "components" / "layout" / "NotificationBell.tsx",
    V2_SOURCE / "components" / "layout" / "PageHeader.tsx",
    V2_SOURCE / "components" / "layout" / "HeaderActions.tsx",
    V2_SOURCE / "components" / "ui" / "primitives.tsx",
    V2_SOURCE / "components" / "workspace" / "primitives.tsx",
]
# A secure context, as every deployment is.
ORIGIN = "https://simplechat.test"
BASE_TIME = datetime(2025, 6, 2, 15, 0, tzinfo=timezone.utc)
CLASSIC_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Classic page</title></head>'
    "<body><h1>Classic interface</h1></body></html>"
)
XSS_TITLE = '<img src=x onerror="window.__xss=1">Quoted subject'
XSS_MESSAGE = '<b>Quoted mail</b> & <script>window.__xss=2</script>'
SEARCH_MAX_LENGTH = 100


def iso(moment):
    return moment.isoformat()


def notice(notice_id, title, message="", *, notification_type="system_announcement", link_url="",
           link_context=None, metadata=None, read=False, color="secondary", icon="bi-bell", **extra):
    """A notification document as route_backend_notifications.api_get_notifications returns it."""
    record = {
        "id": notice_id,
        "user_id": "user-1",
        "notification_type": notification_type,
        "title": title,
        "message": message,
        "link_url": link_url,
        "link_context": dict(link_context or {}),
        "metadata": dict(metadata or {}),
        "is_read": read,
        "is_dismissed": False,
        "type_config": {"icon": icon, "color": color},
    }
    record.update(extra)
    return record


def document_notice(notice_id="n-doc", *, read=False, title="Document ready: Q3 forecast.pdf"):
    return notice(
        notice_id, title, "Q3 forecast.pdf finished processing and is ready to search.",
        notification_type="document_processing_complete", link_url="/workspace?document_id=doc-1",
        link_context={"workspace_type": "personal", "document_id": "doc-1"},
        read=read, color="success", icon="bi-file-earmark-check",
    )


def ledger_notice(notice_id, *, in_title=True, read=False):
    """A notice that mentions "ledger" in its title or only in its message."""
    if in_title:
        return notice(notice_id, f"Ledger export {notice_id} is ready", "The export finished.", read=read)
    return notice(notice_id, f"Budget workbook {notice_id}", "Your ledger export finished.", read=read)


def plain_notice(number, *, read=False):
    return notice(f"n-{number:03d}", f"Announcement {number:03d}", f"Details for announcement {number:03d}.", read=read)


def acknowledgment_alert(notice_id="n-ack", *, link=True, acknowledged=False):
    alert = workflow_alert_document(
        notice_id, created_at=iso(BASE_TIME + timedelta(hours=3)), title="Nightly scan failed",
        category="failure", require_acknowledgment=True, sound="repeat", size="large",
        acknowledged=acknowledged,
    )
    if not link:
        alert["link_url"] = ""
        alert["link_context"] = {}
    return alert


class NotificationsApi:
    """The routes the page calls, answered the way route_backend_notifications.py answers them."""

    def __init__(self, page):
        self.page = page
        self.notices = []
        self.requests = []
        self.list_queries = []
        self.read_calls = []
        self.dismiss_calls = []
        self.acknowledge_calls = []
        self.mark_all_calls = 0
        # The answer to Mark all read waits here while this is set, as a slow server's would.
        self.hold_mark_all = False
        self.held_mark_all = []
        self.settings_posts = []
        self.fail_next = set()
        # Every list read fails while this is set. A one-shot failure would be spent on the first of
        # the two reads React's development mode makes when the page mounts.
        self.list_failure = False
        self.hold_lists = False
        self.held_lists = []
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()
        self._created = 0

    # Server state -----------------------------------------------------------------------------

    def add(self, *records):
        """Store notices; each one added is newer than the one before it."""
        for record in records:
            if "created_at" not in record:
                self._created += 1
                record["created_at"] = iso(BASE_TIME + timedelta(minutes=self._created))
            self.notices.append(record)

    def find(self, notice_id):
        return next((record for record in self.notices if record["id"] == notice_id), None)

    def unread(self):
        return [record for record in self.notices if not record["is_read"] and not record["is_dismissed"]]

    def listed(self, status="all", query="", include_read=True, include_dismissed=False):
        """The whole filtered list, newest first: the filter and the search come before the paging."""
        items = [
            record for record in self.notices
            if (include_dismissed or not record["is_dismissed"]) and (include_read or not record["is_read"])
        ]
        if status == "unread":
            items = [record for record in items if not record["is_read"]]
        elif status == "read":
            items = [record for record in items if record["is_read"]]
        needle = query.strip()[:SEARCH_MAX_LENGTH].strip().casefold()
        if needle:
            items = [
                record for record in items
                if needle in record["title"].casefold() or needle in record["message"].casefold()
            ]
        return sorted(items, key=lambda record: record["created_at"], reverse=True)

    # Routing ----------------------------------------------------------------------------------

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        method = request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(f"{method} {request.url}")
            route.abort()
            return
        path = parsed.path
        self.requests.append((method, f"{path}?{parsed.query}" if parsed.query else path))
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        for answer in (self.page_route, self.notification_route):
            if answer(route, method, path, query):
                return
        self.unexpected.append(f"{method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def page_route(self, route, method, path, query):
        if method != "GET":
            return False
        if path == "/v2" or path.startswith("/v2/"):
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        elif path.startswith("/view_pdf"):
            route.fulfill(content_type="text/html", body=CLASSIC_PAGE)
        elif path.startswith("/static/"):
            asset = (STATIC / unquote(path.removeprefix("/static/"))).resolve()
            if not (asset.is_relative_to(STATIC.resolve()) and asset.is_file()):
                return False
            route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        else:
            return False
        return True

    def notification_route(self, route, method, path, query):
        if method == "GET" and path == "/api/notifications/count":
            # get_unread_notification_count caps the count at 10.
            route.fulfill(json=notification_count_payload(min(len(self.unread()), 10)))
        elif method == "GET" and path == "/api/notifications":
            self.answer_list(route, query)
        elif method == "POST" and path == "/api/notifications/mark-all-read":
            self.answer_mark_all(route, path)
        elif method == "POST" and path == "/api/notifications/settings":
            self.answer_settings(route, path)
        elif method == "POST" and (match := re.fullmatch(r"/api/notifications/([^/]+)/read", path)):
            self.answer_change(route, path, unquote(match.group(1)), "read")
        elif method == "DELETE" and (match := re.fullmatch(r"/api/notifications/([^/]+)/dismiss", path)):
            self.answer_change(route, path, unquote(match.group(1)), "dismiss")
        elif method == "POST" and (match := re.fullmatch(r"/api/notifications/([^/]+)/acknowledge", path)):
            self.answer_acknowledge(route, unquote(match.group(1)))
        else:
            return False
        return True

    # Answers ----------------------------------------------------------------------------------

    def fail(self, route, path, name, status=500, message="Internal server error"):
        if name not in self.fail_next:
            return False
        self.fail_next.discard(name)
        self.expected_http_failures.add((path, status))
        route.fulfill(status=status, json={"success": False, "error": message})
        return True

    def answer_list(self, route, query):
        self.list_queries.append(query)
        if self.list_failure:
            self.expected_http_failures.add(("/api/notifications", 500))
            route.fulfill(status=500, json={"success": False, "error": "Failed to fetch notifications"})
            return
        status = query.get("status", "all")
        if status not in ("all", "unread", "read"):
            self.expected_http_failures.add(("/api/notifications", 400))
            route.fulfill(status=400, json={"success": False, "error": "Invalid status. Use all, unread or read."})
            return
        page_number = int(query.get("page", 1))
        per_page = int(query.get("per_page", 20))
        if per_page not in (10, 20, 50):
            per_page = 20
        items = self.listed(
            status, query.get("q", ""),
            include_read=query.get("include_read", "true") == "true",
            include_dismissed=query.get("include_dismissed") == "true",
        )
        start = (page_number - 1) * per_page
        payload = {
            "success": True,
            "notifications": copy.deepcopy(items[start:start + per_page]),
            "total": len(items),
            "page": page_number,
            "per_page": per_page,
            "has_more": start + per_page < len(items),
        }
        if self.hold_lists:
            self.held_lists.append((route, payload, query))
        else:
            route.fulfill(json=payload)

    def release_lists(self, order=None):
        """Answer the held list reads, in `order` when it is given, as a slow server would."""
        assert self.held_lists, "No list request was held."
        held, self.held_lists = self.held_lists, []
        for index in order or range(len(held)):
            route, payload, _ = held[index]
            try:
                route.fulfill(json=payload)
            except Exception:  # noqa: BLE001 - the page cancels a read it no longer wants
                pass

    def answer_change(self, route, path, notice_id, change):
        (self.read_calls if change == "read" else self.dismiss_calls).append(notice_id)
        message = "Failed to mark notification as read" if change == "read" else "Failed to dismiss notification"
        record = self.find(notice_id)
        if self.fail(route, path, change, status=400, message=message) or record is None:
            if record is None:
                self.expected_http_failures.add((path, 400))
                route.fulfill(status=400, json={"success": False, "error": message})
            return
        if change == "read":
            record["is_read"] = True
            route.fulfill(json={"success": True, "message": "Notification marked as read"})
        else:
            record["is_dismissed"] = True
            route.fulfill(json={"success": True, "message": "Notification dismissed"})

    def answer_acknowledge(self, route, notice_id):
        self.acknowledge_calls.append(notice_id)
        record = self.find(notice_id)
        path = f"/api/notifications/{notice_id}/acknowledge"
        if self.fail(route, path, "acknowledge") or record is None:
            if record is None:
                self.expected_http_failures.add((path, 404))
                route.fulfill(status=404, json={"success": False, "error": "Alert not found."})
            return
        record["acknowledged"] = True
        record["acknowledged_at"] = iso(BASE_TIME + timedelta(hours=4))
        record["acknowledged_by_name"] = "Riley Chen"
        record["is_read"] = True
        route.fulfill(json={
            "success": True, "notification_id": notice_id, "acknowledged_at": record["acknowledged_at"],
            "acknowledged_by_name": "Riley Chen", "already_acknowledged": False,
        })

    def answer_mark_all(self, route, path):
        self.mark_all_calls += 1
        if self.fail(route, path, "mark_all"):
            return
        if self.hold_mark_all:
            self.held_mark_all.append(route)
            return
        self.finish_mark_all(route)

    def finish_mark_all(self, route):
        unread = self.unread()
        for record in unread:
            record["is_read"] = True
        route.fulfill(json={"success": True, "message": f"{len(unread)} notifications marked as read", "count": len(unread)})

    def release_mark_all(self):
        """Answer the held Mark all read requests."""
        assert self.held_mark_all, "No Mark all read request was held."
        held, self.held_mark_all = self.held_mark_all, []
        for route in held:
            self.finish_mark_all(route)

    def answer_settings(self, route, path):
        body = route.request.post_data_json or {}
        self.settings_posts.append(body)
        if self.fail(route, path, "settings"):
            return
        if body.get("notifications_per_page") not in (10, 20, 50):
            self.expected_http_failures.add((path, 400))
            route.fulfill(status=400, json={"success": False, "error": "Invalid per_page value. Must be 10, 20, or 50."})
            return
        route.fulfill(json={"success": True, "message": "Settings updated"})

    # Asking what was requested ----------------------------------------------------------------

    def lists_with(self, **expected):
        """The list reads whose query carries every given parameter (a value of None means absent)."""
        return [
            query for query in self.list_queries
            if all((query.get(key) == value) if value is not None else (key not in query)
                   for key, value in expected.items())
        ]

    def saw(self, method, target):
        return any(seen_method == method and seen == target for seen_method, seen in self.requests)


SEED = r"""
(seed) => {
    const H = window.NotificationsPageHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.448',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: {},
            branding: {app_title: 'Contoso Chat'},
            settings: {},
            scope: {groups: [], public_workspaces: []},
            catalogs: {models: [], agents: [], prompts: []},
        },
        loading: false,
        error: null,
    });
    H.stores.userSettings.useUserSettingsStore.setState({
        settings: seed.settings,
        loading: seed.settingsLoading,
        error: null,
    });
    H.stores.ui.useUiStore.setState({railCollapsed: seed.railCollapsed, mobileNavOpen: false});
    H.mount();
}
"""

COUNT_SETTLED = r"""
() => {
    const store = window.NotificationsPageHarness.stores.notification;
    return store.useNotificationStore.getState().count !== null && !store.isNotificationCountReading();
}
"""


class Harness(NotificationsApi):
    """The frame in a browser page, driven the way a reader drives it."""

    def __init__(self, page, stylesheets):
        super().__init__(page)
        self.stylesheets = stylesheets

    def open(self, path="/notifications", *, settings=None, settings_loading=False, rail_collapsed=False,
             width=1280, height=900):
        """Load the harness at `/v2{path}`, seed the stores and mount the frame."""
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.route("**/*", self.handle)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/v2{path}")
        self.boot(settings=settings, settings_loading=settings_loading, rail_collapsed=rail_collapsed)

    def boot(self, *, settings=None, settings_loading=False, rail_collapsed=False):
        """Style the loaded harness page, seed the stores and mount the frame. A page loaded afresh,
        as a full navigation to `/v2/...` leaves it, is booted again the same way."""
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.page.evaluate(SEED, {
            "settings": {} if settings is None else settings,
            "settingsLoading": settings_loading,
            "railCollapsed": rail_collapsed,
        })
        self.settle_count()

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.expected_http_failures:
            return
        self.errors.append(message.text)

    # Waiting ----------------------------------------------------------------------------------

    def wait_for(self, predicate, message, timeout=5.0):
        """Poll from the test thread, so held and pending routes keep being answered meanwhile."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(message)
            self.page.wait_for_timeout(50)

    def settle_count(self):
        """Wait until the bell's count has been read and no read is on its way."""
        self.wait_for(lambda: self.page.evaluate(COUNT_SETTLED), "The notification count was not read.")

    def settled(self):
        """The list is drawn: nothing is loading and an answer, or a failure, is on screen."""
        expect(self.results).to_have_attribute("aria-busy", "false")

    # Reading the page -------------------------------------------------------------------------

    def js(self, script, arg=None):
        return self.page.evaluate(script, arg)

    def active(self):
        """What has keyboard focus, named so that a failure reads plainly. BODY means it was dropped."""
        return self.js("""() => {
            const element = document.activeElement;
            if (!element) return 'nothing';
            if (element === document.body) return 'BODY';
            const page = element.dataset.notificationPage;
            return element.dataset.testid || (page ? `page ${page}` : '')
                || element.getAttribute('aria-label') || element.textContent.trim() || element.tagName;
        }""")

    def expect_focus(self, locator, what):
        """The keyboard is on `locator`. A control that becomes disabled under the reader's fingers
        hands focus to BODY, which the failure names."""
        try:
            expect(locator).to_be_focused()
        except AssertionError as error:
            raise AssertionError(f"Focus should be on {what}, but it is on {self.active()}.") from error

    @property
    def results(self):
        return self.page.get_by_test_id("notifications-results")

    @property
    def rows(self):
        return self.page.locator('[data-testid="notifications-list"] li[data-notification-id]')

    def row(self, notice_id):
        return self.page.locator(f'li[data-notification-id="{notice_id}"]')

    def action(self, notice_id, name):
        return self.row(notice_id).locator(f'[data-notification-action="{name}"]')

    def row_ids(self):
        return self.rows.evaluate_all("(items) => items.map((item) => item.dataset.notificationId)")

    @property
    def summary(self):
        return self.page.locator("[data-notifications-summary]")

    def filter(self, name):
        return self.page.locator(f'[data-notification-filter="{name}"]')

    @property
    def search(self):
        return self.page.get_by_role("searchbox", name="Search notifications")

    @property
    def per_page(self):
        return self.page.get_by_label("Per page")

    @property
    def pager(self):
        return self.page.get_by_role("navigation", name="Notification pages")

    def page_button(self, number):
        return self.pager.get_by_role("button", name=f"Page {number}", exact=True)

    def page_numbers(self):
        return self.pager.locator("button[data-notification-page]").evaluate_all(
            "(items) => items.map((item) => item.dataset.notificationPage).filter((value) => /^\\d+$/.test(value))"
        )

    @property
    def mark_all(self):
        return self.page.get_by_test_id("notifications-mark-all-read")

    @property
    def refresh(self):
        return self.page.get_by_test_id("notifications-refresh")

    @property
    def bell(self):
        return self.page.locator("button[data-notification-bell]")

    @property
    def panel(self):
        return self.page.locator("[data-notification-panel]")

    @property
    def route(self):
        """The router's own route, relative to its `/v2` base."""
        return self.page.locator("[data-current-route]")

    def toast(self, text):
        return self.page.get_by_role("alert").filter(has_text=text)

    # Acting -----------------------------------------------------------------------------------

    def type_search(self, text, *, delay=20):
        self.search.click()
        self.search.press_sequentially(text, delay=delay)


@pytest.fixture(scope="module")
def harness_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: npm --prefix application/v2_ui run build"
    markup = index.read_text(encoding="utf-8")
    expected_js = os.getenv("SIMPLECHAT_UI_EXPECTED_JS", "")
    expected_css = os.getenv("SIMPLECHAT_UI_EXPECTED_CSS", "")
    if expected_js or expected_css:
        # An explicitly released build, named by its files, stands in for the freshness check, as in the
        # other V2 fixtures: a sibling's save of a shared file after the build does not fail the run.
        if not (expected_js and expected_css):
            pytest.fail("Set both SIMPLECHAT_UI_EXPECTED_JS and SIMPLECHAT_UI_EXPECTED_CSS.")
        for filename, attribute, suffix in ((expected_js, "src", "js"), (expected_css, "href", "css")):
            if not re.fullmatch(rf"[A-Za-z0-9_.-]+\.{suffix}", filename):
                pytest.fail("Expected build assets must be local filenames.")
            reference = f"/static/v2/assets/{filename}"
            if not (STATIC / "v2" / "assets" / filename).is_file() or not re.search(
                rf'{attribute}=["\']{re.escape(reference)}["\']', markup,
            ):
                pytest.fail("The explicitly released SPA assets are missing or have changed.")
    else:
        built = index.stat().st_mtime
        # The page's own styling comes from the built stylesheet, so a source that draws it and is newer
        # than the build means a class the stylesheet may not have yet. Only these are checked, so an
        # unrelated change elsewhere in the application does not fail this suite.
        stale = [item for item in WATCHED_SOURCES if item.is_file() and item.stat().st_mtime > built]
        if stale:
            pytest.fail(
                f"The V2 bundle is stale ({stale[0].relative_to(ROOT)} changed after it was built). "
                "Run npm --prefix application/v2_ui run build",
            )
    hrefs = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', markup)
    stylesheets = [STATIC / href.removeprefix("/static/") for href in hrefs]
    assert stylesheets and all(sheet.is_file() for sheet in stylesheets), stylesheets
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=BUNDLE)
    yield stylesheets
    BUNDLE.unlink(missing_ok=True)


@pytest.fixture
def harness(page, harness_assets):
    api = Harness(page, harness_assets)
    yield api
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected


def test_the_page_lists_every_notice_with_its_total_and_its_pages(harness):
    for number in range(1, 31):
        harness.add(plain_notice(number, read=number % 3 == 0))
    harness.open("/notifications", settings={"notifications_per_page": 10})
    harness.settled()

    expect(harness.page.get_by_role("heading", level=1, name="Notifications")).to_be_visible()
    assert harness.list_queries[-1] == {"page": "1", "per_page": "10", "include_read": "true", "include_dismissed": "false"}
    assert harness.row_ids() == [f"n-{number:03d}" for number in range(30, 20, -1)]
    expect(harness.summary).to_have_text("Showing 1\u201310 of 30 notifications.")
    expect(harness.filter("all")).to_have_attribute("aria-pressed", "true")
    expect(harness.filter("unread")).to_have_attribute("aria-pressed", "false")
    expect(harness.pager).to_contain_text("Page 1 of 3")
    expect(harness.page_button(1)).to_have_attribute("aria-current", "page")
    assert harness.page_numbers() == ["1", "2", "3"]


def unread_flags(harness):
    return harness.rows.evaluate_all("(items) => items.map((item) => item.dataset.unread)")


# The read filter and the search ---------------------------------------------------------------


def test_the_read_filter_is_asked_of_the_server_so_the_total_and_the_pages_follow_it(harness):
    # 20 unread and 10 read.
    for number in range(1, 31):
        harness.add(plain_notice(number, read=number % 3 == 0))
    harness.open("/notifications?page=2", settings={"notifications_per_page": 10})
    harness.settled()
    expect(harness.summary).to_have_text("Showing 11\u201320 of 30 notifications.")

    harness.filter("unread").click()
    expect(harness.filter("unread")).to_have_attribute("aria-pressed", "true")
    expect(harness.summary).to_have_text("Showing 1\u201310 of 20 unread notifications.")
    harness.settled()
    # A new filter starts at the first page, and the address says what is shown.
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?status=unread")
    assert harness.list_queries[-1] == {
        "page": "1", "per_page": "10", "include_read": "true", "include_dismissed": "false", "status": "unread",
    }
    assert set(unread_flags(harness)) == {"true"}
    expect(harness.pager).to_contain_text("Page 1 of 2")

    harness.filter("read").click()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 10 read notifications.")
    harness.settled()
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?status=read")
    assert set(unread_flags(harness)) == {"false"}
    # One page of results has no pager.
    expect(harness.pager).to_have_count(0)

    harness.filter("all").click()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 30 notifications.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications")


def test_a_search_is_sent_once_the_reader_pauses_and_the_totals_follow_it(harness):
    # 12 notices mention "ledger", some only in their message, and 3 of them are read.
    for number in range(1, 13):
        harness.add(ledger_notice(f"l-{number:02d}", in_title=number % 2 == 0, read=number > 9))
    for number in range(1, 9):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=10")
    harness.settled()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 20 notifications.")

    harness.type_search("ledger")
    expect(harness.summary).to_have_text("Showing 1\u201310 of 12 notifications matching your search.")
    harness.settled()
    # One read for the word, not one for each letter of it.
    assert [query["q"] for query in harness.list_queries if "q" in query] == ["ledger"]
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?q=ledger&per_page=10")
    assert harness.row_ids() == [record["id"] for record in harness.listed(query="ledger")[:10]]
    expect(harness.pager).to_contain_text("Page 1 of 2")

    harness.page_button(2).click()
    expect(harness.summary).to_have_text("Showing 11\u201312 of 12 notifications matching your search.")
    assert len(harness.row_ids()) == 2

    # The filter and the search narrow each other, and a new search starts at the first page.
    harness.filter("unread").click()
    expect(harness.summary).to_have_text("Showing 1\u20139 of 9 unread notifications matching your search.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?status=unread&q=ledger&per_page=10")
    harness.filter("all").click()

    # Case does not matter, and the box shows what was typed rather than what was sent.
    harness.search.fill("LEDGER ")
    expect(harness.summary).to_have_text("Showing 1\u201310 of 12 notifications matching your search.")
    expect(harness.search).to_have_value("LEDGER ")
    harness.settled()
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?q=LEDGER&per_page=10")


def test_enter_searches_at_once_and_clearing_the_search_lists_everything_again(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=10")
    harness.settled()
    expect(harness.page.get_by_role("button", name="Clear search")).to_have_count(0)

    harness.search.fill("announcement 00")
    harness.search.press("Enter")
    # Well inside the pause that would otherwise have sent it.
    harness.wait_for(lambda: harness.lists_with(q="announcement 00"), "Enter did not search at once.", timeout=0.3)
    expect(harness.summary).to_have_text("Showing 1\u20139 of 9 notifications matching your search.")
    harness.page.wait_for_timeout(600)
    assert len(harness.lists_with(q="announcement 00")) == 1, "The pause sent the same search again."

    clear = harness.page.get_by_role("button", name="Clear search")
    clear.click()
    expect(harness.search).to_have_value("")
    expect(harness.search).to_be_focused()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 12 notifications.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?per_page=10")
    expect(clear).to_have_count(0)
    assert harness.list_queries[-1].get("q") is None


def test_a_search_with_no_match_says_so_and_can_be_cleared(harness):
    harness.add(plain_notice(1), plain_notice(2))
    harness.open("/notifications")
    harness.settled()

    harness.type_search("zzzz")
    empty = harness.page.locator("[data-notification-empty]")
    expect(empty).to_contain_text("No notifications match your search")
    expect(harness.summary).to_have_text("No notifications match your search.")
    expect(harness.pager).to_have_count(0)
    empty.get_by_role("button", name="Clear search").click()
    expect(harness.summary).to_have_text("Showing 1\u20132 of 2 notifications.")
    expect(harness.search).to_have_value("")


def test_a_search_is_capped_where_the_server_caps_it(harness):
    harness.add(plain_notice(1))
    harness.open("/notifications")
    harness.settled()

    assert harness.search.get_attribute("maxlength") == str(SEARCH_MAX_LENGTH)
    harness.search.fill("x" * 150)
    harness.wait_for(lambda: harness.lists_with(q="x" * SEARCH_MAX_LENGTH), "The capped search was not sent.")
    assert not harness.lists_with(q="x" * 150)


def test_an_address_the_server_would_refuse_falls_back_to_the_default_view(harness):
    harness.add(plain_notice(1))
    harness.open("/notifications?status=archived&page=0&per_page=15&q=&other=1", settings={"notifications_per_page": "lots"})
    harness.settled()

    assert harness.list_queries[-1] == {"page": "1", "per_page": "20", "include_read": "true", "include_dismissed": "false"}
    expect(harness.filter("all")).to_have_attribute("aria-pressed", "true")
    expect(harness.per_page).to_have_value("20")


# Numbered pages ------------------------------------------------------------------------------


def test_numbered_pages_show_their_range_and_keep_the_view_in_the_address(harness):
    for number in range(1, 121):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=10")
    harness.settled()

    # Twelve pages: the ends and a window around the current one, never all of them.
    assert harness.page_numbers() == ["1", "2", "3", "4", "5", "12"]
    expect(harness.pager.get_by_role("button", name="Previous")).to_be_disabled()

    harness.page_button(2).click()
    expect(harness.summary).to_have_text("Showing 11\u201320 of 120 notifications.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?page=2&per_page=10")
    expect(harness.page_button(2)).to_have_attribute("aria-current", "page")
    assert harness.row_ids() == [f"n-{number:03d}" for number in range(110, 100, -1)]

    harness.pager.get_by_role("button", name="Next").click()
    expect(harness.summary).to_have_text("Showing 21\u201330 of 120 notifications.")
    harness.page_button(5).click()
    expect(harness.summary).to_have_text("Showing 41\u201350 of 120 notifications.")
    assert harness.page_numbers() == ["1", "4", "5", "6", "12"]

    harness.pager.get_by_role("button", name="Previous").click()
    expect(harness.summary).to_have_text("Showing 31\u201340 of 120 notifications.")

    # Each page is a step in the history, so Back returns to the page before it.
    harness.page.go_back()
    expect(harness.summary).to_have_text("Showing 41\u201350 of 120 notifications.")
    harness.page.go_forward()
    expect(harness.summary).to_have_text("Showing 31\u201340 of 120 notifications.")


def test_the_last_page_ends_the_pager(harness):
    for number in range(1, 36):
        harness.add(plain_notice(number))
    harness.open("/notifications?page=3&per_page=10")
    harness.settled()
    expect(harness.summary).to_have_text("Showing 21\u201330 of 35 notifications.")

    harness.pager.get_by_role("button", name="Next").click()
    expect(harness.summary).to_have_text("Showing 31\u201335 of 35 notifications.")
    expect(harness.pager.get_by_role("button", name="Next")).to_be_disabled()
    expect(harness.pager.get_by_role("button", name="Previous")).to_be_enabled()
    assert harness.row_ids() == [f"n-{number:03d}" for number in range(5, 0, -1)]


def test_an_address_past_the_last_page_lands_on_the_last_one(harness):
    for number in range(1, 36):
        harness.add(plain_notice(number))
    harness.open("/notifications?page=99&per_page=10")
    harness.settled()

    expect(harness.summary).to_have_text("Showing 31\u201335 of 35 notifications.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?page=4&per_page=10")
    assert harness.lists_with(page="99"), "The page past the end was never asked for."
    assert harness.row_ids() == [f"n-{number:03d}" for number in range(5, 0, -1)]
    # The address was replaced rather than added to, so Back leaves the page.
    harness.page.go_back()
    expect(harness.page).not_to_have_url(re.compile(r"/v2/notifications"))


def test_the_pager_stays_put_and_keeps_focus_while_the_next_page_loads(harness):
    for number in range(1, 36):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=10")
    harness.settled()
    next_button = harness.pager.get_by_role("button", name="Next")
    next_button.focus()

    harness.hold_lists = True
    harness.page.keyboard.press("Enter")
    harness.wait_for(lambda: len(harness.held_lists) == 1, "The next page was not asked for.")
    # The pager is not swapped for the loading state, so the control just used is still the one in focus.
    expect(harness.pager).to_contain_text("Page 2 of 4")
    expect(next_button).to_be_focused()
    assert harness.row_ids() == []

    harness.hold_lists = False
    harness.release_lists()
    expect(harness.summary).to_have_text("Showing 11\u201320 of 35 notifications.")
    expect(next_button).to_be_focused()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 21\u201330 of 35 notifications.")


def test_a_changed_page_returns_to_the_top_of_the_list(harness):
    for number in range(1, 31):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=10")
    harness.settled()
    scroller = harness.page.get_by_test_id("notifications-page-scroll")
    scroller.evaluate("(element) => { element.scrollTop = element.scrollHeight; }")
    assert scroller.evaluate("(element) => element.scrollTop") > 0

    harness.pager.get_by_role("button", name="Next").click()
    expect(harness.summary).to_have_text("Showing 11\u201320 of 30 notifications.")
    assert scroller.evaluate("(element) => element.scrollTop") == 0


# The page size ---------------------------------------------------------------------------------


def test_the_page_size_starts_from_the_saved_one_and_choosing_another_saves_it(harness):
    for number in range(1, 61):
        harness.add(plain_notice(number))
    harness.open("/notifications", settings={"notifications_per_page": 50})
    harness.settled()

    assert harness.list_queries[-1]["per_page"] == "50"
    expect(harness.per_page).to_have_value("50")
    expect(harness.summary).to_have_text("Showing 1\u201350 of 60 notifications.")
    assert harness.settings_posts == [], "Opening the page must not save a size."
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications")

    harness.per_page.select_option("10")
    expect(harness.summary).to_have_text("Showing 1\u201310 of 60 notifications.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?per_page=10")
    harness.wait_for(lambda: harness.settings_posts == [{"notifications_per_page": 10}], "The size was not saved.")
    # Not /api/user/settings, which does not accept the key.
    assert not harness.saw("POST", "/api/user/settings")
    harness.wait_for(
        lambda: harness.js(
            "() => window.NotificationsPageHarness.stores.userSettings.useUserSettingsStore.getState()"
            ".settings.notifications_per_page"
        ) == 10,
        "The saved size was not kept in the preferences already loaded.",
    )

    # A new size starts again at the first page.
    harness.page_button(3).click()
    expect(harness.summary).to_have_text("Showing 21\u201330 of 60 notifications.")
    harness.per_page.select_option("20")
    expect(harness.summary).to_have_text("Showing 1\u201320 of 60 notifications.")
    harness.wait_for(lambda: len(harness.settings_posts) == 2, "The second size was not saved.")
    assert harness.settings_posts[-1] == {"notifications_per_page": 20}


def test_a_size_named_in_the_address_wins_and_saves_nothing(harness):
    for number in range(1, 31):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=20", settings={"notifications_per_page": 50})
    harness.settled()

    assert harness.list_queries[-1]["per_page"] == "20"
    expect(harness.per_page).to_have_value("20")
    expect(harness.summary).to_have_text("Showing 1\u201320 of 30 notifications.")
    assert harness.settings_posts == []


def test_the_first_read_waits_for_the_saved_size_instead_of_reading_twice(harness):
    for number in range(1, 31):
        harness.add(plain_notice(number))
    harness.open("/notifications", settings={}, settings_loading=True)
    expect(harness.per_page).to_be_disabled()
    expect(harness.page.locator("[data-notifications-loading]")).to_be_visible()
    harness.page.wait_for_timeout(500)
    assert harness.list_queries == [], "The list was read before the saved size was known."

    harness.js("""() => window.NotificationsPageHarness.stores.userSettings.useUserSettingsStore.setState({
        settings: {notifications_per_page: 10}, loading: false,
    })""")
    expect(harness.summary).to_have_text("Showing 1\u201310 of 30 notifications.")
    assert {query["per_page"] for query in harness.list_queries} == {"10"}
    expect(harness.per_page).to_have_value("10")


def test_a_size_that_could_not_be_saved_still_applies_and_the_reader_is_told(harness):
    for number in range(1, 31):
        harness.add(plain_notice(number))
    harness.fail_next.add("settings")
    harness.open("/notifications")
    harness.settled()

    harness.per_page.select_option("10")
    expect(harness.summary).to_have_text("Showing 1\u201310 of 30 notifications.")
    expect(harness.toast("page size could not be saved")).to_be_visible()
    saved = harness.js("() => window.NotificationsPageHarness.stores.userSettings.useUserSettingsStore.getState().settings")
    assert "notifications_per_page" not in saved


# Acting on notices ----------------------------------------------------------------------------


def actionable_inbox(harness):
    """Five unread notices, one read one, an unread document notice and an alert to acknowledge."""
    for number in range(1, 6):
        harness.add(plain_notice(number))
    harness.add(plain_notice(6, read=True), document_notice("n-doc"), acknowledgment_alert("n-ack", link=False))


def test_read_dismiss_and_acknowledge_change_the_server_and_the_bell(harness):
    actionable_inbox(harness)
    harness.open("/notifications")
    harness.settled()
    expect(harness.bell).to_have_attribute("data-unread-count", "7")
    expect(harness.summary).to_have_text("Showing 1\u20138 of 8 notifications.")

    harness.action("n-004", "read").click()
    expect(harness.row("n-004")).to_have_attribute("data-unread", "false")
    expect(harness.action("n-004", "read")).to_have_count(0)
    harness.wait_for(lambda: harness.read_calls == ["n-004"], "The notice was not marked read.")
    harness.settle_count()
    expect(harness.bell).to_have_attribute("data-unread-count", "6")
    expect(harness.summary).to_have_text("Showing 1\u20138 of 8 notifications.")

    harness.action("n-005", "dismiss").click()
    expect(harness.row("n-005")).to_have_count(0)
    expect(harness.summary).to_have_text("Showing 1\u20137 of 7 notifications.")
    harness.wait_for(lambda: harness.dismiss_calls == ["n-005"], "The notice was not dismissed.")
    harness.settle_count()
    expect(harness.bell).to_have_attribute("data-unread-count", "5")

    # An alert that needs acknowledgment says so, and acknowledging it names who did.
    expect(harness.row("n-ack").locator("[data-notification-ack-tag]")).to_have_text("Needs acknowledgment")
    harness.action("n-ack", "acknowledge").click()
    expect(harness.row("n-ack").locator("[data-notification-acknowledged]")).to_contain_text("Acknowledged by Riley Chen at")
    expect(harness.row("n-ack").locator("[data-notification-ack-tag]")).to_have_count(0)
    assert harness.acknowledge_calls == ["n-ack"]
    harness.settle_count()
    expect(harness.bell).to_have_attribute("data-unread-count", "4")

    # Read and dismissed notices stay as the server has them.
    assert harness.find("n-004")["is_read"] and harness.find("n-005")["is_dismissed"]
    assert harness.read_calls == ["n-004"] and harness.dismiss_calls == ["n-005"]


def test_mark_all_read_and_refresh(harness):
    actionable_inbox(harness)
    harness.open("/notifications")
    harness.settled()
    expect(harness.mark_all).to_be_enabled()

    harness.mark_all.click()
    harness.wait_for(lambda: harness.mark_all_calls == 1 and not harness.unread(), "Mark all read did not reach the server.")
    expect(harness.bell).to_have_attribute("data-unread-count", "0")
    harness.settled()
    assert set(unread_flags(harness)) == {"false"}
    expect(harness.mark_all).to_be_disabled()

    # Refresh reads the same view again, and shows what changed elsewhere.
    harness.add(notice("n-late", "Arrived meanwhile", "Added by another tab."))
    reads_before = len(harness.lists_with())
    harness.refresh.click()
    expect(harness.row("n-late")).to_be_visible()
    assert len(harness.lists_with()) == reads_before + 1
    expect(harness.summary).to_have_text("Showing 1\u20139 of 9 notifications.")


def test_a_refused_change_is_explained_and_the_list_stays_as_the_server_has_it(harness):
    actionable_inbox(harness)
    harness.open("/notifications")
    harness.settled()

    harness.fail_next.add("read")
    harness.action("n-004", "read").click()
    expect(harness.toast("Failed to mark notification as read")).to_be_visible()
    expect(harness.row("n-004")).to_have_attribute("data-unread", "true")
    expect(harness.action("n-004", "read")).to_be_enabled()

    harness.fail_next.add("dismiss")
    harness.action("n-003", "dismiss").click()
    expect(harness.toast("Failed to dismiss notification")).to_be_visible()
    expect(harness.row("n-003")).to_be_visible()

    harness.fail_next.add("acknowledge")
    harness.action("n-ack", "acknowledge").click()
    expect(harness.toast("That alert could not be acknowledged.")).to_be_visible()
    expect(harness.row("n-ack").locator("[data-notification-ack-tag]")).to_be_visible()

    harness.fail_next.add("mark_all")
    harness.mark_all.click()
    expect(harness.toast("Internal server error")).to_be_visible()
    harness.settled()
    assert len(harness.unread()) == 7
    expect(harness.bell).to_have_attribute("data-unread-count", "7")


def test_in_the_unread_view_a_read_notice_leaves_and_the_next_one_takes_its_place(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number))
    harness.open("/notifications?status=unread&per_page=10")
    harness.settled()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 12 unread notifications.")
    assert harness.row_ids()[-1] == "n-003"

    harness.action("n-012", "read").click()
    expect(harness.row("n-012")).to_have_count(0)
    expect(harness.summary).to_have_text("Showing 1\u201310 of 11 unread notifications.")
    assert harness.row_ids() == [f"n-{number:03d}" for number in range(11, 1, -1)]
    expect(harness.pager).to_contain_text("Page 1 of 2")


def test_dismissing_the_last_notice_on_the_last_page_moves_to_the_page_before(harness):
    for number in range(1, 12):
        harness.add(plain_notice(number))
    harness.open("/notifications?page=2&per_page=10")
    harness.settled()
    expect(harness.summary).to_have_text("Showing 11 of 11 notifications.")
    assert harness.row_ids() == ["n-001"]

    harness.action("n-001", "dismiss").click()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 10 notifications.")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?per_page=10")
    assert len(harness.row_ids()) == 10


def test_focus_stays_in_the_list_when_the_button_pressed_goes_with_its_row(harness):
    actionable_inbox(harness)
    harness.open("/notifications")
    harness.settled()

    harness.action("n-003", "dismiss").focus()
    harness.page.keyboard.press("Enter")
    expect(harness.row("n-003")).to_have_count(0)
    harness.wait_for(
        lambda: harness.js("() => Boolean(document.activeElement?.closest('[data-testid=\"notifications-results\"]'))"),
        "Focus was lost with the row.",
    )

    # A notice that is only marked read keeps its row, so focus lands on that row's first control.
    harness.action("n-002", "read").focus()
    harness.page.keyboard.press("Enter")
    expect(harness.row("n-002")).to_have_attribute("data-unread", "false")
    harness.wait_for(
        lambda: harness.js("() => document.activeElement?.closest('li')?.dataset.notificationId") == "n-002",
        "Focus did not land on the row that was changed.",
    )


# Opening a notice -----------------------------------------------------------------------------


def test_opening_a_notice_follows_its_link_and_reads_it(harness):
    harness.add(
        notice("n-classic", "Open the viewer", link_url="/view_pdf?doc_id=d-1&page=2"),
        document_notice("n-doc"),
    )
    harness.open("/notifications")
    harness.settled()

    harness.action("n-doc", "open").click()
    expect(harness.route).to_have_text("/workspace/documents")
    harness.wait_for(lambda: harness.read_calls == ["n-doc"], "Opening an unread notice should mark it read.")
    harness.page.go_back()
    expect(harness.row("n-doc")).to_have_attribute("data-unread", "false")

    # A page V2 has not rebuilt is opened with a full page load, which would cancel a request still
    # on its way, so the read is settled first.
    harness.action("n-classic", "open").click()
    harness.page.wait_for_url(f"{ORIGIN}/view_pdf?doc_id=d-1&page=2")
    expect(harness.page.get_by_role("heading", name="Classic interface")).to_be_visible()
    assert harness.read_calls == ["n-doc", "n-classic"]
    order = [(method, target) for method, target in harness.requests]
    assert order.index(("POST", "/api/notifications/n-classic/read")) < order.index(
        ("GET", "/view_pdf?doc_id=d-1&page=2"),
    )


def test_opening_an_alert_that_needs_acknowledgment_acknowledges_it(harness):
    alert = acknowledgment_alert("n-ack")
    alert["link_url"] = "/workspace"
    alert["link_context"] = {"workspace_type": "personal"}
    harness.add(alert)
    harness.open("/notifications")
    harness.settled()

    harness.action("n-ack", "open").click()
    expect(harness.route).to_have_text("/workspace/documents")
    harness.wait_for(lambda: harness.acknowledge_calls == ["n-ack"], "Opening the alert did not acknowledge it.")
    assert harness.read_calls == []


def test_a_notice_without_a_usable_link_says_why_instead_of_opening(harness):
    harness.add(
        notice("n-offsite", "Visit the vendor", link_url="https://evil.example/phish"),
        notice("n-api", "Raw endpoint", link_url="/api/notifications/mark-all-read"),
        notice("n-none", "Nothing to open"),
    )
    harness.open("/notifications")
    harness.settled()

    expect(harness.action("n-offsite", "open")).to_have_count(0)
    expect(harness.row("n-offsite").locator("[data-notification-link-error]")).to_have_text(
        "This notification links to another site, so it is not opened from here.",
    )
    expect(harness.row("n-api").locator("[data-notification-link-error]")).to_contain_text("unsupported link")
    expect(harness.action("n-none", "open")).to_have_count(0)
    expect(harness.row("n-none").locator("[data-notification-link-error]")).to_have_count(0)
    assert harness.read_calls == [] and harness.mark_all_calls == 0


# Empty, failed and slow ------------------------------------------------------------------------


@pytest.mark.parametrize(("status", "read", "title", "summary"), [
    ("all", None, "You're all caught up", "No notifications."),
    ("unread", True, "No unread notifications", "No unread notifications."),
    ("read", False, "No read notifications", "No read notifications."),
])
def test_an_empty_list_says_why_it_is_empty(harness, status, read, title, summary):
    # Each view is empty because of what the inbox does not hold: nothing, nothing unread, nothing read.
    if read is not None:
        harness.add(plain_notice(1, read=read))
    harness.open("/notifications" if status == "all" else f"/notifications?status={status}")
    harness.settled()

    expect(harness.page.locator("[data-notification-empty]")).to_contain_text(title)
    expect(harness.summary).to_have_text(summary)
    expect(harness.pager).to_have_count(0)
    assert harness.row_ids() == []


def test_a_failed_read_is_explained_and_can_be_tried_again(harness):
    harness.add(plain_notice(1), plain_notice(2))
    harness.list_failure = True
    harness.open("/notifications")

    failure = harness.page.locator("[data-notifications-error]")
    expect(failure).to_contain_text("Failed to fetch notifications")
    expect(failure.get_by_role("alert")).to_be_visible()
    expect(harness.summary).to_have_text("")
    assert harness.row_ids() == []

    harness.list_failure = False
    failure.get_by_role("button", name="Try again").click()
    expect(harness.summary).to_have_text("Showing 1\u20132 of 2 notifications.")
    expect(failure).to_have_count(0)


def test_a_failed_refresh_keeps_what_is_on_screen_and_says_it_may_be_out_of_date(harness):
    harness.add(plain_notice(1), plain_notice(2))
    harness.open("/notifications")
    harness.settled()

    harness.list_failure = True
    harness.refresh.click()
    failure = harness.page.locator("[data-notifications-error]")
    expect(failure).to_contain_text("What is shown may be out of date.")
    assert harness.row_ids() == ["n-002", "n-001"]

    harness.list_failure = False
    failure.get_by_role("button", name="Try again").click()
    expect(failure).to_have_count(0)
    expect(harness.summary).to_have_text("Showing 1\u20132 of 2 notifications.")


def test_a_slow_answer_to_an_earlier_view_is_never_shown_under_a_later_one(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number, read=number > 6))
    harness.open("/notifications")
    harness.settled()

    harness.hold_lists = True
    harness.filter("unread").click()
    harness.wait_for(lambda: len(harness.held_lists) == 1, "The unread view was not asked for.")
    # Nothing from the view that was left is shown while the next one is on its way.
    expect(harness.page.locator("[data-notifications-loading]")).to_be_visible()
    assert harness.row_ids() == []
    harness.filter("read").click()
    harness.wait_for(lambda: len(harness.held_lists) == 2, "The read view was not asked for.")

    harness.hold_lists = False
    harness.release_lists(order=[1, 0])
    expect(harness.filter("read")).to_have_attribute("aria-pressed", "true")
    expect(harness.summary).to_have_text("Showing 1\u20136 of 6 read notifications.")
    harness.page.wait_for_timeout(200)
    assert set(unread_flags(harness)) == {"false"}
    expect(harness.summary).to_have_text("Showing 1\u20136 of 6 read notifications.")


def test_a_notice_that_arrives_while_the_page_is_open_is_listed(harness):
    harness.add(plain_notice(1), plain_notice(2))
    harness.open("/notifications")
    harness.settled()
    expect(harness.summary).to_have_text("Showing 1\u20132 of 2 notifications.")
    reads_before = len(harness.lists_with())

    harness.add(notice("n-new", "Brand new notice", "Just arrived."))
    harness.js("() => window.NotificationsPageHarness.stores.notification.refreshNotificationCount('action')")
    expect(harness.summary).to_have_text("Showing 1\u20133 of 3 notifications.")
    assert harness.row_ids()[0] == "n-new"
    expect(harness.bell).to_have_attribute("data-unread-count", "3")
    assert len(harness.lists_with()) == reads_before + 1, "The new notice should cost one read of the list."


# Reaching the page -----------------------------------------------------------------------------


def test_the_bell_panel_leads_to_the_page(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number))
    harness.open("/elsewhere")
    harness.bell.click()
    expect(harness.panel).to_be_visible()

    link = harness.panel.get_by_role("link", name="View all notifications")
    expect(link).to_have_attribute("href", "/v2/notifications")
    link.click()
    expect(harness.panel).to_have_count(0)
    expect(harness.route).to_have_text("/notifications")
    expect(harness.page.get_by_role("heading", level=1, name="Notifications")).to_be_visible()
    harness.settled()
    expect(harness.summary).to_have_text("Showing 1\u201312 of 12 notifications.")
    # The classic page is no longer the panel's way to everything.
    assert not harness.saw("GET", "/notifications")


def test_the_account_menu_leads_to_the_page_and_carries_the_bells_count(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number))
    harness.open("/elsewhere")

    harness.page.locator('[data-tour="user-menu"]').click()
    menu = harness.page.locator("#sidebar-account-menu")
    link = menu.get_by_role("link", name="Notifications, 9+ unread")
    expect(link).to_have_attribute("href", "/v2/notifications")
    expect(link.locator("[data-account-menu-notification-badge]")).to_have_text("9+")
    # The first entry, ahead of the settings that follow it.
    assert menu.get_by_role("link").first.get_attribute("href") == "/v2/notifications"
    link.click()
    expect(harness.route).to_have_text("/notifications")
    expect(menu).to_have_count(0)


@pytest.mark.parametrize("rail_collapsed", [False, True])
def test_the_account_menu_entry_has_no_badge_when_nothing_is_unread(harness, rail_collapsed):
    harness.add(plain_notice(1, read=True))
    harness.open("/elsewhere", rail_collapsed=rail_collapsed)

    harness.page.locator('[data-tour="user-menu"]').click()
    link = harness.page.locator("#sidebar-account-menu").get_by_role("link", name="Notifications", exact=True)
    expect(link).to_be_visible()
    expect(link.locator("[data-account-menu-notification-badge]")).to_have_count(0)
    link.click()
    expect(harness.route).to_have_text("/notifications")


# Layout, keyboard and untrusted text --------------------------------------------------------------


def test_the_page_fits_a_phone_and_is_reached_from_the_header_bell_and_the_navigation_drawer(harness):
    for number in range(1, 26):
        harness.add(plain_notice(number, read=number % 4 == 0))
    # One unbroken string, as a long address or identifier is, which must wrap rather than overflow.
    harness.add(notice("n-long", "A" * 140, "B" * 300))
    phone = {"settings": {"notifications_per_page": 10}}
    harness.open("/elsewhere", width=390, height=844, **phone)

    # On a phone the bell is in the page header, and its panel leads to the page inside the application.
    harness.bell.click()
    harness.panel.get_by_role("link", name="View all notifications").click()
    expect(harness.route).to_have_text("/notifications")
    harness.settled()

    scroller = harness.page.get_by_test_id("notifications-page-scroll")
    overflow = scroller.evaluate(
        "(element) => Math.max(element.scrollWidth - element.clientWidth,"
        " document.documentElement.scrollWidth - document.documentElement.clientWidth)",
    )
    assert overflow <= 1, f"The page scrolls sideways by {overflow}px"
    for control in (harness.filter("all"), harness.filter("unread"), harness.search, harness.per_page):
        assert control.bounding_box()["height"] >= 43.5, "A control is too short for a thumb."
    for control in (harness.mark_all, harness.refresh):
        box = control.bounding_box()
        assert box["width"] >= 43.5 and box["height"] >= 43.5
    harness.pager.get_by_role("button", name="Next").scroll_into_view_if_needed()
    assert harness.pager.get_by_role("button", name="Next").bounding_box()["height"] >= 43.5
    assert harness.row("n-long").bounding_box()["width"] <= 390

    harness.filter("unread").click()
    expect(harness.filter("unread")).to_have_attribute("aria-pressed", "true")
    harness.settled()
    assert set(unread_flags(harness)) == {"true"}

    # The navigation drawer reaches it too, through the account menu. A link in the drawer follows its
    # address with a page load -- the drawer closes on the click and takes the link with it, before the
    # router has seen it -- so the application is started again at the page the link names.
    harness.page.get_by_role("button", name="Open navigation").click()
    harness.page.locator('[data-tour="user-menu"]').click()
    entry = harness.page.locator("#sidebar-account-menu").get_by_role("link", name=re.compile("^Notifications"))
    expect(entry).to_have_attribute("href", "/v2/notifications")
    entry.click()
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications")
    harness.boot(**phone)
    harness.settled()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 26 notifications.")


def focused(harness):
    return harness.js("""() => {
        const element = document.activeElement;
        const label = element.getAttribute('aria-label');
        if (label) return label;
        if (element.labels && element.labels.length) {
            const text = element.labels[0].querySelector('span') || element.labels[0];
            return text.textContent.trim();
        }
        return element.textContent.trim();
    }""")


def test_tab_order_and_names_follow_the_visible_order(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number))
    harness.add(document_notice("n-doc"))
    harness.open("/notifications", settings={"notifications_per_page": 10})
    harness.settled()

    harness.mark_all.focus()
    title = "Document ready: Q3 forecast.pdf"
    expected = [
        "Mark all read", "Refresh", "All", "Unread", "Read", "Search notifications", "Per page",
        title, f"Mark as read: {title}", f"Dismiss: {title}", "Mark as read: Announcement 012",
    ]
    seen = [focused(harness)]
    for _ in range(len(expected) - 1):
        harness.page.keyboard.press("Tab")
        seen.append(focused(harness))
    assert seen == expected

    # The group and the pager have names of their own.
    expect(harness.page.get_by_role("group", name="Show notifications")).to_be_visible()
    expect(harness.pager).to_be_visible()
    for name in ("All", "Unread", "Read"):
        expect(harness.page.get_by_role("button", name=name, exact=True)).to_be_visible()


def test_the_results_are_announced_politely_when_they_change(harness):
    for number in range(1, 13):
        harness.add(plain_notice(number))
    harness.open("/notifications", settings={"notifications_per_page": 10})
    harness.settled()

    expect(harness.summary).to_have_attribute("role", "status")
    expect(harness.summary).to_have_attribute("aria-live", "polite")
    expect(harness.summary).to_have_attribute("aria-atomic", "true")
    # Nothing is announced about a view that is still loading.
    harness.hold_lists = True
    harness.filter("unread").click()
    expect(harness.summary).to_have_text("")
    harness.hold_lists = False
    harness.release_lists()
    expect(harness.summary).to_have_text("Showing 1\u201310 of 12 unread notifications.")


def test_text_that_looks_like_markup_is_shown_and_searched_as_text(harness):
    harness.add(notice("n-x", XSS_TITLE, XSS_MESSAGE), plain_notice(1))
    harness.open("/notifications")
    harness.settled()

    row = harness.row("n-x")
    expect(row).to_contain_text(XSS_TITLE)
    expect(row).to_contain_text(XSS_MESSAGE)
    assert row.locator("img, b, script").count() == 0
    assert harness.js("() => window.__xss") is None

    markup = '<img src=x onerror="window.__xss=1">'
    harness.search.fill(markup)
    expect(harness.summary).to_have_text("Showing 1 of 1 notification matching your search.")
    expect(harness.row("n-x")).to_be_visible()
    assert harness.lists_with(q=markup), "The text was not sent as typed."
    assert harness.page.locator("[data-testid=notifications-page-scroll] img").count() == 0
    assert harness.js("() => window.__xss") is None
    expect(harness.search).to_have_value(markup)


# Keyboard focus stays on the control that was pressed -----------------------------------------------

# A browser takes keyboard focus from a button that becomes disabled and leaves it on the page, so a
# reader who pressed Next on the way to the last page, or Refresh, or Mark all read, was dropped at
# the top of the document. These controls stay focusable and say they are unavailable instead.
VIEWPORTS = [
    pytest.param({"width": 1280, "height": 900}, id="desktop"),
    pytest.param({"width": 390, "height": 844}, id="phone"),
]


def unavailable(locator):
    """Unavailable to a reader of the page, and to the eye, without being natively disabled."""
    expect(locator).to_have_attribute("aria-disabled", "true")
    expect(locator).to_be_disabled()
    assert locator.evaluate("(element) => element.disabled") is False, "A native disabled button drops focus."
    look = locator.evaluate("(element) => ({ opacity: Number(getComputedStyle(element).opacity), cursor: getComputedStyle(element).cursor })")
    assert look["opacity"] < 1 and look["cursor"] == "not-allowed", f"An unavailable control must look it: {look}"


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_the_ends_of_the_pager_keep_the_keyboard_and_do_nothing(harness, viewport):
    for number in range(1, 46):
        harness.add(plain_notice(number))
    harness.open("/notifications?page=2", **viewport)
    harness.settled()
    expect(harness.summary).to_have_text("Showing 21\u201340 of 45 notifications.")
    next_button = harness.pager.get_by_role("button", name="Next")
    previous_button = harness.pager.get_by_role("button", name="Previous")

    # Next to the last page. It has nothing further to offer, and the keyboard is still on it.
    next_button.focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 41\u201345 of 45 notifications.")
    harness.expect_focus(next_button, "Next")
    unavailable(next_button)

    # Pressing an unavailable end does nothing at all: no read, no new address, no loss of focus.
    reads = len(harness.list_queries)
    harness.page.keyboard.press("Enter")
    harness.page.keyboard.press("Space")
    harness.page.wait_for_timeout(250)
    assert len(harness.list_queries) == reads, "An unavailable Next asked for another page."
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/notifications?page=3")
    harness.expect_focus(next_button, "Next")

    # Back down to the first page the same way.
    expect(previous_button).not_to_have_attribute("aria-disabled", "true")
    previous_button.focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 21\u201340 of 45 notifications.")
    harness.expect_focus(previous_button, "Previous")
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 1\u201320 of 45 notifications.")
    harness.expect_focus(previous_button, "Previous")
    unavailable(previous_button)
    reads = len(harness.list_queries)
    harness.page.keyboard.press("Enter")
    harness.page.wait_for_timeout(250)
    assert len(harness.list_queries) == reads, "An unavailable Previous asked for another page."
    # The far end is available again, so the keyboard can go back the way it came.
    expect(next_button).not_to_have_attribute("aria-disabled", "true")
    next_button.focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 21\u201340 of 45 notifications.")
    harness.expect_focus(next_button, "Next")


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_a_numbered_page_keeps_the_keyboard_after_the_page_changes(harness, viewport):
    for number in range(1, 121):
        harness.add(plain_notice(number))
    harness.open("/notifications?per_page=10", **viewport)
    harness.settled()
    assert harness.page_numbers() == ["1", "2", "3", "4", "5", "12"]

    harness.page_button(3).focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 21\u201330 of 120 notifications.")
    expect(harness.page_button(3)).to_have_attribute("aria-current", "page")
    harness.expect_focus(harness.page_button(3), "Page 3")

    # The window of numbers moves with the page, and the button just pressed is always in it.
    harness.page_button(5).focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 41\u201350 of 120 notifications.")
    assert harness.page_numbers() == ["1", "4", "5", "6", "12"]
    harness.expect_focus(harness.page_button(5), "Page 5")

    # Tab goes on to the next number, and pressing it goes on from there.
    harness.page.keyboard.press("Tab")
    harness.expect_focus(harness.page_button(6), "Page 6")
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 51\u201360 of 120 notifications.")
    assert harness.page_numbers() == ["1", "5", "6", "7", "12"]
    harness.expect_focus(harness.page_button(6), "Page 6")

    # Into the last pages the window gives way to the end, and still holds the button pressed.
    harness.page_button(12).focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("Showing 111\u2013120 of 120 notifications.")
    harness.expect_focus(harness.page_button(12), "Page 12")
    unavailable(harness.pager.get_by_role("button", name="Next"))


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_refresh_keeps_the_keyboard_while_it_reads_and_afterwards(harness, viewport):
    actionable_inbox(harness)
    harness.open("/notifications", **viewport)
    harness.settled()
    expect(harness.refresh).not_to_have_attribute("aria-disabled", "true")
    harness.refresh.focus()

    harness.hold_lists = True
    harness.page.keyboard.press("Enter")
    harness.wait_for(lambda: len(harness.held_lists) == 1, "Refresh did not read the list again.")
    # While it reads it says so and is unavailable, and it is still the control the keyboard is on.
    harness.expect_focus(harness.refresh, "Refresh")
    unavailable(harness.refresh)
    expect(harness.refresh).to_have_attribute("aria-busy", "true")
    # A press meanwhile is ignored rather than started over.
    harness.page.keyboard.press("Enter")
    harness.page.wait_for_timeout(250)
    assert len(harness.held_lists) == 1, "A second read was started while the first was on its way."

    harness.hold_lists = False
    harness.release_lists()
    expect(harness.refresh).not_to_have_attribute("aria-disabled", "true")
    expect(harness.refresh).not_to_have_attribute("aria-busy", "true")
    harness.expect_focus(harness.refresh, "Refresh")
    # And it works again from the keyboard.
    reads = len(harness.list_queries)
    harness.page.keyboard.press("Enter")
    harness.wait_for(lambda: len(harness.list_queries) == reads + 1, "Refresh did not work a second time.")
    harness.settled()
    harness.expect_focus(harness.refresh, "Refresh")


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_mark_all_read_keeps_the_keyboard_through_the_request_and_when_nothing_is_left(harness, viewport):
    actionable_inbox(harness)
    harness.open("/notifications", **viewport)
    harness.settled()
    expect(harness.mark_all).not_to_have_attribute("aria-disabled", "true")
    harness.mark_all.focus()

    harness.hold_mark_all = True
    harness.page.keyboard.press("Enter")
    harness.wait_for(lambda: len(harness.held_mark_all) == 1, "Mark all read did not reach the server.")
    # On its way it is unavailable, and the keyboard is still on it. A second press sends nothing.
    harness.expect_focus(harness.mark_all, "Mark all read")
    unavailable(harness.mark_all)
    harness.page.keyboard.press("Enter")
    harness.page.wait_for_timeout(250)
    assert harness.mark_all_calls == 1, "Mark all read was sent twice."

    harness.hold_mark_all = False
    harness.release_mark_all()
    harness.wait_for(lambda: not harness.unread(), "The server did not mark everything read.")
    harness.settle_count()
    harness.settled()
    expect(harness.bell).to_have_attribute("data-unread-count", "0")
    # Nothing is left unread, so there is nothing more for it to do, and the keyboard is still on it.
    harness.expect_focus(harness.mark_all, "Mark all read")
    unavailable(harness.mark_all)
    harness.page.keyboard.press("Enter")
    harness.page.wait_for_timeout(250)
    assert harness.mark_all_calls == 1, "Mark all read was sent with nothing unread."


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_a_refused_mark_all_read_leaves_the_keyboard_on_a_control_that_works_again(harness, viewport):
    actionable_inbox(harness)
    harness.open("/notifications", **viewport)
    harness.settled()
    harness.mark_all.focus()

    harness.fail_next.add("mark_all")
    harness.page.keyboard.press("Enter")
    expect(harness.toast("Internal server error")).to_be_visible()
    harness.settled()
    assert len(harness.unread()) == 7
    expect(harness.mark_all).not_to_have_attribute("aria-disabled", "true")
    harness.expect_focus(harness.mark_all, "Mark all read")
    # The line above the list says nothing about unread notifications that are still unread.
    expect(harness.summary).to_have_text("Showing 1\u20138 of 8 notifications.")


def test_mark_all_read_says_so_in_the_line_above_the_list_once_and_only_once(harness):
    actionable_inbox(harness)
    harness.open("/notifications")
    harness.settled()
    expect(harness.summary).to_have_text("Showing 1\u20138 of 8 notifications.")

    harness.mark_all.focus()
    harness.page.keyboard.press("Enter")
    # The sentence the Unread list already uses for nothing to show, added to the line the page
    # announces, so the outcome is heard in the filters that still list everything.
    expect(harness.summary).to_have_text("Showing 1\u20138 of 8 notifications. No unread notifications.")
    harness.expect_focus(harness.mark_all, "Mark all read")

    # Reading the list again says what it shows and no more.
    harness.refresh.click()
    expect(harness.summary).to_have_text("Showing 1\u20138 of 8 notifications.")

    # Where the filter already says it, it is not said twice.
    for number in range(9, 12):
        harness.add(plain_notice(number))
    harness.refresh.click()
    expect(harness.summary).to_have_text("Showing 1\u201311 of 11 notifications.")
    harness.filter("unread").click()
    expect(harness.summary).to_have_text("Showing 1\u20133 of 3 unread notifications.")
    harness.mark_all.focus()
    harness.page.keyboard.press("Enter")
    expect(harness.summary).to_have_text("No unread notifications.")
    harness.expect_focus(harness.mark_all, "Mark all read")


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_try_again_keeps_the_keyboard_in_the_results_and_returns_to_the_button_if_the_read_fails_again(harness, viewport):
    harness.add(plain_notice(1))
    harness.list_failure = True
    harness.open("/notifications", **viewport)
    harness.settled()
    retry = harness.page.get_by_role("button", name="Try again")
    expect(retry).to_be_visible()
    retry.focus()

    # The explanation, and the button on it, go while the read is on its way. A read that fails again
    # brings them back, and the keyboard returns to the button it pressed instead of being left on the page.
    reads = len(harness.list_queries)
    harness.page.keyboard.press("Enter")
    harness.wait_for(lambda: len(harness.list_queries) == reads + 1, "Try again did not read the list.")
    harness.settled()
    expect(retry).to_be_visible()
    harness.expect_focus(retry, "Try again")

    # A read that works: the keyboard waits in the list while it is on its way, and stays there.
    harness.list_failure = False
    harness.hold_lists = True
    harness.page.keyboard.press("Enter")
    harness.wait_for(lambda: len(harness.held_lists) == 1, "Try again did not read the list a second time.")
    harness.expect_focus(harness.results, "the list of notifications")
    harness.hold_lists = False
    harness.release_lists()
    expect(harness.row("n-001")).to_be_visible()
    expect(retry).to_have_count(0)
    harness.expect_focus(harness.results, "the list of notifications")


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_try_again_under_a_list_that_may_be_out_of_date_keeps_the_keyboard_in_the_results(harness, viewport):
    harness.add(plain_notice(1), plain_notice(2))
    harness.open("/notifications", **viewport)
    harness.settled()
    harness.list_failure = True
    harness.refresh.click()
    failure = harness.page.locator("[data-notifications-error]")
    expect(failure).to_contain_text("What is shown may be out of date.")
    retry = failure.get_by_role("button", name="Try again")
    retry.focus()

    harness.list_failure = False
    harness.page.keyboard.press("Enter")
    expect(failure).to_have_count(0)
    expect(harness.summary).to_have_text("Showing 1\u20132 of 2 notifications.")
    harness.expect_focus(harness.results, "the list of notifications")
