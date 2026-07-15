# test_phase9_orchestration_live_smoke.py
"""
Controlled live-smoke gate for Phase 9 chat orchestration.
Version: 0.250.068
Implemented in: 0.250.068

This test executes an explicit five-scenario manifest only when a deployed URL,
authenticated state, and manifest path are configured. Results retain bounded
aggregate status and timing data without prompts, evidence text, or object IDs.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

import pytest


REQUIRED_SCENARIO_NAMES = frozenset({
    'generated_file_metadata',
    'grounded_image_with_selected_agent',
    'selected_image_qa',
    'selected_image_reference_generation',
    'web_and_selected_image',
})
ALLOWED_RESPONSE_TYPES = frozenset({'json', 'sse'})
MAX_SCENARIO_TIMEOUT_MS = 600000
BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
MANIFEST_PATH = os.getenv('SIMPLECHAT_PHASE9_LIVE_MANIFEST', '').strip()
STORAGE_STATE = (
    os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '').strip()
    or os.getenv('SIMPLECHAT_UI_ADMIN_STORAGE_STATE', '').strip()
)
ACCESS_TOKEN = os.getenv('SIMPLECHAT_UI_ACCESS_TOKEN', '').strip()
RESULT_PATH = Path(os.getenv(
    'SIMPLECHAT_PHASE9_LIVE_RESULT_PATH',
    Path(__file__).resolve().parents[1] / 'artifacts' / 'phase9_orchestration_live_smoke.json',
))


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('version') != 1:
        raise ValueError('Phase 9 live-smoke manifest version must be 1.')
    scenarios = manifest.get('scenarios')
    if not isinstance(scenarios, list):
        raise ValueError('Phase 9 live-smoke manifest scenarios must be a list.')
    names = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError('Each live-smoke scenario must be an object.')
        name = str(scenario.get('name') or '').strip()
        endpoint = str(scenario.get('endpoint') or '').strip()
        request_body = scenario.get('request')
        expectations = scenario.get('expect')
        response_type = str((expectations or {}).get('response_type') or 'sse').strip()
        if name not in REQUIRED_SCENARIO_NAMES or name in names:
            raise ValueError(f'Unexpected or duplicate live-smoke scenario: {name or "missing"}.')
        if not endpoint.startswith('/') or '://' in endpoint:
            raise ValueError(f'Live-smoke endpoint must be a same-origin path: {name}.')
        if not isinstance(request_body, dict):
            raise ValueError(f'Live-smoke request must be an object: {name}.')
        if not isinstance(expectations, dict):
            raise ValueError(f'Live-smoke expectations must be an object: {name}.')
        if response_type not in ALLOWED_RESPONSE_TYPES:
            raise ValueError(f'Unsupported live-smoke response type: {name}.')
        names.append(name)
    missing = REQUIRED_SCENARIO_NAMES.difference(names)
    if missing:
        raise ValueError(
            'Live-smoke manifest is missing scenarios: ' + ', '.join(sorted(missing))
        )
    return scenarios


def _path_value(payload, dotted_path):
    current = payload
    for segment in str(dotted_path or '').split('.'):
        if not segment or not isinstance(current, dict) or segment not in current:
            raise KeyError(dotted_path)
        current = current[segment]
    return current


def _parse_sse_payloads(response_text):
    payloads = []
    for line in str(response_text or '').splitlines():
        if not line.startswith('data:'):
            continue
        serialized = line[5:].strip()
        if not serialized:
            continue
        try:
            payload = json.loads(serialized)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    if not payloads:
        raise AssertionError('Live-smoke SSE response contained no JSON data events.')
    return payloads


def _terminal_payload(payloads):
    return next(
        (
            payload
            for payload in reversed(payloads)
            if payload.get('done') is True or payload.get('error')
        ),
        payloads[-1],
    )


def _citation_count(payload):
    return sum(
        len(payload.get(field_name) or [])
        for field_name in (
            'agent_citations',
            'hybrid_citations',
            'web_search_citations',
        )
    )


def _source_status_counts(payload):
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    ledger = metadata.get('evidence_ledger') if isinstance(metadata.get('evidence_ledger'), dict) else {}
    counts = {}
    for source in ledger.get('sources') or []:
        if not isinstance(source, dict):
            continue
        status = str(source.get('status') or 'unknown').strip().lower()
        counts[status] = counts.get(status, 0) + 1
    return counts


def _has_image_proposal(payload):
    content = str(payload.get('full_content') or payload.get('content') or '')
    return '```simpleimage' in content


def _assert_expectations(scenario, payload, status_code):
    expectations = scenario['expect']
    assert status_code == int(expectations.get('status_code', 200))
    for dotted_path in expectations.get('required_paths') or []:
        _path_value(payload, dotted_path)
    for dotted_path, expected_value in (expectations.get('equals') or {}).items():
        assert _path_value(payload, dotted_path) == expected_value
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    plan = metadata.get('orchestration') if isinstance(metadata.get('orchestration'), dict) else {}
    runtime = metadata.get('orchestration_runtime') if isinstance(metadata.get('orchestration_runtime'), dict) else {}
    if 'task_profile' in expectations:
        assert plan.get('task_profile') == expectations['task_profile']
    if 'finalizer' in expectations:
        assert plan.get('finalizer') == expectations['finalizer']
    if 'image_proposal' in expectations:
        assert _has_image_proposal(payload) is bool(expectations['image_proposal'])
    if 'minimum_citation_count' in expectations:
        assert _citation_count(payload) >= int(expectations['minimum_citation_count'])
    if expectations.get('allowed_run_statuses'):
        assert runtime.get('status') in expectations['allowed_run_statuses']
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden_value in expectations.get('forbidden_substrings') or []:
        assert str(forbidden_value) not in serialized


def _result_summary(scenario, payload, status_code, latency_ms, status):
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    plan = metadata.get('orchestration') if isinstance(metadata.get('orchestration'), dict) else {}
    runtime = metadata.get('orchestration_runtime') if isinstance(metadata.get('orchestration_runtime'), dict) else {}
    return {
        'name': scenario['name'],
        'status': status,
        'http_status': int(status_code),
        'latency_ms': min(max(0, int(latency_ms)), MAX_SCENARIO_TIMEOUT_MS),
        'task_profile': str(plan.get('task_profile') or 'unknown'),
        'run_status': str(runtime.get('status') or 'unknown'),
        'citation_count': _citation_count(payload),
        'source_status_counts': _source_status_counts(payload),
        'image_proposal_present': _has_image_proposal(payload),
    }


def _write_results(started_at, results):
    host = urlparse(BASE_URL).netloc
    document = {
        'version': 1,
        'started_at': started_at,
        'completed_at': _utc_now(),
        'environment_correlation': (
            hashlib.sha256(host.encode('utf-8')).hexdigest()[:16]
            if host
            else None
        ),
        'scenario_count': len(results),
        'passed_count': sum(result.get('status') == 'passed' for result in results),
        'failed_count': sum(result.get('status') == 'failed' for result in results),
        'scenarios': results,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(document, indent=2), encoding='utf-8')


def _require_live_configuration():
    required = os.getenv('SIMPLECHAT_PHASE9_LIVE_REQUIRED') == '1'
    missing = []
    if not BASE_URL:
        missing.append('SIMPLECHAT_UI_BASE_URL')
    if not MANIFEST_PATH:
        missing.append('SIMPLECHAT_PHASE9_LIVE_MANIFEST')
    if not ACCESS_TOKEN and (not STORAGE_STATE or not Path(STORAGE_STATE).exists()):
        missing.append('SIMPLECHAT_UI_ACCESS_TOKEN or valid storage state')
    if missing and required:
        pytest.fail('Live smoke configuration is incomplete: ' + ', '.join(missing))
    if missing:
        pytest.skip('Phase 9 live smoke is opt-in; missing: ' + ', '.join(missing))


def test_phase9_live_smoke_manifest_contract():
    private_request_value = 'private prompt and object identifiers'
    scenarios = _validate_manifest({
        'version': 1,
        'scenarios': [
            {
                'name': name,
                'endpoint': '/api/chat/stream',
                'request': {'message': private_request_value},
                'expect': {'response_type': 'sse'},
            }
            for name in sorted(REQUIRED_SCENARIO_NAMES)
        ],
    })
    summary = _result_summary(
        scenarios[0],
        {
            'done': True,
            'full_content': 'A bounded response.',
            'metadata': {
                'orchestration': {'task_profile': 'grounded_answer'},
                'orchestration_runtime': {'status': 'succeeded'},
                'evidence_ledger': {'sources': [{'status': 'succeeded'}]},
            },
        },
        200,
        1250,
        'passed',
    )

    assert len(scenarios) == len(REQUIRED_SCENARIO_NAMES)
    assert private_request_value not in json.dumps(summary)
    assert set(summary) == {
        'name',
        'status',
        'http_status',
        'latency_ms',
        'task_profile',
        'run_status',
        'citation_count',
        'source_status_counts',
        'image_proposal_present',
    }


@pytest.mark.ui
def test_phase9_controlled_live_smoke():
    _require_live_configuration()
    manifest = json.loads(Path(MANIFEST_PATH).read_text(encoding='utf-8'))
    scenarios = _validate_manifest(manifest)
    started_at = _utc_now()
    results = []
    failed_names = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        request_options = {
            'base_url': BASE_URL,
            'ignore_https_errors': True,
        }
        auth_headers = {}
        if ACCESS_TOKEN:
            auth_headers['Authorization'] = f'Bearer {ACCESS_TOKEN}'
            request_options['extra_http_headers'] = auth_headers
        else:
            request_options['storage_state'] = STORAGE_STATE
        api = playwright.request.new_context(**request_options)
        try:
            if ACCESS_TOKEN:
                session_response = api.post(
                    '/ci-auth/session',
                    headers=auth_headers,
                    timeout=30000,
                )
                assert session_response.ok

            for scenario in scenarios:
                started = perf_counter()
                payload = {}
                status_code = 0
                try:
                    timeout_ms = min(
                        max(1000, int(scenario.get('timeout_ms') or 180000)),
                        MAX_SCENARIO_TIMEOUT_MS,
                    )
                    response = api.post(
                        scenario['endpoint'],
                        data=scenario['request'],
                        timeout=timeout_ms,
                    )
                    status_code = response.status
                    response_type = scenario['expect'].get('response_type', 'sse')
                    payload = (
                        _terminal_payload(_parse_sse_payloads(response.text()))
                        if response_type == 'sse'
                        else response.json()
                    )
                    _assert_expectations(scenario, payload, status_code)
                    scenario_status = 'passed'
                except Exception:
                    scenario_status = 'failed'
                    failed_names.append(scenario['name'])
                latency_ms = round((perf_counter() - started) * 1000)
                results.append(_result_summary(
                    scenario,
                    payload,
                    status_code,
                    latency_ms,
                    scenario_status,
                ))

                conversation_id = str(
                    payload.get('conversation_id')
                    or scenario['request'].get('conversation_id')
                    or ''
                ).strip()
                if scenario.get('cleanup_conversation') and conversation_id:
                    try:
                        api.delete(f'/api/conversations/{conversation_id}', timeout=30000)
                    except Exception:
                        pass
        finally:
            api.dispose()
            _write_results(started_at, results)

    assert not failed_names, 'Failed Phase 9 live-smoke scenarios: ' + ', '.join(failed_names)