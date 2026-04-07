# route_frontend_profile.py

from config import *
from functions_appinsights import log_event
from functions_authentication import *
from functions_debug import debug_print
from functions_settings import get_settings, get_user_settings, update_user_settings
from semantic_kernel_fact_memory_store import FactMemoryStore
from swagger_wrapper import swagger_route, get_auth_security
import traceback

def register_route_frontend_profile(app):
    @app.route('/profile')
    @swagger_route(security=get_auth_security())
    @login_required
    def profile():
        user = session.get('user')
        return render_template('profile.html', user=user)

    def serialize_fact_memory_item(fact_item):
        return {
            'id': fact_item.get('id'),
            'value': str(fact_item.get('value') or ''),
            'agent_id': fact_item.get('agent_id'),
            'conversation_id': fact_item.get('conversation_id'),
            'scope_type': fact_item.get('scope_type'),
            'scope_id': fact_item.get('scope_id'),
            'created_at': fact_item.get('created_at'),
            'updated_at': fact_item.get('updated_at') or fact_item.get('created_at'),
        }

    def get_profile_fact_memory_payload(user_id):
        settings = get_settings()
        fact_store = FactMemoryStore()
        facts = fact_store.list_facts(scope_type='user', scope_id=user_id)
        return {
            'success': True,
            'enabled': bool(settings.get('enable_fact_memory_plugin', False)),
            'facts': [serialize_fact_memory_item(fact) for fact in facts],
        }
    
    @app.route('/api/profile/image/refresh', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def refresh_profile_image():
        """
        Fetches the user's profile image from Microsoft Graph and saves it to user settings.
        """
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({"error": "Unable to identify user"}), 401
            
            # Fetch profile image from Microsoft Graph
            profile_image_data = get_user_profile_image()
            
            if profile_image_data:
                # Save the profile image to user settings
                success = update_user_settings(user_id, {'profileImage': profile_image_data})
                
                if success:
                    return jsonify({
                        "success": True,
                        "message": "Profile image updated successfully",
                        "profileImage": profile_image_data
                    }), 200
                else:
                    return jsonify({"error": "Failed to save profile image"}), 500
            else:
                # No profile image found, remove any existing one
                success = update_user_settings(user_id, {'profileImage': None})
                
                if success:
                    return jsonify({
                        "success": True,
                        "message": "No profile image found",
                        "profileImage": None
                    }), 200
                else:
                    return jsonify({"error": "Failed to update profile image settings"}), 500
                    
        except Exception as e:
            debug_print(f"Error refreshing profile image for user {user_id}: {e}")
            log_event(f"Error refreshing profile image for user {user_id}: {str(e)}", level=logging.ERROR)
            return jsonify({"error": "Internal server error"}), 500
    
    @app.route('/api/user/activity-trends', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_activity_trends():
        """
        Get time-series activity trends for the current user over the last 30 days.
        Returns data for login activity, conversation creation, document uploads, and token usage.
        """
        try:
            from datetime import datetime, timezone, timedelta
            from collections import defaultdict
            from config import cosmos_activity_logs_container, cosmos_conversations_container
            from config import cosmos_user_documents_container, cosmos_messages_container
            
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({"error": "Unable to identify user"}), 401
            
            # Calculate date range for last 30 days
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=30)
            
            # Initialize data structures for daily aggregation
            logins_by_date = defaultdict(int)
            conversations_by_date = defaultdict(int)
            conversations_delete_by_date = defaultdict(int)
            documents_upload_by_date = defaultdict(int)
            documents_delete_by_date = defaultdict(int)
            tokens_by_date = defaultdict(int)
            
            # Query 1: Get login activity from activity_logs
            try:
                login_query = """
                    SELECT c.timestamp, c.created_at FROM c 
                    WHERE c.user_id = @user_id 
                    AND c.activity_type = 'user_login'
                    AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
                """
                login_params = [
                    {"name": "@user_id", "value": user_id},
                    {"name": "@start_date", "value": start_date.isoformat()}
                ]
                login_records = list(cosmos_activity_logs_container.query_items(
                    query=login_query,
                    parameters=login_params,
                    enable_cross_partition_query=True
                ))
                
                for record in login_records:
                    timestamp = record.get('timestamp') or record.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            date_key = dt.strftime('%Y-%m-%d')
                            logins_by_date[date_key] += 1
                        except Exception as ex:
                            pass
            except Exception as e:
                debug_print(f"Error fetching login trends: {e}")
                log_event(f"Error fetching login trends: {str(e)}", level=logging.ERROR)
            
            # Query 2: Get conversation creation activity from activity_logs
            try:
                conv_query = """
                    SELECT c.timestamp, c.created_at FROM c 
                    WHERE c.user_id = @user_id 
                    AND c.activity_type = 'conversation_creation'
                    AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
                """
                conv_params = [
                    {"name": "@user_id", "value": user_id},
                    {"name": "@start_date", "value": start_date.isoformat()}
                ]
                conv_records = list(cosmos_activity_logs_container.query_items(
                    query=conv_query,
                    parameters=conv_params,
                    enable_cross_partition_query=True
                ))
                
                for record in conv_records:
                    timestamp = record.get('timestamp') or record.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            date_key = dt.strftime('%Y-%m-%d')
                            conversations_by_date[date_key] += 1
                        except Exception as ex:
                            pass
            except Exception as e:
                debug_print(f"Error fetching conversation trends: {e}")
                log_event(f"Error fetching conversation trends: {str(e)}", level=logging.ERROR)
            
            # Query 2b: Get conversation deletion activity from activity_logs
            try:
                conv_delete_query = """
                    SELECT c.timestamp, c.created_at FROM c 
                    WHERE c.user_id = @user_id 
                    AND c.activity_type = 'conversation_deletion'
                    AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
                """
                conv_delete_records = list(cosmos_activity_logs_container.query_items(
                    query=conv_delete_query,
                    parameters=conv_params,
                    enable_cross_partition_query=True
                ))
                
                for record in conv_delete_records:
                    timestamp = record.get('timestamp') or record.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            date_key = dt.strftime('%Y-%m-%d')
                            conversations_delete_by_date[date_key] += 1
                        except Exception as ex:
                            pass
            except Exception as e:
                debug_print(f"Error fetching conversation deletion trends: {e}")
                log_event(f"Error fetching conversation deletion trends: {str(e)}", level=logging.ERROR)
            
            # Query 3: Get document upload activity from activity_logs
            try:
                doc_upload_query = """
                    SELECT c.timestamp, c.created_at FROM c 
                    WHERE c.user_id = @user_id 
                    AND c.activity_type = 'document_creation'
                    AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
                """
                doc_params = [
                    {"name": "@user_id", "value": user_id},
                    {"name": "@start_date", "value": start_date.isoformat()}
                ]
                doc_records = list(cosmos_activity_logs_container.query_items(
                    query=doc_upload_query,
                    parameters=doc_params,
                    enable_cross_partition_query=True
                ))
                
                for record in doc_records:
                    timestamp = record.get('timestamp') or record.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            date_key = dt.strftime('%Y-%m-%d')
                            documents_upload_by_date[date_key] += 1
                        except Exception as ex:
                            pass
            except Exception as e:
                debug_print(f"Error fetching document upload trends: {e}")
                log_event(f"Error fetching document upload trends: {str(e)}", level=logging.ERROR)
            
            # Query 3b: Get document delete activity from activity_logs
            try:
                doc_delete_query = """
                    SELECT c.timestamp, c.created_at FROM c 
                    WHERE c.user_id = @user_id 
                    AND c.activity_type = 'document_deletion'
                    AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
                """
                doc_delete_records = list(cosmos_activity_logs_container.query_items(
                    query=doc_delete_query,
                    parameters=doc_params,
                    enable_cross_partition_query=True
                ))
                
                for record in doc_delete_records:
                    timestamp = record.get('timestamp') or record.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            date_key = dt.strftime('%Y-%m-%d')
                            documents_delete_by_date[date_key] += 1
                        except Exception as ex:
                            pass
            except Exception as e:
                debug_print(f"Error fetching document delete trends: {e}")
                log_event(f"Error fetching document delete trends: {str(e)}", level=logging.ERROR)
            
            # Query 4: Get token usage from activity_logs
            try:
                token_query = """
                    SELECT c.timestamp, c.created_at, c.usage FROM c 
                    WHERE c.user_id = @user_id 
                    AND c.activity_type = 'token_usage'
                    AND (c.timestamp >= @start_date OR c.created_at >= @start_date)
                """
                token_params = [
                    {"name": "@user_id", "value": user_id},
                    {"name": "@start_date", "value": start_date.isoformat()}
                ]
                token_records = list(cosmos_activity_logs_container.query_items(
                    query=token_query,
                    parameters=token_params,
                    enable_cross_partition_query=True
                ))
                
                for record in token_records:
                    timestamp = record.get('timestamp') or record.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            date_key = dt.strftime('%Y-%m-%d')
                            # Extract total tokens from usage field
                            usage = record.get('usage', {})
                            total_tokens = usage.get('total_tokens', 0)
                            tokens_by_date[date_key] += total_tokens
                        except Exception as ex:
                            pass
            except Exception as e:
                debug_print(f"Error fetching token usage trends: {e}")
                log_event(f"Error fetching token usage trends: {str(e)}", level=logging.ERROR)
            
            # Generate complete date range (last 30 days)
            date_range = []
            for i in range(30):
                date = end_date - timedelta(days=29-i)
                date_range.append(date.strftime('%Y-%m-%d'))
            
            # Format data for Chart.js
            logins_data = [{"date": date, "count": logins_by_date.get(date, 0)} for date in date_range]
            conversations_data = {
                "creates": [{"date": date, "count": conversations_by_date.get(date, 0)} for date in date_range],
                "deletes": [{"date": date, "count": conversations_delete_by_date.get(date, 0)} for date in date_range]
            }
            documents_data = {
                "uploads": [{"date": date, "count": documents_upload_by_date.get(date, 0)} for date in date_range],
                "deletes": [{"date": date, "count": documents_delete_by_date.get(date, 0)} for date in date_range]
            }
            tokens_data = [{"date": date, "tokens": tokens_by_date.get(date, 0)} for date in date_range]
            
            # Get storage metrics from user settings
            user_settings = get_user_settings(user_id)
            metrics = user_settings.get('settings', {}).get('metrics', {})
            document_metrics = metrics.get('document_metrics', {})
            
            storage_data = {
                "ai_search_size": document_metrics.get('ai_search_size', 0),
                "storage_account_size": document_metrics.get('storage_account_size', 0)
            }
            
            return jsonify({
                "success": True,
                "logins": logins_data,
                "conversations": conversations_data,
                "documents": documents_data,
                "tokens": tokens_data,
                "storage": storage_data
            }), 200
            
        except Exception as e:
            debug_print(f"Error fetching user activity trends: {e}")
            log_event(f"Error fetching user activity trends: {str(e)}", level=logging.ERROR)
            traceback.print_exc()
            return jsonify({"error": "Failed to fetch activity trends"}), 500
    
    @app.route('/api/user/settings', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_settings_api():
        """
        Get current user's settings including cached metrics.
        """
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({"error": "Unable to identify user"}), 401
            
            user_settings = get_user_settings(user_id)
            
            # Extract relevant data for frontend
            settings = user_settings.get('settings', {})
            metrics = settings.get('metrics', {})
            
            # Return ALL settings from Cosmos for backwards compatibility
            # This matches the old API behavior: return jsonify(user_settings_data), 200
            response_data = {
                "success": True,
                "settings": settings,  # Return entire settings object
                "metrics": metrics,
                "retention_policy": {
                    "enabled": settings.get('retention_policy_enabled', False),
                    "days": settings.get('retention_policy_days', 30)
                },
                "display_name": user_settings.get('display_name'),
                "email": user_settings.get('email'),
                "lastUpdated": user_settings.get('lastUpdated'),
                # Add at root level for backwards compatibility with agents code
                "selected_agent": settings.get('selected_agent')
            }
            
            return jsonify(response_data), 200
            
        except Exception as e:
            debug_print(f"Error fetching user settings: {e}")
            log_event(f"Error fetching user settings: {str(e)}", level=logging.ERROR)
            traceback.print_exc()
            return jsonify({"error": "Failed to fetch user settings"}), 500

    @app.route('/api/profile/fact-memory', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_profile_fact_memory():
        """Return the current user's fact-memory entries for profile recall."""
        user_id = None
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'Unable to identify user'}), 401

            return jsonify(get_profile_fact_memory_payload(user_id)), 200
        except Exception as exc:
            debug_print(f"[ProfileFactMemory] Failed to fetch fact memory for user {user_id}: {exc}")
            log_event(
                f"[ProfileFactMemory] Failed to fetch fact memory: {exc}",
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to fetch fact memory'}), 500

    @app.route('/api/profile/fact-memory', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def create_profile_fact_memory():
        """Create a user-scoped fact-memory entry from the profile page."""
        user_id = None
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'Unable to identify user'}), 401

            data = request.get_json(silent=True) or {}
            value = str(data.get('value') or '').strip()
            if not value:
                return jsonify({'error': 'Memory value is required'}), 400

            fact_store = FactMemoryStore()
            fact_item = fact_store.set_fact(
                scope_type='user',
                scope_id=user_id,
                value=value,
                conversation_id=None,
                agent_id=None,
            )
            log_event(
                '[ProfileFactMemory] Created fact memory entry',
                extra={'user_id': user_id, 'fact_id': fact_item.get('id')},
                level=logging.INFO,
            )
            return jsonify({
                'success': True,
                'fact': serialize_fact_memory_item(fact_item),
            }), 201
        except Exception as exc:
            debug_print(f"[ProfileFactMemory] Failed to create fact memory for user {user_id}: {exc}")
            log_event(
                f"[ProfileFactMemory] Failed to create fact memory: {exc}",
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to create fact memory'}), 500

    @app.route('/api/profile/fact-memory/<fact_id>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_profile_fact_memory(fact_id):
        """Update an existing user-scoped fact-memory entry."""
        user_id = None
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'Unable to identify user'}), 401

            data = request.get_json(silent=True) or {}
            value = str(data.get('value') or '').strip()
            if not value:
                return jsonify({'error': 'Memory value is required'}), 400

            fact_store = FactMemoryStore()
            updated_fact = fact_store.update_fact(user_id, fact_id, value)
            if updated_fact is None:
                return jsonify({'error': 'Fact memory entry not found'}), 404

            log_event(
                '[ProfileFactMemory] Updated fact memory entry',
                extra={'user_id': user_id, 'fact_id': fact_id},
                level=logging.INFO,
            )
            return jsonify({
                'success': True,
                'fact': serialize_fact_memory_item(updated_fact),
            }), 200
        except Exception as exc:
            debug_print(f"[ProfileFactMemory] Failed to update fact memory {fact_id} for user {user_id}: {exc}")
            log_event(
                f"[ProfileFactMemory] Failed to update fact memory: {exc}",
                extra={'user_id': user_id, 'fact_id': fact_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to update fact memory'}), 500

    @app.route('/api/profile/fact-memory/<fact_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_profile_fact_memory(fact_id):
        """Delete an existing user-scoped fact-memory entry."""
        user_id = None
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'Unable to identify user'}), 401

            fact_store = FactMemoryStore()
            deleted = fact_store.delete_fact(user_id, fact_id)
            if not deleted:
                return jsonify({'error': 'Fact memory entry not found'}), 404

            log_event(
                '[ProfileFactMemory] Deleted fact memory entry',
                extra={'user_id': user_id, 'fact_id': fact_id},
                level=logging.INFO,
            )
            return jsonify({'success': True}), 200
        except Exception as exc:
            debug_print(f"[ProfileFactMemory] Failed to delete fact memory {fact_id} for user {user_id}: {exc}")
            log_event(
                f"[ProfileFactMemory] Failed to delete fact memory: {exc}",
                extra={'user_id': user_id, 'fact_id': fact_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to delete fact memory'}), 500