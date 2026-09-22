# test_orchestration_dependency_allowlist.py
"""Functional tests for authoritative v2 capability allowlists and admin metadata.

Version: 0.261.127
Implemented in: 0.261.127
Saved legacy selections never silently opt into composition or file publication.
The real registry/compiler/executor and initialized rendering service are exercised;
only external I/O is isolated.
"""

from copy import deepcopy
import importlib

import pytest

from test_orchestration_dependency_runtime import binding, compose, execute, runtime
from test_orchestration_output_lifecycle import lifecycle, production_modules


CAPABILITIES_KEY = 'chat_orchestration_enabled_capabilities'
CANDIDATES = {'document_search', 'compose', 'render_file'}


def _ids(registry, settings=None, *, allowed_ids=None, service=None, unavailable=None):
    capabilities = registry.resolve_available_capabilities(
        {'enable_user_workspace': True, **(settings or {})},
        allowed_ids=allowed_ids,
        request_context={'rendering_service': service},
        candidate_ids=CANDIDATES,
        unavailable=unavailable,
        contract_version=2,
    )
    return {capability['id'] for capability in capabilities}


@pytest.mark.parametrize('saved, caller, expected', [
    (None, None, {'document_search', 'compose'}),
    ([], None, {'document_search', 'compose'}),
    (['document_search', 'respond'], None, {'document_search'}),
    (['respond'], None, set()),
    (['compose'], None, {'compose'}),
    (['compose'], ['document_search'], set()),
    (['compose', 'document_search'], ['document_search'], {'document_search'}),
    (['document_search'], ['document_search', 'compose', 'render_file'], {'document_search'}),
    (['document_search'], [], {'document_search'}),
    ([], ['compose'], {'compose'}),
    ([' compose '], {'compose'}, {'compose'}),
    (None, frozenset({'compose'}), {'compose'}),
    (['retired_unknown_capability'], None, set()),
])
def test_saved_and_caller_allowlists_intersect_without_implicit_permissions(runtime, saved, caller, expected):
    settings = {CAPABILITIES_KEY: saved}
    original = deepcopy(settings)
    result = _ids(runtime.registry, settings, allowed_ids=caller)
    assert result == expected
    assert settings == original


def test_full_saved_legacy_list_is_not_an_opt_in_to_new_capabilities(runtime):
    legacy_ids = runtime.registry.all_capability_ids()
    unavailable = {}
    result = _ids(runtime.registry, {CAPABILITIES_KEY: legacy_ids}, unavailable=unavailable)
    assert result == {'document_search'}
    assert unavailable['compose'] == 'not_enabled_for_orchestration'
    assert unavailable['render_file'] == 'not_enabled_for_orchestration'
    assert 'compose' not in legacy_ids and 'render_file' not in legacy_ids


@pytest.mark.parametrize('source', ['saved', 'caller'])
@pytest.mark.parametrize('malformed', [
    'compose', {}, False, [''], [' '], ['compose', None], ['compose', 42],
])
def test_malformed_allowlists_fail_closed_and_are_logged(runtime, monkeypatch, source, malformed):
    events = []
    monkeypatch.setattr(runtime.registry, 'log_event', lambda message, **kwargs: events.append((message, kwargs)))
    settings = {CAPABILITIES_KEY: malformed if source == 'saved' else []}
    caller = malformed if source == 'caller' else ['compose']
    with pytest.raises(runtime.registry.CapabilityResolutionError):
        _ids(runtime.registry, settings, allowed_ids=caller)
    assert len(events) == 1
    assert events[0][0] == '[ORCHESTRATION_REGISTRY] Invalid harness capability allowlist.'
    assert events[0][1]['extra']['source'] == ('settings' if source == 'saved' else 'allowed_ids')


def test_saved_restriction_is_applied_before_disabled_runtime_bindings(runtime, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('An excluded operation must not enter its feature or caller gate.')

    monkeypatch.setattr(runtime.registry, '_gates_pass', forbidden)
    monkeypatch.setattr(runtime.registry, '_request_gate_passes', forbidden)
    unavailable = {}
    result = _ids(
        runtime.registry, {CAPABILITIES_KEY: ['respond']},
        allowed_ids=['compose', 'render_file'], unavailable=unavailable,
    )
    assert result == set()
    assert set(unavailable.values()) == {'not_enabled_for_orchestration'}


def test_explicit_selection_does_not_override_feature_gates(runtime):
    unavailable = {}
    result = _ids(
        runtime.registry,
        {CAPABILITIES_KEY: ['document_search', 'compose'], 'enable_user_workspace': False},
        unavailable=unavailable,
    )
    assert result == {'compose'}
    assert unavailable['document_search'] == 'feature_disabled'


def test_real_render_service_does_not_override_legacy_or_caller_restrictions(lifecycle):
    registry = importlib.import_module('functions_orchestration_registry')
    legacy_ids = registry.all_capability_ids()
    legacy = _ids(registry, {CAPABILITIES_KEY: legacy_ids}, service=lifecycle.service)
    explicit = _ids(registry, {CAPABILITIES_KEY: ['compose', 'render_file']}, service=lifecycle.service)
    narrowed = _ids(
        registry, {CAPABILITIES_KEY: ['compose', 'render_file']},
        allowed_ids=['compose'], service=lifecycle.service,
    )
    broadened = _ids(
        registry, {CAPABILITIES_KEY: ['compose']},
        allowed_ids=['compose', 'render_file'], service=lifecycle.service,
    )
    assert legacy == {'document_search'}
    assert explicit == {'compose', 'render_file'}
    assert narrowed == broadened == {'compose'}
    assert lifecycle.render_calls == [] and lifecycle.blobs.uploads == 0


@pytest.mark.parametrize('service', [None, True, {'enabled': True}, lambda: None])
def test_explicit_render_permission_still_requires_initialized_service(runtime, service):
    unavailable = {}
    result = _ids(
        runtime.registry, {CAPABILITIES_KEY: ['render_file']},
        service=service, unavailable=unavailable,
    )
    assert result == set()
    assert unavailable['render_file'] == 'rendering_service_unavailable'


def test_execution_rechecks_saved_compose_permission_before_any_model_call(runtime):
    case = runtime.make([compose()], ['Do not generate this answer.'], final_response=binding('draft'))
    case.settings[CAPABILITIES_KEY] = ['document_search', 'respond']
    with pytest.raises(runtime.schema.PlanValidationError):
        execute(runtime, case)
    assert case.model.calls == []
    assert case.context.task_results == {}


def test_denied_file_cannot_be_repaired_into_a_text_only_plan(lifecycle):
    registry = importlib.import_module('functions_orchestration_registry')
    schema = importlib.import_module('functions_orchestration_schema')
    settings = {CAPABILITIES_KEY: ['compose']}
    available = _ids(registry, settings, service=lifecycle.service)
    raw = {
        'steps': [
            compose(),
            {
                'step_id': 'file', 'capability_id': 'render_file',
                'arguments': {
                    'file_name': 'Prepared report.md', 'output_format': 'md', 'profile': 'prepared_text_v1',
                },
                'inputs': {'source': {'binding': binding('draft'), 'allow_partial': False}},
                'outputs': [],
            },
        ],
        'final_response': binding('draft'),
    }
    original = deepcopy(raw)
    with pytest.raises(schema.PlanValidationError):
        schema.normalize_plan(
            raw, 'conversation-1', 'owner', settings=settings, available_capability_ids=available,
            contract_version=2,
        )
    assert raw == original
    assert lifecycle.render_calls == [] and lifecycle.blobs.uploads == 0


def test_v2_metadata_expresses_roles_and_version_without_changing_legacy(runtime):
    registry = runtime.registry
    original = deepcopy(registry.CAPABILITY_REGISTRY)
    legacy = registry.describe_registry()
    dependency = registry.describe_registry(contract_version=2)
    client = registry.build_capability_client_projection(registry.capabilities_for_contract(2))
    legacy_client = registry.build_capability_client_projection(registry.CAPABILITY_REGISTRY)
    by_id = {capability['id']: capability for capability in client}
    assert legacy == {
        'contract_version': 1,
        'capability_ids': [capability['id'] for capability in original],
        'terminal_capability_id': 'respond',
        'phases': ['knowledge', 'reasoning', 'output'],
    }
    assert dependency['contract_version'] == 2 and dependency['terminal_capability_id'] is None
    assert dependency['roles'] == ['gather', 'reason', 'render']
    assert {'compose', 'render_file'} <= set(dependency['capability_ids'])
    assert 'respond' not in dependency['capability_ids'] and 'phases' not in dependency
    assert by_id['compose']['role'] == 'reason' and by_id['render_file']['role'] == 'render'
    for capability in client:
        assert set(capability) == {'id', 'label', 'role', 'summary', 'cost', 'terminal', 'plan_contract_version'}
        assert capability['plan_contract_version'] == 2 and capability['terminal'] is False
    for capability in legacy_client:
        assert set(capability) == {'id', 'label', 'phase', 'summary', 'cost', 'terminal'}
    assert registry.CAPABILITY_REGISTRY == original


def test_legacy_narrowing_retains_its_terminal_and_original_settings_semantics(runtime):
    registry = runtime.registry
    settings = {'enable_user_workspace': True, CAPABILITIES_KEY: ['respond']}
    default = registry.resolve_available_capability_ids(settings)
    narrowed = registry.resolve_available_capability_ids(settings, allowed_ids=['document_search'])
    assert 'document_search' in default and 'respond' in default
    assert narrowed == ['document_search', 'respond']
