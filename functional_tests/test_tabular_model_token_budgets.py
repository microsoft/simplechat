# test_tabular_model_token_budgets.py
"""
Functional tests for scoped tabular model budgets and generation ceilings.
Version: 0.261.035
Implemented in: 0.261.035

The principal regressions use the shipped catalog and real shared resolver.
Only endpoint retrieval and model I/O are replaced with in-memory boundaries;
AST extraction avoids initializing the export module's cloud storage clients.
Missing capacities retain bounded application policies, with their generation
allowance carried through the real SDK rather than labeled as a provider maximum.
Unknown accounting retains the conservative legacy policy with a warning; new
catalog capacities may tighten, but not enlarge, that policy. The shared evidence
budget remains strict and never gains forged total-generation accounting.
Explicit checks also run under optimized Python and standalone failures raise.
Refs: #1493, PR #1497.
"""

import ast
import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
from unittest.mock import patch

import httpx
import requests
from openai import AsyncAzureOpenAI, AsyncOpenAI
from semantic_kernel.connectors.ai.open_ai import (
    AzureChatCompletion,
    AzureChatPromptExecutionSettings,
    OpenAIChatCompletion,
)
from semantic_kernel.contents.chat_history import ChatHistory as SKChatHistory

from test_tabular_row_orchestration_scale import _load_performance_helpers

# The shared standalone harness establishes the application import path first.
from functions_model_budget_runtime import prepare_model_execution_settings
from functions_model_capabilities import ModelTokenBudgetError, resolve_model_token_budget
from model_endpoint_clients import AnthropicSemanticKernelChatCompletion


EXPORT_MODULE = (
    Path(__file__).resolve().parents[1]
    / 'application' / 'single_app' / 'functions_tabular_generated_exports.py'
)


def _require_equal(actual, expected):
    if actual != expected:
        raise AssertionError(f'Expected {expected!r}, received {actual!r}')


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _expect_budget_error(operation, code):
    try:
        operation()
    except ModelTokenBudgetError as exc:
        _require_equal(exc.code, code)
    else:
        raise AssertionError(f'Expected model budget error {code!r}')


def _load_budget_helpers(selected_endpoint=None, service=None):
    helpers = _load_performance_helpers()
    endpoint_reads = []
    budget_warnings = []
    service_builds = []

    def resolve_endpoint(settings, model_context):
        endpoint_reads.append((settings, model_context))
        return selected_endpoint

    def build_service(model, settings, **kwargs):
        service_builds.append((model, settings, kwargs))
        return service, 'azure_openai'

    helpers['resolve_model_endpoint_from_context'] = resolve_endpoint
    helpers['prepare_model_execution_settings'] = prepare_model_execution_settings
    helpers['asyncio'] = asyncio
    helpers['AzureChatPromptExecutionSettings'] = AzureChatPromptExecutionSettings
    helpers['SKChatHistory'] = SKChatHistory
    helpers['logging'] = logging
    helpers['budget_warnings'] = budget_warnings
    helpers['service_builds'] = service_builds
    helpers['log_event'] = lambda message, properties, **kwargs: budget_warnings.append(
        (message, properties, kwargs)
    )
    helpers['build_semantic_kernel_chat_service_for_model'] = build_service
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node for node in module_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in {
            '_TabularBudgetedChatService', '_build_chat_service', '_stage_tabular_generated_output_source',
            '_clean_generated_json_code_fence', '_parse_generated_json_entries', '_parse_generated_json_object',
            '_invoke_tabular_semantic_model',
        }
    ]
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(EXPORT_MODULE), 'exec'), helpers)
    return helpers, endpoint_reads


def _catalog_context(model_id, provider='azure', response_length=None, model_version=None):
    context = {
        'catalogModelId': model_id,
        'provider': 'aoai' if provider == 'azure' else 'custom',
        'api_type': 'gemini' if provider == 'google' else 'openai',
        'tokenLimitProvider': provider,
    }
    if response_length is not None:
        context['responseLength'] = response_length
    if model_version is not None:
        context['modelVersion'] = model_version
    return context


def test_unknown_legacy_fallback_is_policy_not_provider_capacity():
    helpers, endpoint_reads = _load_budget_helpers()
    budget = helpers['_build_model_aware_source_batch_budget']('unknown-legacy-model', {})
    analysis = helpers['_build_model_aware_source_batch_budget'](
        'unknown-legacy-model', {}, task_type='hierarchical_analysis',
    )
    _require_equal(budget['context_token_limit'], None)
    _require_equal(budget['input_token_limit'], None)
    _require_equal(budget['output_token_limit'], None)
    _require_equal(budget['request_output_token_limit'], 65536)
    _require_equal(budget['configured_response_token_limit'], None)
    _require_equal(budget['request_output_limit_source'], 'legacy_accounting_policy')
    _require_equal(budget['output_token_accounting'], 'unknown')
    _require_equal(budget['uses_legacy_accounting_policy'], True)
    _require(budget['budget_warning'], 'The legacy accounting policy must be explicit.')
    _require_equal(budget['planning_input_token_limit'], 128000)
    _require_equal(budget['planning_output_token_limit'], 65536)
    _require_equal(budget['input_token_budget'], 59904)
    _require_equal(budget['output_token_budget'], 39321)
    _require_equal(budget['max_chars'], 104856)
    _require_equal(budget['max_rows'], 88)
    _require_equal(analysis['max_chars'], 239616)
    _require_equal(budget['limit_source'], 'fallback')
    _require(budget['uses_input_fallback_policy'], 'Legacy input policy must be labeled.')
    _require(budget['uses_output_fallback_policy'], 'Legacy output policy must be labeled.')
    _require_equal(endpoint_reads, [])


def test_selected_endpoint_partial_overrides_never_read_siblings():
    selected = {
        'id': 'authorized-endpoint',
        'provider': 'aoai',
        'inputTokenLimit': 90000,
        'outputTokenLimit': 8192,
        'auth': {'api_key': 'private-test-key'},
        'models': [{
            'id': 'selected-model',
            'deploymentName': 'shared-deployment',
            'contextWindow': 200000,
            'inputTokenLimit': None,
            'outputTokenLimit': None,
            'responseLength': 2000,
        }],
    }
    sibling = {
        'id': 'unselected-endpoint',
        'provider': 'aoai',
        'models': [{
            'id': 'selected-model',
            'deploymentName': 'shared-deployment',
            'contextWindow': 1000000,
            'outputTokenLimit': 128000,
        }],
    }
    settings = {'enable_multi_model_endpoints': True, 'model_endpoints': [sibling, selected]}
    context = {
        'endpoint_id': 'authorized-endpoint', 'model_id': 'selected-model',
        'user_id': 'authorized-user', 'model_deployment': 'shared-deployment',
    }
    before = deepcopy(settings)
    helpers, reads = _load_budget_helpers(selected)
    budget = helpers['_build_model_aware_source_batch_budget'](
        'shared-deployment', settings, model_context=context,
    )
    _require_equal(len(reads), 1)
    _require_equal(reads[0], (settings, context))
    _require_equal(settings, before)
    _require_equal(budget['context_token_limit'], 200000)
    _require_equal(budget['input_token_limit'], 90000)
    _require_equal(budget['output_token_limit'], 8192)
    _require_equal(budget['request_output_token_limit'], 2000)
    _require_equal(budget['output_token_budget'], 1200)
    _require_equal(budget['max_chars'], 3200)
    _require('private-test-key' not in json.dumps(budget), 'Budget metadata must not retain credentials.')


def test_response_length_is_model_scoped_not_an_endpoint_request_default():
    selected_model = {
        'id': 'request-model', 'deploymentName': 'request-model',
        'contextWindow': 131072, 'responseLength': 4096,
    }
    selected_endpoint = {
        'id': 'request-endpoint', 'provider': 'aoai',
        'outputTokenLimit': 32000, 'outputTokenAccounting': 'total_generation',
        'responseLength': 'unused endpoint metadata', 'tokenLimits': {'max_completion_tokens': -1},
        'models': [selected_model],
    }
    context = {'endpoint_id': selected_endpoint['id'], 'model_id': selected_model['id']}
    helpers, _ = _load_budget_helpers(selected_endpoint)
    configured = helpers['_build_model_aware_source_batch_budget'](
        'request-model', {}, model_context=context,
    )
    _require_equal(configured['output_token_limit'], 32000)
    _require_equal(configured['request_output_token_limit'], 4096)
    _require_equal(configured['request_output_limit_source'], 'configured')

    selected_model.pop('responseLength')
    defaulted = helpers['_build_model_aware_source_batch_budget'](
        'request-model', {}, model_context=context,
    )
    _require_equal(defaulted['configured_response_token_limit'], None)
    _require_equal(defaulted['request_output_token_limit'], 32000)
    _require_equal(defaulted['request_output_limit_source'], 'model_output_limit')

    selected_model['responseLength'] = -1
    _expect_budget_error(
        lambda: helpers['_build_model_aware_source_batch_budget'](
            'request-model', {}, model_context=context,
        ),
        'model_context_invalid',
    )


def test_missing_or_ambiguous_endpoint_model_never_borrows_another_model():
    selected = {
        'id': 'selected-endpoint', 'provider': 'aoai', 'contextWindow': 1000000,
        'models': [{
            'id': 'different-model', 'deploymentName': 'shared-deployment',
            'outputTokenLimit': 50000,
        }],
    }
    settings = {'enable_multi_model_endpoints': True, 'model_endpoints': [selected]}
    helpers, reads = _load_budget_helpers(selected)
    budget = helpers['_build_model_aware_source_batch_budget'](
        'shared-deployment', settings,
        model_context={'endpoint_id': 'selected-endpoint', 'model_id': 'missing-model'},
    )
    _require_equal(budget['limit_source'], 'fallback')
    _require_equal(budget['context_token_limit'], None)
    _require_equal(budget['output_token_limit'], None)
    _require_equal(len(reads), 1)

    missing_endpoint = helpers['_build_model_aware_source_batch_budget'](
        'shared-deployment', settings,
        model_context={'model_id': 'different-model', 'model_deployment': 'shared-deployment'},
    )
    _require_equal(missing_endpoint['limit_source'], 'fallback')
    _require_equal(len(reads), 1)

    selected['models'].append(dict(selected['models'][0]))
    ambiguous = helpers['_build_model_aware_source_batch_budget'](
        'shared-deployment', settings,
        model_context={'endpoint_id': 'selected-endpoint', 'model_id': 'different-model'},
    )
    _require_equal(ambiguous['limit_source'], 'fallback')


def test_legacy_aliases_keep_context_input_output_and_request_distinct():
    helpers, _ = _load_budget_helpers()
    limits = helpers['_resolve_tabular_model_token_limits'](
        'custom-deployment', {},
        model_context={
            'limits': {
                'context_length': '250000',
                'max_input_tokens': '100000',
                'max_output_tokens': '10000',
                'max_completion_tokens': '4096',
            },
        },
    )
    _require_equal(limits['context_token_limit'], 250000)
    _require_equal(limits['input_token_limit'], 100000)
    _require_equal(limits['output_token_limit'], 10000)
    _require_equal(limits['request_output_token_limit'], 4096)
    _require_equal(limits['available_input_tokens'], 100000)

    for value in (True, False, 0, -1, 100.5, float('inf'), '1.5'):
        _expect_budget_error(
            lambda: helpers['_resolve_tabular_model_token_limits'](
                'custom-deployment', {}, model_context={'limits': {'max_input_tokens': value}},
            ),
            'model_context_invalid',
        )


def test_legacy_selection_matches_the_selected_azure_endpoint_and_model():
    selected = {
        'id': 'legacy-model', 'deploymentName': 'legacy-deployment',
        'contextWindow': 200000, 'outputTokenLimit': 8192, 'responseLength': 2000,
    }
    sibling = {
        **selected, 'endpoint': 'https://other-endpoint.invalid',
        'contextWindow': 1000000, 'outputTokenLimit': 128000,
    }
    settings = {
        'azure_openai_gpt_endpoint': 'https://selected-endpoint.invalid',
        'gpt_model': {'selected': [sibling, selected]},
    }
    context = {
        'provider': 'aoai', 'endpoint': 'https://selected-endpoint.invalid',
        'model_id': 'legacy-model', 'model_deployment': 'legacy-deployment',
    }
    helpers, reads = _load_budget_helpers()
    budget = helpers['_build_model_aware_source_batch_budget'](
        'legacy-deployment', settings, model_context=context,
    )
    _require_equal(budget['context_token_limit'], 200000)
    _require_equal(budget['output_token_limit'], 8192)
    _require_equal(budget['request_output_token_limit'], 2000)
    _require_equal(reads, [])


def test_configured_chunk_model_does_not_inherit_the_conversation_model():
    settings = {
        'tabular_generated_output_chunk_model_mode': 'configured',
        'tabular_generated_output_chunk_model_deployment': 'chunk-model',
        'gpt_model': {'selected': [{
            'deploymentName': 'chunk-model', 'contextWindow': 24000,
            'outputTokenLimit': 4096, 'responseLength': 2000,
        }]},
    }
    helpers, reads = _load_budget_helpers()
    budget = helpers['_build_model_aware_source_batch_budget'](
        'conversation-model', settings,
        model_context={
            'endpoint_id': 'conversation-endpoint', 'contextWindow': 1000000,
            'outputTokenLimit': 128000, 'responseLength': 90000,
        },
    )
    _require_equal(budget['model'], 'chunk-model')
    _require_equal(budget['context_token_limit'], 24000)
    _require_equal(budget['output_token_limit'], 4096)
    _require_equal(budget['request_output_token_limit'], 2000)
    _require_equal(reads, [])


def test_actual_response_cap_not_output_max_controls_remaining_room():
    helpers, _ = _load_budget_helpers()
    context = {
        'contextWindow': 100000, 'inputTokenLimit': 80000, 'outputTokenLimit': 80000,
        'outputTokenAccounting': 'total_generation',
    }
    maximum = helpers['_build_model_aware_source_batch_budget'](
        'custom-deployment', {}, model_context=context, task_type='hierarchical_analysis',
    )
    requested = helpers['_build_model_aware_source_batch_budget'](
        'custom-deployment', {}, model_context={**context, 'responseLength': 4000},
        task_type='hierarchical_analysis',
    )
    _require_equal(maximum['input_token_budget'], 15904)
    _require_equal(requested['input_token_budget'], 35904)
    _require_equal(requested['output_token_limit'], 80000)
    _require_equal(requested['request_output_token_limit'], 4000)
    _require_equal(requested['output_token_budget'], 2400)
    _require_equal(requested['output_token_accounting_override_source'], 'context')
    _expect_budget_error(
        lambda: helpers['_build_model_aware_source_batch_budget'](
            'custom-deployment', {}, model_context={**context, 'responseLength': 80001},
        ),
        'model_context_invalid',
    )


def test_explicit_request_with_known_context_does_not_invent_an_output_maximum():
    helpers, _ = _load_budget_helpers()
    context = {
        'contextWindow': 60000, 'responseLength': 4000, 'outputTokenAccounting': 'total_generation',
    }
    budget = helpers['_build_model_aware_source_batch_budget'](
        'custom-deployment', {}, model_context=context,
    )
    _require_equal(budget['context_token_limit'], 60000)
    _require_equal(budget['output_token_limit'], None)
    _require_equal(budget['request_output_token_limit'], 4000)
    _require_equal(budget['output_token_budget'], 2400)
    _require_equal(budget['uses_output_fallback_policy'], False)
    fallback = helpers['_build_model_aware_source_batch_budget'](
        'custom-deployment', {},
        model_context={'contextWindow': 60000, 'outputTokenAccounting': 'total_generation'},
    )
    _require_equal(fallback['output_token_limit'], None)
    _require_equal(fallback['request_output_token_limit'], 30000)
    _require_equal(fallback['configured_response_token_limit'], None)
    _require_equal(fallback['request_output_limit_source'], 'fallback_policy')
    _require_equal(fallback['uses_output_fallback_policy'], True)
    _require_equal(fallback['input_token_budget'], 25904)


async def _exercise_chat_wire_budget(
    model_context, *, model='policy-model', selected_endpoint=None, settings=None, openai_compatible=False,
    expected_budget_model_id=None,
):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'policy-response', 'object': 'chat.completion', 'created': 1, 'model': model,
            'choices': [{
                'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': '{"ok":true}'},
            }],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        })

    client_type = AsyncOpenAI if openai_compatible else AsyncAzureOpenAI
    connection = (
        {'base_url': 'https://tabular-policy.invalid/v1'}
        if openai_compatible else {
            'api_version': '2024-10-21', 'azure_endpoint': 'https://tabular-policy.invalid',
        }
    )
    async with client_type(
        api_key='test-only-key',
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        max_retries=0,
        **connection,
    ) as client:
        if openai_compatible:
            native_service = OpenAIChatCompletion(
                service_id='tabular-generated-output-background', ai_model_id=model, async_client=client,
            )
        else:
            native_service = AzureChatCompletion(
                service_id='tabular-generated-output-background', deployment_name=model, async_client=client,
            )
        helpers, _ = _load_budget_helpers(selected_endpoint, native_service)
        budget = helpers['_build_model_aware_source_batch_budget'](
            model, settings or {}, model_context=model_context,
        )
        service = helpers['_build_chat_service'](
            model, settings or {}, model_context=model_context,
        )
        _require_equal(len(helpers['service_builds']), 1)
        _require_equal(helpers['service_builds'][0][0], model)
        _require_equal(helpers['service_builds'][0][2]['model_context'], model_context)
        if expected_budget_model_id is not None:
            _require_equal(service._budget.model_id, expected_budget_model_id)
        if budget['uses_legacy_accounting_policy']:
            _require_equal(service._budget.output_accounting, 'unknown')
            _expect_budget_error(service._budget.remaining_input, 'model_generation_unbounded')
            _require_equal(len(helpers['budget_warnings']), 1)
            _require_equal(helpers['budget_warnings'][0][2]['level'], logging.WARNING)
            _require(budget['budget_warning'] in helpers['budget_warnings'][0][0], 'Log the explicit policy warning.')
        else:
            _require_equal(helpers['budget_warnings'], [])
        settings_class = service.get_prompt_execution_settings_class()
        native_settings_class = native_service.get_prompt_execution_settings_class()
        _require_equal(settings_class, native_settings_class)
        history = SKChatHistory()
        history.add_user_message('Return one JSON object.')
        original_settings = AzureChatPromptExecutionSettings(service_id=service.service_id)
        result = await service.get_chat_message_contents(history, original_settings)
        _require_equal(result[0].content, '{"ok":true}')
        _require_equal(original_settings.max_tokens, None)
        _require_equal(original_settings.max_completion_tokens, None)
        semantic_result = await helpers['_invoke_tabular_semantic_model'](
            service, 'Return JSON.', 'Return one JSON object.',
            'tabular-semantic-verifier', 5,
        )
        _require_equal(semantic_result, {'ok': True})
    return budget, requests


def test_partial_capacities_with_declared_accounting_send_sdk_generation_policy():
    async def exercise_cases():
        for context, expected_limit, expected_source in (
            ({}, 65536, 'fallback_policy'),
            ({'contextWindow': 200000}, 65536, 'fallback_policy'),
            ({'contextWindow': 60000}, 30000, 'fallback_policy'),
            ({'inputTokenLimit': 60000}, 65536, 'fallback_policy'),
            ({'outputTokenLimit': 8192}, 8192, 'model_output_limit'),
            ({'contextWindow': 10000, 'outputTokenLimit': 20000}, 5903, 'model_output_limit'),
            ({'contextWindow': 4098}, 1, 'fallback_policy'),
        ):
            budget, requests = await _exercise_chat_wire_budget({
                **context, 'outputTokenAccounting': 'total_generation',
            })
            _require_equal(budget['output_token_limit'], context.get('outputTokenLimit'))
            _require_equal(budget['configured_response_token_limit'], None)
            _require_equal(budget['request_output_token_limit'], expected_limit)
            _require_equal(budget['request_output_limit_source'], expected_source)
            _require_equal(budget['uses_output_fallback_policy'], expected_source == 'fallback_policy')
            _require_equal(budget['output_token_accounting_override_source'], 'context')
            _require_equal(len(requests), 2)
            for request in requests:
                _require_equal(request['max_tokens'], expected_limit)
                _require('max_completion_tokens' not in request, 'Send only one generation ceiling.')
            if context.get('contextWindow'):
                total = budget['input_token_budget'] + 4096 + expected_limit
                _require(total <= context['contextWindow'], 'Input, prompt reserve, and generation must fit.')
            if context.get('inputTokenLimit'):
                _require(
                    budget['input_token_budget'] + 4096 <= context['inputTokenLimit'],
                    'An independent input cap bounds input without subtracting output.',
                )

    asyncio.run(exercise_cases())


def test_anthropic_generation_policy_replaces_the_adapter_default_on_the_wire():
    sent_payloads = []

    def respond(_session, request, **kwargs):
        sent_payloads.append(json.loads(request.body))
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response._content = json.dumps({
            'id': 'policy-response', 'type': 'message', 'role': 'assistant',
            'model': 'policy-anthropic', 'content': [{'type': 'text', 'text': '{"ok":true}'}],
            'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1},
        }).encode('utf-8')
        return response

    native_service = AnthropicSemanticKernelChatCompletion(
        service_id='tabular-generated-output-background',
        deployment_name='policy-anthropic',
        endpoint='https://tabular-policy.invalid/anthropic',
        api_key='test-only-key',
    )
    helpers, _ = _load_budget_helpers(service=native_service)
    context = {
        'provider': 'anthropic',
        'endpoint': 'https://tabular-policy.invalid/anthropic',
        'contextWindow': 60000,
    }
    budget = helpers['_build_model_aware_source_batch_budget'](
        'policy-anthropic', {}, model_context=context,
    )
    service = helpers['_build_chat_service']('policy-anthropic', {}, model_context=context)
    with patch.object(requests.Session, 'send', autospec=True, side_effect=respond):
        result = asyncio.run(helpers['_invoke_tabular_semantic_model'](
            service, 'Return JSON.', 'Return one JSON object.', 'tabular-semantic-verifier', 5,
        ))
    _require_equal(result, {'ok': True})
    _require_equal(budget['output_token_limit'], None)
    _require_equal(budget['request_output_token_limit'], 30000)
    _require_equal(sent_payloads[0]['max_tokens'], 30000)
    _require('max_completion_tokens' not in sent_payloads[0], 'Anthropic accepts the single max_tokens ceiling.')


def test_unbounded_protocol_and_exhausted_context_errors_remain_explicit():
    helpers, _ = _load_budget_helpers()
    build_budget = helpers['_build_model_aware_source_batch_budget']
    for metadata in ({'contextWindow': 60000}, {'outputTokenLimit': 8192}, {}):
        _expect_budget_error(
            lambda: build_budget(
                'unbounded-model', {},
                model_context={**metadata, 'outputTokenAccounting': 'visible_only'},
            ),
            'model_generation_unbounded',
        )
    for metadata in (
        {'contextWindow': 4097},
        {'inputTokenLimit': 4096},
        {'contextWindow': 10000, 'responseLength': 10000},
    ):
        _expect_budget_error(
            lambda: build_budget(
                'exhausted-model', {},
                model_context={**metadata, 'outputTokenAccounting': 'total_generation'},
            ),
            'model_context_exhausted',
        )
    _expect_budget_error(
        lambda: build_budget(
            'grok-imagine-image', {},
            model_context=_catalog_context('grok-imagine-image', 'xai'),
        ),
        'model_context_unavailable',
    )


def test_unknown_accounting_retains_legacy_policy_without_forging_shared_budget():
    helpers, _ = _load_budget_helpers()
    for metadata in (
        {},
        {'contextWindow': 10485760},
        {'inputTokenLimit': 1048576, 'outputTokenLimit': 65536},
        {'outputTokenLimit': 32768},
        {'contextWindow': 60000, 'inputTokenLimit': 12000, 'outputTokenLimit': 5000},
        {'contextWindow': 1000000, 'outputTokenLimit': 200000, 'responseLength': 128000},
    ):
        context = {**metadata, 'outputTokenAccounting': 'unknown'}
        limits = helpers['_resolve_tabular_model_token_limits'](
            'legacy-accounting-model', {}, model_context=context,
        )
        budget = helpers['_build_model_aware_source_batch_budget'](
            'legacy-accounting-model', {}, model_context=context,
        )
        analysis = helpers['_build_model_aware_source_batch_budget'](
            'legacy-accounting-model', {}, model_context=context, task_type='hierarchical_analysis',
        )
        _require_equal(limits['model_token_budget'].output_accounting, 'unknown')
        _expect_budget_error(limits['model_token_budget'].remaining_input, 'model_generation_unbounded')
        _require_equal(budget['output_token_limit'], metadata.get('outputTokenLimit'))
        _require_equal(budget['configured_response_token_limit'], metadata.get('responseLength'))
        _require_equal(budget['uses_legacy_accounting_policy'], True)
        _require_equal(budget['request_output_limit_source'], 'legacy_accounting_policy')
        _require(budget['budget_warning'], 'Unverified accounting needs an explicit policy warning.')
        _require(budget['planning_input_token_limit'] <= 128000, 'Do not adopt a larger catalog input window.')
        _require(budget['request_output_token_limit'] <= 65536, 'Keep the legacy request ceiling.')
        _require(budget['input_token_budget'] <= 59904, 'Do not enlarge default legacy input batches.')
        _require(budget['output_token_budget'] <= 39321, 'Do not enlarge default legacy output batches.')
        _require(budget['max_chars'] <= 104856, 'Structured batches must stay inside the legacy policy.')
        _require(analysis['max_chars'] <= 239616, 'Analysis must stay inside the legacy input policy.')
        if metadata.get('contextWindow'):
            planned_total = budget['input_token_budget'] + 4096 + budget['request_output_token_limit']
            _require(planned_total <= metadata['contextWindow'], 'Respect tighter known shared context.')
        if metadata.get('inputTokenLimit'):
            _require(
                budget['input_token_budget'] + 4096 <= metadata['inputTokenLimit'],
                'Respect tighter independent input limits.',
            )

    for metadata in ({'contextWindow': 4097}, {'inputTokenLimit': 4096}):
        _expect_budget_error(
            lambda: helpers['_build_model_aware_source_batch_budget'](
                'exhausted-legacy-policy', {},
                model_context={**metadata, 'outputTokenAccounting': 'unknown'},
            ),
            'model_context_exhausted',
        )
    _expect_budget_error(
        lambda: helpers['_build_model_aware_source_batch_budget'](
            'invalid-legacy-policy', {},
            model_context={
                'outputTokenAccounting': 'unknown', 'outputTokenLimit': 8192, 'responseLength': 8193,
            },
        ),
        'model_context_invalid',
    )


def test_unknown_accounting_request_policy_is_bounded_on_the_wire():
    async def exercise_cases():
        for context, expected_cap in (
            ({'contextWindow': 10485760}, 65536),
            ({'inputTokenLimit': 1048576}, 65536),
            ({'contextWindow': 60000}, 30000),
            ({'outputTokenLimit': 8192}, 8192),
            ({'contextWindow': 1000000, 'outputTokenLimit': 200000, 'responseLength': 128000}, 65536),
        ):
            budget, requests = await _exercise_chat_wire_budget({
                **context, 'outputTokenAccounting': 'unknown',
            })
            _require_equal(budget['output_token_accounting'], 'unknown')
            _require_equal(budget['request_output_token_limit'], expected_cap)
            for request in requests:
                _require_equal(request['max_tokens'], expected_cap)

    asyncio.run(exercise_cases())


def test_real_catalog_openweight_fallback_uses_verified_host_accounting():
    selected = {
        'id': 'verified-serving-endpoint',
        'provider': 'aifoundry',
        'outputTokenAccounting': 'total_generation',
        'models': [{
            'id': 'selected-openweight',
            'deploymentName': 'tabular-llama',
            'catalogModelId': 'llama-3.3-70b-instruct',
        }],
    }
    context = {'endpoint_id': selected['id'], 'model_id': 'selected-openweight'}
    budget, requests = asyncio.run(_exercise_chat_wire_budget(
        context,
        model='tabular-llama',
        selected_endpoint=selected,
        settings={'enable_multi_model_endpoints': True},
    ))
    _require_equal(budget['context_token_limit'], 131072)
    _require_equal(budget['output_token_limit'], None)
    _require_equal(budget['request_output_token_limit'], 65536)
    _require_equal(budget['input_token_budget'], 61440)
    _require_equal(budget['request_output_limit_source'], 'fallback_policy')
    _require_equal(requests[0]['max_tokens'], 65536)

    unverified_endpoint = {key: value for key, value in selected.items() if key != 'outputTokenAccounting'}
    legacy_budget, legacy_requests = asyncio.run(_exercise_chat_wire_budget(
        context,
        model='tabular-llama',
        selected_endpoint=unverified_endpoint,
        settings={'enable_multi_model_endpoints': True},
    ))
    _require_equal(legacy_budget['context_token_limit'], 131072)
    _require_equal(legacy_budget['output_token_limit'], None)
    _require_equal(legacy_budget['output_token_accounting'], 'unknown')
    _require_equal(legacy_budget['output_token_accounting_override_source'], None)
    _require_equal(legacy_budget['planning_input_token_limit'], 128000)
    _require_equal(legacy_budget['input_token_budget'], 59904)
    _require_equal(legacy_budget['uses_legacy_accounting_policy'], True)
    _require_equal(legacy_requests[0]['max_tokens'], 65536)


def test_large_context_threshold_and_small_input_boundary_are_preserved():
    helpers, _ = _load_budget_helpers()
    for context_window, expected in ((499999, 245903), (500000, 245904), (500001, 145904)):
        budget = helpers['_build_model_aware_source_batch_budget'](
            'custom-deployment', {}, task_type='hierarchical_analysis',
            model_context={
                'contextWindow': context_window, 'outputTokenLimit': 100000,
                'outputTokenAccounting': 'total_generation',
            },
        )
        _require_equal(budget['input_token_budget'], expected)

    context = {
        'contextWindow': 10000, 'outputTokenLimit': 9000, 'responseLength': 5000,
        'outputTokenAccounting': 'total_generation',
    }
    just_below = helpers['_build_model_aware_source_batch_budget'](
        'custom-deployment', {}, model_context=context, user_question='x' * 3612,
    )
    _require_equal(just_below['input_token_budget'], 1)
    _require_equal(just_below['max_chars'], 4)
    _require_equal(just_below['max_rows'], 1)
    for question_chars in (3616, 3620):
        _expect_budget_error(
            lambda: helpers['_build_model_aware_source_batch_budget'](
                'custom-deployment', {}, model_context=context, user_question='x' * question_chars,
            ),
            'model_context_exhausted',
        )


def test_small_character_budget_survives_source_staging():
    helpers, _ = _load_budget_helpers()
    source_rows = [{'value': 'x' * 1700} for _ in range(3)]
    checkpoints = []

    def checkpoint(run, rows, source_scan_row_count):
        checkpoints.append(list(rows))
        run['source_staged_rows'] = run.get('source_staged_rows', 0) + len(rows)
        run['source_staged_batches'] = len(checkpoints)
        run['source_scan_row_count'] = source_scan_row_count
        return run

    helpers.update({
        'TABULAR_EXTENSIONS': {'csv'},
        '_iter_versioned_tabular_source_rows': lambda *args: enumerate(source_rows, start=1),
        '_dump_generated_output_json': json.dumps,
        '_checkpoint_source_input_batch': checkpoint,
        '_input_blob_path': lambda *args: args[-1],
        '_download_json_blob': lambda batch_number: checkpoints[batch_number - 1],
        '_write_chunk_manifest_for_run': lambda *args, **kwargs: kwargs,
        '_now_iso': lambda: '2026-09-19T15:00:00+00:00',
        '_replace_claimed_run': lambda run: run,
    })
    result = helpers['_stage_tabular_generated_output_source'](
        {
            'id': 'bounded-staging-run',
            'source_descriptor': {
                'kind': 'query_tabular_data', 'source_format': 'csv', 'expected_row_count': 3,
                'batch_max_rows': 3, 'batch_max_chars': 3200,
            },
        },
        {},
    )
    _require_equal([len(batch) for batch in checkpoints], [1, 1, 1])
    _require_equal(result['row_count'], 3)
    _require_equal(result['batch_count'], 3)


def test_scoped_effective_context_remains_a_separate_constraint():
    helpers, _ = _load_budget_helpers()
    record = {
        'id': 'effective-context-model',
        'contextWindow': 150000, 'inputTokenLimit': 80000, 'outputTokenLimit': 60000,
        'outputTokenAccounting': 'total_generation',
        'tokenLimitProfiles': [{
            'id': 'azure-chat', 'provider': 'azure', 'protocol': 'chat_completions',
            'effectiveContextWindow': 60000,
        }],
    }
    budget = helpers['_build_model_aware_source_batch_budget'](
        'effective-context-model', {}, catalog_records=[record],
        model_context={'responseLength': 40000},
    )
    _require_equal(budget['context_token_limit'], 150000)
    _require_equal(budget['input_token_limit'], 80000)
    _require_equal(budget['effective_context_token_limit'], 60000)
    _require_equal(budget['input_token_budget'], 15904)


def test_real_catalog_terra_selected_deployment_and_wire_ceiling():
    class RecordingService:
        service_id = 'tabular-generated-output-background'

        def __init__(self):
            self.requests = []

        async def get_chat_message_contents(self, chat_history, settings, **kwargs):
            self.requests.append(settings.prepare_settings_dict())
            return ['model-response']

    selected = {
        'id': 'approved-endpoint', 'provider': 'aoai',
        'models': [{
            'id': 'approved-model', 'deploymentName': 'prod-west-terra',
            'catalogModelId': 'gpt-5.6-terra', 'responseLength': 8192,
        }],
    }
    sibling = {
        'id': 'sibling-endpoint', 'provider': 'aoai',
        'models': [{
            'id': 'approved-model', 'deploymentName': 'prod-west-terra',
            'catalogModelId': 'gpt-5-mini', 'outputTokenLimit': 16,
        }],
    }
    settings = {'enable_multi_model_endpoints': True, 'model_endpoints': [sibling, selected]}
    context = {'endpoint_id': 'approved-endpoint', 'model_id': 'approved-model'}
    recording_service = RecordingService()
    helpers, reads = _load_budget_helpers(selected, recording_service)
    _require(helpers['resolve_model_token_budget'] is resolve_model_token_budget, 'Use the real catalog resolver.')
    budget = helpers['_build_model_aware_source_batch_budget'](
        'prod-west-terra', settings, model_context=context,
    )
    _require_equal(budget['context_token_limit'], 1050000)
    _require_equal(budget['input_token_limit'], 922000)
    _require_equal(budget['output_token_limit'], 128000)
    _require_equal(budget['request_output_token_limit'], 8192)
    _require_equal(budget['input_token_budget'], 175904)
    _require_equal(budget['output_token_budget'], 4915)
    _require_equal(budget['max_chars'], 13106)
    _require_equal(budget['limit_source'], 'catalog')
    service = helpers['_build_chat_service']('prod-west-terra', settings, model_context=context)
    original = AzureChatPromptExecutionSettings(service_id=recording_service.service_id, max_tokens=32000)
    result = asyncio.run(service.get_chat_message_contents([], original))
    _require_equal(result, ['model-response'])
    _require_equal(recording_service.requests[0]['max_completion_tokens'], 8192)
    _require('max_tokens' not in recording_service.requests[0], 'Only one output parameter may reach the provider.')
    _require_equal(original.max_tokens, 32000)
    _require_equal(len(reads), 2)


def test_real_catalog_partial_model_endpoint_catalog_inheritance():
    selected = {
        'id': 'approved-endpoint', 'provider': 'aoai', 'inputTokenLimit': 800000,
        'models': [{
            'id': 'approved-model', 'deploymentName': 'partial-terra',
            'catalogModelId': 'gpt-5.6-terra', 'contextWindow': 1200000,
            'outputTokenLimit': None, 'responseLength': 4096,
        }],
    }
    helpers, _ = _load_budget_helpers(selected)
    budget = helpers['_build_model_aware_source_batch_budget'](
        'partial-terra', {'enable_multi_model_endpoints': True},
        model_context={'endpoint_id': 'approved-endpoint', 'model_id': 'approved-model'},
    )
    _require_equal(budget['context_token_limit'], 1200000)
    _require_equal(budget['input_token_limit'], 800000)
    _require_equal(budget['output_token_limit'], 128000)
    _require_equal(budget['request_output_token_limit'], 4096)
    _require_equal(budget['limit_source'], 'configured+catalog')


def test_real_catalog_provider_and_model_version_profiles():
    helpers, _ = _load_budget_helpers()
    resolve = helpers['_resolve_tabular_model_token_limits']
    azure_pro = resolve_model_token_budget(
        'gpt-5-pro', provider='azure', protocol='responses', request_output_limit=4096,
    )
    openai_pro = resolve_model_token_budget(
        'gpt-5-pro', provider='openai', protocol='responses', request_output_limit=4096,
    )
    _require_equal((azure_pro.context_window, azure_pro.input_limit, azure_pro.output_limit), (400000, 272000, 128000))
    _require_equal((openai_pro.context_window, openai_pro.input_limit, openai_pro.output_limit), (400000, None, 272000))
    for version in ('2026-05-05', '2026-05-28', '2026-06-24'):
        old_chat = resolve(
            'gpt-chat-latest', {},
            model_context=_catalog_context('gpt-chat-latest', 'azure', 4096, version),
        )
        _require_equal(old_chat['context_token_limit'], 128000)
        _require_equal(old_chat['input_token_limit'], 111616)
        _require_equal(old_chat['output_token_limit'], 16384)
    new_chat = resolve(
        'gpt-chat-latest', {},
        model_context=_catalog_context('gpt-chat-latest', 'azure', 4096, '2026-08-06'),
    )
    _require_equal(new_chat['context_token_limit'], 400000)
    _require_equal(new_chat['input_token_limit'], 272000)
    _require_equal(new_chat['output_token_limit'], 128000)
    for version in (None, 'unrecognized-version'):
        unknown_chat = resolve(
            'gpt-chat-latest', {},
            model_context=_catalog_context('gpt-chat-latest', 'azure', 4096, version),
        )
        _require_equal(unknown_chat['context_token_limit'], None)
        _require_equal(unknown_chat['input_token_limit'], None)
        _require_equal(unknown_chat['output_token_limit'], None)


def test_google_chat_accounting_does_not_inherit_another_api_contract():
    raw_budget = resolve_model_token_budget(
        'gemini-2.5-pro', provider='google', protocol='chat_completions',
        request_output_limit=65536,
    )
    _require_equal(raw_budget.input_limit, 1048576)
    _require_equal(raw_budget.output_limit, 65536)
    _require_equal(raw_budget.output_accounting, 'unknown')
    _expect_budget_error(raw_budget.remaining_input, 'model_generation_unbounded')
    context = _catalog_context('gemini-2.5-pro', 'google', 65536)
    budget, requests = asyncio.run(_exercise_chat_wire_budget(
        context, model='gemini-2.5-pro', openai_compatible=True,
    ))
    _require_equal(budget['input_token_limit'], 1048576)
    _require_equal(budget['output_token_limit'], 65536)
    _require_equal(budget['output_token_accounting'], 'unknown')
    _require_equal(budget['output_token_accounting_override_source'], None)
    _require_equal(budget['uses_legacy_accounting_policy'], True)
    _require_equal(budget['planning_input_token_limit'], 128000)
    _require_equal(budget['input_token_budget'], 59904)
    _require_equal(budget['output_token_budget'], 39321)
    _require_equal(budget['max_chars'], 104856)
    _require_equal(budget['max_rows'], 88)
    _require_equal(requests[0]['max_tokens'], 65536)
    helpers, _ = _load_budget_helpers()
    analysis = helpers['_build_model_aware_source_batch_budget'](
        'gemini-2.5-pro', {}, model_context=context, task_type='hierarchical_analysis',
    )
    _require_equal(analysis['max_chars'], 239616)


def test_latest_chat_catalog_identity_does_not_replace_the_selected_wire_model():
    async def exercise_hosts():
        for provider, wire_model, version, expected_context in (
            ('openai', 'chat-latest', None, 400000),
            ('azure', 'azure-chat-prod', '2026-05-05', 128000),
        ):
            selected_model = {
                'id': 'selected-chat-model', 'catalogModelId': 'gpt-chat-latest', 'responseLength': 4096,
            }
            if provider == 'openai':
                selected_model['modelName'] = wire_model
            else:
                selected_model.update({
                    'deploymentName': wire_model, 'modelName': 'gpt-chat-latest', 'modelVersion': version,
                })
            selected_endpoint = {
                'id': 'selected-chat-endpoint',
                'provider': 'custom' if provider == 'openai' else 'aoai',
                'api_type': 'openai' if provider == 'openai' else '',
                'tokenLimitProvider': provider,
                'models': [selected_model],
            }
            budget, requests = await _exercise_chat_wire_budget(
                {'endpoint_id': selected_endpoint['id'], 'model_id': selected_model['id']},
                model=wire_model,
                selected_endpoint=selected_endpoint,
                settings={'enable_multi_model_endpoints': True},
                openai_compatible=provider == 'openai',
                expected_budget_model_id='gpt-chat-latest',
            )
            _require_equal(budget['model'], wire_model)
            _require_equal(budget['context_token_limit'], expected_context)
            for request in requests:
                _require_equal(request['model'], wire_model)
                _require(request['model'] != 'gpt-chat-latest', 'Do not promote a catalog identity to a wire ID.')

    asyncio.run(exercise_hosts())


def test_unlisted_google_chat_does_not_gain_a_provider_wide_accounting_default():
    raw_budget = resolve_model_token_budget(
        'unlisted-gemini-contract', provider='google', protocol='chat_completions',
    )
    _require_equal(raw_budget.output_accounting, 'unknown')
    helpers, _ = _load_budget_helpers()
    budget = helpers['_build_model_aware_source_batch_budget'](
        'unlisted-gemini-contract', {},
        model_context=_catalog_context('unlisted-gemini-contract', 'google', 8192),
    )
    _require_equal(budget['output_token_accounting'], 'unknown')
    _require_equal(budget['uses_legacy_accounting_policy'], True)
    _require_equal(budget['planning_input_token_limit'], 128000)
    _require_equal(budget['request_output_token_limit'], 8192)


def test_real_catalog_google_independent_input_with_explicit_operator_accounting():
    native_budget_before = resolve_model_token_budget(
        'gemini-2.5-pro', provider='google', protocol='chat_completions',
    )
    selected = {
        'id': 'operator-google-endpoint',
        'provider': 'custom',
        'api_type': 'gemini',
        'tokenLimitProvider': 'google',
        'outputTokenAccounting': 'total_generation',
        'models': [{
            'id': 'selected-gemini', 'modelName': 'gemini-2.5-pro', 'responseLength': 65536,
        }],
    }
    model_context = {'endpoint_id': selected['id'], 'model_id': 'selected-gemini'}
    helpers, _ = _load_budget_helpers(selected)
    limits = helpers['_resolve_tabular_model_token_limits'](
        'gemini-2.5-pro', {}, model_context=model_context,
    )
    budget = helpers['_build_model_aware_source_batch_budget'](
        'gemini-2.5-pro', {}, model_context=model_context,
        task_type='hierarchical_analysis',
    )
    _require_equal(limits['context_token_limit'], None)
    _require_equal(limits['input_token_limit'], 1048576)
    _require_equal(limits['output_token_limit'], 65536)
    _require_equal(limits['available_input_tokens'], 1048576)
    _require_equal(budget['input_token_budget'], 175904)
    _require_equal(budget['max_chars'], 703616)
    _require_equal(budget['output_token_accounting'], 'total_generation')
    _require_equal(budget['output_token_accounting_override_source'], 'endpoint')
    unchanged_native_budget = resolve_model_token_budget(
        'gemini-2.5-pro', provider='google', protocol='chat_completions',
    )
    _require_equal(unchanged_native_budget, native_budget_before)


def test_real_catalog_xai_default_and_visible_only_cap_are_not_hard_limits():
    raw_budget = resolve_model_token_budget('grok-4.5', provider='xai', protocol='chat_completions')
    _require_equal(raw_budget.context_window, 500000)
    _require_equal(raw_budget.output_limit, None)
    _require_equal(raw_budget.request_output_limit, None)
    helpers, _ = _load_budget_helpers()
    _expect_budget_error(
        lambda: helpers['_build_model_aware_source_batch_budget'](
            'grok-4.5', {}, model_context=_catalog_context('grok-4.5', 'xai', 160000),
        ),
        'model_generation_unbounded',
    )


def test_real_catalog_does_not_match_sibling_or_display_only_names():
    helpers, _ = _load_budget_helpers()
    for identifier in ('gpt-5.6-terra-unverified-sibling', 'unverified-private-deployment'):
        budget = helpers['_build_model_aware_source_batch_budget'](
            identifier, {},
            model_context={'displayName': 'gpt-5.6-terra', 'model_id': 'unrelated-internal-id'},
        )
        _require_equal(budget['limit_source'], 'fallback')
        _require_equal(budget['context_token_limit'], None)
        _require_equal(budget['output_token_limit'], None)


def main():
    tests = [
        value for name, value in globals().items()
        if name.startswith('test_') and callable(value)
    ]
    for test in tests:
        test()
    print(f'Passed {len(tests)} tabular model-budget tests.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
