# test_orchestration_settings_runtime_state_binding.py
"""Background settings writes never invalidate saved orchestration progress.

Version: 0.261.302
Implemented in: 0.261.302

A waiting run failed with "Saved step inputs changed" because its execution binding hashed the
whole settings document. That document also holds storage metadata that changes on every save
and runtime state that background tasks write, such as the Cosmos DB throughput monitor's
readings. These tests prove those fields no longer change a saved binding, that real policy
changes still do, and that every background writer's keys are covered. Real fingerprints,
leases and waiting checkpoints run; only storage transport and producer/model I/O are isolated.
"""

import ast
from pathlib import Path

import pytest

from test_orchestration_dependency_recovery import durable  # noqa: F401
from test_orchestration_dependency_runtime import compose, runtime  # noqa: F401
from test_orchestration_waiting_continuation import claim, start_waiting
from test_support.versioning import assert_app_version_at_least


APP = Path(__file__).resolve().parents[1] / 'application' / 'single_app'

# What a settings save and a Cosmos DB throughput scale-up change, as seen at 14:24:30 UTC on
# 2026-10-08 just before a waiting run failed. None of it is configuration.
BEFORE_WRITE = {
    '_etag': '"etag-before"', '_ts': 1791469400, '_rid': 'rid', '_self': 'self', '_attachments': 'attachments/',
    '_settings_revision': 41, 'id': 'app_settings',
    'cosmos_throughput_last_checked_at': '2026-10-08T14:22:20+00:00',
    'cosmos_throughput_last_observed_percent': 71,
    'cosmos_throughput_cached_status': {'mode': 'autoscale', 'current_ru': 1000},
    'cosmos_throughput_container_policies': {'settings': {'min_ru': 1000}},
    'service_health': {'semantic_search': {'status': 'healthy'}},
    'control_center_last_refresh': '2026-10-08T06:00:00+00:00',
    'enable_debug_logging': True, 'debug_logging_turnoff_time': '2026-10-08T15:00:00+00:00',
}
AFTER_WRITE = {
    '_etag': '"etag-after"', '_ts': 1791469470, '_settings_revision': 42,
    'cosmos_throughput_last_checked_at': '2026-10-08T14:24:30+00:00',
    'cosmos_throughput_last_observed_percent': 96,
    'cosmos_throughput_last_scale_action': 'up', 'cosmos_throughput_last_scale_to_ru': 2000,
    'cosmos_throughput_cached_status': {'mode': 'autoscale', 'current_ru': 2000},
    'cosmos_throughput_container_policies': {
        'settings': {'min_ru': 1000, 'last_scale_up_at': '2026-10-08T14:24:30+00:00'},
    },
    'service_health': {'semantic_search': {'status': 'quota_exceeded'}},
    'control_center_last_refresh': '2026-10-08T14:24:00+00:00',
    'control_center_auto_refresh_next_run': '2026-10-09T06:00:00+00:00',
    'retention_policy_last_run': '2026-10-08T14:00:00+00:00',
    'last_update_check_time': '2026-10-08T14:24:00+00:00', 'update_available': True,
    'enable_debug_logging': False, 'debug_logging_turnoff_time': None,
}
POLICY_CHANGES = [
    {'chat_orchestration_max_steps': 4},
    {'chat_orchestration_enabled_capabilities': ['document_search']},
    {'enable_user_workspace': False},
    {'enable_chat_orchestration_actions': True},
]

# Background tasks that write settings, and the dictionaries they save. The keys these build
# must all be runtime state, so a new runtime key cannot silently invalidate saved progress.
SETTINGS_WRITERS = (
    ('functions_cosmos_throughput.py', 'build_runtime_update', ('update',)),
    ('background_tasks.py', '_seed_control_center_auto_refresh_next_run', ()),
    ('functions_control_center.py', 'execute_control_center_refresh', ('settings_updates',)),
    ('functions_retention_policy.py', 'execute_retention_policy', ('settings_updates',)),
    ('functions_service_health.py', 'record_semantic_search_quota_exceeded', ()),
    ('functions_service_health.py', 'clear_semantic_search_quota_warning', ()),
    ('functions_settings.py', 'get_application_update_status', ('updates',)),
)


def _bindings(runtime, case, settings):
    checkpoints = runtime.checkpoints
    binding = checkpoints.context_binding(case.context, case.plan, settings)
    step = checkpoints.step_input_fingerprint(case.plan['steps'][0], case.context, binding, settings=settings)
    return binding, step


def _string_keys(node):
    return [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]


def _saved_keys(file_name, function_name, names):
    tree = ast.parse((APP / file_name).read_text(encoding='utf-8'))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    keys = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id == 'update_settings':
                for argument in node.args[:1]:
                    if isinstance(argument, ast.Dict):
                        keys.update(_string_keys(argument))
            if (
                isinstance(target, ast.Attribute) and target.attr == 'update'
                and isinstance(target.value, ast.Name) and target.value.id in names
            ):
                for argument in node.args:
                    if isinstance(argument, ast.Dict):
                        keys.update(_string_keys(argument))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names and isinstance(node.value, ast.Dict):
                    keys.update(_string_keys(node.value))
                if (
                    isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                    and target.value.id in names and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    keys.add(target.slice.value)
    return keys


def test_version_includes_the_runtime_state_binding_fix():
    assert_app_version_at_least('0.261.302')


def test_storage_metadata_and_runtime_state_leave_saved_bindings_unchanged(runtime):
    case = runtime.make([compose()])
    before = {**case.settings, **BEFORE_WRITE}
    after = {**before, **AFTER_WRITE}
    assert _bindings(runtime, case, after) == _bindings(runtime, case, before)
    assert _bindings(runtime, case, before) == _bindings(runtime, case, case.settings)


@pytest.mark.parametrize('changes', POLICY_CHANGES)
def test_policy_changes_still_invalidate_saved_bindings_beside_runtime_state(runtime, changes):
    case = runtime.make([compose()])
    before = {**case.settings, **BEFORE_WRITE}
    changed = {**before, **AFTER_WRITE, **changes}
    original_binding, original_step = _bindings(runtime, case, before)
    changed_binding, changed_step = _bindings(runtime, case, changed)
    assert changed_binding != original_binding
    assert changed_step != original_step


def test_registry_matches_the_settings_store_and_logging_timers(runtime):
    import app_settings_store
    import functions_logging_timers
    import functions_settings_runtime_state as registry

    assert registry.SETTINGS_STORAGE_KEYS == frozenset({
        *app_settings_store.COSMOS_METADATA_FIELDS, app_settings_store.SETTINGS_REVISION_FIELD, 'id',
    })
    for timer in functions_logging_timers.LOGGING_TIMERS.values():
        for key in timer.values():
            assert registry.is_settings_runtime_state_key(key), key
    # Configuration an administrator saves stays in the fingerprint.
    for key in ('enable_chat_orchestration', 'chat_orchestration_max_steps', 'enable_user_workspace', 'gpt_model'):
        assert not registry.is_settings_runtime_state_key(key), key
    assert not registry.is_settings_runtime_state_key(None)


@pytest.mark.parametrize('file_name,function_name,names', SETTINGS_WRITERS)
def test_every_background_settings_writer_saves_only_runtime_state(runtime, file_name, function_name, names):
    import functions_settings_runtime_state as registry

    keys = _saved_keys(file_name, function_name, names)
    assert keys, f'{function_name} no longer saves recognizable settings keys; update this test.'
    assert sorted(key for key in keys if not registry.is_settings_runtime_state_key(key)) == []


def test_a_waiting_run_continues_after_a_background_settings_write(durable):
    settings = durable.case.settings
    settings.update(BEFORE_WRITE)
    start_waiting(durable)
    original = durable.read_run('run-1')

    settings.update(AFTER_WRITE)
    acquired = claim(durable, submission='after-background-write')
    assert acquired['acquired'] is True
    record = acquired['record']
    result = durable.run(record, durable.fresh_context(record))
    saved = durable.read_run('run-1')

    assert result['status'] == 'waiting'
    assert saved['status'] == 'waiting'
    assert saved['execution_binding'] == original['execution_binding']
    assert saved['task_results'] == original['task_results']
    assert saved['pending_results'] == original['pending_results']
    assert saved['execution_deadline_at'] == original['execution_deadline_at']


def test_a_policy_change_still_stops_a_waiting_run(durable):
    settings = durable.case.settings
    settings.update(BEFORE_WRITE)
    start_waiting(durable)

    settings.update({**AFTER_WRITE, 'chat_orchestration_max_steps': 4})
    acquired = claim(durable, submission='after-policy-change')
    assert acquired['acquired'] is True
    record = acquired['record']
    with pytest.raises(durable.runtime.checkpoints.CheckpointError) as failure:
        durable.run(record, durable.fresh_context(record))
    assert failure.value.code == 'recovery_changed'
