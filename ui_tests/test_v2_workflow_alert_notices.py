# test_v2_workflow_alert_notices.py
"""
Browser regressions for the V2 workflow alert notice, its alert card and their runtime.
Version: 0.261.230
Implemented in: 0.261.199
Open and Dismiss up front, everything else under Show more: 0.261.228
Open run in Open workflow's place for an alert that names its run: 0.261.230

Exercises the real rail, bell, notice, card, live region, stores and both notification
runtimes, bundled by fixtures/workflow_alerts. Only HTTP answers and the browser APIs a
headless page cannot drive -- page visibility and window focus -- are replaced. Alerts are
dated from the real clock, because only alerts from the last day pop up; the tests that run
the tuck timer install Playwright's clock at that same moment. The existing Azure Playwright
connection fixture also supports a local browser; no live application data is read or
modified.
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
    WORKFLOW_ALERT_NOTIFICATION_TYPE,
    WORKFLOW_ALERTS_PATH,
    conversation_mark_read_payload,
    notification_count_payload,
    workflow_alert_conversation_target,
    workflow_alert_document,
    workflow_alerts_payload,
)


pytestmark = pytest.mark.ui

FIXTURE = ROOT / "ui_tests" / "fixtures" / "workflow_alerts"
BUNDLE = FIXTURE / "harness.bundle.js"
BUNDLE_CSS = FIXTURE / "harness.bundle.css"
V2_SOURCE = ROOT / "application" / "v2_ui" / "src"
STATIC = ROOT / "application" / "single_app" / "static"
ORIGIN = "https://simplechat.test"
USER_ID = "user-1"
# What the V2 runtime asks for: the store's cap, and only the day a pop-up may come from.
ALERT_QUERY = {"limit": "10", "since_hours": "24"}
WORKFLOW_NAME = "Nightly release readiness scan"
PRIORITIES = ("info", "low", "medium", "high", "critical")
CATEGORIES = ("alert", "failure")
OFF_SITE = "This notification links to another site, so it is not opened from here."
XSS = '<img src=x onerror="window.__xss=1"><b>Quoted mail</b> & <script>window.__xss=2</script>'
# Enrichment labels are capped at 80 characters, so they carry a shorter payload.
SHORT_XSS = '<img src=x onerror="window.__xss=3">'
LAYOUTS = {
    "expanded": {"rail_collapsed": False, "viewport": None, "placement": "below", "nav": 280},
    "collapsed": {"rail_collapsed": True, "viewport": None, "placement": "flyout", "nav": 68},
    "phone": {"rail_collapsed": False, "viewport": {"width": 360, "height": 740}, "placement": "flyout", "nav": 68},
}
# --surface-modal, the glass the notice is drawn on, in each theme.
NOTICE_SURFACE = {"light": "rgba(252, 253, 255, 0.97)", "dark": "rgba(22, 29, 46, 0.97)"}

# Page visibility and window focus as a desktop browser has them, a log of every request the
# page makes, a count of the alert reads that have landed, and a record of every Web Animations
# call. Installed before any application code runs, on every document the page loads.
FAKE_BROWSER = r"""
(options) => {
    const env = {visible: true, focused: true};
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
    window.__harness = {show, hide};

    // Desktop notifications belong to the bell's own suite; none are offered here.
    delete window.Notification;

    window.__fetchLog = [];
    const alertReads = {started: 0, finished: 0, failed: 0};
    window.__alertFetches = alertReads;
    const originalFetch = window.fetch;
    window.fetch = function (input, init) {
        let path = String(input);
        let method = 'GET';
        try {
            const raw = typeof input === 'string' ? input : (input && input.url) || String(input);
            const url = new URL(raw, window.location.href);
            path = url.pathname + url.search;
            method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        } catch (error) {
            // Logged as given.
        }
        window.__fetchLog.push({path, method, at: Date.now()});
        const pending = originalFetch.apply(window, arguments);
        if (path.startsWith(options.alertsPath)) {
            // Attached before the page's own handlers, so the body is cloned before it is read.
            alertReads.started += 1;
            const failed = () => {
                alertReads.failed += 1;
                alertReads.finished += 1;
            };
            pending.then(
                (response) => response.clone().text().then(() => {
                    if (!response.ok) alertReads.failed += 1;
                    alertReads.finished += 1;
                }, failed),
                failed,
            );
        }
        return pending;
    };

    window.__animations = [];
    const originalAnimate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, timing) {
        try {
            const frames = Array.isArray(keyframes) ? keyframes : [keyframes || {}];
            const properties = new Set();
            for (const frame of frames) {
                for (const key of Object.keys(frame || {})) {
                    if (!['offset', 'easing', 'composite'].includes(key)) properties.add(key);
                }
            }
            const settings = typeof timing === 'number' ? {duration: timing} : (timing || {});
            window.__animations.push({
                target: this.closest('[data-workflow-alert-card]') ? 'card'
                    : this.closest('[data-workflow-alert-notice]') ? 'notice'
                    : this.tagName.toLowerCase(),
                properties: [...properties].sort(),
                duration: settings.duration === undefined ? null : settings.duration,
                fill: settings.fill === undefined ? null : settings.fill,
            });
        } catch (error) {
            // Recording never changes what the page does.
        }
        return originalAnimate.apply(this, arguments);
    };
}
"""

SEED = r"""
(seed) => {
    const H = window.WorkflowAlertHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.199',
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
    H.stores.userSettings.useUserSettingsStore.setState({settings: {}, loading: false, error: null});
    H.stores.ui.useUiStore.setState({railCollapsed: seed.railCollapsed, mobileNavOpen: false, theme: seed.theme});
    document.documentElement.classList.toggle('dark', seed.theme === 'dark');
    document.documentElement.style.colorScheme = seed.theme;

    // Count every batch the runtime hands the store, so a test can wait for a read to land.
    const store = H.stores.workflowAlert.useWorkflowAlertStore;
    const receive = store.getState().receiveAlerts;
    window.__alertReceives = 0;
    window.__receiveAlertsDirect = receive;
    store.setState({
        receiveAlerts: (...args) => {
            window.__alertReceives += 1;
            return receive(...args);
        },
    });
    window.__phases = [];
    store.subscribe((state, previous) => {
        if (state.phase !== previous.phase) window.__phases.push(state.phase);
    });
    H.mount(seed.path);
}
"""

COUNT_SETTLED = r"""
() => {
    const started = window.__fetchLog.filter((item) => item.path === '/api/notifications/count').length;
    return started > 0 && !window.WorkflowAlertHarness.stores.notification.isNotificationCountReading();
}
"""

# Every alert read that started has landed and been handed to the store, and the store has
# claimed what it could show -- unless it is holding everything back.
ALERTS_SETTLED = r"""
() => {
    const reads = window.__alertFetches;
    const state = window.WorkflowAlertHarness.stores.workflowAlert.useWorkflowAlertStore.getState();
    return reads.started === reads.finished
        && reads.finished === window.__alertReceives + reads.failed
        && (state.suspended || state.queue.length === 0);
}
"""

STATE = r"""
() => {
    const state = window.WorkflowAlertHarness.stores.workflowAlert.useWorkflowAlertStore.getState();
    return {
        phase: state.phase,
        suspended: state.suspended,
        queue: state.queue.map((alert) => alert.id),
        entries: state.entries.map((entry) => entry.alerts.map((alert) => alert.id)),
        cardIndex: state.cardIndex,
        ringToken: state.ringToken,
        busy: state.busy,
    };
}
"""

# Hand alerts to the store directly, as the lab does, after clearing what it holds.
RECEIVE_DIRECT = r"""
(raw) => {
    const H = window.WorkflowAlertHarness;
    H.stores.workflowAlert.resetWorkflowAlertsForLab();
    const alerts = raw.map((item) => H.notices.readWorkflowAlert(item)).filter(Boolean);
    window.__receiveAlertsDirect(alerts);
}
"""

GEOMETRY = r"""
(notice) => {
    const rect = notice.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    const nav = document.getElementById('primary-navigation').getBoundingClientRect();
    return {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        onTop: Boolean(hit && hit.closest('[data-workflow-alert-notice]')),
        nav: Math.round(nav.width),
        background: getComputedStyle(notice).backgroundColor,
    };
}
"""

# The properties every wf-* keyframe animates.
KEYFRAMES = r"""
() => {
    const found = {};
    const walk = (rules) => {
        for (const rule of rules) {
            if (rule.type === CSSRule.KEYFRAMES_RULE && rule.name.startsWith('wf-')) {
                const properties = new Set(found[rule.name] || []);
                for (const frame of rule.cssRules) {
                    for (let index = 0; index < frame.style.length; index += 1) {
                        properties.add(frame.style[index]);
                    }
                }
                found[rule.name] = [...properties].sort();
            } else if (rule.cssRules) {
                walk(rule.cssRules);
            }
        }
    };
    for (const sheet of document.styleSheets) {
        try {
            walk(sheet.cssRules);
        } catch (error) {
            // A sheet from another origin cannot be read; the harness loads none.
        }
    }
    return found;
}
"""

# WCAG contrast of every piece of visible text under `root`, against the backgrounds painted
# beneath it. Colours are read through a canvas, so any syntax the browser computes -- rgb(),
# oklab(), color-mix() results -- is compared as the pixels it paints.
CONTRAST = r"""
(root, relaxed) => {
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    const unparsed = new Set();
    const parse = (value) => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = '#010203';
        context.fillStyle = value;
        if (context.fillStyle === '#010203' && !/^#010203$/i.test(value)) {
            unparsed.add(value);
            return {r: 0, g: 0, b: 0, a: 0};
        }
        context.fillRect(0, 0, 1, 1);
        const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
        return {r, g, b, a: a / 255};
    };
    const over = (top, bottom) => ({
        r: top.r * top.a + bottom.r * (1 - top.a),
        g: top.g * top.a + bottom.g * (1 - top.a),
        b: top.b * top.a + bottom.b * (1 - top.a),
        a: 1,
    });
    const backgroundOf = (element) => {
        const chain = [];
        for (let node = element; node; node = node.parentElement) chain.unshift(node);
        let colour = {r: 255, g: 255, b: 255, a: 1};
        for (const node of chain) {
            const layer = parse(getComputedStyle(node).backgroundColor);
            if (layer.a > 0) colour = over(layer, colour);
        }
        return colour;
    };
    const channel = (value) => {
        const unit = value / 255;
        return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
    };
    const luminance = ({r, g, b}) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    const ratio = (first, second) => {
        const [light, dark] = [luminance(first), luminance(second)].sort((x, y) => y - x);
        return (light + 0.05) / (dark + 0.05);
    };

    const elements = new Set();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (node.textContent.trim() && node.parentElement) elements.add(node.parentElement);
    }
    const failures = [];
    let checked = 0;
    for (const element of elements) {
        const rect = element.getBoundingClientRect();
        // Screen-reader-only text is clipped to a pixel and never painted.
        if (rect.width <= 1 || rect.height <= 1) continue;
        if (!element.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
        checked += 1;
        const style = getComputedStyle(element);
        const background = backgroundOf(element);
        const colour = over(parse(style.color), background);
        const size = parseFloat(style.fontSize);
        const bold = Number(style.fontWeight) >= 700;
        const large = size >= 24 || (size >= 18.66 && bold);
        let required = large ? 3 : 4.5;
        for (const [selector, minimum] of relaxed) {
            if (element.closest(selector)) required = Math.min(required, minimum);
        }
        const value = ratio(colour, background);
        if (value < required) {
            failures.push({
                text: element.textContent.trim().slice(0, 60),
                ratio: Math.round(value * 100) / 100,
                required,
                colour: style.color,
                background: `rgb(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)})`,
            });
        }
    }
    return {failures, checked, unparsed: [...unparsed]};
}
"""

# The primary button pairs --accent with --on-accent at 4.49:1 in the light theme. That is a
# design-token matter for every primary button in V2, not one this notice can fix alone.
CONTRAST_RELAXED = [["[data-workflow-alert-mark-read]", 4.45]]


def iso(value):
    return value.isoformat(timespec="milliseconds")


def epoch_ms(value):
    return int(value.timestamp() * 1000)


class AlertServer:
    """The routes the frame calls, answered the way route_backend_* answers, shared by every tab."""

    def __init__(self, stylesheets):
        self.stylesheets = stylesheets
        self.notices = []
        self.requests = []
        self.alert_queries = []
        self.list_queries = []
        self.read_calls = []
        self.dismiss_calls = []
        self.mark_all_calls = 0
        self.settings_posts = []
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()
        # When set, the alerts route leaves out its delivery and recency filters, as a server
        # from before they existed would, so the client's own checks are what is tested.
        self.leaky = False
        # When set, the alerts route answers as it does when storage cannot be read.
        self.alerts_failing = False
        # When not None, the count route answers this, as it answers 0 when it cannot count.
        self.count_override = None
        # While set, alert reads are answered as of their arrival, but only on release().
        self.holding = False
        self.held = []

    # Server state -----------------------------------------------------------------------------

    def add(self, *records):
        self.notices.extend(records)

    def find(self, notice_id):
        return next((record for record in self.notices if record["id"] == notice_id), None)

    def unread(self):
        return [record for record in self.notices if not record["is_read"] and not record["is_dismissed"]]

    def mark_read(self, notice_id):
        """Read the notice somewhere else: in classic, or in another tab."""
        record = self.find(notice_id)
        record["is_read"] = True
        record["read_by"] = [USER_ID]

    def release(self):
        """Send the alert reads held back, each with the answer it would have had on arrival."""
        self.holding = False
        held, self.held = self.held, []
        for route, payload in held:
            route.fulfill(json=payload)

    def listed(self, include_read=True, include_dismissed=False):
        items = [
            record for record in self.notices
            if (include_dismissed or not record["is_dismissed"]) and (include_read or not record["is_read"])
        ]
        return sorted(items, key=lambda record: record["created_at"], reverse=True)

    # Routing ----------------------------------------------------------------------------------

    def handle(self, route, tab):
        request = route.request
        parsed = urlsplit(request.url)
        method = request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(f"{tab}: {method} {request.url}")
            route.abort()
            return
        path = parsed.path
        self.requests.append((tab, method, f"{path}?{parsed.query}" if parsed.query else path, request.resource_type))
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        for answer in (self.page_route, self.notification_route, self.conversation_route, self.other_route):
            if answer(route, method, path, query, tab):
                return
        self.unexpected.append(f"{tab}: {method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def page_route(self, route, method, path, query, tab):
        if method != "GET":
            return False
        if path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        elif path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if not (asset.is_relative_to(STATIC.resolve()) and asset.is_file()):
                return False
            route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        else:
            return False
        return True

    def notification_route(self, route, method, path, query, tab):
        if method == "GET" and path == "/api/notifications/count":
            # get_unread_notification_count caps the count at 10.
            count = min(len(self.unread()), 10) if self.count_override is None else self.count_override
            route.fulfill(json=notification_count_payload(count))
        elif method == "GET" and path == WORKFLOW_ALERTS_PATH:
            self.answer_alerts(route, path, query, tab)
        elif method == "GET" and path == "/api/notifications":
            self.answer_list(route, query)
        elif method == "POST" and path == "/api/notifications/mark-all-read":
            self.answer_mark_all(route)
        elif method == "POST" and (match := re.fullmatch(r"/api/notifications/([^/]+)/read", path)):
            self.answer_change(route, unquote(match.group(1)), "read")
        elif method == "DELETE" and (match := re.fullmatch(r"/api/notifications/([^/]+)/dismiss", path)):
            self.answer_change(route, unquote(match.group(1)), "dismiss")
        else:
            return False
        return True

    def conversation_route(self, route, method, path, query, tab):
        if method == "GET" and path == "/api/conversations/feed":
            route.fulfill(json={
                "success": True, "conversations": [], "has_more": False, "next_cursor": None,
                "page_size": int(query.get("page_size", 50)), "hidden_count": 0, "priority_count": 0,
                "recent_count": 0, "source_offsets": {},
            })
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/kind", path)):
            route.fulfill(json={"conversation_id": unquote(match.group(1)), "kind": "personal"})
        elif method == "GET" and re.fullmatch(r"/api/conversations/[^/]+/metadata", path):
            route.fulfill(json={})
        elif method == "GET" and path == "/api/get_messages":
            route.fulfill(json={"messages": []})
        elif method == "POST" and (match := re.fullmatch(r"/api/conversations/([^/]+)/mark-read", path)):
            route.fulfill(json=conversation_mark_read_payload(unquote(match.group(1))))
        else:
            return False
        return True

    def other_route(self, route, method, path, query, tab):
        if method == "GET" and re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
        elif method == "GET" and path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
        elif method == "POST" and path == "/api/user/settings":
            self.settings_posts.append(route.request.post_data_json)
            route.fulfill(json={"message": "User settings updated successfully"})
        elif method == "PATCH" and path == "/api/groups/setActive":
            route.fulfill(json={"message": "Active group set"})
        else:
            return False
        return True

    # Answers ----------------------------------------------------------------------------------

    def answer_alerts(self, route, path, query, tab):
        """get_unread_workflow_priority_notifications behind api_get_workflow_alert_notifications."""
        self.alert_queries.append((tab, dict(query)))
        if self.alerts_failing:
            # With since_hours, a storage failure reaches the route's 500 answer.
            self.expected_http_failures.add((path, 500))
            route.fulfill(status=500, json={"success": False, "notifications": []})
            return
        since = None
        if "since_hours" in query:
            hours = query["since_hours"]
            if not (hours.isascii() and hours.isdigit() and len(hours) <= 4 and 1 <= int(hours) <= 1440):
                self.expected_http_failures.add((path, 400))
                route.fulfill(status=400, json={
                    "success": False, "notifications": [],
                    "error": "since_hours must be a whole number of hours from 1 to 1440.",
                })
                return
            since = datetime.now(timezone.utc) - timedelta(hours=int(hours))
        try:
            limit = int(query.get("limit", 5))
        except ValueError:
            limit = 5
        limit = max(1, min(limit, 10))
        items = [
            record for record in self.notices
            if record["notification_type"] == WORKFLOW_ALERT_NOTIFICATION_TYPE
            and not record["is_read"] and not record["is_dismissed"]
        ]
        if not self.leaky:
            items = [record for record in items if record["metadata"].get("delivery") != "notify_only"]
            if since is not None:
                items = [record for record in items if datetime.fromisoformat(record["created_at"]) >= since]
        items.sort(key=lambda record: record["created_at"], reverse=True)
        payload = workflow_alerts_payload(copy.deepcopy(items[:limit]))
        if self.holding:
            self.held.append((route, payload))
            return
        route.fulfill(json=payload)

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

    def answer_change(self, route, notice_id, change):
        (self.read_calls if change == "read" else self.dismiss_calls).append(notice_id)
        record = self.find(notice_id)
        if record is None:
            self.unexpected.append(f"{change} of unknown notice {notice_id}")
            route.fulfill(status=404, json={"error": "Notification not found"})
            return
        if change == "read":
            record["is_read"] = True
            record["read_by"] = [USER_ID]
            route.fulfill(json={"success": True, "message": "Notification marked as read"})
        else:
            record["is_dismissed"] = True
            record["dismissed_by"] = [USER_ID]
            route.fulfill(json={"success": True, "message": "Notification dismissed"})

    def answer_mark_all(self, route):
        self.mark_all_calls += 1
        unread = self.unread()
        for record in unread:
            record["is_read"] = True
            record["read_by"] = [USER_ID]
        route.fulfill(json={
            "success": True, "message": f"{len(unread)} notifications marked as read", "count": len(unread),
        })


class AlertTab:
    """One tab running the frame, driven the way a reader drives it."""

    def __init__(self, page, server, label):
        self.page = page
        self.server = server
        self.label = label
        self.clocked = False

    def open(self, path="/work", *, rail_collapsed=False, theme="light", clock=None, viewport=None,
             reduced_motion=False, reduced_transparency=False):
        if viewport:
            self.page.set_viewport_size(viewport)
        self.page.emulate_media(reduced_motion="reduce" if reduced_motion else "no-preference")
        if reduced_transparency:
            self.emulate_reduced_transparency(reduced_motion)
        options = {"alertsPath": WORKFLOW_ALERTS_PATH}
        self.page.add_init_script(script=f"({FAKE_BROWSER})({json.dumps(options)})")
        if clock is not None:
            self.clocked = True
            self.page.clock.install(time=clock)
            self.page.clock.pause_at(clock + timedelta(seconds=1))
        self.page.route("**/*", lambda route: self.server.handle(route, self.label))
        self.page.on("pageerror", lambda error: self.server.errors.append(f"{self.label}: {error}"))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        if reduced_transparency and not self.js("() => matchMedia('(prefers-reduced-transparency: reduce)').matches"):
            pytest.skip("This browser cannot emulate prefers-reduced-transparency.")
        for stylesheet in self.server.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.js(SEED, {"path": path, "railCollapsed": rail_collapsed, "theme": theme})
        self.settle()
        return self

    def emulate_reduced_transparency(self, reduced_motion):
        """Playwright has no option for this media feature yet; Chromium's DevTools protocol does."""
        try:
            session = self.page.context.new_cdp_session(self.page)
            session.send("Emulation.setEmulatedMedia", {"features": [
                {"name": "prefers-reduced-transparency", "value": "reduce"},
                {"name": "prefers-reduced-motion", "value": "reduce" if reduced_motion else "no-preference"},
            ]})
        except Exception as error:  # noqa: BLE001 - any browser without the protocol is skipped
            pytest.skip(f"This browser cannot emulate prefers-reduced-transparency: {error}")

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.server.expected_http_failures:
            return
        self.server.errors.append(f"{self.label}: {message.text}")

    # Waiting ----------------------------------------------------------------------------------

    def wait_for(self, predicate, message, timeout=5.0):
        """Poll from the test thread, so routes keep being answered meanwhile."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(message)
            self.page.wait_for_timeout(50)

    def wait_for_js(self, script, message, arg=None, timeout=5.0):
        self.wait_for(lambda: self.page.evaluate(script, arg), message, timeout)

    def settle_count(self):
        """Wait until every count read that has started has landed."""
        self.wait_for_js(COUNT_SETTLED, f"{self.label}: a notification count read did not land.")
        self.page.wait_for_timeout(100)
        self.wait_for_js(COUNT_SETTLED, f"{self.label}: a notification count read did not land.")

    def settle(self):
        """Wait until the count and every alert read it led to have landed and been claimed."""
        self.settle_count()
        self.wait_alerts_settled()
        self.page.wait_for_timeout(100)
        self.wait_alerts_settled()

    def wait_alerts_settled(self):
        try:
            self.wait_for_js(ALERTS_SETTLED, "")
        except AssertionError:
            reads = self.js("""() => {
                const state = window.WorkflowAlertHarness.stores.workflowAlert.useWorkflowAlertStore.getState();
                return {...window.__alertFetches, received: window.__alertReceives,
                        queued: state.queue.length, suspended: state.suspended};
            }""")
            raise AssertionError(
                f"{self.label}: a workflow alert read did not land, a failed one was received as an "
                f"answer, or what it found was not claimed: {reads}"
            ) from None

    def wait_tucked(self):
        """
        Wait for the notice to finish tucking into the bell. The tuck is a Web Animation, which
        runs in real time even on a paused clock; only its fallback timer needs the clock.
        """
        deadline = time.monotonic() + 3
        while self.notice.count() and time.monotonic() < deadline:
            self.page.wait_for_timeout(50)
        if self.notice.count() and self.clocked:
            self.run_for(700)
        expect(self.notice).to_have_count(0)
        assert self.state()["phase"] == "idle", self.state()

    # Reading the page -------------------------------------------------------------------------

    def js(self, script, arg=None):
        return self.page.evaluate(script, arg)

    def state(self):
        return self.js(STATE)

    def claims(self):
        return self.js("() => JSON.parse(localStorage.getItem('simplechat.v2.workflowAlertClaims') || '{}')")

    def tab_id(self):
        return self.js("() => window.WorkflowAlertHarness.claims.workflowAlertClaimTabId()")

    def alert_queries(self):
        return [query for label, query in self.server.alert_queries if label == self.label]

    def count_fetches(self):
        return self.js("() => window.__fetchLog.filter((item) => item.path === '/api/notifications/count').length")

    def animations(self, target):
        return [item for item in self.js("() => window.__animations") if item["target"] == target]

    def focus_in_card(self):
        return self.js("() => Boolean(document.activeElement && document.activeElement.closest('[data-workflow-alert-card]'))")

    def contrast(self, locator):
        return locator.evaluate(CONTRAST, CONTRAST_RELAXED)

    def route_text(self):
        return self.page.locator("[data-current-route]").text_content()

    @property
    def notice(self):
        return self.page.locator("[data-workflow-alert-notice]")

    @property
    def open_button(self):
        return self.notice.locator("[data-workflow-alert-open]")

    @property
    def close_button(self):
        return self.notice.locator("[data-workflow-alert-close]")

    @property
    def card(self):
        return self.page.locator("[data-workflow-alert-card]")

    def live(self, politeness):
        return self.page.locator(f'[data-workflow-alert-live="{politeness}"]')

    @property
    def bell(self):
        return self.page.locator("button[data-notification-bell]")

    @property
    def bell_ring(self):
        return self.bell.locator("[data-notification-bell-ring]")

    @property
    def panel(self):
        return self.page.locator("[data-notification-panel]")

    @property
    def notes(self):
        return self.page.get_by_label("Notes", exact=True)

    @property
    def my_workspace(self):
        return self.page.get_by_role("link", name="My Workspace", exact=True)

    # Acting -----------------------------------------------------------------------------------

    def start_poll(self):
        """Read the count as the poll timer does. Returns what finish_poll waits past."""
        self.settle_count()
        before = self.count_fetches()
        self.js("() => { void window.WorkflowAlertHarness.stores.notification.refreshNotificationCount('poll'); }")
        return before

    def finish_poll(self, before):
        self.wait_for(lambda: self.count_fetches() > before, f"{self.label}: the count was not read.")
        self.settle()

    def poll(self):
        self.finish_poll(self.start_poll())

    def hide(self):
        self.js("() => window.__harness.hide()")

    def show(self):
        self.js("() => window.__harness.show()")

    def run_for(self, milliseconds):
        self.page.clock.run_for(milliseconds)

    def hover_notice(self):
        """Point at the notice. Raw mouse input, which needs no animation frame on a paused clock."""
        centre = self.notice.evaluate("""(notice) => {
            const rect = notice.getBoundingClientRect();
            return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
        }""")
        self.page.mouse.move(centre["x"], centre["y"])
        self.page.wait_for_timeout(200)

    def leave_notice(self):
        self.page.mouse.move(700, 600)
        self.page.wait_for_timeout(200)

    def focus(self, selector):
        self.js("(selector) => document.querySelector(selector).focus()", selector)
        self.page.wait_for_timeout(200)

    def wait_not_busy(self):
        self.wait_for(lambda: not self.state()["busy"], f"{self.label}: a card action did not finish.")


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
    BUNDLE_CSS.unlink(missing_ok=True)


@pytest.fixture
def server(harness_assets):
    api = AlertServer(harness_assets)
    yield api
    assert not api.held, "A test left alert reads held back."
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected


@pytest.fixture
def tab(page, server):
    return AlertTab(page, server, "tab-1")


@pytest.fixture
def another_tab(context, server):
    """Another tab of the same browser, sharing its storage and its locks with the first."""
    def make(label):
        return AlertTab(context.new_page(), server, label)
    return make


@pytest.fixture
def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def alert(now):
    """A workflow alert raised `minutes_ago`; each one is its own workflow unless it says otherwise."""
    def make(notification_id, minutes_ago=1, **fields):
        fields.setdefault("workflow_id", f"wf-{notification_id}")
        return workflow_alert_document(notification_id, created_at=iso(now - timedelta(minutes=minutes_ago)), **fields)
    return make


# When a notice appears -------------------------------------------------------------------------


def test_only_recent_popup_alerts_pop_up_and_the_notice_leaves_focus_alone(tab, server, alert):
    server.leaky = True
    tab.open()
    assert tab.alert_queries() == [], "Nothing was unread, so the alerts must not have been read."
    tab.notes.click()
    tab.page.keyboard.type("Draft ")

    server.add(
        alert("quiet-low", priority="low", delivery="notify_only", title="Nightly summary is ready"),
        alert("quiet-critical", priority="critical", delivery="notify_only", title="Quota almost used"),
        alert("stale", minutes_ago=25 * 60, title="Yesterday's gate"),
        alert("fresh", title="Deploy gate is red"),
    )
    tab.poll()

    expect(tab.notice).to_be_visible()
    expect(tab.notice).to_have_attribute("data-count", "1")
    expect(tab.notice).to_contain_text("Deploy gate is red")
    expect(tab.notice.locator("[data-workflow-alert-more]")).to_have_count(0)
    assert tab.state()["entries"] == [["fresh"]]
    assert set(tab.claims()) == {"fresh"}
    queries = tab.alert_queries()
    assert queries and all(query == ALERT_QUERY for query in queries), queries

    # Nothing new: a poll that finds the same count does not read the alerts again.
    tab.poll()
    assert tab.alert_queries() == queries

    # The reader was typing; the notice never took the caret.
    tab.page.keyboard.type("agenda")
    expect(tab.notes).to_be_focused()
    expect(tab.notes).to_have_value("Draft agenda")
    expect(tab.live("polite")).to_have_text(
        f"High priority workflow alert: Deploy gate is red, from {WORKFLOW_NAME}.",
    )
    expect(tab.live("assertive")).to_have_text("")


def test_each_alert_is_shown_by_one_tab_only(tab, another_tab, server, alert):
    tab.open()
    other = another_tab("tab-2").open()
    server.add(alert("shared", title="Deploy gate is red"))

    first, second = tab.start_poll(), other.start_poll()
    tab.finish_poll(first)
    other.finish_poll(second)
    # Both tabs read the alert; only the claim decides which one shows it.
    assert tab.alert_queries() == [ALERT_QUERY] and other.alert_queries() == [ALERT_QUERY], server.alert_queries

    tabs = (tab, other)
    tab.wait_for(
        lambda: sum(item.notice.count() for item in tabs) == 1,
        "Exactly one tab should show the alert.",
    )
    winner = tab if tab.notice.count() else other
    loser = other if winner is tab else tab
    claims = tab.claims()
    assert set(claims) == {"shared"}, claims
    assert claims["shared"]["tab"] == winner.tab_id() != loser.tab_id()
    assert loser.state()["phase"] == "idle" and loser.state()["entries"] == [], loser.state()
    expect(winner.notice).to_contain_text("Deploy gate is red")

    # A tab opened afterwards reads the alert with its first count, and leaves it to the claim.
    third = another_tab("tab-3").open()
    assert third.alert_queries() == [ALERT_QUERY]
    third.page.wait_for_timeout(300)
    assert third.state()["phase"] == "idle", third.state()
    expect(third.notice).to_have_count(0)
    expect(winner.notice).to_be_visible()


def test_an_alert_waits_while_a_dialog_is_open(tab, server, alert):
    tab.open()
    opener = tab.page.get_by_role("button", name="Open a dialog", exact=True)
    opener.click()
    dialog = tab.page.get_by_role("dialog", name="Share settings")
    expect(dialog).to_be_visible()

    server.add(alert("waiting", title="Deploy gate is red"))
    tab.poll()
    state = tab.state()
    assert state["suspended"] and state["queue"] == ["waiting"] and state["phase"] == "idle", state
    assert tab.claims() == {}
    tab.page.wait_for_timeout(1000)
    assert tab.state()["phase"] == "idle"
    expect(tab.notice).to_have_count(0)

    dialog.get_by_role("button", name="Done", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(tab.notice).to_be_visible()
    expect(tab.live("polite")).to_have_text(f"High priority workflow alert: Deploy gate is red, from {WORKFLOW_NAME}.")
    assert set(tab.claims()) == {"waiting"}
    expect(opener).to_be_focused()


def test_an_alert_waits_while_the_bell_panel_is_open(tab, server, alert):
    tab.open()
    tab.bell.click()
    expect(tab.panel).to_be_visible()
    tab.wait_for(lambda: server.list_queries, "Opening the panel did not read the list.")

    server.add(alert("urgent", priority="critical", title="Production deploy blocked"))
    tab.poll()
    state = tab.state()
    assert state["suspended"] and state["queue"] == ["urgent"], state
    expect(tab.notice).to_have_count(0)

    tab.page.keyboard.press("Escape")
    expect(tab.panel).to_have_count(0)
    expect(tab.notice).to_be_visible(timeout=3000)
    expect(tab.bell).to_be_focused()
    expect(tab.live("assertive")).to_have_text(
        f"Critical priority workflow alert: Production deploy blocked, from {WORKFLOW_NAME}.",
    )
    expect(tab.live("polite")).to_have_text("")


def test_an_alert_read_while_the_tab_was_hidden_never_pops_up(tab, server, alert):
    tab.open()
    tab.hide()
    server.add(alert("away", title="Deploy gate is red"))
    tab.poll()
    state = tab.state()
    assert state["suspended"] and state["queue"] == ["away"], state

    # Read in another tab while this one was in the background.
    server.mark_read("away")
    tab.js("() => { window.__phases = []; }")
    tab.show()
    tab.settle()
    state = tab.state()
    assert "notice" not in tab.js("() => window.__phases")
    assert state["queue"] == [] and state["entries"] == [] and state["phase"] == "idle", state
    assert tab.claims() == {}
    expect(tab.notice).to_have_count(0)

    # One raised while away pops up on return, from a single read.
    tab.page.wait_for_timeout(2200)
    tab.hide()
    server.add(alert("back", title="Canary error rate is up"))
    before = len(tab.alert_queries())
    tab.show()
    tab.settle()
    expect(tab.notice).to_be_visible()
    expect(tab.notice).to_contain_text("Canary error rate is up")
    assert len(tab.alert_queries()) == before + 1


def test_only_a_successful_read_retires_an_alert(tab, server, alert):
    """
    A failed alerts read says nothing about what is still unread, and the count route answers
    zero when it cannot count as well as when nothing is unread. Neither retires an alert: a
    critical notice stays through a failed read on the reader's return, and through a zero count
    whose confirming read fails. The next complete answer that leaves it out retires it.
    """
    tab.open()
    server.add(alert("urgent", priority="critical", title="Production deploy blocked"))
    tab.poll()
    expect(tab.notice).to_be_visible()

    def read_again(action, message):
        before = len(tab.alert_queries())
        action()
        tab.wait_for(lambda: len(tab.alert_queries()) > before, message)
        tab.settle()

    def still_showing():
        expect(tab.notice).to_be_visible()
        expect(tab.notice).to_contain_text("Production deploy blocked")
        state = tab.state()
        assert state["phase"] == "notice" and state["entries"] == [["urgent"]], state

    # The reader comes back, and the read on their return fails.
    server.alerts_failing = True
    tab.page.wait_for_timeout(2300)

    def come_back():
        tab.hide()
        tab.show()

    read_again(come_back, "Coming back did not read the alerts.")
    still_showing()

    # The count reads zero while the notice shows, and the read that would confirm it fails.
    server.count_override = 0
    read_again(tab.poll, "A zero count did not confirm with an alerts read.")
    still_showing()
    assert server.find("urgent")["is_read"] is False
    assert server.read_calls == [] and server.dismiss_calls == []

    # Read somewhere else: the next complete answer leaves it out, and that retires it.
    server.alerts_failing = False
    server.count_override = None
    server.mark_read("urgent")
    read_again(tab.poll, "A zero count did not confirm with an alerts read.")
    expect(tab.notice).to_have_count(0)
    state = tab.state()
    assert state["phase"] == "idle" and state["entries"] == [] and state["queue"] == [], state
    assert tab.alert_queries() == [ALERT_QUERY] * 4


def test_a_rise_on_return_is_read_even_behind_another_read(tab, server, alert):
    """
    Coming back reads the alerts, but not twice in two seconds. A count that rose on the way back
    means a new alert, though, and a read already on its way may have left before it was written,
    so another read follows that one.
    """
    tab.open()
    server.add(alert("first", title="Deploy gate is red"))
    tab.poll()
    expect(tab.notice).to_contain_text("Deploy gate is red")
    tab.page.wait_for_timeout(2300)

    # A new alert starts a read, and that read is slow to answer.
    server.holding = True
    server.add(alert("second", title="Canary error rate is up"))
    before = len(tab.alert_queries())
    tab.start_poll()
    tab.wait_for(lambda: len(server.held) == 1, "The rise did not read the alerts.")

    # Another alert is written after that read left, and the reader looks away and back.
    server.add(alert("third", priority="critical", title="Ledger totals do not match"))
    tab.page.wait_for_timeout(2300)
    counts = tab.count_fetches()
    tab.hide()
    tab.show()
    tab.wait_for(lambda: tab.count_fetches() > counts, "Coming back did not read the count.")
    tab.settle_count()
    assert len(tab.alert_queries()) == before + 1

    server.release()
    tab.settle()
    assert len(tab.alert_queries()) == before + 2
    expect(tab.notice).to_contain_text("Ledger totals do not match")
    expect(tab.notice).to_have_attribute("data-priority", "critical")


# Timers ----------------------------------------------------------------------------------------


def test_a_medium_alert_tucks_into_the_bell_after_eight_seconds(tab, server, alert, now):
    tab.open(clock=now)
    server.add(alert("steady", priority="medium", title="Two checks are flaky"))
    tab.poll()
    expect(tab.notice).to_be_visible()

    tab.run_for(7000)
    expect(tab.notice).to_be_visible()
    tab.run_for(1100)
    tab.wait_tucked()

    # Tucked, not handled: the bell rang, the alert is still unread there, and it stays claimed.
    expect(tab.bell_ring).to_have_count(1)
    expect(tab.bell).to_have_attribute("data-unread-count", "1")
    assert server.read_calls == [] and server.dismiss_calls == []
    assert server.find("steady")["is_read"] is False
    assert set(tab.claims()) == {"steady"}

    # Coming back reads the alerts again, and a tucked alert does not pop up a second time.
    before = len(tab.alert_queries())
    tab.run_for(2500)
    tab.hide()
    tab.show()
    tab.settle()
    assert len(tab.alert_queries()) == before + 1
    expect(tab.notice).to_have_count(0)


def test_hover_and_focus_pause_the_tuck_timer(tab, server, alert, now):
    tab.open(clock=now)
    server.add(alert("paused", priority="medium", title="Two checks are flaky"))
    tab.poll()
    expect(tab.notice).to_be_visible()

    tab.run_for(7000)
    tab.hover_notice()
    tab.run_for(5000)
    expect(tab.notice).to_be_visible()

    # Leaving gives back at least 2.5 seconds, however little was left.
    tab.leave_notice()
    tab.run_for(2400)
    expect(tab.notice).to_be_visible()

    tab.focus("[data-workflow-alert-open]")
    tab.run_for(5000)
    expect(tab.notice).to_be_visible()

    tab.focus('textarea[aria-label="Notes"]')
    tab.run_for(2400)
    expect(tab.notice).to_be_visible()
    assert tab.state()["phase"] == "notice"
    tab.run_for(200)
    tab.wait_tucked()
    expect(tab.notes).to_be_focused()


def test_high_and_critical_alerts_stay_until_handled(tab, server, alert, now):
    tab.open(clock=now)
    server.add(alert("high", title="Deploy gate is red"))
    tab.poll()
    expect(tab.notice).to_have_attribute("data-priority", "high")
    tab.run_for(60_000)
    tab.settle()
    expect(tab.notice).to_be_visible()

    # A louder alert takes the notice, and is announced assertively.
    server.add(alert(
        "critical", priority="critical", title="Ledger totals do not match", workflow_name="Payments reconciliation",
    ))
    tab.poll()
    tab.run_for(150)
    expect(tab.notice).to_have_attribute("data-priority", "critical")
    expect(tab.notice).to_have_attribute("data-count", "1")
    expect(tab.notice).to_contain_text("Ledger totals do not match")
    expect(tab.notice.locator("[data-workflow-alert-more]")).to_have_text("+1 more")
    expect(tab.live("assertive")).to_have_text(
        "Critical priority workflow alert: Ledger totals do not match, from Payments reconciliation. 1 more waiting.",
    )

    tab.run_for(60_000)
    tab.settle()
    expect(tab.notice).to_be_visible()
    assert tab.state()["phase"] == "notice"


# Grouping and actions --------------------------------------------------------------------------


def test_an_alert_storm_is_grouped_by_workflow(tab, server, alert, now):
    tab.open()
    storm = [
        alert(
            f"storm-{minutes}", minutes_ago=minutes, workflow_id="wf-storm", workflow_name="Build watcher",
            category="failure", title=f"Build {minutes} failed", error="Exit code 1",
        )
        for minutes in (4, 3, 2, 1)
    ]
    server.add(
        *storm,
        alert("single-medium", minutes_ago=5, priority="medium", title="Two checks are flaky"),
        alert("single-low", minutes_ago=5, priority="low", title="Docs build is slow"),
        alert("single-info", minutes_ago=5, priority="info", title="Weekly digest is ready"),
    )
    tab.poll()

    since = tab.js(
        "(ms) => window.WorkflowAlertHarness.notices.formatWorkflowAlertClock(ms)",
        epoch_ms(now - timedelta(minutes=4)),
    )
    group_text = f"Failed 4 times since {since}"
    expect(tab.notice).to_have_attribute("data-count", "4")
    expect(tab.notice).to_have_attribute("data-category", "failure")
    expect(tab.notice).to_contain_text("Build 1 failed")
    expect(tab.notice.locator("[data-workflow-alert-group]")).to_have_text(group_text)
    expect(tab.notice.locator("[data-workflow-alert-more]")).to_have_text("+3 more")

    tab.open_button.click()
    expect(tab.card).to_be_visible()
    position = tab.card.locator("[data-workflow-alert-position]")
    group = tab.card.locator("[data-workflow-alert-group]")
    expect(position).to_contain_text("1 of 4")
    expect(group).to_have_text(group_text)
    for index, title in ((2, "Two checks are flaky"), (3, "Docs build is slow"), (4, "Weekly digest is ready")):
        tab.card.locator("[data-workflow-alert-next]").click()
        expect(position).to_contain_text(f"{index} of 4")
        expect(tab.card.get_by_role("heading", level=2)).to_have_text(title)
        expect(group).to_have_count(0)
    tab.card.locator("[data-workflow-alert-next]").click()
    expect(position).to_contain_text("1 of 4")
    expect(group).to_have_text(group_text)


def test_card_actions_act_on_every_alert_of_an_entry(tab, server, alert):
    tab.open()
    tab.notes.fill("Keep this")
    server.add(
        alert("a1", minutes_ago=2, workflow_id="wf-1", priority="critical", title="Production deploy blocked"),
        alert("a2", minutes_ago=3, workflow_id="wf-1", title="Canary error rate is up"),
        alert("b1", minutes_ago=2, workflow_id="wf-2", title="Deploy gate is red"),
        alert("c1", minutes_ago=2, workflow_id="wf-3", priority="medium", title="Two checks are flaky"),
        alert("d1", minutes_ago=2, workflow_id="wf-4", priority="low", title="Docs build is slow"),
    )
    tab.poll()
    expect(tab.notice).to_have_attribute("data-count", "2")

    tab.open_button.click()
    card = tab.card
    position = card.locator("[data-workflow-alert-position]")
    expect(card).to_be_visible()
    expect(position).to_contain_text("1 of 4")
    # Open took Mark read's place, and like Dismiss it acts on every alert of the entry.
    expect(card.locator("[data-workflow-alert-mark-read]")).to_have_count(0)
    expect(card.locator("[data-workflow-alert-primary]")).to_have_attribute("title", "Acts on all 2 alerts from this workflow.")
    dismiss = card.locator("[data-workflow-alert-dismiss]")
    expect(dismiss).to_have_attribute("title", "Acts on all 2 alerts from this workflow.")
    dismiss.click()
    tab.wait_for(lambda: sorted(server.dismiss_calls) == ["a1", "a2"], f"Dismiss sent {server.dismiss_calls}.")
    tab.wait_not_busy()
    expect(position).to_contain_text("1 of 3")
    expect(card.get_by_role("heading", level=2)).to_have_text("Deploy gate is red")

    card.locator("[data-workflow-alert-mark-all]").click()
    tab.wait_for(
        lambda: sorted(server.read_calls) == ["b1", "c1", "d1"],
        f"Mark all read sent {server.read_calls}.",
    )
    expect(card).to_have_count(0)
    # Only the alerts the card held, never every notice the reader has.
    assert server.mark_all_calls == 0
    expect(tab.notes).to_be_focused()
    expect(tab.notes).to_have_value("Keep this")
    tab.settle()
    expect(tab.bell).to_have_attribute("data-unread-count", "0")


def test_open_is_the_one_big_action_and_the_rest_waits_under_show_more(tab, server, alert):
    tab.open()
    posted = workflow_alert_conversation_target("conv-wf-1")
    created = workflow_alert_conversation_target("conv-created", label="Open created conversation")
    server.add(
        alert("s1", workflow_id="wf-1", priority="critical", title="Response cell stood up",
              detail="Group, conversation and briefing are ready.",
              enrichments=["Group conversation: Leadership Coordination", "Word file: Initial Briefing.docx"],
              link_targets=[posted, created]),
        alert("s2", minutes_ago=2, workflow_id="wf-1", title="An earlier run", link_targets=[posted]),
    )
    tab.poll()
    tab.open_button.click()
    card = tab.card
    expect(card).to_be_visible()

    # Up front: the reason, the summary, Dismiss, and one Open to what the workflow created.
    primary = card.locator("[data-workflow-alert-primary]")
    expect(primary).to_have_text("Open")
    expect(primary).to_have_accessible_name("Open created conversation")
    expect(primary).to_have_class(re.compile(r"(^|\s)bg-ok-strong(\s|$)"))
    expect(card.locator("[data-workflow-alert-mark-read]")).to_have_count(0)
    expect(card.get_by_role("button")).to_have_count(4)
    for name in ("Close alert", "Show more", "Dismiss", "Open created conversation"):
        expect(card.get_by_role("button", name=name, exact=True)).to_be_visible()
    for waiting in ("[data-workflow-alert-detail]", "[data-workflow-alert-chip]", "[data-workflow-alert-links]"):
        expect(card.locator(waiting).first).to_be_hidden()

    # Show more holds the detail, the pills and every other way in.
    card.locator("[data-workflow-alert-show-more]").click()
    expect(card.locator("[data-workflow-alert-detail]")).to_have_text("Group, conversation and briefing are ready.")
    expect(card.locator("[data-workflow-alert-chip]").filter(has_text="Word file: Initial Briefing.docx")).to_be_visible()
    others = card.locator("[data-workflow-alert-links]")
    expect(others.locator("[data-workflow-alert-link]")).to_have_text(["Open workflow conversation"])
    # The alert names its run, so the route action is Open run, in Open workflow's place.
    expect(others.locator("[data-workflow-alert-open-run]")).to_have_text("Open run")
    expect(others.locator("[data-workflow-alert-open-workflow]")).to_have_count(0)

    # Open settles every alert of the entry and goes to the conversation the workflow created.
    primary.click()
    tab.wait_for(lambda: tab.route_text() == "/chat?conversationId=conv-created", f"Open went to {tab.route_text()}.")
    tab.wait_for(lambda: sorted(server.read_calls) == ["s1", "s2"], f"Open marked {server.read_calls} as read.")
    expect(card).to_have_count(0)


# Keyboard and focus ----------------------------------------------------------------------------


def test_the_notice_and_card_work_from_the_keyboard(tab, server, alert):
    tab.open()
    server.add(alert("kb-1", title="Deploy gate is red"))
    tab.poll()
    expect(tab.notice).to_be_visible()

    # The notice sits in the tab order right after the rail item it hangs from.
    tab.my_workspace.focus()
    tab.page.keyboard.press("Tab")
    expect(tab.open_button).to_be_focused()
    tab.page.keyboard.press("Enter")
    expect(tab.card).to_be_visible()
    tab.wait_for(tab.focus_in_card, "Opening the card did not move focus into it.")
    for _ in range(12):
        tab.page.keyboard.press("Tab")
        assert tab.focus_in_card(), "Tab left the alert card."
    for _ in range(3):
        tab.page.keyboard.press("Shift+Tab")
        assert tab.focus_in_card(), "Shift+Tab left the alert card."

    tab.page.keyboard.press("Escape")
    expect(tab.card).to_have_count(0)
    expect(tab.my_workspace).to_be_focused()
    assert server.find("kb-1")["is_read"] is False
    assert set(tab.claims()) == {"kb-1"}
    expect(tab.notice).to_have_count(0)

    # Escape on the notice tucks it into the bell and leaves the reader where they were.
    server.add(alert("kb-2", title="Canary error rate is up"))
    tab.poll()
    expect(tab.notice).to_contain_text("Canary error rate is up")
    expect(tab.my_workspace).to_be_focused()
    tab.page.keyboard.press("Tab")
    expect(tab.open_button).to_be_focused()
    tab.page.keyboard.press("Escape")
    tab.wait_tucked()
    expect(tab.my_workspace).to_be_focused()
    expect(tab.bell_ring).to_have_count(1)
    assert server.find("kb-2")["is_read"] is False


def test_tabbing_onto_what_the_notice_covers_tucks_it(tab, server, alert):
    tab.open()
    server.add(alert("covering", title="Deploy gate is red"))
    tab.poll()
    expect(tab.notice).to_be_visible()

    tab.my_workspace.focus()
    for _ in range(3):
        tab.page.keyboard.press("Tab")
    group_workspaces = tab.page.get_by_role("link", name="Group Workspaces", exact=True)
    expect(group_workspaces).to_be_focused()
    tab.wait_tucked()
    expect(group_workspaces).to_be_focused()
    assert server.find("covering")["is_read"] is False
    assert tab.state()["ringToken"] == 1


# Motion ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("reduced", [False, True], ids=["full-motion", "reduced-motion"])
def test_motion_uses_transform_and_opacity_and_honours_reduced_motion(tab, server, alert, reduced):
    tab.open(reduced_motion=reduced)
    server.add(alert("m-1", title="Deploy gate is red"))
    tab.poll()
    expect(tab.notice).to_be_visible()
    entrance = "wf-alert-enter-fade" if reduced else "wf-alert-enter-drop"
    expect(tab.notice).to_have_class(re.compile(rf"(^|\s){entrance}(\s|$)"))
    expect(tab.notice.locator(".wf-bell-swing")).to_have_count(0 if reduced else 1)

    # Opening grows the notice into the card.
    tab.open_button.click()
    expect(tab.card).to_be_visible()
    tab.wait_for(lambda: tab.animations("card"), "Opening the card did not animate it.")
    grow = (["opacity"], 160) if reduced else (["opacity", "transform"], 280)
    for item in tab.animations("card"):
        assert (item["properties"], item["duration"]) == grow, item
    tab.page.keyboard.press("Escape")
    expect(tab.card).to_have_count(0)

    # Closing the next one tucks it into the bell.
    server.add(alert("m-2", title="Canary error rate is up"))
    tab.poll()
    expect(tab.notice).to_be_visible()
    tab.close_button.click()
    tab.wait_tucked()
    tuck = (["opacity"], 160, "forwards") if reduced else (["opacity", "transform"], 420, "forwards")
    tucks = [item for item in tab.animations("notice") if item["fill"] == "forwards"]
    assert tucks, tab.animations("notice")
    for item in tucks:
        assert (item["properties"], item["duration"], item["fill"]) == tuck, item
    expect(tab.bell_ring).to_have_count(0 if reduced else 1)
    assert tab.state()["ringToken"] == 1

    keyframes = tab.js(KEYFRAMES)
    assert {"wf-alert-drop", "wf-alert-flyout", "wf-alert-fade", "wf-bell-swing"} <= set(keyframes), keyframes
    for name, properties in keyframes.items():
        assert set(properties) <= {"opacity", "transform", "animation-timing-function"}, (name, properties)


# Layout, theme and contrast --------------------------------------------------------------------


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_the_notice_fits_every_rail_layout_and_theme(tab, server, alert, layout, theme):
    setup = LAYOUTS[layout]
    tab.open(rail_collapsed=setup["rail_collapsed"], viewport=setup["viewport"], theme=theme)
    server.add(alert("placed", title="Deploy gate is red"))
    tab.poll()
    expect(tab.notice).to_be_visible()
    expect(tab.notice).to_have_attribute("data-placement", setup["placement"])
    tab.page.wait_for_timeout(300)

    geometry = tab.notice.evaluate(GEOMETRY)
    assert geometry["nav"] == setup["nav"], geometry
    assert geometry["left"] >= 0 and geometry["top"] >= 0, geometry
    assert geometry["right"] <= geometry["viewportWidth"] and geometry["bottom"] <= geometry["viewportHeight"], geometry
    assert geometry["onTop"], f"Something covers the notice: {geometry}"
    assert geometry["background"] == NOTICE_SURFACE[theme], geometry

    if layout == "phone":
        # The open navigation drawer has the reader's attention; the notice waits behind it.
        tab.page.get_by_role("button", name="Expand navigation", exact=True).click()
        expect(tab.notice).to_be_hidden()
        tab.page.keyboard.press("Escape")
        expect(tab.notice).to_be_visible()
        assert tab.notice.evaluate(GEOMETRY)["onTop"]


@pytest.mark.parametrize("transparency", ["normal", "reduced"], ids=["glass", "reduced-transparency"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_priority_and_category_is_legible(tab, alert, theme, transparency):
    tab.open(theme=theme, reduced_motion=True, reduced_transparency=transparency == "reduced")
    # The alerts below are handed to the store directly, as the lab does.
    tab.js("() => window.WorkflowAlertHarness.runtime.setWorkflowAlertFeedPaused(true)")
    failures = []
    for priority in PRIORITIES:
        for category in CATEGORIES:
            label = f"{theme}/{transparency} {priority}/{category}"
            raw = [
                alert(
                    "lead", minutes_ago=1, workflow_id="wf-lead", priority=priority, category=category,
                    title=f"{priority.capitalize()} {category} needs a look",
                    detail="Step 3 of 5 stopped at the approval gate.",
                    error="Exit code 1" if category == "failure" else "",
                    enrichments=["Owner: Release team"],
                ),
                alert("sibling", minutes_ago=2, workflow_id="wf-lead", priority=priority, category=category,
                      title="An earlier run"),
                alert("filler", minutes_ago=3, priority="info", title="Weekly digest is ready"),
            ]
            tab.js(RECEIVE_DIRECT, raw)
            expect(tab.notice).to_have_attribute("data-priority", priority)
            expect(tab.notice).to_have_attribute("data-category", category)
            tab.page.wait_for_timeout(250)
            measured = tab.contrast(tab.notice)
            assert measured["checked"] and not measured["unparsed"], (label, measured)
            failures += [f"{label} notice: {item}" for item in measured["failures"]]

            tab.js("() => window.WorkflowAlertHarness.stores.workflowAlert.useWorkflowAlertStore.getState().openCard()")
            expect(tab.card).to_be_visible()
            tab.card.locator("[data-workflow-alert-show-more]").click()
            expect(tab.card.locator("[data-workflow-alert-detail]")).to_be_visible()
            tab.page.wait_for_timeout(250)
            measured = tab.contrast(tab.card)
            assert measured["checked"] and not measured["unparsed"], (label, measured)
            failures += [f"{label} card: {item}" for item in measured["failures"]]
            tab.js("() => window.WorkflowAlertHarness.stores.workflowAlert.useWorkflowAlertStore.getState().closeCard()")
            expect(tab.card).to_have_count(0)
    assert not failures, "\n".join(failures)


# Untrusted text and links ----------------------------------------------------------------------


def test_alert_text_is_plain_text_and_links_stay_on_this_site(tab, server, alert):
    tab.open()
    off_site = {"label": "Open report", "link_url": "https://evil.example/report", "link_context": {}}
    server.add(
        alert(
            "x1", workflow_id="wf-nightly", workflow_name=XSS, title=XSS, summary=XSS, detail=f"Detail {XSS}",
            matched_rules=[{
                "rule_id": "rule-x", "rule_name": XSS, "severity": "high",
                "condition_type": "response_contains", "reason": XSS,
            }],
            enrichments=[SHORT_XSS],
            link_targets=[off_site, workflow_alert_conversation_target("conv-wf-nightly")],
        ),
        alert("x2", minutes_ago=2, priority="medium", workflow_id="wf-other", title="Deploy freeze is on",
              trigger_reason="Deploy freeze window is active."),
    )
    tab.poll()

    expect(tab.notice).to_contain_text(XSS)
    tab.open_button.click()
    card = tab.card
    expect(card).to_be_visible()
    card.locator("[data-workflow-alert-show-more]").click()
    expect(card.get_by_role("heading", level=2)).to_have_text(XSS)
    expect(card.locator("[data-workflow-alert-summary]")).to_have_text(XSS)
    expect(card.locator("[data-workflow-alert-detail]")).to_have_text(f"Detail {XSS}")
    expect(card.locator("[data-workflow-alert-rule]")).to_contain_text(XSS)
    expect(card.locator("[data-workflow-alert-chip]").filter(has_text=SHORT_XSS)).to_have_count(1)
    for root in (tab.page.locator("[data-workflow-alert-ui]"),):
        expect(root.locator("img, script, b")).to_have_count(0)
    assert tab.js("() => window.__xss") is None

    # The runner's own log line says nothing the card does not; a reason of its own is shown.
    expect(card.locator("[data-workflow-alert-server-reason]")).to_have_count(0)
    expect(card.locator("[data-workflow-alert-link-note]")).to_have_text(OFF_SITE)
    links = card.locator("[data-workflow-alert-link]")
    expect(links).to_have_count(1)
    # The one link this site can open is the alert's Open button.
    expect(links).to_have_accessible_name("Open workflow conversation")
    card.locator("[data-workflow-alert-next]").click()
    expect(card.locator("[data-workflow-alert-server-reason]")).to_have_text("Deploy freeze window is active.")
    card.locator("[data-workflow-alert-next]").click()
    expect(card.get_by_role("heading", level=2)).to_have_text(XSS)

    links.click()
    tab.wait_for(lambda: tab.route_text() == "/chat?conversationId=conv-wf-nightly", "The link did not open the chat.")
    tab.wait_for(lambda: server.read_calls == ["x1"], f"Opening marked {server.read_calls} as read.")
    expect(card).to_have_count(0)
    assert tab.js("() => window.__xss") is None


def test_open_run_goes_to_the_run_in_its_workspace(tab, server, alert):
    tab.open()

    def open_card(notice_id, **fields):
        server.add(alert(notice_id, **fields))
        tab.poll()
        tab.open_button.click()
        expect(tab.card).to_be_visible()
        # Ask about this needs Use Workflow Results In Chat, which this bootstrap leaves off
        # (ui_tests/test_chat_workflow_results.py).
        expect(tab.card.locator("[data-workflow-alert-follow-up]")).to_have_count(0)
        # Open goes to the conversation; Open run or Open workflow waits under Show more.
        show_more = tab.card.locator("[data-workflow-alert-show-more]")
        if show_more.count():
            show_more.click()
        return tab.card

    # An alert that names its run offers Open run in Open workflow's place, at the same address.
    personal = open_card("o1", workflow_id="wf-nightly", title="Deploy gate is red")
    expect(personal.locator("[data-workflow-alert-open-workflow]")).to_have_count(0)
    open_run = personal.locator("[data-workflow-alert-open-run]")
    expect(open_run).to_have_text("Open run")
    open_run.click()
    tab.wait_for(
        lambda: tab.route_text() == "/workspace/workflows?workflow_id=wf-nightly&run_id=run-1",
        f"Open run went to {tab.route_text()}.",
    )
    expect(tab.page.get_by_text("Your workflows", exact=True)).to_be_visible()
    tab.wait_for(lambda: server.read_calls == ["o1"], f"Opening marked {server.read_calls} as read.")

    group = open_card("o2", workflow_id="wf-team", scope="group", group_id="grp-7", title="Team budget is over")
    group.locator("[data-workflow-alert-open-run]").click()
    tab.wait_for(
        lambda: tab.route_text() == "/groups/grp-7/workflows?workflow_id=wf-team&run_id=run-1",
        f"Open run went to {tab.route_text()}.",
    )
    expect(tab.page.get_by_text("Workflows of group grp-7", exact=True)).to_be_visible()
    tab.wait_for(lambda: server.read_calls == ["o1", "o2"], f"Opening marked {server.read_calls} as read.")

    # An alert without a run keeps Open workflow, which names the workflow alone.
    no_run = open_card("o4", workflow_id="wf-weekly", run_id="", title="Weekly check needs a look")
    expect(no_run.locator("[data-workflow-alert-open-run]")).to_have_count(0)
    open_workflow = no_run.locator("[data-workflow-alert-open-workflow]")
    expect(open_workflow).to_have_text("Open workflow")
    open_workflow.click()
    tab.wait_for(
        lambda: tab.route_text() == "/workspace/workflows?workflow_id=wf-weekly",
        f"Open workflow went to {tab.route_text()}.",
    )
    tab.wait_for(lambda: server.read_calls == ["o1", "o2", "o4"], f"Opening marked {server.read_calls} as read.")

    # An alert that cannot be placed offers no guess at where its workflow lives.
    nowhere = open_card("o3", workflow_id="wf-lost", scope=None, link_targets=[], title="Nobody knows where")
    expect(nowhere.locator("[data-workflow-alert-open-run]")).to_have_count(0)
    expect(nowhere.locator("[data-workflow-alert-open-workflow]")).to_have_count(0)
    expect(tab.card.locator("[data-workflow-alert-links]")).to_have_count(0)
    tab.page.keyboard.press("Escape")
    expect(tab.card).to_have_count(0)
    assert server.read_calls == ["o1", "o2", "o4"]
