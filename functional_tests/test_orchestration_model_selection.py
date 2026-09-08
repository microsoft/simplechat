# test_orchestration_model_selection.py
"""
Functional regressions for authorized orchestration model selection and SDK parameters.
Version: 0.261.104
Implemented in: 0.261.103
Canonical reasoning resolution and recovery: 0.261.104

Exercises the real selection/binding code with endpoint authorization and client creation
replaced at their existing boundaries. No Azure resources or credentials are used.
"""

import importlib
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai import AuthenticationError, RateLimitError

from test_orchestration_conversation_context import (
    LATEST, RESOLVED, fake_module, load_modules, winery_history,
)
from test_support.app_stubs import stubbed_config
from test_support.versioning import assert_app_version_at_least
from test_model_reasoning_capability_resolution import sdk_error


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

    def test_luna_uuid_and_custom_deployment_resolve_before_the_first_request(self):
        model = self.endpoint['models'][0]
        model.update(id='f8c476df-c951-499c-b87d-98fd02597780', modelName='gpt-5.6-luna',
                     deploymentName='production-answer', displayName='GPT-5 Minimal')
        selection = {**TERRA_SELECTION, 'model_id': model['id'], 'model_deployment': 'production-answer'}
        binding = self.models.resolve_orchestration_model(
            self.settings, user_id='user1', seeds={'model': selection, 'reasoning_effort': 'minimal'},
        )
        self.addCleanup(binding.close)
        self.assertEqual(binding.reasoning_effort, 'minimal')
        self.assertEqual(binding.reasoning_resolution, {
            'requested_effort': 'minimal', 'effective_effort': 'low', 'mode': 'explicit',
            'adjustment_reason': 'reasoning_effort_unsupported',
        })
        self.client.chat.completions.create.assert_not_called()
        binding.create_completion(messages=[], max_tokens=1200, temperature=0)
        parameters = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(parameters['reasoning_effort'], 'low')
        self.assertEqual(parameters['max_completion_tokens'], 8192)
        self.assertEqual(parameters['model'], 'production-answer')
        self.assertEqual(binding.reasoning_effort, 'minimal')

    def test_none_and_explicit_omission_do_not_inherit_the_binding_effort(self):
        binding = self.models.OrchestrationModel(self.client, 'gpt-5.6-luna', reasoning_effort='high')
        for effort, expected in (('none', 'none'), (None, None), ('', None)):
            binding.create_completion(messages=[], max_tokens=1200, reasoning_effort=effort)
            self.assertEqual(
                self.client.chat.completions.create.call_args.kwargs.get('reasoning_effort'), expected,
            )
            self.assertEqual(binding.reasoning_resolution['effective_effort'], expected)
            self.assertEqual(binding.reasoning_effort, 'high')
        binding.create_completion(messages=[], max_tokens=1200)
        self.assertEqual(binding.reasoning_resolution['effective_effort'], 'high')

    def test_provider_recovery_updates_resolution_without_changing_budget_or_selection(self):
        binding = self.models.OrchestrationModel(
            self.client, 'production-answer', behavior_name='gpt-5.6-luna',
            reasoning_effort='minimal', response_length=2048,
        )
        self.client.chat.completions.create.side_effect = [sdk_error(), 'completion']
        result = binding.create_completion(
            messages=[{'role': 'user', 'content': 'answer'}], max_tokens=1200,
            use_model_response_length=True, response_format={'type': 'json_object'},
        )
        self.assertEqual(result, 'completion')
        first, retry = self.client.chat.completions.create.call_args_list
        self.assertEqual(first.kwargs['reasoning_effort'], 'low')
        self.assertEqual(retry.kwargs, {
            key: value for key, value in first.kwargs.items() if key != 'reasoning_effort'
        })
        self.assertEqual(retry.kwargs['max_completion_tokens'], 2048)
        self.assertEqual(binding.reasoning_effort, 'minimal')
        self.assertEqual(binding.reasoning_resolution, {
            'requested_effort': 'minimal', 'effective_effort': None, 'mode': 'model_default',
            'adjustment_reason': 'reasoning_parameter_rejected',
        })

    def test_combined_reasoning_and_json_recovery_never_reintroduces_rejected_effort(self):
        messages = [{'role': 'user', 'content': 'Return one JSON object.'}]
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"steps": []}', refusal=None), finish_reason='stop',
            )],
            usage=SimpleNamespace(total_tokens=12),
        )
        for requested in ('minimal', 'low', 'none'):
            with self.subTest(requested=requested):
                binding = self.models.OrchestrationModel(
                    self.client, 'custom-planner', behavior_name='gpt-5.6-luna',
                    reasoning_effort=requested,
                )
                self.client.chat.completions.create.reset_mock()

                def create(**parameters):
                    if 'reasoning_effort' in parameters:
                        raise sdk_error()
                    if 'response_format' in parameters:
                        raise sdk_error(param='response_format', code='unsupported_parameter')
                    return response

                self.client.chat.completions.create.side_effect = create
                result, usage = self.modules.planner._call_planner(
                    binding.as_planner_client(), binding.deployment, messages,
                    max_tokens=1200, require_complete_response=True,
                )
                calls = self.client.chat.completions.create.call_args_list
                self.assertEqual(len(calls), 3)
                self.assertEqual(calls[0].kwargs['reasoning_effort'], (
                    'low' if requested == 'minimal' else requested
                ))
                self.assertEqual(calls[1].kwargs, {
                    key: value for key, value in calls[0].kwargs.items() if key != 'reasoning_effort'
                })
                self.assertEqual(calls[2].kwargs, {
                    key: value for key, value in calls[1].kwargs.items() if key != 'response_format'
                })
                for call in calls:
                    self.assertIs(call.kwargs['messages'], messages)
                    self.assertEqual(call.kwargs['model'], 'custom-planner')
                    self.assertEqual(call.kwargs['max_completion_tokens'], 8192)
                self.assertEqual(binding.reasoning_resolution, {
                    'requested_effort': requested, 'effective_effort': None, 'mode': 'model_default',
                    'adjustment_reason': 'reasoning_parameter_rejected',
                })
                self.assertEqual(binding.reasoning_effort, requested)
                self.assertEqual(result, '{"steps": []}')
                self.assertIs(usage, response.usage)

    def test_recovery_state_survives_failed_retry_without_swallowing_unrelated_errors(self):
        for error in (
            sdk_error(param='messages', code='invalid_request_error'),
            sdk_error(param='response_format', code='unsupported_parameter'),
        ):
            with self.subTest(parameter=error.param):
                binding = self.models.OrchestrationModel(
                    self.client, 'gpt-5.6-luna', reasoning_effort='minimal',
                )
                self.client.chat.completions.create.reset_mock()
                self.client.chat.completions.create.side_effect = [sdk_error(), error]
                with self.assertRaises(type(error)) as raised:
                    binding.create_completion(messages=[], max_tokens=1200)
                self.assertIs(raised.exception, error)
                self.assertEqual(self.client.chat.completions.create.call_count, 2)
                self.assertEqual(binding.reasoning_resolution, {
                    'requested_effort': 'minimal', 'effective_effort': None, 'mode': 'model_default',
                    'adjustment_reason': 'reasoning_parameter_rejected',
                })
                self.client.chat.completions.create.side_effect = None
                for override, effective, reason in (
                    ('none', 'none', None), ('high', 'high', None), (None, None, None),
                    ('minimal', None, 'reasoning_parameter_rejected'),
                ):
                    binding.create_completion(
                        messages=[], max_tokens=1200, reasoning_effort=override,
                    )
                    parameters = self.client.chat.completions.create.call_args.kwargs
                    self.assertEqual(parameters.get('reasoning_effort'), effective)
                    self.assertEqual(binding.reasoning_resolution, {
                        'requested_effort': override, 'effective_effort': effective,
                        'mode': 'model_default' if effective is None else 'explicit',
                        'adjustment_reason': reason,
                    })
                self.assertEqual(binding.reasoning_effort, 'minimal')
                fresh_binding = self.models.OrchestrationModel(
                    self.client, 'gpt-5.6-luna', reasoning_effort='minimal',
                )
                fresh_binding.create_completion(messages=[], max_tokens=1200)
                self.assertEqual(
                    self.client.chat.completions.create.call_args.kwargs['reasoning_effort'], 'low',
                )

    def test_combined_recovery_does_not_loop_on_a_second_format_rejection(self):
        binding = self.models.OrchestrationModel(
            self.client, 'gpt-5.6-luna', reasoning_effort='low',
        )
        format_error = sdk_error(param='response_format', code='unsupported_parameter')
        self.client.chat.completions.create.side_effect = [
            sdk_error(), format_error, format_error,
        ]
        with self.assertRaises(type(format_error)) as raised:
            self.modules.planner._call_planner(
                binding.as_planner_client(), binding.deployment, [], max_tokens=1200,
            )
        self.assertIs(raised.exception, format_error)
        calls = self.client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertNotIn('reasoning_effort', calls[1].kwargs)
        self.assertNotIn('reasoning_effort', calls[2].kwargs)
        self.assertNotIn('response_format', calls[2].kwargs)
        self.assertEqual(binding.reasoning_resolution['mode'], 'model_default')

    def test_json_then_reasoning_recovery_preserves_the_same_three_attempt_bound(self):
        binding = self.models.OrchestrationModel(
            self.client, 'gpt-5.6-luna', reasoning_effort='low',
        )
        messages = [{'role': 'user', 'content': 'Return a JSON object.'}]
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))], usage=None,
        )
        self.client.chat.completions.create.side_effect = [
            sdk_error(param='response_format', code='unsupported_parameter'), sdk_error(), response,
        ]
        result, _usage = self.modules.planner._call_planner(
            binding.as_planner_client(), binding.deployment, messages, max_tokens=1200,
        )
        calls = self.client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1].kwargs, {
            key: value for key, value in calls[0].kwargs.items() if key != 'response_format'
        })
        self.assertEqual(calls[2].kwargs, {
            key: value for key, value in calls[1].kwargs.items() if key != 'reasoning_effort'
        })
        self.assertEqual(result, '{}')
        self.assertEqual(binding.reasoning_resolution, {
            'requested_effort': 'low', 'effective_effort': None, 'mode': 'model_default',
            'adjustment_reason': 'reasoning_parameter_rejected',
        })

    def test_combined_recovery_propagates_auth_and_rate_errors_without_more_attempts(self):
        for error_type, status in ((AuthenticationError, 401), (RateLimitError, 429)):
            with self.subTest(status=status):
                binding = self.models.OrchestrationModel(
                    self.client, 'gpt-5.6-luna', reasoning_effort='low',
                )
                final_error = sdk_error(error_type, status=status)
                self.client.chat.completions.create.reset_mock()
                self.client.chat.completions.create.side_effect = [
                    sdk_error(), sdk_error(param='response_format', code='unsupported_parameter'),
                    final_error,
                ]
                with self.assertRaises(error_type) as raised:
                    self.modules.planner._call_planner(
                        binding.as_planner_client(), binding.deployment, [], max_tokens=1200,
                    )
                self.assertIs(raised.exception, final_error)
                calls = self.client.chat.completions.create.call_args_list
                self.assertEqual(len(calls), 3)
                self.assertNotIn('reasoning_effort', calls[2].kwargs)
                self.assertEqual(binding.reasoning_resolution['effective_effort'], None)
                self.assertEqual(binding.reasoning_resolution['mode'], 'model_default')

    def test_planner_override_resolves_its_own_policy_without_inheriting_answer_effort(self):
        planner_endpoint = model_endpoint()
        planner_endpoint['id'] = 'planner-endpoint'
        planner_endpoint['models'] = [{
            'id': 'planner-model', 'deploymentName': 'custom-planner', 'modelName': 'gpt-5-mini',
        }]
        self.settings.update({
            'chat_orchestration_planner_model_endpoint_id': 'planner-endpoint',
            'chat_orchestration_planner_model_id': 'planner-model',
        })
        self.runtime.resolve_model_endpoint_from_context.side_effect = [self.endpoint, planner_endpoint]
        planner = self.resolve(TERRA_SELECTION, planner=True)
        self.assertEqual(planner.reasoning_resolution['mode'], 'model_default')
        planner.create_completion(messages=[], max_tokens=1200)
        self.assertNotIn('reasoning_effort', self.client.chat.completions.create.call_args.kwargs)
        planner.create_completion(messages=[], max_tokens=1200, reasoning_effort='minimal')
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs['reasoning_effort'], 'minimal')
        self.assertEqual(planner.answer_model_selection(), TERRA_SELECTION)

    def test_legacy_custom_deployment_uses_the_configured_canonical_name(self):
        self.settings.update(enable_multi_model_endpoints=False, gpt_model={
            'selected': [{'deploymentName': 'legacy-answer', 'modelName': 'gpt-5.6-luna'}]
        })
        binding = self.resolve({'model_deployment': 'legacy-answer'})
        self.assertEqual(binding.reasoning_resolution['effective_effort'], 'high')
        binding.create_completion(messages=[], max_tokens=1200)
        self.assertEqual(
            self.legacy_client.chat.completions.create.call_args.kwargs['max_completion_tokens'], 8192,
        )

    def test_legacy_planner_override_uses_its_own_canonical_record(self):
        self.settings['gpt_model']['selected'].append({
            'deploymentName': 'custom-planner', 'modelName': 'gpt-5-pro',
        })
        self.settings['chat_orchestration_planner_deployment'] = 'custom-planner'
        binding = self.resolve(TERRA_SELECTION, planner=True)
        self.assertEqual(binding.behavior_name, 'gpt-5-pro')
        self.assertIsNone(binding.reasoning_resolution['effective_effort'])
        binding.create_completion(messages=[], max_tokens=1200, reasoning_effort='low')
        self.assertEqual(
            self.legacy_client.chat.completions.create.call_args.kwargs['reasoning_effort'], 'high',
        )
        self.assertEqual(binding.answer_model_selection(), TERRA_SELECTION)

    def test_apim_never_borrows_same_named_direct_aoai_model_metadata(self):
        for deployment, direct_model, expected in (
            ('custom-answer', 'gpt-5.6-luna', None),
            ('gpt-5.6-luna', 'gpt-4o', 'high'),
        ):
            for planner in (False, True):
                with self.subTest(deployment=deployment, planner=planner):
                    self.settings.update(
                        enable_multi_model_endpoints=False,
                        enable_gpt_apim=True,
                        azure_apim_gpt_deployment=deployment,
                        chat_orchestration_planner_deployment=deployment if planner else '',
                        gpt_model={'selected': [{
                            'deploymentName': deployment, 'modelName': direct_model,
                        }]},
                    )
                    binding = self.resolve({'model_deployment': deployment}, planner=planner)
                    self.assertEqual(binding.behavior_name, '')
                    binding.create_completion(
                        messages=[], max_tokens=1200, reasoning_effort='high', temperature=0.3,
                    )
                    parameters = self.legacy_client.chat.completions.create.call_args.kwargs
                    self.assertEqual(parameters['model'], deployment)
                    self.assertEqual(parameters.get('reasoning_effort'), expected)
                    self.assertEqual(binding.reasoning_resolution['effective_effort'], expected)
                    if expected is None:
                        self.assertEqual(parameters['max_tokens'], 1200)
                        self.assertEqual(parameters['temperature'], 0.3)
                        self.assertEqual(
                            binding.reasoning_resolution['adjustment_reason'],
                            'reasoning_capability_unknown',
                        )

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
    assert_app_version_at_least('0.261.103')
    unittest.main()
