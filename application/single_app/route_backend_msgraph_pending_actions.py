# route_backend_msgraph_pending_actions.py

"""Routes for user-owned Microsoft Graph pending actions."""

import logging
import re

from flask import jsonify, request
from azure.core.exceptions import AzureError

from functions_appinsights import log_event
from functions_authentication import (
    get_valid_access_token_for_plugins,
    login_required,
    user_required,
)
from functions_msgraph_pending_actions import (
    approve_msgraph_pending_action,
    build_pending_action_response,
    cancel_msgraph_pending_action,
    get_chat_pending_action_cards,
    get_msgraph_pending_action,
    get_pending_action_page,
    sanitize_msgraph_pending_action_for_client,
)
from functions_m365_context import M365PolicyError
from functions_m365_pending_delivery import authorize_pending_action_view
from m365_interaction import M365_AUTH_INTERACTION_CODES
from route_backend_m365 import _subject, validate_m365_csrf
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
    elif error_code in M365_AUTH_INTERACTION_CODES | {'not_logged_in', 'token_acquisition_failed'}:
        status_code = 401
    elif error_code in {'permission_denied', 'forbidden', 'access_denied', 'm365_principal_mismatch', 'm365_csrf_invalid', 'm365_action_not_authorized', 'm365_action_not_selected'}:
        status_code = 403
    elif error_code in {'pending_action_changed', 'delivery_in_progress', 'm365_action_review_required', 'm365_action_material_changed', 'delivery_outcome_unknown', 'delivery_failed', 'm365_context_changed', 'm365_action_changed', 'm365_workflow_changed', 'm365_execution_stopped'}:
        status_code = 409
    elif error_code == 'throttled':
        status_code = 429
    elif error_code in {'service_unavailable', 'm365_delivery_unavailable', 'm365_connection_unavailable'}:
        status_code = 503

    return jsonify({
        'success': False,
        'error': error_code or 'msgraph_pending_action_failed',
        'message': payload.get('message') or 'Unable to update the Microsoft 365 action.',
        **{key: value for key, value in payload.items() if key not in {'error', 'message'}},
    }), status_code


def _pending_exception_response(error):
    log_event(
        '[MS_GRAPH_PENDING_ACTION_ROUTES] Pending action request failed.',
        extra={'exception_type': type(error).__name__, 'error_code': getattr(error, 'code', 'pending_action_unavailable')},
        level=logging.WARNING,
    )
    if isinstance(error, M365PolicyError):
        return _error_response(error.payload)
    if isinstance(error, PermissionError):
        return _error_response({'error': 'forbidden', 'message': 'This action is not available to your account.'})
    if isinstance(error, LookupError):
        return _error_response({'error': 'not_found', 'message': 'This pending action was not found.'})
    if isinstance(error, ValueError):
        return _error_response({'error': 'invalid_parameters', 'message': 'Refresh the action card and submit a valid request.'})
    return _error_response({
        'error': 'pending_action_unavailable',
        'message': 'Pending actions could not be loaded or updated. Refresh their status before retrying.',
    }, default_status=503)


def _pending_mutation(action_id, *, cancel=False):
    try:
        user_id, _ = _subject()
        validate_m365_csrf()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {'expected_version'}:
            raise ValueError('An action revision is required.')
        version = payload.get('expected_version')
        if not isinstance(version, str) or not 1 <= len(version) <= 256:
            raise ValueError('The action revision is invalid.')
        operation = cancel_msgraph_pending_action if cancel else approve_msgraph_pending_action
        action, error = operation(user_id, action_id, expected_version=version)
        if error:
            safe_action = sanitize_msgraph_pending_action_for_client(
                action, viewer_user_id=user_id, include_full_review=True,
            ) if action else None
            return _error_response({**error, 'pending_action': safe_action})
        return jsonify(build_pending_action_response(action, viewer_user_id=user_id, include_full_review=True))
    except (M365PolicyError, PermissionError, LookupError, ValueError, AzureError) as error:
        return _pending_exception_response(error)


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
        try:
            user_id, _ = _subject()
            return jsonify(get_pending_action_page(
                user_id, conversation_id=request.args.get('conversation_id', ''),
                workflow_id=request.args.get('workflow_id', ''), run_id=request.args.get('run_id', ''),
                active_only=request.args.get('active_only', '') == '1',
                continuation_token=request.args.get('continuation_token', ''),
                limit=int(request.args.get('limit', '50')),
            ))
        except (M365PolicyError, PermissionError, LookupError, ValueError, AzureError) as error:
            return _pending_exception_response(error)


    @bp.route('/api/msgraph/pending-actions/<action_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_msgraph_pending_action(action_id):
        try:
            user_id, _ = _subject()
            conversation_id = request.args.get('conversation_id', '')
            if conversation_id:
                cards = get_chat_pending_action_cards(
                    user_id, conversation_id, action_ids=[action_id], include_full_review=True,
                )
                if not cards:
                    return _error_response({'error': 'not_found', 'message': 'Pending Microsoft 365 action was not found.'})
                return jsonify({'success': True, 'pending_action': cards[0]})
            action = get_msgraph_pending_action(user_id, action_id)
            if not action or not authorize_pending_action_view(action, user_id):
                return _error_response({'error': 'not_found', 'message': 'Pending Microsoft 365 action was not found.'})
            return jsonify(build_pending_action_response(action, viewer_user_id=user_id, include_full_review=True))
        except (M365PolicyError, PermissionError, LookupError, ValueError, AzureError) as error:
            return _pending_exception_response(error)


    @bp.route('/api/msgraph/pending-actions/<action_id>/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def approve_user_msgraph_pending_action(action_id):
        return _pending_mutation(action_id)


    @bp.route('/api/msgraph/pending-actions/<action_id>/send-now', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def send_now_user_msgraph_pending_action(action_id):
        return _pending_mutation(action_id)


    @bp.route('/api/msgraph/pending-actions/<action_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def cancel_user_msgraph_pending_action(action_id):
        return _pending_mutation(action_id, cancel=True)
