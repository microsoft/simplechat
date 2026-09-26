# test_orchestration_registry_contract.py
"""
Functional test for the chat orchestration capability registry.
Version: 0.261.139
Implemented in: 0.261.085
Single orchestration contract updated in: 0.261.139

The registry is the only capability information the planner model sees, and it is also
what the validator checks a plan against. Gather / Reason / Render has one registry, one
contract marker, server-owned roles, and no terminal/respond capability.
"""

import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT  # noqa: E402
from test_support.orchestration_research import stubbed_orchestration_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

REGISTRY = 'functions_orchestration_registry.py'


def _settings(**values):
    return {
        'document_action_capabilities': {
            'analyze': {'enabled': False}, 'comparison': {'enabled': False},
        },
        **values,
    }


def test_descriptors_are_well_formed_for_the_single_contract():
    """Every static descriptor carries the fields the planner and validator both rely on."""
    with stubbed_orchestration_imports():
        import functions_orchestration_registry as registry

        required = {
            'id', 'label', 'role', 'summary', 'when_to_use', 'settings_gates',
            'settings_gates_any', 'gate', 'requires_scope', 'inputs', 'produces',
            'cost_class', 'max_per_plan', 'adapter', 'result_outputs',
            'result_input_kinds', 'partial_inputs_supported', 'result_contract_version',
        }
        ids = [capability['id'] for capability in registry.CAPABILITY_REGISTRY]
        assert len(ids) == len(set(ids))
        assert 'respond' not in ids
        assert registry.CAPABILITY_RENDER_FILE not in ids

        for capability in registry.CAPABILITY_REGISTRY:
            assert required <= set(capability), f"{capability.get('id')} missing {sorted(required - set(capability))}"
            assert capability['role'] in (registry.ROLE_GATHER, registry.ROLE_REASON, registry.ROLE_RENDER)
            assert capability['cost_class'] in registry.COST_CLASSES
            schema = capability['inputs']
            if capability['id'] == registry.CAPABILITY_TABULAR_ANALYZE:
                assert schema is None
                continue
            assert schema.get('type') == 'object'
            assert schema.get('additionalProperties') is False
            for name in schema.get('required') or ():
                assert name in (schema.get('properties') or {})

        source = open(os.path.join(APP_ROOT, REGISTRY), encoding='utf-8').read()
        assert 'def _render_file_descriptor' in source
        assert 'capabilities.append(_render_file_descriptor())' in source
        description = registry.describe_registry()
        assert description['contract_version'] == 2
        assert description['roles'] == ['gather', 'reason', 'render']

        for unsupported in (1, 3, '2'):
            with pytest.raises(ValueError):
                registry.get_capability(registry.CAPABILITY_COMPOSE, contract_version=unsupported)

def test_gates_withhold_capabilities_without_runtime_discovery_side_effects():
    """Settings gates are checked separately from runtime service availability."""
    with stubbed_orchestration_imports():
        import functions_orchestration_registry as registry

        bare = registry.resolve_available_capability_ids(_settings(), candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False)
        assert registry.CAPABILITY_COMPOSE in bare
        assert registry.CAPABILITY_DOCUMENT_SEARCH not in bare
        assert registry.CAPABILITY_WEB_SEARCH not in bare

        with_web = registry.resolve_available_capability_ids(
            _settings(enable_web_search=True), candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False,
        )
        assert registry.CAPABILITY_WEB_SEARCH in with_web

        for workspace_key in ('enable_user_workspace', 'enable_group_workspaces', 'enable_public_workspaces'):
            ids = registry.resolve_available_capability_ids(
                _settings(**{workspace_key: True}), candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False,
            )
            assert registry.CAPABILITY_DOCUMENT_SEARCH in ids

        runtime_checked = registry.resolve_available_capability_ids(
            _settings(enable_web_search=True), candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=True,
        )
        assert registry.CAPABILITY_WEB_SEARCH not in runtime_checked


def test_administrator_narrowing_no_longer_adds_a_terminal_step():
    """The enabled-capability list intersects the registry; no respond capability is forced in."""
    with stubbed_orchestration_imports():
        import functions_orchestration_registry as registry

        settings = _settings(enable_user_workspace=True, enable_web_search=True)
        full = registry.resolve_available_capability_ids(settings, candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False)
        assert registry.resolve_available_capability_ids(settings, allowed_ids=[], candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False) == full
        assert registry.resolve_available_capability_ids(settings, allowed_ids=None, candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False) == full

        narrowed = registry.resolve_available_capability_ids(
            settings, allowed_ids=[registry.CAPABILITY_WEB_SEARCH], candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False,
        )
        assert narrowed == [registry.CAPABILITY_WEB_SEARCH]
        assert 'respond' not in narrowed


def test_planner_and_client_projections_hide_internals():
    """Gate internals stay private; role and output contracts describe feasible work."""
    with stubbed_orchestration_imports():
        import functions_orchestration_registry as registry

        settings = _settings(enable_user_workspace=True, enable_web_search=True)
        available = registry.resolve_available_capabilities(settings, candidate_ids={'compose', 'document_search', 'web_search'}, include_runtime_bindings=False)
        projection = registry.build_planner_capability_projection(available)
        assert projection
        leaked = {'gate', 'settings_gates', 'settings_gates_any', 'adapter', 'document_action_type', 'requires_scope'}
        for entry in projection:
            assert not leaked & set(entry)
            assert entry['role'] in ('gather', 'reason', 'render')
            assert entry['when_to_use']
            assert 'produces' in entry and 'max_per_plan' in entry
            assert 'phase' not in entry and 'terminal' not in entry

        client = registry.build_capability_client_projection(available)
        for entry in client:
            assert set(entry) == {'id', 'label', 'role', 'summary', 'cost'}


def _run_script():
    assert_app_version_at_least('0.261.139')
    tests = [
        test_descriptors_are_well_formed_for_the_single_contract,
        test_gates_withhold_capabilities_without_runtime_discovery_side_effects,
        test_administrator_narrowing_no_longer_adds_a_terminal_step,
        test_planner_and_client_projections_hide_internals,
    ]
    passed = 0
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            passed += 1
            print('Test passed!')
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
    print(f"\nResults: {passed}/{len(tests)} tests passed")
    return passed == len(tests)


if __name__ == '__main__':
    sys.exit(0 if _run_script() else 1)
