# test_orchestration_conversation_context_routes.py
"""
Functional tests for conversation context across real orchestration HTTP/SSE routes.
Version: 0.261.105
Implemented in: 0.261.096
Prompt attachment integration: 0.261.097
Direct action integration: 0.261.098
Resolver response compatibility and bounded recovery: 0.261.103
Authorized model routing and completion metadata: 0.261.103
Atomic plan revision persistence: 0.261.102

Uses Flask, the real planner/executor/adapters/run store, an in-memory Cosmos boundary,
and deterministic model completions. Authentication is a signed-in test user; actual
conversation ownership checks remain active. No external service is contacted.
"""

import hashlib
import importlib
import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.core.exceptions import AzureError
from flask import Blueprint, Flask, has_request_context
from httpx import Request as HttpRequest, Response as HttpResponse
from openai import BadRequestError
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_conversation_context import (
    LATEST, RESOLVED, fake_module, load_modules, message, winery_history,
)
from test_orchestration_model_selection import TERRA_SELECTION, endpoint_runtime, model_endpoint
from test_support.app_stubs import APP_ROOT, stubbed_config
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least
from test_unified_logging_entrypoint import _install_logging_stubs, _restore_modules


MemoryContainer = AtomicMemoryContainer


class ModelBoundary:
    def __init__(self, modules):
        self.modules = modules
        self.calls = []
        self.resolution_override = None
        self.resolution_responses = []
        self.plan_override = None
        self.answer_response = None
        self.answer_error = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        system = kwargs['messages'][0]['content']
        if system == self.modules.planner.RESOLUTION_SYSTEM_PROMPT:
            payload = self.resolution_responses.pop(0) if self.resolution_responses else self.resolution_override
            text = json.dumps(payload if payload is not None else {
                'relationship': 'follow_up',
                'resolved_message': RESOLVED,
                'message_ids': ['u1', 'u2', 'a2'],
                'requires_retrieval': True,
                'clarification': '',
            })
        elif system == self.modules.planner.PLANNER_SYSTEM_PROMPT:
            request_text = json.loads(kwargs['messages'][1]['content'])['message']
            text = json.dumps(self.plan_override or {
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
            if self.answer_error is not None:
                raise self.answer_error
            if self.answer_response is not None:
                return self.answer_response
            text = 'You mean the wineries near Grants Pass. I do not have verified Wednesday hours.'
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=text))],
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

    def use_modern_models(self):
        self.endpoint = model_endpoint()
        self.model_clients = []
        self.model_runtime = endpoint_runtime(self.endpoint, None)

        def build_client(*args, **kwargs):
            self.assertTrue(has_request_context(), 'Model authorization must stay on the request thread.')
            client = SimpleNamespace(chat=self.model.chat, close=Mock())
            self.model_clients.append(client)
            return client, 'azure_openai'

        self.model_runtime.build_model_endpoint_sync_chat_client.side_effect = build_client
        self.settings.update({
            'enable_multi_model_endpoints': True,
            'default_model_selection': {
                'endpoint_id': 'selected-endpoint', 'model_id': 'terra-model', 'provider': 'aoai',
            },
            'gpt_model': {'selected': [{'deploymentName': 'gpt-4o'}]},
        })
        patcher = patch.dict(sys.modules, {'functions_model_endpoint_runtime': self.model_runtime})
        patcher.start()
        self.addCleanup(patcher.stop)
        return dict(TERRA_SELECTION)

    def test_manual_model_is_used_for_resolution_planning_and_answer_in_all_approval_modes(self):
        selection = self.use_modern_models()
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        for mode in ('auto', 'timed', 'manual'):
            with self.subTest(mode=mode):
                self.messages.items.clear()
                self.runs.items.clear()
                self.model.calls.clear()
                for row in winery_history():
                    self.messages.upsert_item(row)
                plan = self.planned(**selection, reasoning_effort='high', approval_mode=mode)
                stored = self.runs.read_item(plan['run_id'], 'conv1')
                self.assertEqual(stored['seeds']['model'], selection)
                self.assertEqual(stored['seeds']['reasoning_effort'], 'high')
                self.assertEqual(stored['plan']['planner_model'], 'gpt-5.6-terra')
                events = frames(self.run_plan(plan))
                self.assertFalse(any(event.get('error') for event in events), events)
                self.assertEqual(len(self.model.calls), 3)
                for call in self.model.calls:
                    self.assertEqual(call['model'], 'gpt-5.6-terra')
                    self.assertEqual(call['reasoning_effort'], 'high')
                    self.assertIn('max_completion_tokens', call)
                    self.assertNotIn('max_tokens', call)
                    self.assertNotIn('temperature', call)
                updated = self.runs.read_item(plan['run_id'], 'conv1')
                answer = self.messages.read_item(updated['assistant_message_id'], 'conv1')
                terminal = next(event for event in events if event.get('type') == 'orchestration_done')
                for key, value in {
                    'model_deployment_name': 'gpt-5.6-terra', 'model_provider': 'aoai',
                    'model_endpoint_id': 'selected-endpoint', 'model_id': 'terra-model',
                }.items():
                    self.assertEqual(answer[key], value)
                    self.assertEqual(terminal[key], value)
                self.assertEqual(updated['token_usage']['total_tokens'], 45)
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_stale_luna_minimal_is_corrected_through_every_approval_mode(self):
        selection = self.use_modern_models()
        selection.update(model_id='luna-model', model_deployment='gpt-5.6-luna')
        normal_completion = self.model.chat.completions.create

        def reject_unsupported_minimal(**kwargs):
            if kwargs.get('reasoning_effort') == 'minimal':
                raise BadRequestError(
                    "Unsupported reasoning_effort: minimal. Supported values: none, low, medium, high, xhigh.",
                    response=HttpResponse(400, request=HttpRequest('POST', 'https://model.example.test')),
                    body={'error': {'code': 'unsupported_value', 'param': 'reasoning_effort'}},
                )
            return normal_completion(**kwargs)

        self.model.chat.completions.create = reject_unsupported_minimal
        for mode in ('auto', 'timed', 'manual'):
            with self.subTest(mode=mode):
                self.messages.items.clear()
                self.runs.items.clear()
                self.model.calls.clear()
                for row in winery_history():
                    self.messages.upsert_item(row)
                plan = self.planned(**selection, reasoning_effort='minimal', approval_mode=mode)
                self.assertEqual(plan['reasoning_adjustments'][0]['effective_effort'], 'low')
                events = frames(self.run_plan(plan))
                self.assertFalse(any(event.get('error') for event in events), events)
                self.assertEqual(len(self.model.calls), 3)
                for call in self.model.calls:
                    self.assertEqual(call['model'], 'gpt-5.6-luna')
                    self.assertEqual(call['reasoning_effort'], 'low')
                terminal = next(event for event in events if event.get('type') == 'orchestration_done')
                self.assertEqual(terminal['requested_reasoning_effort'], 'minimal')
                self.assertEqual(terminal['reasoning_effort'], 'low')
                self.assertEqual(terminal['reasoning_mode'], 'explicit')
                self.assertEqual({item['stage'] for item in terminal['reasoning_adjustments']}, {'planner', 'answer'})
                stored = self.runs.read_item(plan['run_id'], 'conv1')
                answer = self.messages.read_item(stored['assistant_message_id'], 'conv1')
                self.assertEqual(answer['reasoning_effort'], 'low')
                self.assertEqual(answer['requested_reasoning_effort'], 'minimal')

    def test_admin_default_is_pinned_to_the_plan_and_cannot_be_retargeted_at_run_time(self):
        self.use_modern_models()
        plan = self.planned()
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        response = self.client.post('/api/v2/orchestration/run', json={
            'run_id': plan['run_id'], 'conversation_id': 'conv1',
            'model_id': 'luna-model', 'model_deployment': 'gpt-5.6-luna',
        }, buffered=True)
        self.assertFalse(any(event.get('error') for event in frames(response)))
        self.assertEqual({call['model'] for call in self.model.calls}, {'gpt-5.6-terra'})
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['seeds']['model'], TERRA_SELECTION)

    def test_malformed_model_step_lists_never_publish_an_executable_plan(self):
        for proposal in (
            {'kind': 'plan'}, {'kind': 'plan', 'steps': []},
            {'kind': 'plan', 'steps': 'not-a-list'},
        ):
            with self.subTest(proposal=proposal):
                self.model.plan_override = proposal
                _response, events = self.plan()
                self.assertTrue(any(event.get('error') for event in events), events)
                self.assertFalse(any(event.get('type') == 'orchestration_plan' for event in events))
                self.assertFalse(any(row.get('plan') for row in self.runs.items.values()))

    def test_replanning_uses_the_original_model_not_replacement_answer_controls(self):
        self.use_modern_models()
        self.planned()
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        plan = self.planned(**{
            **TERRA_SELECTION, 'model_id': 'luna-model', 'model_deployment': 'gpt-5.6-luna',
        })
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['seeds']['model'], TERRA_SELECTION)
        self.assertEqual({call['model'] for call in self.model.calls}, {'gpt-5.6-terra'})

    def test_planner_override_does_not_change_the_selected_answer_or_research_binding(self):
        selection = self.use_modern_models()
        self.settings['chat_orchestration_planner_deployment'] = 'small-planner'
        contexts = []
        run_context = self.route.RunContext

        def capture_context(**kwargs):
            context = run_context(**kwargs)
            contexts.append(context)
            return context

        with patch.object(
            self.modules.planner, 'resolve_planner_client',
            side_effect=lambda settings: (self.model, settings['chat_orchestration_planner_deployment']),
        ), patch.object(self.route, 'RunContext', side_effect=capture_context):
            plan = self.planned(**selection)
            events = frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.assertEqual([call['model'] for call in self.model.calls], [
            'small-planner', 'small-planner', 'gpt-5.6-terra',
        ])
        self.assertEqual(contexts[0].gpt_model, 'gpt-5.6-terra')
        self.assertEqual(contexts[0].planner_deployment, 'small-planner')
        client, deployment = self.modules.adapters._resolve_source_review_planner(self.settings, contexts[0])
        self.assertIs(client, contexts[0].planner_client)
        self.assertEqual(deployment, 'small-planner')
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['seeds']['model'], selection)

    def test_revoked_model_access_stops_an_approved_run_instead_of_falling_back(self):
        selection = self.use_modern_models()
        plan = self.planned(**selection)
        self.model_runtime.resolve_model_endpoint_from_context.return_value = None
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 403)
        self.assertIn('selected model is unavailable', response.get_json()['error'])
        self.assertEqual(len(self.model.calls), 2)
        self.assertTrue(all(call['model'] == 'gpt-5.6-terra' for call in self.model.calls))
        self.assertEqual(self.model_runtime.resolve_model_endpoint_from_context.call_count, 2)
        self.assertTrue(self.model_runtime.resolve_model_endpoint_from_context.call_args.kwargs['authorize'])
        self.assertEqual(self.model_runtime.build_model_endpoint_sync_chat_client.call_count, 1)

    def test_run_claim_conflict_releases_the_prepared_model_client(self):
        self.use_modern_models()
        plan = self.planned()
        conflict = self.route.PlanRevisionError('The plan changed.', code='plan_changed')
        with patch.object(self.route, 'claim_plan_run', side_effect=conflict):
            response = self.run_plan(plan)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'plan_changed')
        self.assertEqual(len(self.model_clients), 2)
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_model_id_only_planner_override_also_reaches_research_execution(self):
        self.use_modern_models()
        self.settings.update({
            'chat_orchestration_planner_model_endpoint_id': 'selected-endpoint',
            'chat_orchestration_planner_model_id': 'luna-model',
        })
        contexts = []
        run_context = self.route.RunContext

        def capture_context(**kwargs):
            context = run_context(**kwargs)
            contexts.append(context)
            return context

        with patch.object(self.route, 'RunContext', side_effect=capture_context):
            plan = self.planned()
            events = frames(self.run_plan(plan))
        self.assertFalse(any(event.get('error') for event in events), events)
        self.assertEqual([call['model'] for call in self.model.calls], [
            'gpt-5.6-luna', 'gpt-5.6-luna', 'gpt-5.6-terra',
        ])
        self.assertEqual(contexts[0].planner_deployment, 'gpt-5.6-luna')
        self.assertEqual(contexts[0].gpt_model, 'gpt-5.6-terra')
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['seeds']['model'], TERRA_SELECTION)
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_research_model_initialization_failure_closes_the_created_answer_client(self):
        self.use_modern_models()
        plan = self.planned()
        self.settings['chat_orchestration_planner_deployment'] = 'small-planner'
        self.model_runtime.resolve_model_endpoint_from_context.side_effect = [self.endpoint, None]
        response = self.run_plan(plan)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.model_clients), 2)
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_unstarted_streams_close_their_model_clients(self):
        self.use_modern_models()
        with self.app.test_request_context('/api/v2/orchestration/plan', method='POST', json={
            'message': LATEST, 'conversation_id': 'conv1', 'turn_id': 'abandoned',
        }):
            response = self.app.view_functions['context_test.orchestration_plan']()
        response.close()
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.runs.items, {})
        self.assertEqual(self.model_clients, [])

        plan = self.planned()
        with self.app.test_request_context('/api/v2/orchestration/run', method='POST', json={
            'run_id': plan['run_id'], 'conversation_id': 'conv1',
        }):
            response = self.app.view_functions['context_test.orchestration_run']()
        response.close()
        self.assertEqual(len(self.model.calls), 2)
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_disconnecting_does_not_close_a_model_still_used_by_the_worker(self):
        self.use_modern_models()
        plan = self.planned()
        searching, resume, closed = Event(), Event(), Event()

        def pause_search():
            searching.set()
            self.assertTrue(resume.wait(timeout=10))

        self.after_search = pause_search
        response = self.client.post('/api/v2/orchestration/run', json={
            'run_id': plan['run_id'], 'conversation_id': 'conv1',
        }, buffered=False)
        self.model_clients[-1].close.side_effect = closed.set
        try:
            self.assertTrue(searching.wait(timeout=10))
            response.close()
            self.model_clients[-1].close.assert_not_called()
        finally:
            resume.set()
            self.assertTrue(closed.wait(timeout=10))
        self.model_clients[-1].close.assert_called_once_with()

    def test_unavailable_default_fails_planning_without_creating_a_run(self):
        self.use_modern_models()
        self.model_runtime.resolve_model_endpoint_from_context.return_value = None
        _, events = self.plan()
        self.assertTrue(any('selected model is unavailable' in event.get('error', '') for event in events))
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.runs.items, {})
        self.assertEqual(len(self.messages.items), 4)

    def test_model_failure_releases_clarification_submission_for_retry(self):
        self.use_modern_models()
        self.model.resolution_override = {
            'relationship': 'clarification', 'resolved_message': LATEST,
            'message_ids': ['u1'], 'requires_retrieval': True,
            'clarification': 'Which location do you mean?',
        }
        _, events = self.plan()
        question = next(event['elicitation'] for event in events if event.get('elicitation'))
        reply = {
            'elicitation': question,
            'elicitation_response': {'action': 'accept', 'content': {'clarification': 'Grants Pass'}},
        }
        self.model_runtime.resolve_model_endpoint_from_context.return_value = None
        _, events = self.plan(**reply)
        self.assertTrue(any('selected model is unavailable' in event.get('error', '') for event in events))
        self.model_runtime.resolve_model_endpoint_from_context.return_value = self.endpoint
        self.model.resolution_override = None
        plan = self.planned(**reply)
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['seeds']['model'], TERRA_SELECTION)

    def test_failed_or_empty_answer_is_not_reported_as_a_completed_turn(self):
        self.use_modern_models()
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        for response in (
            SimpleNamespace(choices=[], usage=usage),
            SimpleNamespace(choices=[SimpleNamespace(
                finish_reason='length', message=SimpleNamespace(content='', refusal=None),
            )], usage=usage),
            SimpleNamespace(choices=[SimpleNamespace(
                finish_reason='content_filter',
                message=SimpleNamespace(content='PRIVATE_PROVIDER_RESPONSE', refusal=None),
            )], usage=usage),
            SimpleNamespace(choices=[SimpleNamespace(
                finish_reason='stop',
                message=SimpleNamespace(content='', refusal='PRIVATE_PROVIDER_RESPONSE'),
            )], usage=usage),
        ):
            with self.subTest(response=response):
                self.messages.items.clear()
                self.runs.items.clear()
                for row in winery_history():
                    self.messages.upsert_item(row)
                self.model.answer_response = response
                plan = self.planned()
                events = frames(self.run_plan(plan))
                terminal = next(event for event in events if event.get('type') == 'orchestration_done')
                self.assertEqual(terminal['status'], 'failed')
                self.assertTrue(terminal['message_saved'])
                self.assertTrue(terminal['full_content'])
                self.assertNotIn('PRIVATE_PROVIDER_RESPONSE', json.dumps(events))
                stored = self.runs.read_item(plan['run_id'], 'conv1')
                self.assertEqual(stored['status'], 'failed')
                self.assertTrue(stored.get('assistant_message_id'))
                self.assertEqual(stored['token_usage']['total_tokens'], 45)
        for client in self.model_clients:
            client.close.assert_called_once_with()

    def test_provider_answer_error_is_safe_and_closes_the_bound_client(self):
        self.use_modern_models()
        self.model.answer_error = BadRequestError(
            'PRIVATE_PROVIDER_RESPONSE',
            response=HttpResponse(400, request=HttpRequest('POST', 'https://selected.example.test')),
            body={'error': 'PRIVATE_PROVIDER_RESPONSE'},
        )
        plan = self.planned()
        with patch.object(self.route, 'log_event') as log:
            events = frames(self.run_plan(plan))
        terminal = next(event for event in events if event.get('type') == 'orchestration_done')
        self.assertEqual(terminal['status'], 'failed')
        self.assertEqual(terminal['failure']['provider_status'], 400)
        self.assertNotIn('PRIVATE_PROVIDER_RESPONSE', json.dumps(events))
        self.assertNotIn('PRIVATE_PROVIDER_RESPONSE', repr(log.call_args_list))
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['status'], 'failed')
        for client in self.model_clients:
            client.close.assert_called_once_with()

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
        self.model.resolution_override = {
            'relationship': 'follow_up', 'resolved_message': RESOLVED,
            'message_ids': ['u1', 'u2', 'a2'], 'requires_retrieval': True, 'clarification': None,
        }
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
                self.assertEqual(stored['request_resolution']['clarification'], '')
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

    def test_new_conversation_second_question_accepts_an_unused_null_clarification(self):
        self.use_modern_models()
        self.messages.items.clear()
        first = self.planned(message='Find tide pools near Crescent City.', turn_id='first-turn')
        self.assertFalse(any(event.get('error') for event in frames(self.run_plan(first))))
        first_run = self.runs.read_item(first['run_id'], 'conv1')
        question = 'Find wineries open Wednesday on Route 199 from Medford to Crescent City after 1 PM.'
        self.model.resolution_override = {
            'relationship': 'new_topic', 'resolved_message': question,
            'message_ids': [], 'requires_retrieval': True, 'clarification': None,
        }
        second = self.planned(message=question, turn_id='second-turn')
        second_run = self.runs.read_item(second['run_id'], 'conv1')
        self.assertEqual(
            {item['id'] for item in second_run['conversation_context']['messages']},
            {first_run['user_message_id'], first_run['assistant_message_id']},
        )
        self.assertEqual(second_run['resolved_message'], question)
        self.assertEqual(second_run['request_resolution']['message_ids'], [])
        self.assertEqual(second_run['request_resolution']['clarification'], '')
        self.assertFalse(any(event.get('error') for event in frames(self.run_plan(second))))
        self.assertEqual(self.runs.read_item(second['run_id'], 'conv1')['status'], 'completed')
        self.assertEqual(len([row for row in self.messages.items.values() if row.get('role') in ('user', 'assistant')]), 4)
        resolution_calls = [
            call for call in self.model.calls
            if call['messages'][0]['content'] == self.modules.planner.RESOLUTION_SYSTEM_PROMPT
        ]
        self.assertEqual(len(resolution_calls), 1)
        self.assertEqual({call['model'] for call in self.model.calls}, {'gpt-5.6-terra'})

    def test_repaired_resolution_keeps_context_usage_and_single_turn_persistence(self):
        valid = {
            'relationship': 'follow_up', 'resolved_message': RESOLVED,
            'message_ids': ['u1', 'u2', 'a2'], 'requires_retrieval': True, 'clarification': '',
        }
        self.model.resolution_responses = [
            {**valid, 'message_ids': ['foreign-message']}, valid,
        ]
        plan = self.planned()
        stored = self.runs.read_item(plan['run_id'], 'conv1')
        self.assertEqual(stored['request_resolution']['message_ids'], valid['message_ids'])
        self.assertEqual(len(stored['conversation_context']['messages']), 4)
        self.assertEqual(stored['planning_token_usage']['total_tokens'], 45)
        self.assertFalse(any(event.get('error') for event in frames(self.run_plan(plan))))
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['token_usage']['total_tokens'], 60)
        self.assertEqual(self.search_queries, [RESOLVED, RESOLVED])
        self.assertEqual(sum(row.get('content') == LATEST for row in self.messages.items.values()), 1)
        self.assertEqual(len(self.runs.items), 1)

    def test_persistent_resolution_failure_has_safe_searchable_diagnostics_and_no_writes(self):
        self.model.resolution_override = {
            'relationship': 'follow_up', 'resolved_message': 'PRIVATE_MODEL_TEXT',
            'message_ids': ['u1'], 'requires_retrieval': 'false', 'clarification': '',
        }
        with patch.object(self.route, 'log_event') as route_log, \
                patch.object(self.modules.planner, 'log_event') as planner_log:
            response, events = self.plan()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([event['error'] for event in events if event.get('error')], [
            'The conversation could not be interpreted. Please retry your request.',
        ])
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(len(self.messages.items), 4)
        self.assertEqual(self.runs.items, {})
        self.assertEqual(self.search_queries, [])
        properties = route_log.call_args.kwargs['extra']
        resource = f"conversation:{hashlib.sha256(b'conv1').hexdigest()}"
        self.assertEqual(properties['resource'], resource)
        self.assertEqual(properties['reason'], 'invalid_retrieval_flag')
        self.assertEqual(properties['attempt'], 2)
        logged = repr(route_log.call_args_list) + repr(planner_log.call_args_list)
        for private in ('PRIVATE_MODEL_TEXT', LATEST, 'Schmidt', 'conv1'):
            self.assertNotIn(private, logged)

        saved_modules = _install_logging_stubs(debug_enabled=False)
        try:
            logger = importlib.import_module('functions_appinsights')
            forwarded = logger._build_logger_extra(route_log.call_args.args[0], properties)
            self.assertEqual(forwarded['sc_resource'], resource)
            self.assertEqual(forwarded['sc_reason'], 'invalid_retrieval_flag')
            self.assertEqual(forwarded['sc_attempt'], 2)
        finally:
            _restore_modules(saved_modules)

    def test_action_followup_keeps_resolved_context_and_all_model_usage(self):
        self.use_modern_models()
        self.settings.update({
            'enable_semantic_kernel': True,
            'enable_chat_orchestration_actions': True,
        })
        action = {
            'id': 'hours', 'action_ref': 'personal:user1:hours', 'name': 'hours',
            'display_name': 'Opening hours', 'description': 'Look up winery opening hours.',
            'type': 'openapi', 'scope_type': 'personal', 'scope_id': 'user1',
            'scope_label': 'Personal',
        }
        self.model.plan_override = {
            'kind': 'plan',
            'steps': [
                {'step_id': 'lookup', 'capability_id': 'action_invoke',
                 'arguments': {'action_ref': action['action_ref'], 'task': RESOLVED}},
                {'step_id': 'answer', 'capability_id': 'respond',
                 'arguments': {}, 'depends_on': ['lookup']},
            ],
        }
        calls = []

        async def invoke_action(action_ref, task, context, **kwargs):
            calls.append((action_ref, task, context))
            context.token_usage.update({'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7})
            return {
                'findings': 'No verified Wednesday hours were available.',
                'invocations': [], 'root_id': 'test-action-root', 'calls': 1, 'artifacts': [],
            }

        dependencies = {
            'functions_orchestration_actions': fake_module(
                'functions_orchestration_actions', invoke_action=invoke_action,
            ),
            'semantic_kernel_plugins.plugin_invocation_logger': fake_module(
                'semantic_kernel_plugins.plugin_invocation_logger',
                sanitize_plugin_invocation_value=lambda value: value,
            ),
        }
        with patch('functions_action_catalog.build_accessible_action_catalog', return_value=[action]):
            with patch.dict(sys.modules, dependencies):
                plan = self.planned()
                self.assertEqual(plan['steps'][0]['capability_id'], 'action_invoke')
                self.assertEqual(plan['inputs']['actions'][0]['action_ref'], action['action_ref'])
                planner_call = next(
                    call for call in self.model.calls
                    if call['messages'][0]['content'] == self.modules.planner.PLANNER_SYSTEM_PROMPT
                )
                planner_context = json.loads(planner_call['messages'][1]['content'])
                self.assertEqual(planner_context['message'], RESOLVED)
                self.assertEqual(planner_context['original_message'], LATEST)
                self.assertEqual(planner_context['request_resolution']['message_ids'], ['u1', 'u2', 'a2'])
                self.assertEqual(planner_context['actions'][0]['action_ref'], action['action_ref'])
                response = self.run_plan(plan)

        events = frames(response)
        self.assertFalse(any(event.get('error') for event in events), events)
        self.assertEqual(len(calls), 1)
        action_ref, task, context = calls[0]
        self.assertEqual(action_ref, action['action_ref'])
        self.assertTrue(task.startswith(RESOLVED))
        self.assertIn('Conversation reference', task)
        self.assertIn('Schmidt', task)
        self.assertEqual(context.user_message, LATEST)
        self.assertEqual(context.resolved_message, RESOLVED)
        self.assertEqual(context.context_message_ids, ['u1', 'u2', 'a2'])
        self.assertEqual(context.gpt_model, 'gpt-5.6-terra')
        self.assertEqual(context.model_context, {
            'model_id': 'terra-model', 'endpoint_id': 'selected-endpoint', 'provider': 'aoai',
            'model_deployment': 'gpt-5.6-terra', 'user_id': 'user1', 'active_group_ids': [],
        })
        self.assertEqual(context.planner_deployment, 'gpt-5.6-terra')
        updated = self.runs.read_item(plan['run_id'], 'conv1')
        self.assertEqual(updated['status'], 'completed')
        self.assertEqual(updated['token_usage'], {
            'prompt_tokens': 33, 'completion_tokens': 19, 'total_tokens': 52,
        })
        answer = self.messages.read_item(updated['assistant_message_id'], 'conv1')
        self.assertEqual(answer['metadata']['token_usage'], updated['token_usage'])

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
        terminal = next(event for event in events if event.get('type') == 'orchestration_done')
        self.assertEqual(terminal['failure']['code'], 'context_unavailable')
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
        self.model.plan_override = {
            'kind': 'plan', 'steps': [{'capability_id': 'respond', 'arguments': {}}],
        }
        plan = self.planned(
            revision=1, elicitation=elicitation,
            elicitation_response={'action': 'decline', 'content': {}},
        )
        self.assertEqual([step['capability_id'] for step in plan['steps']], ['respond'])
        self.assertEqual(self.search_queries, [])
        self.assertEqual(self.runs.read_item(plan['run_id'], 'conv1')['answered_questions'][0]['action'], 'decline')
        self.assertTrue(any(
            call['messages'][0]['content'] == self.modules.planner.PLANNER_SYSTEM_PROMPT
            for call in self.model.calls
        ))

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

    def test_planner_can_reuse_history_without_retrieval_and_keeps_answer_context(self):
        self.model.resolution_override = {
            'relationship': 'follow_up',
            'resolved_message': 'Put the previously listed Grants Pass wineries in a table.',
            'message_ids': ['u2', 'a2'], 'requires_retrieval': False, 'clarification': '',
        }
        self.model.plan_override = {
            'kind': 'plan', 'steps': [{'capability_id': 'respond', 'arguments': {}}],
        }
        plan = self.planned(message='Put those in a table.')
        self.assertEqual([step['capability_id'] for step in plan['steps']], ['respond'])
        self.run_plan(plan)
        self.assertEqual(self.search_queries, [])
        self.assertEqual(len(self.model.calls), 3)
        self.assertEqual(self.model.calls[1]['messages'][0]['content'], self.modules.planner.PLANNER_SYSTEM_PROMPT)
        self.assertIn('Schmidt', json.dumps(self.model.calls[-1]))

    def test_short_requests_reach_the_planner_with_available_capabilities(self):
        self.messages.items.clear()
        self.settings['enable_web_search'] = True
        self.model.plan_override = {
            'kind': 'plan', 'steps': [{'capability_id': 'respond', 'arguments': {}}],
        }
        plan = self.planned(message='Hi!', turn_id='short-turn')
        self.assertEqual([step['capability_id'] for step in plan['steps']], ['respond'])
        self.assertEqual(len(self.model.calls), 1)
        call = self.model.calls[0]
        self.assertEqual(call['messages'][0]['content'], self.modules.planner.PLANNER_SYSTEM_PROMPT)
        context = json.loads(call['messages'][1]['content'])
        self.assertIn('web_search', context['capability_availability']['available'])
        self.assertNotIn('web_search', context['user_selected'])

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
        terminal = next(event for event in events if event.get('type') == 'orchestration_done')
        self.assertEqual(terminal['failure']['code'], 'context_unavailable')
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
    assert_app_version_at_least('0.261.103')
    unittest.main()
