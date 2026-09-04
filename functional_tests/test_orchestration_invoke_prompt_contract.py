#!/usr/bin/env python3
"""
Functional test for the orchestration invoke_prompt calling convention.
Version: 0.261.086
Implemented in: 0.261.086

A run failed in production with:

    invoke_prompt() got an unexpected keyword argument 'stage'

The adapters call the model through a closure the route supplies, and the shape of that
call is not the route's to choose: ``run_document_analysis``, ``run_document_comparison``
and the respond adapter all invoke it as ``invoke_prompt(prompt, stage=..., metadata=...)``,
the convention ``functions_workflow_runner.invoke_model_prompt`` established. The route
built a closure taking ``(messages, max_tokens, temperature)`` instead.

Nothing caught it. The executor tests drive fake adapters, so they never cross that seam,
and every real adapter needs Azure to run. The mismatch therefore survived import,
type-checking and the whole suite, and failed only when a real step ran -- taking respond,
document_analyze and document_compare with it, which is every capability that reasons.

This test closes that hole by checking the contract itself rather than the behaviour behind
it: the route's closure must accept what the callers actually pass.
"""

import ast
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import APP_ROOT  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

# The convention every existing caller follows.
REQUIRED_PARAMETERS = ('stage', 'metadata')


def _read(module):
    with open(os.path.join(APP_ROOT, module), encoding='utf-8') as handle:
        return handle.read()


def _call_keywords(source, function_name):
    """Every keyword argument any call to ``function_name`` passes, across a module."""
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


def _find_function(source, name, within=None):
    """Locate a function definition, optionally nested inside another."""
    tree = ast.parse(source)
    scope = tree
    if within:
        scope = next(
            (
                node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == within
            ),
            None,
        )
        assert scope is not None, f"{within} not found"
    for node in ast.walk(scope):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _accepted_parameters(function_node):
    """Parameter names a definition accepts, including **kwargs if it takes one."""
    args = function_node.args
    names = {arg.arg for arg in args.args}
    names |= {arg.arg for arg in args.kwonlyargs}
    if args.vararg:
        names.add('*')
    if args.kwarg:
        names.add('**')
    return names


def test_route_closure_accepts_what_callers_pass():
    """The route's invoke_prompt must accept `stage` and `metadata`.

    Checked statically rather than by calling it. The route imports the Cosmos containers
    at module scope, so importing it needs Azure -- which is precisely why nothing caught
    this the first time. A source-level check has no such dependency and cannot be skipped
    on a developer machine.
    """
    print("Testing the orchestration invoke_prompt signature...")
    try:
        source = _read('route_backend_orchestration.py')
        closure = _find_function(source, 'invoke_prompt', within='_build_invoke_prompt')
        assert closure is not None, (
            "_build_invoke_prompt must define an invoke_prompt closure"
        )

        accepted = _accepted_parameters(closure)
        for name in REQUIRED_PARAMETERS:
            assert name in accepted or '**' in accepted, (
                f"invoke_prompt must accept '{name}': run_document_analysis, "
                f"run_document_comparison and the respond adapter all pass it, following "
                f"functions_workflow_runner.invoke_model_prompt. Accepted: {sorted(accepted)}"
            )

        # The prompt itself is positional, because the document functions pass it that way.
        positional = [arg.arg for arg in closure.args.args]
        assert positional and positional[0] not in REQUIRED_PARAMETERS, (
            f"the prompt must be the first positional parameter, saw {positional}"
        )

        print(f"  ok  invoke_prompt accepts {sorted(accepted)}")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_adapters_only_pass_supported_keywords():
    """No adapter may invent a keyword the route's closure does not declare."""
    print("Testing the adapter call sites against the closure...")
    try:
        passed = _call_keywords(_read('functions_orchestration_adapters.py'), 'invoke_prompt')

        closure = _find_function(
            _read('route_backend_orchestration.py'),
            'invoke_prompt',
            within='_build_invoke_prompt',
        )
        accepted = _accepted_parameters(closure)

        if '**' not in accepted:
            unsupported = sorted(passed - accepted)
            assert not unsupported, (
                f"adapters pass keyword(s) the route's closure does not accept: "
                f"{unsupported}. This fails only when a real step runs, so it has to be "
                f"caught here."
            )
        print(f"  ok  adapters pass {sorted(passed) or 'no keywords'}, all accepted")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_token_usage_is_accumulated():
    """A run's cost must be counted, since every model call passes through one closure."""
    print("Testing that the closure accumulates token usage...")
    try:
        source = _read('route_backend_orchestration.py')
        builder = _find_function(source, '_build_invoke_prompt')
        assert builder is not None

        accepted = _accepted_parameters(builder)
        assert 'token_usage' in accepted, (
            "_build_invoke_prompt must take a token_usage accumulator; without one a run "
            "reports zero cost because nothing counted it, not because it was free"
        )

        body = ast.dump(builder)
        for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            assert field in body, f"the closure should accumulate {field}"

        print("  ok  the closure accumulates prompt, completion and total tokens")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_document_functions_agree_on_the_convention():
    """The convention is repo-wide, so confirm the document functions still use it."""
    print("Testing the document analysis and comparison call sites...")
    try:
        for module in ('functions_document_analysis.py', 'functions_document_comparison.py'):
            keywords = _call_keywords(_read(module), 'invoke_prompt')
            if not keywords:
                # Comparison delegates to analysis on some paths; an absence of direct
                # calls is fine, a contradictory call is not.
                continue
            for name in REQUIRED_PARAMETERS:
                assert name in keywords, (
                    f"{module} calls invoke_prompt without '{name}'; the orchestration "
                    f"closure is built to this convention and would drift from it"
                )
        print("  ok  the document functions still call with stage and metadata")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.261.086")

    tests = [
        test_route_closure_accepts_what_callers_pass,
        test_adapters_only_pass_supported_keywords,
        test_token_usage_is_accumulated,
        test_document_functions_agree_on_the_convention,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
