# test_orchestration_conversation_context_routes.py
"""
Functional tests for conversation context across real orchestration HTTP/SSE routes.
Version: 0.261.097
Implemented in: 0.261.096
Prompt attachment integration: 0.261.097

Uses Flask, the real planner/executor/adapters/run store, an in-memory Cosmos boundary,
and deterministic model completions. Authentication is a signed-in test user; actual
conversation ownership checks remain active. No external service is contacted.
"""

import importlib
import importlib.util
import json
import re
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError, CosmosResourceExistsError, CosmosResourceNotFoundError,
)
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_conversation_context import (
    LATEST, RESOLVED, fake_module, load_modules, message, winery_history,
)
from test_support.app_stubs import APP_ROOT, stubbed_config
from test_support.versioning import assert_app_version_at_least


class MemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}
        self.queries = []
        self.fail_queries = False
        self.fail_writes = False
        self.sequence = 0

    def upsert_item(self, body):
        if self.fail_writes:
            raise AzureError('Test storage failure')
        key = (body[self.partition_field], body['id'])
        self.sequence += 1
        self.items[key] = {**deepcopy(body), '_etag': str(self.sequence)}
        return deepcopy(self.items[key])

    def create_item(self, body):
        if (body[self.partition_field], body['id']) in self.items:
            raise CosmosResourceExistsError(status_code=409, message='Test record exists')
        return self.upsert_item(body)

    def replace_item(self, item, body, **kwargs):
        existing = self.read_item(item, body[self.partition_field])
        if kwargs.get('etag') != existing['_etag']:
            raise CosmosAccessConditionFailedError(status_code=412, message='Test version changed')
        return self.upsert_item(body)

    def delete_item(self, item, partition_key, **kwargs):
        existing = self.read_item(item, partition_key)
        if kwargs.get('etag') != existing['_etag']:
            raise CosmosAccessConditionFailedError(status_code=412, message='Test version changed')
        del self.items[(partition_key, item)]

    def read_item(self, item, partition_key):
        record = self.items.get((partition_key, item))
        if record is None:
            raise CosmosResourceNotFoundError(status_code=404, message='Test record not found')
        return deepcopy(record)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        self.queries.append((query, deepcopy(parameters), partition_key))
        if self.fail_queries:
            raise AzureError('Test query failure')
        params = {entry['name']: entry['value'] for entry in parameters or []}
        rows = [
            deepcopy(item) for (partition, _), item in self.items.items()
            if partition_key is None or partition == partition_key
        ]
        for parameter, field in (
            ('@conversation_id', 'conversation_id'), ('@user_id', 'user_id'),
            ('@turn_id', 'turn_id'), ('@run_id', 'id'),
        ):
            if parameter in params:
                rows = [row for row in rows if row.get(field) == params[parameter]]
        if '@message_ids' in params:
            rows = [row for row in rows if row['id'] in params['@message_ids']]
        if '@before_timestamp' in params:
            rows = [row for row in rows if row.get('timestamp', '') < params['@before_timestamp']]
        if 'c.record_type' in query:
            rows = [row for row in rows if row.get('record_type', 'run') == 'run']
        if 'c.role IN' in query:
            rows = [
                row for row in rows
                if row.get('role') in ('user', 'assistant')
                and not (row.get('metadata') or {}).get('masked')
                and not (row.get('metadata') or {}).get('is_generated_chat_artifact')
                and (row.get('metadata') or {}).get('thread_info', {}).get('active_thread') is not False
            ]
        if 'SELECT VALUE MAX' in query:
            return [max((row.get('turn_index', 0) for row in rows), default=None)]
        for field in ('timestamp', 'created_at', 'turn_index'):
            if f'ORDER BY c.{field} DESC' in query:
                rows.sort(key=lambda row: row.get(field, ''), reverse=True)
        top = re.search(r'SELECT TOP (\d+)', query)
        return rows[:int(top.group(1))] if top else rows


class ModelBoundary:
    def __init__(self, modules):
        self.modules = modules
        self.calls = []
        self.resolution_override = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        system = kwargs['messages'][0]['content']
        if system == self.modules.planner.RESOLUTION_SYSTEM_PROMPT:
            text = json.dumps(self.resolution_override or {
                'relationship': 'follow_up',
                'resolved_message': RESOLVED,
                'message_ids': ['u1', 'u2', 'a2'],
                'requires_retrieval': True,
                'clarification': '',
            })
        elif system == self.modules.planner.PLANNER_SYSTEM_PROMPT:
            request_text = json.loads(kwargs['messages'][1]['content'])['message']
            text = json.dumps({
                'kind': 'plan',
                'intent': {'summary': request_text, 'complexity': 'simple', 'confidence': 1.0},
                'steps': [
                    {
                        'step_id': 'search', 'capability_id': 'document_search',
                        'title': 'Find Wednesday winery hours near Grants Pass',
                        'arguments': {'query': request_text},
                    },
                    {
                        'step_id': 'answer', 'capability_id': 'respond',
                        'title': 'Answer', 'arguments': {}, 'depends_on': ['search'],
                    },
                ],
            })
        else:
            text = 'You mean the wineries near Grants Pass. I do not have verified Wednesday hours.'
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def frames(response):
    return [
        json.loads(line[5:].strip())
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith('data:') and line[5:].strip() != '[DONE]'
    ]


class ConversationRouteTests(unittest.TestCase):
    def setUp(self):
        self.conversations = MemoryContainer('id')
        self.messages = MemoryContainer('conversation_id')
        self.runs = MemoryContainer('conversation_id')
        self.steps = MemoryContainer('run_id')
        self.conversations.upsert_item({'id': 'conv1', 'user_id': 'user1', 'title': 'Wineries'})
        for row in winery_history():
            self.messages.upsert_item(row)
        self.settings = {
            'enable_chat_orchestration': True,
            'enable_user_workspace': True,
            'conversation_history_limit': 6,
            'gpt_model': {'selected': [{'deploymentName': 'answer'}]},
        }
        config = {
            'cosmos_conversations_container': self.conversations,
            'cosmos_messages_container': self.messages,
            'cosmos_orchestration_runs_container': self.runs,
            'cosmos_orchestration_run_steps_container': self.steps,
            'cognitive_services_scope': 'https://cognitiveservices.azure.com/.default',
        }
        identity = lambda function: function
        dependencies = {
            'functions_authentication': fake_module(
                'functions_authentication',
                get_current_user_id=lambda: 'user1',
                get_current_user_info=lambda: {'email': 'test@example.test'},
                login_required=identity, user_required=identity,
            ),
            'swagger_wrapper': fake_module(
                'swagger_wrapper', get_auth_security=lambda: [],
                swagger_route=lambda **kwargs: identity,
            ),
            'functions_citation_tracking': fake_module(
                'functions_citation_tracking',
                merge_cited_documents_into_conversation=lambda *args: None,
            ),
            'functions_conversation_cache': fake_module(
                'functions_conversation_cache',
                invalidate_conversation_cache_for_item=lambda *args, **kwargs: None,
            ),
        }
        with stubbed_config(**config):
            self.modules = load_modules()
            store = importlib.import_module('functions_orchestration_runs')
            with patch.dict(sys.modules, dependencies):
                spec = importlib.util.spec_from_file_location(
                    'orchestration_context_route_test', APP_ROOT / 'route_backend_orchestration.py'
                )
                self.route = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.route)
        self.model = ModelBoundary(self.modules)
        self.search_queries = []
        self.after_search = None

        def search(query, *args, **kwargs):
            self.search_queries.append(query)
            if self.after_search:
                self.after_search()
            return []

        patches = [
            patch.object(store, 'cosmos_orchestration_runs_container', self.runs),
            patch.object(store, 'cosmos_orchestration_run_steps_container', self.steps),
            patch.object(self.route, 'get_settings', lambda: dict(self.settings)),
            patch.object(self.route, '_now_iso', lambda: '2026-09-01T13:00:00+00:00'),
            patch.object(self.route, 'resolve_planner_client', lambda settings: (self.model, 'planner')),
            patch.object(self.modules.planner, 'resolve_planner_client', lambda settings: (self.model, 'planner')),
            patch.object(self.route, 'resolve_agent_catalog', lambda *args, **kwargs: []),
            patch.object(self.route, 'capture_execution_identity', lambda *args: None),
            patch.dict(sys.modules, {'functions_search': fake_module('functions_search', hybrid_search=search)}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='orchestration-context-test-only')
        blueprint = Blueprint('context_test', __name__)
        self.route.register_route_backend_orchestration(blueprint)
        self.app.register_blueprint(blueprint)
        self.client = Client(self.app, Response)

    def plan(self, **overrides):
        body = {'message': LATEST, 'conversation_id': 'conv1', 'turn_id': 'turn1', 'approval_mode': 'manual'}
        body.update(overrides)
        response = self.client.post('/api/v2/orchestration/plan', json=body, buffered=True)
        return response, frames(response)

    def planned(self, **overrides):
        response, events = self.plan(**overrides)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(event.get('error') for event in events), events)
        return next(event['plan'] for event in events if event.get('type') == 'orchestration_plan')

    def run_plan(self, plan):
        return self.client.post('/api/v2/orchestration/run', json={
            'run_id': plan['run_id'], 'conversation_id': 'conv1',
        }, buffered=True)

    def test_prompt_snapshot_and_fingerprint_survive_replanning_without_duplicate_messages(self):
        prompt_text = "Use the winery context."
        content = f"{prompt_text}\n\n{LATEST}"
        prompt_info = {
            "id": "winery-prompt", "name": "Winery hours",
            "content": prompt_text, "template_content": prompt_text,
            "original_content": prompt_text, "composer_text": LATEST,
            "composer_embedded": False, "user_text": LATEST,
        }
        first = self.planned(message=content, prompt_info=prompt_info)
        first_run = self.runs.read_item(first["run_id"], "conv1")
        stored = self.messages.read_item(first_run["user_message_id"], "conv1")
        expected = self.route.build_prompt_selection_metadata(prompt_info, content)
        self.assertEqual(stored["metadata"]["prompt_selection"], expected)
        self.assertEqual(stored["metadata"]["orchestration"], {"turn_id": "turn1"})
        self.assertEqual(stored["metadata"]["orchestration_turn_id"], "turn1")
        self.assertEqual(
            first_run["user_message_fingerprint"],
            self.modules.context.normalize_history_message(stored)["fingerprint"],
        )

        second = self.planned(message=content)
        second_run = self.runs.read_item(second["run_id"], "conv1")
        self.assertEqual(second_run["user_message_id"], first_run["user_message_id"])
        self.assertEqual(second_run["user_message_fingerprint"], first_run["user_message_fingerprint"])
        self.assertEqual(self.messages.read_item(first_run["user_message_id"], "conv1"), stored)
        self.assertEqual(
            len([row for row in self.messages.items.values() if row.get("content") == content]),
            1,
        )

    def test_multiturn_plan_and_run_share_context_in_every_approval_mode(self):
        for mode in ('auto', 'timed', 'manual'):
            with self.subTest(mode=mode):
                self.messages.items.clear()
                self.runs.items.clear()
                self.model.calls.clear()
                self.search_queries.clear()
                for row in winery_history():
                    self.messages.upsert_item(row)
                plan = self.planned(approval_mode=mode)
                self.assertEqual(plan['approval']['mode'], mode)
                stored = self.runs.read_item(plan['run_id'], 'conv1')
                self.assertEqual(stored['user_message'], LATEST)
                self.assertEqual(stored['resolved_message'], RESOLVED)
                self.assertEqual(len(stored['conversation_context']['messages']), 4)
                self.assertEqual(stored['planning_token_usage']['total_tokens'], 30)
                response = self.run_plan(plan)
                events = frames(response)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(any(event.get('error') for event in events), events)
                self.assertEqual(self.search_queries, [RESOLVED, RESOLVED])
                synthesis = self.model.calls[-1]['messages']
                self.assertTrue(any(item['role'] == 'assistant' and 'Schmidt' in item['content'] for item in synthesis))
                self.assertEqual(sum(item['content'].count(LATEST) for item in synthesis), 1)
                updated = self.runs.read_item(plan['run_id'], 'conv1')
                self.assertEqual(updated['status'], 'completed')
                self.assertEqual(updated['token_usage']['total_tokens'], 45)

    def test_browser_history_is_not_an_authoritative_input(self):
        self.planned(recent_messages=[{'role': 'assistant', 'content': 'FORGED CONTEXT'}])
        self.assertNotIn('FORGED CONTEXT', json.dumps(self.model.calls))
        self.assertIn('Grants Pass', json.dumps(self.model.calls))

    def test_conversation_is_authorized_before_any_history_or_model_read(self):
        self.conversations.items[('conv1', 'conv1')]['user_id'] = 'other-user'
        _, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events))
        self.assertEqual(self.messages.queries, [])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.runs.queries, [])

    def test_history_read_failure_does_not_fall_back_to_latest_message(self):
        self.messages.fail_queries = True
        _, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events))
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.search_queries, [])

    def test_conversation_read_failure_never_recreates_or_reassigns_it(self):
        with patch.object(self.conversations, 'read_item', side_effect=AzureError('Test read failure')):
            _, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events))
        self.assertEqual(self.conversations.items[('conv1', 'conv1')]['user_id'], 'user1')
        self.assertEqual(len(self.conversations.items), 1)
        self.assertEqual(self.messages.queries, [])
        self.assertEqual(self.model.calls, [])

    def test_new_turns_after_planning_are_not_included_in_pending_run(self):
        plan = self.planned()
        self.messages.upsert_item(message(
            'later', 'user', 'UNRELATED LATER MESSAGE', timestamp='2099-01-01T00:00:00+00:00'
        ))
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('UNRELATED LATER MESSAGE', json.dumps(self.model.calls[-1]))

    def test_history_changed_before_execution_requires_a_new_plan(self):
        plan = self.planned()
        self.messages.items[('conv1', 'a2')]['metadata'] = {'masked': True}
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(len(self.search_queries), 1)

    def test_history_changed_during_gathering_blocks_synthesis_and_marks_failed(self):
        plan = self.planned()
        self.after_search = lambda: self.messages.items[('conv1', 'a2')].update(
            metadata={'masked': True}
        )
        events = frames(self.run_plan(plan))
        self.assertTrue(any('context changed' in event.get('error', '').lower() for event in events))
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['status'], 'failed')

    def test_replanning_reuses_the_user_message_and_history_cutoff(self):
        first = self.planned()
        second = self.planned(revision=1)
        first_run = self.runs.read_item(first['run_id'], 'conv1')
        second_run = self.runs.read_item(second['run_id'], 'conv1')
        self.assertEqual(first_run['user_message_id'], second_run['user_message_id'])
        self.assertEqual(first_run['conversation_context'], second_run['conversation_context'])
        self.assertEqual(second['revision'], 1)
        self.assertEqual(sum(row.get('content') == LATEST for row in self.messages.items.values()), 1)

    def test_retry_after_plan_persistence_failure_does_not_duplicate_user_message(self):
        self.runs.fail_writes = True
        _, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events))
        self.runs.fail_writes = False
        self.planned()
        self.assertEqual(sum(row.get('content') == LATEST for row in self.messages.items.values()), 1)

    def clarification(self, question='Which location do you mean?', **request_overrides):
        self.model.resolution_override = {
            'relationship': 'clarification', 'resolved_message': LATEST,
            'message_ids': ['u1', 'u2'], 'requires_retrieval': True,
            'clarification': question,
        }
        _, events = self.plan(**request_overrides)
        return next(event['elicitation'] for event in events if event.get('type') == 'orchestration_elicitation')

    def test_clarification_answer_survives_replan_and_execution(self):
        elicitation = self.clarification()
        self.model.resolution_override = None
        plan = self.planned(
            revision=1, elicitation=elicitation,
            elicitation_response={'action': 'accept', 'content': {'clarification': 'Grants Pass'}},
        )
        self.assertEqual(plan['revision'], 1)
        stored = self.runs.read_item(plan['run_id'], 'conv1')
        self.assertEqual(stored['answered_questions'][0]['answer'], {'clarification': 'Grants Pass'})
        self.run_plan(plan)
        self.assertIn('Clarification answers', self.model.calls[-1]['messages'][-1]['content'])
        self.assertIn('Which location', self.model.calls[-1]['messages'][-1]['content'])

    def test_declined_clarification_is_not_asked_again(self):
        elicitation = self.clarification()
        plan = self.planned(
            revision=1, elicitation=elicitation,
            elicitation_response={'action': 'decline', 'content': {}},
        )
        self.assertEqual([step['capability_id'] for step in plan['steps']], ['respond'])
        self.assertEqual(self.search_queries, [])
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['answered_questions'][0]['action'], 'decline')

    def test_successive_clarifications_preserve_answers_without_creating_phantom_runs(self):
        first = self.clarification()
        self.model.resolution_override['clarification'] = 'Which day?'
        _, events = self.plan(
            revision=1, elicitation=first,
            elicitation_response={'action': 'accept', 'content': {'clarification': 'Seattle'}},
        )
        second = next(event['elicitation'] for event in events if event.get('type') == 'orchestration_elicitation')
        pending = self.route.get_pending_turn_context('conv1', 'user1', 'turn1')
        self.assertEqual(pending['answered_questions'][0]['answer'], {'clarification': 'Seattle'})
        self.assertNotEqual(first['elicitation_id'], second['elicitation_id'])
        self.assertEqual(self.client.get(
            '/api/v2/orchestration/runs?conversation_id=conv1'
        ).get_json()['runs'], [])
        self.assertEqual(self.client.post('/api/v2/orchestration/run', json={
            'conversation_id': 'conv1', 'run_id': pending['id'],
        }).status_code, 404)

        self.model.resolution_override = {
            'relationship': 'follow_up', 'resolved_message': 'Find Seattle wineries open Wednesday.',
            'message_ids': [], 'requires_retrieval': True, 'clarification': '',
        }
        plan = self.planned(
            revision=2, elicitation=second,
            elicitation_response={'action': 'accept', 'content': {'clarification': 'Wednesday'}},
        )
        stored = self.runs.read_item(plan['run_id'], 'conv1')
        self.assertEqual([answer['answer'] for answer in stored['answered_questions']], [
            {'clarification': 'Seattle'}, {'clarification': 'Wednesday'},
        ])
        self.assertEqual(stored['turn_index'], 0)
        self.assertEqual(stored['planning_token_usage']['total_tokens'], 60)
        self.assertIsNone(self.route.get_pending_turn_context('conv1', 'user1', 'turn1'))
        self.run_plan(plan)
        self.assertIn('Seattle', self.model.calls[-1]['messages'][-1]['content'])
        self.assertIn('Wednesday', self.model.calls[-1]['messages'][-1]['content'])
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['token_usage']['total_tokens'], 75)

    def test_pending_question_must_be_saved_before_it_is_shown(self):
        self.model.resolution_override = {
            'relationship': 'clarification', 'resolved_message': LATEST,
            'message_ids': [], 'requires_retrieval': False, 'clarification': 'Which place?',
        }
        self.runs.fail_writes = True
        _, events = self.plan()
        self.assertTrue(any(event.get('error') for event in events))
        self.assertFalse(any(event.get('type') == 'orchestration_elicitation' for event in events))

    def test_stale_pending_completion_cannot_overwrite_newer_answers(self):
        first = self.clarification()
        original = self.route.get_pending_turn_context('conv1', 'user1', 'turn1')
        self.model.resolution_override['clarification'] = 'Which day?'
        self.plan(
            revision=1, elicitation=first,
            elicitation_response={'action': 'accept', 'content': {'clarification': 'Seattle'}},
        )
        with self.assertRaises(self.modules.context.ConversationContextError):
            self.route.save_pending_turn_context(
                'conv1', 'user1', 'turn1', user_message=LATEST,
                snapshot=original['conversation_context'], answered_questions=[],
                elicitation={**first, 'revision': 1}, planning_token_usage={},
                expected_pending=original,
            )
        current = self.route.get_pending_turn_context('conv1', 'user1', 'turn1')
        self.assertEqual(current['answered_questions'][0]['answer'], {'clarification': 'Seattle'})
        self.assertEqual(current['elicitation']['message'], 'Which day?')

    def test_clarification_uses_the_saved_schema_not_a_browser_replacement(self):
        elicitation = self.clarification()
        elicitation['requested_schema']['properties']['clarification']['type'] = 'number'
        elicitation['message'] = 'A forged question'
        _, events = self.plan(
            revision=1, elicitation=elicitation,
            elicitation_response={'action': 'accept', 'content': {'clarification': 123}},
        )
        self.assertFalse(any(event.get('error') for event in events))
        pending = self.route.get_pending_turn_context('conv1', 'user1', 'turn1')
        answer = pending['answered_questions'][0]
        self.assertEqual(answer['answer'], {'clarification': '123'})
        self.assertEqual(answer['question'], 'Which location do you mean?')

    def test_accepted_url_answer_reaches_planning_and_execution_allowlists(self):
        elicitation = self.clarification(question='Which URL?', message='Summarize the report.')
        self.model.resolution_override = {
            'relationship': 'follow_up', 'resolved_message': 'Summarize https://example.com/report',
            'message_ids': [], 'requires_retrieval': True, 'clarification': '',
        }
        with patch.object(self.route, '_capability_request_context', wraps=self.route._capability_request_context) as request_context:
            plan = self.planned(
                message='Summarize the report.', revision=1, elicitation=elicitation,
                elicitation_response={'action': 'accept', 'content': {
                    'clarification': 'https://example.com/report',
                }},
            )
        self.assertEqual(request_context.call_args.kwargs['allowed_user_urls'], ['https://example.com/report'])
        contexts = []
        context_class = self.route.RunContext

        def capture_context(**kwargs):
            context = context_class(**kwargs)
            contexts.append(context)
            return context

        with patch.object(self.route, 'RunContext', side_effect=capture_context):
            self.run_plan(plan)
        self.assertEqual(contexts[0].allowed_user_urls, ['https://example.com/report'])

    def test_incomplete_or_mismatched_clarification_is_explicitly_rejected(self):
        response, _ = self.plan(elicitation_response={'action': 'accept', 'content': {}})
        self.assertEqual(response.status_code, 400)
        response, _ = self.plan(
            elicitation={'turn_id': 'another-turn'},
            elicitation_response={'action': 'accept', 'content': {}},
        )
        self.assertEqual(response.status_code, 400)

    def test_history_transformation_bypasses_retrieval_but_keeps_answer_context(self):
        self.model.resolution_override = {
            'relationship': 'follow_up',
            'resolved_message': 'Put the previously listed Grants Pass wineries in a table.',
            'message_ids': ['u2', 'a2'], 'requires_retrieval': False, 'clarification': '',
        }
        plan = self.planned(message='Put those in a table.')
        self.assertEqual([step['capability_id'] for step in plan['steps']], ['respond'])
        self.run_plan(plan)
        self.assertEqual(self.search_queries, [])
        self.assertEqual(len(self.model.calls), 2)
        self.assertIn('Schmidt', json.dumps(self.model.calls[-1]))

    def test_legacy_pending_run_uses_its_saved_user_message_cutoff(self):
        plan = self.planned()
        record = self.runs.items[('conv1', plan['run_id'])]
        for field in ('conversation_context', 'request_resolution', 'resolved_message', 'user_message_fingerprint'):
            record.pop(field)
        self.messages.upsert_item(message(
            'later', 'assistant', 'LATER TEXT MUST NOT LEAK', timestamp='2099-01-01T00:00:00+00:00'
        ))
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('LATER TEXT MUST NOT LEAK', json.dumps(self.model.calls[-1]))
        self.assertIn('Schmidt', json.dumps(self.model.calls[-1]))

    def test_legacy_pending_run_without_cutoff_requires_replanning(self):
        plan = self.planned()
        record = self.runs.items[('conv1', plan['run_id'])]
        record.pop('conversation_context')
        record.pop('user_message_id')
        self.assertEqual(self.run_plan(plan).status_code, 409)

    def test_hydrated_legacy_context_is_revalidated_before_synthesis(self):
        plan = self.planned()
        record = self.runs.items[('conv1', plan['run_id'])]
        for field in ('conversation_context', 'request_resolution', 'resolved_message', 'user_message_fingerprint'):
            record.pop(field)
        self.after_search = lambda: self.messages.items[('conv1', 'a2')].update(
            metadata={'masked': True}
        )
        events = frames(self.run_plan(plan))
        self.assertTrue(any('context changed' in event.get('error', '').lower() for event in events))
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['status'], 'failed')

    def test_run_list_does_not_expose_internal_history_snapshot(self):
        self.planned()
        response = self.client.get('/api/v2/orchestration/runs?conversation_id=conv1')
        self.assertEqual(response.status_code, 200)
        for record in response.get_json()['runs']:
            self.assertNotIn('conversation_context', record)
            self.assertNotIn('request_resolution', record)
            self.assertNotIn('user_message_fingerprint', record)

    def test_ledger_does_not_reintroduce_masked_turn_context(self):
        plan = self.planned()
        self.run_plan(plan)
        record = self.runs.items[('conv1', plan['run_id'])]
        record['plan_summary']['intent_summary'] = 'REDACTED TURN DETAIL'
        record['answered_questions'] = [{'question': 'Hidden detail?', 'answer': 'REDACTED TURN DETAIL'}]
        self.messages.items[('conv1', record['user_message_id'])]['metadata']['masked'] = True
        self.messages.items[('conv1', record['assistant_message_id'])]['metadata']['masked'] = True
        self.model.calls.clear()
        self.planned(turn_id='next-turn')
        self.assertNotIn('REDACTED TURN DETAIL', json.dumps(self.model.calls))


if __name__ == '__main__':
    assert_app_version_at_least('0.261.096')
    unittest.main()
