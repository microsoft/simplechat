# test_orchestration_plan_revision_planner.py
"""
Functional tests for the plan editor's strict planner contract.
Version: 0.261.103
Implemented in: 0.261.102
Authorized model routing through editor replanning: 0.261.103

An edit must produce a validated revision, a scoped explanation, or a question.
It must never replace the existing plan with the initial planner's failure fallback.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_orchestration_conversation_context import load_modules


class PlanRevisionPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = load_modules().planner

    def setUp(self):
        self.context = {
            'message': 'Compare the two products.',
            'candidate_documents': [{'document_id': 'allowed-document'}],
        }
        self.edit = {
            'current_plan': {'steps': [{'step_id': 'old-search', 'enabled': False}]},
            'current_request': 'Compare the two products.',
            'instruction': 'Focus on price and keep the extra search disabled.',
            'chat': [{'role': 'user', 'content': 'Remove the extra search.'}],
        }

    def call(self, reply, **overrides):
        arguments = {
            'settings': {'enable_user_workspace': True}, 'approval_mode': 'manual',
            'authorized_document_ids': {'allowed-document'},
            'edit_context': self.edit, **overrides,
        }
        with (
            patch.object(self.planner, 'resolve_planner_client', return_value=(object(), 'planner')),
            patch.object(
                self.planner, '_call_planner',
                return_value=(json.dumps(reply), SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10)),
            ),
        ):
            return self.planner.plan_request('Compare prices.', self.context, 'conversation', 'owner', **arguments)

    def plan(self, **overrides):
        return {
            'kind': 'plan', 'revised_request': 'Compare prices for the two products.',
            'steps': [
                {
                    'step_id': 'search', 'capability_id': 'document_search',
                    'arguments': {'query': 'Compare product prices.', 'document_ids': ['allowed-document']},
                },
                {'step_id': 'answer', 'capability_id': 'respond', 'arguments': {}},
            ],
            **overrides,
        }

    def test_edit_context_is_scoped_and_distinct_from_execution_feedback(self):
        messages = self.planner.build_planner_messages(self.context, edit_context=self.edit)
        payload = json.loads(messages[1]['content'])
        self.assertEqual(payload['plan_edit'], self.edit)
        self.assertIn('No step of this plan has run.', messages[0]['content'])
        self.assertNotIn('A step in your previous plan reported', messages[1]['content'])
        self.assertIn('revised_request', messages[0]['content'])

    def test_valid_revision_retains_self_contained_task_and_usage(self):
        kind, plan = self.call(self.plan())
        self.assertEqual(kind, 'plan')
        self.assertEqual(plan['revised_request'], 'Compare prices for the two products.')
        self.assertEqual(plan['approval']['mode'], 'manual')
        self.assertEqual(plan['status'], 'awaiting_approval')
        self.assertEqual(plan['token_usage']['total_tokens'], 10)
        self.assertNotIn('planner_fallback_reason', plan)

    def test_unrenderable_question_replanning_keeps_the_bound_model_and_edit_context(self):
        client = object()
        binding = SimpleNamespace(
            deployment='gpt-5.6-terra', as_planner_client=Mock(return_value=client),
        )
        usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10)
        with (
            patch.object(self.planner, 'resolve_planner_client') as legacy,
            patch.object(self.planner, '_call_planner', side_effect=[
                (json.dumps({'kind': 'elicitation'}), usage),
                (json.dumps(self.plan()), usage),
            ]) as completion,
        ):
            kind, plan = self.planner.plan_request(
                'Compare prices.', self.context, 'conversation', 'owner',
                settings={'enable_user_workspace': True},
                authorized_document_ids={'allowed-document'},
                edit_context=self.edit, planner_model=binding,
            )
        legacy.assert_not_called()
        self.assertEqual(kind, 'plan')
        self.assertEqual(plan['planner_model'], 'gpt-5.6-terra')
        self.assertEqual(completion.call_count, 2)
        for call in completion.call_args_list:
            self.assertIs(call.args[0], client)
            self.assertEqual(call.args[1], binding.deployment)
            self.assertIn(self.planner.PLAN_EDIT_INSTRUCTIONS, call.args[2][0]['content'])
            self.assertEqual(json.loads(call.args[2][1]['content'])['plan_edit'], self.edit)

    def test_missing_or_oversized_effective_task_is_not_a_successful_edit(self):
        for task in (None, '', 'x' * 6001):
            with self.subTest(task_length=len(task) if task is not None else None):
                with self.assertRaises(self.planner.PlannerError):
                    self.call(self.plan(revised_request=task))

    def test_disabled_work_is_not_dropped_into_an_apparent_success(self):
        reply = self.plan()
        reply['steps'][0]['capability_id'] = 'missing-capability'
        with self.assertRaises(self.planner.PlannerError):
            self.call(reply)

    def test_unreadable_documents_are_not_silently_removed(self):
        reply = self.plan()
        reply['steps'][0]['arguments']['document_ids'] = ['unreadable-document', 'allowed-document']
        with self.assertRaises(self.planner.PlannerError):
            self.call(reply)

    def test_explanation_has_bounded_content_and_no_execution_plan(self):
        kind, result = self.call({'kind': 'message', 'message': 'That integration is not enabled.'})
        self.assertEqual(kind, 'message')
        self.assertNotIn('steps', result)
        self.assertEqual(result['token_usage']['total_tokens'], 10)
        with self.assertRaises(self.planner.PlannerError):
            self.call({'kind': 'message', 'message': 'x' * 2001})

    def test_unknown_response_kind_is_not_normalized_to_a_plan(self):
        with self.assertRaises(self.planner.PlannerError):
            self.call(self.plan(kind='tool_call'))

    def test_declined_clarification_cannot_fall_back_to_an_answer_plan(self):
        with self.assertRaises(self.planner.PlannerError):
            self.call({'kind': 'elicitation'}, allow_elicitation=False)

    def test_provider_failure_is_safe_and_does_not_fall_back(self):
        with (
            patch.object(self.planner, 'resolve_planner_client', return_value=(object(), 'planner')),
            patch.object(self.planner, '_call_planner', side_effect=RuntimeError('PRIVATE_PROVIDER_DETAIL')),
        ):
            with self.assertRaises(self.planner.PlannerError) as raised:
                self.planner.plan_request(
                    'Change the plan.', self.context, 'conversation', 'owner',
                    settings={'enable_user_workspace': True}, edit_context=self.edit,
                )
        self.assertNotIn('PRIVATE_PROVIDER_DETAIL', str(raised.exception))
        self.assertIn('previous plan is unchanged', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
