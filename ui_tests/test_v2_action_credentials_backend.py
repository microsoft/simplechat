# test_v2_action_credentials_backend.py
"""Real React Save and continue through Flask and freshly constructed SK agents.

Version: 0.261.348
Implemented in: 0.261.345

Only Cosmos and external model/provider transport are offline. Browser fetch is
not replaced: credential and message requests execute the actual Flask routes.
The shared connection fixture supports local and Azure Playwright browsers.
"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from queue import Queue
import sys
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "functional_tests"), str(ROOT / "ui_tests" / "fixtures"),
               str(ROOT / "ui_tests" / "fixtures" / "orchestration")]

# Shared test infrastructure lives outside the UI test module directory.
import harness_build as hb
import playwright_connection
from test_action_credentials_chat_reconstruction import PROBE
from test_orchestration_result_imports import run_probe

connect_options = playwright_connection.connect_options


@contextmanager
def credential_browser(options):
    """Open browser/driver before blocking application sockets in the backend probe."""
    bundle = hb.ensure_bundle()
    errors, requests, replies = [], [], {}
    origin = "https://simplechat.test"
    with sync_playwright() as playwright, ThreadPoolExecutor(max_workers=1) as backend:
        browser = playwright.chromium.connect(**options) if options else playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        assets = {
            "/" + hb.HARNESS_HTML_REL: hb.HERE / "harness.html",
            "/ui_tests/fixtures/orchestration/harness.bundle.js": bundle,
        }

        def assets_only(route):
            path = urlsplit(route.request.url).path
            if path in assets:
                route.fulfill(path=str(assets[path]))
            elif path == "/favicon.ico":
                route.fulfill(status=204)
            else:
                errors.append(f"Unexpected browser request: {path}")
                route.abort()

        page.route("**/*", assets_only)
        page.goto(origin + "/" + hb.HARNESS_HTML_REL)
        page.wait_for_function("() => Boolean(window.OrchHarness)")

        def exercise(client, pending, user_message):
            def forward(route):
                request = route.request
                url = urlsplit(request.url)
                if not (url.path.startswith("/api/action-credentials/") or url.path in {
                    "/api/get_messages", "/api/msgraph/pending-actions",
                    "/api/collaboration/conversations/visible-chat/messages",
                }):
                    errors.append(f"Unexpected application request: {url.path}")
                    route.abort()
                    return
                response = backend.submit(client.open,
                    url.path + (f"?{url.query}" if url.query else ""),
                    method=request.method, data=request.post_data,
                    content_type=request.headers.get("content-type"),
                    headers={"X-CSRFToken": request.headers.get("x-csrftoken", "")}, buffered=True,
                ).result(timeout=60)
                requests.append(url.path)
                if url.path.endswith("/submit"):
                    replies["ready"] = response.json["credential_request"]
                if url.path.endswith("/continue"):
                    replies["continued"] = response
                # The local actor has no Microsoft 365 tenant session.
                graph_signed_out = url.path == "/api/msgraph/pending-actions" and response.status_code == 401
                if response.status_code >= 400 and not graph_signed_out:
                    errors.append(f"Flask rejected {url.path}: {response.status_code}")
                route.fulfill(status=response.status_code, content_type=response.content_type,
                              body=response.get_data())

            page.route("**/api/**", forward)
            page.evaluate("""({pending, userMessage}) => {
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'owner'}}});
                H.stores.chat.useChatStore.setState({
                    activeConversationId: pending.conversation_id, messages: [userMessage],
                    activeConversationKind: pending.conversation_kind || 'personal',
                });
                H.mount('mount-a', 'CredentialRequestCards', {
                    conversationId: pending.conversation_id, conversationKind: pending.conversation_kind || 'personal',
                });
            }""", {"pending": pending, "userMessage": user_message})
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Username", exact=True).fill("private-user-sentinel")
            card.get_by_label("Password", exact=True).fill("private-password-sentinel")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            page.wait_for_function("""() => {
                const state = window.OrchHarness.stores.chat.useChatStore.getState();
                return !state.streaming && state.messages.some(message =>
                    message.role === 'assistant' && message.content === 'sim is RUNNING.');
            }""")
            page.wait_for_function("() => document.querySelectorAll('input[type=password]').length === 0")
            snapshot = page.evaluate("""() => ({
                state: window.OrchHarness.stores.chat.useChatStore.getState(),
                local: {...localStorage}, session: {...sessionStorage},
            })""")
            assert snapshot["state"]["activeConversationId"] == pending["conversation_id"]
            assert sum(message["role"] == "user" for message in snapshot["state"]["messages"]) == 1
            assert "private-password-sentinel" not in json.dumps(snapshot)
            assert "private-user-sentinel" not in json.dumps(snapshot)
            assert requests.count(f"/api/action-credentials/{pending['id']}/submit") == 1
            assert requests.count(f"/api/action-credentials/{pending['id']}/continue") == 1
            assert not errors, errors
            return replies["continued"], replies["ready"]

        try:
            yield exercise
        finally:
            context.close()
            browser.close()


@pytest.mark.ui
@pytest.mark.parametrize("shared_kind", [None, "personal", "group"])
def test_save_continue_executes_tool_and_displays_same_conversation_answer(connect_options, monkeypatch, shared_kind):
    # Run cold, real app imports without polluting other UI suites' module state.
    monkeypatch.setenv("SIMPLECHAT_CREDENTIAL_BROWSER_OPTIONS", json.dumps(connect_options))
    prefix = """
import json
import os
import sys
sys.path[:0] = sys.argv[1:3]
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[2]).parent / "ui_tests"))
from test_v2_action_credentials_backend import run_browser_probe
run_browser_probe(json.loads(os.environ.pop("SIMPLECHAT_CREDENTIAL_BROWSER_OPTIONS")))
"""
    scenario = {"shared": shared_kind, "scope": "personal", "participant": True} if shared_kind else {}
    run_probe(prefix, (json.dumps(scenario),), False)


def run_browser_probe(options):
    """Keep Playwright's loop and the real application's loop on separate threads."""
    requests, responses = Queue(), Queue()

    @contextmanager
    def bridge():
        def transport(*args):
            requests.put(args)
            result = responses.get(timeout=90)
            if isinstance(result, Exception):
                raise result
            return result
        yield transport

    with credential_browser(options) as exercise, ThreadPoolExecutor(max_workers=1) as backend:
        future = backend.submit(exec, PROBE, {"credential_ui_context": bridge})
        future.add_done_callback(lambda result: requests.put(None))
        inputs = requests.get(timeout=90)
        if inputs is None:
            future.result()
            raise AssertionError("Backend ended before credential entry.")
        try:
            result = exercise(*inputs)
        except Exception as error:
            responses.put(error)
            raise
        responses.put(result)
        future.result(timeout=90)
