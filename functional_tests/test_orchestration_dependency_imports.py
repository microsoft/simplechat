# test_orchestration_dependency_imports.py
"""Real cold imports for the v2 runtime/composition dependency boundaries.

Version: 0.261.127
Implemented in: 0.261.127
Uses the existing fresh-process, network-blocked normal/optimized bootstrap matrix.
"""

import ast

import pytest

from test_orchestration_result_imports import APP, APP_PROBE, EARLY_PROBE, run_probe


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('order', [
    ('functions_orchestration_composition', 'functions_orchestration_executor'),
    ('functions_orchestration_executor', 'functions_orchestration_composition'),
])
def test_runtime_and_composition_cold_imports_do_not_bootstrap_owners(order, optimized):
    run_probe(EARLY_PROBE, order, optimized)


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('order', [
    ('functions_orchestration_executor', 'app', 'background_tasks'),
    ('app', 'functions_orchestration_composition', 'background_tasks'),
    ('background_tasks', 'functions_orchestration_composition', 'functions_orchestration_executor'),
])
def test_real_web_scheduler_and_v2_services_import_in_both_modes(order, optimized):
    run_probe(APP_PROBE, order, optimized)


def test_composition_and_result_handoffs_have_no_reverse_owner_imports():
    forbidden = {'config', 'functions_settings', 'functions_saved_analysis', 'functions_artifact_publication'}
    for name in ('functions_orchestration_composition', 'functions_orchestration_result_runtime'):
        tree = ast.parse((APP / f'{name}.py').read_text(encoding='utf-8'))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or '')
        assert not forbidden.intersection(imports)
        assert not any(module.startswith('route_') for module in imports)
