# test_orchestration_settings_upgrade.py
"""Saved runs keep their execution binding across the single-contract settings upgrade.

Version: 0.261.139
Implemented in: 0.261.139
Retiring the Gather / Reason / Render toggle and the removed answering capability must not
change the settings fingerprint a saved run is bound to, or waiting runs could not continue
and failed runs could not be retried. Real fingerprints, leases, retained results and waiting
checkpoints run; only storage transport and producer/model I/O are isolated. The settings
loader's retirement step is the production function, read from source so no application
configuration is imported.
"""

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from test_orchestration_dependency_recovery import durable  # noqa: F401
from test_orchestration_dependency_runtime import binding, compose, runtime  # noqa: F401
from test_orchestration_waiting_continuation import claim, start_waiting
from test_support.versioning import assert_app_version_at_least


APP = Path(__file__).resolve().parents[1] / 'application' / 'single_app'
TOGGLE = 'enable_chat_orchestration_harness'
CAPABILITIES_KEY = 'chat_orchestration_enabled_capabilities'
# Earlier releases always kept the removed answering step in a narrowed list.
SAVED_NARROWED_LIST = ['compose', 'respond']


def _settings_retirement():
    tree = ast.parse((APP / 'functions_settings.py').read_text(encoding='utf-8'))
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == 'normalize_retired_orchestration_settings')
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'RETIRED_SETTING_KEYS' for target in node.targets)
        )
    ]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'functions_settings.py', 'exec'), namespace)
    return namespace['normalize_retired_orchestration_settings']


def _as_loaded_after_upgrade(stored):
    loaded = deepcopy(stored)
    _settings_retirement()(loaded)
    return loaded


def _as_fingerprinted_before_upgrade(stored):
    # Earlier releases left the toggle out of a saved run's settings fingerprint.
    return {key: value for key, value in stored.items() if key != TOGGLE}


def test_version_includes_the_settings_upgrade():
    assert_app_version_at_least('0.261.139')


@pytest.mark.parametrize('saved_list', [[], SAVED_NARROWED_LIST])
def test_saved_bindings_match_after_the_upgrade_retires_the_toggle(runtime, saved_list):
    case = runtime.make([compose()], final_response=binding('draft'))
    checkpoints = runtime.checkpoints
    stored = {**case.settings, TOGGLE: True, CAPABILITIES_KEY: list(saved_list)}
    before = _as_fingerprinted_before_upgrade(stored)
    recorded_binding = checkpoints.context_binding(case.context, case.plan, before)
    recorded_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, recorded_binding, settings=before,
    )
    loaded = _as_loaded_after_upgrade(stored)
    upgraded_binding = checkpoints.context_binding(case.context, case.plan, loaded)
    upgraded_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, upgraded_binding, settings=loaded,
    )
    assert TOGGLE not in loaded and loaded[CAPABILITIES_KEY] == saved_list
    assert upgraded_binding == recorded_binding
    assert upgraded_step == recorded_step


@pytest.mark.parametrize('changes', [
    {'chat_orchestration_max_steps': 4},
    {CAPABILITIES_KEY: ['document_search']},
    {'enable_user_workspace': False},
    {'enable_chat_orchestration_actions': True},
])
def test_real_execution_policy_changes_still_invalidate_saved_bindings(runtime, changes):
    case = runtime.make([compose()])
    checkpoints = runtime.checkpoints
    original_binding = checkpoints.context_binding(case.context, case.plan, case.settings)
    original_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, original_binding, settings=case.settings,
    )
    settings = {**case.settings, **changes}
    changed_binding = checkpoints.context_binding(case.context, case.plan, settings)
    changed_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, changed_binding, settings=settings,
    )
    assert changed_binding != original_binding
    assert changed_step != original_step


def test_a_waiting_run_saved_before_the_upgrade_continues_after_it(durable):
    settings = durable.case.settings
    stored = {**settings, TOGGLE: True, CAPABILITIES_KEY: list(SAVED_NARROWED_LIST)}
    settings.clear()
    settings.update(_as_fingerprinted_before_upgrade(stored))
    start_waiting(durable)
    original = durable.read_run('run-1')

    settings.clear()
    settings.update(_as_loaded_after_upgrade(stored))
    acquired = claim(durable, submission='after-upgrade')
    assert acquired['acquired'] is True
    record = acquired['record']
    result = durable.run(record, durable.fresh_context(record))
    saved = durable.read_run('run-1')

    assert result['status'] == 'waiting'
    assert saved['execution_binding'] == original['execution_binding']
    assert saved['task_results'] == original['task_results']
    assert saved['pending_results'] == original['pending_results']
    assert saved['attempt_index'] == original['attempt_index']
    assert saved['execution_deadline_at'] == original['execution_deadline_at']
    assert record['execution_lease']['token'] == durable.record['execution_lease']['token']
    assert len(durable.case.model.calls) == 1
    assert len(durable.runs.items) == 1
