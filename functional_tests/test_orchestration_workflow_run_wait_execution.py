#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_execution.py
"""
Functional test for a chat plan step that waits for the saved workflow run it started.
Version: 0.261.306
Implemented in: 0.261.306

This test ensures that a workflow_run step the server marked as waitable holds the run's chat
post-back while it waits, uses the run's result when the run finishes within the bound, and hands
the result back to the post-back when the bound passes first, so exactly one of the plan or the
post-back delivers a run's result, in either order. It also checks that every continuation checks
the wait again and ends it cleanly when the chat, the setting, or the workflow changed, and that a
step the server didn't mark, a hand-off, or a run that can't be waited for never waits.
"""

import importlib
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.abspath(os.path.join(_HERE, '..', 'application', 'single_app'))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_orchestration_workflow_runs as runs  # noqa: E402
import functions_workflow_chat_delivery as delivery  # noqa: E402
from functions_orchestration_result_contracts import ProducerIdentity, ResultContractError, TaskResult  # noqa: E402
from functions_orchestration_workflow_run_wait import (  # noqa: E402
    SAVED_WORKFLOW_RUN_WAIT_KIND,
    WAIT_HOLD_GRACE_SECONDS,
)
from functions_workflow_chat_delivery import (  # noqa: E402
    PLAN_WAIT_CONSUMED,
    PLAN_WAIT_HOLDING,
    PLAN_WAIT_KEY,
    PLAN_WAIT_RELEASED,
    REASON_USED_IN_ANSWER,
)
from test_orchestration_harness_routes import modules  # noqa: E402,F401
from test_orchestration_workflow_run_wait_delivery import (  # noqa: E402
    T0,
    _deliver,
    _finish,
    _hold_state,
    _Interleaved,
    _posts,
)
from test_orchestration_workflow_run_wait_eligibility import WAIT_SETTINGS, _quick, _task  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    ATTEMPT_ROOT_RUN_ID,
    CONVERSATION_ID,
    ORCHESTRATION_RUN_ID,
    OTHER_USER,
    RUN_ID,
    STEP_ID,
    USER,
    WORKFLOW_ID,
    WORKFLOW_NAME,
    FakeRuntimeConflict,
    FakeRuntimeUnavailable,
    iso,
    make_run,
    make_workflow,
    make_world,
    parse_iso,
)


WAIT = 'enable_chat_orchestration_workflow_run_wait'
HANDLE = 'wf-1'
FINGERPRINT = 'fingerprint-1'
CAP = timedelta(seconds=300)
DEADLINE = T0 + CAP
POINTER = {'workflow_id': WORKFLOW_ID, 'run_id': RUN_ID, 'result_sha256': 'a' * 64}
PRODUCER = ProducerIdentity(
    user_id=USER, conversation_id=CONVERSATION_ID, run_id=ORCHESTRATION_RUN_ID, attempt_index=1,
    step_id=STEP_ID, capability_id='workflow_run', contract_version='workflow-run-result-v1',
)
STEP = {
    'step_id': STEP_ID, 'capability_id': 'workflow_run', 'role': 'gather', 'enabled': True,
    'optional': False, 'depends_on': [], 'arguments': {'workflow': HANDLE},
}
ANSWER = {
    'step_id': 'answer', 'capability_id': 'compose', 'role': 'compose', 'enabled': True,
    'optional': False, 'depends_on': [STEP_ID], 'arguments': {},
}
PLANNING = {
    'conversation_private': True,
    'workflow_runs': {'ready': True},
    'catalog': {'workflows': [{'handle': HANDLE, 'name': WORKFLOW_NAME}]},
    'handles': {'workflows': {HANDLE: {'id': WORKFLOW_ID}}},
}
WAITING_SUMMARY = f'Waiting for "{WORKFLOW_NAME}" to finish (up to 5 min).'
CONSUMED_SUMMARY = 'The saved workflow finished; its result is ready for this plan.'
TIMEOUT_SUMMARY = 'Still running. Its result will be posted to this chat when it finishes.'
POSTED_SUMMARY = 'The saved workflow finished; its result is posted to this chat separately.'
ENDED_UNPOSTED_SUMMARY = 'The plan stopped waiting for the saved workflow. Open its run in Workflows to see the result.'


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _workflow(**changes):
    quick = {key: value for key, value in _quick().items() if key not in ('id', 'user_id', 'name', 'description')}
    return make_workflow(**{**quick, **changes})


def _datetime_at(clock):
    """A ``datetime`` whose ``now`` reads the fake world's clock, for the module under test."""

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = parse_iso(clock())
            return moment if tz is None else moment.astimezone(tz)

    return _Clock


class _Service:
    """The retained-result service the step writes through, recording each authorization and write."""

    def __init__(self):
        self.authorized = []
        self.persisted = []
        self.access = SimpleNamespace(authorize_producer=self._authorize)

    def _authorize(self, producer, for_write=False):
        self.authorized.append((producer.user_id, for_write))

    def persist_task_result(
        self, *, producer, role, status, outputs, sources, origin, guard_token, upstream, input_fingerprint,
    ):
        self.persisted.append({
            'user_id': producer.user_id, 'role': role, 'status': status, 'guard_token': guard_token,
            'input_fingerprint': input_fingerprint,
            'outputs': [(output.name, output.kind, deepcopy(output.value)) for output in outputs],
        })


class _Env:
    """One plan, one waited step, and the fake run world the plan and the post-back worker share."""

    def __init__(self, world):
        self.world = world
        self.settings = deepcopy(WAIT_SETTINGS)
        self.service = _Service()
        self.container = None
        self.run_id = RUN_ID
        self.start_outcome = {
            'status': 'queued', 'reason': None, 'name': WORKFLOW_NAME, 'workflow_id': WORKFLOW_ID,
            'run_id': RUN_ID, 'queued': True, 'chat_delivery': True,
        }
        self.read = {'outcome': 'read', 'context': deepcopy(POINTER), 'partial': False, 'truncated': False}
        self.reads = []
        self.logs = []
        self.signals = []
        self.saved = None
        self.context = SimpleNamespace(
            user_id=USER, run_id=ORCHESTRATION_RUN_ID, attempt_root_run_id=ATTEMPT_ROOT_RUN_ID,
            conversation_id=CONVERSATION_ID, plan_contract_version=2, user_roles=['User', 'WorkflowUser'],
            workflow_planning=deepcopy(PLANNING), workflow_run_waits={STEP_ID: {'version': 1, 'workflow': HANDLE}},
            durable_checkpoints=True, workflow_run_headless=True,
            execution_deadline_at=(T0 + timedelta(hours=1)).isoformat(),
            plan_steps=[deepcopy(STEP), deepcopy(ANSWER)], pending_results={}, task_results={},
            result_service=self.service, result_producer=lambda step: PRODUCER,
            result_guard_token_for_step=lambda step_id: 'guard-1',
            result_input_fingerprint_for_step=lambda step_id: FINGERPRINT,
        )

    # The pieces the module under test reaches for.

    def start(self, step, context, **_kwargs):
        return {**deepcopy(self.start_outcome), '_workflow': self.world.workflows.get(WORKFLOW_ID)}

    def reader_outcome(self, user_id, workflow_id, run, *, name, newer_in_progress):
        self.reads.append((user_id, workflow_id, (run or {}).get('id'), name, newer_in_progress))
        return deepcopy(self.read)

    def runs_container(self):
        return self.container if self.container is not None else self.world.runs

    # The plan's side.

    def begin(self, cancel=None):
        result = runs.adapter_workflow_run(
            deepcopy(STEP), self.context, settings=self.settings, user_id=USER, cancel_requested=cancel,
        )
        if result['status'] == 'waiting':
            # What the executor keeps for a waiting step, and hands back to the continuation.
            self.context.pending_results[STEP_ID] = deepcopy(result['wait'])
            self.context.task_results[STEP_ID] = TaskResult(PRODUCER, 'gather', 'pending', ())
            self.saved = deepcopy(result)
        return result

    def resume(self, *, step=None, saved=None, cancel=None, fingerprint=FINGERPRINT, user_id=USER):
        return runs.resume_workflow_run_wait(
            deepcopy(step or STEP), self.context, settings=self.settings, user_id=user_id,
            input_fingerprint=fingerprint, cancel_requested=cancel,
            saved_result=self.saved if saved is None else saved,
        )

    # The world's side.

    def advance(self, **delta):
        self.world.clock.advance(**delta)

    def at(self, moment):
        self.world.clock.advance(seconds=(moment - parse_iso(self.world.clock())).total_seconds())

    def finish(self, state='completed'):
        _finish(self.world, state=state)
        run = self.world.run()
        run.update({'started_at': iso(T0 + timedelta(seconds=5)), 'completed_at': self.world.clock()})
        self.world.runs.put(run)

    def change_workflow(self, **changes):
        workflow = self.world.workflows.get(WORKFLOW_ID)
        workflow.update(changes)
        self.world.workflows.put(workflow)

    def change_conversation(self, **changes):
        conversation = self.world.conversations.get(CONVERSATION_ID)
        conversation.update(changes)
        self.world.conversations.put(conversation)

    def hold_until(self):
        return parse_iso((self.world.record().get(PLAN_WAIT_KEY) or {}).get('until'))


@pytest.fixture
def env(modules, monkeypatch):
    world = make_world(run=make_run(status='running'), state='running')
    world.workflows.put(_workflow())
    test_env = _Env(world)
    checkpoints = importlib.import_module('functions_orchestration_checkpoints')
    results = importlib.import_module('functions_orchestration_workflow_results')
    monkeypatch.setattr(runs, '_read_conversation', lambda conversation_id: world.conversations.get(conversation_id))
    monkeypatch.setattr(runs, '_read_workflow', lambda user_id, workflow_id: world.workflows.get(workflow_id))
    monkeypatch.setattr(runs, '_read_workflow_run', lambda user_id, run_id: world.runs.get(run_id))
    monkeypatch.setattr(runs, '_runs_container', test_env.runs_container)
    monkeypatch.setattr(runs, '_runtime_store', world.runtime.factory)
    monkeypatch.setattr(runs, '_runtime_errors', lambda: (FakeRuntimeUnavailable, FakeRuntimeConflict))
    monkeypatch.setattr(
        runs, 'signal_workflow_chat_delivery', lambda user_id, run_id: test_env.signals.append((user_id, run_id)),
    )
    monkeypatch.setattr(runs, '_workflow_run_id', lambda *args, **kwargs: test_env.run_id)
    monkeypatch.setattr(runs, '_start', test_env.start)
    monkeypatch.setattr(runs, 'require_result_service', lambda context: context.result_service)
    monkeypatch.setattr(runs, 'validate_task_outputs', lambda *args, **kwargs: None)
    monkeypatch.setattr(runs, 'log_event', lambda message, **kwargs: test_env.logs.append((message, kwargs)))
    monkeypatch.setattr(runs, 'datetime', _datetime_at(world.clock))
    monkeypatch.setattr(delivery, 'utc_now', lambda: parse_iso(world.clock()))
    monkeypatch.setattr(checkpoints, 'step_input_fingerprint', lambda *args, **kwargs: FINGERPRINT)
    monkeypatch.setattr(results, '_reader_outcome', test_env.reader_outcome)
    return test_env


def _wait_of(result):
    return (result.get('workflow_run') or {}).get('wait')


def _retained_value(env_):
    _require(len(env_.service.persisted) == 1, f'one retained result, got {env_.service.persisted}')
    outputs = env_.service.persisted[0]['outputs']
    _require(len(outputs) == 1 and outputs[0][:2] == (runs.WORKFLOW_RUN_OUTPUT, runs.WORKFLOW_RUN_OUTPUT_KIND),
             f'the run output, got {outputs}')
    return outputs[0][2]


def _waiting(env_):
    result = env_.begin()
    _require(result['status'] == 'waiting', f'the step must wait, got {result}')
    return result


def test_version_is_at_least_the_implementation():
    assert_app_version_at_least('0.261.306')


# ---------------------------------------------------------------------------------------------
# Starting the run
# ---------------------------------------------------------------------------------------------


def test_a_marked_step_holds_the_post_back_and_waits(env):
    result = _waiting(env)

    wait = {
        'kind': SAVED_WORKFLOW_RUN_WAIT_KIND, 'run_id': RUN_ID, 'workflow_id': WORKFLOW_ID,
        'wait_deadline': DEADLINE.isoformat(),
    }
    assert result['wait'] == wait
    assert result['summary'] == WAITING_SUMMARY
    assert _wait_of(result) == {'kind': SAVED_WORKFLOW_RUN_WAIT_KIND, 'wait_deadline': DEADLINE.isoformat()}
    assert result['workflow_run']['run_id'] == RUN_ID and result['workflow_run']['status'] == 'queued'
    assert _hold_state(env.world) == PLAN_WAIT_HOLDING
    assert env.hold_until() == DEADLINE + timedelta(seconds=WAIT_HOLD_GRACE_SECONDS)
    assert env.service.persisted == [], 'nothing is retained until the wait ends'
    assert env.signals == []


def test_the_post_back_waits_out_a_live_hold(env):
    _waiting(env)
    env.advance(seconds=60)
    env.finish()

    _deliver(env.world)

    assert _posts(env.world) == [], 'the post-back must not post while the plan holds the run'
    assert _hold_state(env.world) == PLAN_WAIT_HOLDING


def test_the_bound_is_the_plan_budget_when_that_ends_first(env):
    # One step reads the run: 90 s reserve plus one 120 s step timeout come off the plan's budget.
    env.context.execution_deadline_at = (T0 + timedelta(seconds=360)).isoformat()

    result = _waiting(env)

    assert result['wait']['wait_deadline'] == (T0 + timedelta(seconds=150)).isoformat()
    assert result['summary'] == f'Waiting for "{WORKFLOW_NAME}" to finish (up to 3 min).'


def _not_waitable(env_, label):
    if label == 'the server did not mark it':
        env_.context.workflow_run_waits = {}
    elif label == 'the plan needs the user':
        env_.context.workflow_run_headless = False
    elif label == 'the plan is not durable':
        env_.context.durable_checkpoints = False
    elif label == 'the wait setting is off':
        env_.settings[WAIT] = False
    elif label == 'workflow results are off':
        env_.settings['enable_chat_workflow_results'] = False
    elif label == 'too many tasks':
        env_.change_workflow(tasks=[_task(index) for index in range(1, 7)])
    elif label == 'a one-time hand-off':
        env_.change_workflow(origin={'kind': 'handoff', 'one_time': True})
    elif label == 'a projected hand-off':
        env_.change_workflow(one_time=True)
    elif label == 'no durable execution':
        env_.change_workflow(durable_execution=False)
    elif label == 'too little plan time':
        env_.context.execution_deadline_at = (T0 + timedelta(seconds=240)).isoformat()
    else:
        raise AssertionError(label)


@pytest.mark.parametrize('label', [
    'the plan needs the user', 'the plan is not durable', 'the wait setting is off', 'workflow results are off',
    'too many tasks', 'a one-time hand-off', 'a projected hand-off', 'no durable execution', 'too little plan time',
])
def test_a_marked_step_that_cannot_wait_leaves_the_result_to_the_post_back(env, label):
    _not_waitable(env, label)

    result = env.begin()

    assert result['status'] == 'completed'
    assert result['summary'] == TIMEOUT_SUMMARY
    assert _hold_state(env.world) is None, 'no hold may be written'
    value = _retained_value(env)
    assert value['status'] == 'queued' and value['wait']['outcome'] == 'timeout'
    assert value['wait']['posts_to_chat'] is True and value['wait']['result_pointer'] is None
    assert _wait_of(result) == value['wait']
    env.advance(seconds=30)
    env.finish()
    _deliver(env.world)
    assert len(_posts(env.world)) == 1, 'the post-back posts the result once'


def test_an_unmarked_step_behaves_as_before(env):
    _not_waitable(env, 'the server did not mark it')

    result = env.begin()

    assert result['status'] == 'completed'
    assert result['summary'] == runs._STEP_SUMMARIES['queued']
    assert 'wait' not in _retained_value(env) and 'wait' not in result['workflow_run']
    assert _hold_state(env.world) is None


def test_a_run_started_without_the_post_back_never_waits(env):
    env.start_outcome['chat_delivery'] = False

    result = env.begin()

    assert result['status'] == 'completed'
    assert result['summary'] == 'Still running. Open its run in Workflows to see the result when it finishes.'
    value = _retained_value(env)
    assert value['wait']['outcome'] == 'timeout' and value['wait']['posts_to_chat'] is False
    assert _hold_state(env.world) is None


@pytest.mark.parametrize('status', ['unavailable', 'already_started'])
def test_a_run_this_step_did_not_start_never_waits(env, status):
    env.start_outcome.update({'status': status, 'queued': False})
    if status == 'unavailable':
        env.start_outcome.update({'reason': 'workflow_unavailable', 'run_id': None})

    result = env.begin()

    assert result['status'] == 'completed'
    assert 'wait' not in _retained_value(env)
    assert _hold_state(env.world) is None


# ---------------------------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------------------------


def test_a_waiting_step_keeps_waiting_while_the_run_runs(env):
    _waiting(env)
    env.advance(seconds=130)

    result = env.resume()

    assert result['status'] == 'waiting'
    assert result['wait'] == env.saved['wait']
    assert result['summary'] == f'Waiting for "{WORKFLOW_NAME}" to finish (up to 3 min).'
    assert _hold_state(env.world) == PLAN_WAIT_HOLDING
    assert env.service.persisted == []


def test_a_run_that_finishes_within_the_bound_is_used_once_and_never_posted(env):
    _waiting(env)
    env.advance(seconds=120)
    env.finish()

    result = env.resume()

    assert result['status'] == 'completed' and result['summary'] == CONSUMED_SUMMARY
    wait = _wait_of(result)
    assert wait['outcome'] == 'consumed' and wait['run_id'] == RUN_ID and wait['run_status'] == 'completed'
    assert wait['result_pointer'] == POINTER and wait['posts_to_chat'] is False
    assert wait['started_at'] == (T0 + timedelta(seconds=5)).isoformat()
    assert wait['completed_at'] == (T0 + timedelta(seconds=120)).isoformat()
    assert _retained_value(env)['wait'] == wait
    assert env.service.authorized[-1] == (USER, True), 'the write is authorized again'
    assert env.reads == [(USER, WORKFLOW_ID, RUN_ID, WORKFLOW_NAME, False)]
    assert _hold_state(env.world) == PLAN_WAIT_CONSUMED

    _deliver(env.world)
    _deliver(env.world)

    assert _posts(env.world) == [], 'a result the plan used is never posted as well'
    assert env.world.record().get('outcome_reason') == REASON_USED_IN_ANSWER


def test_the_timeout_ends_the_wait_and_the_post_back_posts_once(env):
    _waiting(env)
    env.at(DEADLINE)

    result = env.resume()

    assert result['status'] == 'completed' and result['summary'] == TIMEOUT_SUMMARY
    wait = _wait_of(result)
    assert wait['outcome'] == 'timeout' and wait['posts_to_chat'] is True and wait['result_pointer'] is None
    assert _retained_value(env)['wait'] == wait
    assert _hold_state(env.world) == PLAN_WAIT_RELEASED
    assert env.signals == [(USER, RUN_ID)], 'the release wakes the post-back worker'

    env.advance(seconds=200)
    env.finish()
    _deliver(env.world)
    _deliver(env.world)

    assert len(_posts(env.world)) == 1, 'the post-back posts the result exactly once'


@pytest.mark.parametrize('state, code', [
    ('failed', 'workflow_run_failed'), ('invalid', 'workflow_run_failed'), ('incomplete', 'workflow_run_failed'),
    ('cancelled', 'workflow_run_cancelled'), ('skipped', 'workflow_run_cancelled'),
])
def test_a_run_that_failed_or_was_cancelled_is_reported_by_the_plan_once(env, state, code):
    _waiting(env)
    env.advance(seconds=90)
    env.finish(state)

    result = env.resume()

    assert result['status'] == 'failed' and result['failure']['code'] == code
    assert env.reads == [], 'a failed run has no result to read'
    assert _hold_state(env.world) == PLAN_WAIT_CONSUMED
    _deliver(env.world)
    assert _posts(env.world) == [], 'the plan reported it, so the chat is not told again'


def test_a_user_stop_releases_the_run_to_the_post_back(env):
    _waiting(env)
    env.advance(seconds=30)

    result = env.resume(cancel=lambda: True)

    assert result['status'] == 'cancelled' and result['failure']['code'] == 'user_cancelled'
    assert _hold_state(env.world) == PLAN_WAIT_RELEASED
    env.finish()
    _deliver(env.world)
    assert len(_posts(env.world)) == 1


# ---------------------------------------------------------------------------------------------
# Finish versus timeout
# ---------------------------------------------------------------------------------------------


def test_race_the_run_finishes_just_before_the_deadline_the_plan_uses_it(env):
    _waiting(env)
    env.at(DEADLINE - timedelta(seconds=1))
    env.finish()
    # The scheduler's continuation lands after the deadline: a finished run is still used.
    env.at(DEADLINE + timedelta(seconds=40))

    result = env.resume()

    assert _wait_of(result)['outcome'] == 'consumed'
    _deliver(env.world)
    assert _posts(env.world) == []


def test_race_the_deadline_passes_just_before_the_run_finishes_the_chat_gets_it(env):
    _waiting(env)
    env.at(DEADLINE)

    result = env.resume()
    env.finish()
    _deliver(env.world)

    assert _wait_of(result)['outcome'] == 'timeout'
    assert len(_posts(env.world)) == 1


def test_race_the_run_finishes_between_the_plans_read_and_its_release(env):
    _waiting(env)
    env.at(DEADLINE)

    def finish_and_deliver():
        env.finish()
        _deliver(env.world)

    env.container = _Interleaved(env.world.runs, before_first_write=finish_and_deliver)
    result = env.resume()
    env.container = None
    _deliver(env.world)

    assert _wait_of(result)['outcome'] == 'timeout' and _wait_of(result)['posts_to_chat'] is True
    assert len(_posts(env.world)) == 1


@pytest.mark.parametrize('worker_first', [True, False])
def test_race_a_continuation_after_the_hold_lapsed_never_doubles_the_post(env, worker_first):
    _waiting(env)
    env.advance(seconds=100)
    env.finish()
    env.at(DEADLINE + timedelta(seconds=WAIT_HOLD_GRACE_SECONDS + 1))

    if worker_first:
        _deliver(env.world)
    result = env.resume()
    _deliver(env.world)
    _deliver(env.world)

    wait = _wait_of(result)
    assert wait['outcome'] in ('posted', 'timeout') and wait['posts_to_chat'] is True
    assert wait['result_pointer'] is None, 'the plan must not use a result the post-back owns'
    assert len(_posts(env.world)) == 1


# ---------------------------------------------------------------------------------------------
# Checking the wait again on every continuation
# ---------------------------------------------------------------------------------------------


def _reauthorization_failure(env_, label):
    if label == 'the chat became shared':
        env_.change_conversation(collaboration_conversation_id='collab-1')
    elif label == 'the chat was converted':
        env_.change_conversation(converted_to_collaboration_at=iso(T0))
    elif label == 'the chat was deleted':
        env_.world.conversations.items.pop(CONVERSATION_ID)
    elif label == 'the chat is being deleted':
        env_.change_conversation(orchestration_deleted=True)
    elif label == 'the chat changed owner':
        env_.change_conversation(user_id=OTHER_USER)
    elif label == 'the wait setting was turned off':
        env_.settings[WAIT] = False
    elif label == 'workflow runs were turned off':
        env_.settings['enable_chat_orchestration_workflow_runs'] = False
    elif label == 'personal workflows were turned off':
        env_.settings['allow_user_workflows'] = False
    elif label == 'the user lost the workflow role':
        env_.settings['require_member_of_workflow_user'] = True
        env_.context.user_roles = ['User']
    elif label == 'the workflow was deleted':
        env_.world.workflows.items.pop(WORKFLOW_ID)
    elif label == 'the workflow is being deleted':
        env_.change_workflow(deleting=True)
    elif label == 'the workflow moved to a group':
        env_.change_workflow(group_id='group-1')
    elif label == 'the workflow changed owner':
        env_.change_workflow(user_id=OTHER_USER)
    elif label == 'the workflow is no longer a quick run':
        env_.change_workflow(tasks=[_task(index) for index in range(1, 7)])
    elif label == 'the workflow became a hand-off':
        env_.change_workflow(one_time=True)
    else:
        raise AssertionError(label)


REAUTHORIZATION_FAILURES = [
    'the chat became shared', 'the chat was converted', 'the chat was deleted', 'the chat is being deleted',
    'the chat changed owner', 'the wait setting was turned off', 'workflow runs were turned off',
    'personal workflows were turned off', 'the user lost the workflow role', 'the workflow was deleted',
    'the workflow is being deleted', 'the workflow moved to a group', 'the workflow changed owner',
    'the workflow is no longer a quick run', 'the workflow became a hand-off',
]


@pytest.mark.parametrize('label', REAUTHORIZATION_FAILURES)
def test_a_wait_that_is_no_longer_allowed_ends_cleanly(env, label):
    _waiting(env)
    env.advance(seconds=60)
    env.finish()
    _reauthorization_failure(env, label)

    result = env.resume()

    assert result['status'] == 'completed' and result['summary'] == ENDED_UNPOSTED_SUMMARY
    wait = _wait_of(result)
    assert wait['outcome'] == 'ended' and wait['posts_to_chat'] is False and wait['result_pointer'] is None
    assert env.reads == [], 'nothing is read for a wait that is no longer allowed'
    assert _hold_state(env.world) == PLAN_WAIT_RELEASED, 'the run goes back to the post-back and its own rules'
    _deliver(env.world)
    _deliver(env.world)
    assert len(_posts(env.world)) <= 1


def test_a_changed_setting_or_plan_input_stops_the_continuation(env):
    _waiting(env)

    with pytest.raises(ResultContractError) as refused:
        env.resume(fingerprint='fingerprint-2')

    assert refused.value.code == 'result_input_changed'
    assert _hold_state(env.world) == PLAN_WAIT_HOLDING, 'the hold lapses on its own at its bound'


def _invalid(env_, label):
    step, saved = deepcopy(STEP), deepcopy(env_.saved)
    if label == 'a hand-off step':
        step['capability_id'] = 'workflow_handoff'
    elif label == 'another role':
        step['role'] = 'compose'
    elif label == 'a disabled step':
        step['enabled'] = False
    elif label == 'an old plan contract':
        env_.context.plan_contract_version = 1
    elif label == 'another user':
        return {'step': step, 'saved': saved, 'user_id': OTHER_USER}
    elif label == 'a native wait':
        env_.context.pending_results[STEP_ID]['kind'] = 'native_tabular_compute'
    elif label == 'an extra wait field':
        env_.context.pending_results[STEP_ID]['extra'] = 'x'
    elif label == 'an unreadable deadline':
        env_.context.pending_results[STEP_ID]['wait_deadline'] = 'soon'
        saved['wait']['wait_deadline'] = 'soon'
    elif label == 'a saved result that is not waiting':
        saved['status'] = 'completed'
    elif label == 'a saved wait that differs':
        saved['wait']['run_id'] = 'run-other'
    elif label == 'a run this step did not start':
        env_.run_id = 'run-other'
    elif label == 'no saved result':
        saved = []
    else:
        raise AssertionError(label)
    return {'step': step, 'saved': saved}


@pytest.mark.parametrize('label', [
    'a hand-off step', 'another role', 'a disabled step', 'an old plan contract', 'another user', 'a native wait',
    'an extra wait field', 'an unreadable deadline', 'a saved result that is not waiting',
    'a saved wait that differs', 'a run this step did not start', 'no saved result',
])
def test_a_continuation_that_does_not_match_the_wait_is_refused(env, label):
    _waiting(env)
    env.advance(seconds=30)
    env.finish()
    call = _invalid(env, label)

    with pytest.raises(ResultContractError) as refused:
        env.resume(**call)

    assert refused.value.code == 'result_wait_invalid'
    assert env.reads == [] and env.service.persisted == []
    assert _hold_state(env.world) == PLAN_WAIT_HOLDING


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
