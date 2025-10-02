# route_frontend_control_center.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_logging import *
from swagger_wrapper import swagger_route, get_auth_security
from datetime import datetime, timedelta
import json

def register_route_frontend_control_center(app):
    @app.route('/admin/control-center', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def control_center():
        """
        Control Center main page for administrators.
        Provides dashboard overview and management tools for users, groups, and workspaces.
        """
        try:
            # Get settings for configuration data
            settings = get_settings()
            
            # Get basic statistics for dashboard
            stats = get_control_center_statistics()
            
            return render_template('control_center.html', 
                                 app_settings=settings, 
                                 settings=settings,
                                 statistics=stats)
        except Exception as e:
            current_app.logger.error(f"Error loading control center: {e}")
            flash(f"Error loading control center: {str(e)}", "error")
            return redirect(url_for('admin_settings'))

def get_control_center_statistics():
    """
    Get aggregated statistics for the Control Center dashboard.
    """
    try:
        stats = {
            'total_users': 0,
            'active_users_30_days': 0,
            'total_groups': 0,
            'locked_groups': 0,
            'total_public_workspaces': 0,
            'hidden_workspaces': 0,
            'recent_activity_24h': {
                'chats': 0,
                'uploads': 0,
                'logins': 0
            },
            'blocked_users': 0,
            'alerts': []
        }
        
        # Get total users count
        try:
            user_query = "SELECT VALUE COUNT(1) FROM c"
            user_result = list(cosmos_user_settings_container.query_items(
                query=user_query,
                enable_cross_partition_query=True
            ))
            stats['total_users'] = user_result[0] if user_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get user count: {e}")
        
        # Get total groups count
        try:
            groups_query = "SELECT VALUE COUNT(1) FROM c"
            groups_result = list(cosmos_groups_container.query_items(
                query=groups_query,
                enable_cross_partition_query=True
            ))
            stats['total_groups'] = groups_result[0] if groups_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get groups count: {e}")
        
        # Get total public workspaces count
        try:
            workspaces_query = "SELECT VALUE COUNT(1) FROM c"
            workspaces_result = list(cosmos_public_workspaces_container.query_items(
                query=workspaces_query,
                enable_cross_partition_query=True
            ))
            stats['total_public_workspaces'] = workspaces_result[0] if workspaces_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get public workspaces count: {e}")
        
        # Get blocked users count
        try:
            blocked_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.settings.access.status = "deny"
            """
            blocked_result = list(cosmos_user_settings_container.query_items(
                query=blocked_query,
                enable_cross_partition_query=True
            ))
            stats['blocked_users'] = blocked_result[0] if blocked_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get blocked users count: {e}")
        
        # Add alerts for blocked users
        if stats['blocked_users'] > 0:
            stats['alerts'].append({
                'type': 'warning',
                'message': f"{stats['blocked_users']} user(s) currently blocked from access",
                'action': 'View Users'
            })
        
        return stats
        
    except Exception as e:
        current_app.logger.error(f"Error getting control center statistics: {e}")
        return {
            'total_users': 0,
            'active_users_30_days': 0,
            'total_groups': 0,
            'locked_groups': 0,
            'total_public_workspaces': 0,
            'hidden_workspaces': 0,
            'recent_activity_24h': {'chats': 0, 'uploads': 0, 'logins': 0},
            'blocked_users': 0,
            'alerts': []
        }