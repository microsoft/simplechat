# test_workflow_document_selection_policy.py
"""
Task document preview policy and response tests.
Version: 0.261.329
Implemented in: 0.261.329

Runs the real route helper and authorized selection service on a closed Flask
app and the existing paged document catalog fixture. No workflow/model writes.
"""

import ast
import logging
import sys
import time
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
sys.path.insert(0, str(ROOT / 'functional_tests'))

from functions_workflow_runtime_store import RuntimeUnavailable
from test_workflow_document_selection import action, catalog, predicate
from test_workflow_document_picker_recent_targets import document_actions_over_stubs

ROUTES = ROOT / 'application' / 'single_app' / 'route_backend_workflows.py'


def test_preview_routes_keep_exact_scope_and_swagger_policies():
    tree = ast.parse(ROUTES.read_text(encoding='utf-8'))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'register_route_backend_workflows')
    paths = []
    for node in registrar.body:
        if not isinstance(node, ast.FunctionDef) or not node.decorator_list:
            continue
        route = node.decorator_list[0]
        if not isinstance(route, ast.Call) or not route.args[0].value.endswith('/document-selection/preview'):
            continue
        paths.append(route.args[0].value)
        decorators = [ast.unparse(value) for value in node.decorator_list]
        assert ast.unparse(route.func) == 'bp.route'
        assert decorators[1] == 'swagger_route(security=get_auth_security())'
        assert 'login_required' in decorators and 'user_required' in decorators
        if '/user/' in paths[-1]:
            assert "enabled_required('allow_user_workflows')" in decorators
            assert 'workflow_user_required' in decorators
        else:
            assert "enabled_required('enable_group_workspaces')" in decorators
            assert "enabled_required('allow_group_workflows')" in decorators
    assert len(paths) == 2


@pytest.fixture
def preview_api(catalog):
    access = {'personal': True, 'group': True}

    def personal_access(_settings):
        if not access['personal']:
            raise PermissionError

    def group_access(_user):
        if not access['group']:
            raise PermissionError
        assert request.args['group_id'] == 'group-1'
        return 'group-1', catalog.settings

    namespace = {
        'request': request, 'jsonify': jsonify, 'logging': logging, 'AzureError': AzureError,
        'RuntimeUnavailable': RuntimeUnavailable, 'get_current_user_id': lambda: 'owner',
        'get_settings': lambda: catalog.settings, '_assert_personal_workflow_draft_access': personal_access,
        '_resolve_active_group_for_workflow_management': group_access, 'log_event': lambda *_args, **_kwargs: None,
    }
    node = next(node for node in ast.parse(ROUTES.read_text(encoding='utf-8')).body
                if isinstance(node, ast.FunctionDef) and node.name == '_workflow_document_selection_preview_response')
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROUTES), 'exec'), namespace)
    app = Flask('document-selection-preview')
    app.add_url_rule('/user', endpoint='personal', view_func=lambda: namespace[node.name](), methods=['POST'])
    app.add_url_rule('/group', endpoint='group', view_func=lambda: namespace[node.name](group=True), methods=['POST'])
    with document_actions_over_stubs():
        yield app.test_client(), catalog, access


def preview_payload(config=None):
    config = config or action()
    return {key: config[key] for key in ('type', 'recent_window_minutes', 'document_selection')}


def test_exact_preview_returns_only_safe_advisory_metadata(preview_api):
    client, catalog, _ = preview_api
    catalog.add_document('one', file_name='Tim.pdf', _ts=int(time.time()))
    response = client.post('/user', json=preview_payload(action(predicate())))
    assert response.status_code == 200 and response.json['count'] == 1
    assert response.json['advisory'] is True and response.json['count_exact'] is True
    encoded = response.get_data(as_text=True)
    for sensitive in ('PRIVATE-STORAGE-PATH', 'PRIVATE-SECRET', 'blob_path', 'provenance', 'settings'):
        assert sensitive not in encoded


def test_access_denials_and_explicit_group_scope_precede_document_reads(preview_api):
    client, catalog, access = preview_api
    access['personal'] = False
    refused = client.post('/user', json=preview_payload())
    assert refused.status_code == 403 and catalog.index.requests == []
    assert client.post('/group', json=preview_payload()).status_code == 400
    access['group'] = False
    assert client.post('/group?group_id=group-1', json=preview_payload()).status_code == 403
    assert catalog.index.requests == []


def test_group_workflow_cannot_preview_other_workspaces(preview_api):
    client, catalog, _ = preview_api
    invalid = client.post('/group?group_id=group-1', json=preview_payload())
    assert invalid.status_code == 422 and catalog.index.requests == []
    catalog.add_document('one', scope='group', _ts=int(time.time()))
    valid = client.post('/group?group_id=group-1', json=preview_payload(
        action(scopes=[{'scope_type': 'group', 'scope_id': 'group-1'}]),
    ))
    assert valid.status_code == 200 and valid.json['count'] == 1


def test_invalid_regex_and_incomplete_catalog_are_not_reported_as_empty(preview_api):
    client, catalog, _ = preview_api
    invalid = client.post('/user', json=preview_payload(action(predicate(operator='regex', value='['))))
    assert invalid.status_code == 400 and invalid.json['code'] == 'document_selection_regex_invalid'
    catalog.index.incomplete = True
    incomplete = client.post('/user', json=preview_payload())
    assert incomplete.status_code == 422 and incomplete.json.get('count') is None
    assert incomplete.json.get('count_exact') is not True
    assert client.post('/user', json={'user_id': 'another-user', **preview_payload()}).status_code == 400


def test_over_limit_preview_reports_a_lower_bound_not_a_partial_match_set(preview_api):
    client, catalog, _ = preview_api
    empty = client.post('/user', json=preview_payload())
    limit = empty.json['limit']
    for index in range(limit + 1):
        catalog.add_document(f'doc-{index}', _ts=int(time.time()))
    response = client.post('/user', json=preview_payload())
    assert response.status_code == 422 and response.json['code'] == 'document_selection_limit_exceeded'
    assert response.json['count'] == limit + 1 and response.json['count_exact'] is False
    assert 'items' not in response.json
