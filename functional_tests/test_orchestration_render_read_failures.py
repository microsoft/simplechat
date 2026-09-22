# test_orchestration_render_read_failures.py
"""Saved Render reads preserve service uncertainty and independent file visibility.

Version: 0.261.127
Implemented in: 0.261.127
Real runtime, checkpoint, retained-result and rendering services are used.
Only provider I/O and the specific current read failure are isolated.
"""

from copy import deepcopy
import importlib

import pytest

from functions_orchestration_executor import _render_dependency_step
from test_orchestration_output_lifecycle import lifecycle, production_modules
from test_orchestration_render_waiting_runtime import render_runtime


def _read_failure(name):
    output_store = importlib.import_module('functions_orchestration_output_store')
    screening = importlib.import_module('content_screening.contracts')
    results = importlib.import_module('functions_orchestration_results')
    errors = {
        'storage': output_store.OutputStorageError(),
        'screening_service': screening.ScreeningError(),
        'authority_service': screening.SourceAuthorityUnavailableError(),
        'authority_configuration': screening.SourceAuthorityUnverifiedError(),
        'source_configuration': output_store.OutputError('output_source_configuration_invalid'),
        'reader_configuration': results.ResultUnavailableError('result_source_reader_required'),
        'external_reader_configuration': results.ResultUnavailableError('result_external_authorizer_required'),
        'raw_storage_permission': PermissionError('Isolated backing-store permission error.'),
    }
    if name == 'raw_storage_permission':
        return errors[name], output_store.OutputStorageError
    if name == 'wrapped_storage':
        error = results.ResultUnavailableError()
        error.__cause__ = TimeoutError('Isolated backing-store timeout.')
        return error, output_store.OutputStorageError
    if name == 'wrapped_screening':
        error = results.ResultUnavailableError()
        error.__cause__ = screening.SourceAuthorityUnverifiedError()
        return error, screening.SourceAuthorityUnverifiedError
    error = errors[name]
    return error, type(error)


def _restart_completed(case):
    record = case.current()
    return case.recovery._replace(record, {
        'status': 'running',
        'execution_lease': {
            **case.recovery.lease_fields(),
            'token': case.initial['execution_lease']['token'],
        },
    })


@pytest.mark.parametrize('saved_status', ['waiting', 'completed'])
@pytest.mark.parametrize('error_name', [
    'storage', 'screening_service', 'authority_service', 'authority_configuration',
    'source_configuration', 'reader_configuration', 'external_reader_configuration',
    'raw_storage_permission', 'wrapped_storage', 'wrapped_screening',
])
def test_saved_render_uncertainty_is_not_persisted_as_source_denial(
    render_runtime, monkeypatch, saved_status, error_name,
):
    case = render_runtime
    if saved_status == 'waiting':
        case.lifecycle.failures['md'] = [TimeoutError('Isolated first-render transport failure.')]
    first = case.execute(case.initial)
    assert first['status'] == saved_status, first
    output_id = first['outputs'][0]['output_id']
    original_output = deepcopy(case.lifecycle.raw(output_id))
    original_record = case.current()
    error, expected_type = _read_failure(error_name)
    claimed = case.claim(f'{error_name}-read') if saved_status == 'waiting' else _restart_completed(case)
    reads = []
    if error_name == 'raw_storage_permission':
        target, method = case.lifecycle.service.store, 'get'
    else:
        target, method = case.lifecycle.service, '_authorize_read_record'
    read = getattr(target, method)

    def fail_once(value):
        reads.append(value)
        if len(reads) == 1:
            raise error
        return read(value)

    with monkeypatch.context() as failing_read:
        failing_read.setattr(target, method, fail_once)
        with pytest.raises(expected_type):
            case.execute(claimed)

    current = case.current()
    current_output = case.lifecycle.raw(output_id)
    assert len(reads) == 1
    assert current['status'] == 'running'
    assert current.get('pending_results', {}) == original_record.get('pending_results', {})
    assert current.get('task_results', {}) == original_record.get('task_results', {})
    assert current_output == original_output
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1
    assert case.lifecycle.blobs.uploads == (1 if saved_status == 'completed' else 0)


@pytest.mark.parametrize('render_runtime', [2], indirect=True)
@pytest.mark.parametrize('denial', ['access', 'screening_hold'])
def test_saved_render_uses_public_sibling_visibility_without_rewriting_commits(
    render_runtime, monkeypatch, denial,
):
    case = render_runtime
    first = case.execute(case.initial)
    assert first['status'] == 'completed', first
    original_outputs = {
        output['output_id']: deepcopy(case.lifecycle.raw(output['output_id']))
        for output in first['outputs']
    }
    output_store = importlib.import_module('functions_orchestration_output_store')
    screening = importlib.import_module('content_screening.contracts')
    error = (
        screening.DocumentHeldError() if denial == 'screening_hold'
        else output_store.OutputUnavailableError()
    )
    authorize_read = case.lifecycle.service._authorize_read_record
    claimed = _restart_completed(case)

    def deny_second(record):
        if record['producer']['step_id'] == 'file-2':
            raise error
        return authorize_read(record)

    def forbidden_raw_projection(*args, **kwargs):
        raise AssertionError('Saved Render visibility must use list_public_outputs, not raw read.')

    with monkeypatch.context() as unavailable:
        unavailable.setattr(case.lifecycle.service, '_authorize_read_record', deny_second)
        unavailable.setattr(case.lifecycle.service, 'read', forbidden_raw_projection)
        result = case.execute(claimed)

    assert result['status'] == 'failed' and result['outcome'] == 'partial', result
    assert len(result['outputs']) == 2 and len(result['artifacts']) == 1
    available, denied = result['outputs']
    assert available['available'] is True and denied['available'] is False
    assert result['artifacts'][0]['output_id'] == available['output_id']
    assert denied['state'] == 'completed'
    assert denied['artifact_message_id'] is None and denied['can_retry'] is False
    assert all(denied[field] is None for field in (
        'next_retry_at', 'row_count', 'character_count', 'size_bytes',
    ))
    expected_code = 'output_screening_hold' if denial == 'screening_hold' else 'output_access_denied'
    assert denied['error_code'] == expected_code
    failed_step = result['steps'][2]
    assert failed_step['status'] == 'failed'
    assert failed_step['failure']['code'] == 'result_unavailable'
    assert failed_step['output_error'] == {'code': expected_code, 'retryable': False}
    assert failed_step['outputs'] == [denied]

    restored = _render_dependency_step(
        case.plan['steps'][2], case.state['context'], settings=case.settings, user_id='owner',
        saved_result=first['steps'][2],
    )
    assert restored['status'] == 'completed' and len(restored['artifacts']) == 1
    assert restored['outputs'][0]['available'] is True
    current_outputs = {
        output_id: case.lifecycle.raw(output_id) for output_id in original_outputs
    }
    assert current_outputs == original_outputs
    assert len(case.calls) == 1 and len(case.lifecycle.render_calls) == case.lifecycle.blobs.uploads == 2
