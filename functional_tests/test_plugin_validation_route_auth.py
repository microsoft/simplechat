# test_plugin_validation_route_auth.py
"""
Functional test for plugin validation route authentication decorators.
Version: 0.241.206
Implemented in: 0.241.206

This test ensures plugin validation routes enforce the expected user and admin
authentication boundaries and prevents regression of missing route decorators.
"""

import ast
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PLUGIN_VALIDATION_FILE = ROOT_DIR / 'application' / 'single_app' / 'plugin_validation_endpoint.py'
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'
AUTH_DECORATORS = {
    'login_required',
    'user_required',
    'admin_required',
}


def read_config_version() -> str:
    """Extract the current application version from config.py."""
    for line in CONFIG_FILE.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped.startswith('VERSION = '):
            return stripped.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def get_decorator_name(decorator: ast.AST) -> str | None:
    """Return a dotted decorator name for supported AST nodes."""
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        parent_name = get_decorator_name(decorator.value)
        return f'{parent_name}.{decorator.attr}' if parent_name else decorator.attr
    if isinstance(decorator, ast.Call):
        return get_decorator_name(decorator.func)
    return None


def get_route_path(decorator: ast.AST) -> str | None:
    """Return the literal route path from a Flask route decorator."""
    if not isinstance(decorator, ast.Call):
        return None

    decorator_name = get_decorator_name(decorator.func)
    if not decorator_name or not decorator_name.endswith('.route'):
        return None

    if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
        return None

    route_path = decorator.args[0].value
    return route_path if isinstance(route_path, str) else None


def collect_plugin_validation_routes() -> dict[str, dict[str, object]]:
    """Collect route paths and runtime auth decorators from the endpoint file."""
    tree = ast.parse(PLUGIN_VALIDATION_FILE.read_text(encoding='utf-8'))
    routes = {}

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue

        route_path = None
        decorator_names = []
        for decorator in node.decorator_list:
            route_path = route_path or get_route_path(decorator)
            decorator_name = get_decorator_name(decorator)
            if decorator_name:
                decorator_names.append(decorator_name)

        if route_path:
            routes[node.name] = {
                'path': route_path,
                'auth_decorators': [
                    decorator_name
                    for decorator_name in decorator_names
                    if decorator_name in AUTH_DECORATORS
                ],
            }

    return routes


def test_plugin_validation_route_authentication_contract() -> None:
    """Plugin validation routes should require the expected runtime auth guards."""
    assert read_config_version() == '0.241.206'

    routes = collect_plugin_validation_routes()
    expected_routes = {
        'validate_plugin_manifest': {
            'path': '/api/plugins/validate',
            'auth_decorators': ['login_required', 'user_required'],
        },
        'validate_plugin_manifest_admin': {
            'path': '/api/admin/plugins/validate',
            'auth_decorators': ['login_required', 'admin_required'],
        },
        'test_plugin_instantiation': {
            'path': '/api/admin/plugins/test-instantiation',
            'auth_decorators': ['login_required', 'admin_required'],
        },
        'check_plugin_health': {
            'path': '/api/admin/plugins/health-check/<plugin_name>',
            'auth_decorators': ['login_required', 'admin_required'],
        },
        'repair_plugin': {
            'path': '/api/admin/plugins/repair/<plugin_name>',
            'auth_decorators': ['login_required', 'admin_required'],
        },
    }

    assert routes == expected_routes


if __name__ == '__main__':
    try:
        test_plugin_validation_route_authentication_contract()
        print('Plugin validation route authentication contract passed.')
        sys.exit(0)
    except Exception as exc:
        print(f'Plugin validation route authentication contract failed: {exc}')
        import traceback
        traceback.print_exc()
        sys.exit(1)