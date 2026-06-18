#!/usr/bin/env python3
# test_tabular_kernel_parameter_annotations.py
"""
Functional test for tabular SK Python 3.13 kernel parameter annotations.
Version: 0.242.071
Implemented in: 0.242.068

This test ensures public Semantic Kernel tabular tool parameters avoid
Annotated[Optional[str], ...] so tool-call argument parsing remains compatible
with both Python 3.12 and Python 3.13.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'semantic_kernel_plugins',
    'tabular_processing_plugin.py',
)
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')


def read_text(path):
    """Read a UTF-8 text file."""
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    """Read the current application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"\'')
    raise AssertionError('VERSION assignment not found in config.py')


def decorator_is_kernel_function(decorator):
    """Return True when an AST decorator is @kernel_function(...)."""
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    return isinstance(decorator, ast.Name) and decorator.id == 'kernel_function'


def annotation_is_annotated_optional_str(annotation):
    """Return True for Annotated[Optional[str], ...] annotations."""
    if not isinstance(annotation, ast.Subscript):
        return False
    if not isinstance(annotation.value, ast.Name) or annotation.value.id != 'Annotated':
        return False

    annotation_slice = annotation.slice
    if isinstance(annotation_slice, ast.Tuple):
        first_argument = annotation_slice.elts[0]
    else:
        first_argument = annotation_slice

    if not isinstance(first_argument, ast.Subscript):
        return False
    if not isinstance(first_argument.value, ast.Name) or first_argument.value.id != 'Optional':
        return False

    optional_slice = first_argument.slice
    return isinstance(optional_slice, ast.Name) and optional_slice.id == 'str'


def test_kernel_function_parameters_do_not_use_optional_str_annotations():
    """Validate public SK tool parameters use concrete str annotations."""
    print('🔍 Testing tabular kernel parameter annotations...')

    try:
        parsed = ast.parse(read_text(PLUGIN_FILE), filename=PLUGIN_FILE)
        violations = []

        for node in ast.walk(parsed):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(decorator_is_kernel_function(decorator) for decorator in node.decorator_list):
                continue

            for argument in node.args.args:
                if argument.arg == 'self':
                    continue
                if annotation_is_annotated_optional_str(argument.annotation):
                    violations.append(f'{node.name}.{argument.arg}')

        assert not violations, f'Kernel function parameters cannot use Annotated[Optional[str], ...]: {violations}'
        assert read_config_version() == '0.242.071'

        print('✅ Tabular kernel parameter annotations passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_kernel_function_parameters_do_not_use_optional_str_annotations,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
