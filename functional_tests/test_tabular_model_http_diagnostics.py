# test_tabular_model_http_diagnostics.py
"""Functional tests for scoped tabular model HTTP diagnostics.

Version: 0.261.057
Implemented in: 0.261.057 (diagnostic change; version bump deferred)

Validate real SDK retries, failed reads, diagnostic budgets, and metadata privacy
using mocked HTTP transport without cloud calls.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import AsyncAzureOpenAI
import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / 'application' / 'single_app'
sys.path.insert(0, str(APP_ROOT))

import functions_tabular_model_diagnostics as diagnostics
from functions_appinsights import _build_logger_extra
from test_custom_model_endpoint_provider import load_model_endpoint_runtime_module, _restore_modules


def test_real_sdk_retries_are_recorded_without_payloads():
    events = []
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadError('sensitive-error-body', request=request)
        return httpx.Response(200, headers={'x-request-id': 'provider-request-123'}, json={
            'id': 'completion-123', 'object': 'chat.completion', 'created': 1,
            'model': 'test-model',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'sensitive-result'}, 'finish_reason': 'stop'}],
        })

    async def probe():
        transport = diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=10, transport=httpx.MockTransport(handler), timeout=5,
        )
        async with AsyncAzureOpenAI(
            api_key='sensitive-api-key', azure_endpoint='https://private-host.example.com',
            api_version='2024-10-21', max_retries=1, http_client=transport,
        ) as client:
            result = await client.chat.completions.create(
                model='private-deployment', messages=[{'role': 'user', 'content': 'sensitive-prompt'}],
            )
            assert result.choices[0].message.content == 'sensitive-result'

    with patch.object(diagnostics, 'log_event', side_effect=lambda message, **kwargs: events.append((message, kwargs))):
        asyncio.run(probe())
    operations = [event[1]['extra']['operation'] for event in events]
    assert operations == ['attempt_started', 'attempt_failed', 'attempt_started', 'attempt_completed']
    completed = events[-1][1]['extra']
    assert completed['retry_count'] == 1
    assert completed['provider_request_id'] == 'provider-request-123'
    assert completed['duration_ms'] >= 0
    assert events[0][1]['extra']['diagnostic_run_id'] == completed['diagnostic_run_id']
    serialized = json.dumps(events)
    for sensitive in ('sensitive-api-key', 'sensitive-prompt', 'sensitive-result', 'sensitive-error-body', 'private-host', 'private-deployment'):
        assert sensitive not in serialized


def test_diagnostics_are_opt_in_and_tabular_only():
    with patch.dict('os.environ', {}, clear=True):
        disabled = diagnostics.build_tabular_model_http_options('tabular-analysis')
    assert disabled == {}
    with patch.dict('os.environ', {diagnostics.DIAGNOSTICS_ENV: 'true'}, clear=True):
        unrelated = diagnostics.build_tabular_model_http_options('chat-model')
        enabled = diagnostics.build_tabular_model_http_options('tabular-analysis')
    assert unrelated == {}
    assert enabled['timeout'] == 60
    assert enabled['max_retries'] == 0
    asyncio.run(enabled['http_client'].aclose())


@pytest.mark.parametrize('token_auth', [False, True])
def test_runtime_builder_uses_diagnostic_client_for_tabular_only(token_auth):
    runtime, original_modules = load_model_endpoint_runtime_module()
    authentication = (
        {'azure_ad_token_provider': lambda: 'sensitive-entra-token'}
        if token_auth else {'api_key': 'test-key'}
    )
    try:
        with patch.dict('os.environ', {diagnostics.DIAGNOSTICS_ENV: 'true'}, clear=True):
            service = runtime._build_azure_chat_completion(
                service_id='tabular-analysis', deployment_name='test-model',
                endpoint='https://models.example.com', api_version='2024-10-21',
                default_headers={'X-Diagnostic-Test': 'retained'}, **authentication,
            )
            ordinary = runtime._build_azure_chat_completion(
                service_id='chat-model', deployment_name='test-model',
                endpoint='https://models.example.com', api_version='2024-10-21', api_key='test-key',
            )
        assert isinstance(service.client._client, diagnostics.TabularDiagnosticAsyncClient)
        assert service.client.max_retries == 0
        assert service.client.timeout == 60
        assert service.client.default_headers['X-Diagnostic-Test'] == 'retained'
        assert not isinstance(ordinary.client._client, diagnostics.TabularDiagnosticAsyncClient)
        asyncio.run(service.client.close())
        asyncio.run(ordinary.client.close())
    finally:
        sys.modules.pop('functions_model_endpoint_runtime', None)
        _restore_modules(original_modules)


def test_diagnostic_metadata_survives_log_sanitization():
    metadata = _build_logger_extra('[TABULAR_MODEL_HTTP] attempt_failed', {
        'diagnostic_run_id': 'run-123', 'http_attempt_id': 'attempt-123',
        'endpoint_fingerprint': '1234567890abcdef', 'provider_request_id': 'provider-123',
        'duration_ms': 12.5, 'retry_count': 1, 'error_type': 'ReadError',
    })
    assert metadata['sc_diagnostic_run_id'] == 'run-123'
    assert metadata['sc_http_attempt_id'] == 'attempt-123'
    assert metadata['sc_endpoint_fingerprint'] == '1234567890abcdef'
    assert metadata['sc_provider_request_id'] == 'provider-123'
    assert metadata['sc_duration_ms'] == 12.5


def test_http_status_retries_are_recorded_as_separate_attempts():
    events = []
    requests = []

    def handler(request):
        requests.append(request)
        status = 429 if len(requests) == 1 else 200
        return httpx.Response(status, headers={
            'retry-after-ms': '1', 'x-request-id': f'provider-{len(requests)}',
        }, json={
            'id': 'completion-123', 'object': 'chat.completion', 'created': 1,
            'model': 'test-model',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}],
        })

    async def probe():
        transport = diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=10, transport=httpx.MockTransport(handler),
        )
        async with AsyncAzureOpenAI(
            api_key='test-key', azure_endpoint='https://models.example.com',
            api_version='2024-10-21', max_retries=1, http_client=transport,
        ) as client:
            await client.chat.completions.create(
                model='test-model', messages=[{'role': 'user', 'content': 'private-prompt'}],
            )

    with patch.object(diagnostics, 'log_event', side_effect=lambda message, **kwargs: events.append(kwargs['extra'])):
        asyncio.run(probe())
    completions = [event for event in events if event['operation'] == 'attempt_completed']
    assert [event['status_code'] for event in completions] == [429, 200]
    assert [event['retry_count'] for event in completions] == [0, 1]
    assert completions[0]['success'] is False
    assert completions[1]['success'] is True
    assert completions[0]['http_attempt_id'] != completions[1]['http_attempt_id']


def test_failure_before_headers_is_logged_and_reraised():
    events = []

    async def handler(request):
        raise httpx.ReadError('private-network-details', request=request)

    async def probe():
        async with diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=5, transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(httpx.ReadError):
                await client.get('https://models.example.com')

    with patch.object(diagnostics, 'log_event', side_effect=lambda message, **kwargs: events.append(kwargs['extra'])):
        asyncio.run(probe())
    assert events[-1]['operation'] == 'attempt_failed'
    assert events[-1]['error_type'] == 'ReadError'
    assert 'private-network-details' not in json.dumps(events)


def test_budget_cancels_a_request_waiting_for_headers():
    events = []

    async def handler(request):
        await asyncio.Event().wait()

    async def probe():
        async with diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=0.01, transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(TimeoutError):
                await client.get('https://models.example.com')

    with patch.object(diagnostics, 'log_event', side_effect=lambda message, **kwargs: events.append(kwargs['extra'])):
        asyncio.run(probe())
    assert events[-1]['operation'] == 'attempt_failed'
    assert events[-1]['budget_exhausted'] is True


def test_budget_is_shared_across_attempts():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200)

    async def probe():
        async with diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=1, transport=httpx.MockTransport(handler),
        ) as client:
            await client.get('https://models.example.com')
            client._first_attempt_at = time.monotonic() - 2
            with pytest.raises(TimeoutError):
                await client.get('https://models.example.com')

    with patch.object(diagnostics, 'log_event'):
        asyncio.run(probe())
    assert len(requests) == 1


@pytest.mark.parametrize('raw_value', ['nan', 'inf', '-1', '0', 'not-a-number', '999999'])
def test_invalid_environment_options_fall_back_to_safe_defaults(raw_value):
    with patch.dict('os.environ', {
        diagnostics.DIAGNOSTICS_ENV: 'true',
        diagnostics.TIMEOUT_ENV: raw_value,
        diagnostics.BUDGET_ENV: raw_value,
        diagnostics.RETRIES_ENV: 'invalid',
    }, clear=True):
        options = diagnostics.build_tabular_model_http_options('tabular-analysis')
    assert options['timeout'] == 60
    assert options['max_retries'] == 0
    assert options['http_client'].budget_seconds == 180
    asyncio.run(options['http_client'].aclose())


def test_cancellation_is_logged_and_propagates():
    events = []

    async def handler(request):
        raise asyncio.CancelledError()

    async def probe():
        async with diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=5, transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(asyncio.CancelledError):
                await client.get('https://models.example.com')

    with patch.object(diagnostics, 'log_event', side_effect=lambda message, **kwargs: events.append(kwargs['extra'])):
        asyncio.run(probe())
    assert events[-1]['error_type'] == 'CancelledError'


def test_telemetry_failure_does_not_break_the_model_request():
    async def probe():
        async with diagnostics.TabularDiagnosticAsyncClient(
            budget_seconds=5, transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        ) as client:
            response = await client.get('https://models.example.com')
        assert response.status_code == 200

    with patch.object(diagnostics, 'log_event', side_effect=RuntimeError('telemetry unavailable')):
        asyncio.run(probe())


def test_cleanup_closes_only_the_diagnostic_client():
    async def probe():
        transport = diagnostics.TabularDiagnosticAsyncClient(budget_seconds=5)
        sdk_client = AsyncAzureOpenAI(
            api_key='test-key', azure_endpoint='https://models.example.com',
            api_version='2024-10-21', http_client=transport,
        )
        await diagnostics.close_tabular_model_http_client(SimpleNamespace(client=sdk_client))
        assert transport.is_closed
        with patch.object(sdk_client, 'close') as close:
            await diagnostics.close_tabular_model_http_client(None)
        close.assert_not_called()

    asyncio.run(probe())


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
