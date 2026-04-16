# route_backend_thoughts.py

from flask import request, jsonify
from config import CosmosResourceNotFoundError
from functions_authentication import login_required, user_required, get_current_user_id
from functions_collaboration import (
    assert_user_can_view_collaboration_conversation,
    get_accessible_collaboration_message_thoughts,
    get_collaboration_conversation,
    get_collaboration_message,
)
from functions_settings import get_settings
from functions_thoughts import get_thoughts_for_message, get_pending_thoughts
from swagger_wrapper import swagger_route, get_auth_security
from functions_appinsights import log_event


def register_route_backend_thoughts(app):

    @app.route('/api/conversations/<conversation_id>/messages/<message_id>/thoughts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_message_thoughts(conversation_id, message_id):
        """Return persisted thoughts for a specific assistant message."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_settings()
        if not settings.get('enable_thoughts', True):
            return jsonify({'thoughts': [], 'enabled': False}), 200

        try:
            thoughts = get_thoughts_for_message(conversation_id, message_id, user_id)
            if not thoughts:
                try:
                    message_doc = get_collaboration_message(message_id)
                    if str(message_doc.get('conversation_id') or '') == str(conversation_id or ''):
                        collaboration_conversation = get_collaboration_conversation(conversation_id)
                        assert_user_can_view_collaboration_conversation(
                            user_id,
                            collaboration_conversation,
                            allow_pending=True,
                        )
                        thoughts = get_accessible_collaboration_message_thoughts(
                            collaboration_conversation,
                            message_doc,
                            user_id,
                        )
                except CosmosResourceNotFoundError:
                    thoughts = thoughts or []
            # Strip internal Cosmos fields before returning
            sanitized = []
            for t in thoughts:
                sanitized.append({
                    'id': t.get('id'),
                    'message_id': t.get('message_id'),
                    'step_index': t.get('step_index'),
                    'step_type': t.get('step_type'),
                    'content': t.get('content'),
                    'detail': t.get('detail'),
                    'duration_ms': t.get('duration_ms'),
                    'timestamp': t.get('timestamp')
                })
            return jsonify({'thoughts': sanitized, 'enabled': True}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as e:
            log_event(f"api_get_message_thoughts error: {e}", level="WARNING")
            return jsonify({'error': 'Failed to retrieve thoughts'}), 500

    @app.route('/api/conversations/<conversation_id>/thoughts/pending', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_pending_thoughts(conversation_id):
        """Return the latest in-progress thoughts for a conversation.

        Used by the non-streaming frontend to poll for thought updates
        while waiting for the chat response.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_settings()
        if not settings.get('enable_thoughts', True):
            return jsonify({'thoughts': [], 'enabled': False}), 200

        try:
            try:
                collaboration_conversation = get_collaboration_conversation(conversation_id)
                assert_user_can_view_collaboration_conversation(
                    user_id,
                    collaboration_conversation,
                    allow_pending=True,
                )
                return jsonify({'thoughts': [], 'enabled': True}), 200
            except CosmosResourceNotFoundError:
                pass

            message_id = request.args.get('message_id')
            thoughts = get_pending_thoughts(conversation_id, user_id, message_id=message_id)
            sanitized = []
            for t in thoughts:
                sanitized.append({
                    'id': t.get('id'),
                    'message_id': t.get('message_id'),
                    'step_index': t.get('step_index'),
                    'step_type': t.get('step_type'),
                    'content': t.get('content'),
                    'detail': t.get('detail'),
                    'duration_ms': t.get('duration_ms'),
                    'timestamp': t.get('timestamp')
                })
            return jsonify({'thoughts': sanitized, 'enabled': True}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as e:
            log_event(f"api_get_pending_thoughts error: {e}", level="WARNING")
            return jsonify({'error': 'Failed to retrieve pending thoughts'}), 500
