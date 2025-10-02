# route_backend_control_center.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_logging import *
from functions_activity_logging import *
from swagger_wrapper import swagger_route, get_auth_security
from datetime import datetime, timedelta
import json

def register_route_backend_control_center(app):
    
    # User Management APIs
    @app.route('/api/admin/control-center/users', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_get_all_users():
        """
        Get all users with their settings, activity data, and access status.
        Supports pagination and filtering.
        """
        try:
            page = int(request.args.get('page', 1))
            per_page = min(int(request.args.get('per_page', 50)), 100)  # Max 100 per page
            search = request.args.get('search', '').strip()
            access_filter = request.args.get('access_filter', 'all')  # all, allow, deny
            
            # Build query with filters
            query_conditions = []
            parameters = []
            
            if search:
                query_conditions.append("(CONTAINS(LOWER(c.email), @search) OR CONTAINS(LOWER(c.display_name), @search))")
                parameters.append({"name": "@search", "value": search.lower()})
            
            if access_filter != 'all':
                query_conditions.append("c.settings.access.status = @access_status")
                parameters.append({"name": "@access_status", "value": access_filter})
            
            where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"
            
            # Get total count for pagination
            count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"
            total_items = list(cosmos_user_settings_container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))[0]
            
            # Calculate pagination
            offset = (page - 1) * per_page
            total_pages = (total_items + per_page - 1) // per_page
            
            # Get paginated results
            users_query = f"""
                SELECT c.id, c.email, c.display_name, c.lastUpdated, c.settings
                FROM c 
                WHERE {where_clause}
                ORDER BY c.display_name
                OFFSET {offset} LIMIT {per_page}
            """
            
            users = list(cosmos_user_settings_container.query_items(
                query=users_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            # Enhance user data with activity information
            enhanced_users = []
            for user in users:
                enhanced_user = enhance_user_with_activity(user)
                enhanced_users.append(enhanced_user)
            
            return jsonify({
                'users': enhanced_users,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_items': total_items,
                    'total_pages': total_pages,
                    'has_prev': page > 1,
                    'has_next': page < total_pages
                }
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Error getting users: {e}")
            return jsonify({'error': 'Failed to retrieve users'}), 500
    
    @app.route('/api/admin/control-center/users/<user_id>/access', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_update_user_access(user_id):
        """
        Update user access permissions (allow/deny with optional time-based restriction).
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            status = data.get('status')
            datetime_to_allow = data.get('datetime_to_allow')
            
            if status not in ['allow', 'deny']:
                return jsonify({'error': 'Status must be "allow" or "deny"'}), 400
            
            # Validate datetime_to_allow if provided
            if datetime_to_allow:
                try:
                    # Validate ISO 8601 format
                    datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00'))
                except ValueError:
                    return jsonify({'error': 'Invalid datetime format. Use ISO 8601 format'}), 400
            
            # Update user access settings
            access_settings = {
                'access': {
                    'status': status,
                    'datetime_to_allow': datetime_to_allow
                }
            }
            
            success = update_user_settings(user_id, access_settings)
            
            if success:
                # Log admin action
                admin_user = session.get('user', {})
                log_event("[ControlCenter] User Access Updated", {
                    "admin_user": admin_user.get('preferred_username', 'unknown'),
                    "target_user_id": user_id,
                    "access_status": status,
                    "datetime_to_allow": datetime_to_allow
                })
                
                return jsonify({'message': 'User access updated successfully'}), 200
            else:
                return jsonify({'error': 'Failed to update user access'}), 500
            
        except Exception as e:
            current_app.logger.error(f"Error updating user access: {e}")
            return jsonify({'error': 'Failed to update user access'}), 500
    
    @app.route('/api/admin/control-center/users/<user_id>/file-uploads', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_update_user_file_uploads(user_id):
        """
        Update user file upload permissions (allow/deny with optional time-based restriction).
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            status = data.get('status')
            datetime_to_allow = data.get('datetime_to_allow')
            
            if status not in ['allow', 'deny']:
                return jsonify({'error': 'Status must be "allow" or "deny"'}), 400
            
            # Validate datetime_to_allow if provided
            if datetime_to_allow:
                try:
                    # Validate ISO 8601 format
                    datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00'))
                except ValueError:
                    return jsonify({'error': 'Invalid datetime format. Use ISO 8601 format'}), 400
            
            # Update user file upload settings
            file_upload_settings = {
                'file_uploads': {
                    'status': status,
                    'datetime_to_allow': datetime_to_allow
                }
            }
            
            success = update_user_settings(user_id, file_upload_settings)
            
            if success:
                # Log admin action
                admin_user = session.get('user', {})
                log_event("[ControlCenter] User File Upload Updated", {
                    "admin_user": admin_user.get('preferred_username', 'unknown'),
                    "target_user_id": user_id,
                    "file_upload_status": status,
                    "datetime_to_allow": datetime_to_allow
                })
                
                return jsonify({'message': 'User file upload permissions updated successfully'}), 200
            else:
                return jsonify({'error': 'Failed to update user file upload permissions'}), 500
            
        except Exception as e:
            current_app.logger.error(f"Error updating user file uploads: {e}")
            return jsonify({'error': 'Failed to update user file upload permissions'}), 500
    
    @app.route('/api/admin/control-center/users/bulk-action', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_bulk_user_action():
        """
        Perform bulk actions on multiple users (access control, file upload control).
        """
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            user_ids = data.get('user_ids', [])
            action_type = data.get('action_type')  # 'access' or 'file_uploads'
            settings = data.get('settings', {})
            
            if not user_ids or not action_type or not settings:
                return jsonify({'error': 'Missing required fields: user_ids, action_type, settings'}), 400
            
            if action_type not in ['access', 'file_uploads']:
                return jsonify({'error': 'action_type must be "access" or "file_uploads"'}), 400
            
            status = settings.get('status')
            datetime_to_allow = settings.get('datetime_to_allow')
            
            if status not in ['allow', 'deny']:
                return jsonify({'error': 'Status must be "allow" or "deny"'}), 400
            
            # Validate datetime_to_allow if provided
            if datetime_to_allow:
                try:
                    datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00'))
                except ValueError:
                    return jsonify({'error': 'Invalid datetime format. Use ISO 8601 format'}), 400
            
            # Apply bulk action
            success_count = 0
            failed_users = []
            
            update_settings = {
                action_type: {
                    'status': status,
                    'datetime_to_allow': datetime_to_allow
                }
            }
            
            for user_id in user_ids:
                try:
                    success = update_user_settings(user_id, update_settings)
                    if success:
                        success_count += 1
                    else:
                        failed_users.append(user_id)
                except Exception as e:
                    current_app.logger.error(f"Error updating user {user_id}: {e}")
                    failed_users.append(user_id)
            
            # Log admin action
            admin_user = session.get('user', {})
            log_event("[ControlCenter] Bulk User Action", {
                "admin_user": admin_user.get('preferred_username', 'unknown'),
                "action_type": action_type,
                "user_count": len(user_ids),
                "success_count": success_count,
                "failed_count": len(failed_users),
                "settings": settings
            })
            
            result = {
                'message': f'Bulk action completed. {success_count} users updated successfully.',
                'success_count': success_count,
                'failed_count': len(failed_users)
            }
            
            if failed_users:
                result['failed_users'] = failed_users
            
            return jsonify(result), 200
            
        except Exception as e:
            current_app.logger.error(f"Error performing bulk user action: {e}")
            return jsonify({'error': 'Failed to perform bulk action'}), 500

def enhance_user_with_activity(user):
    """
    Enhance user data with activity information and computed fields.
    """
    try:
        enhanced = {
            'id': user.get('id'),
            'email': user.get('email', ''),
            'display_name': user.get('display_name', ''),
            'lastUpdated': user.get('lastUpdated'),
            'settings': user.get('settings', {}),
            'activity': {
                'last_login': None,
                'last_chat_activity': None,
                'chat_volume_3m': 0,
                'last_document_activity': None,
                'document_count': 0,
                'document_storage_size': 0
            },
            'access_status': 'allow',  # default
            'file_upload_status': 'allow'  # default
        }
        
        # Extract access status
        access_settings = user.get('settings', {}).get('access', {})
        if access_settings.get('status') == 'deny':
            datetime_to_allow = access_settings.get('datetime_to_allow')
            if datetime_to_allow:
                # Check if time-based restriction has expired
                try:
                    allow_time = datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00'))
                    if datetime.now(timezone.utc) >= allow_time:
                        enhanced['access_status'] = 'allow'  # Expired, should be auto-restored
                    else:
                        enhanced['access_status'] = f"deny_until_{datetime_to_allow}"
                except:
                    enhanced['access_status'] = 'deny'
            else:
                enhanced['access_status'] = 'deny'
        
        # Extract file upload status
        file_upload_settings = user.get('settings', {}).get('file_uploads', {})
        if file_upload_settings.get('status') == 'deny':
            datetime_to_allow = file_upload_settings.get('datetime_to_allow')
            if datetime_to_allow:
                # Check if time-based restriction has expired
                try:
                    allow_time = datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00'))
                    if datetime.now(timezone.utc) >= allow_time:
                        enhanced['file_upload_status'] = 'allow'  # Expired, should be auto-restored
                    else:
                        enhanced['file_upload_status'] = f"deny_until_{datetime_to_allow}"
                except:
                    enhanced['file_upload_status'] = 'deny'
            else:
                enhanced['file_upload_status'] = 'deny'
        
        # Try to get document count and storage size for the user
        try:
            doc_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.user_id = @user_id
            """
            doc_params = [{"name": "@user_id", "value": user.get('id')}]
            doc_count = list(cosmos_user_documents_container.query_items(
                query=doc_query,
                parameters=doc_params,
                enable_cross_partition_query=True
            ))
            enhanced['activity']['document_count'] = doc_count[0] if doc_count else 0
        except Exception as e:
            current_app.logger.debug(f"Could not get document count for user {user.get('id')}: {e}")
        
        # Try to get recent chat activity (last 3 months)
        try:
            three_months_ago = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            chat_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.user_id = @user_id AND c.timestamp >= @three_months_ago
            """
            chat_params = [
                {"name": "@user_id", "value": user.get('id')},
                {"name": "@three_months_ago", "value": three_months_ago}
            ]
            chat_count = list(cosmos_messages_container.query_items(
                query=chat_query,
                parameters=chat_params,
                enable_cross_partition_query=True
            ))
            enhanced['activity']['chat_volume_3m'] = chat_count[0] if chat_count else 0
        except Exception as e:
            current_app.logger.debug(f"Could not get chat activity for user {user.get('id')}: {e}")
        
        return enhanced
        
    except Exception as e:
        current_app.logger.error(f"Error enhancing user data: {e}")
        return user  # Return original user data if enhancement fails

    # Activity Trends API
    @app.route('/api/admin/control-center/activity-trends', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_get_activity_trends():
        """
        Get activity trends data for the control center dashboard.
        Returns aggregated activity data from various containers.
        """
        try:
            days = int(request.args.get('days', 7))
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            print(f"🔍 [Activity Trends API] Request for {days} days: {start_date} to {end_date}")
            
            # Get activity data
            activity_data = get_activity_trends_data(start_date, end_date)
            
            print(f"🔍 [Activity Trends API] Returning data: {activity_data}")
            
            return jsonify({
                'success': True,
                'activity_data': activity_data,
                'period': f"{days} days",
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            })
            
        except Exception as e:
            current_app.logger.error(f"Error getting activity trends: {e}")
            print(f"❌ [Activity Trends API] Error: {e}")
            return jsonify({'error': 'Failed to retrieve activity trends'}), 500

def get_activity_trends_data(start_date, end_date):
    """
    Get aggregated activity data for the specified date range from existing containers.
    Returns daily activity counts by type using real application data.
    """
    try:
        # Debug logging
        print(f"🔍 [Activity Trends Debug] Getting data for range: {start_date} to {end_date}")
        
        # Initialize daily data structure
        daily_data = {}
        current_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        while current_date <= end_date:
            date_key = current_date.strftime('%Y-%m-%d')
            daily_data[date_key] = {
                'date': date_key,
                'chats': 0,
                'documents': 0,
                'logins': 0,
                'total': 0
            }
            current_date += timedelta(days=1)
        
        print(f"🔍 [Activity Trends Debug] Initialized {len(daily_data)} days of data: {list(daily_data.keys())}")
        
        # Parameters for queries
        parameters = [
            {"name": "@start_date", "value": start_date.isoformat()},
            {"name": "@end_date", "value": end_date.isoformat()}
        ]
        
        print(f"🔍 [Activity Trends Debug] Query parameters: {parameters}")
        
        # Query 1: Get chat activity from conversations and messages containers
        try:
            print("🔍 [Activity Trends Debug] Querying conversations...")
            
            # Count conversations created/updated in date range
            conversations_query = """
                SELECT c.last_updated
                FROM c 
                WHERE c.last_updated >= @start_date AND c.last_updated <= @end_date
            """
            
            # Count messages created in date range  
            messages_query = """
                SELECT c.timestamp
                FROM c 
                WHERE c.timestamp >= @start_date AND c.timestamp <= @end_date
            """
            
            # Process conversations
            conversations = list(cosmos_conversations_container.query_items(
                query=conversations_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            print(f"🔍 [Activity Trends Debug] Found {len(conversations)} conversations")
            
            for conv in conversations:
                last_updated = conv.get('last_updated')
                if last_updated:
                    try:
                        if isinstance(last_updated, str):
                            conv_date = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                        else:
                            conv_date = last_updated
                        
                        date_key = conv_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['chats'] += 1
                    except Exception as e:
                        current_app.logger.debug(f"Could not parse conversation timestamp {last_updated}: {e}")
            
            # Process messages  
            messages = list(cosmos_messages_container.query_items(
                query=messages_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            print(f"🔍 [Activity Trends Debug] Found {len(messages)} messages")
            
            for msg in messages:
                timestamp = msg.get('timestamp')
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            msg_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        else:
                            msg_date = timestamp
                        
                        date_key = msg_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['chats'] += 1
                    except Exception as e:
                        current_app.logger.debug(f"Could not parse message timestamp {timestamp}: {e}")
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query conversation/message data: {e}")
            print(f"❌ [Activity Trends Debug] Error querying chats: {e}")

        # Query 2: Get document activity
        try:
            print("🔍 [Activity Trends Debug] Querying documents...")
            
            documents_query = """
                SELECT c.upload_date, c.last_updated, c.timestamp, c.createdAt, c.uploadedAt
                FROM c 
                WHERE (c.upload_date >= @start_date AND c.upload_date <= @end_date)
                   OR (c.last_updated >= @start_date AND c.last_updated <= @end_date)
            """
            
            # Query all document containers
            containers = [
                ('user_documents', cosmos_user_documents_container),
                ('group_documents', cosmos_group_documents_container), 
                ('public_documents', cosmos_public_documents_container)
            ]
            
            total_docs = 0
            for container_name, container in containers:
                docs = list(container.query_items(
                    query=documents_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                print(f"🔍 [Activity Trends Debug] Found {len(docs)} documents in {container_name}")
                total_docs += len(docs)
                
                for doc in docs:
                    # Prioritize upload_date, then last_updated, then other fields
                    timestamp = (doc.get('upload_date') or 
                               doc.get('last_updated') or
                               doc.get('timestamp') or 
                               doc.get('createdAt') or
                               doc.get('uploadedAt'))
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                doc_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            else:
                                doc_date = timestamp
                            
                            date_key = doc_date.strftime('%Y-%m-%d')
                            if date_key in daily_data:
                                daily_data[date_key]['documents'] += 1
                        except Exception as e:
                            current_app.logger.debug(f"Could not parse document timestamp {timestamp}: {e}")
            
            print(f"🔍 [Activity Trends Debug] Total documents found: {total_docs}")
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query document data: {e}")
            print(f"❌ [Activity Trends Debug] Error querying documents: {e}")

        # Query 3: Get login activity from activity_logs container
        try:
            print("🔍 [Activity Trends Debug] Querying login activity...")
            
            login_query = """
                SELECT c.timestamp, c.created_at
                FROM c 
                WHERE c.activity_type = 'user_login' 
                AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                   OR (c.created_at >= @start_date AND c.created_at <= @end_date))
            """
            
            login_activities = list(cosmos_activity_logs_container.query_items(
                query=login_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            print(f"🔍 [Activity Trends Debug] Found {len(login_activities)} login activities")
            
            for login in login_activities:
                timestamp = login.get('timestamp') or login.get('created_at')
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            login_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        else:
                            login_date = timestamp
                        
                        date_key = login_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['logins'] += 1
                    except Exception as e:
                        current_app.logger.debug(f"Could not parse login timestamp {timestamp}: {e}")
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query activity logs for login data: {e}")
            print(f"❌ [Activity Trends Debug] Error querying logins: {e}")

        # Calculate totals for each day
        for date_key in daily_data:
            daily_data[date_key]['total'] = (
                daily_data[date_key]['chats'] + 
                daily_data[date_key]['documents'] + 
                daily_data[date_key]['logins']
            )

        # Group by activity type for chart display  
        result = {
            'chats': {},
            'documents': {},
            'logins': {}
        }
        
        for date_key, data in daily_data.items():
            result['chats'][date_key] = data['chats']
            result['documents'][date_key] = data['documents'] 
            result['logins'][date_key] = data['logins']
        
        print(f"🔍 [Activity Trends Debug] Final result: {result}")
        
        return result

    except Exception as e:
        current_app.logger.error(f"Error getting activity trends data: {e}")
        print(f"❌ [Activity Trends Debug] Fatal error: {e}")
        return {
            'chats': {},
            'documents': {},
            'logins': {}
        }