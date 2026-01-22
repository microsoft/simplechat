# route_backend_notifications.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_notifications import *
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print

def register_route_backend_notifications(app):

    @app.route("/api/notifications", methods=["GET"])
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

    @app.route("/api/notifications/count", methods=["GET"])
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
            
            return jsonify({
                'success': True,
                'count': count
            })
            
        except Exception as e:
            debug_print(f"Error fetching notification count: {e}")
            return jsonify({
                'success': False,
                'count': 0
            }), 500

    @app.route("/api/notifications/<notification_id>/read", methods=["POST"])
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

    @app.route("/api/notifications/<notification_id>/dismiss", methods=["DELETE"])
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

    @app.route("/api/notifications/mark-all-read", methods=["POST"])
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

    @app.route("/api/notifications/settings", methods=["POST"])
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
