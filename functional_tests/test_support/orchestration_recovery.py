# orchestration_recovery.py
"""Offline browser-to-Flask recovery fixture using real routes and checkpoints.

Version: 0.261.105
Implemented in: 0.261.105
Use ``with RecoveryFixture() as fixture``. ``plan_attempt()``, ``run_attempt(plan)``,
``detail(run_id)`` and ``retry(run_id, **overrides)`` operate through the Flask client.
``calls`` records gather adapter invocations; ``fail_b`` controls the failed step.
"""

import unittest
from copy import deepcopy
from unittest.mock import patch

# Keep NumPy's native runtime outside per-test sys.modules snapshots. Reloading
# Semantic Kernel otherwise registers hundreds of DLL search paths on Windows.
import numpy

import test_orchestration_conversation_context_routes as context_routes


frames = context_routes.frames


class RecoveryFixture(unittest.TestCase):
    __test__ = False
    plan = context_routes.ConversationRouteTests.plan
    planned = context_routes.ConversationRouteTests.planned

    def setUp(self):
        context_routes.ConversationRouteTests.setUp(self)
        self.calls = []
        self.fail_b = True
        self.before_adapter = None
        self.settings['enable_semantic_kernel'] = True
        agent = {'id': 'agent1', 'name': 'RecoveryAgent', 'display_name': 'Recovery agent'}
        patcher = patch.object(self.route, 'resolve_agent_catalog', lambda *args, **kwargs: [deepcopy(agent)])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.model.plan_override = {
            'kind': 'plan', 'intent': {'summary': 'Gather two results.', 'complexity': 'simple'},
            'steps': [
                {'step_id': 'a', 'capability_id': 'document_search', 'title': 'Gather A', 'arguments': {'query': 'A'}},
                {'step_id': 'b', 'capability_id': 'agent_invoke', 'title': 'Gather B',
                 'arguments': {'agent_name': 'RecoveryAgent', 'task': 'B'}, 'depends_on': ['a']},
                {'step_id': 'c', 'capability_id': 'document_search', 'title': 'Gather C',
                 'arguments': {'query': 'C'}, 'depends_on': ['b']},
                {'step_id': 'answer', 'capability_id': 'respond', 'title': 'Answer', 'arguments': {}, 'depends_on': ['c']},
            ],
        }
        namespace = self.route.execute_plan.__globals__
        build_step_result = namespace['build_step_result']
        original = namespace['_default_get_adapter']

        def get_adapter(capability):
            if capability == 'respond':
                return original(capability)

            def adapter(step, context, **kwargs):
                self.calls.append(step['step_id'])
                if self.before_adapter:
                    self.before_adapter(step, context, kwargs)
                if step['step_id'] == 'b' and self.fail_b:
                    return build_step_result(
                        status='failed', failure=namespace['build_failure']('step_timeout'),
                        error='SECRET_SENTINEL https://private.test/<script>private</script>',
                        summary='SECRET_SENTINEL',
                    )
                return build_step_result(notes=[f"Saved findings {step['step_id']}"], summary='Completed')

            return adapter

        patcher = patch.dict(namespace, {'_default_get_adapter': get_adapter})
        patcher.start()
        self.addCleanup(patcher.stop)

    def __enter__(self):
        try:
            self.setUp()
        except Exception:
            self.doCleanups()
            raise
        return self

    def __exit__(self, *_args):
        self.doCleanups()

    def plan_attempt(self):
        return self.planned()

    def run_attempt(self, plan):
        return self.client.post('/api/v2/orchestration/run', json={
            'conversation_id': 'conv1', 'run_id': plan['run_id'],
            **({'expected_version': plan['edit_version']} if plan.get('edit_version') else {}),
        }, buffered=True)

    def detail(self, run_id):
        response = self.client.get(f'/api/v2/orchestration/runs/{run_id}?conversation_id=conv1')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()['run']

    def retry(self, run_id, **overrides):
        body = {
            'conversation_id': 'conv1', 'submission_id': 'retry-submission',
            'expected_version': self.detail(run_id)['recovery']['expected_version'],
            'confirm_external_effects': True, **overrides,
        }
        return self.client.post(f'/api/v2/orchestration/runs/{run_id}/retry', json=body)
