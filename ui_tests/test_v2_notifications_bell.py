# test_v2_notifications_bell.py
"""
Browser regressions for the V2 notification bell, its panel and desktop notifications.
Version: 0.261.194
Implemented in: 0.261.194

Exercises the real rail, bell, panel, chat page, preferences tab, stores and notification
runtime, bundled by fixtures/notification_bell. Only HTTP answers and the browser APIs a
headless page cannot drive -- Notification, page visibility and window focus -- are replaced.
The existing Azure Playwright connection fixture also supports a local browser; no live
application data is read or modified.
"""

import copy
import json
import mimetypes
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
    conversation_mark_read_payload,
    notification_count_payload,
)


pytestmark = pytest.mark.ui

FIXTURE = ROOT / "ui_tests" / "fixtures" / "notification_bell"
BUNDLE = FIXTURE / "harness.bundle.js"
V2_SOURCE = ROOT / "application" / "v2_ui" / "src"
STATIC = ROOT / "application" / "single_app" / "static"
# A secure context, as every deployment is: browsers offer notifications to no other kind.
ORIGIN = "https://simplechat.test"
BASE_TIME = datetime(2025, 6, 2, 15, 0, tzinfo=timezone.utc)
CLOCK_START = datetime(2025, 6, 3, 9, 0, tzinfo=timezone.utc)
CLASSIC_PAGES = {"/approvals", "/workflow-activity", "/chats", "/notifications"}
DEFAULT_FEATURES = {"enable_desktop_notifications": True}
DEFAULT_BRANDING = {"app_title": "Contoso Chat"}
CONVERSATIONS = {
    "conv-a": "Quarterly plan",
    "conv-b": "Budget review",
}
XSS_MESSAGE = '<img src=x onerror="window.__xss=1"><b>Quoted mail</b> & <script>window.__xss=2</script>'

OFF_SITE = "This notification links to another site, so it is not opened from here."
UNSUPPORTED = "This notification has an unsupported link. Open the destination directly."
INVALID = "This notification has an invalid link. Open the destination directly."
MISMATCH = (
    "This notification does not match its group and document. "
    "Refresh notifications or open the workspace directly."
)
DELETED = (
    "Could not open that conversation. It may have been deleted, "
    "or you may not have access to it."
)

# Page visibility, window focus and the Notification API, as a desktop browser has them.
# Installed before any application code runs, on every document the page loads.
FAKE_BROWSER = r"""
(options) => {
    const env = {
        visible: options.visible !== false,
        focused: options.focused !== false,
        autoShowOnFocus: options.autoShowOnFocus !== false,
        focusCalls: 0,
    };
    window.__harnessEnv = env;
    Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (env.visible ? 'visible' : 'hidden'),
    });
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => !env.visible});
    document.hasFocus = () => env.visible && env.focused;

    // Events in the order a browser sends them: visibility, then focus, on the way back;
    // blur, then visibility, on the way out.
    const show = () => {
        const wasHidden = !env.visible;
        const wasBlurred = !env.focused;
        env.visible = true;
        env.focused = true;
        if (wasHidden) document.dispatchEvent(new Event('visibilitychange'));
        if (wasBlurred) window.dispatchEvent(new FocusEvent('focus'));
    };
    const hide = () => {
        const wasFocused = env.focused;
        const wasVisible = env.visible;
        env.focused = false;
        env.visible = false;
        if (wasFocused) window.dispatchEvent(new FocusEvent('blur'));
        if (wasVisible) document.dispatchEvent(new Event('visibilitychange'));
    };
    const blur = () => {
        if (!env.focused) return;
        env.focused = false;
        window.dispatchEvent(new FocusEvent('blur'));
    };
    window.__harness = {show, hide, blur};
    // Bringing the window forward, as clicking a system notification does.
    window.focus = () => {
        env.focusCalls += 1;
        if (env.autoShowOnFocus) setTimeout(show, 0);
    };

    window.__fetchLog = [];
    const originalFetch = window.fetch;
    window.fetch = function (input, init) {
        try {
            const raw = typeof input === 'string' ? input : (input && input.url) || String(input);
            const url = new URL(raw, window.location.href);
            const method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
            window.__fetchLog.push({path: url.pathname + url.search, method, at: Date.now()});
        } catch (error) {
            window.__fetchLog.push({path: String(input), method: 'GET', at: Date.now()});
        }
        return originalFetch.apply(window, arguments);
    };

    if (options.notification === false) {
        delete window.Notification;
        return;
    }
    class FakeNotification extends EventTarget {
        constructor(title, init = {}) {
            super();
            this.title = String(title);
            this.body = init.body === undefined ? '' : String(init.body);
            this.tag = init.tag === undefined ? '' : String(init.tag);
            this.closed = false;
            FakeNotification.instances.push(this);
        }

        close() {
            this.closed = true;
        }

        click() {
            this.dispatchEvent(new Event('click'));
        }

        static requestPermission(callback) {
            const activation = navigator.userActivation;
            FakeNotification.requests.push({
                active: Boolean(activation && activation.isActive),
                eventType: window.event ? window.event.type : null,
            });
            FakeNotification.permission = FakeNotification.nextPermission;
            if (typeof callback === 'function') callback(FakeNotification.permission);
            return Promise.resolve(FakeNotification.permission);
        }
    }
    FakeNotification.permission = options.permission || 'granted';
    FakeNotification.nextPermission = options.nextPermission || 'granted';
    FakeNotification.requests = [];
    FakeNotification.instances = [];
    Object.defineProperty(window, 'Notification', {
        configurable: true,
        writable: true,
        value: FakeNotification,
    });
}
"""

# Set the page and the stores to one scenario, announce one finished reply, and return the
# system notifications it raised.
ANNOUNCE_AND_COLLECT = r"""
(scenario) => {
    const H = window.NotificationHarness;
    const env = window.__harnessEnv;
    env.visible = scenario.visible;
    env.focused = scenario.focused;
    const bootstrap = H.stores.bootstrap.useBootstrapStore;
    const data = bootstrap.getState().data;
    bootstrap.setState({data: {...data, features: scenario.features, branding: scenario.branding}});
    H.stores.userSettings.useUserSettingsStore.setState({
        settings: scenario.settings,
        loading: scenario.loading,
        error: scenario.error,
    });
    window.Notification.permission = scenario.permission;
    const before = window.Notification.instances.length;
    H.replyEvents.announceCompletedReply(scenario.reply);
    return window.Notification.instances.slice(before).map((item) => ({
        title: item.title,
        body: item.body,
        tag: item.tag,
    }));
}
"""


def iso(moment):
    return moment.isoformat()


def notice(notice_id, notification_type, title, message="", *, link_url="", link_context=None,
           metadata=None, read=False, color="info", icon="bi-bell", **extra):
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


def chat_notice(notice_id, conversation_id, title, preview="The reply is ready.", *, read=False,
                message_id=None, param="conversationId"):
    """The "AI responded" notice route_backend_chats writes when a personal reply finishes."""
    return notice(
        notice_id, "chat_response_complete", f"AI responded in {title}", preview,
        link_url=f"/chats?{param}={conversation_id}",
        link_context={"workspace_type": "personal", "conversation_id": conversation_id},
        metadata={"conversation_id": conversation_id, "message_id": message_id or f"msg-{notice_id}"},
        read=read, color="success", icon="bi-chat-dots",
    )


def workflow_notice(notice_id, message, *, group_id=None, read=False):
    metadata = {"workflow_id": "wf-1", "run_id": "run-1"}
    if group_id:
        metadata["group_id"] = group_id
    return notice(
        notice_id, "workflow_priority_alert", "Nightly digest failed", message,
        link_url="/workflow-activity?workflowId=wf-1&runId=run-1",
        metadata=metadata, read=read, color="danger", icon="bi-exclamation-octagon",
        priority="high", category="failure",
    )


def m365_approval_notice(notice_id="n-m365", approval_id="appr-1"):
    # functions_notifications.py names the approver's own id as the group.
    return notice(
        notice_id, "m365_approval_pending", "Microsoft 365 approval required",
        "Send the weekly update email to 3 recipients.",
        link_url=f"/approvals?m365_approval={approval_id}",
        link_context={"approval_id": approval_id, "group_id": "user-1"},
        color="warning", icon="bi-shield-check",
    )


def m365_pending_action_notice(notice_id="n-m365-action", conversation_id="conv-b", action_id="act-1"):
    return notice(
        notice_id, "system_announcement", "Microsoft 365 action awaiting review",
        "Review the calendar invite before it is sent.",
        link_url=f"/chats?conversationId={conversation_id}&m365_pending_action={action_id}",
        metadata={"m365_pending_action_id": action_id, "workflow_id": None, "conversation_id": conversation_id},
    )


def document_notice(notice_id="n-doc", read=False):
    return notice(
        notice_id, "document_processing_complete", "Document ready: Q3 forecast.pdf",
        "Q3 forecast.pdf finished processing and is ready to search.",
        link_url="/workspace?document_id=doc-1",
        link_context={"workspace_type": "personal", "document_id": "doc-1"},
        read=read, color="success", icon="bi-file-earmark-check",
    )


def share_notice(notice_id="n-share", read=False):
    return notice(
        notice_id, "personal_document_share_pending", "Alex shared a document with you",
        "Budget.xlsx is waiting for you to accept it.",
        link_url="/workspace", read=read, icon="bi-share",
    )


def announcement_notice(notice_id="n-announce", title="Maintenance on Saturday", *, read=False, link_url=""):
    return notice(
        notice_id, "system_announcement", title,
        "The service will be read-only from 08:00 to 09:00 UTC.",
        link_url=link_url, read=read, color="secondary",
    )


CLASSIC_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Classic page</title></head>'
    "<body><h1>Classic interface</h1></body></html>"
)
SIGN_IN_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Sign in</title></head>'
    "<body><h1>Sign in</h1></body></html>"
)


def stream_body(frames):
    return "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)


class NotificationApi:
    """The routes the frame calls, answered the way route_backend_* answers, with their state."""

    def __init__(self, page):
        self.page = page
        self.notices = []
        self.conversations = {
            conversation_id: {"id": conversation_id, "title": title, "unread": False}
            for conversation_id, title in CONVERSATIONS.items()
        }
        self.requests = []
        self.list_queries = []
        self.read_calls = []
        self.dismiss_calls = []
        self.mark_all_calls = 0
        self.conversation_reads = []
        self.set_active_calls = []
        self.settings_posts = []
        self.fail_next = set()
        self.count_failure = None
        self.set_active_status = 200
        self.hold_kinds = set()
        self.held_kinds = {}
        self.hold_streams = False
        self.held_streams = []
        self.streams = 0
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

    def listed(self, include_read=True, include_dismissed=False):
        items = [
            record for record in self.notices
            if (include_dismissed or not record["is_dismissed"]) and (include_read or not record["is_read"])
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
        self.requests.append((method, f"{path}?{parsed.query}" if parsed.query else path, request.resource_type))
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        for answer in (self.page_route, self.notification_route, self.conversation_route, self.other_route):
            if answer(route, method, path, query):
                return
        self.unexpected.append(f"{method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def page_route(self, route, method, path, query):
        if method != "GET":
            return False
        if path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        elif path in CLASSIC_PAGES:
            route.fulfill(content_type="text/html", body=CLASSIC_PAGE)
        elif path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if not (asset.is_relative_to(STATIC.resolve()) and asset.is_file()):
                return False
            route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        else:
            return False
        return True

    def notification_route(self, route, method, path, query):
        if method == "GET" and path == "/api/notifications/count":
            self.answer_count(route, path)
        elif method == "GET" and path == "/api/notifications":
            self.answer_list(route, query)
        elif method == "POST" and path == "/api/notifications/mark-all-read":
            self.answer_mark_all(route, path)
        elif method == "POST" and (match := re.fullmatch(r"/api/notifications/([^/]+)/read", path)):
            self.answer_notice_change(route, path, unquote(match.group(1)), "read")
        elif method == "DELETE" and (match := re.fullmatch(r"/api/notifications/([^/]+)/dismiss", path)):
            self.answer_notice_change(route, path, unquote(match.group(1)), "dismiss")
        else:
            return False
        return True

    def conversation_route(self, route, method, path, query):
        if method == "GET" and path == "/api/conversations/feed":
            rows = [
                {
                    "id": item["id"], "title": item["title"], "last_updated": iso(BASE_TIME),
                    "has_unread_assistant_response": item["unread"], "is_pinned": False, "is_hidden": False,
                }
                for item in self.conversations.values()
            ]
            route.fulfill(json={
                "success": True, "conversations": rows, "has_more": False, "next_cursor": None,
                "page_size": int(query.get("page_size", 50)), "hidden_count": 0, "priority_count": 0,
                "recent_count": len(rows), "source_offsets": {},
            })
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/kind", path)):
            conversation_id = unquote(match.group(1))
            if conversation_id in self.hold_kinds:
                self.hold_kinds.discard(conversation_id)
                self.held_kinds[conversation_id] = route
            else:
                self.answer_kind(route, conversation_id)
        elif method == "GET" and re.fullmatch(r"/api/conversations/[^/]+/metadata", path):
            route.fulfill(json={})
        elif method == "GET" and path == "/api/get_messages":
            route.fulfill(json={"messages": []})
        elif method == "POST" and (match := re.fullmatch(r"/api/conversations/([^/]+)/mark-read", path)):
            self.answer_conversation_read(route, unquote(match.group(1)))
        else:
            return False
        return True

    def other_route(self, route, method, path, query):
        if method == "GET" and re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
        elif method == "GET" and path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
        elif method == "POST" and path == "/api/chat/stream":
            body = route.request.post_data_json or {}
            if self.hold_streams:
                self.held_streams.append((route, body))
            else:
                self.answer_stream(route, body)
        elif method == "POST" and path == "/api/user/settings":
            self.settings_posts.append(route.request.post_data_json)
            route.fulfill(json={"message": "User settings updated successfully"})
        elif method == "PATCH" and path == "/api/groups/setActive":
            self.set_active_calls.append(route.request.post_data_json)
            if self.set_active_status == 200:
                route.fulfill(json={"message": "Active group set"})
            else:
                self.expected_http_failures.add((path, self.set_active_status))
                route.fulfill(status=self.set_active_status, json={"error": "Group not found"})
        else:
            return False
        return True

    # Answers ----------------------------------------------------------------------------------

    def answer_count(self, route, path):
        failure = self.count_failure
        if failure == "html":
            # What a lapsed session gets from a gateway that sends it to sign in: a 200 page.
            route.fulfill(content_type="text/html", body=SIGN_IN_PAGE)
        elif failure:
            self.expected_http_failures.add((path, failure))
            message = {401: "Unauthorized", 403: "Forbidden"}.get(failure, "Internal server error")
            route.fulfill(status=failure, json={"error": message})
        else:
            # get_unread_notification_count caps the count at 10.
            route.fulfill(json=notification_count_payload(min(len(self.unread()), 10)))

    def answer_list(self, route, query):
        self.list_queries.append(query)
        page_number = int(query.get("page", 1))
        per_page = int(query.get("per_page", 20))
        items = self.listed(query.get("include_read", "true") == "true", query.get("include_dismissed") == "true")
        start = (page_number - 1) * per_page
        route.fulfill(json={
            "success": True,
            "notifications": copy.deepcopy(items[start:start + per_page]),
            "total": len(items),
            "page": page_number,
            "per_page": per_page,
            "has_more": start + per_page < len(items),
        })

    def answer_notice_change(self, route, path, notice_id, change):
        (self.read_calls if change == "read" else self.dismiss_calls).append(notice_id)
        record = self.find(notice_id)
        if change in self.fail_next or record is None:
            self.fail_next.discard(change)
            self.expected_http_failures.add((path, 400))
            error = "Failed to mark notification as read" if change == "read" else "Failed to dismiss notification"
            route.fulfill(status=400, json={"error": error})
            return
        if change == "read":
            record["is_read"] = True
            route.fulfill(json={"success": True, "message": "Notification marked as read"})
        else:
            record["is_dismissed"] = True
            route.fulfill(json={"success": True, "message": "Notification dismissed"})

    def answer_mark_all(self, route, path):
        self.mark_all_calls += 1
        if "mark_all" in self.fail_next:
            self.fail_next.discard("mark_all")
            self.expected_http_failures.add((path, 500))
            route.fulfill(status=500, json={"error": "Internal server error"})
            return
        unread = self.unread()
        for record in unread:
            record["is_read"] = True
        route.fulfill(json={
            "success": True, "message": f"{len(unread)} notifications marked as read", "count": len(unread),
        })

    def answer_kind(self, route, conversation_id):
        if conversation_id in self.conversations:
            route.fulfill(json={"conversation_id": conversation_id, "kind": "personal"})
            return
        self.expected_http_failures.add((urlsplit(route.request.url).path, 404))
        route.fulfill(status=404, json={"error": "Conversation not found"})

    def answer_conversation_read(self, route, conversation_id):
        self.conversation_reads.append(conversation_id)
        if conversation_id in self.conversations:
            self.conversations[conversation_id]["unread"] = False
        marked = 0
        for record in self.notices:
            if (
                record["notification_type"] == "chat_response_complete"
                and not record["is_read"]
                and record["metadata"].get("conversation_id") == conversation_id
            ):
                record["is_read"] = True
                marked += 1
        payload = conversation_mark_read_payload(conversation_id)
        payload["notifications_marked_read"] = marked
        route.fulfill(json=payload)

    def answer_stream(self, route, body):
        """Finish a personal reply the way route_backend_chats does: unread, with a notice."""
        self.streams += 1
        number = self.streams
        conversation_id = body.get("conversation_id") or "conv-a"
        conversation = self.conversations[conversation_id]
        conversation["unread"] = True
        message_id = f"reply-{number}"
        self.add(chat_notice(f"n-reply-{number}", conversation_id, conversation["title"], message_id=message_id))
        route.fulfill(content_type="text/event-stream", body=stream_body([
            {"type": "user_message_persisted", "conversation_id": conversation_id, "user_message_id": f"user-{number}"},
            {"content": "Here is the plan."},
            {
                "done": True, "conversation_id": conversation_id, "conversation_title": conversation["title"],
                "message_id": message_id, "user_message_id": f"user-{number}",
                "full_content": "Here is the plan.", "chat_type": "personal",
            },
        ]))

    def release_stream(self):
        assert self.held_streams, "No chat request was held."
        route, body = self.held_streams.pop(0)
        self.answer_stream(route, body)

    def release_kind(self, conversation_id):
        assert conversation_id in self.held_kinds, f"No kind request for {conversation_id} was held."
        self.answer_kind(self.held_kinds.pop(conversation_id), conversation_id)

    def saw(self, method, target):
        """Whether a request was made; the target's query need only be a subset of the actual one."""
        wanted = urlsplit(target)
        wanted_query = parse_qs(wanted.query)
        for seen_method, seen_target, _ in self.requests:
            seen = urlsplit(seen_target)
            if seen_method != method or seen.path != wanted.path:
                continue
            seen_query = parse_qs(seen.query)
            if all(seen_query.get(key) == value for key, value in wanted_query.items()):
                return True
        return False

    def count_requests(self, method, path):
        return sum(1 for seen_method, seen_target, _ in self.requests
                   if seen_method == method and urlsplit(seen_target).path == path)


SEED = r"""
(seed) => {
    const H = window.NotificationHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.194',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: seed.features,
            branding: seed.branding,
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
        error: seed.settingsError,
    });
    H.stores.ui.useUiStore.setState({railCollapsed: seed.railCollapsed, mobileNavOpen: false});
    H.stores.chat.useChatStore.setState({
        activeConversationId: seed.active,
        activeConversationKind: 'personal',
        conversations: seed.conversations,
        messages: [],
        streaming: false,
        messagesLoading: false,
    });
    H.mount(seed.path);
}
"""

COUNT_SETTLED = r"""
() => {
    const started = window.__fetchLog.filter((item) => item.path === '/api/notifications/count').length;
    const store = window.NotificationHarness.stores.notification.useNotificationStore.getState();
    return started > 0 && (started === window.NotificationHarness.countChanges.length || store.halted);
}
"""

LIST_SETTLED = r"""
() => {
    const store = window.NotificationHarness.stores.notification.useNotificationStore.getState();
    return store.listLoaded && !store.listLoading;
}
"""


class Harness(NotificationApi):
    """The frame in a browser page, driven the way a reader drives it."""

    def __init__(self, page, stylesheets):
        super().__init__(page)
        self.stylesheets = stylesheets

    def open(self, path="/chat", *, browser=None, features=None, settings=None, settings_loading=False,
             settings_error=None, rail_collapsed=False, branding=None, clock=False, active="conv-a"):
        options = {"visible": True, "focused": True, **(browser or {})}
        self.page.add_init_script(script=f"({FAKE_BROWSER})({json.dumps(options)})")
        if clock:
            self.page.clock.install(time=CLOCK_START)
            self.page.clock.pause_at(CLOCK_START + timedelta(seconds=1))
        self.page.route("**/*", self.handle)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.page.evaluate(SEED, {
            "path": path,
            "features": DEFAULT_FEATURES if features is None else features,
            "branding": DEFAULT_BRANDING if branding is None else branding,
            "settings": {} if settings is None else settings,
            "settingsLoading": settings_loading,
            "settingsError": settings_error,
            "railCollapsed": rail_collapsed,
            "active": active,
            "conversations": [
                {"id": item["id"], "title": item["title"], "has_unread_assistant_response": item["unread"]}
                for item in self.conversations.values()
            ],
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

    def wait_for_js(self, script, message, arg=None, timeout=5.0):
        self.wait_for(lambda: self.page.evaluate(script, arg), message, timeout)

    def settle_count(self):
        """Wait until every count read that has started has landed."""
        self.wait_for_js(COUNT_SETTLED, "A notification count read did not land.")
        self.page.wait_for_timeout(100)
        self.wait_for_js(COUNT_SETTLED, "A notification count read did not land.")

    # Reading the page -------------------------------------------------------------------------

    def js(self, script, arg=None):
        return self.page.evaluate(script, arg)

    def count_fetches(self):
        return self.js("() => window.__fetchLog.filter((item) => item.path === '/api/notifications/count').length")

    def changes(self):
        return self.js("() => window.NotificationHarness.countChanges")

    def store(self):
        return self.js("""() => {
            const state = window.NotificationHarness.stores.notification.useNotificationStore.getState();
            return {count: state.count, halted: state.halted, items: state.items.map((item) => item.id)};
        }""")

    def active_conversation(self):
        return self.js("() => window.NotificationHarness.stores.chat.useChatStore.getState().activeConversationId")

    def conversation_unread(self, conversation_id):
        return self.js("""(id) => {
            const item = window.NotificationHarness.stores.chat.useChatStore.getState()
                .conversations.find((conversation) => conversation.id === id);
            return Boolean(item && item.has_unread_assistant_response);
        }""", conversation_id)

    def notifications(self):
        return self.js("""() => window.Notification.instances.map((item) => ({
            title: item.title, body: item.body, tag: item.tag, closed: item.closed,
        }))""")

    def permission_requests(self):
        return self.js("() => window.Notification.requests")

    def env(self):
        return self.js("() => ({...window.__harnessEnv})")

    def route_text(self):
        return self.page.locator("[data-current-route]").text_content()

    @property
    def bell(self):
        return self.page.locator("button[data-notification-bell]")

    @property
    def panel(self):
        return self.page.locator("[data-notification-panel]")

    @property
    def rows(self):
        return self.panel.locator("li[data-notification-id]")

    def row(self, notice_id):
        return self.panel.locator(f'li[data-notification-id="{notice_id}"]')

    def action(self, notice_id, name):
        return self.row(notice_id).locator(f'[data-notification-action="{name}"]')

    def row_ids(self):
        return self.rows.evaluate_all("(items) => items.map((item) => item.dataset.notificationId)")

    def toast(self, text):
        return self.page.get_by_role("alert").filter(has_text=text)

    # Acting -----------------------------------------------------------------------------------

    def open_panel(self):
        before = len(self.list_queries)
        self.bell.click()
        expect(self.panel).to_be_visible()
        self.wait_for(lambda: len(self.list_queries) > before, "Opening the panel did not read the list.")
        self.wait_for_js(LIST_SETTLED, "The notification list did not finish loading.")

    def hide(self):
        self.js("() => window.__harness.hide()")

    def show(self):
        self.js("() => window.__harness.show()")

    def blur(self):
        self.js("() => window.__harness.blur()")

    def navigate(self, path):
        self.js("(path) => window.NotificationHarness.appNavigation.getAppNavigator().navigate(path)", path)

    def announce(self, **reply):
        self.js("(reply) => window.NotificationHarness.replyEvents.announceCompletedReply(reply)", reply)

    def set_permission(self, permission, next_permission=None):
        self.js("""([permission, next]) => {
            window.Notification.permission = permission;
            if (next) window.Notification.nextPermission = next;
        }""", [permission, next_permission])

    def send(self, text="Draft the plan"):
        self.page.get_by_role("textbox", name="Message", exact=True).fill(text)
        self.page.get_by_role("button", name="Send message", exact=True).click()


@pytest.fixture(scope="module")
def harness_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: npm --prefix application/v2_ui run build"
    built = index.stat().st_mtime
    stale = [item for item in V2_SOURCE.rglob("*") if item.is_file() and item.stat().st_mtime > built]
    if stale:
        pytest.fail(
            f"The V2 bundle is stale ({stale[0].relative_to(ROOT)} changed after it was built). "
            "Run npm --prefix application/v2_ui run build",
        )
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


def centre_y(box):
    return box["y"] + box["height"] / 2


def unread_flags(harness):
    return harness.rows.evaluate_all("(items) => items.map((item) => item.dataset.unread)")


# Layout ---------------------------------------------------------------------------------------


def test_bell_sits_beside_the_brand_and_its_panel_lists_every_kind_of_notice(harness):
    harness.add(
        announcement_notice(read=True),
        share_notice(),
        document_notice(read=True),
        m365_approval_notice(),
        workflow_notice("n-workflow", XSS_MESSAGE),
        chat_notice("n-chat", "conv-b", "Budget review"),
    )
    harness.open("/chat")
    page = harness.page
    bell = harness.bell

    expect(bell).to_have_attribute("data-unread-count", "4")
    expect(bell).to_have_accessible_name("Notifications, 4 unread")
    expect(bell.locator("[data-notification-badge]")).to_have_text("4")
    expect(bell.locator("[data-notification-dot]")).to_have_count(0)
    expect(bell).to_have_attribute("aria-expanded", "false")
    assert bell.get_attribute("aria-controls") is None
    # V2 has no top bar: the bell shares the rail's header row with the brand.
    brand = page.get_by_role("link", name="Contoso Chat home")
    collapse = page.get_by_role("button", name="Collapse navigation")
    brand_box, bell_box, collapse_box = brand.bounding_box(), bell.bounding_box(), collapse.bounding_box()
    assert abs(centre_y(bell_box) - centre_y(brand_box)) < 4
    assert abs(centre_y(bell_box) - centre_y(collapse_box)) < 4
    assert brand_box["x"] + brand_box["width"] <= bell_box["x"] < collapse_box["x"]
    assert bell.evaluate("(button) => Boolean(button.closest('nav[aria-label=\"Primary\"]'))")

    harness.open_panel()
    panel = harness.panel
    expect(page.get_by_role("dialog", name="Notifications")).to_be_visible()
    expect(bell).to_have_attribute("aria-expanded", "true")
    assert bell.get_attribute("aria-controls") == panel.get_attribute("id")
    expect(panel).to_be_focused()
    expect(panel.locator("[data-notification-panel-count]")).to_have_text("4 unread")
    assert harness.list_queries[-1] == {
        "page": "1", "per_page": "20", "include_read": "true", "include_dismissed": "false",
    }
    assert harness.row_ids() == ["n-chat", "n-workflow", "n-m365", "n-doc", "n-share", "n-announce"]
    assert unread_flags(harness) == ["true", "true", "true", "false", "true", "false"]
    labels = {
        "n-chat": "AI responded",
        "n-workflow": "Workflow run failed",
        "n-m365": "Microsoft 365 approval",
        "n-doc": "Document processed",
        "n-share": "Share request",
        "n-announce": "Announcement",
    }
    for notice_id, label in labels.items():
        expect(harness.row(notice_id).locator("p").first).to_contain_text(label)
    expect(harness.action("n-share", "read")).to_have_accessible_name("Mark as read: Alex shared a document with you")
    expect(harness.action("n-doc", "read")).to_have_count(0)
    expect(harness.action("n-doc", "dismiss")).to_have_accessible_name("Dismiss: Document ready: Q3 forecast.pdf")
    expect(harness.action("n-chat", "open")).to_have_text("AI responded in Budget review")
    # A notice with nowhere to go is shown without a link, and without a complaint.
    expect(harness.action("n-announce", "open")).to_have_count(0)
    expect(harness.row("n-announce").locator("[data-notification-link-error]")).to_have_count(0)

    # Quoted mail or web text is shown as text, never as markup.
    workflow = harness.row("n-workflow")
    expect(workflow).to_contain_text(XSS_MESSAGE)
    assert workflow.locator("img, b, script").count() == 0
    assert harness.js("() => window.__xss") is None

    expect(panel.get_by_role("link", name="Open all in the classic interface")).to_have_attribute(
        "href", "/notifications",
    )
    page.keyboard.press("Escape")
    expect(panel).to_have_count(0)
    expect(bell).to_be_focused()
    expect(bell).to_have_attribute("aria-expanded", "false")


def test_collapsed_rail_shows_a_dot_and_the_panel_pages_through_the_list(harness):
    for number in range(25):
        harness.add(announcement_notice(f"n-{number:02d}", f"Notice {number:02d}", read=number >= 12))
    harness.open("/elsewhere", rail_collapsed=True)
    page = harness.page
    bell = harness.bell

    # The server stops counting at ten, so ten reads as "this many or more".
    expect(bell).to_have_attribute("data-unread-count", "10")
    expect(bell).to_have_accessible_name("Notifications, 9+ unread")
    expect(bell.locator("[data-notification-dot]")).to_have_count(1)
    expect(bell.locator("[data-notification-badge]")).to_have_count(0)
    brand_box = page.get_by_role("link", name="Contoso Chat home").bounding_box()
    expand_box = page.get_by_role("button", name="Expand navigation").bounding_box()
    bell_box = bell.bounding_box()
    assert brand_box["y"] + brand_box["height"] <= bell_box["y"]
    assert bell_box["y"] + bell_box["height"] <= expand_box["y"]
    assert abs((bell_box["x"] + bell_box["width"] / 2) - (expand_box["x"] + expand_box["width"] / 2)) < 2

    harness.open_panel()
    panel = harness.panel
    expect(panel.locator("[data-notification-panel-count]")).to_have_text("9+ unread")
    expect(harness.rows).to_have_count(20)
    assert harness.row_ids()[0] == "n-24"
    load_more = panel.locator('[data-notification-action="load-more"]')
    load_more.click()
    expect(harness.rows).to_have_count(25)
    expect(load_more).to_have_count(0)
    assert harness.list_queries[-1]["page"] == "2"
    assert harness.row_ids()[-1] == "n-00"

    panel_box = panel.bounding_box()
    assert panel_box["width"] == 384
    assert abs(panel_box["x"] - bell_box["x"]) < 1
    assert abs(panel_box["y"] - (bell_box["y"] + bell_box["height"] + 8)) < 1

    # A click elsewhere closes the panel and leaves focus where the reader put it.
    page.get_by_text("Another page").click()
    expect(panel).to_have_count(0)
    expect(bell).not_to_be_focused()


def test_mobile_bell_works_from_the_strip_and_from_the_open_navigation(harness):
    harness.page.set_viewport_size({"width": 390, "height": 844})
    harness.add(chat_notice("n-chat", "conv-b", "Budget review", read=True), document_notice())
    harness.open("/elsewhere")
    page = harness.page
    bell = harness.bell
    expand = page.get_by_role("button", name="Expand navigation")
    collapse = page.get_by_role("button", name="Collapse navigation")

    expect(bell).to_have_count(1)
    expect(bell.locator("[data-notification-dot]")).to_have_count(1)
    harness.open_panel()
    panel_box = harness.panel.bounding_box()
    assert panel_box["width"] == 374
    assert panel_box["x"] == 8
    page.keyboard.press("Escape")
    expect(harness.panel).to_have_count(0)
    expect(bell).to_be_focused()

    expand.click()
    expect(collapse).to_be_focused()
    expect(bell.locator("[data-notification-badge]")).to_have_text("1")
    harness.open_panel()
    panel_box = harness.panel.bounding_box()
    assert harness.js(
        "([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest('[data-notification-panel]'))",
        [panel_box["x"] + panel_box["width"] / 2, panel_box["y"] + 24],
    ), "The panel should sit above the open navigation and its backdrop."
    # Escape closes the panel first; the navigation stays open for a second Escape.
    page.keyboard.press("Escape")
    expect(harness.panel).to_have_count(0)
    expect(bell).to_be_focused()
    expect(collapse).to_be_visible()
    page.keyboard.press("Escape")
    expect(expand).to_be_focused()

    # A notice opened from the open navigation takes the reader there and closes it.
    expand.click()
    harness.open_panel()
    harness.action("n-doc", "open").click()
    expect(page.locator("[data-current-route]")).to_have_text("/workspace/documents")
    expect(harness.panel).to_have_count(0)
    expect(collapse).to_have_count(0)
    expect(expand).to_be_visible()
    harness.wait_for(lambda: harness.read_calls == ["n-doc"], "Opening an unread notice should mark it read.")


# Read, dismiss and mark all read ------------------------------------------------------------


def test_read_dismiss_and_mark_all_read_change_the_server_and_the_count(harness):
    harness.add(
        announcement_notice("n-old", "Old notice", read=True),
        share_notice(),
        document_notice(),
        workflow_notice("n-workflow", "The digest step timed out."),
    )
    harness.open("/elsewhere")
    bell = harness.bell
    expect(bell).to_have_attribute("data-unread-count", "3")
    harness.open_panel()
    assert harness.row_ids() == ["n-workflow", "n-doc", "n-share", "n-old"]

    harness.action("n-doc", "read").click()
    expect(harness.row("n-doc")).to_have_attribute("data-unread", "false")
    expect(harness.action("n-doc", "read")).to_have_count(0)
    harness.wait_for(lambda: harness.find("n-doc")["is_read"], "The notice was not marked read on the server.")
    harness.settle_count()
    expect(bell).to_have_attribute("data-unread-count", "2")

    harness.action("n-workflow", "dismiss").click()
    expect(harness.row("n-workflow")).to_have_count(0)
    expect(harness.panel).to_be_focused()
    harness.wait_for(lambda: harness.find("n-workflow")["is_dismissed"], "The notice was not dismissed on the server.")
    harness.settle_count()
    expect(bell).to_have_attribute("data-unread-count", "1")

    # A read notice leaves the count alone when it goes.
    harness.action("n-old", "dismiss").click()
    expect(harness.row("n-old")).to_have_count(0)
    harness.wait_for(lambda: harness.find("n-old")["is_dismissed"], "The read notice was not dismissed.")
    harness.settle_count()
    expect(bell).to_have_attribute("data-unread-count", "1")

    mark_all = harness.panel.locator('[data-notification-action="mark-all-read"]')
    mark_all.click()
    harness.wait_for(lambda: not harness.unread(), "Mark all read did not reach the server.")
    harness.settle_count()
    expect(bell).to_have_attribute("data-unread-count", "0")
    expect(bell).to_have_accessible_name("Notifications")
    expect(bell.locator("[data-notification-badge]")).to_have_count(0)
    expect(harness.panel.locator("[data-notification-panel-count]")).to_have_count(0)
    expect(mark_all).to_be_disabled()
    assert unread_flags(harness) == ["false", "false"]
    assert harness.read_calls == ["n-doc"]
    assert harness.dismiss_calls == ["n-workflow", "n-old"]
    assert harness.mark_all_calls == 1

    # The server's list, read again, agrees.
    harness.page.keyboard.press("Escape")
    harness.open_panel()
    assert harness.row_ids() == ["n-doc", "n-share"]


def test_failed_changes_are_put_back_and_explained(harness):
    harness.add(share_notice(), document_notice(), workflow_notice("n-workflow", "The digest step timed out."))
    harness.open("/elsewhere")
    bell = harness.bell
    harness.open_panel()
    expect(bell).to_have_attribute("data-unread-count", "3")

    harness.fail_next.add("read")
    harness.action("n-doc", "read").click()
    expect(harness.toast("Failed to mark notification as read")).to_be_visible()
    expect(harness.row("n-doc")).to_have_attribute("data-unread", "true")
    expect(harness.action("n-doc", "read")).to_be_enabled()
    expect(bell).to_have_attribute("data-unread-count", "3")

    harness.fail_next.add("dismiss")
    harness.action("n-doc", "dismiss").click()
    expect(harness.toast("Failed to dismiss notification")).to_be_visible()
    expect(harness.rows.nth(1)).to_have_attribute("data-notification-id", "n-doc")
    expect(harness.rows).to_have_count(3)
    expect(bell).to_have_attribute("data-unread-count", "3")

    harness.fail_next.add("mark_all")
    harness.panel.locator('[data-notification-action="mark-all-read"]').click()
    expect(harness.toast("Internal server error")).to_be_visible()
    expect(harness.rows.and_(harness.page.locator('[data-unread="true"]'))).to_have_count(3)
    expect(bell).to_have_attribute("data-unread-count", "3")

    assert len(harness.unread()) == 3
    assert not any(record["is_dismissed"] for record in harness.notices)
    assert harness.read_calls == ["n-doc"]
    assert harness.dismiss_calls == ["n-doc"]
    assert harness.mark_all_calls == 1


# Deep links -----------------------------------------------------------------------------------


def current_route(harness):
    return harness.page.locator("[data-current-route]")


def test_reply_notice_opens_its_conversation_from_another_page(harness):
    harness.conversations["conv-b"]["unread"] = True
    harness.add(document_notice(read=True), chat_notice("n-chat", "conv-b", "Budget review"))
    harness.open("/settings")
    bell = harness.bell
    expect(bell).to_have_attribute("data-unread-count", "1")

    harness.open_panel()
    harness.action("n-chat", "open").click()
    expect(current_route(harness)).to_have_text("/chat?conversationId=conv-b")
    expect(harness.panel).to_have_count(0)
    harness.wait_for(lambda: harness.active_conversation() == "conv-b", "The notice did not open its conversation.")
    harness.wait_for(
        lambda: harness.conversation_reads == ["conv-b"],
        "Opening the conversation should clear its unread reply.",
    )
    harness.wait_for(lambda: not harness.conversation_unread("conv-b"), "The rail still shows the reply as unread.")
    assert harness.read_calls == ["n-chat"]
    assert harness.count_requests("GET", "/api/conversations/conv-b/kind") == 1
    assert harness.saw("GET", "/api/get_messages?conversation_id=conv-b")
    harness.settle_count()
    expect(bell).to_have_attribute("data-unread-count", "0")


def test_reply_notices_open_in_place_on_the_chat_page(harness):
    harness.add(
        chat_notice("n-open", "conv-a", "Quarterly plan"),
        chat_notice("n-legacy", "conv-b", "Budget review", param="conversation_id"),
    )
    harness.open("/chat")
    route = current_route(harness)
    expect(route).to_have_text("/chat?conversationId=conv-a")

    # The conversation already on screen is left alone: no reload, and no lost stream.
    harness.open_panel()
    harness.action("n-open", "open").click()
    expect(harness.panel).to_have_count(0)
    harness.wait_for(lambda: harness.read_calls == ["n-open"], "Opening the notice should mark it read.")
    harness.page.wait_for_timeout(200)
    assert harness.active_conversation() == "conv-a"
    assert harness.count_requests("GET", "/api/conversations/conv-a/kind") == 0
    assert harness.count_requests("GET", "/api/get_messages") == 0
    expect(route).to_have_text("/chat?conversationId=conv-a")

    # The chat page reads its address once, so another conversation is opened directly.
    # The older conversation_id spelling, still written by the server, works as well.
    harness.open_panel()
    harness.action("n-legacy", "open").click()
    harness.wait_for(lambda: harness.active_conversation() == "conv-b", "The notice did not open its conversation.")
    expect(route).to_have_text("/chat?conversationId=conv-b")
    assert harness.read_calls == ["n-open", "n-legacy"]
    assert harness.count_requests("GET", "/api/conversations/conv-b/kind") == 1
    assert harness.saw("GET", "/api/get_messages?conversation_id=conv-b")
    harness.settle_count()
    expect(harness.bell).to_have_attribute("data-unread-count", "0")


# (notice id, link written for the classic interface, link context, V2 route it opens)
ROUTE_LINKS = [
    ("n-group-documents", "/group_workspaces", {"group_id": "grp-1"}, "/groups/grp-1/documents"),
    ("n-groups", "/group_workspaces", {}, "/groups"),
    ("n-group", "/groups/grp-2", {}, "/groups/grp-2"),
    ("n-directory", "/public_directory", {}, "/public/directory"),
    ("n-public", "/public_workspaces", {"public_workspace_id": "pub-1"}, "/public/pub-1"),
    ("n-public-page", "/public_workspaces/pub-2", {}, "/public/pub-2"),
    ("n-violations", "/profile?tab=violations", {}, "/settings?tab=violations"),
    ("n-profile", "/profile", {}, "/settings"),
    (
        "n-group-document", "/v2/groups/grp-3/documents?document_id=doc-3",
        {"workspace_type": "group", "group_id": "grp-3", "document_id": "doc-3"},
        "/groups/grp-3/documents?document_id=doc-3",
    ),
    ("n-v2", "/v2/workspace/prompts?tab=mine", {}, "/workspace/prompts?tab=mine"),
    # A chat link naming no conversation opens the chat page, which names the one it shows.
    ("n-chat-page", "/chats", {}, "/chat?conversationId=conv-a"),
]


def test_classic_links_open_the_matching_v2_page(harness):
    for notice_id, link_url, link_context, _ in ROUTE_LINKS:
        harness.add(notice(
            notice_id, "system_announcement", f"Open {notice_id}", link_url=link_url, link_context=link_context,
        ))
    harness.open("/elsewhere")
    route = current_route(harness)

    for notice_id, link_url, _, destination in ROUTE_LINKS:
        harness.open_panel()
        harness.action(notice_id, "open").click()
        expect(route, f"{link_url} should open {destination}").to_have_text(destination)
        expect(harness.panel).to_have_count(0)

    harness.wait_for(lambda: len(harness.read_calls) == len(ROUTE_LINKS), "Every opened notice should be read.")
    assert harness.read_calls == [item[0] for item in ROUTE_LINKS]
    # V2 routes name their workspace, so no active group is set on the way.
    assert harness.set_active_calls == []


# (notice, page it is opened from, classic page, groups made active on the way, setActive status)
CLASSIC_LINKS = {
    "workflow-alert": (
        lambda: workflow_notice("n-classic", "The digest step timed out.", group_id="grp-9"),
        "/elsewhere", "/workflow-activity?workflowId=wf-1&runId=run-1", [{"groupId": "grp-9"}], 200,
    ),
    # The server names the approver as the approval's group, which is not a group at all. Classic
    # asks for it anyway and ignores the refusal; so does V2, and the page still opens.
    "m365-approval": (
        lambda: m365_approval_notice("n-classic"),
        "/elsewhere", "/approvals?m365_approval=appr-1", [{"groupId": "user-1"}], 404,
    ),
    # Only the classic chat page draws the pending-action card, so it is not opened in V2.
    "m365-pending-action": (
        lambda: m365_pending_action_notice("n-classic"),
        "/chat", "/chats?conversationId=conv-b&m365_pending_action=act-1", [], 200,
    ),
}


@pytest.mark.parametrize("case", list(CLASSIC_LINKS))
def test_notices_for_pages_v2_has_not_rebuilt_open_the_classic_page(harness, case):
    build, start, destination, set_active, status = CLASSIC_LINKS[case]
    harness.set_active_status = status
    harness.add(build())
    harness.open(start)
    harness.open_panel()
    harness.action("n-classic", "open").click()

    harness.page.wait_for_url(f"{ORIGIN}{destination}")
    expect(harness.page.get_by_role("heading", name="Classic interface")).to_be_visible()
    assert harness.read_calls == ["n-classic"]
    assert harness.set_active_calls == set_active
    # A full page load cancels whatever is still on its way, so the read goes first.
    order = [(method, target) for method, target, _ in harness.requests]
    read_at = order.index(("POST", "/api/notifications/n-classic/read"))
    page_at = order.index(("GET", destination))
    assert read_at < page_at
    if set_active:
        assert read_at < order.index(("PATCH", "/api/groups/setActive")) < page_at
    assert harness.count_requests("GET", "/api/conversations/conv-b/kind") == 0


# (notice id, link, link context, what the panel says instead of opening it)
UNSAFE_LINKS = [
    ("n-off-site", "https://evil.example/phish", {}, OFF_SITE),
    ("n-scheme-relative", "//evil.example/phish", {}, OFF_SITE),
    ("n-backslash", "/\\evil.example/phish", {}, OFF_SITE),
    ("n-plain-http", "http://simplechat.test/chats", {}, OFF_SITE),
    ("n-script", "javascript:window.__xss=3", {}, UNSUPPORTED),
    ("n-data", "data:text/html,<script>window.__xss=4</script>", {}, UNSUPPORTED),
    ("n-credentials", "https://user:secret@simplechat.test/chats", {}, UNSUPPORTED),
    ("n-api", "/api/notifications/mark-all-read", {}, UNSUPPORTED),
    ("n-blank", "   ", {}, INVALID),
    ("n-traversal", "/chats?conversationId=../conv-a", {}, INVALID),
    ("n-bad-group", "/groups/a%2Fb", {}, INVALID),
    (
        "n-mismatch", "/v2/groups/grp-1/documents?document_id=doc-1",
        {"workspace_type": "group", "group_id": "grp-2", "document_id": "doc-1"}, MISMATCH,
    ),
]


def test_links_that_leave_the_site_or_cannot_be_trusted_are_explained_not_followed(harness):
    for notice_id, link_url, link_context, _ in UNSAFE_LINKS:
        harness.add(notice(
            notice_id, "system_announcement", f"Check {notice_id}", link_url=link_url, link_context=link_context,
        ))
    harness.open("/elsewhere")
    harness.open_panel()

    for notice_id, link_url, _, error in UNSAFE_LINKS:
        row = harness.row(notice_id)
        expect(row.locator("[data-notification-link-error]"), repr(link_url)).to_have_text(error)
        expect(harness.action(notice_id, "open")).to_have_count(0)
        expect(row.locator("a")).to_have_count(0)
        expect(row).to_contain_text(f"Check {notice_id}")

    # Nothing was followed, nothing ran, and each notice can still be dealt with.
    expect(current_route(harness)).to_have_text("/elsewhere")
    assert harness.js("() => window.__xss") is None
    assert harness.read_calls == []
    harness.action("n-script", "dismiss").click()
    expect(harness.row("n-script")).to_have_count(0)
    harness.wait_for(lambda: harness.dismiss_calls == ["n-script"], "The notice was not dismissed.")


def test_a_notice_for_a_conversation_that_is_gone_says_so_and_leaves_the_chat_alone(harness):
    harness.add(chat_notice("n-gone", "conv-gone", "Retired thread"))
    harness.open("/chat")
    route = current_route(harness)
    expect(route).to_have_text("/chat?conversationId=conv-a")

    harness.open_panel()
    harness.action("n-gone", "open").click()
    expect(harness.toast(DELETED)).to_be_visible()
    harness.wait_for(lambda: harness.read_calls == ["n-gone"], "Opening the notice should mark it read.")
    assert harness.active_conversation() == "conv-a"
    expect(route).to_have_text("/chat?conversationId=conv-a")
    assert harness.saw("GET", "/api/conversations/conv-gone/kind")
    assert not harness.saw("GET", "/api/get_messages?conversation_id=conv-gone")

    # From another page the link is followed, fails the same way, and the address bar goes
    # back to naming the conversation that is actually open.
    harness.add(chat_notice("n-gone-too", "conv-gone-too", "Archived thread"))
    harness.navigate("/elsewhere")
    expect(route).to_have_text("/elsewhere")
    harness.open_panel()
    harness.action("n-gone-too", "open").click()
    harness.wait_for(
        lambda: harness.saw("GET", "/api/conversations/conv-gone-too/kind"),
        "The link was not followed to the chat page.",
    )
    expect(route).to_have_text("/chat?conversationId=conv-a")
    expect(harness.toast(DELETED).last).to_be_visible()
    assert harness.active_conversation() == "conv-a"
    assert not harness.saw("GET", "/api/get_messages?conversation_id=conv-gone-too")


# The unread count -----------------------------------------------------------------------------


def poll_now(harness):
    """Read the count the way the poller's timer does."""
    harness.js("() => window.NotificationHarness.stores.notification.refreshNotificationCount('poll')")


def test_a_notice_that_arrives_while_the_panel_is_open_is_listed(harness):
    harness.add(share_notice())
    harness.open("/elsewhere")
    bell = harness.bell
    harness.open_panel()
    harness.settle_count()
    assert harness.row_ids() == ["n-share"]
    queries = len(harness.list_queries)

    harness.add(workflow_notice("n-workflow", "The digest step timed out."))
    poll_now(harness)
    expect(harness.rows).to_have_count(2)
    assert harness.row_ids() == ["n-workflow", "n-share"]
    expect(bell).to_have_attribute("data-unread-count", "2")
    expect(harness.panel.locator("[data-notification-panel-count]")).to_have_text("2 unread")
    assert len(harness.list_queries) == queries + 1
    # What Track N2's pop-ups will hear.
    assert harness.changes()[-1] == {"count": 2, "previousCount": 1, "changed": True, "rose": True, "reason": "poll"}

    # A count that falls -- the notice was read in another tab -- is shown, and the list is
    # left as it is rather than reloaded under the reader.
    harness.find("n-share")["is_read"] = True
    poll_now(harness)
    expect(bell).to_have_attribute("data-unread-count", "1")
    harness.settle_count()
    assert harness.changes()[-1] == {"count": 1, "previousCount": 2, "changed": True, "rose": False, "reason": "poll"}
    harness.page.wait_for_timeout(200)
    assert len(harness.list_queries) == queries + 1


CLOCK_STEP = 5


def count_read_times(harness):
    """When each count read started, in seconds on the page's clock."""
    return harness.js("""() => window.__fetchLog
        .filter((item) => item.path === '/api/notifications/count')
        .map((item) => item.at / 1000)""")


def gaps(times):
    return [round(later - earlier, 3) for earlier, later in zip(times, times[1:])]


def settle_answered(harness):
    """Wait for every count read to be answered and handled, whether it succeeded or not."""
    harness.wait_for(
        lambda: harness.count_requests("GET", "/api/notifications/count") >= harness.count_fetches(),
        "A notification count read was not answered.",
    )
    harness.page.wait_for_timeout(150)


def advance_until_reads(harness, total, limit, settle=None):
    """
    Run the page's clock on a step at a time until `total` count reads have started.

    Each read is let land before the clock moves again, so the poller schedules its next read
    within one step of starting the last: a wait of W seconds shows as a gap between W and
    W plus one step.
    """
    settle = settle or harness.settle_count
    clock = harness.page.clock
    elapsed = 0
    while harness.count_fetches() < total:
        if elapsed >= limit:
            raise AssertionError(f"{harness.count_fetches()} count reads after {elapsed} s, not {total}.")
        before = harness.count_fetches()
        clock.run_for(CLOCK_STEP * 1000)
        elapsed += CLOCK_STEP
        if harness.count_fetches() != before:
            settle()
    return count_read_times(harness)


def assert_waits(observed, expected):
    """Each wait is the poller's interval, give or take a tenth, plus the clock's step."""
    assert len(observed) == len(expected), (observed, expected)
    for gap, interval in zip(observed, expected):
        assert interval * 0.9 <= gap <= interval * 1.1 + CLOCK_STEP, (observed, expected)


def test_the_count_backs_off_while_nothing_changes_and_rests_while_hidden(harness):
    harness.add(share_notice())
    harness.open("/elsewhere", clock=True)
    # React's development double start makes one read, not two.
    assert harness.count_fetches() == 1
    assert harness.changes() == [
        {"count": 1, "previousCount": None, "changed": True, "rose": False, "reason": "initial"},
    ]

    # Thirty seconds, doubling each time nothing changed, up to five minutes.
    times = advance_until_reads(harness, 7, 1400)
    assert_waits(gaps(times), [30, 60, 120, 240, 300, 300])
    assert all(change == {"count": 1, "previousCount": 1, "changed": False, "rose": False, "reason": "poll"}
               for change in harness.changes()[1:])

    # A change brings it straight back to thirty seconds.
    harness.add(document_notice())
    advance_until_reads(harness, 8, 340)
    assert harness.changes()[-1] == {"count": 2, "previousCount": 1, "changed": True, "rose": True, "reason": "poll"}
    expect(harness.bell).to_have_attribute("data-unread-count", "2")
    times = advance_until_reads(harness, 9, 40)
    assert_waits(gaps(times)[-1:], [30])

    # A hidden tab is not polled at all, however long it stays hidden.
    harness.hide()
    reads = harness.count_fetches()
    harness.page.clock.run_for(15 * 60 * 1000)
    harness.page.wait_for_timeout(100)
    assert harness.count_fetches() == reads

    # Coming back arrives as a visibility change and a focus event; one read answers both.
    harness.add(share_notice("n-share-2"))
    harness.show()
    harness.settle_count()
    assert harness.count_fetches() == reads + 1
    assert harness.changes()[-1]["reason"] == "visibility"
    expect(harness.bell).to_have_attribute("data-unread-count", "3")

    # Straight back out and in again: the read just made answers for it, and the timer the
    # hidden tab cleared is set again rather than lost.
    harness.hide()
    harness.show()
    harness.page.wait_for_timeout(100)
    assert harness.count_fetches() == reads + 1
    times = advance_until_reads(harness, reads + 2, 40)
    assert_waits(gaps(times)[-1:], [30])

    # Focus alone, after the window was left for another one, is a reason to look too.
    harness.blur()
    harness.page.clock.run_for(5_000)
    harness.show()
    harness.settle_count()
    assert harness.count_fetches() == reads + 3
    assert harness.changes()[-1]["reason"] == "focus"


@pytest.mark.parametrize("failure", [401, 403, "html"], ids=["401", "403", "sign-in-page"])
def test_polling_stops_for_good_once_the_session_has_lapsed(harness, failure):
    harness.add(share_notice())
    harness.open("/elsewhere", clock=True)
    expect(harness.bell).to_have_attribute("data-unread-count", "1")

    harness.count_failure = failure
    advance_until_reads(harness, 2, 40)
    assert harness.store()["halted"] is True
    reads = harness.count_fetches()

    # Nothing asks again: not the timer, not coming back to the tab, not an action.
    harness.page.clock.run_for(10 * 60 * 1000)
    harness.hide()
    harness.page.clock.run_for(5_000)
    harness.show()
    harness.blur()
    harness.page.clock.run_for(5_000)
    harness.show()
    harness.js("() => window.NotificationHarness.stores.notification.refreshNotificationCount('action')")
    harness.page.wait_for_timeout(200)
    assert harness.count_fetches() == reads
    # The last count read stays on the bell rather than a guess.
    expect(harness.bell).to_have_attribute("data-unread-count", "1")


def test_a_failed_count_read_is_tried_again_later_rather_than_given_up(harness):
    harness.add(share_notice())
    harness.open("/elsewhere", clock=True)

    harness.count_failure = 500
    times = advance_until_reads(harness, 3, 120, settle=lambda: settle_answered(harness))
    # Each failure doubles the wait, as an unchanged count does.
    assert_waits(gaps(times), [30, 60])
    assert harness.store()["halted"] is False
    expect(harness.bell).to_have_attribute("data-unread-count", "1")

    harness.count_failure = None
    harness.add(document_notice())
    times = advance_until_reads(harness, 4, 160, settle=lambda: settle_answered(harness))
    assert_waits(gaps(times)[-1:], [120])
    expect(harness.bell).to_have_attribute("data-unread-count", "2")


# Replies and desktop notifications ------------------------------------------------------------


def system_notice(conversation_id, title="Quarterly plan", *, app="Contoso Chat", closed=False):
    """A system notification as the notifier raises one: the app and the conversation, no reply."""
    return {"title": app, "body": title, "tag": f"simplechat-conversation-{conversation_id}", "closed": closed}


def click_notice(harness, index=-1):
    """Click a system notification, as the reader does from the operating system."""
    harness.js("(index) => window.Notification.instances.at(index).click()", index)


def run_reply(conversation_id, title, run_id="run-7"):
    """A finished orchestration run, announced the way orchestrationController announces one."""
    return {
        "conversationId": conversation_id, "messageId": None, "runId": run_id,
        "conversationTitle": title, "blocked": False, "source": "orchestration",
    }


def send_and_hold(harness, text="Draft the plan"):
    """Send a message from the composer and keep its reply back until the test lets it land."""
    harness.hold_streams = True
    harness.send(text)
    harness.wait_for(lambda: harness.held_streams, "The message was not sent.")


def wait_for_count(harness, count):
    harness.wait_for(lambda: harness.store()["count"] == count, f"The bell's count did not become {count}.")
    expect(harness.bell).to_have_attribute("data-unread-count", str(count))


def test_a_reply_that_lands_in_a_hidden_tab_raises_one_notice_and_waits_to_be_seen(harness):
    harness.open("/chat")
    send_and_hold(harness)
    # Permission was granted long ago, so sending asks for nothing.
    assert harness.permission_requests() == []

    harness.hide()
    harness.release_stream()
    harness.wait_for(lambda: harness.notifications(), "No desktop notification was raised.")
    wait_for_count(harness, 1)
    assert harness.notifications() == [system_notice("conv-a")]
    # Nobody saw it arrive, so it stays unread -- in the rail and in the bell -- until somebody does.
    harness.page.wait_for_timeout(200)
    assert harness.conversation_reads == []
    assert harness.conversation_unread("conv-a") is True

    # Heard of twice, a reply is still one notice.
    harness.announce(
        conversationId="conv-a", messageId="reply-1", conversationTitle="Quarterly plan",
        blocked=False, source="chat",
    )
    assert len(harness.notifications()) == 1

    # Coming back to the tab is seeing it.
    harness.show()
    harness.wait_for(lambda: harness.conversation_reads == ["conv-a"], "Coming back did not read the reply.")
    harness.wait_for(lambda: not harness.conversation_unread("conv-a"), "The rail still shows the reply as unread.")
    wait_for_count(harness, 0)
    assert harness.find("n-reply-1")["is_read"] is True
    harness.page.wait_for_timeout(200)
    assert harness.conversation_reads == ["conv-a"]


def test_a_reply_watched_as_it_lands_is_read_at_once_and_noticed_only_from_another_window(harness):
    harness.open("/chat")
    harness.send()
    harness.wait_for(lambda: harness.conversation_reads == ["conv-a"], "The watched reply was not read.")
    harness.settle_count()
    wait_for_count(harness, 0)
    assert harness.notifications() == []
    assert harness.conversation_unread("conv-a") is False

    # Another window in front of this one, which is still showing: the reply is on screen, so it
    # is read at once, but only a notice would tell the reader it has arrived.
    harness.blur()
    harness.send("And the budget")
    harness.wait_for(
        lambda: harness.conversation_reads == ["conv-a", "conv-a"], "The second watched reply was not read.",
    )
    harness.wait_for(lambda: harness.notifications(), "No desktop notification was raised.")
    assert harness.notifications() == [system_notice("conv-a")]
    harness.settle_count()
    wait_for_count(harness, 0)


def test_clicking_a_notice_opens_its_conversation_and_reads_the_reply(harness):
    harness.open("/chat")
    route = current_route(harness)
    send_and_hold(harness)
    harness.navigate("/settings")
    expect(route).to_have_text("/settings")
    harness.hide()
    harness.release_stream()
    harness.wait_for(lambda: harness.notifications(), "No desktop notification was raised.")
    wait_for_count(harness, 1)
    assert harness.conversation_reads == []

    click_notice(harness)
    expect(route).to_have_text("/chat?conversationId=conv-a")
    harness.wait_for(lambda: harness.conversation_reads == ["conv-a"], "Opening the reply did not read it.")
    wait_for_count(harness, 0)
    env = harness.env()
    assert env["focusCalls"] == 1
    assert env["visible"] is True
    assert harness.notifications() == [system_notice("conv-a", closed=True)]
    # It was the open conversation already, so it is shown as it is rather than loaded again.
    assert harness.count_requests("GET", "/api/conversations/conv-a/kind") == 0
    harness.page.wait_for_timeout(200)
    assert harness.conversation_reads == ["conv-a"]

    # A notice for another conversation -- here an orchestration run's -- opens that one.
    harness.navigate("/settings")
    expect(route).to_have_text("/settings")
    harness.hide()
    harness.announce(**run_reply("conv-b", "Budget review"))
    assert harness.notifications()[-1] == system_notice("conv-b", "Budget review")
    click_notice(harness)
    harness.wait_for(lambda: harness.active_conversation() == "conv-b", "The notice did not open its conversation.")
    expect(route).to_have_text("/chat?conversationId=conv-b")
    assert harness.count_requests("GET", "/api/conversations/conv-b/kind") == 1
    assert harness.saw("GET", "/api/get_messages?conversation_id=conv-b")
    assert harness.env()["focusCalls"] == 2


def test_a_reply_that_lands_while_the_reader_is_on_another_page_is_read_when_they_return(harness):
    harness.open("/chat")
    send_and_hold(harness)
    harness.navigate("/settings")
    harness.release_stream()
    wait_for_count(harness, 1)
    # The tab is in front, so the bell is notice enough.
    assert harness.notifications() == []
    assert harness.conversation_unread("conv-a") is True

    # Leaving the tab and coming back to the same page does not show the reply.
    harness.hide()
    harness.show()
    harness.settle_count()
    harness.page.wait_for_timeout(200)
    assert harness.conversation_reads == []

    # Going back to the chat page does.
    harness.navigate("/chat")
    harness.wait_for(lambda: harness.conversation_reads == ["conv-a"], "Returning to the chat did not read the reply.")
    harness.wait_for(lambda: not harness.conversation_unread("conv-a"), "The rail still shows the reply as unread.")
    wait_for_count(harness, 0)


def test_a_reply_left_behind_for_another_conversation_stays_unread(harness):
    harness.conversations["conv-b"]["unread"] = True
    harness.add(chat_notice("n-b", "conv-b", "Budget review"))
    harness.open("/chat")
    send_and_hold(harness)
    harness.navigate("/settings")
    harness.release_stream()
    wait_for_count(harness, 2)

    # The bell's link names conv-b, so conv-b is what the reader comes back to, not the
    # conversation that was open when they left.
    harness.open_panel()
    harness.action("n-b", "open").click()
    harness.wait_for(lambda: harness.active_conversation() == "conv-b", "The notice did not open its conversation.")
    harness.wait_for(lambda: harness.conversation_reads == ["conv-b"], "Opening conv-b did not read it.")
    harness.page.wait_for_timeout(200)
    assert harness.conversation_reads == ["conv-b"]
    assert harness.conversation_unread("conv-a") is True
    assert harness.find("n-reply-1")["is_read"] is False
    wait_for_count(harness, 1)


def test_a_notice_for_another_conversation_leaves_the_open_ones_reply_unread(harness):
    harness.open("/chat")
    send_and_hold(harness)
    harness.hide()
    harness.release_stream()
    harness.wait_for(lambda: harness.notifications(), "No desktop notification was raised.")
    harness.announce(**run_reply("conv-b", "Budget review"))
    assert len(harness.notifications()) == 2

    # conv-b is slow to open, and the tab is showing again before it has: the chat page is in
    # front with conv-a still on it, but the reader is on the way to conv-b.
    harness.hold_kinds.add("conv-b")
    click_notice(harness)
    harness.wait_for(lambda: "conv-b" in harness.held_kinds, "The notice did not start opening its conversation.")
    harness.wait_for(lambda: harness.env()["visible"], "The notice did not bring the window forward.")
    harness.page.wait_for_timeout(200)
    assert harness.active_conversation() == "conv-a"
    assert harness.conversation_reads == []

    harness.release_kind("conv-b")
    harness.wait_for(lambda: harness.active_conversation() == "conv-b", "The notice did not open its conversation.")
    expect(current_route(harness)).to_have_text("/chat?conversationId=conv-b")
    harness.page.wait_for_timeout(200)
    assert harness.conversation_reads == []
    assert harness.conversation_unread("conv-a") is True
    wait_for_count(harness, 1)


# The rules a desktop notification obeys, one scenario at a time.

# Nobody is looking, both switches are on and the browser has said yes.
ANNOUNCE_BASE = {
    "visible": False, "focused": False,
    "features": DEFAULT_FEATURES, "branding": DEFAULT_BRANDING,
    "settings": {}, "loading": False, "error": None, "permission": "granted",
}


def chat_reply(conversation_id, message_id, title="Quarterly plan"):
    return {
        "conversationId": conversation_id, "messageId": message_id, "runId": None,
        "conversationTitle": title, "blocked": False, "source": "chat",
    }


def announce_in(harness, reply, **scenario):
    """Announce one finished reply in the given scenario; return the notifications it raised."""
    return harness.js(ANNOUNCE_AND_COLLECT, {**ANNOUNCE_BASE, **scenario, "reply": reply})


def raised(conversation_id, title="Quarterly plan", *, app="Contoso Chat"):
    """A system notification as the scenario script reports it."""
    return {"title": app, "body": title, "tag": f"simplechat-conversation-{conversation_id}"}


NOTICE_RULES = [
    # (scenario, what differs from ANNOUNCE_BASE, what differs in the reply, raises a notice)
    ("the tab is hidden and the reader never chose", {}, {}, True),
    ("the tab shows but another window is in front", {"visible": True}, {}, True),
    ("the reader turned it on", {"settings": {"desktopNotificationsEnabled": True}}, {}, True),
    ("the reader is watching", {"visible": True, "focused": True}, {}, False),
    ("the administrator turned it off", {"features": {"enable_desktop_notifications": False}}, {}, False),
    ("the administrator never turned it on", {"features": {}}, {}, False),
    ("the reader turned it off", {"settings": {"desktopNotificationsEnabled": False}}, {}, False),
    ("preferences are still loading", {"loading": True}, {}, False),
    ("preferences failed to load", {"error": "Could not load your preferences."}, {}, False),
    ("the browser has not been asked", {"permission": "default"}, {}, False),
    ("the browser refused", {"permission": "denied"}, {}, False),
    ("the safety filter replaced the reply", {}, {"blocked": True}, False),
]


def test_a_desktop_notice_is_raised_only_when_every_rule_allows_it(harness):
    harness.open("/elsewhere")
    outcomes = {}
    for number, (scenario, changes, reply_changes, _) in enumerate(NOTICE_RULES):
        # A new reply each time, so no scenario is decided by an earlier one's notice.
        reply = {**chat_reply("conv-a", f"m-rule-{number}"), **reply_changes}
        outcomes[scenario] = announce_in(harness, reply, **changes)
    assert outcomes == {
        scenario: [raised("conv-a")] if raises else [] for scenario, _, _, raises in NOTICE_RULES
    }


def test_each_reply_is_noticed_once_and_named_only_by_its_conversation(harness):
    harness.open("/elsewhere")

    # A reply is known by its message ...
    assert announce_in(harness, chat_reply("conv-a", "m-1")) == [raised("conv-a")]
    assert announce_in(harness, chat_reply("conv-a", "m-1")) == []
    # ... and the next one in the same conversation is noticed in its turn.
    assert announce_in(harness, chat_reply("conv-a", "m-2")) == [raised("conv-a")]

    # An orchestration run's answer is known by the run.
    assert announce_in(harness, run_reply("conv-b", "Budget review", "run-1")) == [raised("conv-b", "Budget review")]
    assert announce_in(harness, run_reply("conv-b", "Budget review", "run-1")) == []
    assert announce_in(harness, run_reply("conv-b", "Budget review", "run-2")) == [raised("conv-b", "Budget review")]

    # With neither, by its conversation.
    anonymous = chat_reply("conv-c", None, "Hiring plan")
    assert announce_in(harness, anonymous) == [raised("conv-c", "Hiring plan")]
    assert announce_in(harness, anonymous) == []
    assert announce_in(harness, chat_reply("conv-d", None, "Travel")) == [raised("conv-d", "Travel")]

    # Classic's wording where there is nothing better: never a blank notice.
    assert announce_in(harness, chat_reply("conv-a", "m-blank", "   ")) == [raised("conv-a", "Conversation")]
    assert announce_in(harness, chat_reply("conv-a", "m-untitled", None)) == [raised("conv-a", "Conversation")]
    assert announce_in(harness, chat_reply("conv-a", "m-padded", "  Quarterly plan  ")) == [raised("conv-a")]
    assert announce_in(harness, chat_reply("conv-a", "m-unbranded"), branding={}) == [
        raised("conv-a", app="Simple Chat"),
    ]
    assert announce_in(harness, chat_reply("conv-a", "m-blank-brand"), branding={"app_title": "   "}) == [
        raised("conv-a", app="Simple Chat"),
    ]
    assert announce_in(harness, chat_reply("conv-a", "m-padded-brand"), branding={"app_title": " Contoso Chat "}) == [
        raised("conv-a"),
    ]


def submit(harness, how, text):
    box = harness.page.get_by_role("textbox", name="Message", exact=True)
    box.fill(text)
    if how == "enter":
        box.press("Enter")
    else:
        harness.page.get_by_role("button", name="Send message", exact=True).click()


@pytest.mark.parametrize(
    ("how", "options", "event_type"),
    [
        pytest.param("click", {}, "click", id="click"),
        pytest.param("enter", {}, "keydown", id="enter"),
        pytest.param("click", {"settings": {"desktopNotificationsEnabled": False}}, None, id="preference-off"),
        pytest.param("click", {"features": {}}, None, id="administrator-off"),
        pytest.param("click", {"settings_loading": True}, None, id="preferences-loading"),
    ],
)
def test_sending_asks_the_browser_once_and_only_while_notifications_are_on(harness, how, options, event_type):
    # The reader will close the browser's prompt without answering, leaving it undecided.
    harness.open("/chat", browser={"permission": "default", "nextPermission": "default"}, **options)
    asked = [{"active": True, "eventType": event_type}] if event_type else []

    submit(harness, how, "Draft the plan")
    harness.wait_for(lambda: harness.conversation_reads == ["conv-a"], "The first reply did not land.")
    # Asked in the key press or click itself: the only moment a browser shows its prompt.
    assert harness.permission_requests() == asked

    harness.settle_count()
    submit(harness, how, "And the budget")
    harness.wait_for(lambda: harness.conversation_reads == ["conv-a", "conv-a"], "The second reply did not land.")
    # Once a page has asked, it leaves the reader alone.
    assert harness.permission_requests() == asked
    assert harness.streams == 2


NOTIFY_TOGGLE = "Notify me when a reply is ready"


def notify_toggle(harness):
    return harness.page.get_by_role("checkbox", name=NOTIFY_TOGGLE, exact=True)


def permission_status(harness):
    return harness.page.locator("[data-desktop-notification-permission]")


def wait_for_saves(harness, count):
    harness.wait_for(lambda: len(harness.settings_posts) >= count, f"The preference was not saved {count} time(s).")
    harness.page.wait_for_timeout(500)
    assert len(harness.settings_posts) == count, harness.settings_posts


def test_allowing_notifications_from_preferences_asks_the_browser_and_changes_no_setting(harness):
    harness.open("/settings", browser={"permission": "default", "nextPermission": "granted"})
    page = harness.page
    status = permission_status(harness)

    # A reader who never chose is opted in, as classic reads the preference.
    expect(notify_toggle(harness)).to_be_checked()
    expect(status).to_have_attribute("data-desktop-notification-permission", "default")
    expect(status).to_contain_text("This browser has not been given permission yet.")

    page.get_by_role("button", name="Allow notifications", exact=True).click()
    expect(status).to_have_count(0)
    assert harness.permission_requests() == [{"active": True, "eventType": "click"}]
    page.wait_for_timeout(600)
    assert harness.settings_posts == []
    expect(notify_toggle(harness)).to_be_checked()


def test_turning_the_preference_on_asks_the_browser_in_the_same_click_and_saves_it(harness):
    harness.open(
        "/settings",
        settings={"desktopNotificationsEnabled": False},
        browser={"permission": "default", "nextPermission": "default"},
    )
    page = harness.page
    toggle = notify_toggle(harness)
    label = page.get_by_text(NOTIFY_TOGGLE, exact=True)
    status = permission_status(harness)
    expect(toggle).not_to_be_checked()
    expect(status).to_have_count(0)

    label.click()
    expect(toggle).to_be_checked()
    assert harness.permission_requests() == [{"active": True, "eventType": "click"}]
    # The prompt was closed unanswered, and the page says the browser is still undecided.
    expect(status).to_have_attribute("data-desktop-notification-permission", "default")
    wait_for_saves(harness, 1)
    assert harness.settings_posts == [{"settings": {"desktopNotificationsEnabled": True}}]

    label.click()
    expect(toggle).not_to_be_checked()
    expect(status).to_have_count(0)
    wait_for_saves(harness, 2)
    assert harness.settings_posts[-1] == {"settings": {"desktopNotificationsEnabled": False}}
    assert len(harness.permission_requests()) == 1

    # Turning it on is a request to be asked, however often the page has asked before.
    label.click()
    expect(toggle).to_be_checked()
    assert harness.permission_requests() == [{"active": True, "eventType": "click"}] * 2
    wait_for_saves(harness, 3)
    assert harness.settings_posts[-1] == {"settings": {"desktopNotificationsEnabled": True}}


@pytest.mark.parametrize("case", ["denied", "unsupported", "administrator-off"])
def test_preferences_say_why_this_browser_cannot_show_a_notice(harness, case):
    browser = {"denied": {"permission": "denied"}, "unsupported": {"notification": False}}.get(case)
    harness.open("/settings", browser=browser, features={} if case == "administrator-off" else None)
    page = harness.page
    status = permission_status(harness)
    expect(page.get_by_role("radiogroup", name="Text size")).to_be_visible()

    if case == "administrator-off":
        # Nothing to turn on, so nothing is offered.
        expect(page.get_by_text(NOTIFY_TOGGLE, exact=True)).to_have_count(0)
        expect(page.get_by_text("Desktop notifications", exact=True)).to_have_count(0)
        expect(status).to_have_count(0)
        return

    explanation = {
        "denied": "This browser is blocking notifications from this site.",
        "unsupported": "This browser cannot show desktop notifications.",
    }[case]
    expect(notify_toggle(harness)).to_be_checked()
    expect(status).to_have_attribute("data-desktop-notification-permission", case)
    expect(status).to_contain_text(explanation)
    # There is nothing the page can ask for.
    expect(page.get_by_role("button", name="Allow notifications")).to_have_count(0)

    label = page.get_by_text(NOTIFY_TOGGLE, exact=True)
    label.click()
    expect(status).to_have_count(0)
    wait_for_saves(harness, 1)
    label.click()
    expect(status).to_have_attribute("data-desktop-notification-permission", case)
    wait_for_saves(harness, 2)

    if case == "denied":
        assert harness.permission_requests() == []
        return
    # A browser without notifications takes a finished reply in a hidden tab in its stride.
    assert harness.js("() => 'Notification' in window") is False
    harness.hide()
    harness.announce(**chat_reply("conv-a", "m-1"))
    harness.page.wait_for_timeout(200)
