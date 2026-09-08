# test_orchestration_plan_revision_routes.py
"""
Functional tests for conversational, pre-execution plan revisions.
Version: 0.261.104
Implemented in: 0.261.102
Authorized model routing through revisions and clarification: 0.261.103

Exercises the real Flask routes, planner, executor, and atomic revision persistence.
Only model, search, source-access, and Cosmos service boundaries are replaced.
"""

import json
import unittest
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import AzureError
from httpx import Request
from openai import APIError

import test_orchestration_conversation_context_routes as context_routes
from test_orchestration_model_selection import TERRA_SELECTION
from test_support.versioning import assert_app_version_at_least


frames = context_routes.frames


def revised_plan(task='Compare pricing for the wineries near Grants Pass.', searches=2):
    steps = [
        {
            'step_id': f'search_{index}', 'capability_id': 'document_search',
            'title': f'Gather evidence {index + 1}', 'arguments': {'query': task},
        }
        for index in range(searches)
    ]
    steps.append({
        'step_id': 'answer', 'capability_id': 'respond', 'title': 'Answer the revised request',
        'arguments': {}, 'depends_on': [step['step_id'] for step in steps],
    })
    return {
        'kind': 'plan', 'revised_request': task,
        'intent': {'summary': task, 'complexity': 'simple'}, 'steps': steps,
    }


def question():
    return {
        'kind': 'elicitation', 'message': 'Which weekday should the comparison cover?',
        'requested_schema': {
            'type': 'object', 'properties': {'day': {'type': 'string', 'title': 'Weekday'}},
            'required': ['day'],
        },
    }


class PlanRevisionRouteTests(unittest.TestCase):
    plan = context_routes.ConversationRouteTests.plan
    planned = context_routes.ConversationRouteTests.planned
    use_modern_models = context_routes.ConversationRouteTests.use_modern_models

    def setUp(self):
        context_routes.ConversationRouteTests.setUp(self)
        self.edit_responses = []
        self.edit_calls = []
        self.allowed_documents = set()
        self.before_edit_reply = None
        self.before_plan_reply = None
        normal_completion = self.model.create

        def completion(**kwargs):
            if self.modules.planner.PLAN_EDIT_INSTRUCTIONS not in kwargs['messages'][0]['content']:
                if self.before_plan_reply:
                    self.before_plan_reply()
                return normal_completion(**kwargs)
            self.edit_calls.append(deepcopy(kwargs))
            if self.before_edit_reply:
                self.before_edit_reply()
            reply = self.edit_responses.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        def manifest(ids, user_id, **kwargs):
            return [
                {
                    'document_id': document_id, 'file_name': f'{document_id}.pdf',
                    'scope': 'personal',
                    'authorization_status': 'authorized' if document_id in self.allowed_documents else 'denied',
                }
                for document_id in ids
            ]

        self.model.chat.completions.create = completion
        # The config-stub loader restores sys.modules; patch the route-bound module.
        patcher = patch.dict(self.route.build_plan_edit_outcome.__globals__, {
            'resolve_agent_catalog': lambda *args, **kwargs: [],
            'resolve_action_catalog': lambda *args, **kwargs: [],
            'resolve_authorized_source_manifest': manifest,
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_editor(self, plan=None, edits=None):
        plan = plan or self.planned()
        response = self.client.post(
            f"/api/v2/orchestration/runs/{plan['run_id']}/edit",
            json={'conversation_id': 'conv1', 'plan_id': plan['plan_id'], 'edits': edits},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()['editor']

    def editor(self, run_id):
        response = self.client.get(
            f'/api/v2/orchestration/runs/{run_id}/editor?conversation_id=conv1',
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()['editor']

    def request_revision(self, editor, action='ask', **fields):
        body = {
            'conversation_id': 'conv1', 'expected_version': editor['version'],
            'submission_id': str(uuid.uuid4()), 'action': action, 'edits': editor['edits'],
            **fields,
        }
        if action == 'ask':
            body.setdefault('instruction', 'Add another search focused on pricing.')
        response = self.client.post(
            f"/api/v2/orchestration/runs/{editor['plan']['run_id']}/revisions",
            json=body, buffered=True,
        )
        return response, frames(response), body

    def revise(self, editor, reply=None, action='ask', **fields):
        if reply is not None:
            self.edit_responses.append(reply)
        response, events, body = self.request_revision(editor, action, **fields)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertFalse(any(event.get('error') for event in events), events)
        result = next(event['editor'] for event in events if event.get('editor'))
        return result, body

    def run_editor_plan(self, editor, **fields):
        return self.client.post('/api/v2/orchestration/run', json={
            'conversation_id': 'conv1', 'run_id': editor['plan']['run_id'],
            'plan_id': editor['plan']['plan_id'], 'expected_version': editor['version'],
            'edits': editor['edits'], **fields,
        }, buffered=True)

    def test_application_version(self):
        assert_app_version_at_least('0.261.103')

    def test_editing_preserves_the_selected_model_through_execution(self):
        selection = self.use_modern_models()
        editor = self.open_editor(self.planned(**selection, reasoning_effort='high'))
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        revised, _body = self.revise(editor, revised_plan())
        self.assertEqual(self.edit_calls[0]['model'], 'gpt-5.6-terra')
        self.assertEqual(self.edit_calls[0]['reasoning_effort'], 'high')
        self.assertIn('max_completion_tokens', self.edit_calls[0])
        self.assertNotIn('max_tokens', self.edit_calls[0])
        self.assertNotIn('temperature', self.edit_calls[0])
        record = self.runs.read_item(revised['plan']['run_id'], 'conv1')
        self.assertEqual(record['seeds']['model'], selection)
        self.assertEqual(record['original_seeds']['model'], selection)
        events = frames(self.run_editor_plan(revised))
        self.assertFalse(any(event.get('error') for event in events), events)
        terminal = next(event for event in events if event.get('type') == 'orchestration_done')
        self.assertEqual(terminal['model_deployment_name'], 'gpt-5.6-terra')
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_editing_uses_a_separate_planner_without_replacing_the_answer_model(self):
        self.use_modern_models()
        self.settings.update({
            'chat_orchestration_planner_model_endpoint_id': 'selected-endpoint',
            'chat_orchestration_planner_model_id': 'luna-model',
        })
        revised, _body = self.revise(self.open_editor(), revised_plan())
        self.assertEqual(self.edit_calls[0]['model'], 'gpt-5.6-luna')
        record = self.runs.read_item(revised['plan']['run_id'], 'conv1')
        self.assertEqual(record['seeds']['model'], TERRA_SELECTION)
        events = frames(self.run_editor_plan(revised))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.assertEqual(self.model.calls[-1]['model'], 'gpt-5.6-terra')
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_edit_clarification_retains_the_original_default_model(self):
        self.use_modern_models()
        editor = self.open_editor()
        pending, _body = self.revise(editor, question())
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        clarification = pending['pending']
        revised, _body = self.revise(
            pending, revised_plan('Compare wineries on Friday.', searches=1),
            action='answer', elicitation_id=clarification['elicitation_id'],
            elicitation_revision=clarification['revision'],
            elicitation_response={'action': 'accept', 'content': {'day': 'Friday'}},
        )
        self.assertEqual([call['model'] for call in self.edit_calls], ['gpt-5.6-terra'] * 2)
        record = self.runs.read_item(revised['plan']['run_id'], 'conv1')
        self.assertEqual(record['seeds']['model'], TERRA_SELECTION)
        self.assertEqual(record['original_seeds']['model'], TERRA_SELECTION)
        self.assertIsNone(revised['pending'])
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_replay_discard_and_restore_do_not_allocate_model_clients(self):
        self.use_modern_models()
        editor = self.open_editor()
        pending, body = self.revise(editor, question())
        client_count = len(self.model_clients)
        self.model_runtime.resolve_model_endpoint_from_context.return_value = None
        response = self.client.post(
            f"/api/v2/orchestration/runs/{editor['plan']['run_id']}/revisions",
            json=body, buffered=True,
        )
        replay = next(event['editor'] for event in frames(response) if event.get('editor'))
        self.assertEqual(replay['pending']['elicitation_id'], pending['pending']['elicitation_id'])
        discarded, _body = self.revise(replay, action='discard')
        restored, _body = self.revise(
            discarded, action='restore', source_run_id=editor['plan']['run_id'],
        )
        self.assertIsNone(restored['pending'])
        self.assertEqual(len(self.model_clients), client_count)
        self.assertEqual(len(self.edit_calls), 1)

    def test_revoked_model_does_not_replace_the_plan_and_releases_its_edit_claim(self):
        self.use_modern_models()
        editor = self.open_editor()
        self.model_runtime.resolve_model_endpoint_from_context.return_value = None
        _response, events, _body = self.request_revision(editor)
        self.assertTrue(any(event.get('code') == 'model_unavailable' for event in events), events)
        self.assertEqual(self.edit_calls, [])
        current = self.editor(editor['plan']['run_id'])
        self.assertEqual(current['plan']['run_id'], editor['plan']['run_id'])
        self.assertEqual(current['version'], editor['version'])
        self.assertFalse(current['busy'])
        self.model_runtime.resolve_model_endpoint_from_context.return_value = self.endpoint
        revised, _body = self.revise(current, revised_plan())
        self.assertNotEqual(revised['plan']['run_id'], current['plan']['run_id'])
        self.assertEqual(self.edit_calls[0]['model'], 'gpt-5.6-terra')

    def test_failed_model_edit_closes_its_client_and_preserves_the_plan(self):
        self.use_modern_models()
        editor = self.open_editor()
        self.edit_responses.append({'kind': 'plan', 'steps': []})
        _response, events, _body = self.request_revision(editor)
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertEqual(self.editor(editor['plan']['run_id'])['version'], editor['version'])
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_get_does_not_pause_but_edit_holds_countdown_durably(self):
        self.settings.update({
            'chat_orchestration_default_approval_mode': 'timed',
            'chat_orchestration_allow_user_approval_override': False,
        })
        plan = self.planned()
        self.assertEqual(self.editor(plan['run_id'])['plan']['approval']['mode'], 'timed')
        editor = self.open_editor(plan)
        self.assertEqual(editor['plan']['approval']['mode'], 'manual')
        self.assertEqual(editor['plan']['approval']['state'], 'pending')
        self.assertEqual(self.editor(plan['run_id'])['version'], editor['version'])
        self.assertEqual(self.editor(plan['run_id'])['plan']['approval']['mode'], 'manual')
        stale = self.run_editor_plan(editor, expected_version=None)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()['code'], 'plan_changed')
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['status'], 'awaiting_approval')

    def test_add_remove_restore_and_retry_keep_one_original_message(self):
        editor = self.open_editor()
        original_id = editor['plan']['run_id']
        original_message_count = len(self.messages.items)
        first, body = self.revise(editor, revised_plan())
        self.assertEqual(len(first['plan']['steps']), 3)
        self.assertNotEqual(first['plan']['run_id'], original_id)
        response = self.client.post(
            f'/api/v2/orchestration/runs/{original_id}/revisions', json=body, buffered=True,
        )
        replay = next(event['editor'] for event in frames(response) if event.get('editor'))
        self.assertEqual(replay['plan']['run_id'], first['plan']['run_id'])
        self.assertEqual(len(self.edit_calls), 1)
        second, _body = self.revise(
            first, revised_plan('Summarize the already available comparison.', searches=0),
            instruction='Remove the searches and summarize what is already available.',
        )
        self.assertEqual([step['capability_id'] for step in second['plan']['steps']], ['respond'])
        restored, _body = self.revise(second, action='restore', source_run_id=original_id)
        self.assertEqual(len(restored['plan']['steps']), len(editor['plan']['steps']))
        self.assertGreater(restored['plan']['revision'], second['plan']['revision'])
        self.assertNotEqual(restored['plan']['run_id'], original_id)
        self.assertEqual(len(self.messages.items), original_message_count)
        self.assertEqual(self.editor(original_id)['plan']['run_id'], restored['plan']['run_id'])
        latest, _body = self.revise(restored, revised_plan('Focus the restored comparison on price.', searches=1))
        prompt = json.loads(self.edit_calls[-1]['messages'][1]['content'])
        self.assertEqual(
            prompt['plan_edit']['current_plan']['steps'],
            restored['plan']['steps'],
        )
        self.assertEqual(self.runs.read_item(latest['plan']['run_id'], 'conv1')['user_message'],
                         self.runs.read_item(original_id, 'conv1')['user_message'])

    def test_review_narrowing_reaches_the_planner(self):
        editor = self.open_editor(edits={
            'disabled_step_ids': ['search'], 'removed_document_ids': {},
        })
        updated, _body = self.revise(editor, revised_plan(searches=0))
        supplied = json.loads(self.edit_calls[-1]['messages'][1]['content'])['plan_edit']['current_plan']
        self.assertFalse(next(step for step in supplied['steps'] if step['step_id'] == 'search')['enabled'])
        self.assertEqual(updated['edits'], {'disabled_step_ids': [], 'removed_document_ids': {}})

    def test_document_removal_is_not_lost_when_editor_opens(self):
        self.allowed_documents = {'docA', 'docB'}
        self.model.plan_override = revised_plan(searches=1)
        self.model.plan_override['steps'][0]['arguments']['document_ids'] = ['docA', 'docB']
        plan = self.planned(selected_document_ids=['docA', 'docB'])
        editor = self.open_editor(plan, {
            'disabled_step_ids': [], 'removed_document_ids': {'search_0': ['docA']},
        })
        reply = revised_plan(searches=1)
        reply['steps'][0]['arguments']['document_ids'] = ['docB']
        updated, _body = self.revise(editor, reply)
        supplied = json.loads(self.edit_calls[-1]['messages'][1]['content'])
        self.assertEqual(supplied['plan_edit']['current_plan']['steps'][0]['arguments']['document_ids'], ['docB'])
        self.assertEqual(updated['plan']['steps'][0]['arguments']['document_ids'], ['docB'])

    def test_unavailable_capability_and_invalid_model_output_keep_previous_plan(self):
        editor = self.open_editor()
        invalid = revised_plan()
        invalid['steps'][0]['capability_id'] = 'not_enabled_or_registered'
        provider_error = APIError(
            'provider-secret', request=Request('POST', 'https://model.example'), body=None,
        )
        for reply in (
            invalid, {'kind': 'plan', 'steps': []},
            {'kind': 'plan', 'revised_request': 'Keep the current task.', 'steps': []},
            {'kind': 'plan', 'revised_request': 'Keep the current task.', 'steps': 'not-a-list'},
            provider_error,
        ):
            with self.subTest(reply=type(reply).__name__):
                self.edit_responses.append(reply)
                _response, events, _body = self.request_revision(editor)
                self.assertTrue(any(event.get('error') for event in events), events)
                self.assertNotIn('provider-secret', json.dumps(events))
                current = self.editor(editor['plan']['run_id'])
                self.assertEqual(current['plan']['run_id'], editor['plan']['run_id'])
                self.assertEqual(current['version'], editor['version'])
                self.assertFalse(current['busy'])

    def test_model_explanation_is_scoped_chat_not_a_new_plan(self):
        editor = self.open_editor()
        count = len(self.messages.items)
        updated, _body = self.revise(editor, {'kind': 'message', 'message': 'The search gathers evidence before answering.'})
        self.assertEqual(updated['plan']['run_id'], editor['plan']['run_id'])
        self.assertEqual(updated['chat'][-1]['content'], 'The search gathers evidence before answering.')
        self.assertEqual(len(self.messages.items), count)

    def test_clarification_continues_the_same_edit_without_running(self):
        editor = self.open_editor()
        pending, _body = self.revise(editor, question(), instruction='Compare these wineries on a different weekday.')
        self.assertIsNotNone(pending['pending'])
        self.assertEqual(pending['plan']['run_id'], editor['plan']['run_id'])
        blocked = self.run_editor_plan(pending)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.get_json()['code'], 'edit_in_progress')
        clarification = pending['pending']
        final, _body = self.revise(
            pending, revised_plan('Compare the wineries near Grants Pass on Friday.', searches=1),
            action='answer', elicitation_id=clarification['elicitation_id'],
            elicitation_revision=clarification['revision'],
            elicitation_response={'action': 'accept', 'content': {'day': 'Friday'}},
        )
        prompt = json.loads(self.edit_calls[-1]['messages'][1]['content'])
        self.assertEqual(prompt['plan_edit']['instruction'], 'Compare these wineries on a different weekday.')
        self.assertEqual(prompt['clarifications'][-1]['answer'], {'day': 'Friday'})
        self.assertIsNone(final['pending'])
        self.assertIn('Friday', self.runs.read_item(final['plan']['run_id'], 'conv1')['resolved_message'])

    def test_discard_question_leaves_original_plan_manually_runnable(self):
        editor = self.open_editor()
        pending, _body = self.revise(editor, question())
        final, _body = self.revise(pending, action='discard')
        self.assertIsNone(final['pending'])
        self.assertEqual(final['plan']['run_id'], editor['plan']['run_id'])
        self.assertEqual(final['plan']['approval']['mode'], 'manual')
        self.assertFalse(any(event.get('error') for event in frames(self.run_editor_plan(final))))

    def test_latest_effective_request_reaches_real_execution(self):
        editor = self.open_editor()
        task = 'Compare only pricing for the wineries near Grants Pass on Friday.'
        final, _body = self.revise(editor, revised_plan(task, searches=1), instruction=task)
        self.search_queries.clear()
        response = self.run_editor_plan(final)
        events = frames(response)
        self.assertEqual(response.status_code, 200, events)
        self.assertFalse(any(event.get('error') for event in events), events)
        self.assertEqual(self.search_queries, [task])
        synthesis = self.model.calls[-1]['messages']
        self.assertTrue(any(task in turn['content'] for turn in synthesis), synthesis)
        old = self.run_editor_plan(editor)
        self.assertEqual(old.status_code, 409)
        self.assertEqual(old.get_json()['code'], 'plan_changed')

    def test_model_rewording_cannot_authorize_new_urls(self):
        editor = self.open_editor()
        final, _body = self.revise(
            editor, revised_plan('Read https://invented.example.test and summarize it.', searches=0),
            instruction='Also consider https://supplied.example.test in the comparison.',
        )
        stored = self.runs.read_item(final['plan']['run_id'], 'conv1')
        allowed = self.route.revision_allowed_urls(stored)
        self.assertTrue(any(url.startswith('https://supplied.example.test') for url in allowed))
        self.assertFalse(any(url.startswith('https://invented.example.test') for url in allowed))

    def test_editor_followup_can_use_a_link_from_an_earlier_user_message(self):
        editor = self.open_editor()
        explained, _body = self.revise(
            editor, {'kind': 'message', 'message': 'We can use your source, not https://invented.example.test.'},
            instruction='Can the plan use https://supplied.example.test as a source?',
        )
        final, _body = self.revise(
            explained, revised_plan('Compare the wineries using the supplied source.', searches=0),
            instruction='Yes, use that source for the comparison.',
        )
        stored = self.runs.read_item(final['plan']['run_id'], 'conv1')
        allowed = self.route.revision_allowed_urls(stored)
        self.assertIn('https://supplied.example.test', allowed)
        self.assertFalse(any(url.startswith('https://invented.example.test') for url in allowed))

    def test_failed_execution_claim_never_reaches_an_adapter(self):
        editor = self.open_editor()
        self.search_queries.clear()
        self.model.calls.clear()
        with patch.object(self.route, 'claim_plan_run', side_effect=AzureError('claim unavailable')):
            response = self.run_editor_plan(editor)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.search_queries, [])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.runs.read_item(editor['plan']['run_id'], 'conv1')['status'], 'awaiting_approval')

    def test_changed_context_is_not_reported_as_an_already_executed_plan(self):
        editor = self.open_editor()
        record = self.runs.read_item(editor['plan']['run_id'], 'conv1')
        original = self.messages.read_item(record['user_message_id'], 'conv1')
        self.messages.upsert_item({**original, 'content': 'A different request.'})
        self.model.calls.clear()
        response = self.run_editor_plan(editor)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'plan_changed')
        self.assertEqual(self.model.calls, [])
        self.assertIsNone(self.runs.read_item(record['run_id'], 'conv1')['started_at'])

    def test_storage_failure_does_not_publish_or_discard_previous_plan(self):
        editor = self.open_editor()
        self.edit_responses.append(revised_plan())
        with patch.object(self.runs, 'execute_item_batch', side_effect=AzureError('private-storage-error')):
            _response, events, _body = self.request_revision(editor)
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertNotIn('private-storage-error', json.dumps(events))
        current = self.editor(editor['plan']['run_id'])
        self.assertEqual(current['version'], editor['version'])
        self.assertFalse(current['busy'])

    def test_plain_replan_cannot_bypass_an_edit_hold(self):
        editor = self.open_editor()
        _response, events = self.plan(revision=1)
        self.assertTrue(any(event.get('code') == 'plan_changed' for event in events), events)
        self.assertEqual(self.editor(editor['plan']['run_id'])['version'], editor['version'])

    def test_lost_confirmation_recovers_committed_revision_without_second_model_call(self):
        editor = self.open_editor()
        self.edit_responses.append(revised_plan())
        with patch.object(self.route, 'plan_editor_state', side_effect=AzureError('read unavailable')):
            _response, events, body = self.request_revision(editor)
        error = next(event['error'] for event in events if event.get('error'))
        self.assertNotIn('unchanged', error)
        response = self.client.post(
            f"/api/v2/orchestration/runs/{editor['plan']['run_id']}/revisions",
            json=body, buffered=True,
        )
        recovered = next(event['editor'] for event in frames(response) if event.get('editor'))
        self.assertNotEqual(recovered['plan']['run_id'], editor['plan']['run_id'])
        self.assertEqual(len(self.edit_calls), 1)

    def test_inflight_plain_replan_loses_to_edit_hold(self):
        plan = self.planned()
        held = []
        self.before_plan_reply = lambda: held.append(self.open_editor(plan))
        _response, events = self.plan(revision=1)
        self.assertTrue(any(event.get('error') for event in events), events)
        self.assertEqual(self.editor(plan['run_id'])['version'], held[-1]['version'])
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['status'], 'awaiting_approval')

    def test_read_and_edit_routes_enforce_conversation_ownership(self):
        editor = self.open_editor()
        with patch.object(self.route, 'get_current_user_id', return_value='another-user'):
            for method, suffix, body in (
                ('get', 'editor?conversation_id=conv1', None),
                ('post', 'edit', {'conversation_id': 'conv1', 'plan_id': editor['plan']['plan_id']}),
                ('post', 'revisions', {'conversation_id': 'conv1', 'action': 'ask'}),
            ):
                response = getattr(self.client, method)(
                    f"/api/v2/orchestration/runs/{editor['plan']['run_id']}/{suffix}",
                    **({'json': body} if body else {}),
                )
                self.assertEqual(response.status_code, 404)

    def test_invalid_requests_and_stale_versions_do_not_call_the_model(self):
        editor = self.open_editor()
        for fields, status in (
            ({'instruction': ' '}, 400),
            ({'instruction': 'x' * 2001}, 400),
            ({'plan': revised_plan()}, 400),
            ({'expected_version': 'stale-token'}, 409),
        ):
            with self.subTest(fields=list(fields)):
                response, _events, _body = self.request_revision(editor, **fields)
                self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertEqual(self.edit_calls, [])

    def test_editor_projection_does_not_expose_private_context_or_claims(self):
        editor = self.open_editor()
        serialized = json.dumps(editor)
        for private in ('_etag', 'original_seeds', 'conversation_context', 'user_message_fingerprint',
                        'edit_pending', 'edit_submissions', 'request_fingerprint'):
            self.assertNotIn(f'"{private}"', serialized)
        response = self.client.get(
            f"/api/v2/orchestration/runs/{editor['plan']['run_id']}/editor"
            '?conversation_id=conv1&before_revision=-1',
        )
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
