# test_orchestration_catalog_auto_execution.py
"""Exercise Auto planning, execution, attribution and invalidation through Flask.

Version: 0.261.126
Implemented in: 0.261.126

Uses real model resolution, plan storage, execution and checkpoints with offline
provider responses and an explicitly authorized candidate inventory.
"""

from contextlib import contextmanager
from copy import deepcopy
import sys
import unittest
from unittest.mock import patch

from test_orchestration_conversation_context import fake_module
from test_support.orchestration_recovery import RecoveryFixture, frames


@contextmanager
def auto_fixture():
    with RecoveryFixture() as fixture:
        fixture.settings['gpt_model']['selected'] = [
            {'deploymentName': 'bootstrap', 'modelName': 'gpt-5-mini'},
            {'deploymentName': 'routed-answer', 'modelName': 'gpt-5-nano'},
        ]
        fixture.model.plan_override = {
            'kind': 'plan', 'intent': {'summary': 'Answer the question.', 'complexity': 'simple'},
            'steps': [
                {'step_id': 'search', 'capability_id': 'document_search',
                 'title': 'Find evidence', 'arguments': {'query': 'Wineries'}},
                {'step_id': 'answer', 'capability_id': 'respond', 'title': 'Answer',
                 'model_task': 'general', 'arguments': {}, 'depends_on': ['search']},
            ],
        }
        original_create = fixture.model.create

        def provider_response(**kwargs):
            messages = deepcopy(kwargs['messages'])
            if messages[0]['content'].startswith(fixture.modules.planner.PLANNER_SYSTEM_PROMPT):
                messages[0]['content'] = fixture.modules.planner.PLANNER_SYSTEM_PROMPT
            return original_create(**{**kwargs, 'messages': messages})

        def candidates(settings, user_id):
            fixture.assertEqual(user_id, 'user1')
            rows = []
            for model in settings['gpt_model']['selected'][1:]:
                metadata = fixture.route.resolve_orchestration_model.__globals__['apply_model_profile'](
                    model, {}, settings,
                )
                rows.append({
                    'key': model['deploymentName'], 'label': model['deploymentName'],
                    'selection': {'model_deployment': model['deploymentName'], 'model_provider': 'aoai'},
                    'profile': metadata['_catalog_profile'], 'capabilities': metadata['capabilities'],
                    'effective_revision': metadata['_catalog_effective_revision'],
                })
            return rows

        with patch.object(fixture.model.chat.completions, 'create', provider_response), patch.object(
            fixture.modules.planner, 'authorized_routing_candidates', candidates,
        ):
            yield fixture


class AutoExecutionTests(unittest.TestCase):
    def test_research_and_answer_use_different_models_and_restore_context(self):
        with auto_fixture() as fixture:
            fixture.settings['enable_source_review'] = True
            fixture.settings['gpt_model']['selected'].append({
                'deploymentName': 'research-model', 'modelName': 'gpt-5',
            })
            steps = fixture.model.plan_override['steps']
            steps.insert(0, {
                'step_id': 'research', 'capability_id': 'deep_research', 'title': 'Research',
                'model_task': 'reasoning', 'arguments': {'query': 'Compare winery options'},
            })
            steps[1]['depends_on'] = ['research']
            steps[-1]['model_task'] = 'summarization'
            scopes = []

            def observe_scope(step, context, _kwargs):
                scopes.append((step['step_id'], context.gpt_model, context.planner_deployment))
                if step['step_id'] == 'research':
                    context.invoke_prompt('Compare winery options.', stage='research')

            fixture.before_adapter = observe_scope
            source_review = fake_module(
                'functions_source_review',
                is_source_review_enabled_for_user=lambda *args, **kwargs: True,
            )
            with patch.dict(sys.modules, {'functions_source_review': source_review}):
                plan = fixture.planned(model_routing='auto')
                self.assertEqual(plan['steps'][0]['model_binding']['selection']['model_deployment'], 'research-model')
                self.assertEqual(plan['steps'][-1]['model_binding']['selection']['model_deployment'], 'routed-answer')
                fixture.model.calls.clear()
                response = fixture.run_attempt(plan)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            events = frames(response)
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'completed', events)
            self.assertEqual(scopes, [
                ('research', 'research-model', 'research-model'),
                ('search', 'routed-answer', 'routed-answer'),
            ])
            self.assertEqual([call['model'] for call in fixture.model.calls], ['research-model', 'routed-answer'])
            self.assertEqual(done['model_deployment_name'], 'routed-answer')

    def test_actual_binding_survives_public_plan_execution_events_and_storage(self):
        with auto_fixture() as fixture:
            plan = fixture.planned(model_routing='auto')
            self.assertEqual(plan['model_routing'], 'auto')
            self.assertNotIn('model_binding', plan['steps'][0])
            binding = plan['steps'][-1]['model_binding']
            self.assertEqual(binding['selection']['model_deployment'], 'routed-answer')
            fixture.model.calls.clear()
            response = fixture.run_attempt(plan)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            events = frames(response)
            done = next(event for event in events if event.get('type') == 'orchestration_done')
            self.assertEqual(done['status'], 'completed', events)
            self.assertEqual(done['model_deployment_name'], 'routed-answer')
            self.assertTrue(fixture.model.calls)
            self.assertEqual({call['model'] for call in fixture.model.calls}, {'routed-answer'})
            completed = next(
                event for event in events
                if event.get('step_id') == 'answer' and event.get('status') == 'completed'
            )
            self.assertEqual(completed['model_binding']['selection'], binding['selection'])
            saved = fixture.client.get(
                f"/api/v2/orchestration/runs/{plan['run_id']}/steps?conversation_id=conv1"
            )
            self.assertEqual(saved.status_code, 200)
            answer = next(step for step in saved.get_json()['steps'] if step['step_id'] == 'answer')
            self.assertEqual(answer['model_binding']['selection'], binding['selection'])
            assistant = fixture.messages.read_item(done['message_id'], 'conv1')
            self.assertEqual(assistant['model_deployment_name'], 'routed-answer')

    def test_changed_capacity_or_revoked_deployment_is_rejected_before_execution(self):
        for change in ('capacity', 'revoked'):
            with self.subTest(change=change), auto_fixture() as fixture:
                plan = fixture.planned(model_routing='auto')
                if change == 'capacity':
                    fixture.settings['gpt_model']['selected'][1]['responseLength'] = 2048
                else:
                    fixture.settings['gpt_model']['selected'].pop()
                fixture.model.calls.clear()
                response = fixture.run_attempt(plan)
                self.assertIn(response.status_code, (403, 503))
                self.assertIn('error', response.get_json())
                self.assertEqual(fixture.model.calls, [])
                self.assertEqual(fixture.calls, [])

    def test_checkpoint_fingerprint_includes_approved_binding(self):
        with auto_fixture() as fixture:
            plan = fixture.planned(model_routing='auto')
            context_binding = fixture.route.prepare_retry.__globals__['context_binding']
            helpers = context_binding.__globals__
            before = helpers['fingerprint'](helpers['effective_plan'](plan))
            changed = deepcopy(plan)
            changed['steps'][-1]['model_binding']['selection']['model_deployment'] = 'another'
            after = helpers['fingerprint'](helpers['effective_plan'](changed))
            self.assertNotEqual(before, after)


if __name__ == '__main__':
    unittest.main()
