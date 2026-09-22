# test_orchestration_analysis_checkpoint_access.py
"""Functional regressions for saved Analyze access during checkpoint recovery.

Version: 0.261.127
Implemented in: 0.261.109

Exercise the real saved-result manifest authorizer and recovery logic. The
existing source/section fixtures replace only external I/O. Recovery must not
materialize full datasets or retain state mutations after a validation probe.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_analyze_backend_saved_integration import load_functions
from test_analyze_orchestration_saved_integration import orchestration, saved


def save_descriptor(fixture):
    return saved.save_orchestration_analysis(
        {'analysis_result': deepcopy(fixture.result), 'reply': fixture.result['reply']},
        user_id='owner', conversation_id='conversation-1',
        run_id='run-1', step_id='analyze-1', settings={},
    )


def recovery_functions(fixture):
    checkpoints = fixture.checkpoints
    namespace = {
        'deepcopy': deepcopy,
        **{key: getattr(checkpoints, key) for key in (
            'CheckpointError', 'STATE_FIELDS', 'OPTIONAL_STATE_FIELDS', 'DEPENDENCY_STATE_FIELDS',
            'context_binding', 'effective_plan', 'step_input_fingerprint', 'restore_context',
            'plan_contract_version',
        )},
    }
    load_functions('functions_orchestration_recovery.py', {
        '_validate_payload_sources', '_execution_steps', '_retained_statuses', 'validate_resume',
    }, namespace)
    return SimpleNamespace(**namespace)


def test_recovery_checks_large_analysis_access_without_reading_full_data(orchestration, monkeypatch):
    fixture = orchestration
    for record in fixture.result['authoritative_result']['value']:
        record['values']['detail'] = 'Original complete finding. ' * 7000
    descriptor = save_descriptor(fixture)
    assert sum(len(value) for value in fixture.store.contents.values()) > 8 * 1024 * 1024
    recovery = recovery_functions(fixture)
    load = fixture.store.load
    reads = []

    def only_manifest(user_id, conversation_id, run_id, step_id, reference):
        reads.append(reference)
        assert reference == descriptor['result_ref'], 'Authorization must not load record sections.'
        return load(user_id, conversation_id, run_id, step_id, reference)

    monkeypatch.setattr(fixture.store, 'load', only_manifest)
    recovery._validate_payload_sources(
        {'state': {'saved_analyses': [descriptor]}}, fixture.context, {}, 'owner',
    )
    assert reads == [descriptor['result_ref']]
    assert fixture.state['model_calls'] == []
    fixture.state['allowed'] = False
    with pytest.raises(recovery.CheckpointError) as failure:
        recovery._validate_payload_sources(
            {'state': {'saved_analyses': [descriptor]}}, fixture.context, {}, 'owner',
        )
    assert failure.value.code == 'context_unavailable'


@pytest.mark.parametrize('absent', [False, True])
@pytest.mark.parametrize('fail_after_restore', [False, True])
def test_resume_probes_restore_optional_reference_state_on_success_and_failure(
    orchestration, monkeypatch, absent, fail_after_restore,
):
    fixture = orchestration
    descriptor = save_descriptor(fixture)
    recovery = recovery_functions(fixture)
    checkpoints = fixture.checkpoints
    context = fixture.context
    if absent:
        delattr(context, 'saved_analyses')
    initial_state = checkpoints.context_state(context)
    step = {'step_id': 'analyze-1', 'capability_id': 'document_analyze', 'arguments': {}}
    plan = {'steps': [step]}
    if fail_after_restore:
        plan['steps'].append({'step_id': 'later-step', 'capability_id': 'document_search', 'arguments': {}})
    binding = checkpoints.context_binding(context, plan, {})
    record = {
        'id': 'run-1', 'user_id': 'owner', 'conversation_id': 'conversation-1',
        'turn_id': 'turn-1', 'plan': plan, 'execution_binding': binding,
        'execution_initial_manifest': deepcopy(context.execution_manifest),
        'execution_steps': [{'step_id': item['step_id'], 'status': 'completed'} for item in plan['steps']],
    }
    payload = {
        'binding': binding, 'input_fingerprint': checkpoints.step_input_fingerprint(step, context, binding),
        'state': {**deepcopy(initial_state), 'saved_analyses': [descriptor]},
    }
    fetched = []
    reconciliation_services = []
    checkpoint_services = []

    def reconcile(source, authorize, *, result_service=None):
        reconciliation_services.append(result_service)
        return source

    def completed(source, step_id, authorize, *, result_service=None):
        fetched.append(step_id)
        checkpoint_services.append(result_service)
        return deepcopy(payload) if step_id == 'analyze-1' else {'binding': 'changed'}

    namespace = recovery.validate_resume.__globals__
    monkeypatch.setitem(namespace, '_owned', lambda *args: deepcopy(record))
    monkeypatch.setitem(namespace, 'reconcile_checkpoints', reconcile)
    monkeypatch.setitem(namespace, '_completed_checkpoint', completed)
    for _ in range(2):
        if fail_after_restore:
            with pytest.raises(recovery.CheckpointError):
                recovery.validate_resume(record, context, {}, lambda: True)
        else:
            resumed = recovery.validate_resume(record, context, {}, lambda: True)
            assert set(resumed) == {'analyze-1'}
        assert checkpoints.context_state(context) == initial_state
        assert hasattr(context, 'saved_analyses') is not absent
        if not absent:
            assert context.saved_analyses == []
    assert fetched == (['analyze-1', 'later-step'] if fail_after_restore else ['analyze-1']) * 2
    assert reconciliation_services == [None, None]
    assert checkpoint_services == [None] * len(fetched)


@pytest.mark.parametrize('kind', ['chat', 'workflow'])
def test_message_backed_recovery_references_use_metadata_authorization_only(orchestration, monkeypatch, kind):
    recovery = recovery_functions(orchestration)
    descriptor = {
        'version': 'analyze-final-v1',
        'binding': {'kind': kind},
        'conversation_id': 'conversation-1', 'message_id': 'actual-assistant',
        'result_sha256': 'a' * 64,
    }
    calls = []

    def metadata_only(user_id, context):
        calls.append((user_id, context))
        return {}, lambda reference: pytest.fail('Recovery must not read data pages.'), {}

    monkeypatch.setattr(saved, 'load_saved_analysis', metadata_only)
    monkeypatch.setattr(
        saved, 'load_saved_analysis_input', lambda *args, **kwargs: pytest.fail('No whole-data input reader.'),
    )
    recovery._validate_payload_sources(
        {'state': {'saved_analyses': [descriptor]}}, orchestration.context, {}, 'owner',
    )
    assert calls == [('owner', {
        'conversation_id': 'conversation-1', 'message_id': 'actual-assistant',
        'result_sha256': 'a' * 64,
    })]
