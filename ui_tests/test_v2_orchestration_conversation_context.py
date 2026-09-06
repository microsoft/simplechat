# test_v2_orchestration_conversation_context.py
"""
Browser regressions for orchestration follow-up and clarification transport.
Version: 0.261.099
Implemented in: 0.261.096

Runs the shipped controller, stores, elicitation card, and approval card in the
existing local Playwright harness. HTTP/SSE is stubbed here; the companion
functional tests exercise the actual backend context pipeline.
"""

import sys
import unittest
from pathlib import Path

# The shared browser harness and version helper live outside this test module.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'fixtures' / 'orchestration'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'functional_tests'))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


_START = r"""
async ({ mode, ask, conversationId }) => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.chat.useChatStore.setState({ activeConversationId: conversationId, messages: [] });
    H.stores.orchestration.useOrchestrationStore.setState({ visibleConversationId: conversationId });
    window.contextPlanCalls = [];
    window.contextRunCalls = [];
    const stream = (event) => new Response('data: ' + JSON.stringify(event) + '\n\n', {
        status: 200, headers: { 'Content-Type': 'text/event-stream' },
    });
    window.fetch = async (url, options = {}) => {
        const path = String(url);
        if (path.includes('/api/v2/orchestration/plan')) {
            const body = JSON.parse(options.body);
            window.contextPlanCalls.push(body);
            if (ask && !body.elicitation_response) {
                return stream({
                    type: 'orchestration_elicitation', done: true,
                    elicitation: {
                        elicitation_id: 'question-1', conversation_id: conversationId,
                        turn_id: body.turn_id, revision: body.revision,
                        message: 'Which location do you mean?',
                        requested_schema: {
                            type: 'object', properties: {
                                location: { type: 'string', title: 'Location' },
                            }, required: ['location'],
                        },
                        ui_hints: { pages: [['location']], order: ['location'] },
                    },
                });
            }
            return stream({
                type: 'orchestration_plan', done: true,
                plan: {
                    plan_id: 'plan-' + body.turn_id, run_id: 'run-' + body.turn_id,
                    turn_id: body.turn_id, revision: body.revision,
                    conversation_id: conversationId, user_id: 'test-user',
                    planner_contract_version: 1,
                    intent: { summary: 'Wineries near Grants Pass open Wednesdays', complexity: 'simple' },
                    assumptions: [],
                    steps: [{
                        step_id: 'answer', capability_id: 'respond', title: 'Answer',
                        rationale: '', arguments: {}, depends_on: [],
                        optional: false, enabled: true, estimated_cost: 'low',
                        status: 'pending', phase: 'reasoning',
                    }],
                    approval: {
                        mode, timeout_seconds: 3, state: mode === 'auto' ? 'approved' : 'pending',
                        approved_at: null, approved_by: null, edited: false,
                    },
                    validation: { ok: true, errors: [], repairs: [] },
                    status: mode === 'auto' ? 'approved' : 'awaiting_approval',
                },
            });
        }
        if (path.includes('/api/v2/orchestration/run')) {
            const body = JSON.parse(options.body);
            window.contextRunCalls.push(body);
            return stream({
                done: true, message_id: 'answer-1', conversation_id: conversationId,
                full_content: 'The request concerns wineries near Grants Pass.',
            });
        }
        return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
    };
    await H.controller.startOrchestrationPlan({
        conversationId, message: 'Which are open on Wednesdays?', approvalMode: mode,
        seeds: { selected_document_ids: ['hours-document'] },
    });
    const turnId = window.contextPlanCalls[0].turn_id;
    H.mount('mount-a', ask ? 'ElicitationCard' : 'OrchestrationPlanCard', { conversationId, turnId });
    return turnId;
}
"""


class ConversationTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.errors = []
        cls.browser_context = hb.harness_page(cls.errors)
        cls.page = cls.browser_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.browser_context.__exit__(None, None, None)

    def setUp(self):
        self.errors.clear()

    def tearDown(self):
        self.assertEqual(self.errors, [], f'Browser errors: {self.errors}')

    def start(self, mode='manual', ask=True):
        conversation_id = f'conversation-{self._testMethodName}-{mode}'
        turn_id = self.page.evaluate(_START, {
            'mode': mode, 'ask': ask, 'conversationId': conversation_id,
        })
        return conversation_id, turn_id

    def wait_for_reply(self):
        self.page.wait_for_function('() => window.contextPlanCalls.length === 2')
        return self.page.evaluate('() => window.contextPlanCalls')

    def test_accept_sends_matching_question_answer_and_stable_turn(self):
        conversation_id, turn_id = self.start()
        self.page.get_by_role('textbox', name='Location', exact=True).fill('Grants Pass')
        self.page.get_by_role('button', name='Finish', exact=True).click()
        first, second = self.wait_for_reply()
        self.assertEqual(first['message'], second['message'])
        self.assertEqual(second['conversation_id'], conversation_id)
        self.assertEqual(second['turn_id'], turn_id)
        self.assertEqual(second['revision'], 1)
        self.assertEqual(second['selected_document_ids'], ['hours-document'])
        self.assertEqual(second['elicitation']['elicitation_id'], 'question-1')
        self.assertEqual(second['elicitation']['turn_id'], turn_id)
        self.assertEqual(second['elicitation_id'], 'question-1')
        self.assertEqual(second['elicitation_revision'], 0)
        self.assertTrue(second['elicitation_submission_id'])
        self.assertEqual(second['elicitation_context']['location']['text'], 'Grants Pass')
        self.assertEqual(second['elicitation_response'], {
            'action': 'accept', 'content': {'location': 'Grants Pass'},
        })
        self.assertNotIn('recent_messages', second)
        count = self.page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore
            .getState().messages.filter(message => message.role === 'user').length""")
        self.assertEqual(count, 1)

    def test_decline_carries_question_but_not_unsubmitted_answers(self):
        self.start()
        self.page.get_by_role('textbox', name='Location', exact=True).fill('DO NOT FORWARD')
        self.page.get_by_role('button', name='Decline to answer').click()
        _, second = self.wait_for_reply()
        self.assertEqual(second['elicitation']['elicitation_id'], 'question-1')
        self.assertEqual(second['elicitation_response'], {'action': 'decline', 'content': {}})
        self.assertNotIn('elicitation_context', second)
        self.assertNotIn('DO NOT FORWARD', str(second))

    def test_cancel_does_not_start_another_plan_or_run(self):
        self.start()
        self.page.get_by_role('button', name='Cancel and abandon this request').click()
        self.page.wait_for_function("""() => Object.keys(window.OrchHarness.stores.orchestration
            .useOrchestrationStore.getState().elicitations).length === 0""")
        counts = self.page.evaluate('() => [window.contextPlanCalls.length, window.contextRunCalls.length]')
        self.assertEqual(counts, [1, 0])

    def test_all_approval_modes_run_the_server_plan_without_uploading_history(self):
        for mode in ('auto', 'timed', 'manual'):
            with self.subTest(mode=mode):
                conversation_id, turn_id = self.start(mode=mode, ask=False)
                if mode == 'manual':
                    self.page.get_by_role('button', name='Approve and run the plan').click()
                self.page.wait_for_function(
                    """(conversationId) => (window.OrchHarness.stores.orchestration
                        .useOrchestrationStore.getState().history[conversationId] || [])
                        .some(run => run.status === 'completed')""",
                    arg=conversation_id, timeout=10000,
                )
                plans, runs = self.page.evaluate('() => [window.contextPlanCalls, window.contextRunCalls]')
                self.assertEqual(len(plans), 1)
                self.assertEqual(plans[0]['message'], 'Which are open on Wednesdays?')
                self.assertNotIn('recent_messages', plans[0])
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]['conversation_id'], conversation_id)
                self.assertEqual(runs[0]['run_id'], f'run-{turn_id}')
                self.assertNotIn('message', runs[0])
                self.assertNotIn('recent_messages', runs[0])

    def test_navigation_does_not_retarget_a_pending_plan(self):
        conversation_id, turn_id = self.start(ask=False)
        self.page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState({
            activeConversationId: 'another-conversation', messages: [],
        })""")
        self.page.get_by_role('button', name='Approve and run the plan').click()
        self.page.wait_for_function('() => window.contextRunCalls.length === 1')
        run = self.page.evaluate('() => window.contextRunCalls[0]')
        self.assertEqual(run['conversation_id'], conversation_id)
        self.assertEqual(run['run_id'], f'run-{turn_id}')
        self.assertEqual(self.page.evaluate(
            '() => window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId'
        ), 'another-conversation')


if __name__ == '__main__':
    assert_app_version_at_least('0.261.096')
    unittest.main()
