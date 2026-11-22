# test_v2_classic_links.py
"""
Browser regressions for the V2 side of the classic to V2 redirect: a classic fragment that survives the
server's redirect, and "Switch to classic UI" from every page that has a classic counterpart.
Version: 0.261.449
Implemented in: 0.261.448

A server never sees the part of a URL after ``#``, but a browser keeps it across a redirect, so
``/workspace#documents-tab`` arrives in V2 as ``/v2/workspace#documents-tab``. V2 replaces it, once and
in place, with the route the page registry says it names. "Switch to classic UI" in the account menu saves
the account preference and opens
the classic version of the page on screen, carrying the open conversation from the chat page, and every
address carries ``ui=classic`` so a server that has selected the modern interface serves the classic page
instead of sending the visitor straight back.

These tests run the real rail, account menu, stores and fragment translation, bundled by
fixtures/classic_links, in a browser router with the application's ``/v2`` base. Only HTTP answers are
replaced; every page body is a placeholder, because what the tests need from a page is to have arrived.
The expected addresses come from the server's own resolver (ui_routing.py), so the two interfaces are
held to the same registry. The existing Azure Playwright connection fixture also supports a local
browser; no live application data is read or modified.
"""

import json
import mimetypes
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "application" / "single_app"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# Imported through the package: a bare `harness_build` would collide with the orchestration
# fixture module of the same name when both suites run in one session.
from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
import ui_routing  # noqa: E402


pytestmark = pytest.mark.ui

FIXTURE = ROOT / "ui_tests" / "fixtures" / "classic_links"
BUNDLE = FIXTURE / "harness.bundle.js"
STATIC = ROOT / "application" / "single_app" / "static"
# A secure context, as every deployment is.
ORIGIN = "https://simplechat.test"
CLASSIC_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Classic page</title></head>'
    "<body><h1>Classic interface</h1></body></html>"
)
SAMPLE = "abc-123"
CLASSIC_TOKEN_RE = re.compile(r"<(?:[a-z_]+:)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>")
EMPTY_CONVERSATION_FEED = {
    "success": True, "conversations": [], "has_more": False, "next_cursor": None, "page_size": 30,
    "hidden_count": 0, "priority_count": 0, "recent_count": 0, "source_offsets": {},
}


def registry_rows():
    return json.loads(ui_routing.UI_ROUTE_MAP_PATH.read_text(encoding="utf-8"))["routes"]


def fragment_cases():
    """Every fragment the registry lists, as the address a redirected browser arrives at."""
    cases = []
    for row in registry_rows():
        if not row.get("hash_map") or not row.get("v2") or row["status"] not in ("native", "partial"):
            continue
        classic_path = CLASSIC_TOKEN_RE.sub(SAMPLE, row["classic"])
        arrival = ui_routing.resolve_v2_target(classic_path)
        for fragment in row["hash_map"]:
            whole = ui_routing.resolve_v2_target(classic_path, "", fragment)
            if arrival is not None and whole is not None:
                cases.append(pytest.param(
                    arrival["path"], fragment, whole["path"], id=f"{row['key']}-{fragment}",
                ))
    return cases


FRAGMENT_CASES = fragment_cases()

# (id, the V2 address on screen, the classic address it opens, the conversation open in the chat)
BACK_TO_CLASSIC_CASES = [
    ("chat-with-a-conversation", "/v2/chat", "/chats?conversationId=conv-1&ui=classic", "conv-1"),
    ("chat-without-one", "/v2/chat", "/chats?ui=classic", None),
    ("settings", "/v2/settings", "/profile?ui=classic", "conv-1"),
    ("settings-tab", "/v2/settings?tab=feedback", "/profile?tab=feedback&ui=classic", "conv-1"),
    (
        "settings-section",
        "/v2/settings?tab=preferences&section=m365-chat-connection",
        "/profile?tab=settings&ui=classic#m365-chat-connection",
        None,
    ),
    ("group-members", "/v2/groups/abc-123/members", "/groups/abc-123?ui=classic", "conv-1"),
    ("notifications", "/v2/notifications", "/notifications?ui=classic", "conv-1"),
    ("a-page-with-no-classic-counterpart", "/v2/groups/directory", "/chats?conversationId=conv-1&ui=classic", "conv-1"),
]


class Harness:
    """The frame in a browser page, driven the way a reader drives it."""

    def __init__(self, page, stylesheets):
        self.page = page
        self.stylesheets = stylesheets
        self.requests = []
        self.errors = []
        self.unexpected = []
        self.fail_save = False
        self.saved_settings = {}

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
        if method == "POST" and path == "/api/user/settings":
            if self.fail_save:
                route.fulfill(status=500, json={"error": "Unable to save settings"})
            else:
                self.saved_settings.update(request.post_data_json["settings"])
                route.fulfill(json={"message": "Settings updated"})
        elif method != "GET":
            self.unexpected.append(f"{method} {path}")
            route.fulfill(status=405, body="")
        elif path == "/v2" or path.startswith("/v2/"):
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        elif path.startswith("/static/"):
            asset = (STATIC / unquote(path.removeprefix("/static/"))).resolve()
            if asset.is_relative_to(STATIC.resolve()) and asset.is_file():
                route.fulfill(
                    path=str(asset),
                    content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream",
                )
            else:
                self.unexpected.append(f"{method} {path}")
                route.fulfill(status=404, body="")
        elif path == "/api/conversations/feed":
            # The rail's conversation list, on the chat page: the reader has none.
            route.fulfill(json=EMPTY_CONVERSATION_FEED)
        elif path.startswith("/api/"):
            self.unexpected.append(f"{method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})
        else:
            route.fulfill(content_type="text/html", body=CLASSIC_PAGE)

    # Starting ---------------------------------------------------------------------------------

    def listen(self):
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)

    def open(self, address, *, conversation=None, width=1280, height=900):
        """Load the harness at `address`, seed the stores and mount the frame."""
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.route("**/*", self.handle)
        self.listen()
        self.page.goto(f"{ORIGIN}{address}")
        self.history_at_load = self.page.evaluate("() => window.history.length")
        self.boot(conversation=conversation)

    def boot(self, *, conversation=None):
        """Style the loaded harness page, seed the stores and mount the frame."""
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.page.evaluate(SEED, {"conversation": conversation})

    def record_console(self, message):
        if message.type == "error":
            if (
                self.fail_save
                and urlsplit(message.location.get("url", "")).path == "/api/user/settings"
                and message.text == "Failed to load resource: the server responded with a status of 500 (Internal Server Error)"
            ):
                return
            self.errors.append(message.text)

    # Reading the page -------------------------------------------------------------------------

    @property
    def address(self):
        """The router's own address, relative to its `/v2` base, with the fragment the router sees."""
        return self.page.locator("[data-current-address]")

    @property
    def classic_link(self):
        return self.page.get_by_role("button", name="Switch to classic UI")

    def open_account_menu(self, *, phone=False):
        if phone:
            self.page.get_by_role("button", name="Open navigation").click()
        self.page.locator('[data-tour="user-menu"]').click()
        expect(self.page.locator("#sidebar-account-menu")).to_be_visible()


class RedirectingServer:
    """A real local server that answers a classic address with a 302 to V2, as the application does in the
    modern interface, so the browser's own network stack follows the redirect and decides what happens to
    the fragment. It serves the harness page for V2 and nothing else."""

    def __init__(self, redirects):
        self.redirects = redirects
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlsplit(self.path)
                outer.requests.append(self.path)
                if parsed.path in outer.redirects:
                    self.send_response(302)
                    self.send_header("Location", outer.redirects[parsed.path])
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif parsed.path == "/v2" or parsed.path.startswith("/v2/"):
                    self.answer(FIXTURE / "harness.html", "text/html")
                elif parsed.path == "/harness.bundle.js":
                    self.answer(BUNDLE, "application/javascript")
                elif parsed.path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def answer(self, path, content_type):
                body = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc_info):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


SEED = r"""
(seed) => {
    const H = window.ClassicLinksHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.448',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: {},
            branding: {app_title: 'Contoso Chat'},
            settings: {},
            ui: {policy: 'both', default: 'modern', effective: 'modern', can_switch: true},
            scope: {groups: [], public_workspaces: []},
            catalogs: {models: [], agents: [], prompts: []},
        },
        loading: false,
        error: null,
    });
    H.stores.userSettings.useUserSettingsStore.setState({settings: {}, loading: false, error: null});
    H.stores.ui.useUiStore.setState({railCollapsed: false, mobileNavOpen: false});
    H.stores.chat.useChatStore.setState({activeConversationId: seed.conversation});
    H.mount();
}
"""


@pytest.fixture(scope="module")
def harness_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: npm --prefix application/v2_ui run build"
    hrefs = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
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


# A classic fragment that survives the redirect -------------------------------------------------


@pytest.mark.parametrize(("arrival", "fragment", "expected"), FRAGMENT_CASES)
def test_a_classic_fragment_becomes_the_route_it_names_in_place(harness, arrival, fragment, expected):
    harness.open(f"{arrival}#{fragment}")

    expect(harness.page).to_have_url(f"{ORIGIN}{expected}")
    router_address = expected.removeprefix("/v2") or "/"
    expect(harness.address).to_have_text(router_address)
    assert "#" not in harness.page.url, "The fragment is dropped once it has been translated."
    assert harness.page.evaluate("() => window.history.length") == harness.history_at_load, (
        "The address is replaced, so Back does not return to the classic fragment."
    )


def test_a_fragment_the_registry_does_not_list_is_left_as_it_is(harness):
    harness.open("/v2/workspace#a-heading-on-the-page")

    expect(harness.address).to_have_text("/workspace#a-heading-on-the-page")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/workspace#a-heading-on-the-page")
    assert harness.page.evaluate("() => window.history.length") == harness.history_at_load


def test_a_listed_fragment_on_another_page_is_left_as_it_is(harness):
    harness.open("/v2/chat#documents-tab")

    expect(harness.address).to_have_text("/chat#documents-tab")
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/chat#documents-tab")


def test_the_fragment_survives_the_servers_redirect_and_is_translated(harness, harness_assets):
    """The application answers a classic URL with a 302 whose Location carries no fragment. Chromium keeps
    the fragment the visitor arrived with (the Fetch standard), and V2 turns it into the section it names."""
    harness.listen()
    with RedirectingServer({"/profile": "/v2/settings?tab=preferences"}) as server:
        harness.page.goto(f"{server.origin}/profile?tab=settings#m365-chat-connection")
        assert harness.page.url == f"{server.origin}/v2/settings?tab=preferences#m365-chat-connection", (
            "The browser carried the fragment across the redirect."
        )
        harness.boot()

        expect(harness.page).to_have_url(f"{server.origin}/v2/settings?tab=preferences&section=m365-chat-connection")
        expect(harness.address).to_have_text("/settings?tab=preferences&section=m365-chat-connection")
    assert server.requests[0] == "/profile?tab=settings", "The fragment is never sent to the server."


# Back to classic UI ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("v2_address", "classic_address", "conversation"),
    [pytest.param(*case[1:], id=case[0]) for case in BACK_TO_CLASSIC_CASES],
)
def test_back_to_classic_opens_the_classic_version_of_the_page_on_screen(
    harness, v2_address, classic_address, conversation,
):
    harness.open(v2_address, conversation=conversation)
    harness.open_account_menu()

    link = harness.classic_link
    link.click()
    expect(harness.page).to_have_url(f"{ORIGIN}{classic_address}")
    assert harness.saved_settings == {"preferredUiMode": "classic"}
    requested = [
        target for _method, target in harness.requests
        if not target.startswith(("/v2", "/harness", "/static", "/favicon", "/api/"))
    ]
    assert requested == [urlsplit(classic_address)._replace(fragment="").geturl()], requested
    assert "ui=classic" in requested[0], "The classic request carries the escape pair."


@pytest.mark.parametrize(
    ("v2_address", "classic_address", "conversation"),
    [pytest.param(*case[1:], id=case[0]) for case in BACK_TO_CLASSIC_CASES if case[0] in (
        "chat-with-a-conversation", "settings-tab", "group-members", "a-page-with-no-classic-counterpart",
    )],
)
def test_back_to_classic_works_from_the_navigation_drawer_on_a_phone(
    harness, v2_address, classic_address, conversation,
):
    harness.open(v2_address, conversation=conversation, width=390, height=844)
    harness.open_account_menu(phone=True)

    link = harness.classic_link
    expect(link).to_be_visible()
    box = link.bounding_box()
    assert box is not None and box["width"] > 0 and box["x"] + box["width"] <= 390 + 1, "The link fits the phone."
    link.click()
    expect(harness.page).to_have_url(f"{ORIGIN}{classic_address}")


def test_the_link_follows_the_page_as_you_move_around_the_application(harness):
    harness.open("/v2/chat", conversation="conv-1")
    menu = harness.page.locator("#sidebar-account-menu")
    harness.open_account_menu()
    expect(harness.classic_link).to_be_visible()

    menu.get_by_role("link", name="User Settings").click()
    expect(harness.address).to_have_text("/settings")
    expect(menu).to_have_count(0)

    harness.open_account_menu()
    expect(harness.classic_link).to_be_visible()

    harness.page.locator("[data-account-menu-notifications]").click()
    expect(harness.address).to_have_text("/notifications")
    harness.open_account_menu()
    harness.classic_link.click()
    expect(harness.page).to_have_url(f"{ORIGIN}/notifications?ui=classic")


def test_the_link_is_reachable_and_named_for_a_keyboard_user(harness):
    """The menu panel sits ahead of its button in the page, as it always did, so Shift+Tab from the button
    walks it from the bottom: Sign out, then Back to classic UI."""
    harness.open("/v2/settings?tab=feedback")
    harness.page.locator('[data-tour="user-menu"]').focus()
    harness.page.keyboard.press("Enter")
    expect(harness.page.locator("#sidebar-account-menu")).to_be_visible()

    reached = []
    for _ in range(8):
        harness.page.keyboard.press("Shift+Tab")
        reached.append(harness.page.evaluate("() => document.activeElement.textContent.trim()"))
        if reached[-1] == "Switch to classic UI":
            break
    assert reached[-1] == "Switch to classic UI", reached
    harness.page.keyboard.press("Escape")
    expect(harness.page.locator("#sidebar-account-menu")).to_have_count(0)


def test_failed_preference_save_stays_in_modern_and_reports_error(harness):
    harness.open("/v2/settings")
    harness.fail_save = True
    harness.open_account_menu()
    harness.classic_link.click()
    expect(harness.page.get_by_role("alert")).to_have_text(
        "Your interface preference could not be saved. Please try again."
    )
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/settings")
    expect(harness.classic_link).to_be_enabled()
    assert harness.saved_settings == {}


def test_failed_pending_settings_save_does_not_discard_error_by_switching(harness):
    harness.open("/v2/settings")
    harness.open_account_menu()
    harness.fail_save = True
    harness.page.evaluate("""() => {
        window.ClassicLinksHarness.stores.userSettings.useUserSettingsStore
            .getState().update({showTutorialButtons: false});
    }""")
    harness.classic_link.click()
    expect(harness.page.get_by_role("alert")).to_have_text(
        "Your pending preferences could not be saved. Please retry them before switching interfaces."
    )
    expect(harness.page).to_have_url(f"{ORIGIN}/v2/settings")
    expect(harness.classic_link).to_be_enabled()
    assert harness.saved_settings == {}


def test_modern_only_policy_hides_the_switch(harness):
    harness.open("/v2/settings")
    harness.page.evaluate("""() => {
        const store = window.ClassicLinksHarness.stores.bootstrap.useBootstrapStore;
        store.setState({data: {...store.getState().data,
            ui: {policy: 'modern', default: 'modern', effective: 'modern', can_switch: false}}});
    }""")
    harness.open_account_menu()
    expect(harness.classic_link).to_have_count(0)
