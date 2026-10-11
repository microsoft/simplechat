# test_v2_m365_review_placement.py
"""Real planning-to-review placement with distinct optimistic and saved IDs.

Version: 0.261.325
Implemented in: 0.261.325
Runs desktop/mobile with mocked HTTP; no mailbox or cloud mutations.
"""

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.fixtures.orchestration import harness_build
from ui_tests.test_v2_m365_pending_action_cards import (
    CONVERSATION_ID, USER_TEXT, _collect_page_errors, _open_chat,
    _posts_to_actions, _require_bundle, pending_action,
)


pytestmark = pytest.mark.ui


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
@pytest.mark.parametrize("report_status", ["completed", "failed"])
def test_list_first_review_keeps_its_request_anchor_and_dom_identity(page, viewport, report_status):
    _require_bundle()
    errors = _collect_page_errors(page)
    page.set_viewport_size(viewport)
    saved_id = "user_orchestration_saved-real-plan"
    action = pending_action(
        "placement-action", action_mode="manual", producing_user_message_id=saved_id,
        orchestration_run_id="placement-run", summary={
            "subject": "Quarterly numbers", "body_preview": "Hello Ann",
            "body_preview_truncated": False, "to_recipients": ["ann@example.com"],
        },
    )
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=[], by_id=[action])
        page.evaluate("""({savedId, message}) => {
            const H = window.OrchHarness;
            const previousFetch = window.fetch;
            window.fetch = async (url, init = {}) => {
                const path = new URL(String(url), location.origin).pathname;
                if (path !== '/api/v2/orchestration/plan') return previousFetch(url, init);
                const request = JSON.parse(init.body);
                window.optimisticUserId = H.stores.chat.useChatStore.getState().messages[0].id;
                window.placementTurnId = request.turn_id;
                const plan = {
                    plan_id: 'placement-plan', run_id: 'placement-run', turn_id: request.turn_id,
                    conversation_id: 'conversation-m365', planner_contract_version: 2,
                    intent: {summary: 'Prepare email', complexity: 'simple'},
                    steps: [{step_id: 'draft', capability_id: 'compose', title: 'Prepare email',
                        arguments: {}, role: 'reason', estimated_cost: 'low'}],
                    assumptions: [], status: 'awaiting_approval', approval: {mode: 'manual', state: 'pending'},
                    validation: {valid: true, errors: [], warnings: [], repairs: []},
                };
                const frame = {type: 'orchestration_plan', done: true, plan, turn_identity: {
                    conversation_id: plan.conversation_id, run_id: plan.run_id,
                    turn_id: plan.turn_id, user_message_id: savedId,
                }};
                return new Response(`data: ${JSON.stringify(frame)}\\n\\n`,
                    {headers: {'Content-Type': 'text/event-stream'}});
            };
            return H.controller.startOrchestrationPlan({
                conversationId: 'conversation-m365', message, approvalMode: 'manual', seeds: {},
            });
        }""", {"savedId": saved_id, "message": USER_TEXT})
        assert page.evaluate("() => window.optimisticUserId") != saved_id
        user = root.locator(f'[id="message-{saved_id}"]')
        expect(user).to_have_count(1)
        page.evaluate("""(action) => {
            window.listedActions = [action];
            return window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().refreshList();
        }""", action)
        card = user.get_by_test_id("v2-pending-action-card")
        expect(card).to_have_count(1)
        expect(root.get_by_test_id("v2-pending-actions-section")).to_have_count(0)
        # Keep the actual DOM node: a final assistant reference must not remount it.
        card.evaluate("(node) => window.originalReviewNode = node")
        page.evaluate("""() => {
            void window.OrchHarness.controller.approveAndRunPlan({
                conversationId: 'conversation-m365', turnId: window.placementTurnId,
            });
        }""")
        page.wait_for_function("() => typeof window.pushChatFrame === 'function'")
        page.evaluate("""({action, savedId}) => window.pushChatFrame({
            type: 'm365_pending_action', conversation_id: 'conversation-m365', run_id: 'placement-run',
            step_id: 'draft', user_message_id: savedId, pending_action: action,
        })""", {"action": action, "savedId": saved_id})
        page.evaluate("""({action, savedId, status}) => {
            window.pushChatFrame({
                type: 'orchestration_done', done: true, conversation_id: 'conversation-m365',
                run_id: 'placement-run', turn_id: window.placementTurnId, user_message_id: savedId,
                message_id: 'placement-answer', status, outcome: status, message_saved: true,
                full_content: 'Prepared for review. Check the action card for its current status.',
                metadata: {m365_pending_action_ids: [action.id]}, m365_pending_actions: [action],
            });
            window.closeChatFrames();
        }""", {"action": action, "savedId": saved_id, "status": report_status})
        expect(root.locator('[id="message-placement-answer"]')).to_have_count(1)
        expect(card).to_have_count(1)
        assert card.evaluate("(node) => node === window.originalReviewNode")
        assert not _posts_to_actions(page)
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    assert errors == []
