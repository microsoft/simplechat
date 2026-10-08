#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_delivery.py
"""
Functional test for how a waiting chat plan and the workflow chat post-back share one run's result.
Version: 0.261.306
Implemented in: 0.261.306

This test ensures that a plan waiting on a saved workflow run holds the run's chat post-back only
while no post of that outcome has begun, that the plan uses the result at most once and only
through an ETag compare-and-set on the run's delivery record, that letting go hands the result back
to the post-back so it's posted exactly once, and that a finish racing the wait's timeout ends in
exactly one of the two, in either order. It also checks the wait's bound: the admin cap or the
plan's remaining budget, whichever ends first, with room left for the steps that use the result.

The post-back worker and the delivery contract are real. Storage, the runtime store, the result
reader and the models are the in-memory fakes in ``test_support/workflow_chat_delivery_fakes.py``.

Checks raise ``AssertionError`` explicitly, so they also run under ``python -O``.
"""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.abspath(os.path.join(_HERE, '..', 'application', 'single_app'))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_orchestration_workflow_runs as runs  # noqa: E402
import functions_workflow_chat_delivery_status as delivery_status  # noqa: E402
import functions_workflow_chat_delivery_worker as worker  # noqa: E402
from functions_orchestration_workflow_run_wait import (  # noqa: E402
    WAIT_HOLD_GRACE_SECONDS,
    WAIT_MIN_SECONDS,
    WAIT_RESERVE_SECONDS,
    waited_run_dependents,
    workflow_run_hold_until,
    workflow_run_wait_deadline,
)
from functions_workflow_chat_delivery import (  # noqa: E402
    KIND_FAILED,
    KIND_RESULT,
    NOTICE_NONE,
    PLAN_WAIT_CONSUMED,
    PLAN_WAIT_ENDED,
    PLAN_WAIT_HELD,
    PLAN_WAIT_HOLDING,
    PLAN_WAIT_KEY,
    PLAN_WAIT_POSTED,
    PLAN_WAIT_RELEASED,
    REASON_USED_IN_ANSWER,
    apply_plan_wait_consume,
    apply_plan_wait_hold,
    apply_plan_wait_release,
    control_summary,
    parse_delivery_timestamp,
    plan_wait_hold_until,
    workflow_delivery_message_id,
)
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    ORCHESTRATION_RUN_ID,
    OTHER_USER,
    RUN_ID,
    STEP_ID,
    USER,
    WORKFLOW_ID,
    FakeRuntimeConflict,
    FakeRuntimeUnavailable,
    cosmos_error,
    iso,
    make_record,
    make_run,
    make_world,
    parse_iso,
)


T0 = datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc)
M6 = workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 6)
M8 = workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 8)
OTHER_STEP = 'step-2'


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _summary(state='completed', version=6, deleted=False):
    return control_summary({'state': state, 'version': version, 'deleted': deleted, 'schema_version': 2})


def _held(record=None, *, until=None, now=T0, step_id=STEP_ID):
    """A record this plan step holds until ``until`` (seven minutes from ``now`` by default)."""
    updated, decision = apply_plan_wait_hold(
        make_record() if record is None else record,
        orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=step_id,
        until=until or now + timedelta(minutes=7), now=now,
    )
    _require(decision == PLAN_WAIT_HELD and updated is not None, f'the hold must be written, got {decision}')
    return updated


def _now(world):
    return parse_iso(world.clock())


def _running_world():
    return make_world(run=make_run(status='running'), state='running')


def _finish(world, state='completed', version=6):
    """What the runtime does when the run ends: the control and the run document's status agree."""
    world.runtime.update(state=state, version=version)
    run = world.run()
    run['status'] = state
    world.runs.put(run)


def _deliver(world):
    return worker.process_workflow_chat_delivery(USER, RUN_ID, services=world.services)


def _plan_hold(world, minutes=7):
    until = _now(world) + timedelta(minutes=minutes)
    decision = runs.hold_chat_delivery(
        USER, RUN_ID, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, until=until, now=_now(world),
    )
    return decision, until


def _plan_consume(world, *, step_id=STEP_ID):
    summary = runs.read_run_control_summary(USER, WORKFLOW_ID, RUN_ID)
    return runs.consume_chat_delivery(
        USER, RUN_ID, summary, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=step_id, now=_now(world),
    )


def _plan_release(world):
    return runs.release_chat_delivery(
        USER, RUN_ID, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=_now(world),
    )


def _posts(world):
    return [message['id'] for message in world.delivery_messages()]


def _hold_state(world):
    return (world.record().get(PLAN_WAIT_KEY) or {}).get('state')


class _Interleaved:
    """The plan's view of the runs container, letting another writer in between its read and its write."""

    def __init__(self, container, before_first_write):
        self._container = container
        self._before_first_write = before_first_write
        self.replace_calls = 0

    def read_item(self, *args, **kwargs):
        return self._container.read_item(*args, **kwargs)

    def replace_item(self, *args, **kwargs):
        self.replace_calls += 1
        hook, self._before_first_write = self._before_first_write, None
        if hook is not None:
            hook()
        return self._container.replace_item(*args, **kwargs)


@contextmanager
def _plan_side(world, container=None):
    """Point the plan's run storage and runtime reads at the fake world; collect worker signals."""
    signals = []
    saved = {
        name: getattr(runs, name)
        for name in ('_runs_container', '_runtime_store', '_runtime_errors', 'signal_workflow_chat_delivery')
    }
    runs._runs_container = lambda: world.runs if container is None else container
    runs._runtime_store = world.runtime.factory
    runs._runtime_errors = lambda: (FakeRuntimeUnavailable, FakeRuntimeConflict)
    runs.signal_workflow_chat_delivery = lambda user_id, run_id: signals.append((user_id, run_id))
    try:
        yield signals
    finally:
        for name, value in saved.items():
            setattr(runs, name, value)


# ---------------------------------------------------------------------------------------------
# A. The wait's bound
# ---------------------------------------------------------------------------------------------


def test_version_is_at_least_the_implementation():
    assert_app_version_at_least('0.261.306')


def test_the_bound_is_the_cap_or_the_plan_budget_whichever_ends_first():
    roomy = workflow_run_wait_deadline(
        now=T0, execution_deadline_at=T0 + timedelta(hours=1), cap_seconds=300,
        step_timeout_seconds=180, dependents=1,
    )
    _require(roomy == T0 + timedelta(seconds=300), f'a plan with time to spare waits the admin cap, got {roomy}')

    tight = workflow_run_wait_deadline(
        now=T0, execution_deadline_at=iso(T0 + timedelta(seconds=600)).replace('+00:00', 'Z'), cap_seconds=1800,
        step_timeout_seconds=180, dependents=1,
    )
    expected = T0 + timedelta(seconds=600 - WAIT_RESERVE_SECONDS - 180)
    _require(tight == expected, f'the plan budget ends the wait early enough to write the answer, got {tight}')

    two_readers = workflow_run_wait_deadline(
        now=T0, execution_deadline_at=T0 + timedelta(seconds=900), cap_seconds=1800,
        step_timeout_seconds=180, dependents=2,
    )
    _require(
        two_readers == T0 + timedelta(seconds=900 - WAIT_RESERVE_SECONDS - 360),
        f'each step that uses the result keeps a step timeout of the budget, got {two_readers}',
    )

    for dependents in (0, -3, None, True, '2'):
        counted = workflow_run_wait_deadline(
            now=T0, execution_deadline_at=T0 + timedelta(seconds=600), cap_seconds=1800,
            step_timeout_seconds=180, dependents=dependents,
        )
        _require(counted == expected, f'an unreadable reader count keeps one step timeout, got {counted} for {dependents!r}')


def test_no_wait_when_too_little_time_is_left_or_a_bound_is_unreadable():
    edge = T0 + timedelta(seconds=WAIT_MIN_SECONDS + WAIT_RESERVE_SECONDS + 180)
    exact = workflow_run_wait_deadline(
        now=T0, execution_deadline_at=edge, cap_seconds=300, step_timeout_seconds=180, dependents=1,
    )
    _require(exact == T0 + timedelta(seconds=WAIT_MIN_SECONDS), f'the minimum wait itself is allowed, got {exact}')
    short = workflow_run_wait_deadline(
        now=T0, execution_deadline_at=edge - timedelta(seconds=1), cap_seconds=300,
        step_timeout_seconds=180, dependents=1,
    )
    _require(short is None, 'a plan with less than the minimum wait left does not wait')

    naive = datetime(2026, 5, 4, 15, 0)
    unreadable = [
        {'now': naive},
        {'now': 'not a time'},
        {'execution_deadline_at': None},
        {'execution_deadline_at': naive + timedelta(hours=1)},
        {'execution_deadline_at': 'soon'},
        {'cap_seconds': 0},
        {'cap_seconds': True},
        {'cap_seconds': 300.0},
        {'step_timeout_seconds': -1},
        {'step_timeout_seconds': '180'},
        {'step_timeout_seconds': True},
    ]
    for change in unreadable:
        arguments = {
            'now': T0, 'execution_deadline_at': T0 + timedelta(hours=1), 'cap_seconds': 300,
            'step_timeout_seconds': 180, 'dependents': 1,
        }
        arguments.update(change)
        _require(workflow_run_wait_deadline(**arguments) is None, f'an unreadable bound never waits: {change!r}')


def test_dependents_count_direct_and_indirect_readers_once():
    steps = [
        {'step_id': 'run', 'capability_id': 'workflow_run'},
        {'step_id': 'compare', 'depends_on': ['run']},
        {'step_id': 'summarize', 'inputs': {'text': {'binding': {'step_id': 'compare', 'output_name': 'answer'}}}},
        {'step_id': 'both', 'depends_on': ['run', 'compare']},
        {'step_id': 'unrelated', 'depends_on': []},
        {'step_id': 'off', 'enabled': False, 'depends_on': ['run']},
        'not a step',
    ]
    count = waited_run_dependents(steps, 'run')
    _require(count == 3, f'compare, summarize and both use the result; got {count}')
    _require(waited_run_dependents([], 'run') == 0, 'a plan with no readers counts none')


def test_the_hold_outlasts_the_wait_by_its_grace():
    deadline = T0 + timedelta(minutes=5)
    _require(
        workflow_run_hold_until(deadline) == deadline + timedelta(seconds=WAIT_HOLD_GRACE_SECONDS),
        'the post-back stays held a little past the wait, so a plan resuming late can still use the result',
    )
    _require(workflow_run_hold_until(None) is None, 'no deadline holds nothing')
    _require(workflow_run_hold_until(datetime(2026, 5, 4)) is None, 'a naive deadline holds nothing')


# ---------------------------------------------------------------------------------------------
# B. The record's plan-wait transitions
# ---------------------------------------------------------------------------------------------


def test_a_hold_is_written_only_on_an_unposted_record():
    record = make_record()
    until = T0 + timedelta(minutes=7)
    updated, decision = apply_plan_wait_hold(
        record, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, until=until, now=T0,
    )
    _require(decision == PLAN_WAIT_HELD, f'a pending record is held, got {decision}')
    hold = updated[PLAN_WAIT_KEY]
    _require(
        hold['state'] == PLAN_WAIT_HOLDING and hold['orchestration_run_id'] == ORCHESTRATION_RUN_ID
        and hold['step_id'] == STEP_ID and parse_delivery_timestamp(hold['until']) == until
        and hold['version'] == 1,
        f'the hold names its plan step and when it lapses: {hold}',
    )
    _require(updated['status'] == record['status'], 'holding never changes the delivery status')
    _require(PLAN_WAIT_KEY not in record, 'the applier never changes the record it was given')

    claimed = _held(make_record(status='ready', phase='claimed', generation=6, kind=KIND_RESULT))
    _require(claimed[PLAN_WAIT_KEY]['state'] == PLAN_WAIT_HOLDING, 'a claim that never began publishing can be held')

    owned_elsewhere = [
        ({'status': 'delivering', 'phase': 'claimed', 'lease_id': 'lease-1'}, PLAN_WAIT_POSTED),
        ({'status': 'ready', 'phase': 'publishing', 'generation': 6}, PLAN_WAIT_POSTED),
        ({'status': 'ready', 'phase': 'message_created', 'generation': 6}, PLAN_WAIT_POSTED),
        ({'status': 'delivered', 'generation': 6, 'message_id': M6}, PLAN_WAIT_POSTED),
        ({'status': 'undeliverable'}, PLAN_WAIT_ENDED),
        ({'status': 'expired'}, PLAN_WAIT_ENDED),
        ({'status': 'mystery'}, PLAN_WAIT_ENDED),
        ({'version': 99}, PLAN_WAIT_ENDED),
    ]
    for changes, expected in owned_elsewhere:
        updated, decision = apply_plan_wait_hold(
            make_record(**changes), orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, until=until, now=T0,
        )
        _require(updated is None and decision == expected, f'{changes!r} must not be held; got {decision}')
    _require(
        apply_plan_wait_hold(None, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, until=until, now=T0)
        == (None, PLAN_WAIT_ENDED),
        'a run without a delivery record has nothing to hold',
    )


def test_a_hold_belongs_to_one_live_plan_step():
    held = _held()
    again = apply_plan_wait_hold(
        held, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, until=T0 + timedelta(minutes=9), now=T0,
    )
    _require(again == (None, PLAN_WAIT_HELD), f'holding again is a no-op that keeps the first bound, got {again}')
    other = apply_plan_wait_hold(
        held, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=OTHER_STEP, until=T0 + timedelta(minutes=7), now=T0,
    )
    _require(other == (None, PLAN_WAIT_POSTED), f"another step never takes over a hold, got {other}")
    for orchestration_run_id, step_id, until in (
        ('', STEP_ID, T0 + timedelta(minutes=7)),
        (ORCHESTRATION_RUN_ID, None, T0 + timedelta(minutes=7)),
        (ORCHESTRATION_RUN_ID, STEP_ID, T0),
        (ORCHESTRATION_RUN_ID, STEP_ID, 'not a time'),
    ):
        result = apply_plan_wait_hold(
            make_record(), orchestration_run_id=orchestration_run_id, step_id=step_id, until=until, now=T0,
        )
        _require(result == (None, PLAN_WAIT_POSTED), f'an unusable hold is never written: {result}')

    lapsed = apply_plan_wait_hold(
        held, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID,
        until=T0 + timedelta(minutes=30), now=T0 + timedelta(minutes=8),
    )
    _require(lapsed == (None, PLAN_WAIT_POSTED), f'a lapsed hold is never renewed, got {lapsed}')


def test_hold_until_covers_only_a_live_hold_on_an_unposted_record():
    until = T0 + timedelta(minutes=7)
    held = _held(until=until)
    _require(plan_wait_hold_until(held, T0) == until, 'a live hold keeps the post until it lapses')
    _require(plan_wait_hold_until(held, until) is None, 'a hold ends at its own bound')
    _require(plan_wait_hold_until({**held, 'status': 'delivering'}, T0) is None, 'a post in progress is never held')
    _require(
        plan_wait_hold_until({**held, 'status': 'ready', 'phase': 'publishing'}, T0) is None,
        'a post that began publishing is never held',
    )
    released = {**held, PLAN_WAIT_KEY: {**held[PLAN_WAIT_KEY], 'state': PLAN_WAIT_RELEASED}}
    _require(plan_wait_hold_until(released, T0) is None, 'a released hold holds nothing')
    _require(plan_wait_hold_until(make_record(), T0) is None, 'a record nobody held holds nothing')


def test_consume_uses_only_a_finished_generation_under_this_steps_live_hold():
    held = _held()
    still_running = apply_plan_wait_consume(
        held, _summary('running', 5), orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0,
    )
    _require(still_running == (None, PLAN_WAIT_HELD), f'a running run keeps the hold, got {still_running}')

    updated, decision = apply_plan_wait_consume(
        held, _summary('completed', 6), orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID,
        now=T0 + timedelta(minutes=1),
    )
    _require(decision == PLAN_WAIT_CONSUMED, f'a finished run under a live hold is used, got {decision}')
    _require(
        updated['status'] == 'delivered' and updated['notice_kind'] == NOTICE_NONE
        and updated['outcome_reason'] == REASON_USED_IN_ANSWER and updated['message_id'] is None
        and updated['generation'] == 6 and updated['kind'] == KIND_RESULT
        and updated['lease_id'] is None and updated['next_attempt_at'] is None,
        f'a used result closes its generation without a message or a notice: {updated}',
    )
    _require(updated[PLAN_WAIT_KEY]['state'] == PLAN_WAIT_CONSUMED, 'the hold records that the plan used the result')
    again = apply_plan_wait_consume(
        updated, _summary('completed', 6), orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0,
    )
    _require(again == (None, PLAN_WAIT_CONSUMED), f'using the result again changes nothing, got {again}')

    failed, decision = apply_plan_wait_consume(
        held, _summary('failed', 6), orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0,
    )
    _require(
        decision == PLAN_WAIT_CONSUMED and failed['kind'] == KIND_FAILED,
        'a failed run is reported by the plan, so the failure note is not posted as well',
    )

    others = [
        (held, _summary(), OTHER_STEP, T0, PLAN_WAIT_POSTED, 'another step'),
        (make_record(), _summary(), STEP_ID, T0, PLAN_WAIT_POSTED, 'a record nobody held'),
        (held, _summary(), STEP_ID, T0 + timedelta(minutes=7), PLAN_WAIT_POSTED, 'a lapsed hold'),
        ({**held, 'status': 'ready', 'phase': 'message_created', 'generation': 6, 'kind': KIND_RESULT},
         _summary(), STEP_ID, T0, PLAN_WAIT_POSTED, 'a generation whose message exists'),
        ({**held, 'status': 'undeliverable'}, _summary(), STEP_ID, T0, PLAN_WAIT_ENDED, 'a closed record'),
        ({**held, 'version': 99}, _summary(), STEP_ID, T0, PLAN_WAIT_ENDED, 'an unknown record'),
        (held, None, STEP_ID, T0, PLAN_WAIT_HELD, 'an unread runtime'),
    ]
    for record, summary, step_id, moment, expected, label in others:
        result = apply_plan_wait_consume(
            record, summary, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=step_id, now=moment,
        )
        _require(result == (None, expected), f'{label}: the plan must not use the result; got {result}')


def test_release_hands_back_only_an_unposted_outcome():
    until = T0 + timedelta(minutes=7)
    held = _held(until=until)
    waiting_on_hold = {**held, 'status': 'ready', 'generation': 6, 'kind': KIND_RESULT, 'next_attempt_at': iso(until)}
    updated, decision = apply_plan_wait_release(
        waiting_on_hold, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0,
    )
    _require(decision == PLAN_WAIT_RELEASED, f'a held record is released, got {decision}')
    _require(updated['next_attempt_at'] is None, "the hold's own wait is cleared so the post goes out now")
    _require(updated[PLAN_WAIT_KEY]['state'] == PLAN_WAIT_RELEASED, 'the hold records the release')
    _require(updated['status'] == 'ready', 'releasing never changes the delivery status')

    retry_at = iso(T0 + timedelta(minutes=2))
    kept, decision = apply_plan_wait_release(
        {**waiting_on_hold, 'next_attempt_at': retry_at},
        orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0,
    )
    _require(decision == PLAN_WAIT_RELEASED and kept['next_attempt_at'] == retry_at, "the worker's own retry is kept")

    again = apply_plan_wait_release(updated, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0)
    _require(again == (None, PLAN_WAIT_RELEASED), f'releasing again changes nothing, got {again}')
    consumed, _ = apply_plan_wait_consume(
        held, _summary(), orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0,
    )
    after_use = apply_plan_wait_release(consumed, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID, now=T0)
    _require(after_use == (None, PLAN_WAIT_CONSUMED), f'a used result is never handed back, got {after_use}')

    for record, step_id, expected, label in (
        (held, OTHER_STEP, PLAN_WAIT_POSTED, 'another step'),
        ({**held, 'status': 'delivering'}, STEP_ID, PLAN_WAIT_POSTED, 'a post in progress'),
        ({**held, 'status': 'expired'}, STEP_ID, PLAN_WAIT_ENDED, 'an expired record'),
        ({**held, 'version': 99}, STEP_ID, PLAN_WAIT_ENDED, 'an unknown record'),
    ):
        result = apply_plan_wait_release(record, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=step_id, now=T0)
        _require(result == (None, expected), f'{label}: nothing to release; got {result}')


# ---------------------------------------------------------------------------------------------
# C. The plan and the post-back worker on one run document
# ---------------------------------------------------------------------------------------------


def test_the_worker_waits_out_a_live_hold_then_posts_once():
    world = _running_world()
    with _plan_side(world):
        decision, until = _plan_hold(world)
    _require(decision == PLAN_WAIT_HELD, f'the plan holds the post-back, got {decision}')
    _finish(world)

    outcome = _deliver(world)
    _require(outcome == worker.OUTCOME_NOT_DUE, f'a held result is not posted yet, got {outcome}')
    record = world.record()
    _require(
        record['status'] == 'ready' and parse_delivery_timestamp(record['next_attempt_at']) == until,
        f'the worker waits until the hold lapses: {record}',
    )
    _require(_posts(world) == [], 'nothing is posted while the plan holds the result')

    world.clock.now = iso(until - timedelta(seconds=1))
    _require(_deliver(world) == worker.OUTCOME_NOT_DUE, 'the hold keeps the post until its bound')
    world.clock.now = iso(until + timedelta(seconds=1))
    _require(_deliver(world) == worker.OUTCOME_DELIVERED, 'a lapsed hold hands the result to the chat')
    _require(_deliver(world) == worker.OUTCOME_NOT_APPLICABLE, 'a delivered run is never posted again')
    _require(_posts(world) == [M6], f'the result is posted exactly once, got {_posts(world)}')

    with _plan_side(world):
        late = _plan_consume(world)
    _require(late == PLAN_WAIT_POSTED, f'a plan resuming after the post reports it, got {late}')
    _require(_posts(world) == [M6], 'a late plan never changes the posted result')


def test_a_used_result_is_never_posted_and_reads_as_used_in_the_answer():
    world = _running_world()
    with _plan_side(world):
        _plan_hold(world)
        _finish(world)
        _require(_deliver(world) == worker.OUTCOME_NOT_DUE, 'the worker leaves a held result alone')
        world.clock.advance(seconds=40)
        decision = _plan_consume(world)
    _require(decision == PLAN_WAIT_CONSUMED, f'the plan uses the finished result, got {decision}')
    record = world.record()
    _require(
        record['status'] == 'delivered' and record['outcome_reason'] == REASON_USED_IN_ANSWER
        and record['message_id'] is None and record['notice_kind'] == NOTICE_NONE,
        f'the delivery record closes as used in the answer: {record}',
    )

    _require(_deliver(world) == worker.OUTCOME_NOT_APPLICABLE, 'a used result is closed for the worker')
    world.clock.advance(hours=1)
    _require(_deliver(world) == worker.OUTCOME_NOT_APPLICABLE, 'it stays closed after the hold would have lapsed')
    _require(_posts(world) == [], 'a used result is never posted to the chat')
    _require(world.notifications.chat_calls == [], 'the bell never says a used result is in the chat')
    _require(world.notifications.notices() == [], 'the bell gets no undeliverable notice either')
    _require(world.unread_calls == [], 'the chat is not marked unread for a result already in the answer')

    row = delivery_status._delivery({
        'delivery_status': record['status'],
        'delivery_generation': record['generation'],
        'delivery_message_id': record['message_id'],
        'delivery_delivered_at': record['delivered_at'],
        'delivery_outcome_reason': record['outcome_reason'],
    })
    _require(
        row['status'] == 'delivered' and row['reason'] == REASON_USED_IN_ANSWER and row['message_id'] is None,
        f'the run card and tracker read the used result, never a chat message: {row}',
    )


def test_race_the_run_finishes_before_the_wait_times_out():
    world = _running_world()
    with _plan_side(world):
        _decision, until = _plan_hold(world, minutes=7)
        _finish(world)
        _require(_deliver(world) == worker.OUTCOME_NOT_DUE, 'the finish reaches the worker first and is held')
        # The plan's own deadline passed; it resumes inside the hold's grace and finds the run finished.
        world.clock.now = iso(until - timedelta(seconds=30))
        decision = _plan_consume(world)
        world.clock.now = iso(until + timedelta(minutes=5))
        outcome = _deliver(world)
    _require(decision == PLAN_WAIT_CONSUMED, f'the finished run is used in the answer, got {decision}')
    _require(outcome == worker.OUTCOME_NOT_APPLICABLE and _posts(world) == [], 'and so it is never posted')


def test_race_the_wait_times_out_before_the_run_finishes():
    world = _running_world()
    with _plan_side(world) as signals:
        _plan_hold(world)
        world.clock.advance(minutes=5)
        released = _plan_release(world)
        _require(released == PLAN_WAIT_RELEASED, f'the timed-out plan lets go, got {released}')
        _require(signals == [(USER, RUN_ID)], 'letting go wakes the post-back worker')
        _finish(world)
        world.clock.advance(seconds=5)
        _require(_deliver(world) == worker.OUTCOME_DELIVERED, 'the run finishing after the timeout is posted at once')
        late = _plan_consume(world)
    _require(late == PLAN_WAIT_POSTED, f'the plan never uses a result it let go of, got {late}')
    _require(_posts(world) == [M6], f'the result is posted exactly once, got {_posts(world)}')
    _require(_hold_state(world) == PLAN_WAIT_RELEASED, 'the record keeps the release')


def test_a_release_that_loses_its_write_to_the_worker_decides_again():
    world = _running_world()
    with _plan_side(world):
        _decision, until = _plan_hold(world)
    _finish(world)
    world.clock.advance(minutes=5)
    outcomes = []
    container = _Interleaved(world.runs, lambda: outcomes.append(_deliver(world)))
    with _plan_side(world, container) as signals:
        released = _plan_release(world)
    _require(outcomes == [worker.OUTCOME_NOT_DUE], f'the worker wrote between the read and the write: {outcomes}')
    _require(container.replace_calls == 2, 'the stale write was refused and retried on a fresh read')
    _require(released == PLAN_WAIT_RELEASED and signals == [(USER, RUN_ID)], f'the retry still lets go, got {released}')
    record = world.record()
    _require(record['next_attempt_at'] is None, "the worker's wait for the hold is cleared")
    _require(_deliver(world) == worker.OUTCOME_DELIVERED and _posts(world) == [M6], 'the result is posted once')
    _require(parse_delivery_timestamp(until) is not None, 'the hold had a bound')


def test_a_consume_that_loses_its_write_to_the_worker_decides_again():
    world = _running_world()
    with _plan_side(world):
        _plan_hold(world)
    _finish(world)
    world.clock.advance(minutes=1)
    outcomes = []
    container = _Interleaved(world.runs, lambda: outcomes.append(_deliver(world)))
    with _plan_side(world, container):
        decision = _plan_consume(world)
    _require(outcomes == [worker.OUTCOME_NOT_DUE], f'the worker saw the finish first and kept it held: {outcomes}')
    _require(container.replace_calls == 2, 'the stale write was refused and retried on a fresh read')
    _require(decision == PLAN_WAIT_CONSUMED, f'the plan still uses the result, got {decision}')
    world.clock.advance(hours=1)
    _require(_deliver(world) == worker.OUTCOME_NOT_APPLICABLE and _posts(world) == [], 'nothing is ever posted')


def test_a_release_after_the_hold_lapsed_loses_cleanly_to_the_post():
    world = _running_world()
    with _plan_side(world):
        _decision, until = _plan_hold(world)
    _finish(world)
    _require(_deliver(world) == worker.OUTCOME_NOT_DUE, 'the finish is held')
    world.clock.now = iso(until + timedelta(seconds=10))
    outcomes = []
    container = _Interleaved(world.runs, lambda: outcomes.append(_deliver(world)))
    with _plan_side(world, container) as signals:
        decision = _plan_release(world)
    _require(outcomes == [worker.OUTCOME_DELIVERED], f'the worker posted between the read and the write: {outcomes}')
    _require(decision == PLAN_WAIT_POSTED, f'the plan sees the post and reports it, got {decision}')
    _require(signals == [], 'a release that changed nothing wakes nobody')
    _require(_posts(world) == [M6], f'the result is posted exactly once, got {_posts(world)}')


def test_a_hold_after_the_worker_claimed_reports_posted_without_writing():
    for changes in (
        {'status': 'delivering', 'phase': 'claimed', 'lease_id': 'lease-1', 'generation': 5, 'kind': KIND_RESULT,
         'lease_expires_at': iso(T0 + timedelta(minutes=5))},
        {'status': 'ready', 'phase': 'message_created', 'generation': 5, 'kind': KIND_RESULT},
    ):
        world = make_world()
        world.set_record(**changes)
        writes = len(world.runs.writes())
        with _plan_side(world):
            decision, _until = _plan_hold(world)
        _require(decision == PLAN_WAIT_POSTED, f'{changes["status"]}: a post that began is never held; got {decision}')
        _require(len(world.runs.writes()) == writes, 'and the plan writes nothing')
        _require(PLAN_WAIT_KEY not in world.record(), 'the record carries no hold')


def test_a_new_outcome_after_a_used_one_is_posted_as_usual():
    world = _running_world()
    with _plan_side(world):
        _plan_hold(world)
        _finish(world)
        world.clock.advance(minutes=1)
        _require(_plan_consume(world) == PLAN_WAIT_CONSUMED, 'the plan used the first outcome')
    world.runtime.update(state='queued', version=7)
    _require(_deliver(world) == worker.OUTCOME_PENDING, 'a resumed run reopens the post-back')
    _finish(world, version=8)
    _require(_deliver(world) == worker.OUTCOME_DELIVERED, 'its new outcome is posted; the used one is not held')
    _require(_posts(world) == [M8], f'only the new outcome is posted, got {_posts(world)}')
    history = world.record()['history']
    _require(
        len(history) == 1 and history[0]['generation'] == 6
        and history[0]['outcome_reason'] == REASON_USED_IN_ANSWER and history[0]['message_id'] is None,
        f'the used generation stays on record: {history}',
    )


def test_storage_trouble_leaves_the_decision_to_a_later_pass():
    world = _running_world()
    with _plan_side(world):
        world.runs.fail('read_item', cosmos_error(503))
        _require(_plan_hold(world)[0] is None, 'an unreadable run decides nothing')
        world.runs.fail('replace_item', cosmos_error(503))
        _require(_plan_hold(world)[0] is None, 'an unwritable run decides nothing')
        world.runs.fail('replace_item', *[cosmos_error(412) for _ in range(runs._DELIVERY_WRITE_RETRIES + 1)])
        _require(_plan_hold(world)[0] is None, 'a run that keeps changing decides nothing')
        _require(PLAN_WAIT_KEY not in world.record(), 'none of those wrote a hold')
        world.runs.fail('replace_item', cosmos_error(404))
        _require(_plan_hold(world)[0] == PLAN_WAIT_ENDED, 'a run deleted under the write ends the wait')
        _require(_plan_hold(world)[0] == PLAN_WAIT_HELD, 'storage that recovers takes the hold')

        foreign = runs.hold_chat_delivery(
            OTHER_USER, RUN_ID, orchestration_run_id=ORCHESTRATION_RUN_ID, step_id=STEP_ID,
            until=_now(world) + timedelta(minutes=7), now=_now(world),
        )
        _require(foreign == PLAN_WAIT_ENDED, "another user's run is never held")
        world.runs.items.clear()
        _require(_plan_release(world) == PLAN_WAIT_ENDED, 'a deleted run ends the wait')


def test_the_runtime_control_is_read_like_the_post_back_reads_it():
    world = _running_world()
    with _plan_side(world):
        _finish(world)
        summary = runs.read_run_control_summary(USER, WORKFLOW_ID, RUN_ID)
        _require(summary['exists'] and summary['state'] == 'completed' and summary['version'] == 6, f'{summary}')
        world.runtime.fail(RUN_ID, FakeRuntimeUnavailable())
        _require(runs.read_run_control_summary(USER, WORKFLOW_ID, RUN_ID) is None, 'an outage decides nothing')
        world.runtime.fail(RUN_ID, FakeRuntimeConflict('busy'))
        _require(runs.read_run_control_summary(USER, WORKFLOW_ID, RUN_ID) is None, 'a conflict decides nothing')
        world.runtime.tombstone()
        tombstoned = runs.read_run_control_summary(USER, WORKFLOW_ID, RUN_ID)
        _require(tombstoned['exists'] and tombstoned['deleted'], 'a deleted workflow reads as deleted')
        world.runtime.remove()
        missing = runs.read_run_control_summary(USER, WORKFLOW_ID, RUN_ID)
        _require(missing['exists'] is False, 'a control that was never written reads as missing')


TESTS = [
    test_version_is_at_least_the_implementation,
    test_the_bound_is_the_cap_or_the_plan_budget_whichever_ends_first,
    test_no_wait_when_too_little_time_is_left_or_a_bound_is_unreadable,
    test_dependents_count_direct_and_indirect_readers_once,
    test_the_hold_outlasts_the_wait_by_its_grace,
    test_a_hold_is_written_only_on_an_unposted_record,
    test_a_hold_belongs_to_one_live_plan_step,
    test_hold_until_covers_only_a_live_hold_on_an_unposted_record,
    test_consume_uses_only_a_finished_generation_under_this_steps_live_hold,
    test_release_hands_back_only_an_unposted_outcome,
    test_the_worker_waits_out_a_live_hold_then_posts_once,
    test_a_used_result_is_never_posted_and_reads_as_used_in_the_answer,
    test_race_the_run_finishes_before_the_wait_times_out,
    test_race_the_wait_times_out_before_the_run_finishes,
    test_a_release_that_loses_its_write_to_the_worker_decides_again,
    test_a_consume_that_loses_its_write_to_the_worker_decides_again,
    test_a_release_after_the_hold_lapsed_loses_cleanly_to_the_post,
    test_a_hold_after_the_worker_claimed_reports_posted_without_writing,
    test_a_new_outcome_after_a_used_one_is_posted_as_usual,
    test_storage_trouble_leaves_the_decision_to_a_later_pass,
    test_the_runtime_control_is_read_like_the_post_back_reads_it,
]


if __name__ == '__main__':
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f'PASS {test.__name__}')
        except Exception as exc:  # noqa: BLE001 - report every failing test, then exit non-zero
            failed += 1
            print(f'FAIL {test.__name__}: {exc}')
    print(f'{len(TESTS) - failed}/{len(TESTS)} tests passed')
    sys.exit(1 if failed else 0)
