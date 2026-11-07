# route_backend_conversation_handoffs.py
"""Authenticated HTTP routes for durable private-conversation handoffs (issue #1835)."""

import logging

from azure.core.exceptions import AzureError
from flask import jsonify, request

from content_screening.contracts import ScreeningError
from functions_appinsights import log_event
from functions_authentication import get_current_user_id, login_required, user_required
from functions_conversation_handoff_generation import resolve_handoff_destination
from functions_conversation_handoff_runtime import get_handoff_service
from functions_conversation_handoffs import ConversationHandoffError, public_handoff
from functions_conversation_references import ConversationReferenceError
from swagger_wrapper import get_auth_security, swagger_route


def _no_store_json(payload, status_code=200):
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response, status_code


def _handoff_error_response(error):
    if isinstance(error, (ConversationHandoffError, ConversationReferenceError, ScreeningError)):
        return _no_store_json(
            {'error': error.public_message, 'code': error.code},
            error.status_code,
        )
    log_event(
        '[CONVERSATION_HANDOFF] Conversation handoff request failed.',
        extra={'error_type': type(error).__name__},
        level=logging.ERROR,
    )
    return _no_store_json(
        {
            'error': 'Conversation handoff is temporarily unavailable.',
            'code': 'conversation_handoff_unavailable',
        },
        503,
    )


def register_route_backend_conversation_handoffs(
    bp,
    *,
    service_factory=get_handoff_service,
    destination_resolver=resolve_handoff_destination,
):
    @bp.route('/api/conversation-handoffs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_conversation_handoffs_api():
        user_id = get_current_user_id()
        if not user_id:
            return _no_store_json({'error': 'User not authenticated.', 'code': 'unauthenticated'}, 401)
        try:
            conversation_id = request.args.get('conversation_id')
            destination_preview_id = request.args.get('destination_preview_id')
            service = service_factory()
            if conversation_id is not None or not destination_preview_id:
                jobs = service.list(user_id, conversation_id)
                payload = {'handoffs': [public_handoff(job) for job in jobs]}
            else:
                payload = {'handoffs': []}
            if destination_preview_id:
                payload['destination_config'] = destination_resolver(user_id, destination_preview_id)
            return _no_store_json(payload)
        except (ConversationHandoffError, ConversationReferenceError, ScreeningError, AzureError, Exception) as error:
            return _handoff_error_response(error)

    @bp.route('/api/conversation-handoffs/destination/<destination_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def preview_conversation_handoff_destination_api(destination_id):
        user_id = get_current_user_id()
        if not user_id:
            return _no_store_json({'error': 'User not authenticated.', 'code': 'unauthenticated'}, 401)
        try:
            config = destination_resolver(user_id, destination_id)
            return _no_store_json({'destination_config': config})
        except (ConversationHandoffError, ConversationReferenceError, ScreeningError, AzureError, Exception) as error:
            return _handoff_error_response(error)

    @bp.route('/api/conversation-handoffs', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def create_conversation_handoff_api():
        user_id = get_current_user_id()
        if not user_id:
            return _no_store_json({'error': 'User not authenticated.', 'code': 'unauthenticated'}, 401)
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ConversationHandoffError('invalid_request', 'A JSON request body is required.', 400)
            service = service_factory()
            job = service.enqueue(
                user_id,
                data.get('source_conversation_id'),
                data.get('destination_conversation_id'),
                data.get('instruction'),
                references=data.get('conversation_references'),
                request_id=data.get('request_id'),
                destination_config_revision=data.get('destination_config_revision'),
            )
            if job.get('status') == 'queued':
                try:
                    dispatched = service.dispatch(job['destination_conversation_id'])
                    if isinstance(dispatched, dict) and dispatched.get('id') == job['id']:
                        job = dispatched
                    else:
                        job = service.get(user_id, job['destination_conversation_id'], job['id'])
                except ConversationHandoffError as error:
                    if error.code not in ('destination_busy', 'destination_needs_attention'):
                        raise
            return _no_store_json({'handoff': public_handoff(job)})
        except (ConversationHandoffError, ConversationReferenceError, ScreeningError, AzureError, Exception) as error:
            return _handoff_error_response(error)

    @bp.route('/api/conversation-handoffs/<handoff_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_handoff_api(handoff_id):
        user_id = get_current_user_id()
        if not user_id:
            return _no_store_json({'error': 'User not authenticated.', 'code': 'unauthenticated'}, 401)
        try:
            destination_conversation_id = request.args.get('destination_conversation_id')
            service = service_factory()
            job = service.get(user_id, destination_conversation_id, handoff_id)
            return _no_store_json({'handoff': public_handoff(job)})
        except (ConversationHandoffError, ConversationReferenceError, ScreeningError, AzureError, Exception) as error:
            return _handoff_error_response(error)

    @bp.route('/api/conversation-handoffs/<handoff_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def cancel_conversation_handoff_api(handoff_id):
        user_id = get_current_user_id()
        if not user_id:
            return _no_store_json({'error': 'User not authenticated.', 'code': 'unauthenticated'}, 401)
        try:
            data = request.get_json(silent=True)
            if data is None and not request.get_data():
                data = {}
            if not isinstance(data, dict):
                raise ConversationHandoffError('invalid_request', 'A JSON request body is required.', 400)
            destination_conversation_id = (
                data.get('destination_conversation_id')
                or request.args.get('destination_conversation_id')
            )
            service = service_factory()
            job = service.cancel(user_id, destination_conversation_id, handoff_id)
            return _no_store_json({'handoff': public_handoff(job)})
        except (ConversationHandoffError, ConversationReferenceError, ScreeningError, AzureError, Exception) as error:
            return _handoff_error_response(error)
