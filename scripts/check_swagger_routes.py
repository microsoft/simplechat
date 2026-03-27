# check_swagger_routes.py

"""Validate that changed Flask route files include authenticated swagger decorators."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def get_name(node: ast.AST | None) -> str | None:
    """Return a dotted name for supported AST node types."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = get_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return get_name(node.func)
    return None


def is_route_decorator(node: ast.AST) -> bool:
    """Return True when the decorator is a Flask route decorator."""
    return isinstance(node, ast.Call) and bool(get_name(node.func) and get_name(node.func).endswith('.route'))


def is_exact_swagger_decorator(node: ast.AST) -> bool:
    """Return True when the decorator matches swagger_route(security=get_auth_security())."""
    if not isinstance(node, ast.Call):
        return False

    if get_name(node.func) != 'swagger_route':
        return False

    if len(node.keywords) != 1:
        return False

    keyword = node.keywords[0]
    if keyword.arg != 'security' or not isinstance(keyword.value, ast.Call):
        return False

    return get_name(keyword.value.func) == 'get_auth_security'


def iter_route_issues(file_path: Path) -> list[str]:
    """Inspect one file and return any swagger integration violations."""
    try:
        relative_path = file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        relative_path = file_path.as_posix()
    source = file_path.read_text(encoding='utf-8')

    if '.route(' not in source:
        return []

    tree = ast.parse(source, filename=str(file_path))
    issues: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        route_indexes = [index for index, decorator in enumerate(node.decorator_list) if is_route_decorator(decorator)]
        if not route_indexes:
            continue

        swagger_indexes = [index for index, decorator in enumerate(node.decorator_list) if is_exact_swagger_decorator(decorator)]
        if not swagger_indexes:
            issues.append(
                f"::error file={relative_path},line={node.lineno}::"
                f"Route function '{node.name}' is missing @swagger_route(security=get_auth_security())."
            )
            continue

        expected_index = route_indexes[-1] + 1
        if swagger_indexes[0] != expected_index:
            issues.append(
                f"::error file={relative_path},line={node.lineno}::"
                f"Route function '{node.name}' must place @swagger_route(security=get_auth_security()) immediately after the route decorator."
            )

    return issues


def normalize_paths(paths: list[str]) -> list[Path]:
    """Resolve CLI paths relative to the repository root and keep existing Python files."""
    normalized: list[Path] = []
    for raw_path in paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        if candidate.exists() and candidate.suffix == '.py':
            normalized.append(candidate)
    return normalized


def main() -> int:
    """Run the swagger route validation for the provided files."""
    parser = argparse.ArgumentParser(description='Validate swagger decorators on changed Flask route files.')
    parser.add_argument('files', nargs='*', help='Python files to validate relative to the repository root.')
    args = parser.parse_args()

    files = normalize_paths(args.files)

    if not files:
        print('No changed Python files to validate for swagger route coverage.')
        return 0

    all_issues: list[str] = []
    checked_files = 0

    for file_path in files:
        issues = iter_route_issues(file_path)
        if '.route(' in file_path.read_text(encoding='utf-8'):
            checked_files += 1
        all_issues.extend(issues)

    if checked_files == 0:
        print('Changed Python files do not define Flask routes. Swagger route check skipped.')
        return 0

    if all_issues:
        print('Swagger route validation failed:')
        for issue in all_issues:
            print(issue)
        return 1

    print(f'Swagger route validation passed for {checked_files} changed route file(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())