# route_backend_notifications.py

from config import *
from functions_authentication import *
from functions_appinsights import log_event
from functions_conversation_cache import bump_conversation_cache_version
from functions_settings import *
from functions_notifications import *
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print

def register_route_backend_notifications(bp):

    @bp.route("/api/notifications", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_notifications():
        """
        Get paginated notifications for the current user.
        
        Query Parameters:
            page (int): Page number (default: 1)
            per_page (int): Items per page (default: 20)
            include_read (bool): Include read notifications (default: true)
            include_dismissed (bool): Include dismissed notifications (default: false)
        """
        try:
            user_id = get_current_user_id()
            user = session.get('user', {})
            user_roles = user.get('roles', [])
            
            # Get query parameters
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
            include_read = request.args.get('include_read', 'true').lower() == 'true'
            include_dismissed = request.args.get('include_dismissed', 'false').lower() == 'true'
            
            # Validate per_page
            if per_page not in [10, 20, 50]:
                per_page = 20
            
            result = get_user_notifications(
                user_id=user_id,
                page=page,
                per_page=per_page,
                include_read=include_read,
                include_dismissed=include_dismissed,
                user_roles=user_roles
            )
            
            return jsonify({
                'success': True,
                **result
            })
            
        except Exception as e:
            debug_print(f"Error fetching notifications: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to fetch notifications'
            }), 500

    @bp.route("/api/notifications/count", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_notification_count():
        """
        Get count of unread notifications for the current user.
        """
        try:
            user_id = get_current_user_id()
            count = get_unread_notification_count(user_id)
            app_settings = get_settings()
            completion_audio_enabled = bool(
                app_settings.get("enable_chat_completion_audio_cues", False)
            )
            completion_audio_updated_at = app_settings.get(
                "chat_completion_audio_cues_updated_at"
            )
            
            return jsonify({
                'success': True,
                'count': count,
                'chat_completion_audio_enabled': completion_audio_enabled,
                'chat_completion_audio_updated_at': completion_audio_updated_at,
            })
            
        except Exception as e:
            debug_print(f"Error fetching notification count: {e}")
            return jsonify({
                'success': False,
                'count': 0
            }), 500

    @bp.route("/api/notifications/chat-completions", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_chat_completion_notifications():
        """Get recent personal chat completion event identities for audio cues."""
        user_id = None
        try:
            user_id = get_current_user_id()
            app_settings = get_settings()
            completion_audio_enabled = bool(
                app_settings.get("enable_chat_completion_audio_cues", False)
            )
            completion_audio_updated_at = app_settings.get(
                "chat_completion_audio_cues_updated_at"
            )
            if not completion_audio_enabled:
                return jsonify({
                    "success": True,
                    "enabled": False,
                    "updated_at": completion_audio_updated_at,
                    "notifications": [],
                })
            limit = request.args.get("limit", 50)
            notifications = get_recent_chat_response_notifications(user_id, limit=limit)
            return jsonify({
                "success": True,
                "enabled": True,
                "updated_at": completion_audio_updated_at,
                "notifications": notifications,
            })
        except Exception as e:
            log_event(
                "[Notifications] Chat completion event request failed.",
                extra={
                    "user_id": user_id,
                    "error": str(e),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "notifications": [],
                "error": "Failed to fetch chat completion events",
            }), 500

    @bp.route("/api/notifications/chat-completion-audio-status", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_chat_completion_audio_status():
        """Return the current server-authoritative completion audio gate."""
        try:
            app_settings = get_settings()
            enabled = bool(
                app_settings.get("enable_chat_completion_audio_cues", False)
            )
            return jsonify({
                "success": True,
                "enabled": enabled,
                "updated_at": app_settings.get(
                    "chat_completion_audio_cues_updated_at"
                ),
            })
        except Exception as e:
            log_event(
                "[Notifications] Completion audio status request failed.",
                extra={"error": str(e)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "enabled": False,
                "error": "Failed to load completion audio status",
            }), 500

    @bp.route("/api/notifications/workflow-alerts", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_workflow_alert_notifications():
        """Get unread workflow alert notifications for the current user."""
        try:
            user_id = get_current_user_id()
            limit = int(request.args.get('limit', 5))
            if limit < 1 or limit > 10:
                limit = 5

            notifications = get_unread_workflow_priority_notifications(user_id, limit=limit)
            return jsonify({
                'success': True,
                'notifications': notifications,
            })
        except Exception as e:
            debug_print(f"Error fetching workflow alert notifications: {e}")
            return jsonify({
                'success': False,
                'notifications': [],
            }), 500

    @bp.route("/api/notifications/<notification_id>/read", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_mark_notification_read(notification_id):
        """
        Mark a notification as read.
        """
        try:
            user_id = get_current_user_id()
            success = mark_notification_read(notification_id, user_id)
            
            if success:
                bump_conversation_cache_version(user_id, reason="notification_marked_read")
                return jsonify({
                    'success': True,
                    'message': 'Notification marked as read'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to mark notification as read'
                }), 400
            
        except Exception as e:
            debug_print(f"Error marking notification as read: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500

    @bp.route("/api/notifications/<notification_id>/dismiss", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_dismiss_notification(notification_id):
        """
        Dismiss a notification.
        """
        try:
            user_id = get_current_user_id()
            success = dismiss_notification(notification_id, user_id)
            
            if success:
                bump_conversation_cache_version(user_id, reason="notification_dismissed")
                return jsonify({
                    'success': True,
                    'message': 'Notification dismissed'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to dismiss notification'
                }), 400
            
        except Exception as e:
            debug_print(f"Error dismissing notification: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500

    @bp.route("/api/notifications/mark-all-read", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_mark_all_read():
        """
        Mark all notifications as read for the current user.
        """
        try:
            user_id = get_current_user_id()
            count = mark_all_read(user_id)
            if count:
                bump_conversation_cache_version(user_id, reason="notifications_marked_read")
            
            return jsonify({
                'success': True,
                'message': f'{count} notifications marked as read',
                'count': count
            })
            
        except Exception as e:
            debug_print(f"Error marking all notifications as read: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500

    @bp.route("/api/notifications/settings", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_update_notification_settings():
        """
        Update notification settings for the current user.
        
        Body:
            notifications_per_page (int): Number of notifications per page (10, 20, or 50)
        """
        try:
            user_id = get_current_user_id()
            data = request.get_json()
            
            per_page = data.get('notifications_per_page', 20)
            
            # Validate per_page
            if per_page not in [10, 20, 50]:
                return jsonify({
                    'success': False,
                    'error': 'Invalid per_page value. Must be 10, 20, or 50.'
                }), 400
            
            # Update user settings
            update_user_settings(user_id, {
                'notifications_per_page': per_page
            })
            
            return jsonify({
                'success': True,
                'message': 'Settings updated'
            })
            
        except Exception as e:
            debug_print(f"Error updating notification settings: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500
