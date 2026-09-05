# test_foundry_consent_v2.py
"""
Foundry consent errors through the real V2 SSE reader, chat store and MessageList.
Version: 0.261.093
Implemented in: 0.261.093

Deterministic local Playwright tests. HTTP responses are mocked, not stream handlers,
store transitions or the rendered notice. No model, Azure credentials or remote browser
service is required. All runtime assets come from the repository's existing V2 build.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle
from ui_tests.fixtures.orchestration.harness_build import start_static_server


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "ui_tests" / "fixtures" / "foundry_consent"
BUNDLE = FIXTURE / "harness.bundle.js"
AUTH_PATH = "/api/agents/foundry-auth?id=child-1&scope_type=group&scope_id=group-1"
LINK_LABEL = "Sign in or grant Foundry access"


class StreamApi:
    def __init__(self, context):
        self.responses = []
        self.requests = []
        self.hold_retry = False
        self.pending_retry = None
        context.route("**/api/**", self.handle)

    def queue(self, payload, *, status=200, content_type="text/event-stream"):
        self.responses.append((status, content_type, payload))

    def handle(self, route):
        path = urlparse(route.request.url).path
        self.requests.append((route.request.method, path, route.request.url))
        cors_headers = {
            "Access-Control-Allow-Origin": route.request.headers.get("origin", "*"),
            "Access-Control-Allow-Credentials": "true",
        }
        if route.request.method == "OPTIONS":
            route.fulfill(status=204, body="", headers={
                **cors_headers,
                "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
                "Access-Control-Allow-Headers": route.request.headers.get(
                    "access-control-request-headers", "Content-Type",
                ),
            })
            return

        def respond(payload, status=200):
            route.fulfill(status=status, content_type="application/json", body=json.dumps(payload), headers=cors_headers)

        if path == "/api/chat/stream":
            assert self.responses, "Unexpected automatic chat retry"
            status, content_type, payload = self.responses.pop(0)
            body = json.dumps(payload)
            if content_type == "text/event-stream":
                body = (
                    'data: {"type":"user_message_persisted","user_message_id":"user-message"}\n\n'
                    f"data: {body}\n\n"
                )
            route.fulfill(status=status, content_type=content_type, body=body, headers=cors_headers)
        elif path.endswith("/retry"):
            if self.hold_retry:
                self.pending_retry = route
            else:
                self.finish_retry(route)
        elif path == "/api/get_messages":
            respond({"messages": []})
        elif path.endswith("/metadata"):
            respond({})
        elif "/api/chat/stream/status/" in path:
            respond({"pending": False})
        elif path == "/api/agents/foundry-auth":
            route.fulfill(
                content_type="text/html",
                body="<html lang=\"en\"><body>Authenticated consent handoff reached</body></html>",
            )
        else:
            respond({"error": "Unexpected test endpoint"}, 500)

    def finish_retry(self, route=None):
        route = route or self.pending_retry
        assert route is not None
        route.fulfill(
            content_type="application/json",
            body=json.dumps({
                "success": True,
                "chat_request": {"conversation_id": "chat-1", "message": "Delegate a review."},
            }),
        )
        self.pending_retry = None


@pytest.fixture(scope="module")
def harness_url():
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=BUNDLE)
    try:
        with start_static_server() as origin:
            yield origin
    finally:
        BUNDLE.unlink(missing_ok=True)


@pytest.fixture
def ui(page, harness_url):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    api = StreamApi(page.context)
    page.goto(f"{harness_url}/ui_tests/fixtures/foundry_consent/harness.html")
    css = sorted((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
    assert css, "Run npm run build in application/v2_ui before these UI tests."
    page.add_style_tag(url=f"{harness_url}/{css[0].relative_to(ROOT).as_posix()}")
    yield page, api
    assert not errors, errors


def send(page, api, payload=None, **response_options):
    api.queue(payload or {
        "error": "The called Foundry agent needs consent.",
        "auth_required": True,
        "auth_url": AUTH_PATH,
    }, **response_options)
    page.evaluate("window.FoundryConsentHarness.send()")


@pytest.mark.parametrize("absolute_link", [False, True])
def test_separate_api_origin_is_used_for_transport_and_consent(page, tmp_path, absolute_link):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    with start_static_server() as ui_origin, start_static_server() as api_origin:
        bundle = ensure_bundle(
            entry=FIXTURE / "harness_entry.tsx",
            bundle=tmp_path / "api-origin.bundle.js",
            api_base=api_origin,
        )
        page.route(
            "**/ui_tests/fixtures/foundry_consent/harness.bundle.js",
            lambda route: route.fulfill(path=str(bundle), content_type="application/javascript"),
        )
        api = StreamApi(page.context)
        page.goto(f"{ui_origin}/ui_tests/fixtures/foundry_consent/harness.html")
        send(page, api, {
            "error": "Foundry access required.", "auth_required": True,
            "auth_url": f"{api_origin}{AUTH_PATH}" if absolute_link else AUTH_PATH,
        })
        link = page.get_by_role("link", name=LINK_LABEL)
        expect(link).to_have_attribute("href", f"{api_origin}{AUTH_PATH}")
        assert any(
            method == "POST" and url == f"{api_origin}/api/chat/stream"
            for method, _, url in api.requests
        )
        with page.context.expect_page() as opened:
            link.click()
        popup = opened.value
        try:
            popup.wait_for_load_state()
            assert popup.url == f"{api_origin}{AUTH_PATH}"
            expect(popup.get_by_text("Authenticated consent handoff reached")).to_be_visible()
        finally:
            popup.close()
        assert not errors


@pytest.mark.parametrize("status,content_type", [
    (200, "text/event-stream"),
    (403, "text/event-stream"),
    (401, "application/json"),
])
@pytest.mark.parametrize("mobile", [False, True])
def test_consent_error_reaches_real_notice_and_authenticated_handoff(ui, status, content_type, mobile):
    page, api = ui
    page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
    send(page, api, status=status, content_type=content_type)
    notice = page.get_by_role("alert")
    expect(notice).to_contain_text("The called Foundry agent needs consent.")
    expect(notice).to_contain_text("return to this chat and retry your message")
    link = notice.get_by_role("link", name=LINK_LABEL)
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}{AUTH_PATH}")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    assert page.evaluate("window.FoundryConsentHarness.state().authUrl") == link.get_attribute("href")
    assert not any("/status/" in path or "reattach" in path or "foundry-auth" in path for _, path, _ in api.requests)
    link.focus()
    expect(link).to_be_focused()
    with page.expect_popup() as popup_info:
        page.keyboard.press("Enter")
    popup = popup_info.value
    expect(popup.get_by_text("Authenticated consent handoff reached")).to_be_visible()
    popup.close()
    assert sum(path == "/api/chat/stream" for _, path, _ in api.requests) == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "//untrusted.example/authorize",
    "https://untrusted.example/authorize",
    "http://[malformed",
    "",
])
def test_unsafe_consent_urls_never_become_links(ui, url):
    page, api = ui
    send(page, api, {"error": "Consent required.", "auth_required": True, "auth_url": url})
    expect(page.get_by_role("alert")).to_contain_text("Consent required.")
    expect(page.get_by_role("link", name=LINK_LABEL)).to_have_count(0)
    assert page.evaluate("window.FoundryConsentHarness.state().authUrl") is None


def test_consent_alias_fallback_and_explicit_auth_flag(ui):
    page, api = ui
    send(page, api, {
        "auth_required": True,
        "auth_url": "javascript:alert(1)",
        "consent_url": AUTH_PATH,
    })
    expect(page.get_by_role("alert")).to_contain_text("Foundry sign-in or consent is required.")
    expect(page.get_by_role("link", name=LINK_LABEL)).to_be_visible()
    send(page, api, {
        "error": "A different error.",
        "auth_required": False,
        "auth_url": AUTH_PATH,
        "consent_url": AUTH_PATH,
    })
    expect(page.get_by_role("alert")).to_contain_text("A different error.")
    expect(page.get_by_role("link", name=LINK_LABEL)).to_have_count(0)
    assert page.evaluate("window.FoundryConsentHarness.state().authUrl") is None


def test_same_origin_absolute_url_and_credential_url_rejection(ui):
    page, api = ui
    origin = f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}"
    send(page, api, {
        "auth_required": True, "consent_url": f"{origin}{AUTH_PATH}",
    }, status=401, content_type="application/json")
    expect(page.get_by_role("alert")).to_contain_text("Foundry sign-in or consent is required.")
    expect(page.get_by_role("link", name=LINK_LABEL)).to_have_attribute("href", f"{origin}{AUTH_PATH}")
    send(page, api, {
        "error": "Untrusted credential URL.", "auth_required": True,
        "auth_url": f"{urlparse(page.url).scheme}://name:password@{urlparse(page.url).netloc}{AUTH_PATH}",
    })
    expect(page.get_by_role("alert")).to_contain_text("Untrusted credential URL.")
    expect(page.get_by_role("link", name=LINK_LABEL)).to_have_count(0)


@pytest.mark.parametrize("operation", ["reset", "switchChat", "send", "retry"])
def test_consent_link_is_cleared_on_chat_lifecycle_changes(ui, operation):
    page, api = ui
    send(page, api)
    expect(page.get_by_role("link", name=LINK_LABEL)).to_be_visible()
    if operation == "send":
        send(page, api, {"error": "A later ordinary error."})
    elif operation == "retry":
        api.hold_retry = True
        api.queue({"error": "A later ordinary error."})
        with page.expect_request("**/api/message/user-message/retry"):
            page.evaluate("() => { void window.FoundryConsentHarness.retry(); }")
        expect(page.get_by_role("link", name=LINK_LABEL)).to_have_count(0)
        page.wait_for_function("window.FoundryConsentHarness.state().streaming")
        assert page.evaluate("window.FoundryConsentHarness.state().authUrl") is None
        # Finishing this HTTP round trip executes the actual retry -> SSE path.
        api.finish_retry()
        expect(page.get_by_role("alert")).to_contain_text("A later ordinary error.")
    else:
        page.evaluate(f"window.FoundryConsentHarness.{operation}()")
    expect(page.get_by_role("link", name=LINK_LABEL)).to_have_count(0)
    assert page.evaluate("window.FoundryConsentHarness.state().authUrl") is None
