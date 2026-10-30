# functions_tabular_model_diagnostics.py
"""Opt-in, metadata-only HTTP diagnostics for foreground tabular model calls."""

import asyncio
import hashlib
import logging
import math
import os
import re
import time
import uuid

from openai import DefaultAsyncHttpxClient

from functions_appinsights import log_event


DIAGNOSTICS_ENV = 'SIMPLECHAT_TABULAR_HTTP_DIAGNOSTICS'
TIMEOUT_ENV = 'SIMPLECHAT_TABULAR_HTTP_TIMEOUT_SECONDS'
RETRIES_ENV = 'SIMPLECHAT_TABULAR_HTTP_MAX_RETRIES'
BUDGET_ENV = 'SIMPLECHAT_TABULAR_HTTP_BUDGET_SECONDS'


def _diagnostic_number(name, default, minimum, maximum, integer=False):
    try:
        raw_value = os.environ.get(name, str(default))
        value = int(raw_value) if integer else float(raw_value)
        if math.isfinite(value) and minimum <= value <= maximum:
            return value
    except (ValueError, TypeError, OverflowError):
        pass
    return default


def _safe_provider_request_id(response):
    for name in ('x-request-id', 'apim-request-id', 'x-ms-request-id'):
        value = response.headers.get(name, '')
        if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            return value
    return ''


class TabularDiagnosticAsyncClient(DefaultAsyncHttpxClient):
    """Observe SDK HTTP attempts without inspecting request or response bodies."""

    def __init__(self, *, budget_seconds, **kwargs):
        super().__init__(**kwargs)
        self.diagnostic_run_id = uuid.uuid4().hex
        self.budget_seconds = budget_seconds
        self._first_attempt_at = None
        self._attempt_sequence = 0

    def _emit(self, operation, properties, level=logging.INFO):
        try:
            log_event(
                f'[TABULAR_MODEL_HTTP] {operation}',
                extra={
                    'diagnostic_run_id': self.diagnostic_run_id,
                    'operation': operation,
                    'service': 'tabular-analysis',
                    **properties,
                },
                level=level,
            )
        except Exception:
            pass

    async def send(self, request, **kwargs):
        started_at = time.monotonic()
        if self._first_attempt_at is None:
            self._first_attempt_at = started_at
        self._attempt_sequence += 1
        try:
            retry_count = max(0, int(request.headers.get('x-stainless-retry-count', '0')))
        except (ValueError, TypeError):
            retry_count = 0
        endpoint_identity = f'{request.url.host}:{request.url.port}{request.url.path}'
        properties = {
            'http_attempt_id': uuid.uuid4().hex,
            'attempt_sequence': self._attempt_sequence,
            'retry_count': retry_count,
            'endpoint_fingerprint': hashlib.sha256(endpoint_identity.encode('utf-8')).hexdigest()[:16],
            'budget_seconds': self.budget_seconds,
        }
        self._emit('attempt_started', properties)
        try:
            remaining = self.budget_seconds - (started_at - self._first_attempt_at)
            if remaining <= 0:
                raise TimeoutError('Tabular diagnostic HTTP budget exhausted')
            async with asyncio.timeout(remaining):
                response = await super().send(request, **kwargs)
        except (Exception, asyncio.CancelledError) as exc:
            cause = exc
            seen = set()
            while cause.__cause__ is not None and id(cause) not in seen:
                seen.add(id(cause))
                cause = cause.__cause__
            self._emit('attempt_failed', {
                **properties,
                'duration_ms': round((time.monotonic() - started_at) * 1000, 3),
                'error_type': type(exc).__name__,
                'reason': type(cause).__name__,
                'budget_exhausted': time.monotonic() - self._first_attempt_at >= self.budget_seconds,
            }, level=logging.WARNING)
            raise
        self._emit('attempt_completed', {
            **properties,
            'duration_ms': round((time.monotonic() - started_at) * 1000, 3),
            'status_code': response.status_code,
            'success': response.is_success,
            'provider_request_id': _safe_provider_request_id(response),
        })
        return response


def build_tabular_model_http_options(service_id):
    """Return SDK options only for explicitly enabled tabular-analysis clients."""
    enabled = os.environ.get(DIAGNOSTICS_ENV, '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if service_id != 'tabular-analysis' or not enabled:
        return {}
    timeout = _diagnostic_number(TIMEOUT_ENV, 60, 1, 600)
    retries = _diagnostic_number(RETRIES_ENV, 0, 0, 2, integer=True)
    budget = _diagnostic_number(BUDGET_ENV, 180, 1, 1800)
    return {
        'http_client': TabularDiagnosticAsyncClient(budget_seconds=budget, timeout=timeout),
        'timeout': timeout,
        'max_retries': retries,
    }


async def close_tabular_model_http_client(service):
    """Close only the explicitly owned diagnostic SDK client after a tabular run."""
    sdk_client = getattr(service, 'client', None)
    http_client = getattr(sdk_client, '_client', None)
    if isinstance(http_client, TabularDiagnosticAsyncClient):
        try:
            await sdk_client.close()
        except Exception as exc:
            http_client._emit('cleanup_failed', {'error_type': type(exc).__name__}, level=logging.WARNING)
