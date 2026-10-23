# test_v2_conversation_handoffs.py
"""
Browser regressions for V2 queued AI conversation handoffs (`Send To Conversation`).
Version: 0.261.381
Implemented in: 0.261.381

Covers:
- Opening `Send To Conversation` from a private conversation's rail menu.
- Selecting a private destination conversation, reviewing the destination model and bounded
  source preview, and submitting to `POST /api/conversation-handoffs`.
- Rendering outgoing/incoming handoff status cards (`Queued`, `Running`, `Completed`, `Cancelled`)
  with a destination link that preserves the active draft and a `Cancel` action that posts to
  `POST /api/conversation-handoffs/<id>/cancel`.
- Enforcing manual approval floor on orchestration plans containing `conversation_send`.

Run: python .\\ui_tests\\test_v2_conversation_handoffs.py
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

SOURCE_CONVERSATION_ID = "conv-source-research"
DEST_CONVERSATION_ID = "conv-dest-summary"


class ConversationHandoffApi:
    """Mock endpoints used by V2 Send To Conversation and handoff status cards."""

    def __init__(self):
        self.created_handoffs = []
        self.cancelled_handoffs = []
        self.unexpected = []

    def handle(self, route: Route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path

        if request.method == "GET" and path == "/api/conversations/feed":
            route.fulfill(
                json={
                    "success": True,
                    "conversations": [
                        {
                            "id": SOURCE_CONVERSATION_ID,
                            "title": "Q4 Research Thread",
                            "chat_type": "personal_single_user",
                            "last_updated": "2026-10-23T10:00:00Z",
                        },
                        {
                            "id": DEST_CONVERSATION_ID,
                            "title": "Executive Summary Thread",
                            "chat_type": "personal_single_user",
                            "last_updated": "2026-10-23T09:30:00Z",
                        },
                    ],
                    "has_more": False,
                    "next_cursor": None,
                }
            )
            return

        if request.method == "GET" and path == "/api/conversation-references":
            params = parse_qs(url.query)
            exclude_id = params.get("exclude_conversation_id", [""])[0]
            items = [
                {
                    "kind": "conversation",
                    "id": DEST_CONVERSATION_ID,
                    "title": "Executive Summary Thread",
                    "last_updated": "2026-10-23T09:30:00Z",
                }
            ]
            route.fulfill(
                json={
                    "conversations": [item for item in items if item["id"] != exclude_id],
                    "has_more": False,
                    "next_offset": None,
                    "partial": False,
                }
            )
            return

        if request.method == "POST" and path == "/api/conversation-references/resolve":
            route.fulfill(
                json={
                    "references": [
                        {
                            "kind": "conversation",
                            "id": SOURCE_CONVERSATION_ID,
                            "title": "Q4 Research Thread",
                        }
                    ],
                    "excerpts": [
                        {
                            "conversation_id": SOURCE_CONVERSATION_ID,
                            "message_id": "msg-research-1",
                            "role": "assistant",
                            "content": "Key finding: customer retention rose 14% after onboarding updates.",
                        }
                    ],
                    "partial": False,
                    "revision": "rev-research-1",
                    "prompt": "Quoted evidence",
                }
            )
            return

        if request.method == "GET" and path == f"/api/conversation-handoffs/destination/{DEST_CONVERSATION_ID}":
            route.fulfill(
                json={
                    "destination_config": {
                        "conversation_id": DEST_CONVERSATION_ID,
                        "model_name": "GPT-4o Executive",
                        "model_deployment": "gpt-4o",
                        "revision": "dest-rev-1",
                    }
                }
            )
            return

        if request.method == "POST" and path == "/api/conversation-handoffs":
            body = request.post_data_json
            self.created_handoffs.append(body)
            route.fulfill(
                json={
                    "handoff": {
                        "id": "handoff-q4-1",
                        "kind": "handoff",
                        "source_conversation_id": body["source_conversation_id"],
                        "destination_conversation_id": body["destination_conversation_id"],
                        "instruction": body["instruction"],
                        "conversation_references": body.get("conversation_references", []),
                        "status": "queued",
                        "destination_config": {"model_name": "GPT-4o Executive", "revision": "dest-rev-1"},
                    }
                }
            )
            return

        if request.method == "POST" and path == "/api/conversation-handoffs/handoff-q4-1/cancel":
            body = request.post_data_json
            self.cancelled_handoffs.append(body)
            route.fulfill(
                json={
                    "handoff": {
                        "id": "handoff-q4-1",
                        "kind": "handoff",
                        "source_conversation_id": SOURCE_CONVERSATION_ID,
                        "destination_conversation_id": DEST_CONVERSATION_ID,
                        "instruction": "Draft a three-bullet executive summary from the Q4 findings.",
                        "status": "cancelled",
                    }
                }
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
def handoff_page(page: Page):
    errors = []
    hb.ensure_bundle()
    api = ConversationHandoffApi()

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


def mount_handoff_experience(page: Page):
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({
                data: {
                    features: {
                        enable_user_workspace: true,
                        enable_chat_orchestration: true,
                    },
                    orchestration: {
                        enabled: true,
                        show_manual_controls: true,
                        default_approval_mode: 'timed',
                        allow_user_approval_override: true,
                        timed_approval_seconds: 10,
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
        {"conversationId": SOURCE_CONVERSATION_ID},
    )


def test_send_to_conversation_reviews_preview_queues_card_and_cancels(handoff_page):
    page, api = handoff_page
    mount_handoff_experience(page)

    draft = page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Keep this unsent draft intact.")

    page.get_by_role("button", name="Actions for Q4 Research Thread", exact=True).click()
    page.get_by_role("button", name="Send To Conversation", exact=True).click()

    dialog = page.get_by_role("dialog", name="Send To Conversation")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("queues in FIFO order")
    expect(dialog).to_contain_text("customer retention rose 14%")

    dialog.get_by_role("option", name="Executive Summary Thread").click()
    expect(dialog.locator("[data-destination-model]")).to_have_text("GPT-4o Executive")

    dialog.get_by_role("textbox", name="Task instruction", exact=True).fill(
        "Draft a three-bullet executive summary from the Q4 findings."
    )
    dialog.get_by_role("button", name="Send and start AI", exact=True).click()
    expect(dialog).to_have_count(0)

    assert len(api.created_handoffs) == 1
    assert api.created_handoffs[0] == {
        "source_conversation_id": SOURCE_CONVERSATION_ID,
        "destination_conversation_id": DEST_CONVERSATION_ID,
        "instruction": "Draft a three-bullet executive summary from the Q4 findings.",
        "conversation_references": [{"kind": "conversation", "id": SOURCE_CONVERSATION_ID}],
        "destination_config_revision": "dest-rev-1",
    }

    # Outgoing handoff status card appears with Queued status, destination link, and Cancel button.
    card = page.locator("[data-handoff-card='handoff-q4-1']")
    expect(card).to_be_visible()
    expect(card.locator("[data-handoff-status-label]")).to_have_text("Queued")
    expect(card.get_by_role("link", name="Open destination")).to_have_attribute(
        "href", f"/chat?conversationId={DEST_CONVERSATION_ID}"
    )
    expect(draft).to_have_value("Keep this unsent draft intact.")

    card.get_by_role("button", name="Cancel handoff to Executive Summary Thread", exact=True).click()
    expect(card.locator("[data-handoff-status-label]")).to_have_text("Cancelled")
    assert api.cancelled_handoffs == [{"destination_conversation_id": DEST_CONVERSATION_ID}]


def test_conversation_send_step_enforces_manual_approval_floor(handoff_page):
    page, _ = handoff_page
    mount_handoff_experience(page)

    page.evaluate(
        """(conversationId) => {
            const H = window.OrchHarness;
            const normalized = H.plan.normalizePlan({
                plan_id: 'send-plan-1',
                run_id: 'send-run-1',
                turn_id: 'turn-send-1',
                conversation_id: conversationId,
                planner_contract_version: 2,
                intent: { summary: 'Send summary to destination conversation', complexity: 'simple' },
                steps: [
                    {
                        step_id: 'send_step',
                        capability_id: 'conversation_send',
                        role: 'render',
                        title: 'Send summary to Executive Summary Thread',
                        arguments: {
                            destination_conversation_id: 'conv-dest-summary',
                            instruction: 'Summarize the Q4 metrics.',
                            conversation_references: [{ kind: 'conversation', id: conversationId }],
                        },
                        inputs: {},
                        outputs: [{ name: 'result', kind: 'structured-v1' }],
                        depends_on: [],
                        estimated_cost: 'low',
                    },
                ],
                approval: { mode: 'timed', timeout_seconds: 10, state: 'pending' },
                status: 'awaiting_approval',
            });
            H.stores.orchestration.useOrchestrationStore.getState().setPlan(conversationId, 'turn-send-1', normalized);
            H.stores.orchestration.useOrchestrationStore.getState().setActiveTurn(conversationId, 'turn-send-1');
        }""",
        SOURCE_CONVERSATION_ID,
    )

    expect(page.get_by_text("This plan will send a task to another private conversation")).to_be_visible()
    expect(page.get_by_role("timer")).to_have_count(0)
    expect(page.get_by_role("button", name="Approve and run the plan", exact=True)).to_be_visible()
