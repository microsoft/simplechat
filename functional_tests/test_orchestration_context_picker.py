#!/usr/bin/env python3
# test_orchestration_context_picker.py
"""
Functional test for the document context picker reaching orchestration.
Version: 0.261.139
Implemented in: 0.261.091
Single orchestration contract updated in: 0.261.139

The composer's context picker lets a user name documents, tags and whole workspaces before
asking. Gather / Reason / Render keeps those selections as planning seeds, and Analyze
reads Search output through a named source-set binding instead of the removed
``documents_from_step`` argument.
"""

import ast
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT, stubbed_app_imports  # noqa: E402
from test_support.orchestration_research import document_action_policy_module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

ADAPTERS = 'functions_orchestration_adapters.py'
CONTEXT = 'functions_orchestration_context.py'
SEARCH = 'functions_search.py'

_PERMISSIVE = {
    'enable_chat_orchestration': True,
    'enable_user_workspace': True,
    'enable_group_workspaces': True,
    'enable_web_search': True,
    'document_action_capabilities': {'analyze': {'enabled': True}},
}
_CAPABILITIES = ['document_search', 'document_analyze', 'document_compare', 'tabular_analyze', 'web_search', 'compose']


def _read(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return handle.read()


def _tree(module):
    return ast.parse(_read(module))


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _binding(step_id, output='sources'):
    return {
        'version': 'orchestration-input-binding-v1',
        'step_id': step_id,
        'output_name': output,
        'existing_result': None,
    }


def _source_input(step_id, output='sources'):
    return {'binding': _binding(step_id, output), 'allow_partial': False}


def test_picked_tags_reach_the_plan():
    assert_app_version_at_least('0.261.139')
    with stubbed_app_imports():
        from functions_orchestration_context import resolve_seeds

        seeds = resolve_seeds({
            'selected_document_ids': ['doc1'],
            'tags': ['Contracts', 'Q3'],
            'document_filter_mode': 'union',
        })
        assert seeds['tags'] == ['Contracts', 'Q3']
        assert seeds['document_filter_mode'] == 'union'
        assert resolve_seeds({'document_filter_mode': 'nonsense'})['document_filter_mode'] == ''
        assert resolve_seeds({})['tags'] == []


def test_a_tag_scopes_the_probe_rather_than_replacing_it():
    with stubbed_app_imports():
        from functions_orchestration_context import resolve_seeds, seeds_are_explicit

        assert not seeds_are_explicit(resolve_seeds({'tags': ['Contracts']}))
        assert seeds_are_explicit(resolve_seeds({'selected_document_ids': ['doc1']}))


def test_the_probe_and_the_run_filter_by_the_same_tags():
    search_fn = _function(_tree(SEARCH), 'hybrid_search')
    assert search_fn is not None
    accepted = {a.arg for a in search_fn.args.args} | {a.arg for a in search_fn.args.kwonlyargs}
    assert 'tags_filter' in accepted

    for module, function_name in ((CONTEXT, 'resolve_candidate_documents'), (ADAPTERS, 'run_document_search')):
        node = _function(_tree(module), function_name)
        assert node is not None
        passed = set()
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'hybrid_search':
                passed = {kw.arg for kw in call.keywords}
        assert passed, f'{function_name} does not call hybrid_search'
        assert not ({'tags_filter', 'document_filter_mode'} - passed)
        assert not (passed - accepted)


def test_a_picked_document_reaches_the_planner_by_name():
    with stubbed_app_imports():
        from functions_orchestration_context import resolve_candidate_documents, resolve_seeds

        seeds = resolve_seeds({
            'selected_document_ids': ['doc1', 'doc2'],
            'context_documents': [
                {'id': 'doc1', 'label': 'Q3 Contract.pdf', 'scope_kind': 'personal'},
                {'id': 'doc2', 'label': 'Q4 Contract.pdf', 'scope_kind': 'group'},
            ],
        })
        assert seeds['document_labels'] == {'doc1': 'Q3 Contract.pdf', 'doc2': 'Q4 Contract.pdf'}
        candidates, probed = resolve_candidate_documents('anything', 'user-1', seeds=seeds)
        assert not probed
        assert {c['document_id']: c['file_name'] for c in candidates} == {
            'doc1': 'Q3 Contract.pdf', 'doc2': 'Q4 Contract.pdf',
        }
        assert all(c['selected_by_user'] for c in candidates)


def test_the_name_reaches_the_approval_card():
    with stubbed_app_imports():
        from functions_orchestration_context import resolve_candidate_documents, resolve_seeds
        from functions_orchestration_schema import build_plan_inputs

        seeds = resolve_seeds({
            'selected_document_ids': ['doc1'],
            'context_documents': [{'id': 'doc1', 'label': 'Q3 Contract.pdf'}],
        })
        candidates, _ = resolve_candidate_documents('anything', 'user-1', seeds=seeds)
        labels = {c['document_id']: (c.get('title') or c.get('file_name')) for c in candidates}
        plan = {'steps': [{
            'step_id': 's1', 'capability_id': 'document_analyze', 'enabled': True,
            'arguments': {'document_ids': ['doc1', 'doc9']},
        }]}
        inputs = build_plan_inputs(plan, seeds=seeds, document_labels=labels)
        by_id = {d['document_id']: d for d in inputs['documents']}
        assert by_id['doc1']['display_name'] == 'Q3 Contract.pdf'
        assert by_id['doc1']['selected_by_user'] is True
        assert by_id['doc9']['display_name'] == 'doc9'
        assert by_id['doc9']['selected_by_user'] is False


def test_a_supplied_label_cannot_widen_access():
    node = _function(_tree('route_backend_orchestration.py'), '_authorized_document_ids')
    assert node is not None
    body = ast.dump(node)
    for label_field in ('document_labels', 'context_documents', 'label', 'file_name'):
        assert label_field not in body
    assert 'document_ids' in body


def test_found_documents_carry_their_workspace():
    node = _function(_tree(ADAPTERS), '_citations_from_search_results')
    assert node is not None
    body = ast.dump(node)
    for field in ('group_id', 'public_workspace_id'):
        assert f"'{field}'" in body


def test_analyze_can_read_sources_from_an_earlier_search_binding():
    sys.modules['functions_document_actions'] = document_action_policy_module()
    with stubbed_app_imports():
        from functions_orchestration_schema import validate_plan

        plan = validate_plan({
            'planner_contract_version': 2,
            'intent': {'summary': 'Analyse the relevant contracts'},
            'steps': [
                {'step_id': 'find', 'capability_id': 'document_search', 'arguments': {'query': 'contracts'}},
                {
                    'step_id': 'read', 'capability_id': 'document_analyze',
                    'arguments': {'analysis_prompt': 'Summarise the payment terms.'},
                    'depends_on': ['find'],
                    'inputs': {'sources': _source_input('find', 'sources')},
                },
            ],
        }, settings=_PERMISSIVE, available_capability_ids=_CAPABILITIES)
        by_id = {step['step_id']: step for step in plan['steps']}
        assert by_id['read']['inputs']['sources']['binding']['step_id'] == 'find'
        assert 'find' in by_id['read']['depends_on']
        assert by_id['find']['outputs'][1] == {'name': 'sources', 'kind': 'source-set-v1'}


def test_bad_source_bindings_are_caught_without_repair():
    sys.modules['functions_document_actions'] = document_action_policy_module()
    with stubbed_app_imports():
        from functions_orchestration_schema import PlanValidationError, validate_plan

        def analyse(binding_step, producer='web_search'):
            steps = [
                {'step_id': 'producer', 'capability_id': producer, 'arguments': {'query': 'x'}},
                {
                    'step_id': 'read', 'capability_id': 'document_analyze',
                    'arguments': {'analysis_prompt': 'Summarise.'},
                    'depends_on': ['producer'],
                    'inputs': {'sources': _source_input(binding_step, 'prepared' if producer == 'web_search' else 'sources')},
                },
            ]
            return validate_plan(
                {'planner_contract_version': 2, 'steps': steps},
                settings=_PERMISSIVE, available_capability_ids=_CAPABILITIES,
            )

        for bad_step, producer in (('producer', 'web_search'), ('read', 'document_search'), ('nonexistent', 'document_search')):
            with pytest.raises(PlanValidationError):
                analyse(bad_step, producer)


def test_runtime_source_bindings_are_reauthorized_and_limited_at_execution():
    source = _read('functions_orchestration_executor.py')
    runner = _function(ast.parse(source), '_run_dependency_step')
    assert runner is not None
    body = ast.dump(runner)
    assert 'named_sources' in body
    assert '_dependency_source_manifest' in body
    assert 'result_source_identity_ambiguous' in body
    assert 'result_source_snapshot_changed' in body


def test_executor_retains_named_results_instead_of_step_document_lists():
    with stubbed_app_imports():
        from functions_orchestration_executor import RunContext

        context = RunContext(run_id='r1', plan_id='p1', conversation_id='c1', user_id='u1', plan_contract_version=2)
        assert hasattr(context, 'task_results')
        assert hasattr(context, 'pending_results')
        assert not hasattr(context, 'merge_step_result')


if __name__ == '__main__':
    tests = [
        test_picked_tags_reach_the_plan,
        test_a_tag_scopes_the_probe_rather_than_replacing_it,
        test_the_probe_and_the_run_filter_by_the_same_tags,
        test_a_picked_document_reaches_the_planner_by_name,
        test_the_name_reaches_the_approval_card,
        test_a_supplied_label_cannot_widen_access,
        test_found_documents_carry_their_workspace,
        test_analyze_can_read_sources_from_an_earlier_search_binding,
        test_bad_source_bindings_are_caught_without_repair,
        test_runtime_source_bindings_are_reauthorized_and_limited_at_execution,
        test_executor_retains_named_results_instead_of_step_document_lists,
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
    sys.exit(0 if passed == len(tests) else 1)
