#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_plan_rules.py
"""
Functional test for the plan-level rules that decide whether a chat plan waits for a saved workflow run.
Version: 0.261.306
Implemented in: 0.261.306

This test ensures that ``compute_workflow_run_waits`` marks a plan's one workflow_run step as
waiting only when the server-side planning context says the wait is configured, the workflow's
catalog entry was found quick, every enabled capability is still available without the user's
sign-in, nothing in the plan needs the user's session, the plan starts exactly one workflow, and
only answer steps read the run, through a required input. It also ensures a stored marker is kept
only while it still fits the plan exactly, that model-written fields are never read, and that the
headless check uses the caller's own request context with roles, email and the native bridge
emptied, failing closed when the check itself fails.

Checks raise ``AssertionError`` explicitly, so they also run under ``python -O``.
"""

import os
import sys
from copy import deepcopy

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.abspath(os.path.join(_HERE, '..', 'application', 'single_app'))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_orchestration_registry as registry  # noqa: E402
from functions_orchestration_workflow_run_wait import (  # noqa: E402
    SESSION_NEEDING_CAPABILITIES,
    compute_workflow_run_waits,
    headless_capability_ids,
    headless_request_context,
    stored_workflow_run_waits,
    waited_run_consumers_valid,
)


HOSTILE_NAME = '<script>alert(1)</script> Sales digest'
MARKER = {'run_digest': {'version': 1, 'workflow': 'w1'}}
HEADLESS = ['compose', 'document_search', 'workflow_run']


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _planning(*, waitable=True, ready=True, headless=HEADLESS):
    planning = {
        'handles': {'workflows': {'w1': {'id': 'workflow-1'}, 'w2': {'id': 'workflow-2'}}},
        'catalog': {'workflows': [
            {'handle': 'w1', 'name': HOSTILE_NAME, 'durable': True, 'waitable': waitable},
            {'handle': 'w2', 'name': 'Other', 'durable': True},
        ]},
    }
    if ready is not None:
        planning['workflow_run_wait'] = {'ready': ready}
        if headless is not None:
            planning['workflow_run_wait']['headless_capability_ids'] = list(headless)
    return planning


def _run(step_id='run_digest', handle='w1', **fields):
    return {
        'step_id': step_id, 'capability_id': 'workflow_run', 'role': 'act', 'enabled': True,
        'arguments': {'workflow': handle}, 'inputs': {}, 'depends_on': [], **fields,
    }


def _compose(step_id='answer', producer='run_digest', output='run', optional=False, **fields):
    inputs = {'digest': {'binding': {'step_id': producer, 'output_name': output}}}
    if optional:
        inputs['digest']['optional'] = True
    return {
        'step_id': step_id, 'capability_id': 'compose', 'role': 'compose', 'enabled': True,
        'arguments': {'instruction': 'Compare the totals.'}, 'inputs': inputs, 'depends_on': [producer], **fields,
    }


def _search(step_id='q3', capability_id='document_search', **fields):
    return {
        'step_id': step_id, 'capability_id': capability_id, 'role': 'gather', 'enabled': True,
        'arguments': {'query': 'Q3 totals'}, 'inputs': {}, 'depends_on': [], **fields,
    }


def _plan():
    compose = _compose()
    compose['inputs']['report'] = {'binding': {'step_id': 'q3', 'output_name': 'sources'}}
    compose['depends_on'].append('q3')
    return [_run(), _search(), compose], {'step_id': 'answer', 'output_name': 'answer'}


def test_version_is_at_least_the_implementation():
    """The plan-level rules ship in 0.261.306."""
    assert_app_version_at_least('0.261.306')


def test_quick_plan_waits():
    """A run, a search and a compose that reads both: the run step waits."""
    steps, final = _plan()
    waits = compute_workflow_run_waits(steps, final, _planning())
    _require(waits == MARKER, f'Expected the run step to wait, got {waits!r}.')
    _require(stored_workflow_run_waits(waits, steps, final) == MARKER, 'A fitting stored marker should be kept.')


def test_server_context_decides():
    """Without the server's marker, its headless list or a quick catalog entry, nothing waits."""
    steps, final = _plan()
    for label, planning in (
        ('no planning context', None),
        ('the wait not configured', _planning(ready=None)),
        ('the marker not ready', _planning(ready='yes')),
        ('no headless list', _planning(headless=None)),
        ('a malformed headless list', {**_planning(), 'workflow_run_wait': {'ready': True,
                                                                             'headless_capability_ids': 'all'}}),
        ('a workflow that is not quick', _planning(waitable=False)),
        ('a waitable flag as text', _planning(waitable='true')),
    ):
        _require(compute_workflow_run_waits(steps, final, planning) == {}, f'{label}: nothing should wait.')
    other = [_run(handle='w2'), *steps[1:]]
    _require(compute_workflow_run_waits(other, final, _planning()) == {}, 'A non-quick workflow should not wait.')
    invented = [_run(handle='w9'), *steps[1:]]
    _require(compute_workflow_run_waits(invented, final, _planning()) == {}, 'An invented handle should not wait.')


def test_headless_rules():
    """A capability unavailable without sign-in, or one that needs the session, stops the wait."""
    steps, final = _plan()
    planning = _planning(headless=['compose', 'workflow_run'])
    _require(compute_workflow_run_waits(steps, final, planning) == {}, 'A non-headless capability should stop it.')
    for capability_id in sorted(SESSION_NEEDING_CAPABILITIES):
        extra = _search(step_id='extra', capability_id=capability_id)
        planning = _planning(headless=[*HEADLESS, capability_id])
        waits = compute_workflow_run_waits([*steps, extra], final, planning)
        _require(waits == {}, f'{capability_id} needs the session, so the plan should not wait.')
        _require(stored_workflow_run_waits(MARKER, [*steps, extra], final) == {}, f'{capability_id}: stored marker.')
        disabled = {**extra, 'enabled': False}
        waits = compute_workflow_run_waits([*steps, disabled], final, planning)
        _require(waits == MARKER, f'A disabled {capability_id} step never runs, so the plan should still wait.')
    second = _run(step_id='run_other', handle='w1')
    _require(compute_workflow_run_waits([*steps, second], final, _planning()) == {}, 'Two runs should not wait.')


def test_consumer_rules():
    """Only compose may read the run, through a required input; the answer can't select the run."""
    final = {'step_id': 'answer', 'output_name': 'answer'}
    cases = [
        ('the final response selects the run', [_run(), _compose()], {'step_id': 'run_digest', 'output_name': 'run'}),
        ('an optional input only', [_run(), _compose(optional=True)], final),
        ('another output name', [_run(), _compose(output='summary')], final),
        ('a dependency without a binding', [_run(), {**_compose(), 'inputs': {}}], final),
        ('a disabled reader', [_run(), _compose(enabled=False)], final),
        ('no reader at all', [_run(), _search()], final),
        ('a non-answer step reads the run', [_run(), _compose(), {
            **_search(step_id='leak', capability_id='render_file'),
            'inputs': {'source': {'binding': {'step_id': 'run_digest', 'output_name': 'run'}}},
        }], final),
        ('a non-answer step reads the answer', [_run(), _compose(), {
            **_search(step_id='leak', capability_id='render_file'),
            'inputs': {'source': {'binding': {'step_id': 'answer', 'output_name': 'answer'}}},
        }], final),
        ('a non-answer step depends on the run', [_run(), _compose(), {
            **_search(step_id='leak', capability_id='document_analyze'), 'depends_on': ['run_digest'],
        }], final),
        ('the run step is optional', [_run(optional=True), _compose()], final),
    ]
    for label, steps, final_response in cases:
        _require(compute_workflow_run_waits(steps, final_response, _planning()) == {}, f'{label}: should not wait.')
        _require(stored_workflow_run_waits(MARKER, steps, final_response) == {}, f'{label}: stored marker kept.')
    chained = [_run(), _compose(), _compose(step_id='polish', producer='answer', output='answer')]
    _require(compute_workflow_run_waits(chained, {'step_id': 'polish', 'output_name': 'answer'}, _planning())
             == MARKER, 'A compose that reads a compose that reads the run is still only the answer.')
    _require(waited_run_consumers_valid([_run(), _compose()], final, None) is False, 'No run step id is invalid.')


def test_model_fields_are_ignored():
    """A model cannot ask for a wait: extra fields on steps or the plan are never read."""
    steps, final = _plan()
    claimed = [{**step, 'wait': True, 'waitable': True, 'workflow_run_waits': MARKER} for step in steps]
    claimed[0]['arguments'] = {**claimed[0]['arguments'], 'wait': True}
    _require(compute_workflow_run_waits(claimed, final, _planning(waitable=False)) == {}, 'A model asked for a wait.')
    before = deepcopy(steps)
    compute_workflow_run_waits(steps, final, _planning())
    stored_workflow_run_waits(MARKER, steps, final)
    _require(steps == before, 'The rules changed the plan.')


def test_stored_marker_must_fit_exactly():
    """A stored marker with another shape, version, handle or step is dropped."""
    steps, final = _plan()
    for label, marker in (
        ('no marker', None),
        ('an empty marker', {}),
        ('another step', {'q3': {'version': 1, 'workflow': 'w1'}}),
        ('another version', {'run_digest': {'version': 2, 'workflow': 'w1'}}),
        ('another handle', {'run_digest': {'version': 1, 'workflow': 'w2'}}),
        ('an extra key', {'run_digest': {'version': 1, 'workflow': 'w1', 'deadline': 'never'}}),
        ('two entries', {**MARKER, 'q3': {'version': 1, 'workflow': 'w1'}}),
        ('a list', [MARKER]),
    ):
        _require(stored_workflow_run_waits(marker, steps, final) == {}, f'{label}: the marker should be dropped.')


def test_headless_context_and_capability_check():
    """The headless check empties only roles, email and the bridge, and fails closed."""
    caller = {'user_id': 'owner', 'user_roles': ['WorkflowUser'], 'user_email': 'owner@example.com',
              'native_bridge_for_step': object(), 'agent_catalog': [{'name': 'a'}], 'workflow_planning': {'x': 1}}
    before = dict(caller)
    headless = headless_request_context(caller)
    _require(caller == before, 'The caller context was changed.')
    _require(headless['user_roles'] == [] and headless['user_email'] is None, 'Roles and email should be empty.')
    _require(headless['native_bridge_for_step'] is None, 'A resumed plan has no native bridge.')
    _require(all(headless[key] is caller[key] for key in ('user_id', 'agent_catalog', 'workflow_planning')),
             'Everything else should be the caller context.')
    _require(headless_request_context(None) == {'user_roles': [], 'user_email': None, 'native_bridge_for_step': None},
             'A missing context should still be headless.')

    calls = []
    original = registry.resolve_available_capability_ids

    def fake(settings, allowed_ids=None, request_context=None, candidate_ids=None, **kwargs):
        calls.append({'allowed': allowed_ids, 'context': request_context, 'candidates': set(candidate_ids)})
        return ['compose', 'workflow_run', 'web_search']

    def broken(*_args, **_kwargs):
        raise RuntimeError('catalog unavailable')

    try:
        registry.resolve_available_capability_ids = fake
        settings = {'chat_orchestration_enabled_capabilities': ['compose', 'workflow_run']}
        ids = headless_capability_ids(settings, caller, {'compose', 'workflow_run', 'document_search'})
        _require(ids == frozenset({'compose', 'workflow_run'}), f'Only available candidates come back: {ids!r}.')
        _require(calls[0]['allowed'] == ['compose', 'workflow_run'], 'The admin allowlist should be applied.')
        _require(calls[0]['context']['user_roles'] == [] and calls[0]['context']['user_email'] is None,
                 'The check must run without roles or email.')
        _require(calls[0]['candidates'] == {'compose', 'workflow_run', 'document_search'}, 'Wrong candidates.')
        _require(headless_capability_ids(settings, caller, ()) == frozenset(), 'No candidates means none.')
        registry.resolve_available_capability_ids = broken
        _require(headless_capability_ids(settings, caller, {'compose'}) == frozenset(), 'A failure must fail closed.')
    finally:
        registry.resolve_available_capability_ids = original


if __name__ == '__main__':
    tests = [
        test_version_is_at_least_the_implementation,
        test_quick_plan_waits,
        test_server_context_decides,
        test_headless_rules,
        test_consumer_rules,
        test_model_fields_are_ignored,
        test_stored_marker_must_fit_exactly,
        test_headless_context_and_capability_check,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f'PASS {test.__name__}')
        except Exception as exc:  # noqa: BLE001 - report every failing test, then exit non-zero
            failed += 1
            print(f'FAIL {test.__name__}: {exc}')
    print(f'{len(tests) - failed}/{len(tests)} tests passed')
    sys.exit(1 if failed else 0)
