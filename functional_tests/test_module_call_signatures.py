#!/usr/bin/env python3
# test_module_call_signatures.py
"""
Functional test for calls a module makes to its own top-level functions.
Version: 0.261.483
Implemented in: 0.261.483

This test ensures that no application module calls one of its own top-level functions with an
argument that function does not take. A background spreadsheet export failed on start with a
TypeError because its caller passed semantic_checkpoint_run to
_generate_and_checkpoint_batch_window_entries, which takes the run as its first argument and
has no such parameter. The branch runs only when completion-driven checkpointing is enabled,
so no test reached it; this check reads every call without running one.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
EXPORTS = APP_ROOT / "functions_tabular_generated_exports.py"


def _parameters(definition):
    arguments = definition.args
    return [*arguments.posonlyargs, *arguments.args], arguments


def _rebound_names(tree):
    """Names that are not safely the top-level function: parameters, nested functions, assignments."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = node.args
            for argument in (
                *arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs,
                arguments.vararg, arguments.kwarg,
            ):
                if argument is not None:
                    names.add(argument.arg)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node not in tree.body:
            names.add(node.name)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def call_problems(source, checked=None):
    """Calls that cannot bind to the one top-level definition of the function they name."""
    tree = ast.parse(source)
    definitions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.setdefault(node.name, []).append(node)
    rebound = _rebound_names(tree)
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        # A decorator may change the signature, and a name defined twice or rebound is not
        # known to be this function; none of those is judged here.
        if name not in definitions or len(definitions[name]) != 1 or name in rebound:
            continue
        definition = definitions[name][0]
        if definition.decorator_list:
            continue
        if checked is not None:
            checked.add(name)
        positional, arguments = _parameters(definition)
        accepted = {argument.arg for argument in (*arguments.args, *arguments.kwonlyargs)}
        unpacked = any(isinstance(argument, ast.Starred) for argument in node.args) or any(
            keyword.arg is None for keyword in node.keywords
        )
        if arguments.kwarg is None:
            problems.extend(
                (node.lineno, name, f"unknown keyword {keyword.arg}")
                for keyword in node.keywords if keyword.arg is not None and keyword.arg not in accepted
            )
        if unpacked:
            continue
        if arguments.vararg is None and len(node.args) > len(positional):
            problems.append((node.lineno, name, f"{len(node.args)} positional, takes {len(positional)}"))
        by_position = {argument.arg for argument in positional[:len(node.args)]}
        problems.extend(
            (node.lineno, name, f"{keyword.arg} given twice")
            for keyword in node.keywords if keyword.arg in by_position
        )
        supplied = by_position | {keyword.arg for keyword in node.keywords}
        required = [argument.arg for argument in positional[:len(positional) - len(arguments.defaults)]]
        required += [
            argument.arg for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
            if default is None
        ]
        problems.extend(
            (node.lineno, name, f"missing {argument}") for argument in required if argument not in supplied
        )
    return problems


def test_the_check_reports_each_kind_of_call_that_cannot_bind():
    """The check itself: each kind of mismatch is reported, and a valid call is not."""
    print("Testing the call check on known mismatches...")
    source = (
        "def target(run, total, *, plan=None):\n    return run\n"
        "def flexible(*values, **options):\n    return values\n"
        "def caller(run, local):\n"
        "    target(run, 1, plan=2)\n"
        "    target(run, 1, checkpoint_run=run)\n"
        "    target(run, 1, 2)\n"
        "    target(run)\n"
        "    target(run, 1, run=run)\n"
        "    flexible(1, 2, anything=3)\n"
        "    target(*local)\n"
        "    local(unknown=1)\n"
    )
    assert sorted(problem for _line, _name, problem in call_problems(source)) == [
        "3 positional, takes 2", "missing total", "run given twice", "unknown keyword checkpoint_run",
    ]
    print("Call check test passed!")
    return True


def test_the_background_export_calls_its_batch_window_generators_with_arguments_they_take():
    """0.261.483: the export module, and the two generators its processor chooses between."""
    print("Testing the export module's calls to its own functions...")
    checked = set()
    problems = call_problems(EXPORTS.read_text(encoding="utf-8"), checked)
    assert not problems, problems
    # Both generators were found and judged, so an empty result is not a vacuous one.
    assert {"_generate_and_checkpoint_batch_window_entries", "_generate_batch_window_entries"} <= checked
    print("Export call test passed!")
    return True


def test_no_application_module_calls_its_own_function_with_an_argument_it_does_not_take():
    print("Testing every application module's calls to its own functions...")
    problems, modules = [], 0
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        modules += 1
        problems.extend(
            f"{path.relative_to(APP_ROOT).as_posix()}:{line}: {name}: {problem}"
            for line, name, problem in call_problems(path.read_text(encoding="utf-8"))
        )
    assert modules > 100, modules
    assert not problems, "\n".join(problems)
    print(f"Call test passed for {modules} modules!")
    return True


if __name__ == "__main__":
    tests = [
        test_the_check_reports_each_kind_of_call_that_cannot_bind,
        test_the_background_export_calls_its_batch_window_generators_with_arguments_they_take,
        test_no_application_module_calls_its_own_function_with_an_argument_it_does_not_take,
    ]
    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)
    sys.exit(0 if all(results) else 1)
