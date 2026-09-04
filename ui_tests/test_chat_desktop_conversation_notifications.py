# test_chat_desktop_conversation_notifications.py
"""
UI test for desktop conversation notifications.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures browser permission is requested from a chat interaction and
completed conversations notify only while SimpleChat is hidden or unfocused.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = "ui_tests/fixtures/chat_thought_progress_harness.html"


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _start_static_test_server():
    port = _get_free_local_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.ui
def test_desktop_notification_permission_visibility_and_content():
    """Validate permission, focus gating, content, deduplication, and click behavior."""
    playwright_sync_api = pytest.importorskip("playwright.sync_api")

    with playwright_sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        try:
            with _start_static_test_server() as server_base_url:
                response = page.goto(f"{server_base_url}/{HARNESS_PATH}", wait_until="domcontentloaded")
                assert response is not None and response.ok

                result = page.evaluate(
                    r"""
                    async () => {
                        let visibilityState = 'hidden';
                        let hasFocus = false;
                        let focusCalls = 0;

                        class FakeNotification {
                            static permission = 'default';
                            static nextPermission = 'granted';
                            static requestCount = 0;
                            static instances = [];

                            static async requestPermission() {
                                FakeNotification.requestCount += 1;
                                FakeNotification.permission = FakeNotification.nextPermission;
                                return FakeNotification.permission;
                            }

                            constructor(title, options = {}) {
                                this.title = title;
                                this.options = options;
                                this.listeners = {};
                                this.closed = false;
                                FakeNotification.instances.push(this);
                            }

                            addEventListener(type, listener) {
                                this.listeners[type] = listener;
                            }

                            close() {
                                this.closed = true;
                            }
                        }

                        Object.defineProperty(window, 'Notification', {
                            configurable: true,
                            value: FakeNotification,
                        });
                        Object.defineProperty(document, 'visibilityState', {
                            configurable: true,
                            get: () => visibilityState,
                        });
                        document.hasFocus = () => hasFocus;
                        window.focus = () => {
                            focusCalls += 1;
                        };
                        window.appSettings = {
                            enable_desktop_notifications: true,
                            desktop_notifications_enabled: true,
                            app_title: 'Contoso Chat',
                        };

                        const notifications = await import(
                            '/application/single_app/static/js/chat/chat-desktop-notifications.js'
                        );
                        notifications.resetDesktopNotificationCompletionKeysForTesting();

                        const permission = await notifications.requestDesktopNotificationPermissionIfNeeded();
                        const finalData = {
                            message_id: 'message-1',
                            conversation_id: 'conversation-1',
                            conversation_title: 'Quarterly planning',
                        };

                        const first = notifications.showDesktopConversationNotification(finalData);
                        const duplicate = notifications.showDesktopConversationNotification(finalData);
                        first.listeners.click();

                        visibilityState = 'visible';
                        hasFocus = true;
                        const focused = notifications.showDesktopConversationNotification({
                            message_id: 'message-2',
                            conversation_id: 'conversation-2',
                            conversation_title: 'Focused conversation',
                        });

                        FakeNotification.permission = 'denied';
                        const deniedPermission = await notifications.requestDesktopNotificationPermissionIfNeeded();
                        const denied = notifications.showDesktopConversationNotification({
                            message_id: 'message-3',
                            conversation_id: 'conversation-3',
                            conversation_title: 'Denied conversation',
                        });

                        FakeNotification.permission = 'granted';
                        visibilityState = 'hidden';
                        hasFocus = false;
                        const blocked = notifications.showDesktopConversationNotification({
                            message_id: 'message-4',
                            conversation_id: 'conversation-4',
                            conversation_title: 'Blocked conversation',
                            blocked: true,
                            role: 'safety',
                        });

                        notifications.resetDesktopNotificationCompletionKeysForTesting();
                        FakeNotification.permission = 'default';
                        FakeNotification.nextPermission = 'default';
                        await notifications.requestDesktopNotificationPermissionIfNeeded();
                        await notifications.requestDesktopNotificationPermissionIfNeeded();

                        return {
                            permission,
                            requestCount: FakeNotification.requestCount,
                            notificationCount: FakeNotification.instances.length,
                            firstTitle: first?.title || '',
                            firstBody: first?.options?.body || '',
                            firstTag: first?.options?.tag || '',
                            firstClosed: first?.closed || false,
                            duplicateWasSuppressed: duplicate === null,
                            focusedWasSuppressed: focused === null,
                            deniedPermission,
                            deniedWasSuppressed: denied === null,
                            blockedWasSuppressed: blocked === null,
                            undecidedRequestCount: FakeNotification.requestCount,
                            focusCalls,
                        };
                    }
                    """
                )

            assert result["permission"] == "granted"
            assert result["requestCount"] == 2
            assert result["notificationCount"] == 1
            assert result["firstTitle"] == "Contoso Chat"
            assert result["firstBody"] == "Quarterly planning"
            assert result["firstTag"] == "simplechat-conversation-conversation-1"
            assert result["firstClosed"] is True
            assert result["duplicateWasSuppressed"] is True
            assert result["focusedWasSuppressed"] is True
            assert result["deniedPermission"] == "denied"
            assert result["deniedWasSuppressed"] is True
            assert result["blockedWasSuppressed"] is True
            assert result["undecidedRequestCount"] == 2
            assert result["focusCalls"] == 1
        finally:
            context.close()
            browser.close()
