# test_v2_profile_photo_refresh.py
"""
Browser coverage for "Refresh photo" on the V2 User Settings page.
Version: 0.261.448
Implemented in: 0.261.448

Serve the real built SPA through Playwright request interception with a closed API
boundary. Check that the control has an accessible name, shows a busy state and takes only one
request however often it is activated; that a new photo replaces the picture in the rail and in
the Settings header at once, without being written back through the settings route; that "no
photo" falls back to initials in both places; that a photo which could not be decoded gives way
to the one fetched next; that a failure keeps the photo on screen, says so in a status region
and never repeats what the server sent; that an ended session shows the existing sign-in
notice; and that the control and its message fit a phone. Unexpected requests and page errors
fail.
"""

import base64
import copy
import struct
import sys
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from color_contrast import CONTRAST_RATIO_SCRIPT  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401
from v2_notification_stubs import is_notification_count, notification_count_payload  # noqa: E402


pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
ORIGIN = "http://simplechat.test"
REFRESH_PATH = "/api/profile/image/refresh"
AA_TEXT = 4.5

UPDATED = "Your photo was updated from Microsoft 365."
NONE_FOUND = "Microsoft 365 did not return a photo, so your initials are shown."
FAILED = "We couldn't refresh your photo. Try again in a moment."
OFFLINE = "We couldn't reach SimpleChat. Check your connection and try again."
SIGN_IN = "Sign in again to refresh your photo."


def solid_png(red, green, blue, size=16):
    """A valid solid-colour PNG, so an <img> really decodes it."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes([red, green, blue]) * size
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


OLD_PHOTO = solid_png(200, 30, 30)
NEW_PHOTO = solid_png(30, 60, 200)
BROKEN_PHOTO = "data:image/png;base64,AAAA"

# What the Preferences tab, which opens first, reads besides the user's settings: the fact
# memory and Microsoft 365 cards, answered as an account with neither set up would see them.
PREFERENCES_TAB_READS = {
    "/api/profile/fact-memory": {"success": True, "enabled": False, "instruction_count": 0,
                                 "fact_count": 0, "facts": []},
    "/api/m365/preferences": {
        "success": True, "csrf_token": "photo-ui-csrf-token-000000000001",
        "preferences": {"sources": {"calendar": "ask", "email": "ask", "onedrive": "ask", "spo": "ask"},
                        "extended_analysis": {"onedrive": "ask", "spo": "ask"}},
    },
    "/api/m365/chat/connection": {
        "success": True, "csrf_token": "photo-ui-csrf-token-000000000001",
        "connection": {"status": "not_connected", "sources": [], "persistence": "session"},
    },
    "/api/m365/connections": {
        "success": True, "connection": None, "csrf_token": "photo-ui-csrf-token-000000000001",
        "workflow_connections": {"available": True, "reason": None, "message": ""},
    },
    "/api/m365/bindings": {"items": [], "continuation_token": None},
}


class PhotoFixture:
    """The V2 Settings page with an in-memory API for the user's photo."""

    def __init__(self, page: Page, *, photo=OLD_PHOTO, dark=False):
        self.page = page
        self.preferences = {"darkModeEnabled": dark, "profileImage": photo}
        if dark:
            page.add_init_script("localStorage.setItem('simplechat.v2.theme', 'dark')")
        self.refreshes = []
        self.settings_writes = []
        self.answer = {"status": 200, "json": {"success": True, "message": "Profile image updated successfully",
                                               "profileImage": NEW_PHOTO}}
        self.hold = False
        self.held = []
        self.abort_next = False
        self.errors = []
        self.failed_resources = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on("console", self._console)
        page.route("**/*", self._route)

    def _console(self, message):
        if message.type != "error":
            return
        if "Failed to load resource" in message.text:
            self.failed_resources.append(message.text)
        else:
            self.errors.append(message.text)

    def bootstrap(self):
        return {
            "version": "0.261.448",
            "user": {"id": "user-1", "display_name": "Test User", "email": "test.user@contoso.test",
                     "is_admin": False, "roles": ["User"]},
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {"custom_pages": {"enabled": False, "items": []},
                           "external_links": {"enabled": False, "items": []}},
            "workspace": {"sections": {}},
            "safety_warnings": {"pending": 0},
            "settings": {},
        }

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        method = request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
        elif method == "GET" and (path == "/v2" or path.startswith("/v2/")):
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
        elif method == "GET" and path.startswith("/static/"):
            asset = (STATIC_ROOT / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file():
                route.fulfill(path=str(asset))
            else:
                self.unexpected_requests.append(path)
                route.fulfill(status=404, body="Fixture asset not found")
        elif method == "GET" and path == "/api/v2/bootstrap":
            route.fulfill(json=self.bootstrap())
        elif path == "/api/user/settings":
            if method == "GET":
                route.fulfill(json={"settings": copy.deepcopy(self.preferences)})
            else:
                self.settings_writes.append(request.post_data_json)
                self.preferences.update(request.post_data_json["settings"])
                route.fulfill(json={"message": "Saved."})
        elif is_notification_count(method, path):
            route.fulfill(json=notification_count_payload())
        elif method == "GET" and path == "/api/approvals":
            route.fulfill(json={"approvals": [], "total_count": 0, "total_pages": 1})
        elif method == "GET" and path in PREFERENCES_TAB_READS:
            route.fulfill(json=PREFERENCES_TAB_READS[path])
        elif method == "POST" and path == REFRESH_PATH:
            self.refreshes.append({
                "body": request.post_data_json,
                "ui": request.headers.get("x-simplechat-ui", ""),
            })
            if self.abort_next:
                self.abort_next = False
                route.abort()
            elif self.hold:
                self.held.append(route)
            else:
                route.fulfill(**self.answer)
        else:
            self.unexpected_requests.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def release(self):
        """Answer the request that was held, so a test can look at the busy state first."""
        self.wait_for_held()
        route = self.held.pop(0)
        route.fulfill(**self.answer)

    def wait_for_held(self, timeout=5000):
        waited = 0
        while not self.held:
            if waited >= timeout:
                raise AssertionError("The refresh request never arrived.")
            self.page.wait_for_timeout(25)
            waited += 25

    def open(self, *, width=1280, height=900):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}/v2/settings", wait_until="networkidle")
        expect(self.page.get_by_role("heading", name="User Settings")).to_be_visible()

    def control(self):
        return self.page.get_by_role("button", name="Refresh photo")

    def photos(self, source):
        """The pictures on screen with this source: the rail's and the Settings header's."""
        return self.page.locator(f'img[src="{source}"]')

    def status(self):
        return self.page.get_by_test_id("v2-settings-photo-status")

    def assert_clean(self, expected_failed_resources=0):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors
        assert len(self.failed_resources) == expected_failed_resources, self.failed_resources


@pytest.fixture
def photo_ui(page):
    fixture = PhotoFixture(page)
    yield fixture
    fixture.assert_clean()


def test_the_control_is_named_and_the_photo_starts_where_the_server_put_it(photo_ui):
    photo_ui.open()
    expect(photo_ui.control()).to_be_visible()
    expect(photo_ui.control()).to_be_enabled()
    expect(photo_ui.photos(OLD_PHOTO)).to_have_count(2)
    expect(photo_ui.status()).to_have_text("")
    assert photo_ui.refreshes == []


def test_a_new_photo_replaces_the_picture_in_the_rail_and_the_header(photo_ui):
    photo_ui.open()
    photo_ui.hold = True
    control = photo_ui.control()

    control.click()
    expect(control).to_be_disabled()
    expect(control).to_have_attribute("aria-busy", "true")
    expect(photo_ui.photos(OLD_PHOTO)).to_have_count(2)
    photo_ui.wait_for_held()
    assert photo_ui.refreshes == [{"body": {}, "ui": "v2"}]

    photo_ui.release()
    expect(photo_ui.photos(NEW_PHOTO)).to_have_count(2)
    expect(photo_ui.photos(OLD_PHOTO)).to_have_count(0)
    expect(photo_ui.status()).to_have_text(UPDATED)
    expect(control).to_be_enabled()
    expect(control).not_to_have_attribute("aria-busy", "true")
    expect(control).to_be_focused()
    assert photo_ui.settings_writes == [], "the photo is not posted back through the settings route"


def test_no_photo_falls_back_to_initials_in_both_places(photo_ui):
    photo_ui.answer = {"status": 200, "json": {"success": True, "message": "No profile image found",
                                                "profileImage": None}}
    photo_ui.open()
    expect(photo_ui.photos(OLD_PHOTO)).to_have_count(2)

    photo_ui.control().click()
    expect(photo_ui.status()).to_have_text(NONE_FOUND)
    expect(photo_ui.page.locator('img[src^="data:image"]')).to_have_count(0)
    expect(photo_ui.page.get_by_text("TU", exact=True)).to_have_count(2)
    assert photo_ui.settings_writes == []


def test_a_photo_that_could_not_be_decoded_gives_way_to_the_next_one(page):
    fixture = PhotoFixture(page, photo=BROKEN_PHOTO)
    fixture.open()
    expect(page.get_by_text("TU", exact=True)).to_have_count(2)

    fixture.control().click()
    expect(fixture.photos(NEW_PHOTO)).to_have_count(2)
    expect(page.get_by_text("TU", exact=True)).to_have_count(0)
    fixture.assert_clean()


def test_a_second_activation_while_the_first_runs_sends_no_second_request(photo_ui):
    photo_ui.open()
    photo_ui.hold = True
    control = photo_ui.control()
    control.click()
    control.click(force=True)
    control.dispatch_event("click")
    photo_ui.wait_for_held()
    photo_ui.page.wait_for_timeout(150)
    assert len(photo_ui.refreshes) == 1
    photo_ui.release()
    expect(photo_ui.status()).to_have_text(UPDATED)


def test_the_control_works_from_the_keyboard(photo_ui):
    photo_ui.open()
    photo_ui.control().focus()
    photo_ui.page.keyboard.press("Enter")
    expect(photo_ui.status()).to_have_text(UPDATED)
    expect(photo_ui.control()).to_be_focused()
    photo_ui.answer = {"status": 200, "json": {"success": True, "message": "ok", "profileImage": OLD_PHOTO}}
    photo_ui.page.keyboard.press("Space")
    expect(photo_ui.photos(OLD_PHOTO)).to_have_count(2)
    assert len(photo_ui.refreshes) == 2


def test_a_failed_refresh_keeps_the_photo_says_so_and_repeats_nothing_the_server_sent(page):
    fixture = PhotoFixture(page)
    leak = "SECRET-DIAGNOSTIC-" + NEW_PHOTO[:60]
    fixture.answer = {"status": 500, "json": {"error": leak}}
    fixture.open()

    fixture.control().click()
    alert = page.get_by_test_id("v2-settings-photo-error")
    expect(alert).to_have_text(FAILED)
    expect(fixture.photos(OLD_PHOTO)).to_have_count(2)
    expect(fixture.control()).to_be_enabled()
    assert "SECRET-DIAGNOSTIC" not in page.locator("body").inner_text()
    assert NEW_PHOTO[:60] not in page.locator("body").inner_text()
    fixture.assert_clean(expected_failed_resources=1)


def test_an_unreadable_answer_is_a_failure_that_does_not_quote_it(page):
    fixture = PhotoFixture(page)
    fixture.answer = {"status": 200, "json": {"success": True, "profileImage": {"data": NEW_PHOTO}}}
    fixture.open()

    fixture.control().click()
    expect(page.get_by_test_id("v2-settings-photo-error")).to_have_text(FAILED)
    expect(fixture.photos(OLD_PHOTO)).to_have_count(2)
    assert NEW_PHOTO not in page.locator("body").inner_text()
    fixture.assert_clean()


def test_a_dropped_connection_is_reported_as_one_and_can_be_retried(page):
    fixture = PhotoFixture(page)
    fixture.open()
    fixture.abort_next = True

    fixture.control().click()
    expect(page.get_by_test_id("v2-settings-photo-error")).to_have_text(OFFLINE)
    expect(fixture.photos(OLD_PHOTO)).to_have_count(2)

    fixture.control().click()
    expect(page.get_by_test_id("v2-settings-photo-status")).to_have_text(UPDATED)
    expect(page.get_by_test_id("v2-settings-photo-error")).to_have_count(0)
    expect(fixture.photos(NEW_PHOTO)).to_have_count(2)
    # The browser logs the dropped request itself; nothing else may be logged.
    assert not fixture.errors, fixture.errors
    assert not fixture.unexpected_requests


def test_an_ended_session_shows_the_existing_sign_in_notice(page):
    fixture = PhotoFixture(page)
    fixture.answer = {"status": 401, "json": {
        "error": "Session expired", "message": "Your session expired due to inactivity.", "requires_reauth": True}}
    fixture.open()

    fixture.control().click()
    expect(page.get_by_test_id("v2-session-notice")).to_be_visible()
    expect(page.get_by_test_id("v2-settings-photo-error")).to_have_text(SIGN_IN)
    expect(fixture.photos(OLD_PHOTO)).to_have_count(2)
    fixture.assert_clean(expected_failed_resources=1)


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_the_messages_are_readable_in_light_and_dark(page, dark):
    fixture = PhotoFixture(page, dark=dark)
    fixture.open()
    assert page.evaluate("document.documentElement.classList.contains('dark')") == dark
    ratios = {"control": fixture.control().evaluate(CONTRAST_RATIO_SCRIPT, "color")}

    fixture.control().click()
    expect(fixture.status()).to_have_text(UPDATED)
    ratios["updated"] = fixture.status().evaluate(CONTRAST_RATIO_SCRIPT, "color")

    fixture.answer = {"status": 200, "json": {"success": True, "profileImage": None}}
    fixture.control().click()
    expect(fixture.status()).to_have_text(NONE_FOUND)
    ratios["no photo"] = fixture.status().evaluate(CONTRAST_RATIO_SCRIPT, "color")

    fixture.answer = {"status": 500, "json": {"error": "x"}}
    fixture.control().click()
    alert = page.get_by_test_id("v2-settings-photo-error")
    expect(alert).to_have_text(FAILED)
    ratios["failed"] = alert.evaluate(CONTRAST_RATIO_SCRIPT, "color")

    too_faint = {name: round(ratio, 2) for name, ratio in ratios.items() if ratio < AA_TEXT}
    assert not too_faint, f"Below {AA_TEXT}:1 in {'dark' if dark else 'light'} mode: {too_faint}"
    fixture.assert_clean(expected_failed_resources=1)


def test_the_control_and_its_message_fit_a_phone(page):
    fixture = PhotoFixture(page)
    fixture.open(width=390, height=844)
    control = fixture.control()
    expect(control).to_be_visible()
    expect(control).to_have_accessible_name("Refresh photo")
    box = control.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44, box
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390, box

    control.click()
    expect(fixture.status()).to_have_text(UPDATED)
    expect(fixture.status()).to_be_in_viewport()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    fixture.answer = {"status": 500, "json": {"error": "x"}}
    control.click()
    alert = page.get_by_test_id("v2-settings-photo-error")
    expect(alert).to_have_text(FAILED)
    expect(alert).to_be_in_viewport()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    fixture.assert_clean(expected_failed_resources=1)
