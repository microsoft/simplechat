# route_backend_control_center.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_logging import *
from functions_activity_logging import *
from functions_documents import update_document
from swagger_wrapper import swagger_route, get_auth_security
from datetime import datetime, timedelta, timezone
import json
from functions_debug import debug_print

def enhance_user_with_activity(user, force_refresh=False):
    """
    Enhance user data with activity information and computed fields.
    If force_refresh is False, will try to use cached metrics from user settings.
    """
    try:
        user_id = user.get('id')
        debug_print(f"👤 [USER DEBUG] Processing user {user_id}, force_refresh={force_refresh}")
        
        # Check both user and app settings for enhanced citations
        user_enhanced_citation = user.get('settings', {}).get('enable_enhanced_citation', False)
        from functions_settings import get_settings
        app_settings = get_settings()
        app_enhanced_citations = app_settings.get('enable_enhanced_citations', False) if app_settings else False
        
        debug_print(f"📋 [SETTINGS DEBUG] User enhanced citation: {user_enhanced_citation}")
        debug_print(f"📋 [SETTINGS DEBUG] App enhanced citations: {app_enhanced_citations}")
        debug_print(f"📋 [SETTINGS DEBUG] Will use app setting: {app_enhanced_citations}")
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
                    # enhanced_citation_enabled is NOT stored in user data - frontend gets it from app settings
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
                    current_app.logger.debug(f"Using cached metrics for user {user.get('id')}")
                    # Use cached data regardless of age when not forcing refresh
                    if 'login_metrics' in cached_metrics:
                        enhanced['activity']['login_metrics'] = cached_metrics['login_metrics']
                    if 'chat_metrics' in cached_metrics:
                        enhanced['activity']['chat_metrics'] = cached_metrics['chat_metrics']
                    if 'document_metrics' in cached_metrics:
                        # Merge cached document metrics with settings-based flags
                        cached_doc_metrics = cached_metrics['document_metrics'].copy()
                        cached_doc_metrics['personal_workspace_enabled'] = user.get('settings', {}).get('enable_personal_workspace', False)
                        # Do NOT include enhanced_citation_enabled in user data - frontend gets it from app settings
                        enhanced['activity']['document_metrics'] = cached_doc_metrics
                    return enhanced
                except Exception as cache_e:
                    current_app.logger.debug(f"Error using cached metrics for user {user.get('id')}: {cache_e}")
            
            # If no cached metrics and not forcing refresh, return with default/empty metrics
            # Do NOT include enhanced_citation_enabled in user data - frontend gets it from app settings
            current_app.logger.debug(f"No cached metrics for user {user.get('id')}, returning default values (use refresh button to calculate)")
            return enhanced
            
        current_app.logger.debug(f"Force refresh requested - calculating fresh metrics for user {user.get('id')}")
        
        
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
            
            # Last day upload tracking removed - keeping only document count and sizes
            
            # Get actual storage account size if enhanced citation is enabled (check app settings)
            debug_print(f"💾 [STORAGE DEBUG] Enhanced citation enabled: {app_enhanced_citations}")
            if app_enhanced_citations:
                debug_print(f"💾 [STORAGE DEBUG] Starting storage calculation for user {user.get('id')}")
                try:
                    # Query actual file sizes from Azure Storage
                    storage_client = CLIENTS.get("storage_account_office_docs_client")
                    debug_print(f"💾 [STORAGE DEBUG] Storage client retrieved: {storage_client is not None}")
                    if storage_client:
                        user_folder_prefix = f"{user.get('id')}/"
                        total_storage_size = 0
                        
                        debug_print(f"💾 [STORAGE DEBUG] Looking for blobs with prefix: {user_folder_prefix}")
                        
                        # List all blobs in the user's folder
                        container_client = storage_client.get_container_client(storage_account_user_documents_container_name)
                        blob_list = container_client.list_blobs(name_starts_with=user_folder_prefix)
                        
                        blob_count = 0
                        for blob in blob_list:
                            total_storage_size += blob.size
                            blob_count += 1
                            debug_print(f"💾 [STORAGE DEBUG] Blob {blob.name}: {blob.size} bytes")
                            current_app.logger.debug(f"Storage blob {blob.name}: {blob.size} bytes")
                        
                        debug_print(f"💾 [STORAGE DEBUG] Found {blob_count} blobs, total size: {total_storage_size} bytes")
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        current_app.logger.debug(f"Total storage size for user {user.get('id')}: {total_storage_size} bytes")
                    else:
                        debug_print(f"💾 [STORAGE DEBUG] Storage client NOT available for user {user.get('id')}")
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
                        debug_print(f"💾 [STORAGE DEBUG] Fallback estimation complete: {total_storage_size} bytes")
                        current_app.logger.debug(f"Estimated storage size for user {user.get('id')}: {total_storage_size} bytes")
                    
                except Exception as storage_e:
                    debug_print(f"❌ [STORAGE DEBUG] Storage calculation failed for user {user.get('id')}: {storage_e}")
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

def enhance_public_workspace_with_activity(workspace, force_refresh=False):
    """
    Enhance public workspace data with activity information and computed fields.
    Follows the same pattern as group enhancement but for public workspaces.
    """
    try:
        workspace_id = workspace.get('id')
        debug_print(f"🌐 [PUBLIC WORKSPACE DEBUG] Processing workspace {workspace_id}, force_refresh={force_refresh}")
        
        # Get app settings for enhanced citations
        from functions_settings import get_settings
        app_settings = get_settings()
        app_enhanced_citations = app_settings.get('enable_enhanced_citations', False) if app_settings else False
        
        debug_print(f"📋 [PUBLIC WORKSPACE SETTINGS DEBUG] App enhanced citations: {app_enhanced_citations}")
        
        # Create flat structure that matches frontend expectations
        owner_info = workspace.get('owner', {})
        
        enhanced = {
            'id': workspace.get('id'),
            'name': workspace.get('name', ''),
            'description': workspace.get('description', ''),
            'owner': workspace.get('owner', {}),
            'admins': workspace.get('admins', []),
            'documentManagers': workspace.get('documentManagers', []),
            'createdDate': workspace.get('createdDate'),
            'modifiedDate': workspace.get('modifiedDate'),
            'created_at': workspace.get('createdDate'),  # Alias for frontend
            
            # Flat fields expected by frontend
            'owner_name': owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'owner_email': owner_info.get('email', ''),
            'created_by': owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'document_count': 0,  # Will be updated from database
            'storage_size': 0,  # Will be updated from storage account
            'last_activity': None,  # Will be updated from public_documents
            'recent_activity_count': 0,  # Will be calculated
            'status': 'active',  # default - can be determined by business logic
            
            # Keep nested structure for backward compatibility
            'activity': {
                'document_metrics': {
                    'total_documents': 0,
                    'ai_search_size': 0,  # pages × 80KB  
                    'storage_account_size': 0  # Actual file sizes from storage
                },
                'member_metrics': {
                    'total_members': len(workspace.get('admins', [])) + len(workspace.get('documentManagers', [])) + (1 if owner_info else 0),
                    'admin_count': len(workspace.get('admins', [])),
                    'document_manager_count': len(workspace.get('documentManagers', [])),
                }
            }
        }
        
        # Check for cached metrics if not forcing refresh
        if not force_refresh:
            cached_metrics = workspace.get('metrics')
            if cached_metrics and cached_metrics.get('calculated_at'):
                try:
                    # Check if cache is recent (within last 24 hours)
                    cache_time = datetime.fromisoformat(cached_metrics['calculated_at'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    
                    if now - cache_time < timedelta(hours=24):  # Use 24-hour cache window
                        debug_print(f"🌐 [PUBLIC WORKSPACE DEBUG] Using cached metrics for workspace {workspace_id} (cached at {cache_time})")
                        if 'document_metrics' in cached_metrics:
                            doc_metrics = cached_metrics['document_metrics']
                            enhanced['activity']['document_metrics'] = doc_metrics
                            # Update flat fields
                            enhanced['document_count'] = doc_metrics.get('total_documents', 0)
                            enhanced['storage_size'] = doc_metrics.get('storage_account_size', 0)
                            # Cached document metrics applied successfully
                        
                        debug_print(f"🌐 [PUBLIC WORKSPACE DEBUG] Returning cached data for {workspace_id}: {enhanced['activity']['document_metrics']}")
                        return enhanced
                    else:
                        debug_print(f"🌐 [PUBLIC WORKSPACE DEBUG] Cache expired for workspace {workspace_id} (cached at {cache_time}, age: {now - cache_time})")
                except Exception as cache_e:
                    debug_print(f"Error using cached metrics for workspace {workspace_id}: {cache_e}")
            
            debug_print(f"No cached metrics for workspace {workspace_id}, calculating basic document count")
            
            # Calculate at least the basic document count
            try:
                doc_count_query = "SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'document_metadata'"
                doc_count_params = [{"name": "@workspace_id", "value": workspace_id}]
                
                doc_count_results = list(cosmos_public_documents_container.query_items(
                    query=doc_count_query,
                    parameters=doc_count_params,
                    enable_cross_partition_query=True
                ))
                
                total_docs = 0
                if doc_count_results and len(doc_count_results) > 0:
                    total_docs = doc_count_results[0] if isinstance(doc_count_results[0], int) else 0
                
                debug_print(f"📄 [PUBLIC WORKSPACE BASIC DEBUG] Document count for workspace {workspace_id}: {total_docs}")
                enhanced['activity']['document_metrics']['total_documents'] = total_docs
                enhanced['document_count'] = total_docs
                
            except Exception as basic_e:
                debug_print(f"Error calculating basic document count for workspace {workspace_id}: {basic_e}")
            
            return enhanced
        
        # Force refresh - calculate fresh metrics
        debug_print(f"🌐 [PUBLIC WORKSPACE DEBUG] Force refresh - calculating fresh metrics for workspace {workspace_id}")
        
        # Calculate document metrics from public_documents container
        try:
            # Count documents for this workspace
            documents_count_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.public_workspace_id = @workspace_id 
                AND c.type = 'document_metadata'
            """
            documents_count_params = [{"name": "@workspace_id", "value": workspace_id}]
            
            documents_count_result = list(cosmos_public_documents_container.query_items(
                query=documents_count_query,
                parameters=documents_count_params,
                enable_cross_partition_query=True
            ))
            
            total_documents = documents_count_result[0] if documents_count_result else 0
            enhanced['activity']['document_metrics']['total_documents'] = total_documents
            enhanced['document_count'] = total_documents
            
            # Calculate AI search size (pages × 80KB)
            pages_sum_query = """
                SELECT VALUE SUM(c.number_of_pages) FROM c 
                WHERE c.public_workspace_id = @workspace_id 
                AND c.type = 'document_metadata'
            """
            pages_sum_params = [{"name": "@workspace_id", "value": workspace_id}]
            
            pages_sum_result = list(cosmos_public_documents_container.query_items(
                query=pages_sum_query,
                parameters=pages_sum_params,
                enable_cross_partition_query=True
            ))
            
            total_pages = pages_sum_result[0] if pages_sum_result and pages_sum_result[0] else 0
            ai_search_size = total_pages * 80 * 1024  # 80KB per page
            enhanced['activity']['document_metrics']['ai_search_size'] = ai_search_size
            
            debug_print(f"📊 [PUBLIC WORKSPACE DOCUMENT DEBUG] Workspace {workspace_id}: {total_documents} documents, {total_pages} pages, {ai_search_size} AI search size")
            
            # Find last upload date
            last_upload_query = """
                SELECT c.upload_date
                FROM c 
                WHERE c.public_workspace_id = @workspace_id
                AND c.type = 'document_metadata'
            """
            last_upload_params = [{"name": "@workspace_id", "value": workspace_id}]
            
            upload_docs = list(cosmos_public_documents_container.query_items(
                query=last_upload_query,
                parameters=last_upload_params,
                enable_cross_partition_query=True
            ))
            
            # Last day upload tracking removed - keeping only document count and sizes
            debug_print(f"� [PUBLIC WORKSPACE DEBUG] Document metrics calculation complete for workspace {workspace_id}")
            
        except Exception as doc_e:
            debug_print(f"❌ [PUBLIC WORKSPACE DOCUMENT DEBUG] Error calculating document metrics for workspace {workspace_id}: {doc_e}")
            
        # Get actual storage account size if enhanced citation is enabled
        debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Enhanced citation enabled: {app_enhanced_citations}")
        if app_enhanced_citations:
                debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Starting storage calculation for workspace {workspace_id}")
                try:
                    # Query actual file sizes from Azure Storage for public workspace documents
                    storage_client = CLIENTS.get("storage_account_office_docs_client")
                    debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Storage client retrieved: {storage_client is not None}")
                    if storage_client:
                        workspace_folder_prefix = f"{workspace_id}/"
                        total_storage_size = 0
                        
                        debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Looking for blobs with prefix: {workspace_folder_prefix}")
                        
                        # List all blobs in the workspace's folder - use PUBLIC documents container
                        container_client = storage_client.get_container_client(storage_account_public_documents_container_name)
                        blob_list = container_client.list_blobs(name_starts_with=workspace_folder_prefix)
                        
                        blob_count = 0
                        for blob in blob_list:
                            total_storage_size += blob.size
                            blob_count += 1
                            debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Blob {blob.name}: {blob.size} bytes")
                        
                        debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Found {blob_count} blobs, total size: {total_storage_size} bytes")
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        enhanced['storage_size'] = total_storage_size  # Update flat field
                    else:
                        debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Storage client NOT available for workspace {workspace_id}")
                        # Fallback to estimation if storage client not available
                        storage_size_query = """
                            SELECT c.file_name, c.number_of_pages FROM c 
                            WHERE c.public_workspace_id = @workspace_id AND c.type = 'document_metadata'
                        """
                        storage_docs = list(cosmos_public_documents_container.query_items(
                            query=storage_size_query,
                            parameters=documents_count_params,
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
                        enhanced['storage_size'] = total_storage_size  # Update flat field
                        debug_print(f"💾 [PUBLIC WORKSPACE STORAGE DEBUG] Fallback estimation complete: {total_storage_size} bytes")
                        
                except Exception as storage_e:
                    debug_print(f"❌ [PUBLIC WORKSPACE STORAGE DEBUG] Storage calculation failed for workspace {workspace_id}: {storage_e}")
                    # Set to 0 if we can't calculate
                    enhanced['activity']['document_metrics']['storage_account_size'] = 0
                    enhanced['storage_size'] = 0
        
        # Cache the computed metrics in the workspace document
        if force_refresh:
            try:
                metrics_cache = {
                    'document_metrics': enhanced['activity']['document_metrics'],
                    'calculated_at': datetime.now(timezone.utc).isoformat()
                }
                
                # Update workspace document with cached metrics
                workspace['metrics'] = metrics_cache
                cosmos_public_workspaces_container.upsert_item(workspace)
                debug_print(f"Successfully cached metrics for workspace {workspace_id}")
                    
            except Exception as cache_save_e:
                debug_print(f"Error saving metrics cache for workspace {workspace_id}: {cache_save_e}")
    
        return enhanced
        
    except Exception as e:
        current_app.logger.error(f"Error enhancing public workspace data: {e}")
        return workspace  # Return original workspace data if enhancement fails

def enhance_group_with_activity(group, force_refresh=False):
    """
    Enhance group data with activity information and computed fields.
    Follows the same pattern as user enhancement but for groups.
    """
    try:
        group_id = group.get('id')
        debug_print(f"👥 [GROUP DEBUG] Processing group {group_id}, force_refresh={force_refresh}")
        
        # Get app settings for enhanced citations
        from functions_settings import get_settings
        app_settings = get_settings()
        app_enhanced_citations = app_settings.get('enable_enhanced_citations', False) if app_settings else False
        
        debug_print(f"📋 [GROUP SETTINGS DEBUG] App enhanced citations: {app_enhanced_citations}")
        
        # Create flat structure that matches frontend expectations
        owner_info = group.get('owner', {})
        users_list = group.get('users', [])
        
        enhanced = {
            'id': group.get('id'),
            'name': group.get('name', ''),
            'description': group.get('description', ''),
            'owner': group.get('owner', {}),
            'users': users_list,
            'admins': group.get('admins', []),
            'documentManagers': group.get('documentManagers', []),
            'pendingUsers': group.get('pendingUsers', []),
            'createdDate': group.get('createdDate'),
            'modifiedDate': group.get('modifiedDate'),
            'created_at': group.get('createdDate'),  # Alias for frontend
            
            # Flat fields expected by frontend
            'owner_name': owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'owner_email': owner_info.get('email', ''),
            'created_by': owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'member_count': len(users_list) + (1 if owner_info else 0),
            'document_count': 0,  # Will be updated from database
            'storage_size': 0,  # Will be updated from storage account
            'last_activity': None,  # Will be updated from group_documents
            'recent_activity_count': 0,  # Will be calculated
            'status': 'active',  # default - can be determined by business logic
            
            # Keep nested structure for backward compatibility
            'activity': {
                'document_metrics': {
                    'total_documents': 0,
                    'ai_search_size': 0,  # pages × 80KB  
                    'storage_account_size': 0  # Actual file sizes from storage
                },
                'member_metrics': {
                    'total_members': len(users_list) + (1 if owner_info else 0),
                    'admin_count': len(group.get('admins', [])),
                    'document_manager_count': len(group.get('documentManagers', [])),
                    'pending_count': len(group.get('pendingUsers', []))
                }
            }
        }
        
        # Check for cached metrics if not forcing refresh
        if not force_refresh:
            # Groups don't have settings like users, but we could store metrics in the group doc
            cached_metrics = group.get('metrics')
            if cached_metrics and cached_metrics.get('calculated_at'):
                try:
                    # Check if cache is recent (within last hour)
                    cache_time = datetime.fromisoformat(cached_metrics['calculated_at'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    
                    if now - cache_time < timedelta(hours=24):  # Use 24-hour cache window
                        debug_print(f"👥 [GROUP DEBUG] Using cached metrics for group {group_id} (cached at {cache_time})")
                        if 'document_metrics' in cached_metrics:
                            doc_metrics = cached_metrics['document_metrics']
                            enhanced['activity']['document_metrics'] = doc_metrics
                            # Update flat fields
                            enhanced['document_count'] = doc_metrics.get('total_documents', 0)
                            enhanced['storage_size'] = doc_metrics.get('storage_account_size', 0)
                            # Cached document metrics applied successfully
                        
                        debug_print(f"👥 [GROUP DEBUG] Returning cached data for {group_id}: {enhanced['activity']['document_metrics']}")
                        return enhanced
                    else:
                        debug_print(f"👥 [GROUP DEBUG] Cache expired for group {group_id} (cached at {cache_time}, age: {now - cache_time})")
                except Exception as cache_e:
                    debug_print(f"Error using cached metrics for group {group_id}: {cache_e}")
            
            debug_print(f"No cached metrics for group {group_id}, calculating basic document count")
            
            # Calculate at least the basic document count
            try:
                doc_count_query = "SELECT VALUE COUNT(1) FROM c WHERE c.group_id = @group_id"
                doc_count_params = [{"name": "@group_id", "value": group_id}]
                
                doc_count_results = list(cosmos_group_documents_container.query_items(
                    query=doc_count_query,
                    parameters=doc_count_params,
                    enable_cross_partition_query=True
                ))
                
                total_docs = 0
                if doc_count_results and len(doc_count_results) > 0:
                    total_docs = doc_count_results[0] if isinstance(doc_count_results[0], int) else 0
                
                debug_print(f"📄 [GROUP BASIC DEBUG] Document count for group {group_id}: {total_docs}")
                enhanced['activity']['document_metrics']['total_documents'] = total_docs
                enhanced['document_count'] = total_docs
                
            except Exception as basic_e:
                debug_print(f"Error calculating basic document count for group {group_id}: {basic_e}")
            
            return enhanced
            
        # Force refresh - calculate fresh metrics
        debug_print(f"👥 [GROUP DEBUG] Force refresh - calculating fresh metrics for group {group_id}")
        
        # Calculate document metrics from group_documents container
        try:
            # Get document count using separate query (avoid MultipleAggregates issue) - same as user management
            doc_count_query = """
                SELECT VALUE COUNT(1)
                FROM c 
                WHERE c.group_id = @group_id AND c.type = 'document_metadata'
            """
            doc_metrics_params = [{"name": "@group_id", "value": group_id}]
            doc_count_result = list(cosmos_group_documents_container.query_items(
                query=doc_count_query,
                parameters=doc_metrics_params,
                enable_cross_partition_query=True
            ))
            
            # Get total pages using separate query - same as user management
            doc_pages_query = """
                SELECT VALUE SUM(c.number_of_pages)
                FROM c 
                WHERE c.group_id = @group_id AND c.type = 'document_metadata'
            """
            doc_pages_result = list(cosmos_group_documents_container.query_items(
                query=doc_pages_query,
                parameters=doc_metrics_params,
                enable_cross_partition_query=True
            ))
            
            total_docs = doc_count_result[0] if doc_count_result else 0
            total_pages = doc_pages_result[0] if doc_pages_result and doc_pages_result[0] else 0
            
            enhanced['activity']['document_metrics']['total_documents'] = total_docs
            enhanced['document_count'] = total_docs  # Update flat field
            # AI search size = pages × 80KB
            enhanced['activity']['document_metrics']['ai_search_size'] = total_pages * 80 * 1024  # 80KB per page
            
            debug_print(f"📄 [GROUP DOCUMENT DEBUG] Total documents for group {group_id}: {total_docs}")
            debug_print(f"📊 [GROUP AI SEARCH DEBUG] Total pages for group {group_id}: {total_pages}, AI search size: {total_pages * 80 * 1024} bytes")
            
            # Last day upload tracking removed - keeping only document count and sizes
            debug_print(f"� [GROUP DOCUMENT DEBUG] Document metrics calculation complete for group {group_id}")
            
            # Find the most recent document upload for last_activity (avoid ORDER BY composite index)
            recent_activity_query = """
                SELECT c.upload_date, c.created_at, c.modified_at
                FROM c 
                WHERE c.group_id = @group_id
            """
            recent_activity_params = [{"name": "@group_id", "value": group_id}]
            
            recent_docs = list(cosmos_group_documents_container.query_items(
                query=recent_activity_query,
                parameters=recent_activity_params,
                enable_cross_partition_query=True
            ))
            
            if recent_docs:
                # Find the most recent activity date from all documents in code
                most_recent_activity = None
                most_recent_activity_str = None
                
                for doc in recent_docs:
                    # Try multiple date fields to find the most recent activity
                    dates_to_check = [
                        doc.get('upload_date'),
                        doc.get('modified_at'), 
                        doc.get('created_at')
                    ]
                    
                    for date_str in dates_to_check:
                        if date_str:
                            try:
                                if isinstance(date_str, str):
                                    if 'T' in date_str:  # ISO format
                                        date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                    else:  # Date only format
                                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                                else:
                                    date_obj = date_str  # Already datetime
                                
                                if most_recent_activity is None or date_obj > most_recent_activity:
                                    most_recent_activity = date_obj
                                    most_recent_activity_str = date_str
                            except Exception as date_parse_e:
                                debug_print(f"📅 [GROUP ACTIVITY DEBUG] Error parsing activity date '{date_str}': {date_parse_e}")
                                continue
                
                if most_recent_activity_str:
                    enhanced['last_activity'] = most_recent_activity_str
                    debug_print(f"📅 [GROUP ACTIVITY DEBUG] Last activity for group {group_id}: {most_recent_activity_str}")
                else:
                    debug_print(f"📅 [GROUP ACTIVITY DEBUG] No valid activity dates found for group {group_id}")
            
            # Calculate recent activity count (documents in last 7 days)
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            week_ago_str = week_ago.strftime('%Y-%m-%d')
            
            recent_activity_count_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE c.group_id = @group_id 
                AND c.upload_date >= @week_ago
            """
            recent_activity_count_params = [
                {"name": "@group_id", "value": group_id},
                {"name": "@week_ago", "value": week_ago_str}
            ]
            
            recent_count_results = list(cosmos_group_documents_container.query_items(
                query=recent_activity_count_query,
                parameters=recent_activity_count_params,
                enable_cross_partition_query=True
            ))
            
            if recent_count_results:
                enhanced['recent_activity_count'] = recent_count_results[0]
                debug_print(f"📊 [GROUP ACTIVITY DEBUG] Recent activity count for group {group_id}: {recent_count_results[0]}")
            
            # AI search size already calculated above with document count
            
        except Exception as doc_e:
            debug_print(f"❌ [GROUP DOCUMENT DEBUG] Error calculating document metrics for group {group_id}: {doc_e}")
            
        # Get actual storage account size if enhanced citation is enabled (check app settings)
        debug_print(f"💾 [GROUP STORAGE DEBUG] Enhanced citation enabled: {app_enhanced_citations}")
        if app_enhanced_citations:
                debug_print(f"💾 [GROUP STORAGE DEBUG] Starting storage calculation for group {group_id}")
                try:
                    # Query actual file sizes from Azure Storage for group documents
                    storage_client = CLIENTS.get("storage_account_office_docs_client")
                    debug_print(f"💾 [GROUP STORAGE DEBUG] Storage client retrieved: {storage_client is not None}")
                    if storage_client:
                        group_folder_prefix = f"{group_id}/"
                        total_storage_size = 0
                        
                        debug_print(f"💾 [GROUP STORAGE DEBUG] Looking for blobs with prefix: {group_folder_prefix}")
                        
                        # List all blobs in the group's folder - use GROUP documents container, not user documents
                        container_client = storage_client.get_container_client(storage_account_group_documents_container_name)
                        blob_list = container_client.list_blobs(name_starts_with=group_folder_prefix)
                        
                        blob_count = 0
                        for blob in blob_list:
                            total_storage_size += blob.size
                            blob_count += 1
                            debug_print(f"💾 [GROUP STORAGE DEBUG] Blob {blob.name}: {blob.size} bytes")
                            current_app.logger.debug(f"Group storage blob {blob.name}: {blob.size} bytes")
                        
                        debug_print(f"💾 [GROUP STORAGE DEBUG] Found {blob_count} blobs, total size: {total_storage_size} bytes")
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        enhanced['storage_size'] = total_storage_size  # Update flat field
                        current_app.logger.debug(f"Total storage size for group {group_id}: {total_storage_size} bytes")
                    else:
                        debug_print(f"💾 [GROUP STORAGE DEBUG] Storage client NOT available for group {group_id}")
                        current_app.logger.debug(f"Storage client not available for group {group_id}")
                        # Fallback to estimation if storage client not available
                        storage_size_query = """
                            SELECT c.file_name, c.number_of_pages FROM c 
                            WHERE c.group_id = @group_id AND c.type = 'document_metadata'
                        """
                        storage_docs = list(cosmos_group_documents_container.query_items(
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
                        enhanced['storage_size'] = total_storage_size  # Update flat field
                        debug_print(f"💾 [GROUP STORAGE DEBUG] Fallback estimation complete: {total_storage_size} bytes")
                        current_app.logger.debug(f"Estimated storage size for group {group_id}: {total_storage_size} bytes")
                    
                except Exception as storage_e:
                    debug_print(f"❌ [GROUP STORAGE DEBUG] Storage calculation failed for group {group_id}: {storage_e}")
                    current_app.logger.debug(f"Could not calculate storage size for group {group_id}: {storage_e}")
                    # Set to 0 if we can't calculate
                    enhanced['activity']['document_metrics']['storage_account_size'] = 0
                    enhanced['storage_size'] = 0
                
        # Cache the computed metrics in the group document
        if force_refresh:
            try:
                metrics_cache = {
                    'document_metrics': enhanced['activity']['document_metrics'],
                    'calculated_at': datetime.now(timezone.utc).isoformat()
                }
                
                # Update group document with cached metrics
                group['metrics'] = metrics_cache
                cosmos_groups_container.upsert_item(group)
                debug_print(f"Successfully cached metrics for group {group_id}")
                    
            except Exception as cache_save_e:
                debug_print(f"Error saving metrics cache for group {group_id}: {cache_save_e}")
        
        return enhanced
        
    except Exception as e:
        current_app.logger.error(f"Error enhancing group data: {e}")
        return group  # Return original group data if enhancement fails

def get_activity_trends_data(start_date, end_date):
    """
    Get aggregated activity data for the specified date range from existing containers.
    Returns daily activity counts by type using real application data.
    """
    try:
        # Debug logging
        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Getting data for range: {start_date} to {end_date}")
        
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
                'personal_documents': 0,  # Track personal documents separately
                'group_documents': 0,     # Track group documents separately
                'public_documents': 0,    # Track public documents separately
                'documents': 0,           # Keep for backward compatibility
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

        # Query 2: Get document activity - separate personal and group documents
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying documents...")
            
            documents_query = """
                SELECT c.upload_date
                FROM c 
                WHERE c.upload_date >= @start_date AND c.upload_date <= @end_date
            """
            
            # Query document containers separately to track personal vs group vs public
            containers = [
                ('user_documents', cosmos_user_documents_container, 'personal_documents'),
                ('group_documents', cosmos_group_documents_container, 'group_documents'), 
                ('public_documents', cosmos_public_documents_container, 'public_documents')  # Track public separately
            ]
            
            total_docs = 0
            for container_name, container, doc_type in containers:
                docs = list(container.query_items(
                    query=documents_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(docs)} documents in {container_name} (type: {doc_type})")
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
                                daily_data[date_key][doc_type] += 1  # Increment specific document type
                                daily_data[date_key]['documents'] += 1  # Keep total for backward compatibility
                        except Exception as e:
                            current_app.logger.debug(f"Could not parse document upload_date {upload_date}: {e}")
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Total documents found: {total_docs}")
                        
        except Exception as e:
            current_app.logger.warning(f"Could not query document data: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying documents: {e}")

        # Query 3: Get login activity from activity_logs container
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying login activity...")
            
            # Query login activity from activity_logs container
            
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
            'documents': {},           # Keep for backward compatibility
            'personal_documents': {},  # New: personal documents only
            'group_documents': {},     # New: group documents only
            'public_documents': {},    # New: public documents only
            'logins': {}
        }
        
        for date_key, data in daily_data.items():
            result['chats'][date_key] = data['chats']
            result['documents'][date_key] = data['documents']  # Total for backward compatibility
            result['personal_documents'][date_key] = data['personal_documents']
            result['group_documents'][date_key] = data['group_documents']
            result['public_documents'][date_key] = data['public_documents']
            result['logins'][date_key] = data['logins']
        
        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Final result: {result}")
        
        return result

    except Exception as e:
        current_app.logger.error(f"Error getting activity trends data: {e}")
        print(f"❌ [ACTIVITY TRENDS DEBUG] Fatal error: {e}")
        return {
            'chats': {},
            'documents': {},
            'personal_documents': {},
            'group_documents': {},
            'public_documents': {},
            'logins': {}
        }

def get_raw_activity_trends_data(start_date, end_date, charts):
    """
    Get raw detailed activity data for export instead of aggregated counts.
    Returns individual records with user information for each activity type.
    """
    try:
        debug_print(f"🔍 [RAW ACTIVITY DEBUG] Getting raw data for range: {start_date} to {end_date}")
        debug_print(f"🔍 [RAW ACTIVITY DEBUG] Requested charts: {charts}")
        
        result = {}
        
        # Parameters for queries
        parameters = [
            {"name": "@start_date", "value": start_date.isoformat()},
            {"name": "@end_date", "value": end_date.isoformat()}
        ]
        
        # Helper function to get user info
        def get_user_info(user_id):
            try:
                user_doc = cosmos_user_settings_container.read_item(
                    item=user_id,
                    partition_key=user_id
                )
                return {
                    'display_name': user_doc.get('display_name', ''),
                    'email': user_doc.get('email', '')
                }
            except Exception:
                return {
                    'display_name': '',
                    'email': ''
                }
        
        # Helper function to get AI Search size with caching
        def get_ai_search_size(doc, cosmos_container):
            """
            Get AI Search size for a document (pages × 80KB).
            Uses cached value from Cosmos if available, otherwise calculates and caches it.
            
            Args:
                doc: The document dict from Cosmos (to check for cached value)
                cosmos_container: Cosmos container to update with cached value
                
            Returns:
                AI Search size in bytes
            """
            try:
                # Check if AI Search size is already cached in the document
                cached_size = doc.get('ai_search_size', 0)
                if cached_size and cached_size > 0:
                    return cached_size
                
                # Not cached or zero, calculate from page count
                pages = doc.get('number_of_pages', 0) or 0
                ai_search_size = pages * 80 * 1024 if pages else 0  # 80KB per page
                
                # Cache the calculated size in Cosmos for future use using update_document
                # This ensures we only update the specific field without overwriting other metadata
                if ai_search_size > 0:
                    try:
                        document_id = doc.get('id') or doc.get('document_id')
                        user_id = doc.get('user_id')
                        group_id = doc.get('group_id')
                        public_workspace_id = doc.get('public_workspace_id')
                        
                        if document_id and user_id:
                            update_document(
                                document_id=document_id,
                                user_id=user_id,
                                group_id=group_id,
                                public_workspace_id=public_workspace_id,
                                ai_search_size=ai_search_size
                            )
                    except Exception as cache_e:
                        # Don't fail if caching fails, just return the calculated value
                        pass
                
                return ai_search_size
                
            except Exception as e:
                return 0
        
        # Helper function to get document storage size from Azure Storage with caching
        def get_document_storage_size(doc, cosmos_container, container_name, folder_prefix, document_id):
            """
            Get actual storage size for a document from Azure Storage.
            Uses cached value from Cosmos if available, otherwise calculates and caches it.
            
            Args:
                doc: The document dict from Cosmos (to check for cached value)
                cosmos_container: Cosmos container to update with cached value
                container_name: Azure Storage container name (e.g., 'user-documents', 'group-documents', 'public-documents')
                folder_prefix: Folder prefix (e.g., user_id, group_id, public_workspace_id)
                document_id: Document ID
                
            Returns:
                Total size in bytes of all blobs for this document
            """
            try:
                # Check if storage size is already cached in the document
                cached_size = doc.get('storage_account_size', 0)
                if cached_size and cached_size > 0:
                    debug_print(f"💾 [STORAGE CACHE] Using cached storage size for {document_id}: {cached_size} bytes")
                    return cached_size
                
                # Not cached or zero, calculate from Azure Storage
                storage_client = CLIENTS.get("storage_account_office_docs_client")
                if not storage_client:
                    debug_print(f"❌ [STORAGE DEBUG] Storage client not available for {document_id}")
                    return 0
                
                # Get the file_name from the document to construct the correct blob path
                # Blob path structure: {folder_prefix}/{file_name}
                # NOT {folder_prefix}/{document_id}/... 
                file_name = doc.get('file_name', '')
                if not file_name:
                    debug_print(f"⚠️ [STORAGE DEBUG] No file_name for document {document_id}, cannot calculate storage size")
                    return 0
                
                # Construct the exact blob path
                blob_path = f"{folder_prefix}/{file_name}"
                
                debug_print(f"💾 [STORAGE DEBUG] Looking for blob: {blob_path}")
                
                container_client = storage_client.get_container_client(container_name)
                
                # Try to get the specific blob
                try:
                    blob_client = container_client.get_blob_client(blob_path)
                    blob_properties = blob_client.get_blob_properties()
                    total_size = blob_properties.size
                    blob_count = 1
                    
                    debug_print(f"💾 [STORAGE CALC] Found blob {blob_path}: {total_size} bytes")
                except Exception as blob_e:
                    debug_print(f"⚠️ [STORAGE DEBUG] Blob not found or error: {blob_path} - {blob_e}")
                    return 0
                
                debug_print(f"💾 [STORAGE CALC] Calculated storage size for {document_id}: {total_size} bytes ({blob_count} blobs)")
                
                # Cache the calculated size in Cosmos for future use using update_document
                # This ensures we only update the specific field without overwriting other metadata
                if total_size > 0:
                    try:
                        user_id = doc.get('user_id')
                        group_id = doc.get('group_id')
                        public_workspace_id = doc.get('public_workspace_id')
                        
                        if document_id and user_id:
                            update_document(
                                document_id=document_id,
                                user_id=user_id,
                                group_id=group_id,
                                public_workspace_id=public_workspace_id,
                                storage_account_size=total_size
                            )
                            debug_print(f"💾 [STORAGE CACHE] Cached storage size in Cosmos for {document_id}")
                    except Exception as cache_e:
                        debug_print(f"⚠️ [STORAGE CACHE] Could not cache storage size for {document_id}: {cache_e}")
                        # Don't fail if caching fails, just return the calculated value
                
                return total_size
                
            except Exception as e:
                debug_print(f"❌ [STORAGE DEBUG] Error getting storage size for document {document_id}: {e}")
                return 0
        
        # 1. Login Data
        if 'logins' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting login records...")
            try:
                login_query = """
                    SELECT c.timestamp, c.created_at, c.user_id, c.activity_type, c.login_method
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
                
                login_records = []
                for login in login_activities:
                    user_id = login.get('user_id', '')
                    user_info = get_user_info(user_id)
                    timestamp = login.get('timestamp') or login.get('created_at')
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                login_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                            else:
                                login_date = timestamp
                            
                            login_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'login_time': login_date.strftime('%Y-%m-%d %H:%M:%S')
                            })
                        except Exception as e:
                            debug_print(f"Could not parse login timestamp {timestamp}: {e}")
                
                result['logins'] = login_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(login_records)} login records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting login data: {e}")
                result['logins'] = []
        
        # 2. Document Data - Handle personal and group documents separately
        documents_query = """
            SELECT c.id, c.user_id, c.file_name, c.title, c.number_of_pages, 
                   c.num_chunks, c.upload_date, c.last_updated, c.status,
                   c.document_id, c.document_classification
            FROM c 
            WHERE c.upload_date >= @start_date AND c.upload_date <= @end_date
        """
        
        # Personal Documents (user_documents only)
        if 'personal_documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting personal document records...")
            try:
                personal_containers = [
                    ('user_documents', cosmos_user_documents_container)
                ]
                
                personal_document_records = []
                for container_name, container in personal_containers:
                    docs = list(container.query_items(
                        query=documents_query,
                        parameters=parameters,
                        enable_cross_partition_query=True
                    ))
                    
                    for doc in docs:
                        user_id = doc.get('user_id', '')
                        user_info = get_user_info(user_id)
                        upload_date = doc.get('upload_date')
                        
                        if upload_date:
                            try:
                                if isinstance(upload_date, str):
                                    doc_date = datetime.fromisoformat(upload_date.replace('Z', '+00:00') if 'Z' in upload_date else upload_date)
                                else:
                                    doc_date = upload_date
                                
                                # Get AI Search size (with caching)
                                ai_search_size = get_ai_search_size(doc, container)
                                pages = doc.get('number_of_pages', 0) or 0
                                
                                # Get actual storage size from Azure Storage (with caching)
                                document_id = doc.get('document_id', '') or doc.get('id', '')
                                storage_size = get_document_storage_size(
                                    doc,
                                    container,
                                    storage_account_user_documents_container_name,
                                    user_id,
                                    document_id
                                )
                                
                                personal_document_records.append({
                                    'display_name': user_info['display_name'],
                                    'email': user_info['email'],
                                    'user_id': user_id,
                                    'document_id': document_id,
                                    'filename': doc.get('file_name', ''),
                                    'title': doc.get('title', 'Unknown Title'),
                                    'page_count': pages,
                                    'ai_search_size': ai_search_size,
                                    'storage_account_size': storage_size,
                                    'upload_date': doc_date.strftime('%Y-%m-%d %H:%M:%S'),
                                    'document_type': 'Personal'
                                })
                            except Exception as e:
                                debug_print(f"Could not parse personal document upload_date {upload_date}: {e}")
                
                result['personal_documents'] = personal_document_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(personal_document_records)} personal document records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting personal document data: {e}")
                result['personal_documents'] = []
        
        # Group Documents
        if 'group_documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting group document records...")
            try:
                group_containers = [
                    ('group_documents', cosmos_group_documents_container)
                ]
                
                group_document_records = []
                for container_name, container in group_containers:
                    docs = list(container.query_items(
                        query=documents_query,
                        parameters=parameters,
                        enable_cross_partition_query=True
                    ))
                    
                    for doc in docs:
                        user_id = doc.get('user_id', '')
                        user_info = get_user_info(user_id)
                        upload_date = doc.get('upload_date')
                        
                        if upload_date:
                            try:
                                if isinstance(upload_date, str):
                                    doc_date = datetime.fromisoformat(upload_date.replace('Z', '+00:00') if 'Z' in upload_date else upload_date)
                                else:
                                    doc_date = upload_date
                                
                                # Get AI Search size (with caching)
                                ai_search_size = get_ai_search_size(doc, container)
                                pages = doc.get('number_of_pages', 0) or 0
                                
                                # Get actual storage size from Azure Storage (with caching)
                                document_id = doc.get('document_id', '') or doc.get('id', '')
                                group_id = doc.get('group_workspace_id', '')
                                storage_size = get_document_storage_size(
                                    doc,
                                    container,
                                    storage_account_group_documents_container_name,
                                    group_id,
                                    document_id
                                )
                                
                                group_document_records.append({
                                    'display_name': user_info['display_name'],
                                    'email': user_info['email'],
                                    'user_id': user_id,
                                    'document_id': document_id,
                                    'filename': doc.get('file_name', ''),
                                    'title': doc.get('title', 'Unknown Title'),
                                    'page_count': pages,
                                    'ai_search_size': ai_search_size,
                                    'storage_account_size': storage_size,
                                    'upload_date': doc_date.strftime('%Y-%m-%d %H:%M:%S'),
                                    'document_type': 'Group'
                                })
                            except Exception as e:
                                debug_print(f"Could not parse group document upload_date {upload_date}: {e}")
                
                result['group_documents'] = group_document_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(group_document_records)} group document records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting group document data: {e}")
                result['group_documents'] = []
        
        # Public Documents
        if 'public_documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting public document records...")
            try:
                public_containers = [
                    ('public_documents', cosmos_public_documents_container)
                ]
                
                public_document_records = []
                for container_name, container in public_containers:
                    docs = list(container.query_items(
                        query=documents_query,
                        parameters=parameters,
                        enable_cross_partition_query=True
                    ))
                    
                    for doc in docs:
                        user_id = doc.get('user_id', '')
                        user_info = get_user_info(user_id)
                        upload_date = doc.get('upload_date')
                        
                        if upload_date:
                            try:
                                if isinstance(upload_date, str):
                                    doc_date = datetime.fromisoformat(upload_date.replace('Z', '+00:00') if 'Z' in upload_date else upload_date)
                                else:
                                    doc_date = upload_date
                                
                                # Get AI Search size (with caching)
                                ai_search_size = get_ai_search_size(doc, container)
                                pages = doc.get('number_of_pages', 0) or 0
                                
                                # Get actual storage size from Azure Storage (with caching)
                                document_id = doc.get('document_id', '') or doc.get('id', '')
                                public_workspace_id = doc.get('public_workspace_id', '')
                                storage_size = get_document_storage_size(
                                    doc,
                                    container,
                                    storage_account_public_documents_container_name,
                                    public_workspace_id,
                                    document_id
                                )
                                
                                public_document_records.append({
                                    'display_name': user_info['display_name'],
                                    'email': user_info['email'],
                                    'user_id': user_id,
                                    'document_id': document_id,
                                    'filename': doc.get('file_name', ''),
                                    'title': doc.get('title', 'Unknown Title'),
                                    'page_count': pages,
                                    'ai_search_size': ai_search_size,
                                    'storage_account_size': storage_size,
                                    'upload_date': doc_date.strftime('%Y-%m-%d %H:%M:%S'),
                                    'document_type': 'Public'
                                })
                            except Exception as e:
                                debug_print(f"Could not parse public document upload_date {upload_date}: {e}")
                
                result['public_documents'] = public_document_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(public_document_records)} public document records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting public document data: {e}")
                result['public_documents'] = []
        
        # Keep backward compatibility - if 'documents' is requested, combine all types
        if 'documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting combined document records for backward compatibility...")
            combined_records = []
            if 'personal_documents' in result:
                combined_records.extend(result['personal_documents'])
            if 'group_documents' in result:
                combined_records.extend(result['group_documents'])
            if 'public_documents' in result:
                combined_records.extend(result['public_documents'])
            result['documents'] = combined_records
            debug_print(f"🔍 [RAW ACTIVITY DEBUG] Combined {len(combined_records)} total document records")
        
        # 3. Chat Data
        if 'chats' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting chat records...")
            try:
                conversations_query = """
                    SELECT c.id, c.user_id, c.title, c.last_updated, c.created_at
                    FROM c 
                    WHERE c.last_updated >= @start_date AND c.last_updated <= @end_date
                """
                
                conversations = list(cosmos_conversations_container.query_items(
                    query=conversations_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                chat_records = []
                for conv in conversations:
                    user_id = conv.get('user_id', '')
                    user_info = get_user_info(user_id)
                    conversation_id = conv.get('id', '')
                    last_updated = conv.get('last_updated')
                    created_at = conv.get('created_at')
                    
                    # Get message count and total size for this conversation
                    try:
                        messages_query = """
                            SELECT VALUE COUNT(1)
                            FROM c 
                            WHERE c.conversation_id = @conversation_id
                        """
                        
                        message_count_result = list(cosmos_messages_container.query_items(
                            query=messages_query,
                            parameters=[{"name": "@conversation_id", "value": conversation_id}],
                            enable_cross_partition_query=True
                        ))
                        message_count = message_count_result[0] if message_count_result else 0
                        
                        # Get total character count
                        messages_size_query = """
                            SELECT c.content
                            FROM c 
                            WHERE c.conversation_id = @conversation_id
                        """
                        
                        messages = list(cosmos_messages_container.query_items(
                            query=messages_size_query,
                            parameters=[{"name": "@conversation_id", "value": conversation_id}],
                            enable_cross_partition_query=True
                        ))
                        
                        total_size = sum(len(str(msg.get('content', ''))) for msg in messages)
                        
                    except Exception as msg_e:
                        debug_print(f"Could not get message data for conversation {conversation_id}: {msg_e}")
                        message_count = 0
                        total_size = 0
                    
                    if last_updated:
                        try:
                            if isinstance(last_updated, str):
                                conv_date = datetime.fromisoformat(last_updated.replace('Z', '+00:00') if 'Z' in last_updated else last_updated)
                            else:
                                conv_date = last_updated
                            
                            # Process created_at date
                            created_date_str = ''
                            if created_at:
                                try:
                                    if isinstance(created_at, str):
                                        created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00') if 'Z' in created_at else created_at)
                                    else:
                                        created_date = created_at
                                    created_date_str = created_date.strftime('%Y-%m-%d %H:%M:%S')
                                except Exception as e:
                                    debug_print(f"Could not parse conversation created_at {created_at}: {e}")
                            
                            chat_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'chat_id': conversation_id,
                                'chat_title': conv.get('title', ''),
                                'message_count': message_count,
                                'total_size': total_size,
                                'created_date': created_date_str
                            })
                        except Exception as e:
                            debug_print(f"Could not parse conversation last_updated {last_updated}: {e}")
                
                result['chats'] = chat_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(chat_records)} chat records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting chat data: {e}")
                result['chats'] = []
        
        debug_print(f"🔍 [RAW ACTIVITY DEBUG] Returning raw data with {len(result)} chart types")
        return result
        
    except Exception as e:
        current_app.logger.error(f"Error getting raw activity trends data: {e}")
        debug_print(f"❌ [RAW ACTIVITY DEBUG] Fatal error: {e}")
        return {}


def register_route_backend_control_center(app):
    
    # User Management APIs
    @app.route('/api/admin/control-center/users', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
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
            export_all = request.args.get('all', 'false').lower() == 'true'  # For CSV export
            
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
            
            if export_all:
                # For CSV export, get all users without pagination
                users_query = f"""
                    SELECT c.id, c.email, c.display_name, c.lastUpdated, c.settings
                    FROM c 
                    WHERE {where_clause}
                    ORDER BY c.display_name
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
                    'success': True,
                    'users': enhanced_users,
                    'total_count': len(enhanced_users)
                }), 200
            
            # Get total count for pagination
            count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"
            total_items_result = list(cosmos_user_settings_container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            total_items = total_items_result[0] if total_items_result and isinstance(total_items_result[0], int) else 0
            
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
    @control_center_admin_required
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
    @control_center_admin_required
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
    @control_center_admin_required
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

    # Group Management APIs
    @app.route('/api/admin/control-center/groups', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
    def api_get_all_groups():
        """
        Get all groups with their activity data and metrics.
        Supports pagination and filtering.
        """
        try:
            page = int(request.args.get('page', 1))
            per_page = min(int(request.args.get('per_page', 50)), 100)  # Max 100 per page
            search = request.args.get('search', '').strip()
            status_filter = request.args.get('status_filter', 'all')  # all, active, locked, etc.
            force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
            export_all = request.args.get('all', 'false').lower() == 'true'  # For CSV export
            
            # Build query with filters
            query_conditions = []
            parameters = []
            
            if search:
                query_conditions.append("(CONTAINS(LOWER(c.name), @search) OR CONTAINS(LOWER(c.description), @search))")
                parameters.append({"name": "@search", "value": search.lower()})
            
            # Note: status filtering would need to be implemented based on business logic
            # For now, we'll get all groups and filter client-side if needed
            
            where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"
            
            if export_all:
                # For CSV export, get all groups without pagination
                groups_query = f"""
                    SELECT *
                    FROM c 
                    WHERE {where_clause}
                    ORDER BY c.name
                """
                
                groups = list(cosmos_groups_container.query_items(
                    query=groups_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                # Enhance group data with activity information
                enhanced_groups = []
                for group in groups:
                    enhanced_group = enhance_group_with_activity(group, force_refresh=force_refresh)
                    enhanced_groups.append(enhanced_group)
                
                return jsonify({
                    'success': True,
                    'groups': enhanced_groups,
                    'total_count': len(enhanced_groups)
                }), 200
            
            # Get total count for pagination
            count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"
            total_items_result = list(cosmos_groups_container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            total_items = total_items_result[0] if total_items_result and isinstance(total_items_result[0], int) else 0
            
            # Calculate pagination
            offset = (page - 1) * per_page
            total_pages = (total_items + per_page - 1) // per_page
            
            # Get paginated results
            groups_query = f"""
                SELECT *
                FROM c 
                WHERE {where_clause}
                ORDER BY c.name
                OFFSET {offset} LIMIT {per_page}
            """
            
            groups = list(cosmos_groups_container.query_items(
                query=groups_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            # Enhance group data with activity information
            enhanced_groups = []
            for group in groups:
                enhanced_group = enhance_group_with_activity(group, force_refresh=force_refresh)
                enhanced_groups.append(enhanced_group)
            
            return jsonify({
                'groups': enhanced_groups,
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
            current_app.logger.error(f"Error getting groups: {e}")
            return jsonify({'error': 'Failed to retrieve groups'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/status', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
    def api_update_group_status(group_id):
        """
        Update group status (active, locked, inactive, etc.)
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
                
            status = data.get('status')
            if not status:
                return jsonify({'error': 'Status is required'}), 400
                
            # Get the group
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
                
            # Update group status (you may need to implement your own status logic)
            group['status'] = status
            group['modifiedDate'] = datetime.utcnow().isoformat()
            
            # Update in database
            cosmos_groups_container.upsert_item(group)
            
            # Log admin action
            admin_user = session.get('user', {})
            log_event("[ControlCenter] Group Status Update", {
                "admin_user": admin_user.get('preferred_username', 'unknown'),
                "group_id": group_id,
                "group_name": group.get('name'),
                "new_status": status
            })
            
            return jsonify({'message': 'Group status updated successfully'}), 200
            
        except Exception as e:
            current_app.logger.error(f"Error updating group status: {e}")
            return jsonify({'error': 'Failed to update group status'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
    def api_get_group_details_admin(group_id):
        """
        Get detailed information about a specific group
        """
        try:
            # Get the group
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Enhance with activity data
            enhanced_group = enhance_group_with_activity(group)
            
            return jsonify(enhanced_group), 200
            
        except Exception as e:
            current_app.logger.error(f"Error getting group details: {e}")
            return jsonify({'error': 'Failed to retrieve group details'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
    def api_delete_group_admin(group_id):
        """
        Delete a group and optionally its documents
        """
        try:
            data = request.get_json() or {}
            delete_documents = data.get('delete_documents', True)  # Default to True for safety
            
            # Get the group first
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
                
            # Initialize docs list
            docs_to_delete = []
            
            # If requested, delete all group documents
            if delete_documents:
                # Delete from group_documents container
                docs_query = "SELECT c.id FROM c WHERE c.group_id = @group_id"
                docs_params = [{"name": "@group_id", "value": group_id}]
                
                docs_to_delete = list(cosmos_group_documents_container.query_items(
                    query=docs_query,
                    parameters=docs_params,
                    enable_cross_partition_query=True
                ))
                
                for doc in docs_to_delete:
                    try:
                        cosmos_group_documents_container.delete_item(
                            item=doc['id'], 
                            partition_key=doc['id']
                        )
                    except Exception as doc_e:
                        current_app.logger.warning(f"Failed to delete document {doc['id']}: {doc_e}")
                
                # Delete files from Azure Storage
                try:
                    storage_client = CLIENTS.get("storage_account_office_docs_client")
                    if storage_client:
                        container_client = storage_client.get_container_client(storage_account_user_documents_container_name)
                        group_folder_prefix = f"group-documents/{group_id}/"
                        
                        blob_list = container_client.list_blobs(name_starts_with=group_folder_prefix)
                        for blob in blob_list:
                            try:
                                container_client.delete_blob(blob.name)
                            except Exception as blob_e:
                                current_app.logger.warning(f"Failed to delete blob {blob.name}: {blob_e}")
                except Exception as storage_e:
                    current_app.logger.warning(f"Error deleting storage files for group {group_id}: {storage_e}")
            
            # Delete the group
            cosmos_groups_container.delete_item(item=group_id, partition_key=group_id)
            
            # Log admin action
            admin_user = session.get('user', {})
            log_event("[ControlCenter] Group Deletion", {
                "admin_user": admin_user.get('preferred_username', 'unknown'),
                "group_id": group_id,
                "group_name": group.get('name'),
                "deleted_documents": delete_documents,
                "document_count": len(docs_to_delete)
            })
            
            return jsonify({'message': 'Group deleted successfully'}), 200
            
        except Exception as e:
            current_app.logger.error(f"Error deleting group: {e}")
            return jsonify({'error': 'Failed to delete group'}), 500

    # Public Workspaces API
    @app.route('/api/admin/control-center/public-workspaces', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
    def api_control_center_public_workspaces():
        """
        Get paginated list of public workspaces with activity data for control center management.
        Similar to groups endpoint but for public workspaces.
        """
        try:
            # Parse request parameters
            page = int(request.args.get('page', 1))
            per_page = min(int(request.args.get('per_page', 50)), 100)  # Max 100 per page
            search_term = request.args.get('search', '').strip()
            status_filter = request.args.get('status_filter', 'all')
            force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
            export_all = request.args.get('all', 'false').lower() == 'true'  # For CSV export
            
            # Calculate offset (only needed if not exporting all)
            offset = (page - 1) * per_page if not export_all else 0
            
            # Base query for public workspaces
            if search_term:
                # Search in workspace name and description
                query = """
                    SELECT * FROM c 
                    WHERE CONTAINS(LOWER(c.name), @search_term) 
                    OR CONTAINS(LOWER(c.description), @search_term)
                    ORDER BY c.name
                """
                parameters = [{"name": "@search_term", "value": search_term.lower()}]
            else:
                # Get all workspaces
                query = "SELECT * FROM c ORDER BY c.name"
                parameters = []
            
            # Execute query to get all matching workspaces
            all_workspaces = list(cosmos_public_workspaces_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            # Apply status filter if specified
            if status_filter != 'all':
                # For now, we'll treat all workspaces as 'active'
                # This can be enhanced later with actual status logic
                if status_filter != 'active':
                    all_workspaces = []
            
            # Calculate pagination
            total_count = len(all_workspaces)
            total_pages = math.ceil(total_count / per_page) if per_page > 0 else 0
            
            # Get the workspaces for current page or all for export
            if export_all:
                workspaces_page = all_workspaces  # Get all workspaces for CSV export
            else:
                workspaces_page = all_workspaces[offset:offset + per_page]
            
            # Enhance each workspace with activity data
            enhanced_workspaces = []
            for workspace in workspaces_page:
                try:
                    enhanced_workspace = enhance_public_workspace_with_activity(workspace, force_refresh=force_refresh)
                    enhanced_workspaces.append(enhanced_workspace)
                except Exception as enhance_e:
                    current_app.logger.error(f"Error enhancing workspace {workspace.get('id', 'unknown')}: {enhance_e}")
                    # Include the original workspace if enhancement fails
                    enhanced_workspaces.append(workspace)
            
            # Return response (paginated or all for export)
            if export_all:
                return jsonify({
                    'success': True,
                    'workspaces': enhanced_workspaces,
                    'total_count': total_count,
                    'filters': {
                        'search': search_term,
                        'status_filter': status_filter,
                        'force_refresh': force_refresh
                    }
                })
            else:
                return jsonify({
                    'workspaces': enhanced_workspaces,
                    'pagination': {
                        'page': page,
                        'per_page': per_page,
                        'total_count': total_count,
                        'total_pages': total_pages,
                        'has_next': page < total_pages,
                        'has_prev': page > 1
                    },
                    'filters': {
                        'search': search_term,
                        'status_filter': status_filter,
                        'force_refresh': force_refresh
                    }
                })
            
        except Exception as e:
            current_app.logger.error(f"Error getting public workspaces for control center: {e}")
            return jsonify({'error': 'Failed to retrieve public workspaces'}), 500

    # Activity Trends API
    @app.route('/api/admin/control-center/activity-trends', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required
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
                    debug_print(f"🔍 [Activity Trends API] Custom date range: {start_date} to {end_date} ({days} days)")
                except ValueError:
                    return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD format.'}), 400
            else:
                # Use days parameter (default behavior)
                days = int(request.args.get('days', 7))
                # Set end_date to end of current day to include all of today's records
                end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                start_date = (end_date - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
                debug_print(f"🔍 [Activity Trends API] Request for {days} days: {start_date} to {end_date}")
            
            # Get activity data
            activity_data = get_activity_trends_data(start_date, end_date)
            
            debug_print(f"🔍 [Activity Trends API] Returning data: {activity_data}")
            
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
    @control_center_admin_required
    def api_export_activity_trends():
        """
        Export activity trends raw data as CSV file based on selected charts and date range.
        Returns detailed records with user information instead of aggregated counts.
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
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Determining date range")
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
            
            # Get raw activity data using new function
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Calling get_raw_activity_trends_data")
            raw_data = get_raw_activity_trends_data(
                start_date_obj,
                end_date_obj,
                charts
            )
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Raw data retrieved: {len(raw_data) if raw_data else 0} chart types")
            
            # Generate CSV content with all data types
            import io
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write data for each chart type
            debug_print(f"🔍 [CSV DEBUG] Processing {len(charts)} chart types: {charts}")
            for chart_type in charts:
                debug_print(f"🔍 [CSV DEBUG] Processing chart type: {chart_type}")
                if chart_type in raw_data and raw_data[chart_type]:
                    debug_print(f"🔍 [CSV DEBUG] Found {len(raw_data[chart_type])} records for {chart_type}")
                    # Add section header
                    writer.writerow([])  # Empty row for separation
                    section_header = f"=== {chart_type.upper()} DATA ==="
                    debug_print(f"🔍 [CSV DEBUG] Writing section header: {section_header}")
                    writer.writerow([section_header])
                    
                    # Write headers and data based on chart type
                    if chart_type == 'logins':
                        debug_print(f"🔍 [CSV DEBUG] Writing login headers for {chart_type}")
                        writer.writerow(['Display Name', 'Email', 'User ID', 'Login Time'])
                        record_count = 0
                        for record in raw_data[chart_type]:
                            record_count += 1
                            if record_count <= 3:  # Debug first 3 records
                                debug_print(f"🔍 [CSV DEBUG] Login record {record_count} structure: {list(record.keys())}")
                                debug_print(f"🔍 [CSV DEBUG] Login record {record_count} data: {record}")
                            writer.writerow([
                                record.get('display_name', ''),
                                record.get('email', ''),
                                record.get('user_id', ''),
                                record.get('login_time', '')
                            ])
                        debug_print(f"🔍 [CSV DEBUG] Finished writing {record_count} login records")
                    
                    elif chart_type in ['documents', 'personal_documents', 'group_documents', 'public_documents']:
                        # Handle all document types with same structure
                        debug_print(f"🔍 [CSV DEBUG] Writing document headers for {chart_type}")
                        writer.writerow([
                            'Display Name', 'Email', 'User ID', 'Document ID', 'Document Filename', 
                            'Document Title', 'Document Page Count', 'Document Size in AI Search', 
                            'Document Size in Storage Account', 'Upload Date', 'Document Type'
                        ])
                        record_count = 0
                        for record in raw_data[chart_type]:
                            record_count += 1
                            if record_count <= 3:  # Log first 3 records for debugging
                                debug_print(f"🔍 [CSV DEBUG] Writing {chart_type} record {record_count}: {record.get('filename', 'No filename')}")
                            writer.writerow([
                                record.get('display_name', ''),
                                record.get('email', ''),
                                record.get('user_id', ''),
                                record.get('document_id', ''),
                                record.get('filename', ''),
                                record.get('title', ''),
                                record.get('page_count', ''),
                                record.get('ai_search_size', ''),
                                record.get('storage_account_size', ''),
                                record.get('upload_date', ''),
                                record.get('document_type', chart_type.replace('_documents', '').title())
                            ])
                        debug_print(f"🔍 [CSV DEBUG] Finished writing {record_count} records for {chart_type}")
                    
                    elif chart_type == 'chats':
                        debug_print(f"🔍 [CSV DEBUG] Writing chat headers for {chart_type}")
                        writer.writerow([
                            'Display Name', 'Email', 'User ID', 'Chat ID', 'Chat Title', 
                            'Number of Messages', 'Total Size (characters)', 'Created Date'
                        ])
                        record_count = 0
                        for record in raw_data[chart_type]:
                            record_count += 1
                            if record_count <= 3:  # Debug first 3 records
                                debug_print(f"🔍 [CSV DEBUG] Chat record {record_count} structure: {list(record.keys())}")
                                debug_print(f"🔍 [CSV DEBUG] Chat record {record_count} data: {record}")
                            writer.writerow([
                                record.get('display_name', ''),
                                record.get('email', ''),
                                record.get('user_id', ''),
                                record.get('chat_id', ''),
                                record.get('chat_title', ''),
                                record.get('message_count', ''),
                                record.get('total_size', ''),
                                record.get('created_date', '')
                            ])
                        debug_print(f"🔍 [CSV DEBUG] Finished writing {record_count} chat records")
                else:
                    debug_print(f"🔍 [CSV DEBUG] No data found for {chart_type} - available keys: {list(raw_data.keys()) if raw_data else 'None'}")
                    
            # Add final debug info
            debug_print(f"🔍 [CSV DEBUG] Finished processing all chart types. Raw data summary:")
            for key, value in raw_data.items():
                if isinstance(value, list):
                    debug_print(f"🔍 [CSV DEBUG] - {key}: {len(value)} records")
                else:
                    debug_print(f"🔍 [CSV DEBUG] - {key}: {type(value)} - {value}")
            
            csv_content = output.getvalue()
            debug_print(f"🔍 [CSV DEBUG] Generated CSV content length: {len(csv_content)} characters")
            debug_print(f"🔍 [CSV DEBUG] CSV content preview (first 500 chars): {csv_content[:500]}")
            output.close()
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"activity_trends_raw_export_{timestamp}.csv"
            
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
    @control_center_admin_required
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
                            'documents': 'Documents',
                            'personal_documents': 'Personal Documents',
                            'group_documents': 'Group Documents',
                            'public_documents': 'Public Documents'
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
    @control_center_admin_required
    def api_refresh_control_center_data():
        """
        Refresh all Control Center metrics data and update admin timestamp.
        This will recalculate all user metrics and cache them in user settings.
        """
        try:
            debug_print("🔄 [REFRESH DEBUG] Starting Control Center data refresh...")
            current_app.logger.info("Starting Control Center data refresh...")
            
            # Check if request has specific user_id
            from flask import request
            try:
                request_data = request.get_json(force=True) or {}
            except:
                # Handle case where no JSON body is sent
                request_data = {}
                
            specific_user_id = request_data.get('user_id')
            force_refresh = request_data.get('force_refresh', False)
            
            debug_print(f"🔄 [REFRESH DEBUG] Request data: user_id={specific_user_id}, force_refresh={force_refresh}")
            
            # Get all users to refresh their metrics
            debug_print("🔄 [REFRESH DEBUG] Querying all users...")
            users_query = "SELECT c.id, c.email, c.display_name, c.lastUpdated, c.settings FROM c"
            all_users = list(cosmos_user_settings_container.query_items(
                query=users_query,
                enable_cross_partition_query=True
            ))
            debug_print(f"🔄 [REFRESH DEBUG] Found {len(all_users)} users to process")
            
            refreshed_count = 0
            failed_count = 0
            
            # Refresh metrics for each user
            debug_print("🔄 [REFRESH DEBUG] Starting user refresh loop...")
            for user in all_users:
                try:
                    user_id = user.get('id')
                    debug_print(f"🔄 [REFRESH DEBUG] Processing user {user_id}")
                    
                    # Force refresh of metrics for this user
                    enhanced_user = enhance_user_with_activity(user, force_refresh=True)
                    refreshed_count += 1
                    
                    debug_print(f"✅ [REFRESH DEBUG] Successfully refreshed user {user_id}")
                    current_app.logger.debug(f"Refreshed metrics for user {user_id}")
                except Exception as user_error:
                    failed_count += 1
                    debug_print(f"❌ [REFRESH DEBUG] Failed to refresh user {user.get('id')}: {user_error}")
                    debug_print(f"❌ [REFRESH DEBUG] User error traceback:")
                    import traceback
                    debug_print(traceback.format_exc())
                    current_app.logger.error(f"Failed to refresh metrics for user {user.get('id')}: {user_error}")
            
            debug_print(f"🔄 [REFRESH DEBUG] User refresh loop completed. Refreshed: {refreshed_count}, Failed: {failed_count}")
            
            # Refresh metrics for all groups
            debug_print("🔄 [REFRESH DEBUG] Starting group refresh...")
            groups_refreshed_count = 0
            groups_failed_count = 0
            
            try:
                groups_query = "SELECT * FROM c"
                all_groups = list(cosmos_groups_container.query_items(
                    query=groups_query,
                    enable_cross_partition_query=True
                ))
                debug_print(f"🔄 [REFRESH DEBUG] Found {len(all_groups)} groups to process")
                
                # Refresh metrics for each group
                for group in all_groups:
                    try:
                        group_id = group.get('id')
                        debug_print(f"🔄 [REFRESH DEBUG] Processing group {group_id}")
                        
                        # Force refresh of metrics for this group
                        enhanced_group = enhance_group_with_activity(group, force_refresh=True)
                        groups_refreshed_count += 1
                        
                        debug_print(f"✅ [REFRESH DEBUG] Successfully refreshed group {group_id}")
                        current_app.logger.debug(f"Refreshed metrics for group {group_id}")
                    except Exception as group_error:
                        groups_failed_count += 1
                        debug_print(f"❌ [REFRESH DEBUG] Failed to refresh group {group.get('id')}: {group_error}")
                        debug_print(f"❌ [REFRESH DEBUG] Group error traceback:")
                        import traceback
                        debug_print(traceback.format_exc())
                        current_app.logger.error(f"Failed to refresh metrics for group {group.get('id')}: {group_error}")
                        
            except Exception as groups_error:
                debug_print(f"❌ [REFRESH DEBUG] Error querying groups: {groups_error}")
                current_app.logger.error(f"Error querying groups for refresh: {groups_error}")
            
            debug_print(f"🔄 [REFRESH DEBUG] Group refresh loop completed. Refreshed: {groups_refreshed_count}, Failed: {groups_failed_count}")
            
            # Update admin settings with refresh timestamp
            debug_print("🔄 [REFRESH DEBUG] Updating admin settings...")
            try:
                from functions_settings import get_settings, update_settings
                
                settings = get_settings()
                if settings:
                    settings['control_center_last_refresh'] = datetime.now(timezone.utc).isoformat()
                    update_success = update_settings(settings)
                    
                    if not update_success:
                        debug_print("⚠️ [REFRESH DEBUG] Failed to update admin settings")
                        current_app.logger.warning("Failed to update admin settings with refresh timestamp")
                    else:
                        debug_print("✅ [REFRESH DEBUG] Admin settings updated successfully")
                        current_app.logger.info("Updated admin settings with refresh timestamp")
                else:
                    debug_print("⚠️ [REFRESH DEBUG] Could not get admin settings")
                    
            except Exception as admin_error:
                debug_print(f"❌ [REFRESH DEBUG] Admin settings update failed: {admin_error}")
                current_app.logger.error(f"Error updating admin settings: {admin_error}")
            
            debug_print(f"🎉 [REFRESH DEBUG] Refresh completed! Users - Refreshed: {refreshed_count}, Failed: {failed_count}. Groups - Refreshed: {groups_refreshed_count}, Failed: {groups_failed_count}")
            current_app.logger.info(f"Control Center data refresh completed. Users: {refreshed_count} refreshed, {failed_count} failed. Groups: {groups_refreshed_count} refreshed, {groups_failed_count} failed")
            
            return jsonify({
                'success': True,
                'message': 'Control Center data refreshed successfully',
                'refreshed_users': refreshed_count,
                'failed_users': failed_count,
                'refreshed_groups': groups_refreshed_count,
                'failed_groups': groups_failed_count,
                'refresh_timestamp': datetime.now(timezone.utc).isoformat()
            }), 200
            
        except Exception as e:
            debug_print(f"💥 [REFRESH DEBUG] MAJOR ERROR in refresh endpoint: {e}")
            debug_print("💥 [REFRESH DEBUG] Full traceback:")
            import traceback
            debug_print(traceback.format_exc())
            current_app.logger.error(f"Error refreshing Control Center data: {e}")
            return jsonify({'error': 'Failed to refresh data'}), 500
    
    # Get refresh status API
    @app.route('/api/admin/control-center/refresh-status', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @control_center_admin_required  
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