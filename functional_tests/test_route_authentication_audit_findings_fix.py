# test_route_authentication_audit_findings_fix.py
"""
Functional test for route authentication audit findings.
Version: 0.242.050
Implemented in: 0.242.050

This test ensures audited Flask routes keep runtime role decorators,
external API token guards, Swagger metadata ordering, and active-scope
authorization helpers in place.
"""

import ast
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / 'application' / 'single_app'
EXPECTED_VERSION = '0.242.050'


def _read_text(relative_path):
    return (ROOT_DIR / relative_path).read_text(encoding='utf-8')


def _decorator_name(decorator_node):
    if isinstance(decorator_node, ast.Name):
        return decorator_node.id
    if isinstance(decorator_node, ast.Attribute):
        return decorator_node.attr
    if isinstance(decorator_node, ast.Call):
        return _decorator_name(decorator_node.func)
    return None


def _route_path(decorator_node):
    if not isinstance(decorator_node, ast.Call):
        return None
    decorator_name = _decorator_name(decorator_node)
    if decorator_name != 'route':
        return None
    if not decorator_node.args or not isinstance(decorator_node.args[0], ast.Constant):
        return None
    return decorator_node.args[0].value


def _route_functions(relative_path):
    source = _read_text(relative_path)
    tree = ast.parse(source, filename=relative_path)
    functions = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        routes = [_route_path(decorator) for decorator in node.decorator_list]
        routes = [route for route in routes if route]
        if not routes:
            continue
        functions[node.name] = {
            'routes': routes,
            'decorators': [_decorator_name(decorator) for decorator in node.decorator_list],
        }
    return functions


def _assert_decorator_order(route_info, expected_decorators, function_name):
    decorators = route_info['decorators']
    for decorator in expected_decorators:
        assert decorator in decorators, f'{function_name} missing @{decorator}'

    indexes = [decorators.index(decorator) for decorator in expected_decorators]
    assert indexes == sorted(indexes), (
        f'{function_name} decorators out of order: expected {expected_decorators}, got {decorators}'
    )


def _assert_swagger_immediately_after_route(route_info, function_name):
    decorators = route_info['decorators']
    assert decorators[0] == 'route', f'{function_name} first decorator should be Flask route'
    assert decorators[1] == 'swagger_route', f'{function_name} must place swagger_route immediately after route'


def test_non_admin_routes_require_user_role():
    route_expectations = {
        'application/single_app/route_backend_agents.py': [
            'generate_agent_id',
            'get_user_agents',
            'get_assigned_knowledge_catalog_route',
            'set_user_agents',
            'delete_user_agent',
            'set_user_selected_agent',
            'get_global_agent_settings_for_users',
        ],
        'application/single_app/route_backend_agent_templates.py': [
            'list_public_agent_templates',
            'submit_agent_template',
        ],
        'application/single_app/route_backend_plugins.py': [
            'get_user_plugins',
            'set_user_plugins',
            'delete_user_plugin',
            'get_user_plugin_types',
        ],
        'application/single_app/route_backend_speech.py': [
            'transcribe_chat_audio',
        ],
        'application/single_app/route_migration.py': [
            'migrate_user_agents',
            'migrate_user_actions',
            'migrate_all_user_data',
            'get_migration_status',
        ],
        'application/single_app/route_plugin_logging.py': [
            'get_plugin_invocations',
            'get_plugin_stats',
            'get_plugin_specific_invocations',
            'export_plugin_logs',
        ],
    }

    for relative_path, function_names in route_expectations.items():
        functions = _route_functions(relative_path)
        for function_name in function_names:
            assert function_name in functions, f'Missing route function {function_name} in {relative_path}'
            _assert_decorator_order(
                functions[function_name],
                ['route', 'swagger_route', 'login_required', 'user_required'],
                function_name,
            )


def test_admin_template_routes_keep_required_order():
    functions = _route_functions('application/single_app/route_backend_agent_templates.py')
    admin_functions = [
        'admin_list_agent_templates',
        'admin_get_agent_template',
        'admin_update_agent_template',
        'admin_approve_agent_template',
        'admin_reject_agent_template',
        'admin_delete_agent_template',
    ]

    for function_name in admin_functions:
        assert function_name in functions, f'Missing admin template route {function_name}'
        _assert_decorator_order(
            functions[function_name],
            ['route', 'swagger_route', 'login_required', 'admin_required'],
            function_name,
        )


def test_swagger_metadata_and_external_api_guardrails():
    health_routes = _route_functions('application/single_app/route_external_health.py')
    _assert_swagger_immediately_after_route(
        health_routes['no_auth_external_healthcheck'],
        'no_auth_external_healthcheck',
    )

    external_routes = _route_functions('application/single_app/route_external_public_documents.py')
    external_delete = external_routes['external_delete_public_document']
    _assert_decorator_order(
        external_delete,
        ['route', 'swagger_route', 'accesstoken_required'],
        'external_delete_public_document',
    )


def test_active_scope_reads_use_authorization_helpers():
    public_documents_source = _read_text('application/single_app/route_backend_public_documents.py')
    collaboration_source = _read_text('application/single_app/route_backend_collaboration.py')

    assert 'activePublicWorkspaceOid' not in public_documents_source
    assert 'require_active_public_workspace(' in public_documents_source
    assert 'activeGroupOid' not in collaboration_source
    assert 'require_active_group(' in collaboration_source


def test_config_version_bumped_for_fix():
    config_source = (APP_DIR / 'config.py').read_text(encoding='utf-8')
    assert f'VERSION = "{EXPECTED_VERSION}"' in config_source


def main():
    tests = [
        test_non_admin_routes_require_user_role,
        test_admin_template_routes_keep_required_order,
        test_swagger_metadata_and_external_api_guardrails,
        test_active_scope_reads_use_authorization_helpers,
        test_config_version_bumped_for_fix,
    ]
    failures = []
    for test in tests:
        try:
            test()
            print(f'PASS: {test.__name__}')
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f'FAIL: {test.__name__}: {exc}')

    if failures:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())