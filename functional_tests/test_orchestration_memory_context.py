# test_orchestration_memory_context.py
"""Functional regressions for audience-bound orchestration memory.

Version: 0.261.104
Implemented in: 0.261.104

Uses real Flask routes, revisions, executor, adapters and the shared memory reader.
Only storage, membership, embedding and model boundaries are replaced. All network
access is blocked; planning and answering may read memory but must never write it.
"""

import json
import sys
import unittest
from unittest.mock import patch

from azure.core.exceptions import AzureError

import test_fact_memory_read_only_context as fact_tests
import test_orchestration_conversation_context_routes as context_tests
import test_orchestration_plan_revision_routes as revision_tests


class OrchestrationMemoryTests(unittest.TestCase):
    plan = context_tests.ConversationRouteTests.plan
    planned = context_tests.ConversationRouteTests.planned
    run_plan = context_tests.ConversationRouteTests.run_plan
    open_editor = revision_tests.PlanRevisionRouteTests.open_editor
    request_revision = revision_tests.PlanRevisionRouteTests.request_revision
    revise = revision_tests.PlanRevisionRouteTests.revise
    run_editor_plan = revision_tests.PlanRevisionRouteTests.run_editor_plan
    list_facts = fact_tests.MemoryContextTests.list_facts
    add_fact = fact_tests.MemoryContextTests.add_fact

    def setUp(self):
        revision_tests.PlanRevisionRouteTests.setUp(self)
        fact_tests.MemoryContextTests.setUp(self)
        self.settings['enable_fact_memory_plugin'] = True
        leaf_patch = patch.dict(sys.modules, {'functions_fact_memory_context': self.context})
        leaf_patch.start()
        self.addCleanup(leaf_patch.stop)
        self.add_fact(1, scope_id='user1', memory_type='instruction', value='Prefer an accessible itinerary.')
        self.add_fact(2, scope_id='user1', value='Saved destination: Crescent City.')
        self.add_fact(3, scope_id='other-user', value='OTHER USER PRIVATE MEMORY')
        self.addCleanup(self.assert_no_memory_writes)

    def assert_no_memory_writes(self):
        self.assertTrue(all(call[0] == 'list_facts' for call in self.store.method_calls), self.store.method_calls)
        self.batch_embeddings.assert_not_called()

    def planner_memory(self, calls=None):
        return json.loads((calls or self.model.calls)[-1]['messages'][1]['content'])['memory']

    def answer_calls(self):
        return [
            call for call in self.model.calls
            if call['messages'][0]['content'] == self.modules.adapters.RESPONSE_CONTEXT_POLICY
        ]

    def shared_source(self):
        conversation = self.conversations.read_item('conv1', 'conv1')
        conversation.update(
            conversation_kind='collaboration_source',
            collaboration_conversation_id='shared-conversation',
            chat_type='personal_single_user', is_hidden=True,
        )
        self.conversations.upsert_item(conversation)

    def group_plan(self):
        self.settings['enable_group_workspaces'] = True
        self.add_fact(4, scope_type='group', scope_id='group1', value='GROUP MEMORY')
        return self.planned(doc_scope='group', active_group_ids=['group1'])

    def test_private_planning_and_answering_use_scoped_memory_and_preserve_citations(self):
        plan = self.planned()
        memory = self.planner_memory()
        self.assertEqual(memory['status'], 'available')
        self.assertEqual(memory['scope_type'], 'user')
        self.assertIn('Saved destination: Crescent City.', json.dumps(memory))
        self.assertNotIn('OTHER USER PRIVATE MEMORY', json.dumps(memory))
        self.assertNotIn('Saved destination:', json.dumps(list(self.runs.items.values())))
        events = context_tests.frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        answer = self.answer_calls()[-1]['messages']
        self.assertIn('Saved destination: Crescent City.', json.dumps(answer))
        self.assertIn('subordinate to the latest request', answer[0]['content'])
        self.assertIn('Which are open on Wednesdays?', answer[-1]['content'])
        terminal = next(event for event in events if event.get('type') == 'orchestration_done')
        self.assertEqual(len(terminal['agent_citations']), 2)
        self.assertTrue(all(citation['plugin_name'] == 'fact_memory' for citation in terminal['agent_citations']))
        self.assertIn('prior-authorized-conversation', json.dumps(terminal['agent_citations']))
        saved_answers = [item for item in self.messages.items.values() if item.get('role') == 'assistant']
        self.assertTrue(any('fact_memory' in json.dumps(item.get('agent_citations')) for item in saved_answers))

    def test_editing_refreshes_memory_without_persisting_raw_prompt_context(self):
        editor = self.open_editor(self.planned())
        self.add_fact(5, scope_id='user1', value='NEWLY SAVED MEMORY')
        revised, _body = self.revise(editor, revision_tests.revised_plan())
        self.assertIn('NEWLY SAVED MEMORY', json.dumps(self.planner_memory(self.edit_calls)))
        record = self.runs.read_item(revised['plan']['run_id'], 'conv1')
        self.assertEqual(record['memory_audience']['kind'], 'personal')
        self.assertNotIn('NEWLY SAVED MEMORY', json.dumps(record))

    def test_disabled_memory_performs_no_reads_or_embeddings_through_plan_and_run(self):
        self.settings['enable_fact_memory_plugin'] = False
        plan = self.planned()
        self.assertEqual(self.planner_memory()['status'], 'disabled')
        events = context_tests.frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.store_factory.assert_not_called()
        self.membership.assert_not_called()
        self.embedding.assert_not_called()

    def test_shared_source_owner_does_not_load_personal_or_seeded_group_memory(self):
        self.shared_source()
        self.settings['enable_group_workspaces'] = True
        plan = self.planned(doc_scope='group', active_group_ids=['group1'])
        memory = self.planner_memory()
        self.assertEqual(memory['status'], 'unavailable')
        self.assertEqual(memory['messages'], [])
        self.assertIn('shared conversations', memory['notices'][0])
        events = context_tests.frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.store_factory.assert_not_called()
        self.membership.assert_not_called()

    def test_private_group_workspace_reads_only_authorized_group_memory(self):
        plan = self.group_plan()
        memory = self.planner_memory()
        self.assertEqual(memory['scope_type'], 'group')
        self.assertIn('GROUP MEMORY', json.dumps(memory))
        self.assertNotIn('Saved destination:', json.dumps(memory))
        events = context_tests.frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.membership.assert_called_with(
            'user1', 'group1', allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        self.assertTrue(all(call.kwargs['scope_id'] == 'group1' for call in self.store.list_facts.call_args_list))

    def test_revoked_group_scope_blocks_run_before_any_execution(self):
        plan = self.group_plan()
        planned_queries = list(self.search_queries)
        self.membership.side_effect = PermissionError('revoked')
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'memory_scope_unavailable')
        self.assertEqual(self.search_queries, planned_queries)
        self.assertEqual(self.answer_calls(), [])

    def test_revoked_group_scope_is_rechecked_after_retrieval_before_answer(self):
        plan = self.group_plan()
        self.after_search = lambda: setattr(self.membership, 'side_effect', PermissionError('revoked'))
        events = context_tests.frames(self.run_plan(plan))
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertEqual(self.answer_calls(), [])

    def test_disabling_memory_during_retrieval_removes_final_context_and_citations(self):
        plan = self.planned()
        self.after_search = lambda: self.settings.update(enable_fact_memory_plugin=False)
        events = context_tests.frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.assertNotIn('Saved destination:', json.dumps(self.answer_calls()))
        terminal = next(event for event in events if event.get('type') == 'orchestration_done')
        self.assertEqual(terminal.get('agent_citations'), [])

    def test_changing_audience_after_planning_blocks_the_saved_plan(self):
        plan = self.planned()
        self.shared_source()
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'memory_audience_changed')
        self.assertEqual(self.answer_calls(), [])

    def test_changing_audience_during_retrieval_blocks_answer_synthesis(self):
        plan = self.planned()
        self.after_search = self.shared_source
        events = context_tests.frames(self.run_plan(plan))
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertEqual(self.answer_calls(), [])

    def test_changing_audience_during_planning_prevents_publication(self):
        def change_after_memory_read():
            if self.store.list_facts.called:
                self.shared_source()

        self.before_plan_reply = change_after_memory_read
        _response, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertFalse(any(event.get('type') == 'orchestration_plan' for event in events), events)

    def test_changing_audience_during_synthesis_prevents_answer_publication(self):
        plan = self.planned()
        completion = self.model.chat.completions.create

        def change_during_answer(**kwargs):
            response = completion(**kwargs)
            if kwargs['messages'][0]['content'] == self.modules.adapters.RESPONSE_CONTEXT_POLICY:
                self.shared_source()
            return response

        self.model.chat.completions.create = change_during_answer
        events = context_tests.frames(self.run_plan(plan))
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertFalse(any(event.get('type') == 'orchestration_done' for event in events), events)
        self.assertFalse(self.runs.read_item(plan['run_id'], 'conv1').get('assistant_message_id'))

    def test_revoked_group_membership_during_synthesis_blocks_answer_and_citations(self):
        plan = self.group_plan()
        completion = self.model.chat.completions.create

        def revoke_during_answer(**kwargs):
            response = completion(**kwargs)
            if kwargs['messages'][0]['content'] == self.modules.adapters.RESPONSE_CONTEXT_POLICY:
                self.membership.side_effect = PermissionError('revoked')
            return response

        self.model.chat.completions.create = revoke_during_answer
        events = context_tests.frames(self.run_plan(plan))
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertFalse(any(event.get('type') == 'orchestration_done' for event in events), events)
        self.assertNotIn('GROUP MEMORY', json.dumps(events))
        stored = self.runs.read_item(plan['run_id'], 'conv1')
        self.assertEqual(stored['status'], 'failed')
        self.assertFalse(stored.get('assistant_message_id'))

    def private_memory_question(self):
        question = revision_tests.question()
        question['message'] = 'Should the visit include your saved destination: Crescent City?'
        return question

    def test_audience_change_during_planner_clarification_prevents_save_and_emit(self):
        self.model.plan_override = self.private_memory_question()

        def change_after_memory_read():
            if self.store.list_facts.called:
                self.shared_source()

        self.before_plan_reply = change_after_memory_read
        _response, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertNotIn('saved destination: Crescent City', json.dumps(events))
        self.assertFalse(any(event.get('type') == 'orchestration_elicitation' for event in events))
        self.assertFalse(any(row.get('question') for row in self.runs.items.values()))

    def test_group_revocation_during_planner_clarification_prevents_save_and_emit(self):
        self.settings['enable_group_workspaces'] = True
        self.add_fact(4, scope_type='group', scope_id='group1', value='GROUP MEMORY')
        self.model.plan_override = self.private_memory_question()

        def revoke_after_memory_read():
            if self.store.list_facts.called:
                self.membership.side_effect = PermissionError('revoked')

        self.before_plan_reply = revoke_after_memory_read
        _response, events = self.plan(doc_scope='group', active_group_ids=['group1'])
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertFalse(any(event.get('type') == 'orchestration_elicitation' for event in events))
        self.assertFalse(any(row.get('question') for row in self.runs.items.values()))

    def test_pending_question_replay_rechecks_memory_audience_without_new_model_call(self):
        self.model.plan_override = self.private_memory_question()
        _response, events = self.plan()
        self.assertTrue(any(event.get('type') == 'orchestration_elicitation' for event in events))
        calls_before = len(self.model.calls)
        self.shared_source()
        _response, replay = self.plan()
        self.assertTrue(any(event.get('error') for event in replay), replay)
        self.assertNotIn('saved destination: Crescent City', json.dumps(replay))
        self.assertEqual(len(self.model.calls), calls_before)

    def test_completed_submission_replay_rechecks_memory_audience(self):
        self.model.plan_override = self.private_memory_question()
        _response, events = self.plan()
        first_question = next(event['elicitation'] for event in events if event.get('type') == 'orchestration_elicitation')
        answer = {
            'revision': 1, 'elicitation': first_question,
            'elicitation_response': {'action': 'accept', 'content': {'day': 'Friday'}},
        }
        _response, answered = self.plan(**answer)
        self.assertTrue(any(event.get('type') == 'orchestration_elicitation' for event in answered), answered)
        calls_before = len(self.model.calls)
        self.shared_source()
        _response, replay = self.plan(**answer)
        self.assertTrue(any(event.get('error') for event in replay), replay)
        self.assertNotIn('saved destination: Crescent City', json.dumps(replay))
        self.assertEqual(len(self.model.calls), calls_before)

    def test_completed_submission_replay_uses_its_original_memory_scope(self):
        self.settings['enable_group_workspaces'] = True
        self.add_fact(4, scope_type='group', scope_id='group1', value='GROUP MEMORY')
        self.model.plan_override = self.private_memory_question()
        _response, events = self.plan(doc_scope='group', active_group_ids=['group1'])
        first_question = next(event['elicitation'] for event in events if event.get('type') == 'orchestration_elicitation')
        answer = {
            'revision': 1, 'elicitation': first_question,
            'elicitation_response': {'action': 'accept', 'content': {'day': 'Friday'}},
        }
        _response, answered = self.plan(**answer)
        self.assertTrue(any(event.get('type') == 'orchestration_elicitation' for event in answered), answered)
        pending = next(row for row in self.runs.items.values() if row.get('question'))
        self.assertEqual(
            pending['submissions'][-1]['outcome']['memory_scope'], {'type': 'group', 'id': 'group1'},
        )
        # A later continuation may have a different scope; it must not authorize an older outcome.
        pending['turn_context']['memory_scope'] = None
        self.membership.side_effect = PermissionError('revoked')
        calls_before = len(self.model.calls)
        _response, replay = self.plan(**answer)
        self.assertTrue(any(event.get('error') for event in replay), replay)
        self.assertFalse(any(event.get('type') == 'orchestration_elicitation' for event in replay))
        self.assertEqual(len(self.model.calls), calls_before)

    def test_missing_fact_embeddings_are_reported_without_backfill(self):
        self.facts[1]['value_embedding'] = None
        self.planned()
        memory = self.planner_memory()
        self.assertEqual(memory['status'], 'partial')
        self.assertIn('could not be searched', memory['notices'][0])
        self.assertIn('accessible itinerary', json.dumps(memory))
        self.assertNotIn('Saved destination:', json.dumps(memory))
        self.embedding.assert_not_called()

    def test_memory_storage_failure_does_not_replace_the_previous_plan(self):
        editor = self.open_editor(self.planned())
        before = self.runs.read_item(editor['plan']['run_id'], 'conv1')['plan']
        self.store.list_facts.side_effect = AzureError('private connection details')
        response, events, _body = self.request_revision(editor)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(event.get('code') == 'memory_context_unavailable' for event in events), events)
        self.assertNotIn('private connection details', json.dumps(events))
        self.assertEqual(self.runs.read_item(editor['plan']['run_id'], 'conv1')['plan'], before)
        self.assertEqual(self.edit_calls, [])


if __name__ == '__main__':
    unittest.main()
