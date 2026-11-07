# test_chat_reasoning_runtime.py
"""Functional tests for ordinary-chat reasoning integration.

Version: 0.261.104
Implemented in: 0.261.104

Executes the actual nonstreaming invocation and streaming branch through shared
policy/retry functions. Azure seams and sockets are blocked; API errors use the
real OpenAI SDK types. No Flask application or route graph is imported.
"""

import ast
import copy
from datetime import datetime
import importlib
import json
import logging
from pathlib import Path
import socket
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import APIConnectionError, AuthenticationError, BadRequestError, RateLimitError

from test_model_reasoning_capability_resolution import sdk_error
from test_support.app_stubs import stubbed_config


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
LUNA = 'gpt-5.6-luna'


class ChatReasoningRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROUTE_FILE.read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.source)
        with stubbed_config():
            cls.clients = importlib.import_module('model_endpoint_clients')

    def setUp(self):
        network_guard = patch.object(socket, 'socket', side_effect=AssertionError('Network is blocked'))
        network_guard.start()
        self.addCleanup(network_guard.stop)
        self.create = Mock()
        self.usage = SimpleNamespace(prompt_tokens=8, completion_tokens=3, total_tokens=11)
        self.completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='Response'))], usage=self.usage,
        )
        self.chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content='Response'))], usage=self.usage,
        )
        self.namespace = {
            'create_completion_with_reasoning': self.clients.create_completion_with_reasoning,
            'ModelEndpointBehavior': self.clients.ModelEndpointBehavior,
            'normalize_chat_completion_text': self.clients.normalize_chat_completion_text,
            'extract_chat_completion_response_text': self.clients.extract_chat_completion_response_text,
            'normalize_model_response_length': lambda value: value,
            'conversation_history_for_api': [{'role': 'user', 'content': 'Request'}],
            'reasoning_effort': 'minimal', 'reasoning_resolution': None,
            'gpt_reasoning_model_name': LUNA, 'gpt_model': 'custom-production-deployment',
            'gpt_provider': 'aoai', 'gpt_endpoint_id': 'authorized-endpoint',
            'gpt_response_length': 4096, 'gpt_response_length_parameter': 'max_completion_tokens',
            'gpt_client': SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))),
            'gpt_api_version': 'configured-version',
            'agent_citations_list': [], 'user_metadata': {}, 'enable_semantic_kernel': False,
            'user_enable_agents': False, 'active_group_id': None, 'document_scope': 'personal',
            'get_current_user_id': lambda: 'self', 'user_id': 'self', 'conversation_id': 'authorized-conversation',
            '_prepare_conversation_context_for_invocation': lambda history, *args, **kwargs: (history, {}),
            'debug_print': Mock(), 'log_event': Mock(), 'datetime': datetime, 'logging': logging,
            'json': json, 'time': time, 'request_start_time': time.time(),
            'emit_thought': Mock(side_effect=lambda *args, **kwargs: {'type': 'thought', **kwargs}),
            'stream_cancel_requested': lambda: False, 'accumulated_content': '',
            'suppress_streamed_file_payload': False, 'token_usage_data': None,
        }
        helper_names = {
            '_create_chat_completion_with_reasoning', '_build_chat_reasoning_metadata',
            '_resolve_reasoning_effort_for_model', '_apply_response_length_for_model',
            '_resolve_legacy_chat_reasoning_model_name',
        }
        helpers = [
            copy.deepcopy(node) for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name in helper_names
        ]
        invocation = copy.deepcopy(next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == 'invoke_gpt_fallback'
        ))
        invocation.body = [
            ast.Global(names=node.names) if isinstance(node, ast.Nonlocal) else node
            for node in invocation.body
        ]
        stream_branch = next(
            node for node in ast.walk(self.tree) if isinstance(node, ast.If)
            and ast.unparse(node.test) == 'use_agent_streaming and selected_agent'
            and any(
                isinstance(child, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'stream_params' for target in child.targets)
                for child in node.orelse
            )
        )
        stream_wrapper = ast.parse('def invoke_stream_branch():\n    pass').body[0]
        stream_wrapper.body = copy.deepcopy(stream_branch.orelse)
        stream_wrapper.body.insert(0, ast.Global(names=[
            'reasoning_resolution', 'accumulated_content', 'token_usage_data',
        ]))
        module = ast.Module(body=[*helpers, invocation, stream_wrapper], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(ROUTE_FILE), 'exec'), self.namespace)

    def metadata(self):
        return self.namespace['_build_chat_reasoning_metadata'](
            self.namespace['reasoning_resolution'], self.namespace['reasoning_effort'], LUNA,
        )

    def invoke(self, streaming):
        if streaming:
            list(self.namespace['invoke_stream_branch']())
        else:
            self.namespace['invoke_gpt_fallback']()

    def test_supported_none_and_levels_sent_unchanged_in_both_routes(self):
        for streaming in (False, True):
            for effort in ('none', 'low', 'medium', 'high', 'xhigh', None):
                with self.subTest(streaming=streaming, effort=effort):
                    self.create.reset_mock()
                    self.namespace['accumulated_content'] = ''
                    self.namespace['reasoning_effort'] = effort
                    self.create.side_effect = None
                    self.create.return_value = [self.chunk] if streaming else self.completion
                    self.invoke(streaming)
                    sent = self.create.call_args.kwargs
                    self.assertEqual(sent.get('reasoning_effort'), effort)
                    self.assertEqual('reasoning_effort' in sent, effort is not None)
                    self.assertEqual(sent['model'], 'custom-production-deployment')
                    self.assertEqual(sent['max_completion_tokens'], 4096)
                    self.assertEqual(sent['messages'], [{'role': 'user', 'content': 'Request'}])
                    self.assertEqual(self.metadata()['reasoning_effort'], effort)
                    self.assertEqual(self.metadata()['requested_reasoning_effort'], effort)
                    self.assertEqual(self.metadata()['reasoning_mode'], 'explicit' if effort else 'model_default')
                    self.assertEqual(self.metadata()['reasoning_adjustments'], [])
                    self.create.assert_called_once()

    def test_stale_minimal_is_low_with_honest_metadata_in_both_routes(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                self.create.reset_mock()
                self.create.return_value = [self.chunk] if streaming else self.completion
                self.invoke(streaming)
                self.create.assert_called_once()
                self.assertEqual(self.create.call_args.kwargs['reasoning_effort'], 'low')
                metadata = self.metadata()
                self.assertEqual(metadata['reasoning_effort'], 'low')
                self.assertEqual(metadata['reasoning_adjustments'][0], {
                    'requested_effort': 'minimal', 'effective_effort': 'low', 'mode': 'explicit',
                    'adjustment_reason': 'reasoning_effort_unsupported', 'model_name': LUNA, 'stage': 'answer',
                })

    def test_unknown_and_nonreasoning_models_do_not_receive_guessed_effort(self):
        for streaming in (False, True):
            for model in ('unknown-private-model', 'gpt-4o'):
                with self.subTest(streaming=streaming, model=model):
                    self.create.reset_mock()
                    self.namespace['accumulated_content'] = ''
                    self.namespace['gpt_reasoning_model_name'] = model
                    self.create.return_value = [self.chunk] if streaming else self.completion
                    self.invoke(streaming)
                    self.assertNotIn('reasoning_effort', self.create.call_args.kwargs)
                    self.assertIsNone(self.metadata()['reasoning_effort'])
                    self.assertEqual(self.metadata()['reasoning_mode'], 'model_default')
                    self.assertTrue(self.metadata()['reasoning_adjustments'])

    def test_provider_contradiction_retries_once_without_other_parameter_changes(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                self.create.reset_mock()
                self.namespace['accumulated_content'] = ''
                self.create.side_effect = [
                    sdk_error(), [self.chunk] if streaming else self.completion,
                ]
                self.invoke(streaming)
                first, second = [call.kwargs for call in self.create.call_args_list]
                self.assertEqual(first['reasoning_effort'], 'low')
                self.assertEqual(second, {key: value for key, value in first.items() if key != 'reasoning_effort'})
                metadata = self.metadata()
                self.assertIsNone(metadata['reasoning_effort'])
                self.assertEqual(metadata['reasoning_mode'], 'model_default')
                self.assertEqual(metadata['reasoning_adjustments'][0]['requested_effort'], 'minimal')
                self.assertEqual(metadata['reasoning_adjustments'][0]['adjustment_reason'], 'reasoning_parameter_rejected')
                self.assertNotIn('private-provider-detail', json.dumps(metadata))

    def test_unrelated_errors_do_not_trigger_reasoning_or_api_version_fallback(self):
        errors = [
            sdk_error(param='messages'),
            sdk_error(code='invalid_request_error'),
            sdk_error(AuthenticationError, status=401),
            sdk_error(RateLimitError, status=429),
            RuntimeError('invalid_request_error reasoning_effort api version not supported'),
            APIConnectionError(request=httpx.Request('POST', 'https://provider.example.test')),
        ]
        for streaming in (False, True):
            for error in errors:
                with self.subTest(streaming=streaming, error=type(error).__name__):
                    self.create.reset_mock()
                    self.create.side_effect = error
                    with self.assertRaises(type(error)):
                        self.invoke(streaming)
                    self.create.assert_called_once()

    def test_second_reasoning_failure_is_not_retried_again(self):
        self.create.side_effect = [sdk_error(), sdk_error()]
        with self.assertRaises(BadRequestError):
            self.invoke(False)
        self.assertEqual(self.create.call_count, 2)

    def test_empty_stream_fallback_keeps_corrected_effort_and_original_adjustment(self):
        self.create.side_effect = [[], self.completion]
        self.invoke(True)
        self.assertEqual(self.create.call_count, 2)
        first, second = [call.kwargs for call in self.create.call_args_list]
        self.assertEqual(second, {key: value for key, value in first.items() if key not in {'stream', 'stream_options'}})
        self.assertEqual(second['reasoning_effort'], 'low')
        self.assertEqual(self.metadata()['reasoning_adjustments'][0]['requested_effort'], 'minimal')
        self.assertEqual(self.namespace['accumulated_content'], 'Response')

    def test_empty_stream_after_compatibility_recovery_does_not_reintroduce_effort(self):
        self.create.side_effect = [sdk_error(), [], self.completion]
        self.invoke(True)
        self.assertEqual(self.create.call_count, 3)
        self.assertTrue(all('reasoning_effort' not in call.kwargs for call in self.create.call_args_list[1:]))
        self.assertIsNone(self.metadata()['reasoning_effort'])
        self.assertEqual(self.metadata()['reasoning_adjustments'][0]['requested_effort'], 'minimal')

    def test_stream_adjustment_precedes_content_and_preserves_thought_envelope(self):
        self.create.return_value = [self.chunk]
        events = list(self.namespace['invoke_stream_branch']())
        adjustment_index = next(
            index for index, event in enumerate(events)
            if isinstance(event, dict) and event.get('reasoning_adjustments')
        )
        content_index = next(index for index, event in enumerate(events) if isinstance(event, str) and '"content"' in event)
        self.assertLess(adjustment_index, content_index)
        adjustment = events[adjustment_index]['reasoning_adjustments'][0]
        self.assertEqual(adjustment['effective_effort'], 'low')

        serializer = copy.deepcopy(next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == 'serialize_thought_event'
        ))
        module = ast.Module(body=[serializer], type_ignores=[])
        ast.fix_missing_locations(module)
        self.namespace['assistant_message_id'] = 'assistant-test'
        exec(compile(module, str(ROUTE_FILE), 'exec'), self.namespace)
        frame = self.namespace['serialize_thought_event'](
            'generation', 'Reasoning adjusted.', 2, reasoning_adjustments=[adjustment],
        )
        payload = json.loads(frame.removeprefix('data: '))
        self.assertEqual(payload['type'], 'thought')
        self.assertEqual(payload['step_type'], 'generation')
        self.assertEqual(payload['reasoning_adjustments'], [adjustment])

    def test_stream_iteration_failure_is_not_replayed(self):
        def failing_stream():
            yield self.chunk
            raise sdk_error()
        self.create.return_value = failing_stream()
        with self.assertRaises(BadRequestError):
            self.invoke(True)
        self.create.assert_called_once()
        self.assertEqual(self.namespace['accumulated_content'], 'Response')

    def test_all_saved_assistant_paths_and_user_updates_use_effective_metadata(self):
        metadata_dicts = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Dict):
                continue
            values = {
                key.value: value for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            metadata = values.get('metadata')
            role = values.get('role')
            if isinstance(role, ast.Constant) and role.value == 'assistant' and isinstance(metadata, ast.Dict):
                if any(
                    isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == '_build_chat_reasoning_metadata'
                    for child in ast.walk(metadata)
                ):
                    metadata_dicts.append(metadata)
        self.assertEqual(len(metadata_dicts), 4, 'Normal, streamed, cancelled and interrupted messages must persist effective effort')
        self.assertEqual(self.source.count("user_message_doc['metadata'].update(_build_chat_reasoning_metadata("), 2)
        self.assertIn("'metadata': assistant_doc.get('metadata', {})", self.source)
        self.assertNotIn("reasoning_effort != 'none'", self.source)

    def test_no_completed_direct_call_does_not_report_requested_effort_as_applied(self):
        self.assertIsNone(self.metadata()['reasoning_effort'])
        self.assertEqual(self.metadata()['reasoning_adjustments'], [])

    def test_authorized_endpoint_identity_uses_canonical_model_not_uuid_or_label(self):
        model_id = 'f8c476df-c951-499c-b87d-98fd02597780'
        endpoints = [{
            'id': endpoint_id, 'provider': 'aoai',
            'connection': {'endpoint': 'https://provider.example.test', 'api_version': 'configured-version'},
            'auth': {}, 'models': [{
                'id': model_id, 'modelName': canonical_name,
                'deploymentName': 'custom-production-deployment', 'displayName': 'GPT-5 Minimal',
            }],
        } for endpoint_id, canonical_name in (('first', LUNA), ('second', 'gpt-5-mini'))]
        namespace = dict(self.namespace)
        namespace.update({
            'get_streaming_model_endpoint_candidates': lambda *args, **kwargs: endpoints,
            'keyvault_model_endpoint_get_helper': lambda endpoint, *args, **kwargs: endpoint,
            'SecretReturnType': SimpleNamespace(VALUE='value'),
            'MODEL_ENDPOINT_PROVIDER_ALLOWLIST': {'aoai'},
            'infer_model_endpoint_protocol': lambda *args: 'azure_openai',
            'MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI': 'azure_openai',
            '_normalize_model_icon_payload': lambda value: None,
            'normalize_model_response_length_from_model': lambda value: 4096,
            'build_streaming_multi_endpoint_client': lambda *args, **kwargs: self.namespace['gpt_client'],
        })
        names = {'resolve_streaming_multi_endpoint_gpt_config', '_build_model_endpoint_behavior_name'}
        module = ast.Module(body=[
            copy.deepcopy(node) for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(ROUTE_FILE), 'exec'), namespace)
        resolver = namespace['resolve_streaming_multi_endpoint_gpt_config']
        for endpoint_id, effective in (('first', 'low'), ('second', 'minimal')):
            resolved = resolver(
                {'enable_multi_model_endpoints': True},
                {'model_id': model_id, 'model_endpoint_id': endpoint_id, 'model_provider': 'aoai'},
                'self',
            )
            self.assertEqual(resolved[1], 'custom-production-deployment')
            self.assertEqual(resolved[6], endpoint_id)
            self.assertEqual(resolved[7], model_id)
            self.create.reset_mock()
            self.create.return_value = self.completion
            _, resolution = self.namespace['_create_chat_completion_with_reasoning'](
                self.create, {'model': resolved[1], 'reasoning_effort': 'minimal'}, resolved[11],
            )
            self.assertEqual(resolution['effective_effort'], effective)
        with self.assertRaises(LookupError):
            resolver(
                {'enable_multi_model_endpoints': True},
                {'model_id': model_id, 'model_endpoint_id': 'unauthorized'},
                'self',
            )

    def test_legacy_apim_does_not_borrow_same_named_direct_endpoint_capabilities(self):
        resolver = self.namespace['_resolve_legacy_chat_reasoning_model_name']
        settings = {'gpt_model': {'selected': [{
            'deploymentName': 'production-answer', 'modelName': LUNA,
        }]}}
        self.assertEqual(resolver(settings, 'production-answer'), LUNA)
        self.assertEqual(
            resolver({**settings, 'enable_gpt_apim': True}, 'production-answer'),
            'production-answer',
        )
        self.assertEqual(resolver(settings, 'different-deployment'), 'different-deployment')
        self.assertEqual(
            resolver({'gpt_model': {'selected': [{'deploymentName': LUNA, 'modelName': ' '}]}}, LUNA),
            LUNA,
        )


if __name__ == '__main__':
    unittest.main()
