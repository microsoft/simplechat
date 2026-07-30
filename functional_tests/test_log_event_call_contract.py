#!/usr/bin/env python3
# test_log_event_call_contract.py
"""
Functional test for the application-wide log_event call contract.
Version: 0.250.101
Implemented in: 0.250.101

This test ensures application callers cannot pass explicit keyword arguments
that functions_appinsights.log_event does not accept.
"""

import ast
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLICATION_ROOT = os.path.join(REPO_ROOT, 'application')
LOGGING_MODULE_PATH = os.path.join(
    APPLICATION_ROOT,
    'single_app',
    'functions_appinsights.py',
)


def _parse_python_file(file_path):
    """Parse a Python source file and retain its path in syntax errors."""
    with open(file_path, 'r', encoding='utf-8-sig') as file_handle:
        return ast.parse(file_handle.read(), filename=file_path)


def _get_log_event_contract():
    """Derive accepted keyword names and positional capacity from the function."""
    logging_tree = _parse_python_file(LOGGING_MODULE_PATH)
    for node in logging_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'log_event':
            positional_parameters = [
                argument.arg
                for argument in [*node.args.posonlyargs, *node.args.args]
            ]
            keyword_parameters = {
                *positional_parameters,
                *(argument.arg for argument in node.args.kwonlyargs),
            }
            return keyword_parameters, len(positional_parameters)

    raise AssertionError(f'Could not find log_event() in {LOGGING_MODULE_PATH}')


def _get_log_event_aliases(tree):
    """Collect direct-function and module aliases that resolve to log_event."""
    function_aliases = set()
    module_aliases = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').endswith('functions_appinsights'):
            for imported_name in node.names:
                if imported_name.name in {'log_event', '*'}:
                    function_aliases.add(imported_name.asname or imported_name.name)
        elif isinstance(node, ast.Import):
            for imported_name in node.names:
                if imported_name.name.endswith('functions_appinsights'):
                    module_aliases.add(imported_name.asname or imported_name.name.split('.')[0])

    return function_aliases, module_aliases


def _is_log_event_call(call_node, function_aliases, module_aliases):
    """Return whether an AST call resolves to the shared logging entry point."""
    if isinstance(call_node.func, ast.Name):
        return (
            call_node.func.id == 'log_event'
            and ('log_event' in function_aliases or '*' in function_aliases)
        ) or call_node.func.id in function_aliases

    return (
        isinstance(call_node.func, ast.Attribute)
        and call_node.func.attr == 'log_event'
        and isinstance(call_node.func.value, ast.Name)
        and call_node.func.value.id in module_aliases
    )


def _iter_application_python_files():
    """Yield every production Python file in stable order."""
    for directory_path, directory_names, file_names in os.walk(APPLICATION_ROOT):
        directory_names[:] = sorted(
            directory_name
            for directory_name in directory_names
            if directory_name != '__pycache__'
        )
        for file_name in sorted(file_names):
            if file_name.endswith('.py'):
                yield os.path.join(directory_path, file_name)


def find_log_event_contract_violations():
    """Return explicit log_event calls that cannot match the current signature."""
    accepted_keywords, positional_limit = _get_log_event_contract()
    violations = []

    for file_path in _iter_application_python_files():
        tree = _parse_python_file(file_path)
        function_aliases, module_aliases = _get_log_event_aliases(tree)
        if not function_aliases and not module_aliases:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_log_event_call(node, function_aliases, module_aliases):
                continue

            relative_path = os.path.relpath(file_path, REPO_ROOT)
            unsupported_keywords = sorted(
                keyword.arg
                for keyword in node.keywords
                if keyword.arg is not None and keyword.arg not in accepted_keywords
            )
            if unsupported_keywords:
                violations.append(
                    f"{relative_path}:{node.lineno}: unsupported keyword(s): "
                    f"{', '.join(unsupported_keywords)}"
                )

            explicit_positional_count = sum(
                not isinstance(argument, ast.Starred)
                for argument in node.args
            )
            if explicit_positional_count > positional_limit:
                violations.append(
                    f"{relative_path}:{node.lineno}: "
                    f"{explicit_positional_count} positional arguments exceed "
                    f"the supported limit of {positional_limit}"
                )

    return violations


def test_application_log_event_calls_match_signature():
    """Reject application log_event calls with unsupported explicit arguments."""
    violations = find_log_event_contract_violations()
    assert not violations, (
        'Invalid functions_appinsights.log_event() call signatures:\n'
        + '\n'.join(violations)
    )


if __name__ == '__main__':
    try:
        test_application_log_event_calls_match_signature()
        print('Application log_event call contract passed')
        sys.exit(0)
    except Exception as exc:
        print(f'Application log_event call contract failed: {exc}')
        sys.exit(1)
