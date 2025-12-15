"""
Teams Bot webhook endpoint and route registration.
Handles incoming messages from Microsoft Teams via Azure Bot Service.
"""

from config import *
from functions_teams_bot import *
from swagger_wrapper import swagger_route, get_auth_security
import logging

def register_teams_bot_routes(app):
    """Register Teams bot routes with Flask app"""

    @app.route('/api/messages', methods=['POST'])
    @swagger_route(
        summary="Teams Bot Webhook",
        description="Receives messages from Microsoft Teams via Azure Bot Service",
        security=get_auth_security()
    )
    def handle_teams_message():
        """
        Handle incoming Teams bot messages.

        Expected request format (Bot Framework Activity):
        {
            "type": "message",
            "text": "user query",
            "from": {
                "id": "29:teams-user-id",
                "aadObjectId": "azure-ad-user-oid",
                "name": "User Name"
            },
            "conversation": {
                "id": "conversation-id",
                "tenantId": "tenant-id"
            }
        }
        """
        try:
            # Check if Teams bot is enabled
            from functions_settings import get_setting
            if not get_setting('enable_teams_bot', False):
                return jsonify({'error': 'Teams bot is not enabled'}), 503

            # Get Bot Framework token from Authorization header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                log_event("Missing or invalid authorization header", level=logging.WARNING)
                return jsonify({'error': 'Missing or invalid authorization header'}), 401

            token = auth_header.replace('Bearer ', '')

            # Validate Bot Framework token
            is_valid, claims_or_error = validate_bot_framework_token(token)
            if not is_valid:
                log_event(f"Bot token validation failed: {claims_or_error}", level=logging.WARNING)
                return jsonify({'error': 'Invalid bot token'}), 401

            # Get activity from request body
            activity = request.get_json()
            if not activity:
                return jsonify({'error': 'No activity in request body'}), 400

            # Extract user AAD OID
            user_aad_oid = activity.get('from', {}).get('aadObjectId')
            if not user_aad_oid:
                # Fallback to Teams user ID if AAD OID not available
                user_aad_oid = activity.get('from', {}).get('id', 'anonymous')
                log_event(f"No AAD OID found, using Teams ID: {user_aad_oid}", level=logging.WARNING)

            # Get conversation and message details
            conversation_id = activity.get('conversation', {}).get('id')
            message_text = activity.get('text', '').strip()
            activity_type = activity.get('type', 'message')

            # Handle different activity types
            if activity_type == 'message':
                if not message_text:
                    return jsonify({
                        'type': 'message',
                        'text': 'Please provide a question or query.'
                    }), 200

                # Remove bot mention if present (e.g., "@BotName query")
                # Teams includes bot mention in message text
                message_text = remove_bot_mention(message_text, activity)

                # Handle commands
                if message_text.lower() in ['/help', 'help']:
                    response = get_help_response()
                elif message_text.lower() in ['/status', 'status']:
                    response = get_status_response()
                else:
                    # Process query through chat engine
                    response = handle_bot_query(
                        user_id=user_aad_oid,
                        workspace_id=HR_WORKSPACE_ID,
                        query=message_text,
                        conversation_id=conversation_id
                    )

                return jsonify(response), 200

            elif activity_type == 'conversationUpdate':
                # Bot added to conversation or member joined
                members_added = activity.get('membersAdded', [])
                bot_id = activity.get('recipient', {}).get('id')

                # Check if bot was added
                if any(member.get('id') == bot_id for member in members_added):
                    response = get_welcome_response()
                    return jsonify(response), 200
                else:
                    # Other members joined, don't respond
                    return jsonify({'type': 'message', 'text': ''}), 200

            else:
                # Unsupported activity type, silently ignore
                log_event(f"Unsupported activity type: {activity_type}", level=logging.INFO)
                return jsonify({'type': 'message', 'text': ''}), 200

        except Exception as e:
            log_event(f"Teams bot error: {str(e)}", level=logging.ERROR)
            import traceback
            traceback.print_exc()
            return jsonify({
                'type': 'message',
                'text': 'Sorry, I encountered an error processing your request. Please try again later.'
            }), 500

    @app.route('/api/teams/health', methods=['GET'])
    def teams_bot_health():
        """Health check endpoint for Teams bot"""
        from functions_settings import get_setting
        return jsonify({
            'status': 'healthy',
            'bot_enabled': get_setting('enable_teams_bot', False),
            'workspace_id': HR_WORKSPACE_ID,
            'version': VERSION
        }), 200
