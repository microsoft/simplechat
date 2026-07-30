# route_backend_msgraph_pending_actions.py

"""Routes for user-owned Microsoft Graph pending actions."""

import logging
import re

from flask import jsonify, request

from functions_appinsights import log_event
from functions_authentication import (
    get_current_user_id,
    get_valid_access_token_for_plugins,
    login_required,
    user_required,
)
from functions_msgraph_pending_actions import (
    approve_msgraph_pending_action,
    build_pending_action_response,
    cancel_msgraph_pending_action,
    get_msgraph_pending_action,
    list_msgraph_pending_actions,
    sanitize_msgraph_pending_action_for_client,
)
from swagger_wrapper import get_auth_security, swagger_route


MSGRAPH_ACCESS_TEST_ALLOWED_SCOPES = {
    'calendars.read',
    'calendars.readwrite',
    'files.read',
    'group.read.all',
    'mail.read',
    'mail.readwrite',
    'mail.send',
    'mailboxsettings.read',
    'people.read.all',
    'securityevents.read.all',
    'user.read',
    'user.readbasic.all',
}
MSGRAPH_SCOPE_URL_PREFIX = 'https://graph.microsoft.com/'


def _error_response(error_payload, default_status=400):
    payload = error_payload if isinstance(error_payload, dict) else {}
    error_code = str(payload.get('error') or '').strip()
    status_code = default_status
    if error_code == 'not_found':
        status_code = 404
    elif error_code in {'not_logged_in', 'token_acquisition_failed'}:
        status_code = 401
    elif error_code in {'permission_denied', 'forbidden'}:
        status_code = 403

    return jsonify({
        'success': False,
        'error': error_code or 'msgraph_pending_action_failed',
        'message': payload.get('message') or 'Unable to update the Microsoft 365 action.',
        **{key: value for key, value in payload.items() if key not in {'error', 'message'}},
    }), status_code


def _normalize_access_test_scopes(raw_scopes):
    if isinstance(raw_scopes, str):
        scope_values = [scope for scope in re.split(r'[\s,;]+', raw_scopes) if scope]
    elif isinstance(raw_scopes, list):
        scope_values = raw_scopes
    else:
        scope_values = []

    normalized_scopes = []
    invalid_scopes = []
    seen_scopes = set()
    for scope in scope_values:
        normalized_scope = str(scope or '').strip()
        if not normalized_scope:
            continue
        normalized_scope_key = normalized_scope.lower()
        scope_name_key = normalized_scope_key
        if scope_name_key.startswith(MSGRAPH_SCOPE_URL_PREFIX):
            scope_name_key = scope_name_key.removeprefix(MSGRAPH_SCOPE_URL_PREFIX)
        if normalized_scope_key in seen_scopes:
            continue
        if scope_name_key not in MSGRAPH_ACCESS_TEST_ALLOWED_SCOPES:
            invalid_scopes.append(normalized_scope)
            continue
        seen_scopes.add(normalized_scope_key)
        normalized_scopes.append(normalized_scope)

    return normalized_scopes, invalid_scopes


def register_route_backend_msgraph_pending_actions(bp):
    @bp.route('/api/msgraph/test-access', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def test_user_msgraph_access():
        payload = request.get_json(silent=True) or {}
        scopes, invalid_scopes = _normalize_access_test_scopes(payload.get('scopes'))
        if invalid_scopes:
            return _error_response({
                'error': 'invalid_scopes',
                'message': 'One or more Microsoft 365 permissions are not supported for this access check.',
                'invalid_scopes': invalid_scopes,
            }, default_status=400)
        if not scopes:
            return _error_response({
                'error': 'invalid_parameters',
                'message': 'At least one Microsoft 365 permission is required to test access.',
            }, default_status=400)

        token_result = get_valid_access_token_for_plugins(scopes=scopes)
        if isinstance(token_result, dict) and token_result.get('access_token'):
            return jsonify({
                'success': True,
                'access_granted': True,
                'message': 'Microsoft 365 access verified.',
                'scopes': scopes,
            })

        error_payload = token_result if isinstance(token_result, dict) else {
            'error': 'token_acquisition_failed',
            'message': 'Microsoft 365 access could not be verified.',
        }
        error_payload.setdefault('scopes', scopes)
        error_payload.setdefault('access_granted', False)
        error_payload.setdefault(
            'message',
            'Microsoft 365 access is not available yet. Grant access in the popup, then test access again.',
        )
        return _error_response(error_payload, default_status=401)

    @bp.route('/api/msgraph/pending-actions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_user_msgraph_pending_actions():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')
        actions = list_msgraph_pending_actions(
            user_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            run_id=run_id,
            limit=100,
        )
        return jsonify({
            'success': True,
            'pending_actions': [sanitize_msgraph_pending_action_for_client(action) for action in actions],
        })


    @bp.route('/api/msgraph/pending-actions/<action_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_msgraph_pending_action(action_id):
        user_id = get_current_user_id()
        action = get_msgraph_pending_action(user_id, action_id)
        if not action:
            return _error_response({'error': 'not_found', 'message': 'Pending Microsoft 365 action was not found.'}, default_status=404)
        return jsonify(build_pending_action_response(action))


    @bp.route('/api/msgraph/pending-actions/<action_id>/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def approve_user_msgraph_pending_action(action_id):
        user_id = get_current_user_id()
        try:
            action, error = approve_msgraph_pending_action(user_id, action_id)
        except Exception as exc:
            log_event(
                f'[MSGraphPendingActionRoutes] Failed to approve pending action: {exc}',
                extra={'user_id': user_id, 'action_id': action_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return _error_response({'error': 'server_error', 'message': 'Unable to approve the Microsoft 365 action right now.'}, default_status=500)

        if error:
            return _error_response(error)
        return jsonify(build_pending_action_response(action))


    @bp.route('/api/msgraph/pending-actions/<action_id>/send-now', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def send_now_user_msgraph_pending_action(action_id):
        user_id = get_current_user_id()
        try:
            action, error = approve_msgraph_pending_action(user_id, action_id)
        except Exception as exc:
            log_event(
                f'[MSGraphPendingActionRoutes] Failed to send pending action now: {exc}',
                extra={'user_id': user_id, 'action_id': action_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return _error_response({'error': 'server_error', 'message': 'Unable to send the Microsoft 365 action right now.'}, default_status=500)

        if error:
            return _error_response(error)
        return jsonify(build_pending_action_response(action))


    @bp.route('/api/msgraph/pending-actions/<action_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def cancel_user_msgraph_pending_action(action_id):
        user_id = get_current_user_id()
        try:
            action, error = cancel_msgraph_pending_action(user_id, action_id)
        except Exception as exc:
            log_event(
                f'[MSGraphPendingActionRoutes] Failed to cancel pending action: {exc}',
                extra={'user_id': user_id, 'action_id': action_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return _error_response({'error': 'server_error', 'message': 'Unable to cancel the Microsoft 365 action right now.'}, default_status=500)

        if error:
            return _error_response(error)
        return jsonify(build_pending_action_response(action))
