# action_recovery.py
"""Closed browser fixture for the production classic/V2 action recovery paths.

Version: 0.261.356
Implemented in: 0.261.347
Only synthetic local API traffic is permitted; no model or external write runs.
"""

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from classic_action_credentials import ClassicCredentialFixture
from orchestration import harness_build


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
ORIGIN = "https://simplechat.test"
REQUEST = {
    "message": "Private unsent fixture message", "conversation_id": "conversation-1",
    "agent_info": {"id": "agent-1", "name": "Fixture agent"},
}
RECOVERY = {
    "type": "action_recovery_required", "id": "incident-1", "conversation_id": "conversation-1",
    "agent_name": "Fixture agent", "all_actions_unavailable": True,
    "actions": [{
        "key": "a" * 64, "name": "FED-calendar-" + "long-name-" * 12, "scope": "personal",
        "reason": "This action could not be loaded.", "can_report": True,
        "capabilities": ["create calendar invite"],
        "edit_url": "/v2/workspace/actions/action-1",
    }],
}


class RecoveryFixture(ClassicCredentialFixture):
    def __init__(self, page, flavour):
        super().__init__(page, real_stream=True)
        self.page.route(f"{ORIGIN}/**", self._route)
        self.flavour = flavour
        self.incident = copy.deepcopy(RECOVERY)
        self.health = "failed"
        self.report_status = 200
        self.stream_outcome = "done"
        self.requests = []
        self.unexpected = []
        self.defer_health = False
        self.pending_health = []
        self.defer_stream = False
        self.pending_stream = []
        self.defer_context = False
        self.pending_context = []
        self.defer_creation = False
        self.pending_creation = []
        if flavour == "v2":
            harness_build.ensure_bundle()

    def _route(self, route):
        path = urlsplit(route.request.url).path
        if path.startswith("/api/"):
            self.requests.append({
                "path": path, "method": route.request.method, "headers": route.request.headers,
                "body": json.loads(route.request.post_data) if route.request.post_data else None,
            })
            if path == "/api/action-recovery/context":
                if self.defer_context:
                    self.pending_context.append(route)
                    self.page.evaluate("window.__contextHeld = true")
                    return
                self._json(route, {"csrf_token": "fixture-csrf"})
            elif path == "/api/create_conversation":
                if self.defer_creation:
                    self.pending_creation.append(route)
                    return
                self._json(route, {"conversation_id": "conversation-1"})
            elif path == "/api/conversations/feed":
                self._json(route, {"conversations": [], "has_more": False})
            elif path.endswith("/metadata"):
                self._json(route, {})
            elif path.startswith("/api/chat/stream/cancel/"):
                self._json(route, {"success": True})
            elif path == "/api/chat/action-health":
                if self.defer_health:
                    self.pending_health.append(route)
                    self.page.evaluate("window.__healthHeld = true")
                    return
                self._json(route, self.incident if self.health == "failed" else {"state": "ready"},
                           503 if self.health == "error" else 200)
            elif path == "/api/action-recovery/incident-1":
                recovered = {**self.incident, "actions": [], "ready": True, "all_actions_unavailable": False}
                self._json(route, {"recovery": recovered if self.health == "ready" else self.incident,
                                   "pending_body": REQUEST})
            elif path.endswith("/report"):
                self._json(route, {"reported": True} if self.report_status == 200 else {
                    "error": "PRIVATE-provider-detail",
                }, self.report_status)
            elif path == "/api/action-credentials/pending":
                self._json(route, {"requests": [], "csrf_token": "fixture-csrf"})
            elif path == "/api/chat/stream":
                if self.defer_stream:
                    self.pending_stream.append(route)
                    self.page.evaluate("window.__streamHeld = true")
                    return
                frame = (self.incident if self.stream_outcome == "recovery" else
                         {"done": True, "full_content": "Synthetic response", "message_id": "answer"})
                route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(frame)}\n\n")
            elif path.endswith("/messages") or path == "/api/get_messages":
                self._json(route, {"messages": [
                    {"id": "user-1", "role": "user", "content": REQUEST["message"],
                     "conversation_id": "conversation-1"},
                    {"id": "answer", "role": "assistant", "content": "Synthetic response",
                     "conversation_id": "conversation-1"},
                ]})
            elif path.endswith("/pending-actions") or "/msgraph/pending-actions" in path:
                self._json(route, {"actions": []})
            elif "stream/status" in path:
                self._json(route, {"status": "completed"})
            elif path == "/api/chat/stream/client-event":
                self._json(route, {"success": True})
            else:
                self.unexpected.append(path)
                self._json(route, {"error": "Unexpected fixture API"}, 501)
            return
        if path == "/harness":
            if self.flavour == "v2":
                css = next((APP / "static" / "v2" / "assets").glob("*.css"), None)
                if css is None:
                    raise AssertionError("Run the production V2 build before recovery UI tests.")
                document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="stylesheet" href="/static/v2/assets/{css.name}"></head>
                    <body><button id="fixture-send">Send fixture</button><div id="mount-a"></div>
                    <script src="/ui_tests/fixtures/orchestration/harness.bundle.js"></script></body></html>"""
            else:
                document = """<!doctype html><html lang="en"><head><meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="stylesheet" href="/static/css/bootstrap.min.css"></head>
                    <body><script>window.currentConversationId = 'conversation-1';</script>
                    <button id="fixture-send">Send fixture</button>
                    <select id="agent-select" aria-label="Agent"><option>Fixture agent</option><option>Another agent</option></select>
                    <main id="chatbox"></main><p id="continuation-result"></p>
                    <script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>
                    <script src="/static/js/chat/chat-action-credentials.js"></script>
                    <script type="module">
                        import { sendMessageWithStreaming } from '/static/js/chat/chat-streaming.js';
                        window.__sendOriginal = sendMessageWithStreaming;
                    </script></body></html>"""
            route.fulfill(content_type="text/html", body=document)
            return
        if path == "/ui_tests/fixtures/orchestration/harness.bundle.js":
            route.fulfill(path=str(harness_build.BUNDLE))
            return
        if path.startswith("/static/"):
            if path.endswith("/chat-action-recovery.js"):
                route.fulfill(path=str(APP / "static" / "js" / "chat" / "chat-action-recovery.js"))
                return
            super()._route(route)
            return
        self.unexpected.append(path)
        route.fulfill(status=404)

    def open(self):
        self.page.goto(f"{ORIGIN}/harness")
        if self.flavour == "v2":
            self.page.wait_for_function("typeof window.OrchHarness === 'object'")
            self.page.evaluate("""() => {
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'actor-1'}}});
                H.stores.chat.useChatStore.setState({activeConversationId: 'conversation-1', streaming: false});
                H.mount('mount-a', 'ActionRecoveryNotice', {
                    conversationId: 'conversation-1', hasAgent: true, agentSelection: 'agent-1'
                });
            }""")
            self.page.get_by_role("status").first.wait_for()
        else:
            self.page.wait_for_function("typeof window.__sendOriginal === 'function'")
            self.page.evaluate("window.currentConversationId = 'conversation-1'")
        self.page.evaluate("""request => {
            window.__request = request;
            document.getElementById('fixture-send').onclick = () => {
                if (window.OrchHarness) {
                    window.__sending = window.OrchHarness.chatSse.streamChat(request, {
                        onDone: () => { window.__completed = true; },
                        onError: message => { window.__error = message; }
                    });
                    window.__sending.finally(() => { window.__settled = true; });
                } else {
                    window.__sending = window.__sendOriginal(request, null, request.conversation_id, {
                        onComplete: () => { window.__completed = true; },
                        onError: message => { window.__error = message; },
                        onFinally: () => { window.__settled = true; }
                    });
                }
            };
        }""", REQUEST)

    def change_agent(self):
        if self.flavour == "v2":
            self.page.evaluate("""() => window.OrchHarness.mount('mount-a', 'ActionRecoveryNotice', {
                conversationId: 'conversation-1', hasAgent: true, agentSelection: 'agent-2'
            })""")
            self.page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        else:
            self.page.get_by_role("combobox", name="Agent").select_option(index=1)

    def open_new_chat(self):
        """Observe the real store's first-send ID adoption with a mounted notice."""
        self.open()
        self.page.evaluate("""() => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.stores.chat.useChatStore.setState({
                activeConversationId: null, messages: [], streaming: false
            });
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                user: {id: 'actor-1'},
                catalogs: {agents: [{id: 'agent-1', name: 'Fixture agent'}]}
            }});
            const render = () => H.mount('mount-a', 'ActionRecoveryNotice', {
                conversationId: H.stores.chat.useChatStore.getState().activeConversationId,
                hasAgent: true, agentSelection: 'agent-1'
            });
            window.__unsubscribeRecoveryFixture = H.stores.chat.useChatStore.subscribe(render);
            render();
            document.getElementById('fixture-send').onclick = () => {
                window.__sending = H.stores.chat.useChatStore.getState().sendMessage(
                    window.__request.message, {
                        agentSelection: 'agent-1', contextItems: [],
                        documentSearch: false, webSearch: false, imageGeneration: false,
                        deepResearch: false, urlAccess: false
                    });
                window.__sending.finally(() => { window.__settled = true; });
            };
        }""")
        self.page.get_by_role("status").first.wait_for()

    def change_conversation(self):
        if self.flavour == "v2":
            self.page.evaluate("""() => {
                window.OrchHarness.stores.chat.useChatStore.setState({activeConversationId: 'conversation-2'});
                window.OrchHarness.mount('mount-a', 'ActionRecoveryNotice', {
                    conversationId: 'conversation-2', hasAgent: true, agentSelection: 'agent-1'
                });
            }""")
            self.page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        else:
            self.page.evaluate("""() => {
                window.currentConversationId = 'conversation-2';
                window.dispatchEvent(new Event('chat:conversation-context-changed'));
            }""")

    def release_stream(self):
        route = self.pending_stream.pop()
        route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(self.incident)}\n\n")
        self.page.wait_for_function("window.__settled === true")

    @property
    def sends(self):
        return [item for item in self.requests if item["path"] == "/api/chat/stream"]

    def wait_complete(self):
        self.page.wait_for_function("""() => window.__completed === true
            || document.body.textContent.includes('Synthetic response')
            || window.OrchHarness?.stores.chat.useChatStore.getState().messages.some(
                message => message.content === 'Synthetic response')""")

    def assert_clean(self):
        assert not self.errors, self.errors
        super().assert_clean()
        assert not self.unexpected, self.unexpected
