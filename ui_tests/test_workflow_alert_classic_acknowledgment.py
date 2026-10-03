# test_workflow_alert_classic_acknowledgment.py
"""
UI test for classic workflow alert acknowledgment.
Version: 0.261.234
Implemented in: 0.261.234

This test runs the real classic workflow alert JavaScript against a minimal
offline page and validates must-acknowledge modal, banner, sizing, sound, and
notification-center behavior.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
BASE_TEMPLATE = APP / "templates" / "base.html"
STATIC = APP / "static"


def _require_playwright():
    return pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")


def _extract_workflow_alert_markup():
    """Extract the production modal and banner markup from base.html."""
    source = BASE_TEMPLATE.read_text(encoding="utf-8")
    start = source.index("  <style>\n    .workflow-alert-modal-dialog")
    end = source.index("  <!-- Split.js -->", start)
    snippet = source[start:end]
    return snippet.replace("  {% endif %}", "")


def _alert(
    alert_id,
    *,
    require_acknowledgment=False,
    sound="off",
    size="small",
    audience="owner",
    priority="high",
    acknowledged=False,
):
    """Build a workflow alert payload used by the offline harness."""
    return {
        "id": alert_id,
        "title": f"{priority.title()} priority workflow alert: {alert_id}",
        "message": f"{alert_id} needs attention.",
        "created_at": "2026-10-03T16:00:00+00:00",
        "priority": priority,
        "category": "alert",
        "delivery": "popup",
        "require_acknowledgment": require_acknowledgment,
        "sound": sound,
        "size": size,
        "audience": audience,
        "acknowledged": acknowledged,
        "acknowledged_at": "2026-10-03T16:10:00+00:00" if acknowledged else None,
        "acknowledged_by_name": "Casey Operator" if acknowledged else None,
        "content_scope": "member" if audience == "group" else "full",
        "link_url": "/chats?conversationId=conversation-1",
        "link_context": {
            "workspace_type": "group" if audience == "group" else "personal",
            "group_id": "group-1" if audience == "group" else "",
            "conversation_id": "conversation-1",
        },
        "metadata": {
            "workflow_name": "Operations Watch",
            "priority": priority,
            "category": "alert",
            "delivery": "popup",
            "require_acknowledgment": require_acknowledgment,
            "sound": sound,
            "size": size,
            "audience": audience,
            "trigger_source": "scheduled",
            "alert_title": f"Alert {alert_id}",
            "alert_summary": f"{alert_id} needs attention.",
            "alert_detail": f"{alert_id} detailed context.",
            "link_targets": [
                {
                    "label": "Open created conversation",
                    "link_url": "/chats?conversationId=conversation-1",
                    "link_context": {
                        "workspace_type": "group" if audience == "group" else "personal",
                        "group_id": "group-1" if audience == "group" else "",
                        "conversation_id": "conversation-1",
                    },
                }
            ],
        },
        "type_config": {"icon": "bi-exclamation-triangle", "color": "danger"},
        "is_read": False,
        "is_dismissed": False,
    }


# The page is served over plain http, where browsers leave navigator.locks out, so each harness
# supplies one. This one grants every request at once.
ALWAYS_GRANTED_LOCKS_STUB = """
            Object.defineProperty(navigator, 'locks', {
                configurable: true,
                value: {
                    request: async (_name, _options, callback) => callback({ name: _name })
                }
            });
"""

# This one behaves as the Web Locks API does: one holder per name, held until the callback's
# promise settles, ifAvailable answered with null while it is held, and other requests queued.
REALISTIC_LOCKS_STUB = """
            (() => {
                const held = new Set();
                const waiting = [];
                window.__heldWorkflowAlertLocks = () => Array.from(held);
                function run(name, callback) {
                    held.add(name);
                    let result;
                    try {
                        result = Promise.resolve(callback({ name }));
                    } catch (error) {
                        result = Promise.reject(error);
                    }
                    const release = () => {
                        held.delete(name);
                        const nextIndex = waiting.findIndex(item => item.name === name);
                        if (nextIndex >= 0) {
                            const next = waiting.splice(nextIndex, 1)[0];
                            run(next.name, next.callback).then(next.resolve, next.reject);
                        }
                    };
                    return result.then(
                        value => { release(); return value; },
                        error => { release(); throw error; }
                    );
                }
                Object.defineProperty(navigator, 'locks', {
                    configurable: true,
                    value: {
                        request(name, optionsOrCallback, maybeCallback) {
                            const callback = typeof optionsOrCallback === 'function' ? optionsOrCallback : maybeCallback;
                            const options = typeof optionsOrCallback === 'function' ? {} : (optionsOrCallback || {});
                            if (held.has(name)) {
                                if (options.ifAvailable) {
                                    return Promise.resolve().then(() => callback(null));
                                }
                                return new Promise((resolve, reject) => waiting.push({ name, callback, resolve, reject }));
                            }
                            return run(name, callback);
                        }
                    }
                });
            })();
"""


class OfflineWorkflowAlertHarness:
    """Serve a minimal SimpleChat page with real static JavaScript."""

    def __init__(
        self,
        page,
        playwright_sync,
        alerts,
        *,
        sounds_enabled=True,
        notification_rows=None,
        use_clock=False,
        reject_play=False,
        complete=True,
        realistic_locks=False,
        sounded_once_ids=(),
    ):
        self.page = page
        self.playwright_sync = playwright_sync
        self.alerts = list(alerts)
        self.sounds_enabled = sounds_enabled
        self.notification_rows = list(notification_rows) if notification_rows is not None else list(alerts)
        self.acknowledged_ids = []
        self.read_ids = []
        self.dismissed_ids = []
        self.use_clock = use_clock
        self.reject_play = reject_play
        self.complete = complete
        self.realistic_locks = realistic_locks
        self.sounded_once_ids = list(sounded_once_ids)
        self.alert_reads = 0
        self.count_override = None
        self.browser = None
        self.context = None

    def __enter__(self):
        playwright = self.playwright_sync.sync_playwright().start()
        self._playwright = playwright
        self.browser = playwright.chromium.launch()
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 820})
        self.page = self.context.new_page()
        if self.use_clock:
            self.page.clock.install()
        self.page.add_init_script(
            """
            window.__workflowAlertPlayed = [];
            window.__workflowAlertStopped = 0;
            window.__rejectWorkflowAlertPlay = REJECT_PLAY;
            LOCKS_STUB
            (() => {
                const soundedOnceIds = SOUNDED_ONCE_IDS;
                if (soundedOnceIds.length) {
                    const soundedAt = Date.now();
                    localStorage.setItem(
                        'simplechat.workflowAlerts.soundedOnce',
                        JSON.stringify(Object.fromEntries(soundedOnceIds.map(id => [id, soundedAt])))
                    );
                }
            })();
            HTMLMediaElement.prototype.play = function() {
                window.__workflowAlertPlayed.push(this.currentSrc || this.src || '');
                if (window.__rejectWorkflowAlertPlay) {
                    return Promise.reject(new DOMException('Autoplay blocked', 'NotAllowedError'));
                }
                return Promise.resolve();
            };
            HTMLMediaElement.prototype.pause = function() {
                window.__workflowAlertStopped += 1;
            };
            window.open = function(url) {
                return {
                    opener: null,
                    location: { href: url || '' },
                    close: function() {}
                };
            };
            """
            .replace("REJECT_PLAY", "true" if self.reject_play else "false")
            .replace("LOCKS_STUB", REALISTIC_LOCKS_STUB if self.realistic_locks else ALWAYS_GRANTED_LOCKS_STUB)
            .replace("SOUNDED_ONCE_IDS", json.dumps(self.sounded_once_ids))
        )
        self.page.route("**/*", self._route)
        self.page.goto("http://simplechat.test/notifications", wait_until="networkidle")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.context.close()
        self.browser.close()
        self._playwright.stop()

    def _html(self):
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <link rel="stylesheet" href="/static/css/bootstrap.min.css" />
</head>
<body>
  <div id="notification-badge"></div>
  <span id="notification-count-badge"></span>
  <div id="sidebar-notification-badge"></div>
  <span id="sidebar-notification-count-badge"></span>
  <main>
    <div id="loading-indicator">Loading...</div>
    <div id="notifications-container"></div>
    <div id="pagination-container"></div>
    <button type="button" id="mark-all-read-btn">Mark all read</button>
    <button type="button" id="refresh-btn">Refresh</button>
    <select id="per-page-select"><option value="20">20</option></select>
    <button type="button" class="filter-btn active" data-filter="all">All</button>
    <input id="search-input" />
  </main>
{_extract_workflow_alert_markup()}
  <script>
    window.appSettings = {{}};
    window.simplechatUserSettings = {{}};
  </script>
  <script src="/static/js/chat/bootstrap.bundle.min.js"></script>
  <script src="/static/js/workflow-alert-sound.js"></script>
  <script src="/static/js/notifications.js"></script>
</body>
</html>"""

    def _static_response(self, route, path):
        static_path = STATIC / path.removeprefix("/static/")
        if not static_path.exists():
            route.fulfill(status=404, body="not found")
            return
        content_type = "text/plain"
        if static_path.suffix == ".js":
            content_type = "application/javascript"
        elif static_path.suffix == ".css":
            content_type = "text/css"
        elif static_path.suffix == ".wav":
            content_type = "audio/wav"
        route.fulfill(status=200, content_type=content_type, body=static_path.read_bytes())

    def _route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        if path == "/notifications":
            route.fulfill(status=200, content_type="text/html", body=self._html())
            return
        if path.startswith("/static/"):
            self._static_response(route, path)
            return
        if path == "/api/notifications/count":
            count = len(self.alerts) if self.count_override is None else self.count_override
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "count": count}),
            )
            return
        if path == "/api/notifications/workflow-alerts":
            self.alert_reads += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "success": True,
                    "notifications": self.alerts,
                    "complete": self.complete,
                    "sounds_enabled": self.sounds_enabled,
                }),
            )
            return
        if path == "/api/notifications":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "success": True,
                    "notifications": self.notification_rows,
                    "total": len(self.notification_rows),
                    "page": 1,
                    "per_page": 20,
                    "has_more": False,
                }),
            )
            return
        acknowledge_match = re.match(r"^/api/notifications/([^/]+)/acknowledge$", path)
        if acknowledge_match:
            notification_id = acknowledge_match.group(1)
            self.acknowledged_ids.append(notification_id)
            self.alerts = [alert for alert in self.alerts if alert["id"] != notification_id]
            self.notification_rows = [
                {**row, "acknowledged": True, "acknowledged_by_name": "Casey Operator", "acknowledged_at": "2026-10-03T16:10:00+00:00"}
                if row["id"] == notification_id else row
                for row in self.notification_rows
            ]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "success": True,
                    "notification_id": notification_id,
                    "acknowledged_at": "2026-10-03T16:10:00+00:00",
                    "acknowledged_by_name": "Casey Operator",
                    "already_acknowledged": False,
                }),
            )
            return
        read_match = re.match(r"^/api/notifications/([^/]+)/read$", path)
        if read_match:
            self.read_ids.append(read_match.group(1))
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True}))
            return
        dismiss_match = re.match(r"^/api/notifications/([^/]+)/dismiss$", path)
        if dismiss_match:
            self.dismissed_ids.append(dismiss_match.group(1))
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True}))
            return
        if path == "/api/groups/setActive":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True}))
            return
        route.fulfill(status=404, body="not found")

    def refresh_alerts(self):
        self.page.evaluate("window.dispatchEvent(new CustomEvent('workflow-alert-refresh-requested'))")


@pytest.mark.ui
def test_must_ack_reappears_after_reload_while_normal_alert_is_suppressed():
    playwright_sync = _require_playwright()
    normal_alert = _alert("normal-once", sound="off")
    must_ack_alert = _alert("must-ack", require_acknowledgment=True, sound="off")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [normal_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        expect(page.locator("#workflowAlertModalLabel")).to_have_text("Alert normal-once")
        page.locator("#workflowAlertModal .btn-close").click()
        expect(page.locator("#workflowAlertModal")).not_to_be_visible()

        harness.alerts = [normal_alert, must_ack_alert]
        page.reload(wait_until="networkidle")

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        expect(page.locator("#workflowAlertModalLabel")).to_have_text("Alert must-ack")
        expect(page.locator("#workflow-alert-acknowledge-btn")).to_be_visible()
        expect(page.locator("#workflow-alert-dismiss-btn")).not_to_be_visible()


@pytest.mark.ui
def test_acknowledge_posts_closes_and_notification_center_exposes_state():
    playwright_sync = _require_playwright()
    must_ack_alert = _alert("ack-action", require_acknowledgment=True, sound="off")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [must_ack_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.locator("#workflow-alert-acknowledge-btn").click()
        expect(page.locator("#workflowAlertModal")).not_to_be_visible()
        assert harness.acknowledged_ids == ["ack-action"]

        page.locator("#refresh-btn").click()
        expect(page.locator(".notification-item")).to_contain_text("Acknowledged by Casey Operator")


@pytest.mark.ui
def test_close_leaves_banner_and_review_reopens_with_size_and_team_line():
    playwright_sync = _require_playwright()
    must_ack_alert = _alert(
        "team-large",
        require_acknowledgment=True,
        sound="off",
        size="large",
        audience="group",
    )

    with OfflineWorkflowAlertHarness(None, playwright_sync, [must_ack_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        expect(page.locator("#workflowAlertModal .modal-dialog")).to_have_class(re.compile(r"modal-fullscreen"))
        expect(page.locator("#workflow-alert-meta")).to_contain_text("Sent to everyone in the group")
        page.locator("#workflowAlertModal .btn-close").click()

        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()
        expect(page.locator("#workflow-alert-ack-banner-count")).to_have_text("1 workflow alert need acknowledgment")
        page.locator("#workflow-alert-ack-banner-review-btn").click()
        expect(page.locator("#workflowAlertModal")).to_be_visible()


@pytest.mark.ui
def test_acknowledged_elsewhere_by_poll_or_broadcast_retires_alert_and_sound():
    playwright_sync = _require_playwright()
    repeating_alert = _alert("shared-ack", require_acknowledgment=True, sound="repeat", priority="critical")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [repeating_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.locator("#workflowAlertModal .btn-close").click()
        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()
        played_before = page.evaluate("window.__workflowAlertPlayed.length")
        assert played_before >= 1

        page.evaluate(
            """
            new BroadcastChannel('simplechat.workflowAlerts').postMessage({
                type: 'acknowledged',
                ids: ['shared-ack']
            });
            """
        )
        expect(page.locator("#workflowAlertAckBanner")).not_to_be_visible()

        harness.alerts = [repeating_alert]
        harness.refresh_alerts()
        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_timeout(250)
        harness.alerts = []
        harness.refresh_alerts()
        page.wait_for_timeout(100)
        expect(page.locator("#workflowAlertModal")).not_to_be_visible()


@pytest.mark.ui
def test_repeat_sound_interval_stops_and_sound_gates_disable_playback():
    playwright_sync = _require_playwright()
    repeating_alert = _alert("repeat-sound", require_acknowledgment=True, sound="repeat", priority="critical")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [repeating_alert], use_clock=True) as harness:
        page = harness.page
        expect = playwright_sync.expect

        page.clock.fast_forward(5100)
        assert page.evaluate("window.__workflowAlertPlayed.length") >= 2
        page.locator("#workflow-alert-acknowledge-btn").click()
        # The modal closes once the acknowledgment has been saved and has retired the alert.
        expect(page.locator("#workflowAlertModal")).not_to_be_visible()
        assert harness.acknowledged_ids == ["repeat-sound"]
        played_after_ack = page.evaluate("window.__workflowAlertPlayed.length")
        page.clock.fast_forward(5100)
        assert page.evaluate("window.__workflowAlertPlayed.length") == played_after_ack

    with OfflineWorkflowAlertHarness(None, playwright_sync, [repeating_alert], sounds_enabled=False) as admin_off:
        assert admin_off.page.evaluate("window.__workflowAlertPlayed.length") == 0

    with OfflineWorkflowAlertHarness(None, playwright_sync, [repeating_alert]) as device_off:
        device_off.page.evaluate("localStorage.setItem('simplechat.workflowAlerts.playSounds', 'false')")
        device_off.page.reload(wait_until="networkidle")
        assert device_off.page.evaluate("window.__workflowAlertPlayed.length") == 0


@pytest.mark.ui
def test_blocked_sound_shows_enable_prompt_and_medium_size_applies():
    playwright_sync = _require_playwright()
    medium_alert = _alert("blocked-medium", require_acknowledgment=True, sound="repeat", size="medium")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [medium_alert], reject_play=True) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        expect(page.locator("#workflowAlertModal .modal-dialog")).to_have_class(re.compile(r"modal-lg"))
        page.locator("#workflowAlertModal .btn-close").click()
        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()
        expect(page.locator("#workflow-alert-enable-sound-btn")).to_be_visible()
        page.evaluate("window.__rejectWorkflowAlertPlay = false")
        page.locator("#workflow-alert-enable-sound-btn").click()
        expect(page.locator("#workflow-alert-enable-sound-btn")).not_to_be_visible()


@pytest.mark.ui
def test_a_closed_alert_stays_in_the_banner_until_review_or_reload():
    playwright_sync = _require_playwright()
    pending_alert = _alert("stays-minimized", require_acknowledgment=True, sound="off")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [pending_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.locator("#workflowAlertModal .btn-close").click()
        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()

        # Later polls still return the alert, but closing it shrank it to the banner on this page.
        for _ in range(2):
            harness.refresh_alerts()
            page.wait_for_timeout(150)
        expect(page.locator("#workflowAlertModal")).not_to_be_visible()
        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()

        page.locator("#workflow-alert-ack-banner-review-btn").click()
        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.locator("#workflowAlertModal .btn-close").click()

        page.reload(wait_until="networkidle")
        expect(page.locator("#workflowAlertModal")).to_be_visible()
        assert harness.acknowledged_ids == []


@pytest.mark.ui
def test_open_modal_offers_enable_sound_while_audio_is_blocked():
    playwright_sync = _require_playwright()
    blocked_alert = _alert("blocked-open", require_acknowledgment=True, sound="repeat")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [blocked_alert], reject_play=True) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        expect(page.locator("#workflow-alert-modal-enable-sound-btn")).to_be_visible()
        page.evaluate("window.__rejectWorkflowAlertPlay = false")
        page.locator("#workflow-alert-modal-enable-sound-btn").click()
        expect(page.locator("#workflow-alert-modal-enable-sound-btn")).not_to_be_visible()
        # Enabling sound retries playback; it never acknowledges or closes the alert.
        expect(page.locator("#workflowAlertModal")).to_be_visible()
        assert harness.acknowledged_ids == []


@pytest.mark.ui
def test_a_capped_read_does_not_retire_a_pending_alert():
    playwright_sync = _require_playwright()
    pending_alert = _alert("capped-pending", require_acknowledgment=True, sound="off")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [pending_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.locator("#workflowAlertModal .btn-close").click()
        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()

        # A full page of newer alerts can leave the pending one out of a capped answer.
        harness.alerts = []
        harness.complete = False
        harness.refresh_alerts()
        page.wait_for_timeout(150)
        expect(page.locator("#workflowAlertAckBanner")).to_be_visible()

        # Only a complete answer without it means someone acknowledged it.
        harness.complete = True
        harness.refresh_alerts()
        expect(page.locator("#workflowAlertAckBanner")).not_to_be_visible()


@pytest.mark.ui
def test_play_once_sounds_once_however_often_the_alert_is_read():
    playwright_sync = _require_playwright()
    once_alert = _alert("once-pending", require_acknowledgment=True, sound="once")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [once_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_function("window.__workflowAlertPlayed.length >= 1")
        for _ in range(3):
            harness.refresh_alerts()
            page.wait_for_timeout(100)

        played = page.evaluate("window.__workflowAlertPlayed.length")
        assert played == 1


@pytest.mark.ui
def test_turning_device_sound_back_on_resumes_a_repeating_alert():
    playwright_sync = _require_playwright()
    repeating_alert = _alert("resume-repeat", require_acknowledgment=True, sound="repeat", priority="critical")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [repeating_alert], use_clock=True) as harness:
        page = harness.page

        page.evaluate("localStorage.setItem('simplechat.workflowAlerts.playSounds', 'false')")
        silenced_at = page.evaluate("window.__workflowAlertPlayed.length")
        page.clock.fast_forward(5100)
        assert page.evaluate("window.__workflowAlertPlayed.length") == silenced_at

        page.evaluate("localStorage.setItem('simplechat.workflowAlerts.playSounds', 'true')")
        page.clock.fast_forward(5100)
        assert page.evaluate("window.__workflowAlertPlayed.length") > silenced_at


@pytest.mark.ui
def test_polls_skip_workflow_alerts_when_nothing_needs_them():
    playwright_sync = _require_playwright()

    with OfflineWorkflowAlertHarness(None, playwright_sync, [], use_clock=True) as harness:
        page = harness.page

        # The first poll after a page load always reads, so a pending alert that was read elsewhere still returns.
        assert harness.alert_reads == 1
        page.clock.fast_forward(45000)
        page.wait_for_timeout(100)
        assert harness.alert_reads == 1

    pending_alert = _alert("tracked-pending", require_acknowledgment=True, sound="off")
    with OfflineWorkflowAlertHarness(None, playwright_sync, [pending_alert], use_clock=True) as tracked:
        page = tracked.page
        reads_after_load = tracked.alert_reads
        # Read elsewhere: the count drops to zero, but the alert still needs acknowledgment.
        tracked.count_override = 0
        page.clock.fast_forward(45000)
        page.wait_for_timeout(100)
        assert tracked.alert_reads > reads_after_load


@pytest.mark.ui
def test_a_refused_repeating_sound_gives_up_the_lock_until_sound_is_allowed():
    playwright_sync = _require_playwright()
    repeating_alert = _alert("refused-lock", require_acknowledgment=True, sound="repeat", priority="critical")

    with OfflineWorkflowAlertHarness(
        None, playwright_sync, [repeating_alert], reject_play=True, realistic_locks=True
    ) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_function("window.__workflowAlertPlayed.length >= 1", timeout=3000)
        # The browser refused, so the lock is free for a tab that may play.
        page.wait_for_function("window.__heldWorkflowAlertLocks().length === 0", timeout=3000)
        enable = page.locator("#workflow-alert-modal-enable-sound-btn")
        expect(enable).to_be_visible()

        # Allowed again, the loop takes the lock back and keeps it while it sounds.
        page.evaluate("window.__rejectWorkflowAlertPlay = false")
        played = page.evaluate("window.__workflowAlertPlayed.length")
        enable.click()
        page.wait_for_function(f"window.__workflowAlertPlayed.length > {played}", timeout=3000)
        page.wait_for_function("window.__heldWorkflowAlertLocks().length === 1", timeout=3000)
        expect(enable).not_to_be_visible()


@pytest.mark.ui
def test_enable_sound_retries_a_refused_one_off_chime_once():
    playwright_sync = _require_playwright()
    once_alert = _alert("refused-once", require_acknowledgment=True, sound="once")

    with OfflineWorkflowAlertHarness(None, playwright_sync, [once_alert], reject_play=True) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_function("window.__workflowAlertPlayed.length === 1", timeout=3000)
        enable = page.locator("#workflow-alert-modal-enable-sound-btn")
        expect(enable).to_be_visible()

        page.evaluate("window.__rejectWorkflowAlertPlay = false")
        enable.click()
        page.wait_for_function("window.__workflowAlertPlayed.length === 2", timeout=3000)
        expect(enable).not_to_be_visible()

        # It played, so later key presses don't play it again, and the browser remembers it.
        page.keyboard.press("Shift")
        page.wait_for_timeout(200)
        assert page.evaluate("window.__workflowAlertPlayed.length") == 2
        sounded = json.loads(page.evaluate("localStorage.getItem('simplechat.workflowAlerts.soundedOnce')"))
        assert "refused-once" in sounded


@pytest.mark.ui
def test_a_chime_another_tab_already_played_is_not_played_again():
    playwright_sync = _require_playwright()
    once_alert = _alert("chimed-elsewhere", require_acknowledgment=True, sound="once")

    with OfflineWorkflowAlertHarness(
        None, playwright_sync, [once_alert], sounded_once_ids=["chimed-elsewhere"]
    ) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_timeout(300)
        assert page.evaluate("window.__workflowAlertPlayed.length") == 0


@pytest.mark.ui
def test_mark_as_read_is_offered_for_an_ordinary_alert_without_links():
    playwright_sync = _require_playwright()
    unlinked_alert = _alert("no-links")
    unlinked_alert["link_url"] = ""
    unlinked_alert["link_context"] = {}
    unlinked_alert["metadata"]["link_targets"] = []

    with OfflineWorkflowAlertHarness(None, playwright_sync, [unlinked_alert]) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        mark_read = page.locator("#workflow-alert-mark-read-btn")
        expect(mark_read).to_be_visible()
        expect(page.locator("#workflow-alert-acknowledge-btn")).not_to_be_visible()
        mark_read.click()
        page.wait_for_function("document.querySelector('#workflowAlertModal').classList.contains('show') === false")
        assert harness.read_ids == ["no-links"]


@pytest.mark.ui
def test_alerts_that_arrive_together_chime_once_in_the_loudest_tone():
    playwright_sync = _require_playwright()
    # Newest first, as the server lists them: the quiet alert would otherwise ask first.
    low_alert = _alert("together-low", require_acknowledgment=True, sound="once", priority="low")
    critical_alert = _alert("together-critical", require_acknowledgment=True, sound="once", priority="critical")

    with OfflineWorkflowAlertHarness(
        None, playwright_sync, [low_alert, critical_alert], realistic_locks=True
    ) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_function("window.__workflowAlertPlayed.length >= 1", timeout=3000)
        page.wait_for_timeout(300)
        played = page.evaluate("window.__workflowAlertPlayed")
        assert len(played) == 1 and played[0].endswith("/alarm.wav"), played
        sounded = json.loads(page.evaluate("localStorage.getItem('simplechat.workflowAlerts.soundedOnce')"))
        assert {"together-low", "together-critical"} <= set(sounded), sounded


@pytest.mark.ui
def test_enable_sound_retries_refused_chimes_as_one_in_the_loudest_tone():
    playwright_sync = _require_playwright()
    low_alert = _alert("refused-low", require_acknowledgment=True, sound="once", priority="low")
    critical_alert = _alert("refused-critical", require_acknowledgment=True, sound="once", priority="critical")

    with OfflineWorkflowAlertHarness(
        None, playwright_sync, [low_alert, critical_alert], reject_play=True, realistic_locks=True
    ) as harness:
        page = harness.page
        expect = playwright_sync.expect

        expect(page.locator("#workflowAlertModal")).to_be_visible()
        page.wait_for_function("window.__workflowAlertPlayed.length >= 1", timeout=3000)
        enable = page.locator("#workflow-alert-modal-enable-sound-btn")
        expect(enable).to_be_visible()

        page.evaluate("window.__rejectWorkflowAlertPlay = false; window.__workflowAlertPlayed = []")
        enable.click()
        page.wait_for_function("window.__workflowAlertPlayed.length >= 1", timeout=3000)
        page.wait_for_timeout(300)
        played = page.evaluate("window.__workflowAlertPlayed")
        assert len(played) == 1 and played[0].endswith("/alarm.wav"), played
        expect(enable).not_to_be_visible()
