# orchestration_recovery.py
"""Offline browser-to-Flask recovery fixture using real routes and checkpoints.

Version: 0.261.139
Implemented in: 0.261.105
Single orchestration contract updated in: 0.261.139
Use ``with RecoveryFixture() as fixture``. ``plan_attempt()``, ``run_attempt(plan)``,
``detail(run_id)`` and ``retry(run_id, **overrides)`` operate through the Flask client.
``calls`` records gather adapter invocations; ``fail_b`` controls the failed step.
"""

import importlib
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

# Keep NumPy's native runtime outside per-test sys.modules snapshots. Reloading
# Semantic Kernel otherwise registers hundreds of DLL search paths on Windows.
import numpy  # noqa: F401
import pytest
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_harness_routes import login
from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_harness_execution import HarnessEnvironment, input_binding
from test_support.orchestration_results import complete


DEFAULT_ANSWER = 'Completed answer using Saved findings a, Saved findings b, and Saved findings c.'
# Catalog reads are storage I/O; the agent itself never runs (its adapter is replaced).
RECOVERY_AGENT = {
    'id': 'agent1', 'name': 'RecoveryAgent', 'display_name': 'Recovery agent',
    'scope_type': 'global', 'scope_id': 'global', 'is_global': True, 'is_group': False,
    'agent_type': 'aifoundry', 'catalog_key': 'global:global:agent1',
}


def frames(response):
    return [
        json.loads(line[5:].strip())
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith('data:') and line[5:].strip() != '[DONE]'
    ]


class RecoveryModelBoundary:
    def __init__(self, harness):
        self.harness = harness
        self.answer_error = None

    @property
    def calls(self):
        return self.harness.model_calls

    @calls.setter
    def calls(self, value):
        self.harness.model_calls = value

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self.harness.client().chat.completions.create))


class RecoveryFixture(unittest.TestCase):
    __test__ = False

    def setUp(self):
        self._offline = offline_app_imports()
        self._offline.__enter__()
        self.monkeypatch = pytest.MonkeyPatch()
        self.harness = HarnessEnvironment(self.monkeypatch)
        self.modules = SimpleNamespace(
            route=importlib.import_module('route_backend_orchestration'),
            auth=importlib.import_module('functions_authentication'),
            executor=importlib.import_module('functions_orchestration_executor'),
            schema=importlib.import_module('functions_orchestration_schema'),
            run_store=importlib.import_module('functions_orchestration_runs'),
        )
        self.route = self.modules.route
        self.settings = self.harness.settings
        self.settings.update(enable_semantic_kernel=True, allow_user_agents=True)
        # The production route reads these module globals; bind them to this fixture's
        # isolated containers exactly as the HTTP harness does, so nothing leaks between tests.
        self.monkeypatch.setattr(self.route, 'cosmos_conversations_container', self.harness.conversations)
        self.monkeypatch.setattr(self.route, 'cosmos_messages_container', self.harness.messages)
        self.monkeypatch.setattr(self.route, 'get_settings', lambda: dict(self.settings))
        self.monkeypatch.setattr(self.route, 'get_user_settings', lambda user_id: {'settings': {}})
        for module in (self.route, self.harness.execution, self.harness.bootstrap):
            if hasattr(module, 'resolve_agent_catalog'):
                self.monkeypatch.setattr(
                    module, 'resolve_agent_catalog', lambda *args, **kwargs: [deepcopy(RECOVERY_AGENT)],
                )
        self.monkeypatch.setattr(self.route, 'capture_execution_identity', lambda *args, **kwargs: None)
        self.monkeypatch.setattr(self.route, 'load_orchestration_memory', lambda *args, **kwargs: {
            'audience': {'kind': 'personal', 'owner_id': self.user_id, 'collaboration_id': ''},
            'scope': None, 'context_messages': [], 'notices': [],
        })
        self.monkeypatch.setattr(self.harness.execution, 'load_orchestration_memory', lambda *args, **kwargs: {
            'audience': {'kind': 'personal', 'owner_id': self.user_id, 'collaboration_id': ''},
            'scope': None, 'context_messages': [], 'notices': [],
        })
        self.calls = []
        self.fail_b = True
        self.before_adapter = None
        self.model = RecoveryModelBoundary(self.harness)
        self.conversation_id = 'conv1'
        self.user_id = 'owner'
        self.harness.conversations.upsert_item({'id': self.conversation_id, 'user_id': self.user_id, 'title': 'Recovery'})
        self.messages = self.harness.messages
        self.runs = self.harness.runs
        self.steps = self.harness.steps
        self.messages.upsert_item({
            'id': 'user_turn_recovery', 'conversation_id': self.conversation_id, 'role': 'user',
            'content': 'Recover this orchestration attempt.', 'timestamp': '2026-09-21T18:00:00+00:00',
            'metadata': {'orchestration_turn_id': 'turn-recovery'},
        })

        original_adapter = self.modules.executor._dependency_adapter
        schema = self.modules.schema
        results = importlib.import_module('functions_orchestration_results')

        def gather_adapter(step, context, **kwargs):
            self.calls.append(step['step_id'])
            if self.before_adapter:
                self.before_adapter(step, context, kwargs)
            if step['step_id'] == 'b' and self.fail_b:
                return schema.build_step_result(
                    status=schema.STEP_STATUS_FAILED,
                    failure=schema.build_failure('step_timeout'),
                    error='SECRET_SENTINEL https://private.test/<script>private</script>',
                    summary='A planned step timed out before returning results.',
                )
            if step['capability_id'] == 'agent_invoke':
                # The agent's findings are retained as source-free prepared content through
                # the real result service; external agent acquisition is out of scope here.
                prepared = {
                    'version': 'orchestration-gathered-content-v1', 'capability_id': 'agent_invoke',
                    'content_scope': 'reported_external_content', 'evidence': [], 'citations': [],
                    'notes': [f"Saved findings {step['step_id']}"],
                    'limitations': ['Reported agent findings, not whole-source coverage.'],
                }
                task = context.result_service.persist_task_result(
                    producer=context.result_producer(step), role='gather', status='complete',
                    outputs=[results.NamedOutput('prepared', 'structured-v1', prepared, complete(1))],
                    sources=[], origin='generated',
                    guard_token=context.result_guard_token_for_step(step['step_id']),
                    input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
                )
                return schema.build_step_result(task_result=task, summary=f"Saved findings {step['step_id']}")
            return schema.build_step_result(
                notes=[f"Saved findings {step['step_id']}"],
                summary=f"Saved findings {step['step_id']}",
            )

        def dependency_adapter(capability_id):
            if capability_id in ('document_search', 'agent_invoke'):
                return gather_adapter
            return original_adapter(capability_id)

        self.monkeypatch.setattr(self.modules.executor, '_dependency_adapter', dependency_adapter)
        self.monkeypatch.setattr(self.harness.execution, '_dependency_adapter', dependency_adapter, raising=False)
        original_client = self.harness.client

        def client_factory(**kwargs):
            client = original_client(**kwargs)
            original_create = client.create

            def create(**call_kwargs):
                if self.model.answer_error is not None:
                    self.harness.model_calls.append(deepcopy(call_kwargs))
                    raise self.model.answer_error
                if not self.harness.replies:
                    self.harness.replies.append(DEFAULT_ANSWER)
                return original_create(**call_kwargs)

            client.chat.completions.create = create
            return client

        # Every model client the application builds comes from the planner's client class.
        self.monkeypatch.setattr(self.harness.planner, 'AzureOpenAI', client_factory)
        self.harness.client = client_factory
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='recovery-real-route-test')
        blueprint = Blueprint('backend_orchestration', __name__)
        blueprint.before_request(self.modules.auth.user_required_blueprint())
        self.route.register_route_backend_orchestration(blueprint)
        app.register_blueprint(blueprint)
        self.app = app
        self.client = Client(app, Response)
        login(SimpleNamespace(app=app, client=self.client), user_id=self.user_id)

    def __enter__(self):
        try:
            self.setUp()
        except Exception:
            self.doCleanups()
            raise
        return self

    def __exit__(self, *_args):
        self.doCleanups()

    def doCleanups(self):
        try:
            if hasattr(self, 'monkeypatch'):
                self.monkeypatch.undo()
        finally:
            try:
                if hasattr(self, '_offline'):
                    try:
                        self._offline.__exit__(None, None, None)
                    except RuntimeError as exc:
                        if 'Cannot run the event loop while another loop is running' not in str(exc):
                            raise
            finally:
                super().doCleanups()

    def _plan_document(self):
        return self.modules.schema.normalize_plan(
            {
                'run_id': 'recovery-run', 'plan_id': 'recovery-plan', 'turn_id': 'turn-recovery',
                'kind': 'plan', 'intent': {'summary': 'Gather two results.', 'complexity': 'simple'},
                'steps': [
                    {'step_id': 'a', 'capability_id': 'document_search', 'title': 'Gather A', 'arguments': {'query': 'A'}},
                    {
                        'step_id': 'b', 'capability_id': 'agent_invoke', 'title': 'Gather B',
                        'arguments': {'agent_name': 'RecoveryAgent', 'task': 'B'}, 'depends_on': ['a'],
                    },
                    {'step_id': 'c', 'capability_id': 'document_search', 'title': 'Gather C', 'arguments': {'query': 'C'}, 'depends_on': ['b']},
                    {
                        'step_id': 'answer', 'capability_id': 'compose', 'title': 'Answer',
                        'arguments': {'instruction': 'Answer from the gathered findings.', 'knowledge_basis': 'sources'},
                        'inputs': {
                            name: {'binding': input_binding(name, 'prepared'), 'allow_partial': False}
                            for name in ('a', 'b', 'c')
                        },
                        'outputs': [{'name': 'answer', 'kind': 'markdown-v1'}],
                    },
                ],
                'final_response': input_binding('answer'),
            },
            self.conversation_id, self.user_id, settings=self.settings,
            available_capability_ids=['document_search', 'agent_invoke', 'compose'],
            agent_names=['RecoveryAgent'],
        )

    def plan_attempt(self):
        plan = self._plan_document()
        normalized = importlib.import_module('functions_orchestration_context').normalize_history_message(
            self.messages.read_item('user_turn_recovery', self.conversation_id),
        )
        turn_context = {
            'turn_id': 'turn-recovery', 'user_message': 'Recover this orchestration attempt.',
            'user_message_id': 'user_turn_recovery', 'user_message_fingerprint': normalized['fingerprint'],
            'resolved_message': 'Recover this orchestration attempt.',
            'request_resolution': {'relationship': 'new_topic', 'message_ids': [], 'requires_retrieval': True, 'clarification': ''},
            'seeds': {}, 'original_seeds': {}, 'answered_questions': [], 'planning_token_usage': {},
            'memory_audience': {'kind': 'personal', 'owner_id': self.user_id, 'collaboration_id': ''},
            'memory_scope': None,
        }
        record = self.modules.run_store.create_orchestration_run(
            plan, self.user_id, self.conversation_id, turn_index=1, turn_context=turn_context,
        )
        return record['plan']

    def run_attempt(self, plan):
        self.harness.replies = [
            self.model.answer_error if self.model.answer_error is not None else DEFAULT_ANSWER
        ]
        return self.client.post('/api/v2/orchestration/run', json={
            'conversation_id': self.conversation_id, 'run_id': plan['run_id'],
            **({'expected_version': plan['edit_version']} if plan.get('edit_version') else {}),
        }, buffered=True)

    def detail(self, run_id):
        response = self.client.get(f'/api/v2/orchestration/runs/{run_id}?conversation_id={self.conversation_id}')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()['run']

    def retry(self, run_id, **overrides):
        body = {
            'conversation_id': self.conversation_id, 'submission_id': 'retry-submission',
            'expected_version': self.detail(run_id)['recovery']['expected_version'],
            'confirm_external_effects': True, **overrides,
        }
        return self.client.post(f'/api/v2/orchestration/runs/{run_id}/retry', json=body)
