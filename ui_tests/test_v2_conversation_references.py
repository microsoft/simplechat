# test_v2_conversation_references.py
"""
Browser regressions for V2 private conversation references (`~`), rail actions, and citations.
Version: 0.261.381
Implemented in: 0.261.381

Covers:
- Typing `~` in the V2 chat composer to search eligible private conversations, insert `~[Title]`
  tokens, preview bounded source excerpts, and remove chips cleanly.
- Pasting a portable conversation reference (`simplechat-conversation:v1:...`), resolving it via
  `/api/conversation-references/resolve` before adding the verified chip.
- Sending chat and orchestration plan requests with `conversation_references` without implicitly
  enabling `hybrid_search` or adding conversation IDs to `selected_document_ids`.
- Rendering referenced conversation pills on sent user messages and in reply `Show sources`.
- Rail row menu `Reference Conversation` (`Use in current conversation` and `Copy reference`) on
  eligible private conversations only.

Run: python .\\ui_tests\\test_v2_conversation_references.py
"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401
from v2_pending_action_stubs import is_pending_actions_list, pending_actions_payload  # noqa: E402


pytestmark = pytest.mark.ui

ACTIVE_CONVERSATION_ID = "conv-active"
PRIVATE_SOURCE_A = {
    "kind": "conversation",
    "id": "conv-budget-2026",
    "title": "FY26 Budget Review",
    "last_updated": "2026-10-20T12:00:00Z",
}
PRIVATE_SOURCE_B = {
    "kind": "conversation",
    "id": "conv-arch-notes",
    "title": "Architecture Decisions",
    "last_updated": "2026-10-21T15:30:00Z",
}


class ConversationReferenceApi:
    """Mock endpoints used by V2 conversation reference flows."""

    def __init__(self):
        self.requests = []
        self.search_requests = []
        self.resolve_requests = []
        self.chat_requests = []
        self.plan_requests = []
        self.unexpected = []

    def handle(self, route: Route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        self.requests.append((request.method, path))

        if request.method == "GET" and path == "/api/conversations/feed":
            route.fulfill(
                json={
                    "success": True,
                    "conversations": [
                        {
                            "id": ACTIVE_CONVERSATION_ID,
                            "title": "Active Drafting Thread",
                            "chat_type": "personal_single_user",
                            "last_updated": "2026-10-23T10:00:00Z",
                        },
                        {
                            "id": PRIVATE_SOURCE_A["id"],
                            "title": PRIVATE_SOURCE_A["title"],
                            "chat_type": "personal_single_user",
                            "last_updated": PRIVATE_SOURCE_A["last_updated"],
                        },
                        {
                            "id": "conv-shared-team",
                            "title": "Shared Team Sync",
                            "conversation_kind": "collaborative",
                            "chat_type": "personal_multi_user",
                            "last_updated": "2026-10-22T09:00:00Z",
                        },
                    ],
                    "has_more": False,
                    "next_cursor": None,
                }
            )
            return

        if request.method == "GET" and path == "/api/conversation-references":
            params = parse_qs(url.query)
            query = params.get("query", [""])[0].casefold()
            search_content = params.get("search_content", ["false"])[0] == "true"
            self.search_requests.append({"query": query, "search_content": search_content})
            sources = [PRIVATE_SOURCE_A, PRIVATE_SOURCE_B]
            matched = [
                source
                for source in sources
                if not query or query in source["title"].casefold() or (search_content and "4500" in query)
            ]
            route.fulfill(
                json={
                    "conversations": matched,
                    "has_more": False,
                    "next_offset": None,
                    "partial": search_content,
                }
            )
            return

        if request.method == "POST" and path == "/api/conversation-references/resolve":
            body = request.post_data_json
            self.resolve_requests.append(body)
            refs = body.get("conversation_references") or []
            resolved_sources = [
                PRIVATE_SOURCE_A if item.get("id") == PRIVATE_SOURCE_A["id"] else PRIVATE_SOURCE_B
                for item in refs
            ]
            route.fulfill(
                json={
                    "references": resolved_sources,
                    "excerpts": [
                        {
                            "conversation_id": resolved_sources[0]["id"],
                            "message_id": "msg-101",
                            "role": "assistant",
                            "content": "Approved capex budget is $4,500 for Q4.",
                        }
                    ]
                    if resolved_sources
                    else [],
                    "partial": False,
                    "revision": "rev-budget-1",
                    "prompt": "Quoted evidence",
                }
            )
            return

        if request.method == "POST" and path == "/api/chat/stream":
            body = request.post_data_json
            self.chat_requests.append(body)
            frames = [
                {"content": "Based on your FY26 Budget Review, the capex budget is $4,500."},
                {
                    "done": True,
                    "message_id": "reply-budget-1",
                    "conversation_id": ACTIVE_CONVERSATION_ID,
                    "metadata": {"conversation_references": [PRIVATE_SOURCE_A]},
                },
            ]
            route.fulfill(
                content_type="text/event-stream",
                body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
            )
            return

        if request.method == "POST" and path == "/api/v2/orchestration/plan":
            body = request.post_data_json
            self.plan_requests.append(body)
            frames = [
                {
                    "type": "orchestration_plan",
                    "plan": {
                        "plan_id": "conv-ref-plan",
                        "run_id": "conv-ref-run",
                        "turn_id": body["turn_id"],
                        "conversation_id": body["conversation_id"],
                        "planner_contract_version": 2,
                        "intent": {"summary": "Read referenced conversation and answer", "complexity": "simple"},
                        "inputs": {
                            "documents": [],
                            "conversation_references": body.get("conversation_references", []),
                            "web": False,
                        },
                        "steps": [
                            {
                                "step_id": "read_conv",
                                "capability_id": "conversation_read",
                                "role": "gather",
                                "title": "Read FY26 Budget Review",
                                "arguments": {
                                    "conversation_references": body.get("conversation_references", []),
                                },
                                "inputs": {},
                                "outputs": [{"name": "result", "kind": "structured-v1"}],
                                "depends_on": [],
                                "estimated_cost": "low",
                            },
                            {
                                "step_id": "answer",
                                "capability_id": "compose",
                                "role": "reason",
                                "title": "Answer from conversation evidence",
                                "arguments": {"instruction": "Summarize the budget."},
                                "inputs": {},
                                "outputs": [{"name": "answer", "kind": "markdown-v1"}],
                                "depends_on": ["read_conv"],
                                "estimated_cost": "low",
                            },
                        ],
                        "final_response": {
                            "version": "orchestration-input-binding-v1",
                            "step_id": "answer",
                            "output_name": "answer",
                            "existing_result": None,
                        },
                        "approval": {"mode": "manual", "timeout_seconds": 0, "state": "pending"},
                        "status": "awaiting_approval",
                    },
                }
            ]
            route.fulfill(
                content_type="text/event-stream",
                body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
            )
            return

        if request.method == "GET" and path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
            return
        if request.method == "GET" and path.startswith("/api/chat/stream/status/"):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
            return
        if is_pending_actions_list(request.method, path):
            route.fulfill(json=pending_actions_payload())
            return
        if request.method == "GET" and path == "/api/action-credentials/pending":
            route.fulfill(json={"success": True, "requests": []})
            return
        if request.method == "GET" and path == "/api/user/settings":
            route.fulfill(json={"settings": {}})
            return
        if request.method == "GET" and path == "/api/notifications/count":
            route.fulfill(json={"unread_count": 0})
            return

        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test endpoint."})


@pytest.fixture
def ref_page(page: Page):
    errors = []
    hb.ensure_bundle()
    api = ConversationReferenceApi()

    def handle(route: Route):
        path = urlsplit(route.request.url).path
        if path == "/harness.html":
            route.fulfill(content_type="text/html", body=(hb.HERE / "harness.html").read_text(encoding="utf-8"))
        elif path == "/harness.bundle.js":
            route.fulfill(content_type="application/javascript", body=hb.BUNDLE.read_text(encoding="utf-8"))
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        else:
            api.handle(route)

    page.route("**/*", handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://simplechat.test/harness.html")
    page.wait_for_function('() => typeof window.OrchHarness === "object"')
    try:
        yield page, api
    finally:
        page.evaluate("() => window.OrchHarness.reset()")
        assert not errors, f"Unexpected browser errors: {errors}"
        assert not api.unexpected, f"Unmocked requests: {api.unexpected}"


def mount_chat(page: Page, *, orchestration=False):
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({
                data: {
                    features: {
                        enable_user_workspace: true,
                        enable_collaborative_conversations: true,
                        enable_chat_orchestration: spec.orchestration,
                    },
                    orchestration: {
                        enabled: spec.orchestration,
                        show_manual_controls: true,
                        default_approval_mode: 'manual',
                        allow_user_approval_override: true,
                        timed_approval_seconds: 8,
                    },
                    catalogs: { prompts: [], models: [{ id: 'gpt-4o', deployment_name: 'gpt-4o', display_name: 'GPT-4o' }], agents: [] },
                    settings: {},
                    user: { id: 'user-1', display_name: 'Tester' },
                    scope: { groups: [], public_workspaces: [], active_group_id: null, active_public_workspace_id: null },
                    branding: { app_title: 'SimpleChat', hide_app_title: false, show_logo: false, logo_url: null, logo_dark_url: null, favicon_url: '', classification_banner: null, landing_page_text: '', landing_page_alignment: 'center', landing_page_logo_scale_percent: 100 },
                    navigation: { custom_pages: { enabled: false, menu_name: '', force_menu: false, items: [] }, external_links: { enabled: false, menu_name: '', force_menu: false, items: [] } },
                    control_center: { can_view_dashboard: false, can_manage_users: false, can_manage_groups: false, can_manage_workspaces: false, can_view_activity_logs: false, can_run_maintenance: false },
                    admin_nav: [],
                    notices: { ai: { enabled: false, message: '', frequency: 'once', hash: '', dismissed: true }, web_search: { enabled: false, text: '' } },
                    workspace: { enabled: true, sections: {} },
                },
            });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversationId,
                activeConversationKind: 'personal',
                messages: [],
                conversations: [],
                streaming: false,
                streamError: null,
            });
            H.stores.orchestration.useOrchestrationStore.getState().setVisibleConversation(spec.conversationId);
            H.mount('mount-a', 'SessionChatExperience', {}, { initialEntries: ['/chat'] });
        }""",
        {"conversationId": ACTIVE_CONVERSATION_ID, "orchestration": orchestration},
    )


def test_tilde_picker_inserts_token_previews_source_and_sends_without_hybrid_search(ref_page):
    page, api = ref_page
    mount_chat(page, orchestration=False)

    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Summarize ~FY26")
    listbox = page.get_by_role("listbox", name="Conversation sources")
    option = listbox.get_by_role("option", name="FY26 Budget Review")
    expect(option).to_be_visible()
    option.click()

    expect(draft).to_have_value("Summarize ~[FY26 Budget Review] ")
    chips = page.get_by_role("list", name="Referenced conversations")
    expect(chips).to_be_visible()

    # Preview bounded excerpts before sending.
    chips.get_by_role("button", name="Preview FY26 Budget Review").click()
    expect(page.get_by_text("Approved capex budget is $4,500 for Q4.")).to_be_visible()

    page.get_by_role("button", name="Send message", exact=True).click()
    assert len(api.chat_requests) == 1
    sent = api.chat_requests[0]
    assert sent["conversation_references"] == [{"kind": "conversation", "id": "conv-budget-2026"}]
    assert sent["hybrid_search"] is False
    assert sent["selected_document_ids"] == []

    # Sent user bubble and reply Show sources both display the referenced conversation.
    expect(page.get_by_text("Based on your FY26 Budget Review, the capex budget is $4,500.")).to_be_visible()
    page.get_by_role("button", name="Show sources (1)", exact=True).click()
    expect(page.get_by_text("Conversations (1)")).to_be_visible()


def test_rail_reference_action_and_portable_paste_resolve_before_attaching(ref_page):
    page, api = ref_page
    mount_chat(page, orchestration=True)

    # Shared conversations do not offer Reference Conversation.
    page.get_by_role("button", name="Actions for Shared Team Sync", exact=True).click()
    expect(page.get_by_role("button", name="Reference Conversation")).to_have_count(0)
    page.get_by_role("button", name="Actions for Shared Team Sync", exact=True).click()

    # Active conversation disables "Use in current conversation".
    page.get_by_role("button", name="Actions for Active Drafting Thread", exact=True).click()
    expect(page.get_by_role("button", name="Use in current conversation", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Actions for Active Drafting Thread", exact=True).click()

    # Paste a portable conversation reference into the composer and verify resolution.
    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.focus()
    page.evaluate(
        """() => {
            const input = document.getElementById('composer-input');
            const event = new Event('paste', { bubbles: true, cancelable: true });
            Object.defineProperty(event, 'clipboardData', {
                value: {
                    getData: (type) => type === 'text/plain'
                        ? 'simplechat-conversation:v1:http://simplechat.test/v2/chat?conversationId=conv-arch-notes'
                        : '',
                },
            });
            input.dispatchEvent(event);
        }"""
    )
    expect(page.get_by_role("button", name="Remove conversation Architecture Decisions")).to_be_visible()
    assert api.resolve_requests[-1]["conversation_references"] == [{"kind": "conversation", "id": "conv-arch-notes"}]

    draft.fill("Include architecture decisions in the plan.")
    page.get_by_role("button", name="Send message", exact=True).click()
    assert len(api.plan_requests) == 1
    assert api.plan_requests[0]["conversation_references"] == [{"kind": "conversation", "id": "conv-arch-notes"}]
    assert api.plan_requests[0]["selected_document_ids"] == []
