#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_claims.py
"""
Functional test for the scheduler claiming a plan that waits on a saved workflow run.
Version: 0.261.309
Implemented in: 0.261.309

This test ensures that the orchestration scheduler claims a continuation for a required
workflow_run step waiting on its quick saved-workflow run, exactly as it claims a native tabular
compute wait, and only while no other worker's lease is live. A wait kind declared by a step whose
capability doesn't own it, a hand-off step, an optional step, and a run that was stopped, timed out,
or is mid-step are never claimed this way, and native tabular waits are claimed as before.
"""

import importlib
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.abspath(os.path.join(_HERE, '..', 'application', 'single_app'))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_orchestration_harness_routes import modules  # noqa: E402,F401


NOW = datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc)
NATIVE = 'native_tabular_compute'
SAVED_RUN = 'saved_workflow_run'
STEP_ID = 'run'


def _record(*, capability='workflow_run', optional=False, lease=None, **changes):
    record = {
        'id': 'run-1', 'run_id': 'run-1', 'user_id': 'owner', 'conversation_id': 'conversation-1',
        'status': 'waiting', 'recovery_version': 'version-1', 'execution_binding': 'binding-1',
        'execution_deadline_at': (NOW + timedelta(minutes=10)).isoformat(), 'execution_lease': lease,
        'plan': {'steps': [{
            'step_id': STEP_ID, 'capability_id': capability, 'role': 'gather', 'enabled': True,
            'optional': optional, 'depends_on': [],
        }]},
        'execution_steps': [{'step_id': STEP_ID, 'status': 'waiting'}],
    }
    record.update(changes)
    return record


def _lease(seconds):
    return {'token': 'lease-token', 'expires_at': (NOW + timedelta(seconds=seconds)).isoformat()}


class _Store:
    """The checkpoint store: one waiting manifest per waiting step, and no complete ones."""

    def __init__(self, kind, *, complete=False, waiting=True):
        self.kind = kind
        self.complete = complete
        self.waiting = waiting

    def has_manifest(self, step_id, waiting=False):
        return step_id == STEP_ID and (self.waiting if waiting else self.complete)

    def load(self, step_id, waiting=False):
        return {'result': {'wait': {'kind': self.kind}}}


class _Lease:
    def __init__(self, record, authorize, *, message_container=None):
        self.record = deepcopy(record)

    def read(self):
        return deepcopy(self.record)


class _Generic(Exception):
    """The generic, non-wait continuation path was taken."""


@pytest.fixture
def claims(modules, monkeypatch):
    continuation = importlib.import_module('functions_orchestration_continuation')
    state = {'record': _record(), 'store': _Store(SAVED_RUN), 'claimed': []}

    def claim_waiting(run_id, user_id, request, *, authorize, message_container):
        state['claimed'].append((run_id, user_id, deepcopy(request)))
        return {'acquired': True, 'record': deepcopy(state['record'])}

    def generic(*args, **kwargs):
        raise _Generic()

    monkeypatch.setattr(continuation, '_now', lambda: NOW)
    monkeypatch.setattr(continuation, '_read_owned', lambda *args, **kwargs: deepcopy(state['record']))
    monkeypatch.setattr(continuation, 'checkpoint_store', lambda record, authorize: state['store'])
    monkeypatch.setattr(continuation, 'claim_waiting_continuation', claim_waiting)
    monkeypatch.setattr(continuation, 'ExecutionLease', _Lease)
    monkeypatch.setattr(continuation, '_continuation_guards', generic)
    state['module'] = continuation
    return state


def _claimable(claims):
    return claims['module']._scheduled_wait_claimable(deepcopy(claims['record']), lambda: True)


def _claim(claims):
    return claims['module'].claim_run_continuation(
        'run-1', 'owner', 'conversation-1', authorize=lambda: True, message_container=object(),
    )


def test_version_is_at_least_the_implementation():
    assert_app_version_at_least('0.261.309')


def test_the_wait_kind_constant_is_the_shared_name():
    from functions_orchestration_workflow_run_wait import SAVED_WORKFLOW_RUN_WAIT_KIND

    assert SAVED_WORKFLOW_RUN_WAIT_KIND == SAVED_RUN


@pytest.mark.parametrize('kind, capability', [(SAVED_RUN, 'workflow_run'), (NATIVE, 'tabular_analyze')])
def test_a_required_waiting_step_is_claimed_for_its_own_wait_kind(claims, kind, capability):
    claims['record'] = _record(capability=capability)
    claims['store'] = _Store(kind)

    claimable = _claimable(claims)
    claimed = _claim(claims)

    assert claimable is True
    record, lease = claimed
    assert record['id'] == 'run-1' and isinstance(lease, _Lease)
    assert len(claims['claimed']) == 1
    run_id, user_id, request = claims['claimed'][0]
    assert (run_id, user_id) == ('run-1', 'owner')
    assert request['conversation_id'] == 'conversation-1' and request['expected_version'] == 'version-1'
    assert request['submission_id'].startswith('scheduler_')


@pytest.mark.parametrize('kind', [SAVED_RUN, NATIVE])
def test_a_live_lease_is_never_claimed(claims, kind):
    claims['record'] = _record(
        capability='workflow_run' if kind == SAVED_RUN else 'tabular_analyze', lease=_lease(30),
    )
    claims['store'] = _Store(kind)

    claimed = _claim(claims)

    assert claimed is None and claims['claimed'] == []


@pytest.mark.parametrize('kind', [SAVED_RUN, NATIVE])
def test_an_expired_lease_is_claimed(claims, kind):
    claims['record'] = _record(
        capability='workflow_run' if kind == SAVED_RUN else 'tabular_analyze', lease=_lease(-1),
    )
    claims['store'] = _Store(kind)

    claimed = _claim(claims)

    assert claimed is not None and len(claims['claimed']) == 1


@pytest.mark.parametrize('label, kind, record', [
    ('a saved-run wait on a native step', SAVED_RUN, _record(capability='tabular_analyze')),
    ('a native wait on a workflow_run step', NATIVE, _record(capability='workflow_run')),
    ('a saved-run wait on a hand-off step', SAVED_RUN, _record(capability='workflow_handoff')),
    ('a saved-run wait on a compose step', SAVED_RUN, _record(capability='compose')),
    ('an unknown wait kind', 'orchestration_result', _record()),
    ('no wait kind', None, _record()),
    ('an optional step', SAVED_RUN, _record(optional=True)),
    ('a stop was requested', SAVED_RUN, _record(cancellation_requested_at=NOW.isoformat())),
    ('no execution binding', SAVED_RUN, _record(execution_binding=None)),
    ('the plan deadline passed', SAVED_RUN, _record(execution_deadline_at=NOW.isoformat())),
    ('a step is mid-run', SAVED_RUN, _record(execution_steps=[
        {'step_id': STEP_ID, 'status': 'waiting'}, {'step_id': 'other', 'status': 'running'},
    ])),
    ('the step is not waiting', SAVED_RUN, _record(execution_steps=[{'step_id': STEP_ID, 'status': 'completed'}])),
])
def test_a_wait_the_scheduler_does_not_own_is_not_claimed_as_a_wait(claims, label, kind, record):
    claims['record'] = record
    claims['store'] = _Store(kind)

    claimable = _claimable(claims)

    assert claimable is False, label
    with pytest.raises(_Generic):
        _claim(claims)
    assert claims['claimed'] == [], label


@pytest.mark.parametrize('store', [_Store(SAVED_RUN, waiting=False), _Store(SAVED_RUN, complete=True)])
def test_a_step_without_an_open_waiting_checkpoint_is_not_claimed(claims, store):
    claims['store'] = store

    claimable = _claimable(claims)

    assert claimable is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
