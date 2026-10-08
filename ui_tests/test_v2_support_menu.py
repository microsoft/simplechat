# test_v2_support_menu.py
"""
Browser coverage for the V2 Support menu: the rail group, the Latest Features page and the
Send Feedback page.
Version: 0.261.296
Implemented in: 0.261.296

Administrators configure the Support menu in Admin Settings. The classic navigation offers it
to users as a collapsible section; V2 used to carry only a Latest Features link that left for
the classic page, and no Send Feedback at all. V2 now draws a Support group in its rail and has
its own pages for both destinations.

Serve the real built SPA through Playwright request interception with a closed API boundary.
Check that the rail offers what the bootstrap payload offers and remembers its open state
without discarding the classic interface's menus, including when preferences failed to load; that hiding Latest Features leaves Send
Feedback; that the Latest Features page lists, opens and searches announcements and routes its
shortcuts inside V2; that both pages explain when they are switched off; that Send Feedback
validates before posting and then prepares a draft; and that both pages fit a phone.
Unexpected requests and page errors fail.
"""

import copy
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options  # noqa: E402,F401
from v2_notification_stubs import is_notification_count, notification_count_payload  # noqa: E402


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
ARTIFACTS = REPO_ROOT / "ui_tests" / "artifacts" / "v2_support_menu"
ORIGIN = "http://simplechat.test"
VERSION = "0.261.296"

# Chromium has no mail handler in the test browser, so opening a draft logs this.
MAILTO_LAUNCH_ERROR = re.compile(r"Failed to launch 'mailto:")


def _action(label, description, icon, href, kind="page", requires=()):
    return {
        "label": label,
        "description": description,
        "icon": icon,
        "kind": kind,
        "href": href,
        "requires_settings": list(requires),
    }


LATEST_FEATURES = {
    "version": VERSION,
    "groups": [
        {
            "id": "current_release",
            "label": "Latest Features",
            "description": "Everything released after v0.250.001 that your admins are sharing with end users.",
            "release_version": "0.261.001",
            "default_expanded": True,
            "features": [
                {
                    "id": "release_260_charts",
                    "title": "Chart Creation in Chat",
                    "icon": "bi-bar-chart-line",
                    "summary": "Ask Contoso Chat to turn data in a conversation into a chart.",
                    "details": "Chart requests turn pasted values, spreadsheets and computed results into visual answers.",
                    "why": "This matters because trends and outliers are easier to see in a chart than in a table.",
                    "guidance": [
                        "Ask Chat for a bar, line or pie chart of the data you are discussing.",
                        "Pair the request with an uploaded CSV or Excel file.",
                    ],
                    "images": [
                        {
                            "url": "/static/images/features/release_250_charts.png",
                            "alt": "A bar chart drawn in a chat reply",
                            "title": "Charts in Chat",
                            "caption": "A chart created from spreadsheet results.",
                            "label": "Chart creation",
                        }
                    ],
                    "actions": [
                        _action("Open Chat", "Ask for a chart from data in your conversation.", "bi-chat-dots", "/chats#chatbox"),
                        _action("Open Agents", "Browse the agents available to your account.", "bi-robot", "/agents"),
                        _action(
                            "Read the guide",
                            "Step-by-step chart examples.",
                            "bi-journal-bookmark",
                            "https://microsoft.github.io/simplechat/latest-release/",
                            kind="external",
                            requires=("enable_support_latest_feature_documentation_links",),
                        ),
                    ],
                },
                {
                    "id": "send_feedback",
                    "title": "Send Feedback",
                    "icon": "bi-envelope-paper",
                    "summary": "Report a bug or request a feature from the Support menu.",
                    "details": "The form prepares an email draft for your administrators.",
                    "why": "This matters because a complete report is faster to act on.",
                    "guidance": ["Open Send Feedback from the Support menu."],
                    "images": [],
                    "actions": [
                        _action("Open Send Feedback", "Prepare a bug report or feature request.", "bi-envelope-paper", "/support/send-feedback"),
                    ],
                },
                {
                    "id": "release_260_processing",
                    "title": "Faster Document Processing",
                    "icon": "bi-speedometer",
                    "summary": "Large uploads finish sooner.",
                    "details": "Document processing now runs more stages in parallel.",
                    "why": "This matters because you can ask about a document sooner after uploading it.",
                    "guidance": [],
                    "images": [],
                    "actions": [],
                },
            ],
        },
        {
            "id": "previous_release",
            "label": "Previous Release Features",
            "description": "The v0.250.001 feature set remains available for reference.",
            "release_version": "0.250.001",
            "default_expanded": False,
            "features": [
                {
                    "id": "release_250_tabular_analysis",
                    "title": "Improved Tabular Analysis",
                    "icon": "bi-table",
                    "summary": "Spreadsheet questions page through larger results.",
                    "details": "Workbook answers keep sheet context.",
                    "why": "This matters because spreadsheet questions need exact calculations.",
                    "guidance": ["Ask about a CSV or Excel file from Chat."],
                    "images": [],
                    "actions": [
                        _action("Open My Workspace", "Upload a workbook.", "bi-folder2-open", "/workspace#documents-tab"),
                    ],
                },
            ],
        },
    ],
}


class SupportMenuFixture:
    """The V2 shell with an in-memory API for the Support menu and its two pages."""

    def __init__(self, page: Page, *, latest_available=True, feedback_available=True):
        self.page = page
        self.latest_available = latest_available
        self.feedback_available = feedback_available
        self.latest_status = 200
        self.latest_requests = 0
        self.settings_status = 200
        self.feedback_posts = []
        self.settings_posts = []
        self.document_loads = 0
        self.errors = []
        self.unexpected_requests = []
        self.preferences = {}
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on(
            "console",
            lambda message: self.errors.append(message.text) if message.type == "error" else None,
        )
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": VERSION,
            "user": {
                "id": "user-1",
                "display_name": "Riley Analyst",
                "email": "riley@contoso.test",
                "is_admin": False,
                "roles": ["User"],
            },
            "branding": {"app_title": "Contoso Chat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {
                "custom_pages": {"enabled": False, "items": []},
                "external_links": {"enabled": False, "items": []},
                "latest_features": {
                    "available": self.latest_available,
                    "hidden_by_development": False,
                    "url": "/support/latest-features",
                    "menu_name": "Help Desk",
                },
                "send_feedback": {
                    "available": self.feedback_available,
                    "url": "/support/send-feedback",
                    "menu_name": "Help Desk",
                },
            },
            "workspace": {"sections": {}},
            "settings": {},
        }

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
            return
        method = request.method
        if method == "GET" and (path == "/v2" or path.startswith("/v2/")):
            self.document_loads += 1
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
        elif method == "GET" and path.startswith("/static/"):
            asset = (STATIC_ROOT / unquote(path.removeprefix("/static/"))).resolve()
            if asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file():
                route.fulfill(path=str(asset))
            else:
                self.unexpected_requests.append(path)
                route.fulfill(status=404, body="Fixture asset not found")
        elif method == "GET" and path == "/api/v2/bootstrap":
            route.fulfill(json=self._bootstrap())
        elif path == "/api/user/settings":
            if method == "GET" and self.settings_status != 200:
                route.fulfill(status=self.settings_status, json={"error": "Failed to load your preferences."})
            elif method == "GET":
                route.fulfill(json={"settings": copy.deepcopy(self.preferences)})
            else:
                posted = request.post_data_json["settings"]
                self.settings_posts.append(posted)
                self.preferences.update(posted)
                route.fulfill(json={"message": "Saved."})
        elif is_notification_count(method, path):
            route.fulfill(json=notification_count_payload())
        elif method == "GET" and path == "/api/v2/support/latest-features":
            self.latest_requests += 1
            if self.latest_status == 200:
                route.fulfill(json=copy.deepcopy(LATEST_FEATURES))
            elif self.latest_status == 404:
                route.fulfill(status=404, json={"error": "Latest Features is not available."})
            else:
                route.fulfill(status=500, json={"error": "Failed to load Latest Features."})
        elif method == "POST" and path == "/api/support/send_feedback_email":
            body = request.post_data_json
            self.feedback_posts.append(body)
            label = "Bug Report" if body["feedbackType"] == "bug_report" else "Feature Request"
            route.fulfill(json={
                "success": True,
                "recipientEmail": "help@contoso.test",
                "subjectLine": f"[Contoso Chat User Support] {label} - {body['organization']}",
                "feedbackLabel": label,
            })
        else:
            self.unexpected_requests.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, path, *, width=1440, height=900, preferences=None):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": False, **(preferences or {})}
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}{path}", wait_until="networkidle")

    def rail(self):
        return self.page.get_by_role("navigation", name="Primary")

    def screenshot(self, name):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)

    def assert_clean(self):
        self.errors = [error for error in self.errors if not MAILTO_LAUNCH_ERROR.search(error)]
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors


@pytest.fixture
def support_ui(page):
    fixture = SupportMenuFixture(page)
    yield fixture
    fixture.assert_clean()


def _no_horizontal_overflow(page):
    overflow = page.get_by_test_id("support-page-scroll").evaluate(
        "element => Math.max(element.scrollWidth - element.clientWidth, "
        "document.documentElement.scrollWidth - document.documentElement.clientWidth)"
    )
    assert overflow <= 1, f"The page scrolls sideways by {overflow}px"


def _settings_saved(page, key):
    """Wait for the debounced preference write that carries ``key`` to be answered."""

    def carries_key(response):
        if not response.url.endswith("/api/user/settings") or response.request.method != "POST":
            return False
        return key in ((response.request.post_data_json or {}).get("settings") or {})

    return page.expect_response(carries_key)


def test_rail_offers_both_destinations_and_remembers_the_menu(support_ui):
    support_ui.open(
        "/v2/support/latest-features",
        preferences={"sidebarMenuState": {"workspaces": False, "externalLinks": True}},
    )
    page = support_ui.page
    menu = support_ui.rail().get_by_test_id("support-menu")

    heading = menu.get_by_role("button", name="Help Desk")
    expect(heading).to_have_attribute("aria-expanded", "true")
    latest = menu.get_by_role("link", name=re.compile("^Latest Features"))
    feedback = menu.get_by_role("link", name="Send Feedback")
    expect(latest).to_have_attribute("href", "/v2/support/latest-features")
    expect(latest).to_have_attribute("aria-current", "page")
    expect(feedback).to_have_attribute("href", "/v2/support/send-feedback")

    with _settings_saved(page, "sidebarMenuState"):
        heading.click()
    expect(heading).to_have_attribute("aria-expanded", "false")
    expect(latest).to_have_count(0)
    assert support_ui.settings_posts[-1] == {
        "sidebarMenuState": {"workspaces": False, "externalLinks": True, "support": False},
    }, "Collapsing the menu must keep the classic interface's own menus"

    with _settings_saved(page, "sidebarMenuState"):
        heading.click()
    expect(feedback).to_be_visible()
    feedback.click()
    expect(page).to_have_url(f"{ORIGIN}/v2/support/send-feedback")
    expect(page.get_by_role("heading", level=1, name="Send Feedback")).to_be_visible()
    assert support_ui.document_loads == 1, "The rail must route inside V2, not reload the page"


def test_hiding_latest_features_keeps_send_feedback(support_ui):
    support_ui.open("/v2/support/send-feedback")
    menu = support_ui.rail().get_by_test_id("support-menu")

    with _settings_saved(support_ui.page, "latestFeaturesHiddenVersion"):
        menu.get_by_role("button", name="Hide Latest Features until the next release").click()
    expect(menu.get_by_role("link", name=re.compile("^Latest Features"))).to_have_count(0)
    expect(menu.get_by_role("link", name="Send Feedback")).to_be_visible()
    assert support_ui.settings_posts[-1] == {"latestFeaturesHiddenVersion": VERSION}


def test_menu_state_is_not_saved_when_preferences_failed_to_load(page):
    """Saving from an empty store would erase every other menu's stored choice."""
    fixture = SupportMenuFixture(page)
    fixture.settings_status = 500
    fixture.open("/v2/support/send-feedback")
    menu = fixture.rail().get_by_test_id("support-menu")

    heading = menu.get_by_role("button", name="Help Desk")
    expect(heading).to_have_attribute("aria-expanded", "true")
    heading.click()
    expect(heading).to_have_attribute("aria-expanded", "false")
    expect(menu.get_by_role("link", name="Send Feedback")).to_have_count(0)
    heading.click()
    expect(heading).to_have_attribute("aria-expanded", "true")

    # A write that is allowed: a top-level key replaces nothing else. Writes are debounced and
    # merged, so any menu-state write queued by the clicks above would travel in this request.
    with _settings_saved(page, "latestFeaturesHiddenVersion"):
        menu.get_by_role("button", name="Hide Latest Features until the next release").click()
    assert not any("sidebarMenuState" in post for post in fixture.settings_posts), (
        "With no preferences loaded, the menu state must stay local: posting it would replace "
        f"the stored object. Posted: {fixture.settings_posts}"
    )
    # The refused preference read is answered with a 500, which the browser logs.
    fixture.errors = [error for error in fixture.errors if "500" not in error]
    fixture.assert_clean()


def test_latest_features_page_lists_reads_and_searches(support_ui):
    support_ui.open("/v2/support/latest-features")
    page = support_ui.page

    expect(page.get_by_role("heading", level=1, name="Latest Features")).to_be_visible()
    expect(page.get_by_text("4 announcements", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Chart Creation in Chat")).to_be_visible()
    expect(page.get_by_role("heading", name="Improved Tabular Analysis")).to_have_count(0)
    support_ui.screenshot("latest-features-desktop")

    details = page.get_by_role("button", name="Details for Chart Creation in Chat")
    details.click()
    expect(details).to_have_attribute("aria-expanded", "true")
    panel = page.locator("#latest-features-release-260-charts-card-details")
    expect(panel).to_contain_text("This matters because trends and outliers")
    expect(panel.get_by_text("How to try it")).to_be_visible()
    expect(panel.get_by_role("link", name="Open Chat")).to_have_attribute("href", "/v2/chat")
    expect(panel.get_by_role("link", name=re.compile("^Open Agents"))).to_have_attribute("href", "/agents")
    guide = panel.get_by_role("link", name=re.compile("^Read the guide"))
    expect(guide).to_have_attribute("target", "_blank")
    expect(guide).to_have_attribute("rel", "noopener noreferrer")
    expect(panel.get_by_role("button", name=re.compile("Chart creation"))).to_be_visible()
    support_ui.screenshot("latest-features-details-desktop")

    page.get_by_role("button", name="Details for Faster Document Processing").click()
    expect(page.locator("#latest-features-release-260-processing-card-details")).to_contain_text(
        "behind-the-scenes improvement"
    )

    search = page.get_by_role("searchbox", name="Search announcements")
    search.fill("spreadsheet")
    expect(page.get_by_text("2 of 4 announcements match")).to_be_visible()
    expect(page.get_by_role("heading", name="Improved Tabular Analysis")).to_be_visible()
    search.fill("zebra")
    expect(page.get_by_text("No announcements match")).to_be_visible()
    search.fill("")

    page.get_by_role("button", name="Details for Send Feedback").click()
    page.locator("#latest-features-send-feedback-card-details").get_by_role(
        "link", name="Open Send Feedback"
    ).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/support/send-feedback")
    expect(page.get_by_role("heading", level=1, name="Send Feedback")).to_be_visible()
    assert support_ui.document_loads == 1, "A translated shortcut must route inside V2"


def test_latest_features_page_explains_when_switched_off(page):
    fixture = SupportMenuFixture(page, latest_available=False)
    fixture.latest_status = 404
    fixture.open("/v2/support/latest-features")
    expect(page.get_by_text("Latest Features is not available")).to_be_visible()
    expect(page.get_by_role("searchbox")).to_have_count(0)
    expect(fixture.rail().get_by_role("link", name=re.compile("^Latest Features"))).to_have_count(0)
    # The refused load is answered with a 404, which the browser logs; it is the point here.
    fixture.errors = [error for error in fixture.errors if "404" not in error]
    fixture.assert_clean()


def test_latest_features_page_recovers_from_a_failed_load(page):
    fixture = SupportMenuFixture(page)
    fixture.latest_status = 500
    fixture.open("/v2/support/latest-features")
    expect(page.get_by_role("alert")).to_contain_text("could not be loaded")

    fixture.latest_status = 200
    page.get_by_role("button", name="Try again").click()
    expect(page.get_by_role("heading", name="Chart Creation in Chat")).to_be_visible()
    assert fixture.latest_requests == 2
    fixture.errors = [error for error in fixture.errors if "500" not in error]
    fixture.assert_clean()


def test_send_feedback_validates_then_prepares_a_draft(support_ui):
    support_ui.open("/v2/support/send-feedback")
    page = support_ui.page
    form = page.get_by_role("form", name="Send Feedback")

    expect(page.get_by_text("Report a problem or request an improvement from your Contoso Chat administrators.")).to_be_visible()
    expect(form.get_by_label("Name")).to_have_value("Riley Analyst")
    expect(form.get_by_label("Email")).to_have_value("riley@contoso.test")
    support_ui.screenshot("send-feedback-desktop")

    form.get_by_role("button", name="Open Bug Report Draft").click()
    expect(form.get_by_role("alert")).to_contain_text("Complete the highlighted fields")
    expect(form.get_by_label("Organization")).to_be_focused()
    expect(form.get_by_label("Organization")).to_have_attribute("aria-invalid", "true")
    expect(form.get_by_text("Enter your organization.")).to_be_visible()
    assert support_ui.feedback_posts == [], "An incomplete report must not be posted"
    support_ui.screenshot("send-feedback-errors-desktop")

    form.get_by_label("Organization").fill("Contoso")
    form.get_by_label("Bug Details").fill("Citations do not open after an upload.")

    # Each kind keeps its own details.
    form.get_by_text("Feature Request", exact=True).click()
    expect(form.get_by_label("Feature Request Details")).to_have_value("")
    expect(form.get_by_role("button", name="Open Feature Request Draft")).to_be_visible()
    form.get_by_text("Bug Report", exact=True).click()
    expect(form.get_by_label("Bug Details")).to_have_value("Citations do not open after an upload.")

    form.get_by_role("button", name="Open Bug Report Draft").click()
    draft = form.get_by_role("link", name="open the draft")
    expect(draft).to_be_visible()
    expect(form).to_contain_text("Draft prepared for help@contoso.test")
    href = draft.get_attribute("href") or ""
    assert href.startswith("mailto:help@contoso.test?subject="), href
    assert "Contoso%20Chat%20User%20Support" in href, href
    assert "Citations%20do%20not%20open" in href and f"App%20Version%3A%20{VERSION}" in href, href

    assert support_ui.feedback_posts == [{
        "feedbackType": "bug_report",
        "reporterName": "Riley Analyst",
        "reporterEmail": "riley@contoso.test",
        "organization": "Contoso",
        "details": "Citations do not open after an upload.",
    }]


def test_send_feedback_page_explains_when_not_offered(page):
    fixture = SupportMenuFixture(page, feedback_available=False)
    fixture.open("/v2/support/send-feedback")
    expect(page.get_by_text("Send Feedback is not available")).to_be_visible()
    expect(page.get_by_role("form")).to_have_count(0)
    menu = fixture.rail().get_by_test_id("support-menu")
    expect(menu.get_by_role("link", name="Send Feedback")).to_have_count(0)
    expect(menu.get_by_role("link", name=re.compile("^Latest Features"))).to_be_visible()
    fixture.assert_clean()


def test_support_pages_fit_a_phone(support_ui):
    support_ui.open("/v2/support/send-feedback", width=390, height=844)
    page = support_ui.page
    form = page.get_by_role("form", name="Send Feedback")
    name_box = form.get_by_label("Name").bounding_box()
    email_box = form.get_by_label("Email").bounding_box()
    assert name_box and email_box
    assert email_box["y"] > name_box["y"], "Name and Email should stack on a phone"
    _no_horizontal_overflow(page)
    support_ui.screenshot("send-feedback-phone")

    support_ui.open("/v2/support/latest-features", width=390, height=844)
    page.get_by_role("button", name="Details for Chart Creation in Chat").click()
    expect(page.locator("#latest-features-release-260-charts-card-details")).to_be_visible()
    _no_horizontal_overflow(page)
    support_ui.screenshot("latest-features-phone")
