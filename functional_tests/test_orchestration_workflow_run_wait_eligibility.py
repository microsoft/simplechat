#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_eligibility.py
"""
Functional test for the quick-run rule that decides whether a chat plan may wait for a saved workflow run.
Version: 0.261.307
Implemented in: 0.261.307

This test ensures that ``quick_run_eligibility`` accepts a quick personal workflow and refuses,
with its own reason, a workflow that breaks any one rule: the wait setting and each setting it
needs, a group workflow, durable execution off, a workflow being deleted or paused on Microsoft
365, a one-time hand-off, a For each or Repeat until loop (checked before the structured rule), a
structured workflow, a task that needs approval, a Microsoft 365 run-as user, a review or indexing
publication policy, File Sync, and a task count outside one to five. It also ensures the rule is
pure and deterministic, ignores anything a model could add to the record, and that no reason text
names a workflow.

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

from functions_m365_workflow_binding import M365_ACTIVE_STATES  # noqa: E402
from functions_orchestration_workflow_run_wait import (  # noqa: E402
    QUICK_RUN_MAX_TASKS,
    QUICK_RUN_REASON_APPROVAL,
    QUICK_RUN_REASON_DELETING,
    QUICK_RUN_REASON_FILE_SYNC,
    QUICK_RUN_REASON_INVALID,
    QUICK_RUN_REASON_LOOP,
    QUICK_RUN_REASON_M365_ACTIVE,
    QUICK_RUN_REASON_NOT_DURABLE,
    QUICK_RUN_REASON_NOT_PERSONAL,
    QUICK_RUN_REASON_NO_TASKS,
    QUICK_RUN_REASON_ONE_TIME,
    QUICK_RUN_REASON_REVIEW,
    QUICK_RUN_REASON_RUN_AS,
    QUICK_RUN_REASON_STRUCTURED,
    QUICK_RUN_REASON_TEXT,
    QUICK_RUN_REASON_TOO_MANY_TASKS,
    QUICK_RUN_REASON_WAIT_DISABLED,
    SAVED_WORKFLOW_RUN_WAIT_KIND,
    quick_run_eligibility,
    quick_run_reason_text,
    wait_configured,
)


HOSTILE_NAME = '<img src=x onerror=alert(1)> Sales "digest" {{7*7}}'
WAIT_SETTINGS = {
    'enable_chat_orchestration': True,
    'enable_chat_orchestration_workflow_runs': True,
    'enable_chat_workflow_results': True,
    'enable_chat_orchestration_workflow_run_wait': True,
    'allow_user_workflows': True,
}


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _task(index, **fields):
    return {
        'id': f'task-{index}', 'type': 'instructions', 'name': f'Task {index}',
        'instructions': 'Summarize the week.', 'order': index, **fields,
    }


def _quick(**fields):
    workflow = {
        'id': 'workflow-1', 'user_id': 'owner', 'name': HOSTILE_NAME, 'description': HOSTILE_NAME,
        'trigger_type': 'manual', 'durable_execution': True, 'is_enabled': True,
        'tasks': [_task(1), _task(2)], 'file_sync': {'enabled': False, 'sources': []},
        'm365_run_as_user_id': '', 'origin': {'kind': 'manual'},
    }
    workflow.update(fields)
    return workflow


def _nested_flow(depth, leaf):
    node = leaf
    for _ in range(depth):
        node = {'kind': 'if', 'then': [node], 'else': []}
    return {'nodes': [node]}


ELIGIBLE = [
    ('two tasks', _quick()),
    ('one task', _quick(tasks=[_task(1)])),
    ('the most tasks', _quick(tasks=[_task(index) for index in range(1, QUICK_RUN_MAX_TASKS + 1)])),
    ('a paused workflow', _quick(is_enabled=False)),
    ('an interval trigger', _quick(trigger_type='interval', schedule={'interval': 'daily'})),
    ('approval not required', _quick(tasks=[_task(1, approval={'required': False})])),
    ('a publication without a review policy', _quick(tasks=[_task(1), _task(2, publication={'target': 'x'})])),
    ('a blank run-as user', _quick(m365_run_as_user_id='   ')),
    ('no run-as user field', {key: value for key, value in _quick().items() if key != 'm365_run_as_user_id'}),
    ('no File Sync config', _quick(file_sync=None)),
    ('an empty flow on a version 2 definition', _quick(definition_version=2, flow={})),
    ('a status outside Microsoft 365', _quick(status='completed')),
]

REFUSED = [
    # Rule 1: the user's own durable workflow, not being deleted, not paused on Microsoft 365.
    ('a group workflow', _quick(group_id='group-1'), QUICK_RUN_REASON_NOT_PERSONAL),
    ('durable execution off', _quick(durable_execution=False), QUICK_RUN_REASON_NOT_DURABLE),
    ('durable execution missing',
     {key: value for key, value in _quick().items() if key != 'durable_execution'}, QUICK_RUN_REASON_NOT_DURABLE),
    ('durable execution as text', _quick(durable_execution='true'), QUICK_RUN_REASON_NOT_DURABLE),
    ('being deleted', _quick(deleting=True), QUICK_RUN_REASON_DELETING),
    *[
        (f'paused on Microsoft 365 ({state})', _quick(status=state), QUICK_RUN_REASON_M365_ACTIVE)
        for state in sorted(M365_ACTIVE_STATES)
    ],
    # Rule 2: never a one-time hand-off, whether read from the record or the catalog projection.
    ('a one-time hand-off', _quick(origin={'kind': 'handoff', 'one_time': True}), QUICK_RUN_REASON_ONE_TIME),
    ('a projected one-time hand-off', _quick(one_time=True), QUICK_RUN_REASON_ONE_TIME),
    # Rule 3: no For each or Repeat until anywhere in the flow, checked before the structured rule.
    ('a For each loop', _quick(definition_version=3, flow={'nodes': [{'kind': 'for_each', 'body': []}]}),
     QUICK_RUN_REASON_LOOP),
    ('a nested Repeat until loop',
     _quick(definition_version=3, flow=_nested_flow(3, {'kind': 'repeat_until', 'body': []})), QUICK_RUN_REASON_LOOP),
    ('a flow too deep to check', _quick(definition_version=3, flow=_nested_flow(40, {'kind': 'task'})),
     QUICK_RUN_REASON_LOOP),
    # Rule 4: never a structured workflow.
    ('a structured workflow', _quick(definition_version=3, flow={'nodes': [{'kind': 'task', 'task_id': 'task-1'}]}),
     QUICK_RUN_REASON_STRUCTURED),
    ('a structured workflow without a flow', _quick(definition_version=3), QUICK_RUN_REASON_STRUCTURED),
    ('a flow without the structured version', _quick(flow={'nodes': [{'kind': 'task'}]}), QUICK_RUN_REASON_STRUCTURED),
    # Rule 5: nothing waits for a person's approval.
    ('a task that needs approval', _quick(tasks=[_task(1), _task(2, approval={'required': True})]),
     QUICK_RUN_REASON_APPROVAL),
    # Rule 6: never runs as a Microsoft 365 user.
    ('a Microsoft 365 run-as user', _quick(m365_run_as_user_id='user-2'), QUICK_RUN_REASON_RUN_AS),
    ('a malformed run-as user', _quick(m365_run_as_user_id={'id': 'user-2'}), QUICK_RUN_REASON_RUN_AS),
    # Rule 7: nothing waits for a review or for indexing.
    ('a publication that waits for approval',
     _quick(tasks=[_task(1), _task(2, publication={'completion_policy': 'approved'})]), QUICK_RUN_REASON_REVIEW),
    ('a publication that waits for indexing',
     _quick(tasks=[_task(1), _task(2, publication={'completion_policy': ' Indexed_Ready '})]),
     QUICK_RUN_REASON_REVIEW),
    ('a malformed publication', _quick(tasks=[_task(1), _task(2, publication='approved')]), QUICK_RUN_REASON_REVIEW),
    # Rule 8: no File Sync trigger and no File Sync before the run.
    ('a File Sync trigger', _quick(trigger_type='file_sync'), QUICK_RUN_REASON_FILE_SYNC),
    ('File Sync on', _quick(file_sync={'enabled': True, 'sources': []}), QUICK_RUN_REASON_FILE_SYNC),
    ('a malformed File Sync config', _quick(file_sync=True), QUICK_RUN_REASON_FILE_SYNC),
    # Rule 9: one to QUICK_RUN_MAX_TASKS tasks.
    ('no tasks', _quick(tasks=[]), QUICK_RUN_REASON_NO_TASKS),
    ('too many tasks', _quick(tasks=[_task(index) for index in range(1, QUICK_RUN_MAX_TASKS + 2)]),
     QUICK_RUN_REASON_TOO_MANY_TASKS),
    # Anything unreadable refuses.
    ('no record', None, QUICK_RUN_REASON_INVALID),
    ('tasks that are not a list', _quick(tasks={'task-1': _task(1)}), QUICK_RUN_REASON_INVALID),
    ('a task that is not a record', _quick(tasks=[_task(1), 'task-2']), QUICK_RUN_REASON_INVALID),
]

SETTINGS_OFF = [
    ('the wait off', {**WAIT_SETTINGS, 'enable_chat_orchestration_workflow_run_wait': False}),
    ('the wait missing',
     {key: value for key, value in WAIT_SETTINGS.items() if key != 'enable_chat_orchestration_workflow_run_wait'}),
    ('the wait as text', {**WAIT_SETTINGS, 'enable_chat_orchestration_workflow_run_wait': 'true'}),
    ('chat orchestration off', {**WAIT_SETTINGS, 'enable_chat_orchestration': False}),
    ('runs from chat off', {**WAIT_SETTINGS, 'enable_chat_orchestration_workflow_runs': False}),
    ('results in chat off', {**WAIT_SETTINGS, 'enable_chat_workflow_results': False}),
    ('personal workflows off', {**WAIT_SETTINGS, 'allow_user_workflows': False}),
    ('no settings', None),
]


def test_version_is_at_least_the_implementation():
    """The quick-run rule ships in 0.261.307."""
    assert_app_version_at_least('0.261.307')


def test_wait_kind_constant():
    """Plan replay refuses this exact wait kind, so its value must not drift."""
    _require(SAVED_WORKFLOW_RUN_WAIT_KIND == 'saved_workflow_run', 'The wait kind constant changed.')


def test_quick_workflows_are_eligible():
    """A quick personal workflow is eligible in every shape the rules allow."""
    _require(wait_configured(WAIT_SETTINGS) is True, 'The wait settings should configure the wait.')
    for label, workflow in ELIGIBLE:
        outcome = quick_run_eligibility(workflow, WAIT_SETTINGS)
        _require(outcome == (True, None), f'{label}: expected eligible, got {outcome!r}.')


def test_each_rule_refuses_with_its_reason():
    """A workflow that breaks one rule is refused with that rule's reason."""
    for label, workflow, reason in REFUSED:
        outcome = quick_run_eligibility(workflow, WAIT_SETTINGS)
        _require(outcome == (False, reason), f'{label}: expected {reason!r}, got {outcome!r}.')


def test_settings_gate_refuses_before_reading_the_workflow():
    """With the wait or anything it needs off, even a quick workflow is refused."""
    for label, settings in SETTINGS_OFF:
        _require(wait_configured(settings) is False, f'{label}: the wait should not be configured.')
        outcome = quick_run_eligibility(_quick(), settings)
        _require(outcome == (False, QUICK_RUN_REASON_WAIT_DISABLED), f'{label}: got {outcome!r}.')


def test_rule_is_pure_and_ignores_model_fields():
    """The rule changes nothing, answers the same twice, and ignores fields a model might add."""
    for _label, workflow, _reason in REFUSED:
        before = deepcopy(workflow)
        first = quick_run_eligibility(workflow, WAIT_SETTINGS)
        second = quick_run_eligibility(workflow, WAIT_SETTINGS)
        _require(first == second, f'The rule is not deterministic: {first!r} then {second!r}.')
        _require(workflow == before, 'The rule changed the workflow record.')
        if isinstance(workflow, dict):
            claimed = {**workflow, 'quick': True, 'waitable': True, 'wait': True, 'eligible': True}
            _require(
                quick_run_eligibility(claimed, WAIT_SETTINGS) == first,
                'A field a model could add changed the outcome.',
            )
    settings = deepcopy(WAIT_SETTINGS)
    quick_run_eligibility(_quick(), settings)
    _require(settings == WAIT_SETTINGS, 'The rule changed the settings.')


def test_reason_texts_are_app_owned():
    """Every reason has fixed text, none of it names a workflow, and an unknown code is generic."""
    reasons = {reason for _label, _workflow, reason in REFUSED} | {QUICK_RUN_REASON_WAIT_DISABLED}
    _require(reasons <= set(QUICK_RUN_REASON_TEXT), f'Reasons without text: {reasons - set(QUICK_RUN_REASON_TEXT)}.')
    for reason, text in QUICK_RUN_REASON_TEXT.items():
        _require(isinstance(text, str) and text.strip(), f'{reason} has no text.')
        _require(HOSTILE_NAME not in text and '<' not in text and '{' not in text, f'{reason} text is unsafe.')
        _require(quick_run_reason_text(reason) == text, f'{reason} text does not round-trip.')
    _require(
        quick_run_reason_text('made_up') == QUICK_RUN_REASON_TEXT[QUICK_RUN_REASON_INVALID],
        'An unknown reason should read as the generic refusal.',
    )
    _require(str(QUICK_RUN_MAX_TASKS) in QUICK_RUN_REASON_TEXT[QUICK_RUN_REASON_TOO_MANY_TASKS],
             'The task limit text should give the limit.')


if __name__ == '__main__':
    tests = [
        test_version_is_at_least_the_implementation,
        test_wait_kind_constant,
        test_quick_workflows_are_eligible,
        test_each_rule_refuses_with_its_reason,
        test_settings_gate_refuses_before_reading_the_workflow,
        test_rule_is_pure_and_ignores_model_fields,
        test_reason_texts_are_app_owned,
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
