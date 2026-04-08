#!/usr/bin/env python3
# test_embedding_rate_limit_wait_time.py
"""
Functional test for embedding rate limit wait time handling.
Version: 0.239.116
Implemented in: 0.239.116

This test ensures that embedding retries respect server-provided wait times
from 429 responses before falling back to local exponential backoff.
"""

import email.utils
import importlib
import os
import sys
import time as real_time
import types


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeRateLimitError(Exception):
    def __init__(self, headers=None):
        super().__init__('Rate limit exceeded')
        self.response = types.SimpleNamespace(headers=headers or {})


class FakeEmbeddingResponse:
    def __init__(self, embeddings, prompt_tokens=12, total_tokens=12):
        self.data = [types.SimpleNamespace(embedding=embedding) for embedding in embeddings]
        self.usage = types.SimpleNamespace(
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
        )


class FakeEmbeddingsEndpoint:
    def __init__(self, scripted_results):
        self.scripted_results = list(scripted_results)

    def create(self, model, input):
        result = self.scripted_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeAzureOpenAI:
    scripted_results = []

    def __init__(self, *args, **kwargs):
        self.embeddings = FakeEmbeddingsEndpoint(type(self).scripted_results)


class SleepRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, delay):
        self.calls.append(delay)


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _load_functions_content(sleep_recorder):
    config_stub = types.ModuleType('config')
    config_stub.time = types.SimpleNamespace(time=real_time.time, sleep=sleep_recorder)
    config_stub.random = types.SimpleNamespace(uniform=lambda low, high: low)
    config_stub.AzureOpenAI = FakeAzureOpenAI
    config_stub.RateLimitError = FakeRateLimitError
    config_stub.DefaultAzureCredential = object
    config_stub.get_bearer_token_provider = lambda *args, **kwargs: 'token-provider'
    config_stub.cognitive_services_scope = 'https://cognitiveservices.azure.com/.default'

    settings_stub = types.ModuleType('functions_settings')
    settings_stub.get_settings = lambda: {
        'enable_embedding_apim': False,
        'azure_openai_embedding_authentication_type': 'api_key',
        'azure_openai_embedding_api_version': '2024-06-01',
        'azure_openai_embedding_endpoint': 'https://example.openai.azure.com',
        'azure_openai_embedding_key': 'test-key',
        'embedding_model': {
            'selected': [
                {'deploymentName': 'text-embedding-test'}
            ]
        }
    }

    logging_stub = types.ModuleType('functions_logging')
    debug_stub = types.ModuleType('functions_debug')
    debug_stub.debug_print = lambda *args, **kwargs: None

    original_modules = {}
    module_stubs = {
        'config': config_stub,
        'functions_settings': settings_stub,
        'functions_logging': logging_stub,
        'functions_debug': debug_stub,
    }

    for module_name, module_stub in module_stubs.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules['functions_content'] = sys.modules.get('functions_content')
    sys.modules.pop('functions_content', None)

    module = importlib.import_module('functions_content')
    return module, original_modules


def test_parse_retry_after_ms_and_date_headers():
    """Test that Retry-After helper parses millisecond and date-based headers."""
    print('🔍 Testing Retry-After header parsing...')
    sleep_recorder = SleepRecorder()
    module, original_modules = _load_functions_content(sleep_recorder)

    try:
        retry_after_ms = module._parse_retry_after_seconds({'retry-after-ms': '4500'})
        if retry_after_ms != 4.5:
            print(f'❌ Expected retry-after-ms to parse as 4.5, got {retry_after_ms}')
            return False

        retry_after_date = email.utils.formatdate(real_time.time() + 5, usegmt=True)
        parsed_date_wait = module._parse_retry_after_seconds({'retry-after': retry_after_date})
        if parsed_date_wait is None or not 0 < parsed_date_wait <= 5.5:
            print(f'❌ Expected retry-after date header to resolve to about 5 seconds, got {parsed_date_wait}')
            return False

        print('✅ Retry-After headers parse into usable wait times')
        return True
    finally:
        _restore_modules(original_modules)


def test_generate_embedding_uses_retry_after_wait_time():
    """Test single embedding retries use the server-provided wait time."""
    print('🔍 Testing single embedding Retry-After handling...')
    sleep_recorder = SleepRecorder()
    module, original_modules = _load_functions_content(sleep_recorder)

    try:
        FakeAzureOpenAI.scripted_results = [
            FakeRateLimitError({'retry-after-ms': '4500'}),
            FakeEmbeddingResponse([[0.1, 0.2, 0.3]])
        ]

        embedding, token_usage = module.generate_embedding('retry-after test text')

        if embedding != [0.1, 0.2, 0.3]:
            print(f'❌ Unexpected embedding result: {embedding}')
            return False

        if 4.5 not in sleep_recorder.calls:
            print(f'❌ Expected a 4.5 second retry wait, got sleep calls: {sleep_recorder.calls}')
            return False

        if not isinstance(token_usage, dict) or token_usage.get('model_deployment_name') != 'text-embedding-test':
            print(f'❌ Unexpected token usage payload: {token_usage}')
            return False

        print('✅ Single embedding retries honor Retry-After wait times')
        return True
    finally:
        _restore_modules(original_modules)


def test_generate_embeddings_batch_uses_retry_after_wait_time():
    """Test batch embedding retries use the server-provided wait time."""
    print('🔍 Testing batch embedding Retry-After handling...')
    sleep_recorder = SleepRecorder()
    module, original_modules = _load_functions_content(sleep_recorder)

    try:
        FakeAzureOpenAI.scripted_results = [
            FakeRateLimitError({'retry-after': '3'}),
            FakeEmbeddingResponse([[0.4, 0.5], [0.6, 0.7]], prompt_tokens=20, total_tokens=20)
        ]

        results = module.generate_embeddings_batch(['first', 'second'], batch_size=2)

        if len(results) != 2:
            print(f'❌ Expected 2 embedding results, got {len(results)}')
            return False

        if 3.0 not in sleep_recorder.calls:
            print(f'❌ Expected a 3.0 second retry wait, got sleep calls: {sleep_recorder.calls}')
            return False

        first_embedding, first_usage = results[0]
        if first_embedding != [0.4, 0.5]:
            print(f'❌ Unexpected first embedding: {first_embedding}')
            return False

        if not isinstance(first_usage, dict) or first_usage.get('prompt_tokens') != 10:
            print(f'❌ Unexpected batch token usage payload: {first_usage}')
            return False

        print('✅ Batch embedding retries honor Retry-After wait times')
        return True
    finally:
        _restore_modules(original_modules)


if __name__ == '__main__':
    tests = [
        test_parse_retry_after_ms_and_date_headers,
        test_generate_embedding_uses_retry_after_wait_time,
        test_generate_embeddings_batch_uses_retry_after_wait_time,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            results.append(test())
        except Exception as exc:
            print(f'❌ {test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(bool(result) for result in results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)