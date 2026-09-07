# test_orchestration_model_selection.py
"""
Functional regressions for authorized orchestration model selection and SDK parameters.
Version: 0.261.101
Implemented in: 0.261.101

Exercises the real selection/binding code with endpoint authorization and client creation
replaced at their existing boundaries. No Azure resources or credentials are used.
"""

import importlib
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_orchestration_conversation_context import (
    LATEST, RESOLVED, fake_module, load_modules, winery_history,
)
from test_support.app_stubs import stubbed_config
from test_support.versioning import assert_app_version_at_least


TERRA_SELECTION = {
    'model_deployment': 'gpt-5.6-terra', 'model_provider': 'aoai',
    'model_endpoint_id': 'selected-endpoint', 'model_id': 'terra-model',
}


def model_endpoint():
    return {
        'id': 'selected-endpoint', 'provider': 'aoai', 'enabled': True,
        'connection': {
            'endpoint': 'https://selected.example.test',
            'openai_api_version': '2025-04-01-preview',
        },
        'auth': {'type': 'api_key', 'api_key': 'test-only-key'},
        'models': [
            {
                'id': 'terra-model', 'deploymentName': 'gpt-5.6-terra',
                'modelName': 'gpt-5.6-terra', 'enabled': True, 'responseLength': 16000,
            },
            {
                'id': 'luna-model', 'deploymentName': 'gpt-5.6-luna',
                'modelName': 'gpt-5.6-luna', 'enabled': True,
            },
        ],
    }


def endpoint_runtime(endpoint, client):
    return fake_module(
        'functions_model_endpoint_runtime',
        MODEL_ENDPOINT_PROVIDER_ALLOWLIST={'aoai', 'aifoundry', 'new_foundry', 'anthropic', 'claude'},
        resolve_model_endpoint_from_context=Mock(return_value=endpoint),
        build_model_endpoint_sync_chat_client=Mock(return_value=(client, 'azure_openai')),
    )


class ModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = load_modules()
        with stubbed_config():
            cls.models = importlib.import_module('functions_orchestration_models')

    def setUp(self):
        self.endpoint = model_endpoint()
        self.client = Mock()
        self.legacy_client = Mock()
        self.runtime = endpoint_runtime(self.endpoint, self.client)
        self.settings = {
            'enable_multi_model_endpoints': True,
            'default_model_selection': {
                'endpoint_id': 'selected-endpoint', 'model_id': 'terra-model', 'provider': 'aoai',
            },
            'gpt_model': {'selected': [{'deploymentName': 'gpt-4o'}]},
        }
        self.identity = {'user_id': 'user1', 'user_roles': ['User'], 'user_email': 'test@example.test'}
        patcher = patch.dict(sys.modules, {'functions_model_endpoint_runtime': self.runtime})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(
            self.modules.planner, 'resolve_planner_client',
            side_effect=lambda settings: (
                self.legacy_client, settings.get('chat_orchestration_planner_deployment') or 'gpt-4o'
            ),
        )
        self.legacy_resolver = patcher.start()
        self.addCleanup(patcher.stop)

    def resolve(self, selection=None, **kwargs):
        seeds = {'model': selection or {}, 'reasoning_effort': 'high', 'active_group_ids': ['group1']}
        binding = self.models.resolve_orchestration_model(
            self.settings, user_id='user1', seeds=seeds, identity_context=self.identity, **kwargs,
        )
        self.addCleanup(binding.close)
        return binding

    def test_explicit_selection_beats_default_and_legacy_with_authorized_identity(self):
        self.settings['default_model_selection']['model_id'] = 'luna-model'
        binding = self.resolve(TERRA_SELECTION)
        self.assertIs(binding.client, self.client)
        self.assertEqual(binding.deployment, 'gpt-5.6-terra')
        self.assertEqual(binding.source, 'request')
        self.assertEqual(binding.answer_model_selection(), TERRA_SELECTION)
        self.runtime.resolve_model_endpoint_from_context.assert_called_once_with(
            self.settings, {
                'endpoint_id': 'selected-endpoint', 'model_id': 'terra-model',
                'model_deployment': 'gpt-5.6-terra', 'provider': 'aoai',
                'user_id': 'user1', 'active_group_ids': ['group1'],
            }, authorize=True,
        )
        self.runtime.build_model_endpoint_sync_chat_client.assert_called_once_with(
            self.endpoint['auth'], 'aoai', 'https://selected.example.test',
            '2025-04-01-preview', 'gpt-5.6-terra', settings=self.settings,
            endpoint_config=self.endpoint, identity_context=self.identity,
        )
        self.legacy_resolver.assert_not_called()
        self.assertNotIn('test-only-key', str(binding.metadata()))
        self.assertNotIn('selected.example.test', str(binding.metadata()))

    def test_admin_default_wins_when_no_model_is_supplied(self):
        binding = self.resolve()
        self.assertEqual(binding.deployment, 'gpt-5.6-terra')
        self.assertEqual(binding.source, 'default')
        self.assertEqual(binding.answer_model_selection(), TERRA_SELECTION)
        self.legacy_resolver.assert_not_called()

    def test_planner_override_is_separate_from_persisted_answer_selection(self):
        self.settings['chat_orchestration_planner_deployment'] = 'small-planner'
        planner = self.resolve(TERRA_SELECTION, planner=True)
        answer = self.resolve(planner.answer_model_selection())
        self.assertEqual(planner.deployment, 'small-planner')
        self.assertEqual(planner.source, 'planner_override')
        self.assertEqual(planner.answer_model_selection(), TERRA_SELECTION)
        self.assertIs(planner.client, self.legacy_client)
        self.assertEqual(answer.deployment, 'gpt-5.6-terra')
        self.assertIs(answer.client, self.client)
        self.assertEqual(self.runtime.resolve_model_endpoint_from_context.call_count, 2)
        self.assertEqual(self.runtime.build_model_endpoint_sync_chat_client.call_count, 1)

    def test_unavailable_modern_model_never_falls_back_even_with_planner_override(self):
        self.runtime.resolve_model_endpoint_from_context.return_value = None
        for override in ('', 'small-planner'):
            self.settings['chat_orchestration_planner_deployment'] = override
            for selection in (None, TERRA_SELECTION):
                with self.subTest(override=override, selection=selection):
                    with self.assertRaises(self.models.OrchestrationModelError):
                        self.resolve(selection, planner=True)
        self.legacy_resolver.assert_not_called()
        self.runtime.build_model_endpoint_sync_chat_client.assert_not_called()

    def test_configured_planner_endpoint_is_authorized_independently_of_the_answer(self):
        planner_endpoint = model_endpoint()
        planner_endpoint.update(id='planner-endpoint', provider='new_foundry')
        planner_endpoint['connection'] = {'endpoint': 'https://planner.example.test/openai/v1'}
        planner_endpoint['models'] = [{
            'id': 'planner-model', 'deploymentName': 'gpt-4o-mini', 'enabled': True,
        }]
        self.settings.update({
            'chat_orchestration_planner_model_endpoint_id': 'planner-endpoint',
            'chat_orchestration_planner_model_id': 'planner-model',
            'chat_orchestration_planner_model_provider': 'new_foundry',
        })
        self.runtime.resolve_model_endpoint_from_context.side_effect = [
            self.endpoint, planner_endpoint,
        ]
        binding = self.resolve(TERRA_SELECTION, planner=True)
        self.assertEqual(binding.deployment, 'gpt-4o-mini')
        self.assertEqual(binding.provider, 'new_foundry')
        self.assertEqual(binding.endpoint_id, 'planner-endpoint')
        self.assertEqual(binding.answer_model_selection(), TERRA_SELECTION)
        self.assertEqual(binding.reasoning_effort, '')
        self.assertTrue(self.models.has_planner_model_override(self.settings))
        self.assertEqual(self.runtime.resolve_model_endpoint_from_context.call_count, 2)
        for call in self.runtime.resolve_model_endpoint_from_context.call_args_list:
            self.assertTrue(call.kwargs['authorize'])
            self.assertEqual(call.args[1]['user_id'], 'user1')
        self.assertEqual(self.runtime.build_model_endpoint_sync_chat_client.call_args.args[1:5], (
            'new_foundry', 'https://planner.example.test/openai/v1', '', 'gpt-4o-mini',
        ))
        self.legacy_resolver.assert_not_called()

    def test_partial_planner_identity_is_rejected_instead_of_using_the_legacy_connection(self):
        for override in (
            {'chat_orchestration_planner_model_id': 'planner-model'},
            {'chat_orchestration_planner_model_provider': 'aoai'},
            {'chat_orchestration_planner_deployment': 'claude-sonnet',
             'chat_orchestration_planner_model_provider': 'anthropic'},
        ):
            with self.subTest(override=override):
                with patch.dict(self.settings, override):
                    with self.assertRaises(self.models.OrchestrationModelError):
                        self.resolve(planner=True)
        self.legacy_resolver.assert_not_called()
        self.runtime.build_model_endpoint_sync_chat_client.assert_not_called()

    def test_endpoint_authorization_failure_is_not_replaced_with_a_default(self):
        self.runtime.resolve_model_endpoint_from_context.side_effect = PermissionError('Test denial')
        with self.assertRaises(PermissionError):
            self.resolve(TERRA_SELECTION)
        self.legacy_resolver.assert_not_called()
        self.runtime.build_model_endpoint_sync_chat_client.assert_not_called()

    def test_incomplete_or_inconsistent_selection_is_rejected(self):
        for selection in (
            {'model_id': 'terra-model'},
            {'model_endpoint_id': 'selected-endpoint'},
            {'model_provider': 'aoai'},
            {**TERRA_SELECTION, 'model_endpoint_id': 'other-endpoint'},
            {**TERRA_SELECTION, 'model_id': 'luna-model'},
            {**TERRA_SELECTION, 'model_deployment': 'gpt-4o'},
            {**TERRA_SELECTION, 'model_provider': 'new_foundry'},
        ):
            with self.subTest(selection=selection):
                with self.assertRaises(self.models.OrchestrationModelError):
                    self.resolve(selection)
        self.legacy_resolver.assert_not_called()
        self.runtime.build_model_endpoint_sync_chat_client.assert_not_called()

    def test_disabled_or_misconfigured_endpoint_and_model_are_rejected(self):
        for change in (
            lambda endpoint: endpoint.update(enabled=False),
            lambda endpoint: endpoint['models'][0].update(enabled=False),
            lambda endpoint: endpoint.update(models=[]),
            lambda endpoint: endpoint['connection'].update(endpoint=''),
            lambda endpoint: endpoint['connection'].update(openai_api_version=''),
        ):
            with self.subTest(change=change):
                endpoint = model_endpoint()
                change(endpoint)
                self.runtime.resolve_model_endpoint_from_context.return_value = endpoint
                with self.assertRaises(self.models.OrchestrationModelError):
                    self.resolve(TERRA_SELECTION)
        self.legacy_resolver.assert_not_called()
        self.runtime.build_model_endpoint_sync_chat_client.assert_not_called()

    def test_stale_defaults_are_rejected_without_a_legacy_fallback(self):
        for default in (
            {'endpoint_id': 'selected-endpoint'},
            {'model_id': 'terra-model'},
            {'endpoint_id': ' ', 'model_id': 'terra-model'},
            {'endpoint_id': 'selected-endpoint', 'model_id': ' '},
            {'endpoint_id': 'selected-endpoint', 'model_id': 'deleted-model'},
        ):
            with self.subTest(default=default):
                self.settings['default_model_selection'] = default
                with self.assertRaises(self.models.OrchestrationModelError):
                    self.resolve()
        self.legacy_resolver.assert_not_called()
        self.runtime.build_model_endpoint_sync_chat_client.assert_not_called()

    def test_modern_selection_requires_enabled_runtime_and_a_captured_user(self):
        self.settings['enable_multi_model_endpoints'] = False
        with self.assertRaises(self.models.OrchestrationModelError):
            self.resolve(TERRA_SELECTION)
        self.settings['enable_multi_model_endpoints'] = True
        with self.assertRaises(self.models.OrchestrationModelError):
            self.models.resolve_orchestration_model(
                self.settings, user_id='', seeds={'model': TERRA_SELECTION},
            )
        self.legacy_resolver.assert_not_called()
        self.runtime.resolve_model_endpoint_from_context.assert_not_called()

    def test_legacy_models_and_apim_keep_their_configured_connection(self):
        self.settings['enable_multi_model_endpoints'] = False
        self.settings['chat_orchestration_planner_deployment'] = 'small-planner'
        for apim in (False, True):
            with self.subTest(apim=apim):
                self.settings['enable_gpt_apim'] = apim
                self.settings['azure_apim_gpt_deployment'] = 'gpt-4o, gpt-5'
                self.settings['gpt_model']['selected'].append({'deploymentName': 'gpt-5'})
                answer = self.resolve({'model_deployment': 'gpt-5'})
                self.assertIs(answer.client, self.legacy_client)
                self.assertEqual(answer.deployment, 'gpt-5')
                self.assertEqual(
                    self.legacy_resolver.call_args.args[0]['chat_orchestration_planner_deployment'], '',
                )
                planner = self.resolve({'model_deployment': 'gpt-5'}, planner=True)
                self.assertEqual(planner.deployment, 'small-planner')
                self.assertEqual(planner.answer_model_selection()['model_deployment'], 'gpt-5')
                with self.assertRaises(self.models.OrchestrationModelError):
                    self.resolve({'model_deployment': 'not-configured'})
        self.runtime.resolve_model_endpoint_from_context.assert_not_called()

    def test_reasoning_planning_uses_bounded_budget_and_compatible_parameters(self):
        binding = self.resolve(TERRA_SELECTION)
        messages = [{'role': 'user', 'content': 'Return a JSON object.'}]
        binding.as_planner_client().chat.completions.create(
            model=binding.deployment, messages=messages, max_tokens=1200,
            temperature=0, response_format={'type': 'json_object'},
        )
        parameters = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(parameters['model'], 'gpt-5.6-terra')
        self.assertEqual(parameters['messages'], messages)
        self.assertEqual(parameters['max_completion_tokens'], 8192)
        self.assertEqual(parameters['reasoning_effort'], 'high')
        self.assertEqual(parameters['response_format'], {'type': 'json_object'})
        self.assertNotIn('max_tokens', parameters)
        self.assertNotIn('temperature', parameters)

    def test_foundry_and_anthropic_use_their_selected_protocol_without_an_azure_api_version(self):
        for provider, address, deployment in (
            ('new_foundry', 'https://selected.example.test/openai/v1', 'gpt-4o-mini'),
            ('anthropic', 'https://selected.example.test/anthropic/v1/messages', 'claude-sonnet'),
        ):
            with self.subTest(provider=provider):
                self.endpoint['provider'] = provider
                self.endpoint['connection'] = {'endpoint': address}
                self.endpoint['models'][0].update(deploymentName=deployment, modelName=deployment)
                binding = self.resolve({
                    **TERRA_SELECTION, 'model_provider': provider, 'model_deployment': deployment,
                })
                self.assertEqual(
                    self.runtime.build_model_endpoint_sync_chat_client.call_args.args[1:5],
                    (provider, address, '', deployment),
                )
                binding.create_completion(messages=[], max_tokens=1200, temperature=0)
                parameters = self.client.chat.completions.create.call_args.kwargs
                self.assertEqual(parameters['model'], deployment)
                self.assertEqual(parameters['max_tokens'], 1200)
                self.assertNotIn('reasoning_effort', parameters)
                self.assertNotIn('max_completion_tokens', parameters)
        self.legacy_resolver.assert_not_called()

    def claude_resolver(self):
        endpoint_clients = importlib.import_module('model_endpoint_clients')
        self.endpoint['provider'] = 'anthropic'
        self.endpoint['connection'] = {'endpoint': 'https://selected.example.test/anthropic/v1/messages'}
        self.endpoint['models'][0].update(deploymentName='claude-sonnet-4', modelName='claude-sonnet-4')
        client = endpoint_clients.AnthropicChatCompletionClient(
            endpoint=self.endpoint['connection']['endpoint'], api_key='test-only-key',
        )
        self.runtime.build_model_endpoint_sync_chat_client.return_value = client, 'anthropic'
        binding = self.resolve({
            **TERRA_SELECTION, 'model_provider': 'anthropic', 'model_deployment': 'claude-sonnet-4',
        })
        snapshot = self.modules.context.build_conversation_snapshot(winery_history())
        response = Mock(status_code=200)
        payload = {
            'content': [{'type': 'text', 'text': json.dumps({
                'relationship': 'follow_up', 'resolved_message': RESOLVED,
                'message_ids': ['u1', 'u2', 'a2'], 'requires_retrieval': True, 'clarification': None,
            })}],
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
        response.json.return_value = payload
        return binding, snapshot, response, payload

    def test_anthropic_completed_followup_preserves_context_without_json_repair(self):
        binding, snapshot, response, payload = self.claude_resolver()
        for reason in ('end_turn', 'stop_sequence'):
            with self.subTest(reason=reason):
                payload['stop_reason'] = reason
                with patch('model_endpoint_clients.requests.post', return_value=response) as post:
                    resolution = self.modules.planner.resolve_conversation_request(
                        LATEST, snapshot, settings=self.settings, planner_model=binding,
                    )
                self.assertEqual(resolution['resolved_message'], RESOLVED)
                self.assertEqual(resolution['clarification'], '')
                self.assertEqual(resolution['token_usage']['total_tokens'], 15)
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs['json']['model'], 'claude-sonnet-4')
                self.assertEqual(
                    post.call_args.kwargs['json']['max_tokens'], self.modules.planner.RESOLUTION_MAX_TOKENS,
                )

    def test_anthropic_truncation_refusal_and_incomplete_turns_are_not_repaired(self):
        binding, snapshot, response, payload = self.claude_resolver()
        for reason, expected in (
            ('max_tokens', 'incomplete_completion'),
            ('model_context_window_exceeded', 'incomplete_completion'),
            ('tool_use', 'incomplete_completion'),
            ('pause_turn', 'incomplete_completion'),
            ('refusal', 'model_refusal'),
        ):
            with self.subTest(reason=reason):
                payload['stop_reason'] = reason
                with patch('model_endpoint_clients.requests.post', return_value=response) as post:
                    with self.assertRaises(self.modules.planner.ConversationResolutionError) as raised:
                        self.modules.planner.resolve_conversation_request(
                            LATEST, snapshot, settings=self.settings, planner_model=binding,
                        )
                self.assertEqual(raised.exception.reason, expected)
                self.assertEqual(raised.exception.attempts, 1)
                post.assert_called_once()

    def test_answer_respects_configured_limit_and_underlying_reasoning_model_alias(self):
        self.endpoint['models'][0].update(deploymentName='production-answer', responseLength=2048)
        binding = self.resolve({**TERRA_SELECTION, 'model_deployment': 'production-answer'})
        binding.create_completion(
            messages=[], max_tokens=4000, temperature=0.3, use_model_response_length=True,
        )
        parameters = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(parameters['model'], 'production-answer')
        self.assertEqual(parameters['max_completion_tokens'], 2048)
        self.assertNotIn('temperature', parameters)

    def test_invalid_response_lengths_use_the_bounded_answer_budget(self):
        for value in (None, False, 0, -1, 'invalid'):
            with self.subTest(value=value):
                self.endpoint['models'][0]['responseLength'] = value
                binding = self.resolve(TERRA_SELECTION)
                binding.create_completion(messages=[], max_tokens=4000, use_model_response_length=True)
                self.assertEqual(
                    self.client.chat.completions.create.call_args.kwargs['max_completion_tokens'], 8192,
                )

    def test_non_reasoning_models_keep_temperature_and_legacy_token_parameter(self):
        binding = self.models.OrchestrationModel(self.client, 'gpt-4o', reasoning_effort='high')
        binding.create_completion(messages=[], max_tokens=1200, temperature=0.3)
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs, {
            'model': 'gpt-4o', 'messages': [], 'max_tokens': 1200, 'temperature': 0.3,
        })

    def test_binding_cannot_be_retargeted_and_closes_its_sdk_client_once(self):
        binding = self.resolve(TERRA_SELECTION)
        with self.assertRaises(self.models.OrchestrationModelError):
            binding.create_completion(model='gpt-4o', messages=[])
        self.client.chat.completions.create.assert_not_called()
        binding.close()
        binding.close()
        self.client.close.assert_called_once_with()

    def test_research_uses_the_captured_planner_instead_of_resolving_a_legacy_client(self):
        binding = self.resolve(TERRA_SELECTION)
        context = SimpleNamespace(
            planner_client=binding.as_planner_client(), planner_deployment=binding.deployment,
        )
        client, deployment = self.modules.adapters._resolve_source_review_planner(self.settings, context)
        self.assertIs(client, context.planner_client)
        self.assertEqual(deployment, 'gpt-5.6-terra')
        self.legacy_resolver.assert_not_called()


if __name__ == '__main__':
    assert_app_version_at_least('0.261.101')
    unittest.main()
