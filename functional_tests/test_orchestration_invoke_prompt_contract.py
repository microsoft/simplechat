#!/usr/bin/env python3
# test_orchestration_invoke_prompt_contract.py
"""
Functional test for the orchestration invoke_prompt calling convention.
Version: 0.261.139
Implemented in: 0.261.086
Single orchestration contract updated in: 0.261.139

Adapters and composition call the model as ``invoke_prompt(messages_or_prompt,
stage=..., metadata=...)``. The route-level builder from the removed legacy path is gone;
the active Gather / Reason / Render execution path binds the same convention in
``functions_orchestration_execution.build_harness_invoke_prompt``.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

REQUIRED_PARAMETERS = ('stage', 'metadata')


def _read(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return handle.read()


def _call_keywords(source, function_name):
    keywords = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = getattr(target, 'id', None) or getattr(target, 'attr', None)
        if name != function_name:
            continue
        for keyword in node.keywords:
            if keyword.arg:
                keywords.add(keyword.arg)
    return keywords


def _find_function(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _nested_function(source, outer, inner):
    parent = _find_function(source, outer)
    assert parent is not None, f'{outer} not found'
    for node in ast.walk(parent):
        if isinstance(node, ast.FunctionDef) and node.name == inner:
            return node
    return None


def _accepted_parameters(function_node):
    args = function_node.args
    names = {arg.arg for arg in args.args}
    names |= {arg.arg for arg in args.kwonlyargs}
    if args.kwarg:
        names.add('**')
    return names


def test_execution_invoke_prompt_accepts_adapter_convention():
    source = _read('functions_orchestration_execution.py')
    closure = _nested_function(source, 'build_harness_invoke_prompt', 'invoke_prompt')
    assert closure is not None
    accepted = _accepted_parameters(closure)
    for name in REQUIRED_PARAMETERS:
        assert name in accepted or '**' in accepted
    positional = [arg.arg for arg in closure.args.args]
    assert positional and positional[0] not in REQUIRED_PARAMETERS


def test_active_callers_only_pass_supported_keywords():
    execution = _read('functions_orchestration_execution.py')
    closure = _nested_function(execution, 'build_harness_invoke_prompt', 'invoke_prompt')
    accepted = _accepted_parameters(closure)
    passed = _call_keywords(_read('functions_orchestration_composition.py'), 'invoke')
    if '**' not in accepted:
        assert not (passed - accepted)
    assert {'stage', 'metadata'} <= passed


def test_token_usage_is_accumulated_in_active_builder():
    builder = _find_function(_read('functions_orchestration_execution.py'), 'build_harness_invoke_prompt')
    assert builder is not None
    accepted = _accepted_parameters(builder)
    assert 'token_usage' in accepted
    body = ast.dump(builder)
    assert '_USAGE_FIELDS' in body
    assert 'token_usage' in body


def test_document_functions_agree_on_the_convention():
    for module in ('functions_document_analysis.py', 'functions_document_comparison.py'):
        keywords = _call_keywords(_read(module), 'invoke_prompt')
        if not keywords:
            continue
        for name in REQUIRED_PARAMETERS:
            assert name in keywords, f'{module} calls invoke_prompt without {name}'


def _run_script():
    assert_app_version_at_least('0.261.139')
    tests = [
        test_execution_invoke_prompt_accepts_adapter_convention,
        test_active_callers_only_pass_supported_keywords,
        test_token_usage_is_accumulated_in_active_builder,
        test_document_functions_agree_on_the_convention,
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
