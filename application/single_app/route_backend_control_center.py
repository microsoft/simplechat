# route_backend_control_center.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_logging import *
from functions_activity_logging import *
from swagger_wrapper import swagger_route, get_auth_security
from datetime import datetime, timedelta
import json
from functions_debug import debug_print

def enhance_user_with_activity(user, force_refresh=False):
    """
    Enhance user data with activity information and computed fields.
    If force_refresh is False, will try to use cached metrics from user settings.
    """
    try:
        enhanced = {
            'id': user.get('id'),
            'email': user.get('email', ''),
            'display_name': user.get('display_name', ''),
            'lastUpdated': user.get('lastUpdated'),
            'settings': user.get('settings', {}),
            'profile_image': user.get('settings', {}).get('profileImage'),  # Extract profile image
            'activity': {
                'login_metrics': {
                    'total_logins': 0,
                    'last_login': None
                },
                'chat_metrics': {
                    'last_day_conversations': 0,
                    'total_conversations': 0,
                    'total_messages': 0,
                    'total_content_size': 0  # Based on actual message content length
                },
                'document_metrics': {
                    'personal_workspace_enabled': user.get('settings', {}).get('enable_personal_workspace', False),
                    'enhanced_citation_enabled': user.get('settings', {}).get('enable_enhanced_citation', False),
                    'last_day_uploads': 0,
                    'total_documents': 0,
                    'ai_search_size': 0,  # pages × 80KB
                    'storage_account_size': 0  # Actual file sizes from storage
                }
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
                    allow_time = datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00') if 'Z' in datetime_to_allow else datetime_to_allow)
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
                    allow_time = datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00') if 'Z' in datetime_to_allow else datetime_to_allow)
                    if datetime.now(timezone.utc) >= allow_time:
                        enhanced['file_upload_status'] = 'allow'  # Expired, should be auto-restored
                    else:
                        enhanced['file_upload_status'] = f"deny_until_{datetime_to_allow}"
                except:
                    enhanced['file_upload_status'] = 'deny'
            else:
                enhanced['file_upload_status'] = 'deny'
                
        # Check for cached metrics if not forcing refresh
        if not force_refresh:
            cached_metrics = user.get('settings', {}).get('metrics')
            if cached_metrics and cached_metrics.get('calculated_at'):
                try:
                    # Check if cache is less than 1 hour old
                    cache_time = datetime.fromisoformat(cached_metrics['calculated_at'].replace('Z', '+00:00') if 'Z' in cached_metrics['calculated_at'] else cached_metrics['calculated_at'])
                    current_time = datetime.now(timezone.utc)
                    
                    if (current_time - cache_time).total_seconds() < 3600:  # 1 hour cache
                        current_app.logger.debug(f"Using cached metrics for user {user.get('id')}")
                        # Use cached data
                        if 'login_metrics' in cached_metrics:
                            enhanced['activity']['login_metrics'] = cached_metrics['login_metrics']
                        if 'chat_metrics' in cached_metrics:
                            enhanced['activity']['chat_metrics'] = cached_metrics['chat_metrics']
                        if 'document_metrics' in cached_metrics:
                            # Merge cached document metrics with settings-based flags
                            cached_doc_metrics = cached_metrics['document_metrics'].copy()
                            cached_doc_metrics['personal_workspace_enabled'] = user.get('settings', {}).get('enable_personal_workspace', False)
                            cached_doc_metrics['enhanced_citation_enabled'] = user.get('settings', {}).get('enable_enhanced_citation', False)
                            enhanced['activity']['document_metrics'] = cached_doc_metrics
                        
                        return enhanced
                    else:
                        current_app.logger.debug(f"Cache expired for user {user.get('id')}, refreshing metrics")
                except Exception as cache_e:
                    current_app.logger.debug(f"Error checking cache for user {user.get('id')}: {cache_e}")
            
        current_app.logger.debug(f"Calculating fresh metrics for user {user.get('id')}")
        
        
        # Try to get comprehensive conversation metrics
        try:
            # Get all user conversations with last_updated info
            user_conversations_query = """
                SELECT c.id, c.last_updated FROM c WHERE c.user_id = @user_id
            """
            user_conversations_params = [{"name": "@user_id", "value": user.get('id')}]
            user_conversations = list(cosmos_conversations_container.query_items(
                query=user_conversations_query,
                parameters=user_conversations_params,
                enable_cross_partition_query=True
            ))
            
            # Total conversations count (all time)
            enhanced['activity']['chat_metrics']['total_conversations'] = len(user_conversations)
            
            # Find last day conversation (most recent conversation with latest last_updated)
            last_day_conversation = None
            if user_conversations:
                # Sort by last_updated to get the most recent
                sorted_conversations = sorted(
                    user_conversations, 
                    key=lambda x: x.get('last_updated', ''), 
                    reverse=True
                )
                if sorted_conversations:
                    most_recent_conv = sorted_conversations[0]
                    last_updated = most_recent_conv.get('last_updated')
                    if last_updated:
                        # Parse the date and format as MM/DD/YYYY
                        try:
                            date_obj = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                            last_day_conversation = date_obj.strftime('%m/%d/%Y')
                        except:
                            last_day_conversation = 'Invalid date'
            
            enhanced['activity']['chat_metrics']['last_day_conversation'] = last_day_conversation or 'Never'
            
            # Get message count and total size using two-step query approach
            if user_conversations:
                conversation_ids = [conv['id'] for conv in user_conversations]
                total_messages = 0
                total_message_size = 0
                
                # Process conversations in batches to avoid query limits
                batch_size = 10
                for i in range(0, len(conversation_ids), batch_size):
                    batch_ids = conversation_ids[i:i+batch_size]
                    
                    # Use parameterized query with IN clause for message querying
                    try:
                        # Build the IN parameters for the batch
                        in_params = []
                        param_placeholders = []
                        for j, conv_id in enumerate(batch_ids):
                            param_name = f"@conv_id_{j}"
                            param_placeholders.append(param_name)
                            in_params.append({"name": param_name, "value": conv_id})
                        
                        # Split into separate queries to avoid MultipleAggregates issue
                        # First query: Get message count
                        messages_count_query = f"""
                            SELECT VALUE COUNT(1)
                            FROM m
                            WHERE m.conversation_id IN ({', '.join(param_placeholders)})
                        """
                        
                        count_result = list(cosmos_messages_container.query_items(
                            query=messages_count_query,
                            parameters=in_params,
                            enable_cross_partition_query=True
                        ))
                        
                        batch_messages = count_result[0] if count_result else 0
                        total_messages += batch_messages
                        
                        # Second query: Get message size 
                        messages_size_query = f"""
                            SELECT VALUE SUM(LENGTH(TO_STRING(m)))
                            FROM m
                            WHERE m.conversation_id IN ({', '.join(param_placeholders)})
                        """
                        
                        size_result = list(cosmos_messages_container.query_items(
                            query=messages_size_query,
                            parameters=in_params,
                            enable_cross_partition_query=True
                        ))
                        
                        batch_size = size_result[0] if size_result else 0
                        total_message_size += batch_size or 0
                        
                        current_app.logger.debug(f"Messages batch {i//batch_size + 1}: {batch_messages} messages, {batch_size or 0} bytes")
                                
                    except Exception as msg_e:
                        current_app.logger.error(f"Could not query message sizes for batch {i//batch_size + 1}: {msg_e}")
                        # Try individual conversation queries as fallback
                        for conv_id in batch_ids:
                            try:
                                individual_params = [{"name": "@conv_id", "value": conv_id}]
                                
                                # Individual count query
                                individual_count_query = """
                                    SELECT VALUE COUNT(1)
                                    FROM m
                                    WHERE m.conversation_id = @conv_id
                                """
                                count_result = list(cosmos_messages_container.query_items(
                                    query=individual_count_query,
                                    parameters=individual_params,
                                    enable_cross_partition_query=True
                                ))
                                total_messages += count_result[0] if count_result else 0
                                
                                # Individual size query
                                individual_size_query = """
                                    SELECT VALUE SUM(LENGTH(TO_STRING(m)))
                                    FROM m
                                    WHERE m.conversation_id = @conv_id
                                """
                                size_result = list(cosmos_messages_container.query_items(
                                    query=individual_size_query,
                                    parameters=individual_params,
                                    enable_cross_partition_query=True
                                ))
                                total_message_size += size_result[0] if size_result and size_result[0] else 0
                                    
                            except Exception as individual_e:
                                current_app.logger.debug(f"Could not query individual conversation {conv_id}: {individual_e}")
                                continue
                
                enhanced['activity']['chat_metrics']['total_messages'] = total_messages
                enhanced['activity']['chat_metrics']['total_message_size'] = total_message_size
                current_app.logger.debug(f"Final chat metrics for user {user.get('id')}: {total_messages} messages, {total_message_size} bytes")
            
        except Exception as e:
            current_app.logger.debug(f"Could not get chat metrics for user {user.get('id')}: {e}")
        
        # Try to get comprehensive login metrics
        try:
            # Get total login count (all time)
            total_logins_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.user_id = @user_id AND c.activity_type = 'user_login'
            """
            login_params = [{"name": "@user_id", "value": user.get('id')}]
            total_logins = list(cosmos_activity_logs_container.query_items(
                query=total_logins_query,
                parameters=login_params,
                enable_cross_partition_query=True
            ))
            enhanced['activity']['login_metrics']['total_logins'] = total_logins[0] if total_logins else 0
            
            # Get last login timestamp
            last_login_query = """
                SELECT TOP 1 c.timestamp, c.created_at FROM c 
                WHERE c.user_id = @user_id AND c.activity_type = 'user_login'
                ORDER BY c.timestamp DESC
            """
            last_login_result = list(cosmos_activity_logs_container.query_items(
                query=last_login_query,
                parameters=login_params,
                enable_cross_partition_query=True
            ))
            if last_login_result:
                login_record = last_login_result[0]
                enhanced['activity']['login_metrics']['last_login'] = login_record.get('timestamp') or login_record.get('created_at')
                
        except Exception as e:
            current_app.logger.debug(f"Could not get login metrics for user {user.get('id')}: {e}")
        
        # Try to get comprehensive document metrics
        try:
            # Get document count using separate query (avoid MultipleAggregates issue)
            doc_count_query = """
                SELECT VALUE COUNT(1)
                FROM c 
                WHERE c.user_id = @user_id AND c.type = 'document_metadata'
            """
            doc_metrics_params = [{"name": "@user_id", "value": user.get('id')}]
            doc_count_result = list(cosmos_user_documents_container.query_items(
                query=doc_count_query,
                parameters=doc_metrics_params,
                enable_cross_partition_query=True
            ))
            
            # Get total pages using separate query 
            doc_pages_query = """
                SELECT VALUE SUM(c.number_of_pages)
                FROM c 
                WHERE c.user_id = @user_id AND c.type = 'document_metadata'
            """
            doc_pages_result = list(cosmos_user_documents_container.query_items(
                query=doc_pages_query,
                parameters=doc_metrics_params,
                enable_cross_partition_query=True
            ))
            
            total_docs = doc_count_result[0] if doc_count_result else 0
            total_pages = doc_pages_result[0] if doc_pages_result and doc_pages_result[0] else 0
            
            enhanced['activity']['document_metrics']['total_documents'] = total_docs
            # AI search size = pages × 80KB
            enhanced['activity']['document_metrics']['ai_search_size'] = total_pages * 80 * 1024  # 80KB per page
            
            # Get last day document upload (most recent last_updated date, formatted as MM/DD/YYYY)
            last_doc_query = """
                SELECT TOP 1 c.last_updated
                FROM c 
                WHERE c.user_id = @user_id AND c.type = 'document_metadata'
                ORDER BY c.last_updated DESC
            """
            last_doc_result = list(cosmos_user_documents_container.query_items(
                query=last_doc_query,
                parameters=doc_metrics_params,
                enable_cross_partition_query=True
            ))
            
            last_day_upload = 'Never'
            if last_doc_result and last_doc_result[0]:
                last_updated = last_doc_result[0].get('last_updated')
                if last_updated:
                    try:
                        date_obj = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                        last_day_upload = date_obj.strftime('%m/%d/%Y')
                    except:
                        last_day_upload = 'Invalid date'
            
            enhanced['activity']['document_metrics']['last_day_upload'] = last_day_upload
            
            # Get actual storage account size if enhanced citation is enabled
            if enhanced['activity']['document_metrics']['enhanced_citation_enabled']:
                try:
                    # Query actual file sizes from Azure Storage
                    storage_client = CLIENTS.get("storage_account_office_docs_client")
                    if storage_client:
                        user_folder_prefix = f"{user.get('id')}/"
                        total_storage_size = 0
                        
                        # List all blobs in the user's folder
                        container_client = storage_client.get_container_client(storage_account_user_documents_container_name)
                        blob_list = container_client.list_blobs(name_starts_with=user_folder_prefix)
                        
                        for blob in blob_list:
                            total_storage_size += blob.size
                            current_app.logger.debug(f"Storage blob {blob.name}: {blob.size} bytes")
                        
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        current_app.logger.debug(f"Total storage size for user {user.get('id')}: {total_storage_size} bytes")
                    else:
                        current_app.logger.debug(f"Storage client not available for user {user.get('id')}")
                        # Fallback to estimation if storage client not available
                        storage_size_query = """
                            SELECT c.file_name, c.number_of_pages FROM c 
                            WHERE c.user_id = @user_id AND c.type = 'document_metadata'
                        """
                        storage_docs = list(cosmos_user_documents_container.query_items(
                            query=storage_size_query,
                            parameters=doc_metrics_params,
                            enable_cross_partition_query=True
                        ))
                        
                        total_storage_size = 0
                        for doc in storage_docs:
                            # Estimate file size based on pages and file type
                            pages = doc.get('number_of_pages', 1)
                            file_name = doc.get('file_name', '')
                            
                            if file_name.lower().endswith('.pdf'):
                                # PDF: ~500KB per page average
                                estimated_size = pages * 500 * 1024
                            elif file_name.lower().endswith(('.docx', '.doc')):
                                # Word docs: ~300KB per page average
                                estimated_size = pages * 300 * 1024
                            elif file_name.lower().endswith(('.pptx', '.ppt')):
                                # PowerPoint: ~800KB per page average
                                estimated_size = pages * 800 * 1024
                            else:
                                # Other files: ~400KB per page average
                                estimated_size = pages * 400 * 1024
                            
                            total_storage_size += estimated_size
                        
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        current_app.logger.debug(f"Estimated storage size for user {user.get('id')}: {total_storage_size} bytes")
                    
                except Exception as storage_e:
                    current_app.logger.debug(f"Could not calculate storage size for user {user.get('id')}: {storage_e}")
                    # Set to 0 if we can't calculate
                    enhanced['activity']['document_metrics']['storage_account_size'] = 0
                
        except Exception as e:
            current_app.logger.debug(f"Could not get document metrics for user {user.get('id')}: {e}")
        
        # Save calculated metrics to user settings for caching (only if we calculated fresh data)
        if force_refresh or not user.get('settings', {}).get('metrics', {}).get('calculated_at'):
            try:
                from functions_settings import update_user_settings
                
                # Prepare metrics data for caching
                metrics_cache = {
                    'calculated_at': datetime.now(timezone.utc).isoformat(),
                    'login_metrics': enhanced['activity']['login_metrics'],
                    'chat_metrics': enhanced['activity']['chat_metrics'],
                    'document_metrics': {
                        'last_day_upload': enhanced['activity']['document_metrics']['last_day_upload'],
                        'total_documents': enhanced['activity']['document_metrics']['total_documents'],
                        'ai_search_size': enhanced['activity']['document_metrics']['ai_search_size'],
                        'storage_account_size': enhanced['activity']['document_metrics']['storage_account_size']
                        # Note: personal_workspace_enabled and enhanced_citation_enabled are not cached as they're settings-based
                    }
                }
                
                # Update user settings with cached metrics
                settings_update = {'metrics': metrics_cache}
                update_success = update_user_settings(user.get('id'), settings_update)
                
                if update_success:
                    current_app.logger.debug(f"Successfully cached metrics for user {user.get('id')}")
                else:
                    current_app.logger.debug(f"Failed to cache metrics for user {user.get('id')}")
                    
            except Exception as cache_save_e:
                current_app.logger.debug(f"Error saving metrics cache for user {user.get('id')}: {cache_save_e}")
        
        return enhanced
        
    except Exception as e:
        current_app.logger.error(f"Error enhancing user data: {e}")
        return user  # Return original user data if enhancement fails

def get_activity_trends_data(start_date, end_date):
    """
    Get aggregated activity data for the specified date range from existing containers.
    Returns daily activity counts by type using real application data.
    """
    try:
        # Debug logging
        print(f"🔍 [ACTIVITY TRENDS DEBUG] Getting data for range: {start_date} to {end_date}")
        
        # Convert string dates to datetime objects if needed
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date)
        
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
        
        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Initialized {len(daily_data)} days of data: {list(daily_data.keys())}")
        
        # Parameters for queries
        parameters = [
            {"name": "@start_date", "value": start_date.isoformat()},
            {"name": "@end_date", "value": end_date.isoformat()}
        ]
        
        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Query parameters: {parameters}")
        
        # Query 1: Get chat activity from conversations and messages containers
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying conversations...")
            
            # Count conversations updated in date range (using last_updated field)
            conversations_query = """
                SELECT c.last_updated
                FROM c 
                WHERE c.last_updated >= @start_date AND c.last_updated <= @end_date
            """
            
            # Process conversations
            conversations = list(cosmos_conversations_container.query_items(
                query=conversations_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(conversations)} conversations")
            
            for conv in conversations:
                last_updated = conv.get('last_updated')
                if last_updated:
                    try:
                        if isinstance(last_updated, str):
                            conv_date = datetime.fromisoformat(last_updated.replace('Z', '+00:00') if 'Z' in last_updated else last_updated)
                        else:
                            conv_date = last_updated
                        
                        date_key = conv_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['chats'] += 1
                    except Exception as e:
                        current_app.logger.debug(f"Could not parse conversation timestamp {last_updated}: {e}")
            
            # Note: Only using conversations.last_updated for chat activity tracking
            # as requested - not using individual message timestamps
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query conversation/message data: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying chats: {e}")

        # Query 2: Get document activity
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying documents...")
            
            documents_query = """
                SELECT c.upload_date
                FROM c 
                WHERE c.upload_date >= @start_date AND c.upload_date <= @end_date
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
                
                debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(docs)} documents in {container_name}")
                total_docs += len(docs)
                
                for doc in docs:
                    # Use upload_date field as specified
                    upload_date = doc.get('upload_date')
                    
                    if upload_date:
                        try:
                            if isinstance(upload_date, str):
                                doc_date = datetime.fromisoformat(upload_date.replace('Z', '+00:00') if 'Z' in upload_date else upload_date)
                            else:
                                doc_date = upload_date
                            
                            date_key = doc_date.strftime('%Y-%m-%d')
                            if date_key in daily_data:
                                daily_data[date_key]['documents'] += 1
                        except Exception as e:
                            current_app.logger.debug(f"Could not parse document upload_date {upload_date}: {e}")
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Total documents found: {total_docs}")
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query document data: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying documents: {e}")

        # Query 3: Get login activity from activity_logs container
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying login activity...")
            
            # First, let's check what's actually in the activity_logs container
            sample_query = """
                SELECT TOP 10 c.id, c.activity_type, c.login_method, c.timestamp, c.created_at, c.user_id
                FROM c 
                ORDER BY c.timestamp DESC
            """
            
            sample_records = list(cosmos_activity_logs_container.query_items(
                query=sample_query,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Sample activity_logs records: {sample_records}")
            
            # Count total records with login_method
            count_query = """
                SELECT VALUE COUNT(1)
                FROM c 
                WHERE c.login_method != null
            """
            
            login_count = list(cosmos_activity_logs_container.query_items(
                query=count_query,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Total records with login_method: {login_count[0] if login_count else 0}")
            
            # Query for login records using the correct activity_type
            # The data shows records have activity_type: "user_login" and proper timestamps
            login_query = """
                SELECT c.timestamp, c.created_at, c.activity_type, c.login_method, c.user_id
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
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(login_activities)} user_login records")
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Date range: {start_date.isoformat()} to {end_date.isoformat()}")
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Sample login records: {login_activities[:3] if login_activities else 'None'}")
            
            # Also check with a simpler query to see if date filtering is the issue
            if len(login_activities) == 0:
                simple_query = """
                    SELECT TOP 5 c.timestamp, c.created_at, c.activity_type
                    FROM c 
                    WHERE c.activity_type = 'user_login'
                    ORDER BY c.timestamp DESC
                """
                
                simple_results = list(cosmos_activity_logs_container.query_items(
                    query=simple_query,
                    enable_cross_partition_query=True
                ))
                
                debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Recent login records (no date filter): {simple_results}")
            
            for login in login_activities:
                timestamp = login.get('timestamp') or login.get('created_at')
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            login_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                        else:
                            login_date = timestamp
                        
                        date_key = login_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['logins'] += 1
                    except Exception as e:
                        current_app.logger.debug(f"Could not parse login timestamp {timestamp}: {e}")
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query activity logs for login data: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying logins: {e}")

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
        
        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Final result: {result}")
        
        return result

    except Exception as e:
        current_app.logger.error(f"Error getting activity trends data: {e}")
        print(f"❌ [ACTIVITY TRENDS DEBUG] Fatal error: {e}")
        return {
            'chats': {},
            'documents': {},
            'logins': {}
        }


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
            force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
            
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
                enhanced_user = enhance_user_with_activity(user, force_refresh=force_refresh)
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
                    datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00') if 'Z' in datetime_to_allow else datetime_to_allow)
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
                    datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00') if 'Z' in datetime_to_allow else datetime_to_allow)
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
                    datetime.fromisoformat(datetime_to_allow.replace('Z', '+00:00') if 'Z' in datetime_to_allow else datetime_to_allow)
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
            # Check if custom start_date and end_date are provided
            custom_start = request.args.get('start_date')
            custom_end = request.args.get('end_date')
            
            if custom_start and custom_end:
                # Use custom date range
                try:
                    start_date = datetime.fromisoformat(custom_start).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = datetime.fromisoformat(custom_end).replace(hour=23, minute=59, second=59, microsecond=999999)
                    days = (end_date - start_date).days + 1
                    print(f"🔍 [Activity Trends API] Custom date range: {start_date} to {end_date} ({days} days)")
                except ValueError:
                    return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD format.'}), 400
            else:
                # Use days parameter (default behavior)
                days = int(request.args.get('days', 7))
                # Set end_date to end of current day to include all of today's records
                end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                start_date = (end_date - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
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



    @app.route('/api/admin/control-center/activity-trends/export', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_export_activity_trends():
        """
        Export activity trends data as CSV file based on selected charts and date range.
        """
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Starting CSV export process")
            data = request.get_json()
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Request data: {data}")            # Parse request parameters
            charts = data.get('charts', ['logins', 'chats', 'documents'])  # Default to all charts
            time_window = data.get('time_window', '30')  # Default to 30 days
            start_date = data.get('start_date')  # For custom range
            end_date = data.get('end_date')  # For custom range
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Parsed params - charts: {charts}, time_window: {time_window}, start_date: {start_date}, end_date: {end_date}")            # Determine date range
            print("🔍 [ACTIVITY TRENDS DEBUG] Determining date range")
            if time_window == 'custom' and start_date and end_date:
                try:
                    debug_print("🔍 [ACTIVITY TRENDS DEBUG] Processing custom dates: {start_date} to {end_date}")
                    start_date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00') if 'Z' in start_date else start_date)
                    end_date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00') if 'Z' in end_date else end_date)
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)
                    debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Custom date objects created: {start_date_obj} to {end_date_obj}")
                except ValueError as ve:
                    print(f"❌ [ACTIVITY TRENDS DEBUG] Date parsing error: {ve}")
                    return jsonify({'error': 'Invalid date format'}), 400
            else:
                # Use predefined ranges
                days = int(time_window) if time_window.isdigit() else 30
                end_date_obj = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                start_date_obj = end_date_obj - timedelta(days=days-1)
                debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Predefined range: {days} days, from {start_date_obj} to {end_date_obj}")
            
            # Get activity data using existing function
            print("🔍 [ACTIVITY TRENDS DEBUG] Calling get_activity_trends_data")
            activity_data = get_activity_trends_data(
                start_date_obj.strftime('%Y-%m-%d'),
                end_date_obj.strftime('%Y-%m-%d')
            )
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Activity data retrieved: {len(activity_data) if activity_data else 0} chart types")
            
            # Prepare CSV data
            print("🔍 [ACTIVITY TRENDS DEBUG] Preparing CSV data")
            csv_rows = []
            csv_rows.append(['Date', 'Chart Type', 'Activity Count'])
            
            # Process each requested chart type
            for chart_type in charts:
                debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Processing chart type: {chart_type}")
                if chart_type in activity_data:
                    chart_data = activity_data[chart_type]
                    debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Chart data for {chart_type}: {len(chart_data) if chart_data else 0} entries")
                    # Sort dates for consistent output
                    sorted_dates = sorted(chart_data.keys())
                    
                    for date_key in sorted_dates:
                        count = chart_data[date_key]
                        chart_display_name = {
                            'logins': 'Logins',
                            'chats': 'Chats', 
                            'documents': 'Documents'
                        }.get(chart_type, chart_type.title())
                        
                        csv_rows.append([date_key, chart_display_name, count])
                        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Added row: {date_key}, {chart_display_name}, {count}")
                else:
                    debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] No data found for chart type: {chart_type}")
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Total CSV rows prepared: {len(csv_rows)}")
            
            # Generate CSV content
            import io
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerows(csv_rows)
            csv_content = output.getvalue()
            output.close()
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"activity_trends_export_{timestamp}.csv"
            
            # Return CSV as downloadable response
            from flask import make_response
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response
            
        except Exception as e:
            current_app.logger.error(f"Error exporting activity trends: {e}")
            return jsonify({'error': 'Failed to export data'}), 500

    @app.route('/api/admin/control-center/activity-trends/chat', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_chat_activity_trends():
        """
        Create a new chat conversation with activity trends data as CSV message.
        """
        try:
            data = request.get_json()
            
            # Parse request parameters
            charts = data.get('charts', ['logins', 'chats', 'documents'])  # Default to all charts
            time_window = data.get('time_window', '30')  # Default to 30 days
            start_date = data.get('start_date')  # For custom range
            end_date = data.get('end_date')  # For custom range
            
            # Determine date range
            if time_window == 'custom' and start_date and end_date:
                try:
                    start_date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00') if 'Z' in start_date else start_date)
                    end_date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00') if 'Z' in end_date else end_date)
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)
                except ValueError:
                    return jsonify({'error': 'Invalid date format'}), 400
            else:
                # Use predefined ranges
                days = int(time_window) if time_window.isdigit() else 30
                end_date_obj = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                start_date_obj = end_date_obj - timedelta(days=days-1)
            
            # Get activity data using existing function
            activity_data = get_activity_trends_data(
                start_date_obj.strftime('%Y-%m-%d'),
                end_date_obj.strftime('%Y-%m-%d')
            )
            
            # Prepare CSV data
            csv_rows = []
            csv_rows.append(['Date', 'Chart Type', 'Activity Count'])
            
            # Process each requested chart type
            for chart_type in charts:
                if chart_type in activity_data:
                    chart_data = activity_data[chart_type]
                    # Sort dates for consistent output
                    sorted_dates = sorted(chart_data.keys())
                    
                    for date_key in sorted_dates:
                        count = chart_data[date_key]
                        chart_display_name = {
                            'logins': 'Logins',
                            'chats': 'Chats', 
                            'documents': 'Documents'
                        }.get(chart_type, chart_type.title())
                        
                        csv_rows.append([date_key, chart_display_name, count])
            
            # Generate CSV content
            import io
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerows(csv_rows)
            csv_content = output.getvalue()
            output.close()
            
            # Get current user info
            user_id = session.get('user_id')
            user_email = session.get('email')
            user_display_name = session.get('display_name', user_email)
            
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401
            
            # Create new conversation
            conversation_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Generate descriptive title with date range
            if time_window == 'custom':
                date_range = f"{start_date} to {end_date}"
            else:
                date_range = f"Last {time_window} Days"
            
            charts_text = ", ".join([c.title() for c in charts])
            conversation_title = f"Activity Trends - {charts_text} ({date_range})"
            
            # Create conversation document
            conversation_doc = {
                "id": conversation_id,
                "title": conversation_title,
                "user_id": user_id,
                "user_email": user_email,
                "user_display_name": user_display_name,
                "created": timestamp,
                "last_updated": timestamp,
                "messages": [],
                "system_message": "You are analyzing activity trends data from a control center dashboard. The user has provided activity data as a CSV file. Please analyze the data and provide insights about user activity patterns, trends, and any notable observations.",
                "message_count": 0,
                "settings": {
                    "model": "gpt-4o",
                    "temperature": 0.7,
                    "max_tokens": 4000
                }
            }
            
            # Create the initial message with CSV data (simulate file upload)
            message_id = str(uuid.uuid4())
            csv_filename = f"activity_trends_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Create message with file attachment structure
            initial_message = {
                "id": message_id,
                "role": "user",
                "content": f"Please analyze this activity trends data from our system dashboard. The data covers {date_range} and includes {charts_text} activity.",
                "timestamp": timestamp,
                "files": [{
                    "name": csv_filename,
                    "type": "text/csv",
                    "size": len(csv_content.encode('utf-8')),
                    "content": csv_content,
                    "id": str(uuid.uuid4())
                }]
            }
            
            conversation_doc["messages"].append(initial_message)
            conversation_doc["message_count"] = 1
            
            # Save conversation to database
            cosmos_conversations_container.create_item(conversation_doc)
            
            # Log the activity
            log_event("[ControlCenter] Activity Trends Chat Created", {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "charts": charts,
                "time_window": time_window,
                "date_range": date_range
            })
            
            return jsonify({
                'success': True,
                'conversation_id': conversation_id,
                'conversation_title': conversation_title,
                'redirect_url': f'/chat/{conversation_id}'
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Error creating activity trends chat: {e}")
            return jsonify({'error': 'Failed to create chat conversation'}), 500
    
    # Data Refresh API
    @app.route('/api/admin/control-center/refresh', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_refresh_control_center_data():
        """
        Refresh all Control Center metrics data and update admin timestamp.
        This will recalculate all user metrics and cache them in user settings.
        """
        try:
            current_app.logger.info("Starting Control Center data refresh...")
            
            # Get all users to refresh their metrics
            users_query = "SELECT c.id, c.email, c.display_name, c.lastUpdated, c.settings FROM c"
            all_users = list(cosmos_user_settings_container.query_items(
                query=users_query,
                enable_cross_partition_query=True
            ))
            
            refreshed_count = 0
            failed_count = 0
            
            # Refresh metrics for each user
            for user in all_users:
                try:
                    # Force refresh of metrics for this user
                    enhanced_user = enhance_user_with_activity(user, force_refresh=True)
                    refreshed_count += 1
                    current_app.logger.debug(f"Refreshed metrics for user {user.get('id')}")
                except Exception as user_error:
                    failed_count += 1
                    current_app.logger.error(f"Failed to refresh metrics for user {user.get('id')}: {user_error}")
            
            # Update admin settings with refresh timestamp
            try:
                from functions_settings import get_settings, update_settings
                
                settings = get_settings()
                settings['control_center_last_refresh'] = datetime.now(timezone.utc).isoformat()
                update_success = update_settings(settings)
                
                if not update_success:
                    current_app.logger.warning("Failed to update admin settings with refresh timestamp")
                else:
                    current_app.logger.info("Updated admin settings with refresh timestamp")
                    
            except Exception as admin_error:
                current_app.logger.error(f"Error updating admin settings: {admin_error}")
            
            current_app.logger.info(f"Control Center data refresh completed. Refreshed: {refreshed_count}, Failed: {failed_count}")
            
            return jsonify({
                'success': True,
                'message': 'Control Center data refreshed successfully',
                'refreshed_users': refreshed_count,
                'failed_users': failed_count,
                'refresh_timestamp': datetime.now(timezone.utc).isoformat()
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Error refreshing Control Center data: {e}")
            return jsonify({'error': 'Failed to refresh data'}), 500
    
    # Get refresh status API
    @app.route('/api/admin/control-center/refresh-status', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required  
    def api_get_refresh_status():
        """
        Get the last refresh timestamp for Control Center data.
        """
        try:
            from functions_settings import get_settings
            
            settings = get_settings()
            last_refresh = settings.get('control_center_last_refresh')
            
            return jsonify({
                'last_refresh': last_refresh,
                'last_refresh_formatted': None if not last_refresh else datetime.fromisoformat(last_refresh.replace('Z', '+00:00') if 'Z' in last_refresh else last_refresh).strftime('%m/%d/%Y %I:%M %p UTC')
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Error getting refresh status: {e}")
            return jsonify({'error': 'Failed to get refresh status'}), 500