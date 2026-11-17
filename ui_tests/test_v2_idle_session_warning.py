# test_v2_idle_session_warning.py
"""
Browser coverage for the V2 idle-session warning.
Version: 0.261.448
Implemented in: 0.261.448

Serve the real built SPA through Playwright request interception with a closed API boundary,
and control the page's clock. Check that the warning opens at the administrator's warning
time with a live countdown and the administrator's sentence as plain text; that "Stay signed
in" posts the heartbeat through the shared API client and restarts the clock; that "Logout
now" and the end of the countdown leave through the local sign-out; that an active user is
reported to the server and is never warned or signed out, including when the input is a scroll
inside a pane or happens inside an embedded same-origin frame; that a disabled timeout, a warning
time equal to the timeout and a server that sends no session block each behave as promised;
that the dialog is an alert dialog that keeps focus inside, ignores Escape and passing input,
is readable in light and dark, and fits a phone; that a heartbeat the server refuses as an ended
session shows the existing sign-in notice instead of signing the user out, and a failed one
offers a retry; and that an idle tab does not sign out a session in use in another tab, while
two untouched tabs both warn. Unexpected requests and page errors fail.
"""

import copy
import sys
from datetime import datetime, timedelta, timezone
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
START = datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc)
AA_TEXT = 4.5

SECOND = 1000
MINUTE = 60 * SECOND
HEARTBEAT_PATH = "/api/session/heartbeat"
SIGN_OUT_PATH = "/logout/local"
FRAME_PATH = "/embedded-page-stub"

IDLE = {
    "enabled": True,
    "timeout_minutes": 30,
    "warning_minutes": 28,
    "warning_message": "Still there?",
}
SESSION_EXPIRED = {
    "error": "Session expired",
    "message": "Your session expired due to inactivity. Please sign in again.",
    "requires_reauth": True,
}


class IdleFixture:
    """The V2 app with an in-memory API: bootstrap, the heartbeat and the local sign-out."""

    def __init__(self, page: Page, *, idle=None, session_block=True):
        self.page = page
        self.idle = copy.deepcopy(IDLE if idle is None else idle)
        self.session_block = session_block
        self.dark = False
        self.heartbeats = []
        self.heartbeat_status = 200
        self.heartbeat_payload = {"message": "Session refreshed", "idle_timeout_minutes": 30}
        self.signed_out = []
        self.errors = []
        self.failed_resources = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on("console", self._console)
        page.route("**/*", self._route)

    def _console(self, message):
        if message.type != "error":
            return
        # The browser reports every refused request as a console error; a test that makes the
        # server refuse one says so with expected_failed_resources.
        if "Failed to load resource" in message.text:
            self.failed_resources.append(message.text)
        else:
            self.errors.append(message.text)

    def bootstrap(self):
        payload = {
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
        if self.session_block:
            payload["session"] = {"idle_timeout": copy.deepcopy(self.idle)}
        return payload

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
            route.fulfill(json={"settings": {"darkModeEnabled": self.dark}} if method == "GET" else {"message": "Saved."})
        elif is_notification_count(method, path):
            route.fulfill(json=notification_count_payload())
        elif method == "GET" and path == "/api/approvals":
            route.fulfill(json={"approvals": [], "total_count": 0, "total_pages": 1})
        elif method == "POST" and path == HEARTBEAT_PATH:
            self.heartbeats.append({
                "body": request.post_data_json,
                "content_type": request.headers.get("content-type", ""),
                "ui": request.headers.get("x-simplechat-ui", ""),
            })
            route.fulfill(status=self.heartbeat_status, json=self.heartbeat_payload)
        elif method == "GET" and path == SIGN_OUT_PATH:
            self.signed_out.append(path)
            route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Signed out</title>Signed out")
        elif method == "GET" and path == FRAME_PATH:
            route.fulfill(content_type="text/html", body=(
                "<!doctype html><title>Embedded page</title><input id='inside' aria-label='Inside the frame'>"
                "<div style='height:2000px'></div>"
            ))
        else:
            self.unexpected_requests.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, path="/v2/", *, width=1280, height=900, install_clock=True):
        """Load the app, then pause the page's clock and count idle time from this moment."""
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self.page.set_viewport_size({"width": width, "height": height})
        if install_clock:
            self.page.clock.install(time=START)
        self.page.goto(f"{ORIGIN}{path}", wait_until="networkidle")
        expect(self.page.locator("main").first).to_be_visible()
        if install_clock:
            self.page.clock.pause_at(START + timedelta(minutes=1))
            self.touch()

    def touch(self):
        """One piece of input: the page counts it as activity and, the first time, reports it."""
        before = len(self.heartbeats)
        self.page.mouse.move(40, 40)
        self.page.mouse.move(60, 60)
        if self.idle.get("enabled") and self.session_block:
            self.wait_until(lambda: len(self.heartbeats) > before)
        self.heartbeats.clear()

    def wait_until(self, condition, timeout=5000):
        """Wait, in real time, for something the stubbed network answers asynchronously."""
        waited = 0
        while not condition():
            if waited >= timeout:
                raise AssertionError("The expected request never arrived.")
            # The browser's timer, not the page's: the page's clock is paused.
            self.page.wait_for_timeout(50)
            waited += 50

    def run_for(self, milliseconds):
        self.page.clock.run_for(milliseconds)

    def dialog(self):
        return self.page.get_by_role("alertdialog", name="Session expiring soon")

    def assert_clean(self, expected_failed_resources=0):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors
        assert len(self.failed_resources) == expected_failed_resources, self.failed_resources


@pytest.fixture
def idle_ui(page):
    fixture = IdleFixture(page)
    yield fixture
    fixture.assert_clean()


def test_the_warning_opens_at_the_warning_time_with_a_live_countdown(idle_ui):
    idle_ui.open()
    page = idle_ui.page

    idle_ui.run_for(28 * MINUTE - 5 * SECOND)
    expect(idle_ui.dialog()).to_have_count(0)

    idle_ui.run_for(5 * SECOND)
    dialog = idle_ui.dialog()
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-modal", "true")
    expect(page.get_by_test_id("v2-idle-session-message")).to_have_text("Still there?")
    countdown = page.get_by_test_id("v2-idle-session-countdown")
    expect(countdown).to_have_text("2 minutes")
    expect(dialog).to_contain_text("You will be signed out in 2 minutes unless you continue your session.")
    expect(page.get_by_test_id("v2-idle-session-stay")).to_be_focused()

    idle_ui.run_for(30 * SECOND)
    expect(countdown).to_have_text("1 minute 30 seconds")

    idle_ui.run_for(30 * SECOND)
    expect(countdown).to_have_text("1 minute")
    expect(page.get_by_test_id("v2-idle-session-announcement")).to_have_text("You will be signed out in 1 minute.")

    idle_ui.run_for(30 * SECOND)
    expect(countdown).to_have_text("30 seconds")
    expect(page.get_by_test_id("v2-idle-session-announcement")).to_have_text("You will be signed out in 30 seconds.")
    assert idle_ui.signed_out == []
    assert idle_ui.heartbeats == [], "no input, so nothing was reported"


def test_stay_signed_in_posts_the_heartbeat_and_restarts_the_clock(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    idle_ui.run_for(28 * MINUTE + 10 * SECOND)
    expect(idle_ui.dialog()).to_be_visible()

    page.get_by_test_id("v2-idle-session-stay").click()
    expect(idle_ui.dialog()).to_have_count(0)
    idle_ui.wait_until(lambda: len(idle_ui.heartbeats) == 1)
    heartbeat = idle_ui.heartbeats[0]
    assert heartbeat["body"] == {}
    assert "application/json" in heartbeat["content_type"]
    assert heartbeat["ui"] == "v2", "the heartbeat goes through the V2 API client"
    assert idle_ui.signed_out == []

    # The clock restarted at the click: no warning for another 28 minutes.
    idle_ui.run_for(27 * MINUTE)
    expect(idle_ui.dialog()).to_have_count(0)
    idle_ui.run_for(2 * MINUTE)
    expect(idle_ui.dialog()).to_be_visible()


def test_logout_now_leaves_through_the_local_sign_out(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    idle_ui.run_for(28 * MINUTE + 10 * SECOND)
    expect(idle_ui.dialog()).to_be_visible()

    page.get_by_test_id("v2-idle-session-sign-out").click()
    expect(page).to_have_url(f"{ORIGIN}{SIGN_OUT_PATH}")
    assert idle_ui.signed_out == [SIGN_OUT_PATH]
    assert idle_ui.heartbeats == []


def test_the_page_signs_out_by_itself_when_the_countdown_ends(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    idle_ui.run_for(29 * MINUTE + 50 * SECOND)
    expect(idle_ui.dialog()).to_be_visible()
    expect(page.get_by_test_id("v2-idle-session-countdown")).to_have_text("10 seconds")
    assert idle_ui.signed_out == []

    idle_ui.run_for(10 * SECOND)
    expect(page).to_have_url(f"{ORIGIN}{SIGN_OUT_PATH}")
    assert idle_ui.signed_out == [SIGN_OUT_PATH]


def test_an_active_user_is_reported_to_the_server_and_never_warned(idle_ui):
    idle_ui.open()
    page = idle_ui.page

    for _ in range(8):
        idle_ui.run_for(20 * MINUTE)
        page.mouse.move(100, 100)
        page.mouse.move(120, 130)
        idle_ui.wait_until(lambda: len(idle_ui.heartbeats) >= 1)
        expect(idle_ui.dialog()).to_have_count(0)
        idle_ui.heartbeats.clear()
    assert idle_ui.signed_out == [], "160 minutes of use with a 30 minute timeout"


def test_continued_input_is_reported_once_a_minute_at_most(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    idle_ui.run_for(5 * MINUTE)
    page.mouse.move(100, 100)
    idle_ui.wait_until(lambda: len(idle_ui.heartbeats) == 1)

    # Input every two seconds for 58 seconds: still inside the minute the first report covers.
    for step in range(29):
        idle_ui.run_for(2 * SECOND)
        page.mouse.move(100 + step, 100)
    assert len(idle_ui.heartbeats) == 1, "steady input stays inside the throttle"

    # The minute ends with the user still active, so the server is told without waiting for
    # another movement: otherwise it would run a minute behind the page.
    idle_ui.run_for(4 * SECOND)
    idle_ui.wait_until(lambda: len(idle_ui.heartbeats) == 2)


def test_a_disabled_timeout_shows_nothing_and_reports_nothing(page):
    fixture = IdleFixture(page, idle={**IDLE, "enabled": False})
    fixture.open()
    page.mouse.move(10, 10)
    fixture.run_for(3 * 60 * MINUTE)
    page.mouse.move(20, 20)
    expect(fixture.dialog()).to_have_count(0)
    assert fixture.heartbeats == []
    assert fixture.signed_out == []
    fixture.assert_clean()


def test_a_server_that_sends_no_session_block_behaves_as_before(page):
    fixture = IdleFixture(page, session_block=False)
    fixture.open()
    page.mouse.move(10, 10)
    fixture.run_for(3 * 60 * MINUTE)
    expect(fixture.dialog()).to_have_count(0)
    assert fixture.heartbeats == []
    assert fixture.signed_out == []
    fixture.assert_clean()


def test_scrolling_inside_a_pane_counts_as_activity(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    # The application scrolls inside panes, and a scroll event does not bubble out of one.
    page.evaluate(
        "() => { const pane = document.createElement('div'); pane.id = 'pane';"
        " pane.style.cssText = 'position:fixed;top:0;left:0;width:200px;height:100px;overflow:auto;z-index:1';"
        " pane.innerHTML = '<div style=\"height:2000px\"></div>'; document.body.appendChild(pane); }"
    )
    idle_ui.run_for(20 * MINUTE)
    page.evaluate("document.getElementById('pane').scrollTop = 120")
    idle_ui.wait_until(lambda: len(idle_ui.heartbeats) == 1)
    expect(idle_ui.dialog()).to_have_count(0)


def test_input_inside_an_embedded_same_origin_frame_counts_as_activity(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    # An embedded custom page is a separate document: its input never reaches the page's.
    page.evaluate(
        "() => { const frame = document.createElement('iframe'); frame.id = 'embedded';"
        " frame.title = 'Embedded page'; frame.src = '/embedded-page-stub';"
        " frame.style.cssText = 'position:fixed;right:0;bottom:0;width:300px;height:200px;z-index:1';"
        " document.body.appendChild(frame); }"
    )
    inside = page.frame_locator("#embedded").locator("#inside")
    expect(inside).to_be_visible()

    for _ in range(4):
        idle_ui.run_for(20 * MINUTE)
        inside.click()
        inside.press("a")
        idle_ui.wait_until(lambda: len(idle_ui.heartbeats) >= 1)
        idle_ui.heartbeats.clear()
        expect(idle_ui.dialog()).to_have_count(0)
    assert idle_ui.signed_out == [], "80 minutes of use inside the frame, with a 30 minute timeout"


def test_a_warning_time_equal_to_the_timeout_signs_out_without_a_dialog(page):
    fixture = IdleFixture(page, idle={**IDLE, "warning_minutes": 30})
    fixture.open()
    fixture.run_for(30 * MINUTE - 5 * SECOND)
    expect(fixture.dialog()).to_have_count(0)
    assert fixture.signed_out == []
    fixture.run_for(5 * SECOND)
    expect(page).to_have_url(f"{ORIGIN}{SIGN_OUT_PATH}")
    assert fixture.signed_out == [SIGN_OUT_PATH]
    fixture.assert_clean()


def test_the_administrators_sentence_is_shown_as_text(page):
    sentence = '<img src=x onerror="window.__idleXss=1"><b>Please confirm</b> you are here.'
    fixture = IdleFixture(page, idle={**IDLE, "warning_message": sentence})
    fixture.open()
    fixture.run_for(28 * MINUTE + 5 * SECOND)
    expect(page.get_by_test_id("v2-idle-session-message")).to_have_text(sentence)
    assert page.evaluate("window.__idleXss") is None
    assert page.locator("[data-testid='v2-idle-session-dialog'] img, [data-testid='v2-idle-session-dialog'] b").count() == 0
    fixture.assert_clean()


def test_an_empty_sentence_falls_back_to_the_default(page):
    fixture = IdleFixture(page, idle={**IDLE, "warning_message": "   "})
    fixture.open()
    fixture.run_for(28 * MINUTE + 5 * SECOND)
    expect(page.get_by_test_id("v2-idle-session-message")).to_have_text("You've been inactive for a while.")
    fixture.assert_clean()


def test_the_dialog_keeps_focus_inside_and_ignores_escape_and_passing_input(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    # Stands in for a dialog underneath, which closes on Escape by listening on the window.
    page.evaluate(
        "() => { window.__escapeHeard = 0;"
        " window.addEventListener('keydown', (event) => { if (event.key === 'Escape') window.__escapeHeard += 1; }); }"
    )
    idle_ui.run_for(28 * MINUTE + 5 * SECOND)
    expect(idle_ui.dialog()).to_be_visible()
    stay = page.get_by_test_id("v2-idle-session-stay")
    logout = page.get_by_test_id("v2-idle-session-sign-out")
    expect(stay).to_be_focused()

    page.keyboard.press("Tab")
    expect(logout).to_be_focused()
    page.keyboard.press("Tab")
    expect(stay).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(logout).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(stay).to_be_focused()
    for _ in range(6):
        page.keyboard.press("Tab")
    inside = page.evaluate(
        "() => document.querySelector('[data-testid=\"v2-idle-session-dialog\"]').contains(document.activeElement)"
    )
    assert inside, "Tab never leaves the dialog"

    page.keyboard.press("Escape")
    page.mouse.click(5, 5)
    page.mouse.move(300, 300)
    page.mouse.wheel(0, 200)
    expect(idle_ui.dialog()).to_be_visible()
    assert page.evaluate("window.__escapeHeard") == 0, "Escape must not reach a dialog underneath"
    # A click on the backdrop leaves focus where it was, and Tab recovers it if it is lost.
    page.keyboard.press("Tab")
    expect(logout).to_be_focused()
    assert idle_ui.heartbeats == [], "passing input neither dismisses the warning nor reports activity"

    stay.click()
    expect(idle_ui.dialog()).to_have_count(0)
    page.keyboard.press("Escape")
    assert page.evaluate("window.__escapeHeard") == 1, "with the dialog gone Escape reaches the page again"


def test_focus_returns_to_where_it_was_when_the_warning_is_answered(idle_ui):
    idle_ui.open()
    page = idle_ui.page
    # The rail's first link stands in for whatever the user was working in.
    opener = page.locator("#primary-navigation a").first
    opener.focus()
    idle_ui.run_for(28 * MINUTE + 5 * SECOND)
    expect(idle_ui.dialog()).to_be_visible()
    expect(page.get_by_test_id("v2-idle-session-stay")).to_be_focused()

    page.get_by_test_id("v2-idle-session-stay").click()
    expect(idle_ui.dialog()).to_have_count(0)
    expect(opener).to_be_focused()


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_the_dialog_text_is_readable_in_light_and_dark(page, dark):
    fixture = IdleFixture(page)
    fixture.dark = dark
    if dark:
        page.add_init_script("localStorage.setItem('simplechat.v2.theme', 'dark')")
    fixture.open()
    assert page.evaluate("document.documentElement.classList.contains('dark')") == dark
    fixture.run_for(28 * MINUTE + 5 * SECOND)
    expect(fixture.dialog()).to_be_visible()
    fixture.heartbeat_status = 500
    fixture.heartbeat_payload = {"error": "Internal Server Error"}
    page.get_by_test_id("v2-idle-session-stay").click()
    expect(page.get_by_test_id("v2-idle-session-error")).to_be_visible()

    readable = {
        "title": page.get_by_role("heading", name="Session expiring soon"),
        "message": page.get_by_test_id("v2-idle-session-message"),
        "countdown": page.get_by_test_id("v2-idle-session-countdown"),
        "error": page.get_by_test_id("v2-idle-session-error"),
        "logout": page.get_by_test_id("v2-idle-session-sign-out"),
    }
    ratios = {name: element.evaluate(CONTRAST_RATIO_SCRIPT, "color") for name, element in readable.items()}
    too_faint = {name: round(ratio, 2) for name, ratio in ratios.items() if ratio < AA_TEXT}
    assert not too_faint, f"Below {AA_TEXT}:1 in {'dark' if dark else 'light'} mode: {too_faint}"
    # "Stay signed in" is the shared primary button, white on the accent blue: 4.49:1 in light
    # mode by the design system's own tokens. It must not get worse than that.
    stay = page.get_by_test_id("v2-idle-session-stay").evaluate(CONTRAST_RATIO_SCRIPT, "color")
    assert stay >= 4.4, f"Stay signed in is {stay:.2f}:1"
    fixture.assert_clean(expected_failed_resources=1)


def test_the_dialog_fits_a_phone(page):
    long_sentence = "Please confirm you are still here " * 6
    fixture = IdleFixture(page, idle={**IDLE, "warning_message": long_sentence.strip()[:200]})
    fixture.open(width=390, height=844)
    fixture.run_for(28 * MINUTE + 5 * SECOND)
    dialog = fixture.dialog()
    expect(dialog).to_be_visible()
    box = dialog.bounding_box()
    assert box["x"] >= 0 and box["y"] >= 0, box
    assert box["x"] + box["width"] <= 390, box
    assert box["y"] + box["height"] <= 844, box
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for test_id in ("v2-idle-session-stay", "v2-idle-session-sign-out"):
        button = page.get_by_test_id(test_id)
        expect(button).to_be_in_viewport()
        button_box = button.bounding_box()
        assert button_box["height"] >= 32 and button_box["width"] >= 100, button_box
    fixture.assert_clean()


def test_a_heartbeat_refused_as_an_ended_session_shows_the_sign_in_notice(page):
    fixture = IdleFixture(page)
    fixture.open()
    fixture.run_for(28 * MINUTE + 10 * SECOND)
    expect(fixture.dialog()).to_be_visible()
    fixture.heartbeat_status = 401
    fixture.heartbeat_payload = SESSION_EXPIRED

    page.get_by_test_id("v2-idle-session-stay").click()
    expect(page.get_by_test_id("v2-session-notice")).to_be_visible()
    expect(fixture.dialog()).to_have_count(0)

    # Nothing signs the user out behind the notice, and no further heartbeat is attempted.
    fixture.run_for(10 * MINUTE)
    page.mouse.move(200, 200)
    expect(fixture.dialog()).to_have_count(0)
    assert fixture.signed_out == []
    assert len(fixture.heartbeats) == 1
    fixture.assert_clean(expected_failed_resources=1)


def test_a_failed_stay_signed_in_keeps_the_dialog_and_offers_a_retry(page):
    fixture = IdleFixture(page)
    fixture.open()
    fixture.run_for(28 * MINUTE + 10 * SECOND)
    expect(fixture.dialog()).to_be_visible()
    fixture.heartbeat_status = 500
    fixture.heartbeat_payload = {"error": "Internal Server Error"}

    stay = page.get_by_test_id("v2-idle-session-stay")
    stay.click()
    error = page.get_by_test_id("v2-idle-session-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("We couldn't confirm your session")
    expect(fixture.dialog()).to_be_visible()
    expect(stay).to_be_enabled()
    expect(page.get_by_test_id("v2-session-notice")).to_have_count(0)

    fixture.heartbeat_status = 200
    fixture.heartbeat_payload = {"message": "Session refreshed", "idle_timeout_minutes": 30}
    stay.click()
    expect(fixture.dialog()).to_have_count(0)
    assert fixture.signed_out == []
    fixture.assert_clean(expected_failed_resources=1)


def test_without_activity_in_any_tab_every_tab_warns(page):
    """The control for the test above: shared activity is what keeps the idle tab quiet."""
    context = page.context
    context.clock.install(time=START)
    first = IdleFixture(page)
    second_page = context.new_page()
    second = IdleFixture(second_page)
    first.open(install_clock=False)
    second.open(install_clock=False)
    context.clock.pause_at(START + timedelta(minutes=1))

    context.clock.run_for(28 * MINUTE + 10 * SECOND)
    expect(first.dialog()).to_be_visible()
    expect(second.dialog()).to_be_visible()
    first.assert_clean()
    second.assert_clean()


def test_an_idle_tab_does_not_sign_out_a_session_in_use_in_another_tab(page):
    context = page.context
    context.clock.install(time=START)
    idle_tab = IdleFixture(page)
    active_page = context.new_page()
    active_tab = IdleFixture(active_page)
    idle_tab.open(install_clock=False)
    active_tab.open(install_clock=False)
    context.clock.pause_at(START + timedelta(minutes=1))
    active_tab.touch()

    # The second tab is used steadily; the first is never touched again.
    for _ in range(4):
        context.clock.run_for(20 * MINUTE)
        active_page.mouse.move(100, 100)
        active_page.mouse.move(130, 120)
        active_tab.wait_until(lambda: len(active_tab.heartbeats) >= 1)
        active_tab.heartbeats.clear()
        expect(idle_tab.dialog()).to_have_count(0)
        expect(active_tab.dialog()).to_have_count(0)

    assert idle_tab.signed_out == [], "80 minutes in, the idle tab has not signed the shared session out"
    assert active_tab.signed_out == []
    idle_tab.assert_clean()
    active_tab.assert_clean()
