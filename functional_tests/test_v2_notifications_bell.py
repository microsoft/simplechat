#!/usr/bin/env python3
# test_v2_notifications_bell.py
"""
Functional test for the V2 notification bell, its panel and desktop notifications.
Version: 0.261.195
Implemented in: 0.261.195

The browser suite (ui_tests/test_v2_notifications_bell.py) drives the bell, the panel and the
desktop notifier against stubbed HTTP answers. On its own it cannot notice those stubs drifting
away from the server they stand in for, or V2 drifting away from the classic interface, which
shares the same preference, administrator switch and system notifications. This test pins the
contracts across both of those lines:

  - every notification call the SPA makes is one route_backend_notifications.py serves, with
    the same method and query parameters, and the SPA's page size and count cap are the
    server's;
  - the administrator switch reaches the SPA through the sanitized bootstrap, and the
    preference the SPA saves is one the user-settings route accepts, read with the default
    classic uses;
  - desktop notifications follow the classic rules: the same fallback text, the same system
    tag, the same test for "the reader can see it", the same safety-filter exclusion and the
    same deduplication keys;
  - permission is asked for from the gestures that can show a browser prompt, including the
    orchestrated send the browser suite does not drive;
  - the runtime runs from the application root and registers the navigator only once;
  - the seams later tracks build on are in place: the count-change feed Track N2's pop-ups
    subscribe to, and the workflow-run link Phase 6b fills in; and
  - notification text is never rendered as markup, links stay on this site, and no new file
    names an off-site address.
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.195"

# The files this feature added. Notification text passes through all of them on its way to
# the screen, and none of them has any reason to load or link anything off-site.
NOTIFICATION_SOURCES = [
    "components/layout/NotificationBell.tsx",
    "components/layout/NotificationPanel.tsx",
    "lib/appNavigation.ts",
    "lib/desktopNotifications.ts",
    "lib/notificationLinks.ts",
    "lib/notificationNavigation.ts",
    "lib/notifications.ts",
    "lib/replyEvents.ts",
    "lib/useNotificationRuntime.ts",
    "stores/notificationStore.ts",
]

# The calls the bell and panel are built on. More may be added (Track N2 reads workflow
# alerts), but none of these may go missing or change shape without the server changing too.
REQUIRED_CALLS = {
    ("GET", "/api/notifications/count"),
    ("GET", "/api/notifications"),
    ("POST", "/api/notifications/{id}/read"),
    ("DELETE", "/api/notifications/{id}/dismiss"),
    ("POST", "/api/notifications/mark-all-read"),
}

MARKUP_SINKS = ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")

SERVER_ROUTE_RE = re.compile(r'@bp\.route\(\s*"(?P<path>[^"]+)"\s*,\s*methods=\[(?P<methods>[^\]]*)\]\s*\)')
CLIENT_CALL_RE = re.compile(r"api\.(?P<method>get|post|put|patch|delete)<[^>]*>\(\s*[`'\"](?P<path>/api/[^`'\"?]*)")


def read_app(relative):
    return (APP_DIR / relative).read_text(encoding="utf-8")


def read_v2(relative):
    return (V2_SRC / relative).read_text(encoding="utf-8")


def normalize_route(path):
    """One spelling for a path parameter, whichever side wrote it."""
    return re.sub(r"<[^>]+>|\$\{[^}]+\}", "{id}", path)


def server_routes():
    routes = {}
    for match in SERVER_ROUTE_RE.finditer(read_app("route_backend_notifications.py")):
        methods = {item.strip().strip("'\"") for item in match.group("methods").split(",") if item.strip()}
        routes.setdefault(normalize_route(match.group("path")), set()).update(methods)
    return routes


def client_calls():
    return {
        (match.group("method").upper(), normalize_route(match.group("path")))
        for match in CLIENT_CALL_RE.finditer(read_v2("lib/notifications.ts"))
    }


def load_function(source, name):
    """Compile one top-level function from a module's source, without importing the module."""
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), name, "exec"), namespace)  # noqa: S102
    return namespace[name]


def test_version_is_at_least_the_implementing_release():
    """The feature is present from the version it was implemented in onwards."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_every_notification_call_is_a_route_the_server_serves():
    calls = client_calls()
    missing = REQUIRED_CALLS - calls
    assert not missing, f"The SPA no longer makes these calls: {sorted(missing)}"
    routes = server_routes()
    for method, path in sorted(calls):
        served = routes.get(path, set())
        assert method in served, f"{method} {path} is not served by route_backend_notifications.py ({served})"
    print("  ok  every notification call is served with the same method")


def test_the_list_query_page_size_and_count_cap_are_the_servers():
    client = read_v2("lib/notifications.ts")
    route = read_app("route_backend_notifications.py")

    params = re.search(r"new URLSearchParams\(\{(?P<body>[^}]*)\}\)", client)
    assert params, "The list query is not built where expected."
    names = re.findall(r"(\w+):", params.group("body"))
    assert names == ["page", "per_page", "include_read", "include_dismissed"], names
    for name in names:
        assert f"request.args.get('{name}'" in route, f"The server does not read {name}."

    # A size the server does not accept is silently replaced by its default, and "load more"
    # would then skip or repeat notices.
    page_size = int(re.search(r"export const NOTIFICATION_PAGE_SIZE = (\d+);", client).group(1))
    accepted = re.search(r"if per_page not in \[([^\]]+)\]", route)
    assert accepted, "The server's page sizes are not declared where expected."
    assert page_size in {int(value) for value in accepted.group(1).split(",")}, page_size

    # The badge reads the cap as "this many or more", so it must be the server's own cap.
    count_cap = int(re.search(r"export const NOTIFICATION_COUNT_CAP = (\d+);", client).group(1))
    server_cap = re.search(r"return min\(result\['total'\], (\d+)\)", read_app("functions_notifications.py"))
    assert server_cap, "The server's count cap is not declared where expected."
    assert count_cap == int(server_cap.group(1)), (count_cap, server_cap.group(1))
    print("  ok  the list query, page size and count cap match the server")


def test_the_administrator_switch_and_the_preference_reach_both_sides():
    v2_route = read_app("route_backend_v2.py")
    assert "public_settings = sanitize_settings_for_user(settings)" in v2_route
    assert '"features": _build_feature_flags(public_settings, per_user_overrides)' in v2_route
    build_feature_flags = load_function(v2_route, "_build_feature_flags")
    assert build_feature_flags({"enable_desktop_notifications": True, "app_title": "Contoso Chat"}, {}) == {
        "enable_desktop_notifications": True,
    }
    assert build_feature_flags({"enable_desktop_notifications": False}, {}) == {
        "enable_desktop_notifications": False,
    }
    # Sanitizing drops any key containing one of these terms; the switch must survive it.
    functions_settings = read_app("functions_settings.py")
    terms = re.search(r"sensitive_terms = (\([^)]*\))", functions_settings)
    assert terms, "The sanitizer's sensitive terms are not declared where expected."
    assert not any(term in "enable_desktop_notifications" for term in ast.literal_eval(terms.group(1)))

    notifier = read_v2("lib/desktopNotifications.ts")
    # The same strict reading as classic's `appSettings.enable_desktop_notifications === true`.
    assert "features?.enable_desktop_notifications === true" in notifier
    assert "export const DESKTOP_NOTIFICATIONS_SETTING = 'desktopNotificationsEnabled';" in notifier
    # A reader who never chose is opted in, on both sides.
    assert "return value === undefined ? true : Boolean(value);" in notifier
    assert 'user_settings_dict.get("desktopNotificationsEnabled", True)' in read_app("route_frontend_chats.py")

    # The preference is saved as the boolean the user-settings route insists on.
    users_route = read_app("route_backend_users.py")
    assert "'desktopNotificationsEnabled'," in users_route
    assert 'if not isinstance(settings_to_update["desktopNotificationsEnabled"], bool):' in users_route
    preferences = read_v2("components/settings/PreferencesTab.tsx")
    assert "update({ [DESKTOP_NOTIFICATIONS_SETTING]: next });" in preferences
    assert "{enabled('enable_desktop_notifications') && (" in preferences
    print("  ok  the administrator switch and the preference cross to the server intact")


def test_desktop_notifications_follow_the_classic_rules():
    classic = read_app("static/js/chat/chat-desktop-notifications.js")
    notifier = read_v2("lib/desktopNotifications.ts")

    # The same fallback wording.
    assert "|| 'Simple Chat'" in classic and "|| 'Simple Chat'" in notifier
    assert "|| 'Conversation'" in classic and "|| 'Conversation'" in notifier
    # Nothing from the reply itself: the body is the conversation's title.
    assert "body: reply.conversationTitle?.trim() || 'Conversation'," in notifier
    # One system tag per conversation, shared, so either interface replaces the other's notice.
    assert "`simplechat-conversation-${conversationId}`" in classic
    assert "`simplechat-conversation-${reply.conversationId}`" in notifier
    # The same test for "the reader can already see it".
    watched = "document.visibilityState !== 'hidden' && document.hasFocus()"
    assert watched in classic and watched in notifier
    # The same keys, so one reply is one notice.
    assert "`message:${messageId}`" in classic and "`message:${reply.messageId}`" in notifier
    assert "`conversation:${conversationId}`" in classic and "`conversation:${reply.conversationId}`" in notifier
    # Never for a reply the safety filter replaced.
    assert "finalData.role === 'safety'" in classic
    for relative in ("stores/chatStore.ts", "lib/orchestrationController.ts"):
        assert "blocked: event.blocked === true || event.role === 'safety'," in read_v2(relative), relative
    print("  ok  desktop notifications follow the classic rules")


def test_permission_is_asked_for_from_gestures_that_can_show_a_prompt():
    composer = read_v2("components/chat/Composer.tsx")
    # Once for an orchestrated turn and once for a chat turn, both inside the send gesture.
    asks = composer.count("void requestDesktopNotificationPermission();")
    assert asks == 2, f"Sending asks for permission from {asks} place(s), not from both send paths."
    orchestrated = re.search(
        r"if \(orchestrating\) \{[^}]*void requestDesktopNotificationPermission\(\);\s*dispatchOrchestration\(",
        composer,
    )
    assert orchestrated, "An orchestrated send no longer asks for permission before it is dispatched."
    preferences = read_v2("components/settings/PreferencesTab.tsx")
    # Turning the preference on, and the Allow button.
    assert preferences.count("requestDesktopNotificationPermission({ explicit: true })") == 2
    print("  ok  permission is asked for from the send, the toggle and the Allow button")


def test_the_runtime_runs_from_the_root_and_registers_the_navigator_once():
    assert "useNotificationRuntime(Boolean(data) && !error);" in read_v2("App.tsx")
    runtime = read_v2("lib/useNotificationRuntime.ts")
    assert "subscribeCompletedReplies(showReplyNotification)" in runtime
    assert "startNotificationPolling();" in runtime and "stopNotificationPolling();" in runtime

    # Registered on mount only. Keyed on `navigate`, which the router replaces on every change
    # of page, it was unregistered at the very moment the change was announced, and a reply
    # that landed while the reader was on another page stayed unread after they came back.
    registration = re.search(
        r"useEffect\(\s*\(\)\s*=>\s*registerAppNavigator\(\{(?P<body>.*?)\}\),\s*\[(?P<deps>[^\]]*)\],?\s*\)",
        runtime,
        re.DOTALL,
    )
    assert registration, "The navigator is not registered from an effect of its own."
    assert registration.group("deps").strip() == "", registration.group("deps")
    assert "navigateRef.current(path)" in registration.group("body")
    assert "pathnameRef.current" in registration.group("body")

    sidebar = read_v2("components/layout/Sidebar.tsx")
    assert "<NotificationBell collapsed={false}" in sidebar, "The expanded rail has no bell."
    assert "<NotificationBell collapsed " in sidebar, "The collapsed rail has no bell."
    print("  ok  the runtime runs from the root and the navigator is registered once")


def test_the_seams_later_tracks_build_on_are_in_place():
    store = read_v2("stores/notificationStore.ts")
    # Track N2's pop-ups subscribe to the count and act when it rises.
    assert "export function subscribeNotificationCount(" in store
    assert re.search(r"export interface NotificationCountChange \{[^}]*\brose: boolean;", store, re.DOTALL)

    links = read_v2("lib/notificationLinks.ts")
    # Phase 6b gives workflow runs a V2 page; both resolvers ask this one function for it.
    assert "export function v2WorkflowRunPath(" in links
    assert links.count("v2WorkflowRunPath(") >= 3
    # Links are read with the chat page's own reader, so both accept the same spellings.
    assert "import { readConversationParam } from './conversationUrl';" in links

    # Workflow runs announce delivered results through the same channel as chat replies.
    events = read_v2("lib/replyEvents.ts")
    assert "export type CompletedReplySource = 'chat' | 'orchestration' | 'workflow';" in events
    print("  ok  the count-change feed and the workflow-run link are in place")


def test_notification_text_is_never_markup_and_links_stay_on_this_site():
    for relative in NOTIFICATION_SOURCES:
        source = read_v2(relative)
        for sink in MARKUP_SINKS:
            assert sink not in source, f"{relative} uses {sink}."
        assert not re.search(r"https?://", source), f"{relative} names an absolute address."

    panel = read_v2("components/layout/NotificationPanel.tsx")
    # Every link in the panel is resolved against this page's own origin.
    assert "const origin = window.location.origin;" in panel
    assert "resolveNotificationLink(item, origin)" in panel
    links = read_v2("lib/notificationLinks.ts")
    assert "if (url.origin !== origin) {" in links
    assert "if (path === '/api' || path.startsWith('/api/')) {" in links
    print("  ok  notification text is plain text and links stay on this site")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_every_notification_call_is_a_route_the_server_serves,
    test_the_list_query_page_size_and_count_cap_are_the_servers,
    test_the_administrator_switch_and_the_preference_reach_both_sides,
    test_desktop_notifications_follow_the_classic_rules,
    test_permission_is_asked_for_from_gestures_that_can_show_a_prompt,
    test_the_runtime_runs_from_the_root_and_registers_the_navigator_once,
    test_the_seams_later_tracks_build_on_are_in_place,
    test_notification_text_is_never_markup_and_links_stay_on_this_site,
]


def main():
    print("Testing the V2 notification bell, panel and desktop notifications...\n")
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
