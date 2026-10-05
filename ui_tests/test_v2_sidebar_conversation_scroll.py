# test_v2_sidebar_conversation_scroll.py
"""
Browser regressions for the V2 chat rail scrolling as one panel.
Version: 0.261.235
Implemented in: 0.261.235

On the chat page, the rail kept its whole height for the navigation and the administrator's
link groups, and the conversation list scrolled in what was left: two rows in a 720px-tall
window with two external links configured (#1642). Now everything between New chat and the
footer scrolls as one panel, as the classic sidebar does. Reading down the list carries the
navigation out of view, and the search is held right under New chat.

The production AppShell, Sidebar, NavExtras, ConversationRail, ChatPage, HomePage and stores
run in Chromium with production CSS, through the orchestration harness. Only HTTP is stubbed:
a conversation feed of 75 conversations served 30 at a time, with its search, and user
settings. No live model, deployment or workspace content is used. Screenshots of the held
search in both themes are written to ui_tests/artifacts/sidebar-conversation-scroll/.

Local Chromium is the default; the shared connect_options fixture supports Azure Playwright.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_sidebar_conversation_scroll.py -q
"""

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).resolve().parent / "artifacts" / "sidebar-conversation-scroll"
DESKTOP = {"width": 1280, "height": 720}
PHONE = {"width": 360, "height": 740}
TOTAL = 75
PAGE_SIZE = 30
# --surface-solid, the backing the held search is drawn on, in each theme.
HELD_BACKING = {"light": "rgb(255, 255, 255)", "dark": "rgb(16, 23, 40)"}

# The rail's geometry, read in one pass so every value describes the same frame.
GEOMETRY = r"""
() => {
    const nav = document.getElementById('primary-navigation');
    const region = nav.querySelector('[data-rail-scroll-region]');
    const header = nav.querySelector('[data-conversation-rail-header]');
    const box = (element) => {
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return {top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, height: rect.height};
    };
    const link = (name) => [...nav.querySelectorAll('a')].find((item) => item.textContent.trim() === name);
    const rows = [...nav.querySelectorAll('li.group\\/row')];
    const regionBox = region.getBoundingClientRect();
    const floor = header ? header.getBoundingClientRect().bottom : regionBox.top;
    const visible = rows.filter((row) => {
        const rect = row.getBoundingClientRect();
        return rect.top >= floor - 0.5 && rect.bottom <= regionBox.bottom + 0.5;
    }).length;
    const scrollers = [...nav.querySelectorAll('*')].filter((element) => {
        const style = getComputedStyle(element);
        return /(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight;
    });
    return {
        region: {
            ...box(region), overflowY: getComputedStyle(region).overflowY,
            scrollTop: region.scrollTop, scrollHeight: region.scrollHeight, clientHeight: region.clientHeight,
        },
        newChat: box(nav.querySelector('[title="Start a new chat"]')),
        chats: box(link('Chats')),
        lastLink: box(link('Simple Chat Videos')),
        search: box(nav.querySelector('input[aria-label="Search conversations"]')),
        header: header && {
            ...box(header),
            stuck: header.hasAttribute('data-stuck'),
            background: getComputedStyle(header).backgroundColor,
        },
        footer: box(nav.querySelector('button[aria-label^="Switch to"]')),
        rows: rows.length,
        visible,
        scrollers: scrollers.length,
        regionScrolls: scrollers.length === 1 && scrollers[0] === region,
    };
}
"""

# Resolves once the region has stopped moving: a wheel scroll is animated.
SETTLE = r"""
() => new Promise((resolve) => {
    const region = document.querySelector('[data-rail-scroll-region]');
    let last = region.scrollTop;
    let still = 0;
    const tick = () => {
        if (region.scrollTop === last) {
            still += 1;
            if (still > 6) {
                resolve(region.scrollTop);
                return;
            }
        } else {
            still = 0;
            last = region.scrollTop;
        }
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
})
"""

# Where the focused element sits against the held header, or null when focus is not in a row.
FOCUS_CLEARANCE = r"""
() => {
    const active = document.activeElement;
    if (!active || !active.closest('li.group\\/row')) return null;
    const header = document.querySelector('[data-conversation-rail-header]');
    return {
        label: active.getAttribute('aria-label') || active.textContent.trim(),
        top: active.getBoundingClientRect().top,
        headerBottom: header.getBoundingClientRect().bottom,
    };
}
"""


def conversation(index):
    return {
        "id": f"conv-{index:02d}",
        "title": f"Conversation {index:02d}",
        "chat_type": "personal_single_user",
        "context": [],
        "is_pinned": index < 2,
        "is_hidden": False,
        "has_unread_assistant_response": False,
        "last_updated": f"2026-10-01T10:{index % 60:02d}:00Z",
    }


class RailApi:
    """Serves the harness and answers the rail's reads; anything else fails the test."""

    def __init__(self, assets):
        self.assets = assets
        self.conversations = [conversation(index) for index in range(TOTAL)]
        self.feed_queries = []
        self.errors = []
        self.unexpected = []

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        if request.method == "GET" and path == "/api/conversations/feed":
            self.answer_feed(route, {key: values[-1] for key, values in parse_qs(url.query).items()})
            return
        if path == "/api/user/settings":
            if request.method == "GET":
                route.fulfill(json={"settings": {}})
            else:
                route.fulfill(json={"message": "User settings updated successfully"})
            return
        if self.answer_open(route, request.method, path):
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test request."})

    def answer_open(self, route, method, path):
        """The reads a conversation makes as it opens, answered for an empty personal thread."""
        if method == "GET" and path == "/api/get_messages":
            route.fulfill(json={"messages": []})
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/metadata", path)):
            conversation_id = unquote(match.group(1))
            title = next((item["title"] for item in self.conversations if item["id"] == conversation_id), "")
            route.fulfill(json={"conversation_id": conversation_id, "title": title})
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/kind", path)):
            route.fulfill(json={"conversation_id": unquote(match.group(1)), "kind": "personal"})
        elif method == "POST" and re.fullmatch(r"/api/conversations/[^/]+/mark-read", path):
            route.fulfill(json={"success": True})
        elif method == "GET" and re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
        elif method == "GET" and path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
        elif method == "GET" and path == "/api/collaboration/file-approvals":
            route.fulfill(json={"approvals": []})
        elif method == "GET" and path == "/api/user/collaboration-suggestions":
            route.fulfill(json={"results": []})
        else:
            return False
        return True

    def answer_feed(self, route, query):
        """The feed route's paging: page_size rows from an opaque cursor, filtered by title."""
        self.feed_queries.append(query)
        term = query.get("search", "").lower()
        matching = [item for item in self.conversations if term in item["title"].lower()]
        start = int(query.get("cursor") or 0)
        size = int(query.get("page_size") or PAGE_SIZE)
        more = start + size < len(matching)
        route.fulfill(json={
            "success": True,
            "conversations": matching[start:start + size],
            "has_more": more,
            "next_cursor": str(start + size) if more else None,
        })

    def cursors(self):
        return [query.get("cursor") for query in self.feed_queries if not query.get("search")]


@pytest.fixture
def open_page(editor_browser, editor_assets):
    """A fresh page per call, each with its own stub API, checked for stray requests and errors."""
    opened = []

    def make(viewport=DESKTOP):
        context = editor_browser.new_context(viewport=viewport)
        page = context.new_page()
        api = RailApi(editor_assets)
        page.route("**/*", api.handle)
        page.on("pageerror", lambda error: api.errors.append(str(error)))
        page.on("console", lambda message: api.errors.append(message.text) if message.type == "error" else None)
        opened.append((context, api))
        return page, api

    yield make
    for context, api in opened:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not api.errors, f"Unexpected browser errors: {api.errors}"


def mount(page, api, *, experience="ChatExperience", entry="/chat", rows=PAGE_SIZE):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {}, settings: {},
                user: {id: 'tester', display_name: 'Riley Chen'},
                branding: {app_title: 'Simple Chat'},
                catalogs: {models: [], agents: [], prompts: []},
                scope: {groups: [], public_workspaces: []},
                orchestration: {enabled: false, capabilities: []},
                navigation: {external_links: {
                    enabled: true, menu_name: 'External Links', force_menu: false,
                    items: [
                        {label: 'Acceptable Use Policy', url: '/external/acceptable-use'},
                        {label: 'Simple Chat Videos', url: '/external/videos'},
                    ],
                }},
            }});
            H.mount('mount-a', spec.experience, {}, {initialEntries: [spec.entry]});
        }""",
        {"experience": experience, "entry": entry},
    )
    if rows:
        expect(row_items(page)).to_have_count(rows)


def row_items(page):
    return page.locator("#primary-navigation li.group\\/row")


def header(page):
    return page.locator("[data-conversation-rail-header]")


def search_box(page):
    return page.get_by_role("searchbox", name="Search conversations")


def geometry(page):
    return page.evaluate(GEOMETRY)


def wheel_rail(page, delta):
    """Scroll with the wheel over the conversation list, the way a reader does."""
    box = header(page).bounding_box()
    page.mouse.move(box["x"] + 80, box["y"] + box["height"] + 40)
    page.mouse.wheel(0, delta)
    page.evaluate(SETTLE)


def opaque(color):
    return color.startswith("rgb(") or color.endswith(", 1)")


def held_under_new_chat(found):
    """The search's header is held at the region's top, which is New chat's bottom edge."""
    return (
        abs(found["header"]["top"] - found["newChat"]["bottom"]) < 1
        and abs(found["search"]["top"] - (found["newChat"]["bottom"] + 12)) < 1
    )


def test_reading_down_the_list_scrolls_the_navigation_away_and_holds_search(open_page):
    page, api = open_page()
    mount(page, api)
    rest = geometry(page)

    # At rest the rail is laid out as it always was: navigation, the link group, then the list.
    assert rest["region"]["overflowY"] == "auto" and rest["region"]["scrollTop"] == 0, rest["region"]
    assert rest["chats"]["bottom"] <= rest["lastLink"]["top"] < rest["search"]["top"], rest
    assert not rest["header"]["stuck"], rest["header"]
    assert rest["header"]["background"] == "rgba(0, 0, 0, 0)", "At rest the search must sit on the rail's glass."
    assert rest["visible"] <= 3, f"The fixture should squeeze the list at rest: {rest['visible']} rows."

    wheel_rail(page, 900)
    expect(header(page)).to_have_attribute("data-stuck", "")
    held = geometry(page)

    assert held["regionScrolls"], "One scrollbar for the whole panel: the list must not scroll on its own."
    assert held["region"]["scrollTop"] > 600, held["region"]
    assert held["newChat"] == rest["newChat"], "New chat must not move."
    assert held["footer"] == rest["footer"], "The footer must not move."
    assert held["chats"]["bottom"] <= held["region"]["top"], "The navigation must scroll out of view."
    assert held_under_new_chat(held), f"The search must be held right under New chat: {held}"
    assert opaque(held["header"]["background"]), f"Held, the search needs a solid backing: {held['header']}"
    assert held["visible"] >= 10, f"The list must take the freed height: {held['visible']} rows visible."
    assert held["visible"] >= rest["visible"] * 4, (rest["visible"], held["visible"])

    # Scrolling back up returns the navigation and lets the search go.
    wheel_rail(page, -5000)
    expect(header(page)).not_to_have_attribute("data-stuck", "")
    back = geometry(page)
    assert back["region"]["scrollTop"] == 0
    assert back["chats"] == rest["chats"] and back["search"] == rest["search"], back
    assert back["header"]["background"] == "rgba(0, 0, 0, 0)"


def test_the_next_page_loads_before_the_end_of_the_list_is_on_screen(open_page):
    page, api = open_page()
    mount(page, api)
    assert api.cursors() == [None], api.feed_queries

    # Bring the end of the list to 60px below the rail's visible edge: inside the look-ahead
    # margin, but not yet on screen. Measured against the viewport, the region's edge clipped
    # the margin away and the next page waited until the end was visible.
    page.evaluate(
        """() => {
            const region = document.querySelector('[data-rail-scroll-region]');
            const header = document.querySelector('[data-conversation-rail-header]');
            const end = header.nextElementSibling.querySelector(':scope > ul + div');
            const gap = end.getBoundingClientRect().top - region.getBoundingClientRect().bottom;
            region.scrollTop += gap - 60;
        }"""
    )
    page.wait_for_function(
        """() => {
            const region = document.querySelector('[data-rail-scroll-region]');
            const header = document.querySelector('[data-conversation-rail-header]');
            const end = header.nextElementSibling.querySelector(':scope > ul + div');
            return end.getBoundingClientRect().top > region.getBoundingClientRect().bottom;
        }"""
    )
    expect(row_items(page)).to_have_count(PAGE_SIZE * 2)
    assert api.cursors() == [None, str(PAGE_SIZE)], api.feed_queries

    # Reading on reaches the last page, and nothing is asked for after it.
    for _ in range(6):
        wheel_rail(page, 1500)
    expect(row_items(page)).to_have_count(TOTAL)
    expect(page.get_by_text(f"Conversation {TOTAL - 1:02d}", exact=True)).to_be_visible()
    assert api.cursors() == [None, str(PAGE_SIZE), str(PAGE_SIZE * 2)], api.feed_queries


def test_keyboard_focus_is_never_hidden_under_the_held_search(open_page):
    page, api = open_page()
    mount(page, api)
    wheel_rail(page, 900)
    expect(header(page)).to_have_attribute("data-stuck", "")

    def walk_up(steps):
        seen = 0
        for _ in range(steps):
            page.keyboard.press("Shift+Tab")
            found = page.evaluate(FOCUS_CLEARANCE)
            if found is None:
                continue
            seen += 1
            assert found["top"] >= found["headerBottom"] - 1, f"Focus went under the held search: {found}"
        return seen

    # Start from a row that is on screen, then walk up into rows scrolled out above it.
    first_visible = page.evaluate(
        """() => {
            const header = document.querySelector('[data-conversation-rail-header]');
            const floor = header.getBoundingClientRect().bottom;
            const row = [...document.querySelectorAll('li.group\\\\/row')]
                .find((item) => item.getBoundingClientRect().top >= floor);
            return row.querySelector('button').textContent.trim();
        }"""
    )
    page.get_by_role("button", name=first_visible, exact=True).focus()
    assert walk_up(9) >= 6, "Shift+Tab should have walked through several rows."

    # The bulk bar makes the held header taller; the rows keep clear of that too.
    page.get_by_role("checkbox", name=f"Select {first_visible}").check()
    expect(page.get_by_text("1 selected", exact=True)).to_be_visible()
    taller = geometry(page)["header"]
    assert taller["height"] > 70, taller
    page.get_by_role("button", name=first_visible, exact=True).focus()
    assert walk_up(9) >= 6


def test_clicking_a_row_partly_under_the_held_search_opens_it(open_page):
    page, api = open_page()
    mount(page, api)
    wheel_rail(page, 913)
    expect(header(page)).to_have_attribute("data-stuck", "")

    # A row cut by the held header: the reader clicks the part they can see. Only keyboard
    # focus is moved clear of the header, so the row must not slide out from under the pointer.
    target = page.evaluate(
        """() => {
            const region = document.querySelector('[data-rail-scroll-region]');
            const floor = document.querySelector('[data-conversation-rail-header]').getBoundingClientRect().bottom;
            const row = [...document.querySelectorAll('li.group\\\\/row')].find((item) => {
                const rect = item.getBoundingClientRect();
                return rect.top < floor && rect.bottom > floor + 6;
            });
            const button = row.querySelector('button');
            const rect = button.getBoundingClientRect();
            return {title: button.textContent.trim(), x: rect.left + 60, y: (floor + rect.bottom) / 2,
                    scrollTop: region.scrollTop};
        }"""
    )
    page.mouse.move(target["x"], target["y"])
    page.mouse.down()
    assert page.evaluate("() => document.querySelector('[data-rail-scroll-region]').scrollTop") == target["scrollTop"]
    page.mouse.up()

    expect(page.get_by_role("heading", name=target["title"], level=1)).to_be_visible()
    active = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId")
    assert active == next(item["id"] for item in api.conversations if item["title"] == target["title"])


def test_searching_while_held_keeps_the_search_box_in_place(open_page):
    page, api = open_page()
    mount(page, api)
    wheel_rail(page, 900)
    expect(header(page)).to_have_attribute("data-stuck", "")
    before = geometry(page)

    search_box(page).click()
    search_box(page).fill("Conversation 7")
    expect(row_items(page)).to_have_count(5)
    page.evaluate(SETTLE)
    narrowed = geometry(page)

    # Five results are far shorter than the rail. The search stays put under the reader's
    # cursor instead of being dragged down as the navigation scrolls back into view. (It can
    # settle one pixel lower: at the end of the shorter range the header sits at rest, under
    # the section's 1px divider, rather than held over it.)
    assert abs(narrowed["search"]["top"] - before["search"]["top"]) <= 1.5, (before["search"], narrowed["search"])
    assert narrowed["chats"]["bottom"] <= narrowed["region"]["top"]
    expect(search_box(page)).to_be_focused()

    search_box(page).fill("")
    expect(row_items(page)).to_have_count(PAGE_SIZE)


def test_the_collapsed_rail_and_other_pages_do_not_scroll_as_a_panel(open_page):
    page, api = open_page()
    mount(page, api)

    page.get_by_role("button", name="Collapse navigation", exact=True).click()
    expect(search_box(page)).to_have_count(0)
    collapsed = geometry(page)
    assert collapsed["region"]["overflowY"] == "visible", collapsed["region"]
    assert collapsed["scrollers"] == 0, "Nothing in the collapsed strip scrolls."

    page.get_by_role("button", name="Expand navigation", exact=True).click()
    expect(row_items(page)).to_have_count(PAGE_SIZE)
    assert geometry(page)["region"]["overflowY"] == "auto"

    other, other_api = open_page()
    mount(other, other_api, experience="HomeExperience", entry="/", rows=0)
    primary = other.get_by_role("navigation", name="Primary")
    expect(primary.get_by_role("link", name="My Workspace", exact=True)).to_be_visible()
    expect(search_box(other)).to_have_count(0)
    expect(other.get_by_title("Start a new chat", exact=True)).to_have_count(0)
    elsewhere = other.evaluate(
        """() => {
            const region = document.querySelector('[data-rail-scroll-region]');
            return {overflowY: getComputedStyle(region).overflowY, flexGrow: getComputedStyle(region).flexGrow};
        }"""
    )
    assert elsewhere == {"overflowY": "visible", "flexGrow": "1"}, elsewhere
    assert other_api.feed_queries == [], "Other pages do not load the conversation list."


def test_the_phone_drawer_holds_search_under_new_chat(open_page):
    page, api = open_page(PHONE)
    mount(page, api, rows=0)
    expect(search_box(page)).to_have_count(0)

    page.get_by_role("button", name="Expand navigation", exact=True).click()
    expect(row_items(page)).to_have_count(PAGE_SIZE)
    wheel_rail(page, 900)
    expect(header(page)).to_have_attribute("data-stuck", "")
    held = geometry(page)
    assert held["regionScrolls"], held
    assert held["chats"]["bottom"] <= held["region"]["top"]
    assert held_under_new_chat(held), held
    assert held["visible"] >= 10, held["visible"]

    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Expand navigation", exact=True)).to_be_visible()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_held_search_is_drawn_on_the_themes_solid_surface(open_page, theme):
    page, api = open_page()
    mount(page, api)
    if theme == "dark":
        page.get_by_role("button", name="Switch to dark theme", exact=True).click()
        expect(page.locator("html.dark")).to_have_count(1)
    wheel_rail(page, 900)
    expect(header(page)).to_have_attribute("data-stuck", "")
    held = geometry(page)
    assert held["header"]["background"] == HELD_BACKING[theme], held["header"]
    # The edge under it is drawn with a shadow, so nothing shifts when the search is held.
    shadow = header(page).evaluate("(element) => getComputedStyle(element).boxShadow")
    assert shadow not in ("", "none") and " 1px 0px" in shadow, shadow

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.locator("#primary-navigation").screenshot(path=str(ARTIFACTS / f"{theme}-held.png"))
