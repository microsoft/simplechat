# test_orchestration_dependency_allowlist.py
"""Functional tests for authoritative capability allowlists and admin metadata.

Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
A capability list saved before Gather / Reason / Render became the only contract keeps
its answering ability, because a stored `respond` reads as `compose`, and never silently
opts into file publication. The stored list itself is never rewritten.
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
# Every capability an administrator could save under the removed earlier contract.
LEGACY_SAVED_IDS = [
    'document_search', 'document_analyze', 'document_compare', 'tabular_analyze', 'web_search',
    'url_fetch', 'deep_research', 'action_invoke', 'agent_invoke', 'respond',
]


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
    (['document_search', 'respond'], None, {'document_search', 'compose'}),
    (['respond'], None, {'compose'}),
    (['respond'], ['document_search'], set()),
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
    # The removed answering step reads as Prepare content, which now writes the answer.
    # Nothing maps a saved list to render_file, and the saved list is not rewritten.
    settings = {CAPABILITIES_KEY: list(LEGACY_SAVED_IDS)}
    unavailable = {}
    result = _ids(runtime.registry, settings, unavailable=unavailable)
    assert result == {'document_search', 'compose'}
    assert unavailable['render_file'] == 'not_enabled_for_orchestration'
    assert settings == {CAPABILITIES_KEY: LEGACY_SAVED_IDS}
    assert 'respond' not in runtime.registry.all_capability_ids()


def test_a_saved_answering_step_is_read_as_prepare_content_without_rewriting(runtime):
    registry = runtime.registry
    saved = ['document_search', 'respond', 'compose']
    assert registry.effective_capability_ids(saved) == ['document_search', 'compose']
    assert saved == ['document_search', 'respond', 'compose']
    assert registry.effective_capability_ids([]) == []
    for malformed in ('respond', None, ('respond',), ['respond', 42]):
        assert registry.effective_capability_ids(malformed) is malformed


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
    assert events[0][0] == '[ORCHESTRATION_REGISTRY] Invalid orchestration capability allowlist.'
    assert events[0][1]['extra']['source'] == ('settings' if source == 'saved' else 'allowed_ids')


def test_saved_restriction_is_applied_before_disabled_runtime_bindings(runtime, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('An excluded operation must not enter its feature or caller gate.')

    monkeypatch.setattr(runtime.registry, '_gates_pass', forbidden)
    monkeypatch.setattr(runtime.registry, '_request_gate_passes', forbidden)
    unavailable = {}
    result = _ids(
        runtime.registry, {CAPABILITIES_KEY: ['document_analyze']},
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
    legacy = _ids(registry, {CAPABILITIES_KEY: LEGACY_SAVED_IDS}, service=lifecycle.service)
    explicit = _ids(registry, {CAPABILITIES_KEY: ['compose', 'render_file']}, service=lifecycle.service)
    narrowed = _ids(
        registry, {CAPABILITIES_KEY: ['compose', 'render_file']},
        allowed_ids=['compose'], service=lifecycle.service,
    )
    broadened = _ids(
        registry, {CAPABILITIES_KEY: ['compose']},
        allowed_ids=['compose', 'render_file'], service=lifecycle.service,
    )
    # A saved legacy list answers through Prepare content but never gains file creation.
    assert legacy == {'document_search', 'compose'}
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
    case.settings[CAPABILITIES_KEY] = ['document_search']
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


def test_registry_metadata_expresses_roles_without_phases_or_a_terminal_step(runtime):
    registry = runtime.registry
    original = deepcopy(registry.CAPABILITY_REGISTRY)
    described = registry.describe_registry()
    client = registry.build_capability_client_projection(registry.capabilities_for_contract())
    by_id = {capability['id']: capability for capability in client}
    assert described == {
        'contract_version': 2,
        'capability_ids': [
            'document_search', 'document_analyze', 'document_compare', 'tabular_analyze',
            'web_search', 'url_fetch', 'deep_research', 'action_invoke', 'agent_invoke',
            'compose', 'generate_image', 'render_file',
        ],
        'roles': ['gather', 'reason', 'render'],
    }
    assert by_id['compose']['role'] == 'reason' and by_id['render_file']['role'] == 'render'
    for capability in client:
        assert set(capability) == {'id', 'label', 'role', 'summary', 'cost'}
    assert registry.CAPABILITY_REGISTRY == original
    with pytest.raises(ValueError):
        registry.describe_registry(contract_version=1)


def test_narrowing_never_adds_an_implicit_answer_capability(runtime):
    registry = runtime.registry
    settings = {'enable_user_workspace': True, CAPABILITIES_KEY: ['document_search']}
    default = registry.resolve_available_capability_ids(settings)
    narrowed = registry.resolve_available_capability_ids(settings, allowed_ids=['document_search'])
    assert default == narrowed == ['document_search']
    # A saved list naming the removed answering step reads as Prepare content, and gains
    # nothing else.
    retired = registry.resolve_available_capability_ids(
        {'enable_user_workspace': True, CAPABILITIES_KEY: ['respond']},
    )
    assert retired == ['compose']
