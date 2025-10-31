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
    @control_center_admin_required
    def control_center():
        """
        Control Center main page for administrators.
        Provides dashboard overview and management tools for users, groups, and workspaces.
        """
        try:
            # Get settings for configuration data
            settings = get_settings()
            public_settings = sanitize_settings_for_user(settings)
            
            # Get basic statistics for dashboard
            stats = get_control_center_statistics()
            
            return render_template('control_center.html', 
                                 app_settings=public_settings, 
                                 settings=public_settings,
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
                'documents': 0,
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
        
        # Get active users in last 30 days using lastUpdated
        try:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            active_users_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.lastUpdated >= @thirty_days_ago
            """
            active_users_params = [{"name": "@thirty_days_ago", "value": thirty_days_ago}]
            active_users_result = list(cosmos_user_settings_container.query_items(
                query=active_users_query,
                parameters=active_users_params,
                enable_cross_partition_query=True
            ))
            stats['active_users_30_days'] = active_users_result[0] if active_users_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get active users count: {e}")
        
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
        
        # Get groups created in last 30 days using createdDate
        try:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            new_groups_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.createdDate >= @thirty_days_ago
            """
            new_groups_params = [{"name": "@thirty_days_ago", "value": thirty_days_ago}]
            new_groups_result = list(cosmos_groups_container.query_items(
                query=new_groups_query,
                parameters=new_groups_params,
                enable_cross_partition_query=True
            ))
            stats['locked_groups'] = new_groups_result[0] if new_groups_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get new groups count: {e}")
            
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
            
        # Get public workspaces created in last 30 days using createdDate
        try:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            new_workspaces_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.createdDate >= @thirty_days_ago
            """
            new_workspaces_params = [{"name": "@thirty_days_ago", "value": thirty_days_ago}]
            new_workspaces_result = list(cosmos_public_workspaces_container.query_items(
                query=new_workspaces_query,
                parameters=new_workspaces_params,
                enable_cross_partition_query=True
            ))
            stats['hidden_workspaces'] = new_workspaces_result[0] if new_workspaces_result else 0
        except Exception as e:
            current_app.logger.warning(f"Could not get new public workspaces count: {e}")
        
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
        
        # Get recent activity (last 24 hours)
        try:
            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            
            # Recent logins from activity_logs
            login_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.activity_type = 'user_login' 
                AND c.timestamp >= @yesterday
            """
            login_params = [{"name": "@yesterday", "value": yesterday}]
            recent_logins = list(cosmos_activity_logs_container.query_items(
                query=login_query,
                parameters=login_params,
                enable_cross_partition_query=True
            ))
            stats['recent_activity_24h']['logins'] = recent_logins[0] if recent_logins else 0
            
            # Recent chat activity from conversations
            chat_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.last_updated >= @yesterday
            """
            chat_params = [{"name": "@yesterday", "value": yesterday}]
            recent_chats = list(cosmos_conversations_container.query_items(
                query=chat_query,
                parameters=chat_params,
                enable_cross_partition_query=True
            ))
            stats['recent_activity_24h']['chats'] = recent_chats[0] if recent_chats else 0
            
            # Recent document uploads from user_documents
            doc_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.upload_date >= @yesterday
            """
            doc_params = [{"name": "@yesterday", "value": yesterday}]
            recent_docs = list(cosmos_user_documents_container.query_items(
                query=doc_query,
                parameters=doc_params,
                enable_cross_partition_query=True
            ))
            stats['recent_activity_24h']['documents'] = recent_docs[0] if recent_docs else 0
            
        except Exception as e:
            current_app.logger.warning(f"Could not get recent activity: {e}")
        
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
            'recent_activity_24h': {'chats': 0, 'documents': 0, 'logins': 0},
            'blocked_users': 0,
            'alerts': []
        }