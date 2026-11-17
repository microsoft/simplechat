#!/usr/bin/env python3
# test_v2_notifications_page.py
"""
Functional test for the V2 Notifications page and the server-side filters behind it.
Version: 0.261.445
Implemented in: 0.261.445

The browser suite (ui_tests/test_v2_notifications_page.py) drives the page against a stand-in
server. On its own it cannot notice the stand-in drifting away from route_backend_notifications.py,
or the page drifting away from classic's `/notifications`, which shares its routes, its saved page
size and its notification documents. This test pins the contracts across those lines:

  - the page is registered in the SPA at `/notifications`, and the entry points that lead to it --
    the bell panel's footer and the account menu -- are router links, not anchors to classic;
  - every parameter the client sends to GET /api/notifications is one the server reads, with the same
    values: the read filters, the search cap and the page sizes, and the page size is saved through
    POST /api/notifications/settings with the key the server stores, never /api/user/settings;
  - the page's view of the list -- parse, serialize, clamp, the numbered pager and the wording of
    the live region -- is a pure module, which is run under Node as the browser runs it;
  - a link to the page resolves to a V2 route in the bell's resolver and in the Latest Features
    shortcuts, carries only the view the page can show, and still refuses every spelling of a link
    that would leave the site or open an API endpoint;
  - the row the panel and the page share keeps every attribute the browser suites select on, the
    page keeps its own page-scoped list instead of the bell's append-only one, and notification
    text is never markup; and
  - classic keeps sending neither new parameter, so it is answered as before.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


ORIGIN = "https://simplechat.test"

# Runs the shipped modules under Node's type stripping, so what is checked is the code the browser
# runs rather than a description of it. Each module is pure or imports only pure modules.
PROBE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const lib = (name) => import(pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', name)));
const view = await lib('notificationsPage.ts');
const links = await lib('notificationLinks.ts');
const shortcuts = await lib('latestFeatureShortcuts.ts');

const notice = (link) => ({
    id: 'n-1', notification_type: 'system_announcement', title: 'Title', message: 'Message',
    created_at: '2025-01-01T00:00:00Z', is_read: false, link_url: link,
    link_context: {}, metadata: {}, type_config: {},
});

process.stdout.write(JSON.stringify({
    constants: {
        statuses: view.NOTIFICATION_STATUSES,
        sizes: view.NOTIFICATIONS_PAGE_SIZES,
        defaultSize: view.DEFAULT_NOTIFICATIONS_PAGE_SIZE,
        searchMax: view.NOTIFICATIONS_SEARCH_MAX_LENGTH,
        path: view.NOTIFICATIONS_PATH,
        offSite: links.OFF_SITE_LINK,
    },
    parsed: input.addresses.map((search) => view.parseNotificationsView(search)),
    serialized: input.views.map((item) => view.serializeNotificationsView(item)),
    roundTrips: input.views.map((item) => view.parseNotificationsView(view.serializeNotificationsView(item))),
    sizes: input.sizes.map(([address, saved]) => view.resolveNotificationsPageSize(address, saved)),
    counts: input.counts.map(([total, perPage]) => view.notificationsPageCount(total, perPage)),
    clamps: input.clamps.map(([page, total, perPage]) => view.clampNotificationsPage(page, total, perPage)),
    ranges: input.ranges.map(([page, perPage, total]) => view.notificationsPageRange(page, perPage, total)),
    windows: input.windows.map(([page, count]) => view.notificationsPageItems(page, count)),
    sentences: input.results.map((item) => view.describeNotificationResults(item)),
    empties: input.empties.map((item) => view.describeEmptyNotifications(item)),
    pathsFor: input.pathsFor.map((search) => view.notificationsPathFor(search)),
    resolved: input.links.map((link) => links.resolveNotificationLink(notice(link), input.origin)),
    shortcuts: input.shortcuts.map((href) => shortcuts.resolveLatestFeatureShortcut(href)),
    shortcutRoutes: input.shortcutRoutes.map((path) => shortcuts.safeShortcutRouteHref(path)),
}));
"""

# Addresses as the page reads them, and what each one means.
ADDRESSES = [
    ("", {"status": "all", "query": "", "page": 1, "perPage": None}),
    (
        "?status=UNREAD&q=%20ledger%20&page=3&per_page=50&utm=1",
        {"status": "unread", "query": "ledger", "page": 3, "perPage": 50},
    ),
    ("?status=read&page=2&per_page=10", {"status": "read", "query": "", "page": 2, "perPage": 10}),
    # What the server would refuse or replace is replaced here first, so a stale or hand-edited
    # address never strands the reader on a request that fails the same way again.
    ("?status=archived&page=0&per_page=15", {"status": "all", "query": "", "page": 1, "perPage": None}),
    ("?page=-4&per_page=abc&q=", {"status": "all", "query": "", "page": 1, "perPage": None}),
    ("?page=2.5&per_page=20.0", {"status": "all", "query": "", "page": 1, "perPage": None}),
    ("?page=99999999", {"status": "all", "query": "", "page": 1, "perPage": None}),
    ("?page=999999", {"status": "all", "query": "", "page": 10000, "perPage": None}),
    ("?page=2&page=3&status=read&status=unread", {"status": "read", "query": "", "page": 2, "perPage": None}),
    ("?q=" + "x" * 130, {"status": "all", "query": "x" * 100, "page": 1, "perPage": None}),
    # The search is capped in characters, as the server counts them, not in UTF-16 units.
    ("?q=" + "%F0%9F%99%82" * 120, {"status": "all", "query": "\U0001F642" * 100, "page": 1, "perPage": None}),
]

VIEWS = [
    {"status": "all", "query": "", "page": 1, "perPage": None},
    {"status": "unread", "query": "", "page": 1, "perPage": None},
    {"status": "read", "query": "quarterly ledger", "page": 3, "perPage": 10},
    {"status": "all", "query": "a&b=c d", "page": 1, "perPage": 50},
    {"status": "bogus", "query": "  padded  ", "page": 0, "perPage": 15},
]

# Written in canonical order, with only what differs from the defaults; the last view is mended.
SERIALIZED = [
    "",
    "status=unread",
    "status=read&q=quarterly+ledger&page=3&per_page=10",
    "q=a%26b%3Dc+d&per_page=50",
    "q=padded",
]

SIZES = [
    (50, 20), (None, 50), (None, "10"), (None, 15), (None, "lots"), (None, None), (None, 0), (10, "garbage"),
]
EXPECTED_SIZES = [50, 50, 10, 20, 20, 20, 20, 10]

COUNTS = [(0, 20), (1, 20), (20, 20), (21, 20), (45, 10), (120, 10), (-5, 10), (7, 0)]
EXPECTED_COUNTS = [1, 1, 1, 2, 5, 12, 1, 1]

CLAMPS = [(1, 45, 20), (3, 45, 20), (4, 45, 20), (99, 45, 20), (0, 45, 20), (5, 0, 20), (2, 20, 20)]
EXPECTED_CLAMPS = [1, 3, 3, 3, 1, 1, 1]

RANGES = [(1, 20, 45), (2, 20, 45), (3, 20, 45), (9, 20, 45), (1, 20, 0), (1, 10, 1), (11, 10, 105)]
EXPECTED_RANGES = [
    {"from": 1, "to": 20}, {"from": 21, "to": 40}, {"from": 41, "to": 45}, {"from": 41, "to": 45},
    {"from": 0, "to": 0}, {"from": 1, "to": 1}, {"from": 101, "to": 105},
]

# (current page, page count) and the buttons offered, a gap being null.
WINDOWS = [
    (1, 1), (1, 3), (2, 7), (1, 8), (4, 12), (5, 12), (6, 12), (8, 12), (9, 12), (12, 12), (99, 12), (0, 12),
]
EXPECTED_WINDOWS = [
    [1],
    [1, 2, 3],
    [1, 2, 3, 4, 5, 6, 7],
    [1, 2, 3, 4, 5, None, 8],
    [1, 2, 3, 4, 5, None, 12],
    [1, None, 4, 5, 6, None, 12],
    [1, None, 5, 6, 7, None, 12],
    [1, None, 7, 8, 9, None, 12],
    [1, None, 8, 9, 10, 11, 12],
    [1, None, 8, 9, 10, 11, 12],
    [1, None, 8, 9, 10, 11, 12],
    [1, 2, 3, 4, 5, None, 12],
]

RESULTS = [
    ({"total": 45, "page": 2, "perPage": 20, "status": "all", "query": ""}, "Showing 21\u201340 of 45 notifications."),
    ({"total": 45, "page": 3, "perPage": 20, "status": "all", "query": ""}, "Showing 41\u201345 of 45 notifications."),
    ({"total": 1, "page": 1, "perPage": 20, "status": "all", "query": ""}, "Showing 1 of 1 notification."),
    (
        {"total": 21, "page": 1, "perPage": 10, "status": "unread", "query": ""},
        "Showing 1\u201310 of 21 unread notifications.",
    ),
    (
        {"total": 3, "page": 1, "perPage": 10, "status": "read", "query": "ledger"},
        "Showing 1\u20133 of 3 read notifications matching your search.",
    ),
    ({"total": 0, "page": 1, "perPage": 10, "status": "all", "query": ""}, "No notifications."),
    ({"total": 0, "page": 1, "perPage": 10, "status": "unread", "query": ""}, "No unread notifications."),
    ({"total": 0, "page": 1, "perPage": 10, "status": "read", "query": ""}, "No read notifications."),
    ({"total": 0, "page": 1, "perPage": 10, "status": "read", "query": "zzz"}, "No notifications match your search."),
    # The text typed is never read back, so a long or odd search cannot lengthen what is announced.
    ({"total": 0, "page": 1, "perPage": 10, "status": "all", "query": "<b>x</b>" * 20}, "No notifications match your search."),
]

EMPTIES = [
    ({"status": "all", "query": ""}, "You're all caught up", False),
    ({"status": "unread", "query": ""}, "No unread notifications", False),
    ({"status": "read", "query": ""}, "No read notifications", False),
    ({"status": "unread", "query": "ledger"}, "No notifications match your search", True),
    ({"status": "all", "query": "   "}, "You're all caught up", False),
]

PATHS_FOR = [
    "",
    "?status=Unread&q=%20ledger%20&page=2&per_page=50&evil=1",
    "?status=archived&page=abc",
    "?q=" + "y" * 150,
]
EXPECTED_PATHS_FOR = [
    "/notifications",
    "/notifications?status=unread&q=ledger&page=2&per_page=50",
    "/notifications",
    "/notifications?q=" + "y" * 100,
]

# Links to the page, as classic's resolver and the server write them, and the V2 route each opens.
FOLLOWED_LINKS = [
    ("/notifications", "/notifications"),
    ("/notifications/", "/notifications"),
    ("/notifications#top", "/notifications"),
    ("/notifications?status=Unread&q=%20ledger%20&page=2&per_page=50&evil=//host#top",
     "/notifications?status=unread&q=ledger&page=2&per_page=50"),
    ("/notifications?status=archived&page=abc", "/notifications"),
    (f"{ORIGIN}/notifications?status=read", "/notifications?status=read"),
    ("/v2/notifications?status=read", "/notifications?status=read"),
]

# The same page named in every way that would leave the site or reach an API endpoint. A link must
# stay on this site however its path is spelled, and the page's own query changes none of that.
OFF_SITE_LINKS = [
    "//evil.example/notifications?status=unread",
    "/\\evil.example/notifications?status=unread",
    "https://evil.example/notifications?q=ledger",
    "/.//evil.example/notifications?status=unread",
    "/x/..//evil.example/notifications",
    "/%2F%2Fevil.example/notifications",
    f"{ORIGIN}//evil.example/notifications?status=unread",
]
UNSUPPORTED_LINKS = [
    "/api/notifications?status=unread&q=ledger",
    "/notifications/../api/notifications",
    "/%61pi/notifications?status=unread",
    "/API/notifications",
    "javascript:alert(1)",
]
INVALID_LINKS = [
    "/notifications%2F..%2Fapi%2Fnotifications",
    "/notifications%00",
    "/notifications//x",
]

SHORTCUTS = [
    "/notifications", "/notifications?status=unread#list", "//evil.example/notifications", "/api/notifications",
]
EXPECTED_SHORTCUTS = [
    {"kind": "route", "path": "/notifications"},
    {"kind": "route", "path": "/notifications"},
    None,
    {"kind": "page", "href": "/api/notifications"},
]
SHORTCUT_ROUTES = ["/notifications", "/notifications?status=unread", "/notifications/evil", "//evil.example"]
EXPECTED_SHORTCUT_ROUTES = ["/notifications", "/support/latest-features", "/support/latest-features", "/support/latest-features"]

MARKUP_SINKS = ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")


def read_app(relative):
    return (APP_DIR / relative).read_text(encoding="utf-8")


def read_v2(relative):
    return (V2_SRC / relative).read_text(encoding="utf-8")


def run_probe():
    node = shutil.which("node")
    assert node, "Node.js is required to run the V2 notification page logic."
    payload = {
        "origin": ORIGIN,
        "addresses": [address for address, _ in ADDRESSES],
        "views": VIEWS,
        "sizes": SIZES,
        "counts": COUNTS,
        "clamps": CLAMPS,
        "ranges": RANGES,
        "windows": WINDOWS,
        "results": [item for item, _ in RESULTS],
        "empties": [item for item, _, _ in EMPTIES],
        "pathsFor": PATHS_FOR,
        "links": (
            [link for link, _ in FOLLOWED_LINKS] + OFF_SITE_LINKS + UNSUPPORTED_LINKS + INVALID_LINKS
        ),
        "shortcuts": SHORTCUTS,
        "shortcutRoutes": SHORTCUT_ROUTES,
    }
    result = subprocess.run(
        [node, "--input-type=module", "--eval", PROBE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload),
        # Node writes UTF-8, which the console's own encoding would misread on Windows.
        cwd=REPO_ROOT, text=True, encoding="utf-8", capture_output=True, timeout=90, check=False,
    )
    assert result.returncode == 0, (
        "The modules could not be run. Their imports need the V2 packages "
        f"(npm --prefix application/v2_ui ci):\n{result.stdout}\n{result.stderr}"
    )
    return json.loads(result.stdout)


def test_version_is_at_least_the_implementing_release():
    """The page is present from the version it was implemented in onwards."""
    assert_app_version_at_least("0.261.445")
    print("  ok  application version is at or beyond the implementing release")


def test_the_page_is_routed_and_both_entry_points_are_router_links():
    app = read_v2("App.tsx")
    assert "import { NotificationsPage } from './pages/NotificationsPage';" in app
    assert app.count('<Route path="/notifications" element={<NotificationsPage />} />') == 1

    panel = read_v2("components/layout/NotificationPanel.tsx")
    footer = re.search(
        r"<Link\s+to=\"/notifications\"(?P<attributes>.*?)\n\s*>\s*View all notifications\s*</Link>", panel, re.DOTALL,
    )
    assert footer, "The panel's footer is not a router link to the Notifications page."
    # Following it closes the panel, so it is not left over the page it led to.
    assert "onClick={() => onClose()}" in footer.group("attributes")
    assert 'href="/notifications"' not in panel and "classic interface" not in panel

    sidebar = read_v2("components/layout/Sidebar.tsx")
    user_menu = re.search(
        r"function UserMenu\(\{ collapsed \}: \{ collapsed: boolean \}\) \{(.*?)\nexport function ", sidebar, re.DOTALL,
    )
    assert user_menu, "UserMenu could not be located in Sidebar.tsx"
    menu = user_menu.group(1)
    entry = re.search(r'<NavLink\s+to="/notifications"(?P<body>.*?)</NavLink>', menu, re.DOTALL)
    assert entry, "The account menu has no Notifications entry."
    # The bell's own count, so the entry and the bell cannot disagree, and the same `9+` at the cap.
    assert "useNotificationStore((state) => state.count)" in menu
    assert "formatNotificationCount(unreadNotifications)" in entry.group("body")
    assert "Notifications, ${formatNotificationCount(unreadNotifications)} unread" in entry.group("body")
    assert menu.index('to="/notifications"') < menu.index('to="/settings"'), "Notifications leads the menu, as in classic."

    # The phone drawer is the same Sidebar, so the entry is reachable there with no change of its own.
    shell = read_v2("components/layout/AppShell.tsx")
    assert "<Sidebar mobile={mobile} />" in shell
    print("  ok  the page is routed and the panel and the account menu lead to it")


def test_the_clients_list_parameters_are_the_ones_the_server_reads():
    client = read_v2("lib/notifications.ts")
    route = read_app("route_backend_notifications.py")
    functions = read_app("functions_notifications.py")
    probe = run_probe()["constants"]

    # The two new parameters: sent only when they narrow the list, and read by the route.
    assert "params.set('status', query.status)" in client and "params.set('q', search)" in client
    assert "if (query.status && query.status !== 'all')" in client
    assert "request.args.get('status')" in route and "request.args.get('q', '')" in route
    # The route hands the filter to the list, and the list accepts exactly what the client offers.
    assert "read_status=read_status" in route and "search=request.args.get('q', '')" in route
    server_statuses = re.search(r"NOTIFICATION_READ_STATUS_FILTERS = \(([^)]*)\)", functions)
    assert server_statuses and re.findall(r"'(\w+)'", server_statuses.group(1)) == probe["statuses"]
    # The search is cut at the same length on both sides, so what is typed is what is searched.
    server_cap = int(re.search(r"NOTIFICATION_SEARCH_MAX_LENGTH = (\d+)", functions).group(1))
    assert server_cap == probe["searchMax"]
    # An unknown status is refused rather than shown as "all".
    assert "'Invalid status. Use all, unread or read.'" in route and "}), 400" in route

    # The page sizes the client offers are the ones both routes accept, and 20 is the default everywhere.
    accepted = re.search(r"if per_page not in \[([^\]]+)\]", route)
    assert accepted and [int(value) for value in accepted.group(1).split(",")] == probe["sizes"]
    saved = re.search(r"if per_page not in \[([^\]]+)\]:\s*return jsonify", route)
    assert saved and [int(value) for value in saved.group(1).split(",")] == probe["sizes"]
    default = int(re.search(r"export const NOTIFICATION_PAGE_SIZE = (\d+);", client).group(1))
    assert default == probe["defaultSize"] == 20
    assert "request.args.get('per_page', 20)" in route

    # The page size is saved through the notifications route, with the key the server stores.
    assert "api.post<unknown>('/api/notifications/settings', { notifications_per_page: perPage })" in client
    assert "data.get('notifications_per_page', 20)" in route
    assert "'notifications_per_page': per_page" in route
    # ...and read back through /api/user/settings, which returns the key but does not accept it.
    assert '"notifications_per_page",' in read_app("functions_settings.py")
    users_route = read_app("route_backend_users.py")
    allowed = re.search(r"allowed_keys = \{(.*?)\n\s*\}", users_route, re.DOTALL)
    assert allowed and "notifications_per_page" not in allowed.group(1)
    assert "notifications_per_page" not in read_v2("lib/userSettings.ts")
    print("  ok  the client's list parameters, page sizes and saved size are the server's")


def test_the_view_is_read_and_written_the_way_the_address_needs():
    probe = run_probe()

    assert probe["constants"]["path"] == "/notifications"
    assert probe["parsed"] == [expected for _, expected in ADDRESSES]
    assert probe["serialized"] == SERIALIZED
    # What the page writes it reads back, and what it cannot read it mends in the same way each time.
    mended = [
        {"status": "all", "query": "", "page": 1, "perPage": None},
        {"status": "unread", "query": "", "page": 1, "perPage": None},
        VIEWS[2], VIEWS[3],
        {"status": "all", "query": "padded", "page": 1, "perPage": None},
    ]
    assert probe["roundTrips"] == mended
    assert probe["sizes"] == EXPECTED_SIZES
    assert probe["counts"] == EXPECTED_COUNTS
    assert probe["clamps"] == EXPECTED_CLAMPS
    assert probe["ranges"] == EXPECTED_RANGES
    assert probe["pathsFor"] == EXPECTED_PATHS_FOR
    print("  ok  the address is parsed, written, clamped and mended consistently")


def test_the_pager_and_the_live_region_say_what_the_list_shows():
    probe = run_probe()

    assert probe["windows"] == EXPECTED_WINDOWS
    for (page, count), buttons in zip(WINDOWS, probe["windows"]):
        if count > 7:
            # A fixed width, so Next does not slide out from under the pointer on the click that moved it.
            assert len(buttons) == 7, (page, count, buttons)
        assert buttons[0] == 1 and buttons[-1] == count
        assert [number for number in buttons if number is not None] == sorted(number for number in buttons if number)
    assert probe["sentences"] == [sentence for _, sentence in RESULTS]
    for copy, (_, title, clearable) in zip(probe["empties"], EMPTIES):
        assert copy["title"] == title and copy["clearable"] is clearable and copy["description"]
    print("  ok  the pager window and the announced sentences are as the page needs")


def test_links_to_the_page_open_it_in_v2_and_never_leave_the_site():
    probe = run_probe()
    resolved = probe["resolved"]
    followed = resolved[: len(FOLLOWED_LINKS)]
    off_site = resolved[len(FOLLOWED_LINKS): len(FOLLOWED_LINKS) + len(OFF_SITE_LINKS)]
    unsupported = resolved[len(FOLLOWED_LINKS) + len(OFF_SITE_LINKS): -len(INVALID_LINKS)]
    invalid = resolved[-len(INVALID_LINKS):]

    for (link, route), result in zip(FOLLOWED_LINKS, followed):
        assert result == {"target": {"kind": "route", "path": route}, "error": None}, f"{link!r} opens {result}"
    # Only the view the page can show survives, so a link cannot carry anything else into the route.
    assert all("evil" not in result["target"]["path"] for result in followed)

    for link, result in zip(OFF_SITE_LINKS, off_site):
        assert result["target"] is None and result["error"] == probe["constants"]["offSite"], f"{link!r}: {result}"
    for link, result in zip(UNSUPPORTED_LINKS, unsupported):
        assert result["target"] is None and "unsupported link" in result["error"], f"{link!r}: {result}"
    for link, result in zip(INVALID_LINKS, invalid):
        assert result["target"] is None and "invalid link" in result["error"], f"{link!r}: {result}"

    # The Latest Features shortcuts translate the same page, from the allowlist and nowhere else.
    assert probe["shortcuts"] == EXPECTED_SHORTCUTS
    assert probe["shortcutRoutes"] == EXPECTED_SHORTCUT_ROUTES
    print("  ok  links to the page open it in V2 and every off-site or API spelling is still refused")


def test_the_page_is_its_own_list_and_the_row_is_shared_with_the_panel():
    page = read_v2("pages/NotificationsPage.tsx")
    hook = read_v2("lib/useNotificationsList.ts")
    row = read_v2("components/notifications/NotificationRow.tsx")
    panel = read_v2("components/layout/NotificationPanel.tsx")

    # Page-scoped state, read for one view at a time, rather than the bell's list that only grows.
    assert "fetchNotificationPage(current.page, controller.signal, {" in hook
    assert "status: current.status" in hook and "query: current.query" in hook and "perPage: current.perPage" in hook
    assert "state.items" not in page and "loadList" not in page and "state.hasMore" not in page
    # An answer is kept with the view it was for, so a slow earlier one is never shown under a later one.
    assert "result && result.key === key" in page and "controller.abort()" in hook
    # The count: read again after every change, and the list read again when it rises.
    assert "refreshNotificationCount('action')" in page
    assert "subscribeNotificationCount" in hook and "change.rose" in hook
    # The saved size is read from the preferences and written through the notifications route only.
    assert "state.settings.notifications_per_page" in page and "saveNotificationsPerPage(next)" in page
    assert "state.update" not in page and ".update(" not in page
    # The same helpers the panel opens a notice with.
    for name in ("resolveNotificationLink", "openNotificationTarget", "notificationNeedsAcknowledgment"):
        assert name in page and name in (panel + row), name
    assert "workflowAlertServerActions.acknowledge" in page

    # The row is one component in two places, and keeps every attribute the browser suites select on.
    assert "from '../notifications/NotificationRow'" in panel and "<NotificationRow" in panel
    assert "function NotificationRow" not in panel and "export function NotificationRow" in row
    for attribute in (
        "data-notification-id", "data-notification-type", "data-unread", "data-notification-action=\"open\"",
        "data-notification-action=\"acknowledge\"", "data-notification-action=\"read\"",
        "data-notification-action=\"dismiss\"", "data-notification-ack-tag", "data-notification-link-error",
        "data-notification-acknowledged",
    ):
        assert attribute in row, attribute
    for attribute in ("data-notification-panel=", "data-notification-action=\"mark-all-read\"",
                      "data-notification-action=\"load-more\"", "data-notification-panel-count", "data-notification-empty"):
        assert attribute in panel, attribute
    print("  ok  the page keeps its own list and shares one row with the panel")


def test_notification_text_on_the_page_is_never_markup():
    for relative in (
        "pages/NotificationsPage.tsx", "components/notifications/NotificationRow.tsx",
        "components/notifications/NotificationsPager.tsx", "components/notifications/NotificationsHeader.tsx",
        "lib/notificationsPage.ts", "lib/useNotificationsList.ts",
    ):
        source = read_v2(relative)
        for sink in MARKUP_SINKS:
            assert sink not in source, f"{relative} uses {sink}."
        assert not re.search(r"https?://", source), f"{relative} names an absolute address."
        assert "display:none" not in source.replace(" ", "")

    # Titles and messages are React text, and a link is resolved against this page's own origin.
    row = read_v2("components/notifications/NotificationRow.tsx")
    assert "{notification.message}" in row and "{title}" in row
    assert "window.location.origin" in read_v2("pages/NotificationsPage.tsx")
    print("  ok  notification text is rendered as text and links are resolved against this site")


def test_controls_that_can_become_unavailable_keep_keyboard_focus():
    """A browser takes focus from a button that becomes disabled, so these are never natively disabled."""
    for relative in ("components/notifications/NotificationsPager.tsx", "components/notifications/NotificationsHeader.tsx"):
        source = read_v2(relative)
        assert "aria-disabled" in source, f"{relative} does not say when a control is unavailable."
        assert not re.search(r"(?<![\w-])disabled=", source), f"{relative} disables a button natively."

    # Refresh and Mark all read are drawn by the page's own header, not the shared one, whose actions
    # are natively disabled while they are busy or have nothing to do.
    page = read_v2("pages/NotificationsPage.tsx")
    assert "<NotificationsHeader" in page and "<PageHeader" not in page
    for test_id in ("notifications-mark-all-read", "notifications-refresh"):
        assert f"testId: '{test_id}'" in page, test_id
    assert "action.disabled || action.loading" in read_v2("components/layout/HeaderActions.tsx"), (
        "The shared header changed; the page's own header may no longer need to differ from it."
    )
    # An unavailable end stop ignores the press, rather than asking for a page that does not exist.
    pager = read_v2("components/notifications/NotificationsPager.tsx")
    assert "aria-disabled={page <= 1 || undefined}" in pager
    assert "aria-disabled={page >= pageCount || undefined}" in pager
    print("  ok  the controls that can become unavailable stay focusable")


def test_classic_keeps_sending_neither_new_parameter_and_keeps_its_route():
    classic = read_app("static/js/notifications.js")
    list_query = re.search(r"const params = new URLSearchParams\(\{(?P<body>[^}]*)\}\);\s*fetch\(`/api/notifications\?", classic)
    assert list_query, "Classic's list query is not built where expected."
    assert re.findall(r"(\w+):", list_query.group("body")) == ["page", "per_page", "include_read", "include_dismissed"]
    assert "status" not in list_query.group("body") and "q:" not in list_query.group("body")
    # It still saves its page size through the route V2 uses now.
    assert "fetch('/api/notifications/settings'" in classic and "notifications_per_page: currentPerPage" in classic

    frontend = read_app("route_frontend_notifications.py")
    assert '@bp.route("/notifications")' in frontend and '"notifications.html"' in frontend
    print("  ok  classic still asks for the list as before and keeps its page")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_page_is_routed_and_both_entry_points_are_router_links,
    test_the_clients_list_parameters_are_the_ones_the_server_reads,
    test_the_view_is_read_and_written_the_way_the_address_needs,
    test_the_pager_and_the_live_region_say_what_the_list_shows,
    test_links_to_the_page_open_it_in_v2_and_never_leave_the_site,
    test_the_page_is_its_own_list_and_the_row_is_shared_with_the_panel,
    test_notification_text_on_the_page_is_never_markup,
    test_controls_that_can_become_unavailable_keep_keyboard_focus,
    test_classic_keeps_sending_neither_new_parameter_and_keeps_its_route,
]


def main():
    print("Testing the V2 Notifications page...\n")
    failures = []

    for test in TESTS:
        try:
            test()
        except Exception as error:  # noqa: BLE001 - a failure must not stop the rest
            failures.append(test.__name__)
            print(f"FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()

    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    if failures:
        print("Failed: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
