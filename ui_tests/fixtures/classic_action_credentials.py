# classic_action_credentials.py
"""
Real classic credential card and action stepper browser harness.
Version: 0.261.333
Implemented in: 0.261.333

All assets are the application's local files. Playwright interception works with
the configured local or Azure browser; no app/Azure data services are needed.
"""

import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from agent_delegation_classic.harness import build_plugin_modal_page, read_partial
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
ORIGIN = "http://simplechat.test"


def credential_request(slots=None, status="pending"):
    return {
        "id": "request-1",
        "etag": '"revision-1"',
        "conversation_id": "conversation-1",
        "action_name": "Mission telemetry",
        "destination_label": "Mission simulator",
        "reason": "setup_required",
        "requirements": slots or [{"slot": "proxy", "auth_type": "username_password", "label": "Proxy sign-in"}],
        "identities": [
            {"id": "user-pass", "name": "My proxy identity", "auth_type": "username_password", "etag": '"identity-1"'},
            {"id": "user-key", "name": "My service identity", "auth_type": "api_key"},
        ],
        "status": status,
    }


class ClassicCredentialFixture:
    def __init__(self, page, modal=False, real_stream=False):
        self.page = page
        self.modal = modal
        self.real_stream = real_stream
        self.current = credential_request()
        self.posts = []
        self.errors = []
        self.submit_status = 200
        self.continue_status = 200
        self.get_status = 200
        self.page.on("pageerror", lambda error: self.errors.append(error.stack or str(error)))
        self.page.route(f"{ORIGIN}/**", self._route)

    def _json(self, route, value, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(value))

    def _route(self, route):
        path = urlsplit(route.request.url).path
        if path.startswith("/api/action-credentials"):
            if route.request.method == "GET":
                value = {"requests": [self.current]} if path.endswith("/pending") else {"credential_request": self.current}
                self._json(route, {**value, "csrf_token": "fixture-csrf-token"}, self.get_status)
                return
            payload = json.loads(route.request.post_data)
            self.posts.append({"path": path, "body": payload, "headers": route.request.headers})
            if path.endswith("/submit"):
                if self.submit_status != 200:
                    self._json(route, {"error": "SECRET-provider-stack-must-not-render"}, self.submit_status)
                    return
                self.current = {**self.current, "etag": '"revision-2"', "status": "ready"}
                self._json(route, {"credential_request": self.current, "status": "ready"})
            elif path.endswith("/continue"):
                if self.continue_status != 200:
                    self._json(route, {"error": "SECRET-provider-stack-must-not-render"}, self.continue_status)
                else:
                    self.current = {**self.current, "status": "completed", "etag": '"revision-3"'}
                    route.fulfill(
                        content_type="text/event-stream",
                        body='data: {"done": true, "full_content": "Blocked read resumed"}\n\n',
                    )
            else:
                self.current = {**self.current, "status": "cancelled", "etag": '"revision-3"'}
                self._json(route, {"credential_request": self.current})
            return
        if path.startswith("/api/"):
            if path == "/api/chat/stream" and self.real_stream:
                self.posts.append({"path": path, "body": json.loads(route.request.post_data)})
                route.fulfill(
                    content_type="text/event-stream",
                    body=f"event: action_credentials_required\ndata: {json.dumps({'credential_request': self.current})}\n\n",
                )
                return
            if path.endswith("/plugins/types"):
                self._json(route, [{"type": "yamcs", "display": "Yamcs", "description": "Read mission telemetry."}])
            elif path.endswith("/identities"):
                self._json(route, {"identities": [{
                    "id": "shared-identity", "name": "Shared action identity",
                    "usage_contexts": ["action"], "supported_source_types": ["action"],
                    "credentials": {"auth_type": "api_key", "secret_stored": True},
                }]})
            elif path.endswith("/preconfigurations"):
                self._json(route, {"preconfigurations": []})
            else:
                self._json(route, {})
            return
        if path.startswith("/static/") or path.startswith("/application/single_app/static/"):
            relative = path.split("/static/", 1)[1]
            asset = APP / "static" / relative
            if self.real_stream and relative.startswith("js/chat/") and relative not in {
                "js/chat/chat-action-credentials.js", "js/chat/chat-streaming.js",
                "js/chat/chat-action-recovery.js",
            }:
                source = (APP / "static" / "js" / "chat" / "chat-streaming.js").read_text(encoding="utf-8")
                exports = []
                for symbols, module in re.findall(r"import\s*\{([^}]+)\}\s*from\s*'([^']+)'", source):
                    if module.removeprefix("./") == asset.name:
                        exports.extend(symbol.strip() for symbol in symbols.split(",") if symbol.strip())
                shell = "\n".join(f"export function {symbol}() {{ return Promise.resolve(); }}" for symbol in exports)
                if asset.name == "chat-messages.js":
                    shell = shell.replace(
                        "export function appendMessage() { return Promise.resolve(); }",
                        """export function appendMessage(sender, text, model, id) {
                            const message = document.createElement('article');
                            message.dataset.messageId = id || 'resumed-result';
                            message.textContent = text;
                            document.getElementById('chatbox').appendChild(message);
                        }""",
                    )
                if asset.name == "chat-reasoning.js":
                    shell = shell.replace(
                        "export function getMessageReasoningAdjustments() { return Promise.resolve(); }",
                        "export function getMessageReasoningAdjustments() { return []; }",
                    )
                if asset.name == "chat-analysis-results.js":
                    shell = shell.replace(
                        "export function getAnalysisContextRevision() { return Promise.resolve(); }",
                        "export function getAnalysisContextRevision() { return 0; }",
                    )
                route.fulfill(content_type="text/javascript", body=shell)
                return
            if asset.is_file():
                route.fulfill(path=str(asset))
            else:
                route.fulfill(status=404)
            return
        if path == "/harness":
            if self.modal:
                document = build_plugin_modal_page(read_partial("_plugin_modal.html"))
            else:
                document = """<!doctype html><html lang="en"><head><meta charset="utf-8">
                    <link rel="stylesheet" href="/static/css/bootstrap.min.css"></head><body>
                    <main id="chatbox"></main><p id="continuation-result"></p>
                    <script src="/static/js/chat/chat-action-credentials.js"></script></body></html>"""
                if self.real_stream:
                    document = document.replace("</body>", """<script type="module">
                        import { sendMessageWithStreaming } from '/static/js/chat/chat-streaming.js';
                        window.__sendOriginal = sendMessageWithStreaming;
                    </script></body>""")
            route.fulfill(content_type="text/html", body=document)
            return
        route.fulfill(status=404)

    def open(self):
        self.page.goto(f"{ORIGIN}/harness")
        if self.modal:
            self.page.wait_for_function("window.__pluginModalHarnessReady === true")
        else:
            if self.real_stream:
                self.page.wait_for_function("typeof window.__sendOriginal === 'function'")
                self.page.evaluate("window.currentConversationId = 'conversation-1'")
                return
            self.page.evaluate("""() => {
                window.currentConversationId = 'conversation-1';
                window.SimpleChatActionCredentials.setContinuationConsumer(async (factory, id) => {
                    const response = await factory(new AbortController().signal);
                    const text = await response.text();
                    window.__continuedConversation = id;
                    document.getElementById('continuation-result').textContent =
                        text.includes('Blocked read resumed') ? 'Blocked read resumed' : 'Unexpected response';
                });
                return window.SimpleChatActionCredentials.refreshConversation('conversation-1');
            }""")

    def show_action(self, scope="personal", manifest=None):
        if self.page.locator("#plugin-modal").is_visible():
            self.page.evaluate("bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide()")
            expect(self.page.locator("#plugin-modal")).to_be_hidden()
        manifest = manifest or {
            "id": "yamcs-1", "name": "mission_telemetry", "displayName": "Mission telemetry",
            "type": "yamcs", "endpoint": "https://yamcs.example.test",
            "auth": {"type": "key", "key": ""},
            "additionalFields": {"instance": "simulator", "auth_method": "api_key"},
        }
        self.page.evaluate("""async ({ scope, manifest }) => {
            const stepper = window.pluginModalStepper;
            stepper.actionIdentityScope = {
                scope, apiBase: scope === 'group' ? '/api/workspace-identities/group/group-1'
                    : '/api/workspace-identities/' + scope
            };
            await stepper.showModal(manifest);
            stepper.goToStep(3);
        }""", {"scope": scope, "manifest": copy.deepcopy(manifest)})
        expect(self.page.locator("#plugin-modal")).to_be_visible()

    def form_data(self):
        return self.page.evaluate("window.pluginModalStepper.getFormData()")

    def assert_clean(self):
        assert self.errors == []
