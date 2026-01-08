# route_backend_control_center.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_logging import *
from functions_activity_logging import *
from functions_approvals import *
from functions_documents import update_document, delete_document, delete_document_chunks
from functions_group import delete_group
from utils_cache import invalidate_group_search_cache
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
                    debug_print(f"Using cached metrics for user {user.get('id')}")
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
                    debug_print(f"Error using cached metrics for user {user.get('id')}: {cache_e}")
            
            # If no cached metrics and not forcing refresh, return with default/empty metrics
            # Do NOT include enhanced_citation_enabled in user data - frontend gets it from app settings
            debug_print(f"No cached metrics for user {user.get('id')}, returning default values (use refresh button to calculate)")
            return enhanced
            
        debug_print(f"Force refresh requested - calculating fresh metrics for user {user.get('id')}")
        
        
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
                        
                        debug_print(f"Messages batch {i//batch_size + 1}: {batch_messages} messages, {batch_size or 0} bytes")
                                
                    except Exception as msg_e:
                        debug_print(f"Could not query message sizes for batch {i//batch_size + 1}: {msg_e}")
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
                                debug_print(f"Could not query individual conversation {conv_id}: {individual_e}")
                                continue
                
                enhanced['activity']['chat_metrics']['total_messages'] = total_messages
                enhanced['activity']['chat_metrics']['total_message_size'] = total_message_size
                debug_print(f"Final chat metrics for user {user.get('id')}: {total_messages} messages, {total_message_size} bytes")
            
        except Exception as e:
            debug_print(f"Could not get chat metrics for user {user.get('id')}: {e}")
        
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
            debug_print(f"Could not get login metrics for user {user.get('id')}: {e}")
        
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
            enhanced['activity']['document_metrics']['ai_search_size'] = total_pages * 22 * 1024  # 22KB per page
            
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
                            debug_print(f"Storage blob {blob.name}: {blob.size} bytes")
                        
                        debug_print(f"💾 [STORAGE DEBUG] Found {blob_count} blobs, total size: {total_storage_size} bytes")
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        debug_print(f"Total storage size for user {user.get('id')}: {total_storage_size} bytes")
                    else:
                        debug_print(f"💾 [STORAGE DEBUG] Storage client NOT available for user {user.get('id')}")
                        debug_print(f"Storage client not available for user {user.get('id')}")
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
                        debug_print(f"Estimated storage size for user {user.get('id')}: {total_storage_size} bytes")
                    
                except Exception as storage_e:
                    debug_print(f"❌ [STORAGE DEBUG] Storage calculation failed for user {user.get('id')}: {storage_e}")
                    debug_print(f"Could not calculate storage size for user {user.get('id')}: {storage_e}")
                    # Set to 0 if we can't calculate
                    enhanced['activity']['document_metrics']['storage_account_size'] = 0
                
        except Exception as e:
            debug_print(f"Could not get document metrics for user {user.get('id')}: {e}")
        
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
                    debug_print(f"Successfully cached metrics for user {user.get('id')}")
                else:
                    debug_print(f"Failed to cache metrics for user {user.get('id')}")
                    
            except Exception as cache_save_e:
                debug_print(f"Error saving metrics cache for user {user.get('id')}: {cache_save_e}")
        
        return enhanced
        
    except Exception as e:
        debug_print(f"Error enhancing user data: {e}")
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
            'owner_name': owner_info.get('displayName') or owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'owner_email': owner_info.get('email', ''),
            'created_by': owner_info.get('displayName') or owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'document_count': 0,  # Will be updated from database
            'member_count': len(workspace.get('admins', [])) + len(workspace.get('documentManagers', [])) + (1 if owner_info else 0),  # Total members including owner
            'storage_size': 0,  # Will be updated from storage account
            'last_activity': None,  # Will be updated from public_documents
            'recent_activity_count': 0,  # Will be calculated
            'status': workspace.get('status', 'active'),  # Read from workspace document, default to 'active'
            'statusHistory': workspace.get('statusHistory', []),  # Include status change history
            
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
                        
                        # Apply cached activity metrics if available
                        if 'last_activity' in cached_metrics:
                            enhanced['last_activity'] = cached_metrics['last_activity']
                        if 'recent_activity_count' in cached_metrics:
                            enhanced['recent_activity_count'] = cached_metrics['recent_activity_count']
                        
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
            ai_search_size = total_pages * 22 * 1024  # 22KB per page
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
                    'last_activity': enhanced.get('last_activity'),
                    'recent_activity_count': enhanced.get('recent_activity_count', 0),
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
        debug_print(f"Error enhancing public workspace data: {e}")
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
            'owner_name': owner_info.get('displayName') or owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'owner_email': owner_info.get('email', ''),
            'created_by': owner_info.get('displayName') or owner_info.get('display_name') or owner_info.get('name', 'Unknown'),
            'member_count': len(users_list),  # Owner is already included in users_list
            'document_count': 0,  # Will be updated from database
            'storage_size': 0,  # Will be updated from storage account
            'last_activity': None,  # Will be updated from group_documents
            'recent_activity_count': 0,  # Will be calculated
            'status': group.get('status', 'active'),  # Read from group document, default to 'active'
            'statusHistory': group.get('statusHistory', []),  # Include status change history
            
            # Keep nested structure for backward compatibility
            'activity': {
                'document_metrics': {
                    'total_documents': 0,
                    'ai_search_size': 0,  # pages × 80KB  
                    'storage_account_size': 0  # Actual file sizes from storage
                },
                'member_metrics': {
                    'total_members': len(users_list),  # Owner is already included in users_list
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
            # AI search size = pages × 22KB
            enhanced['activity']['document_metrics']['ai_search_size'] = total_pages * 22 * 1024  # 22KB per page
            
            debug_print(f"📄 [GROUP DOCUMENT DEBUG] Total documents for group {group_id}: {total_docs}")
            debug_print(f"📊 [GROUP AI SEARCH DEBUG] Total pages for group {group_id}: {total_pages}, AI search size: {total_pages * 22 * 1024} bytes")
            
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
                            debug_print(f"Group storage blob {blob.name}: {blob.size} bytes")
                        
                        debug_print(f"💾 [GROUP STORAGE DEBUG] Found {blob_count} blobs, total size: {total_storage_size} bytes")
                        enhanced['activity']['document_metrics']['storage_account_size'] = total_storage_size
                        enhanced['storage_size'] = total_storage_size  # Update flat field
                        debug_print(f"Total storage size for group {group_id}: {total_storage_size} bytes")
                    else:
                        debug_print(f"💾 [GROUP STORAGE DEBUG] Storage client NOT available for group {group_id}")
                        debug_print(f"Storage client not available for group {group_id}")
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
                        debug_print(f"Estimated storage size for group {group_id}: {total_storage_size} bytes")
                    
                except Exception as storage_e:
                    debug_print(f"❌ [GROUP STORAGE DEBUG] Storage calculation failed for group {group_id}: {storage_e}")
                    debug_print(f"Could not calculate storage size for group {group_id}: {storage_e}")
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
        debug_print(f"Error enhancing group data: {e}")
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
                'chats_created': 0,
                'chats_deleted': 0,
                'chats': 0,  # Keep for backward compatibility
                'personal_documents_created': 0,
                'personal_documents_deleted': 0,
                'group_documents_created': 0,
                'group_documents_deleted': 0,
                'public_documents_created': 0,
                'public_documents_deleted': 0,
                'personal_documents': 0,  # Keep for backward compatibility
                'group_documents': 0,     # Keep for backward compatibility
                'public_documents': 0,    # Keep for backward compatibility
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
        
        # Query 1: Get chat activity from activity logs (both creation and deletion)
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying conversations...")
            
            # Count conversation creations
            conversations_query = """
                SELECT c.timestamp, c.created_at
                FROM c 
                WHERE c.activity_type = 'conversation_creation'
                AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                   OR (c.created_at >= @start_date AND c.created_at <= @end_date))
            """
            
            conversations = list(cosmos_activity_logs_container.query_items(
                query=conversations_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(conversations)} conversation creation logs")
            
            for conv in conversations:
                timestamp = conv.get('timestamp') or conv.get('created_at')
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            conv_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                        else:
                            conv_date = timestamp
                        
                        date_key = conv_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['chats_created'] += 1
                            daily_data[date_key]['chats'] += 1  # Keep total for backward compatibility
                    except Exception as e:
                        debug_print(f"Could not parse conversation timestamp {timestamp}: {e}")
            
            # Count conversation deletions
            deletions_query = """
                SELECT c.timestamp, c.created_at
                FROM c 
                WHERE c.activity_type = 'conversation_deletion'
                AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                   OR (c.created_at >= @start_date AND c.created_at <= @end_date))
            """
            
            deletions = list(cosmos_activity_logs_container.query_items(
                query=deletions_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(deletions)} conversation deletion logs")
            
            for deletion in deletions:
                timestamp = deletion.get('timestamp') or deletion.get('created_at')
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            del_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                        else:
                            del_date = timestamp
                        
                        date_key = del_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            daily_data[date_key]['chats_deleted'] += 1
                    except Exception as e:
                        debug_print(f"Could not parse deletion timestamp {timestamp}: {e}")
                        
        except Exception as e:
            debug_print(f"Could not query conversation activity logs: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying chats: {e}")

        # Query 2: Get document activity from activity_logs (both creation and deletion)
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying documents from activity logs...")
            
            # Document creations
            documents_query = """
                SELECT c.timestamp, c.created_at, c.workspace_type
                FROM c 
                WHERE c.activity_type = 'document_creation'
                AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                   OR (c.created_at >= @start_date AND c.created_at <= @end_date))
            """
            
            docs = list(cosmos_activity_logs_container.query_items(
                query=documents_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(docs)} document creation logs")
            
            for doc in docs:
                timestamp = doc.get('timestamp') or doc.get('created_at')
                workspace_type = doc.get('workspace_type', 'personal')
                
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            doc_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                        else:
                            doc_date = timestamp
                        
                        date_key = doc_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            if workspace_type == 'group':
                                daily_data[date_key]['group_documents_created'] += 1
                                daily_data[date_key]['group_documents'] += 1
                            elif workspace_type == 'public':
                                daily_data[date_key]['public_documents_created'] += 1
                                daily_data[date_key]['public_documents'] += 1
                            else:
                                daily_data[date_key]['personal_documents_created'] += 1
                                daily_data[date_key]['personal_documents'] += 1
                            
                            daily_data[date_key]['documents'] += 1
                    except Exception as e:
                        debug_print(f"Could not parse document timestamp {timestamp}: {e}")
            
            # Document deletions
            deletions_query = """
                SELECT c.timestamp, c.created_at, c.workspace_type
                FROM c 
                WHERE c.activity_type = 'document_deletion'
                AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                   OR (c.created_at >= @start_date AND c.created_at <= @end_date))
            """
            
            doc_deletions = list(cosmos_activity_logs_container.query_items(
                query=deletions_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(doc_deletions)} document deletion logs")
            
            for doc in doc_deletions:
                timestamp = doc.get('timestamp') or doc.get('created_at')
                workspace_type = doc.get('workspace_type', 'personal')
                
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            doc_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                        else:
                            doc_date = timestamp
                        
                        date_key = doc_date.strftime('%Y-%m-%d')
                        if date_key in daily_data:
                            if workspace_type == 'group':
                                daily_data[date_key]['group_documents_deleted'] += 1
                            elif workspace_type == 'public':
                                daily_data[date_key]['public_documents_deleted'] += 1
                            else:
                                daily_data[date_key]['personal_documents_deleted'] += 1
                    except Exception as e:
                        debug_print(f"Could not parse document deletion timestamp {timestamp}: {e}")
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Total documents found: {len(docs)} created, {len(doc_deletions)} deleted")
                        
        except Exception as e:
            debug_print(f"Could not query document activity logs: {e}")
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
                        debug_print(f"Could not parse login timestamp {timestamp}: {e}")
                        
        except Exception as e:
            debug_print(f"Could not query activity logs for login data: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying logins: {e}")

        # Query 4: Get token usage from activity_logs (token_usage activity_type)
        try:
            debug_print("🔍 [ACTIVITY TRENDS DEBUG] Querying token usage...")
            
            token_usage_query = """
                SELECT c.timestamp, c.created_at, c.token_type, c.usage.total_tokens as token_count
                FROM c
                WHERE c.activity_type = 'token_usage'
                AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                   OR (c.created_at >= @start_date AND c.created_at <= @end_date))
            """
            
            token_activities = list(cosmos_activity_logs_container.query_items(
                query=token_usage_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Found {len(token_activities)} token_usage records")
            
            # Initialize token tracking structure
            token_daily_data = {}
            current_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            while current_date <= end_date:
                date_key = current_date.strftime('%Y-%m-%d')
                token_daily_data[date_key] = {
                    'embedding': 0,
                    'chat': 0
                }
                current_date += timedelta(days=1)
            
            for token_record in token_activities:
                timestamp = token_record.get('timestamp') or token_record.get('created_at')
                token_type = token_record.get('token_type', '')
                token_count = token_record.get('token_count', 0)
                
                if timestamp and token_type in ['embedding', 'chat']:
                    try:
                        if isinstance(timestamp, str):
                            token_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                        else:
                            token_date = timestamp
                        
                        date_key = token_date.strftime('%Y-%m-%d')
                        if date_key in token_daily_data:
                            token_daily_data[date_key][token_type] += token_count
                    except Exception as e:
                        debug_print(f"Could not parse token timestamp {timestamp}: {e}")
            
            debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Token daily data: {token_daily_data}")
                        
        except Exception as e:
            debug_print(f"Could not query activity logs for token usage: {e}")
            print(f"❌ [ACTIVITY TRENDS DEBUG] Error querying tokens: {e}")
            # Initialize empty token data on error
            token_daily_data = {}
            current_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            while current_date <= end_date:
                date_key = current_date.strftime('%Y-%m-%d')
                token_daily_data[date_key] = {'embedding': 0, 'chat': 0}
                current_date += timedelta(days=1)

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
            'chats_created': {},
            'chats_deleted': {},
            'documents': {},           # Keep for backward compatibility
            'personal_documents': {},  # Keep for backward compatibility
            'group_documents': {},     # Keep for backward compatibility
            'public_documents': {},    # Keep for backward compatibility
            'personal_documents_created': {},
            'personal_documents_deleted': {},
            'group_documents_created': {},
            'group_documents_deleted': {},
            'public_documents_created': {},
            'public_documents_deleted': {},
            'logins': {},
            'tokens': token_daily_data  # Token usage by type (embedding, chat)
        }
        
        for date_key, data in daily_data.items():
            result['chats'][date_key] = data['chats']
            result['chats_created'][date_key] = data['chats_created']
            result['chats_deleted'][date_key] = data['chats_deleted']
            result['documents'][date_key] = data['documents']
            result['personal_documents'][date_key] = data['personal_documents']
            result['group_documents'][date_key] = data['group_documents']
            result['public_documents'][date_key] = data['public_documents']
            result['personal_documents_created'][date_key] = data['personal_documents_created']
            result['personal_documents_deleted'][date_key] = data['personal_documents_deleted']
            result['group_documents_created'][date_key] = data['group_documents_created']
            result['group_documents_deleted'][date_key] = data['group_documents_deleted']
            result['public_documents_created'][date_key] = data['public_documents_created']
            result['public_documents_deleted'][date_key] = data['public_documents_deleted']
            result['logins'][date_key] = data['logins']
        
        debug_print(f"🔍 [ACTIVITY TRENDS DEBUG] Final result: {result}")
        
        return result

    except Exception as e:
        debug_print(f"Error getting activity trends data: {e}")
        print(f"❌ [ACTIVITY TRENDS DEBUG] Fatal error: {e}")
        return {
            'chats': {},
            'documents': {},
            'personal_documents': {},
            'group_documents': {},
            'public_documents': {},
            'logins': {},
            'tokens': {}
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
        
        # 2. Document Data - From activity_logs container using document_creation activity_type
        # Personal Documents
        if 'personal_documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting personal document records from activity logs...")
            try:
                personal_docs_query = """
                    SELECT c.timestamp, c.created_at, c.user_id, c.document.document_id,
                           c.document.file_name, c.document.file_type, c.document.file_size_bytes,
                           c.document.page_count, c.document_metadata, c.embedding_usage
                    FROM c 
                    WHERE c.activity_type = 'document_creation'
                    AND c.workspace_type = 'personal'
                    AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                       OR (c.created_at >= @start_date AND c.created_at <= @end_date))
                """
                
                personal_docs = list(cosmos_activity_logs_container.query_items(
                    query=personal_docs_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                personal_document_records = []
                for doc in personal_docs:
                    user_id = doc.get('user_id', '')
                    user_info = get_user_info(user_id)
                    timestamp = doc.get('timestamp') or doc.get('created_at')
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                doc_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                            else:
                                doc_date = timestamp
                            
                            document_info = doc.get('document', {})
                            doc_metadata = doc.get('document_metadata', {})
                            pages = document_info.get('page_count', 0) or 0
                            
                            # Calculate AI Search size (pages × 80KB)
                            ai_search_size = pages * 80 * 1024 if pages else 0
                            
                            # Get file size from activity log
                            storage_size = document_info.get('file_size_bytes', 0) or 0
                            
                            personal_document_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'document_id': document_info.get('document_id', ''),
                                'filename': document_info.get('file_name', ''),
                                'title': doc_metadata.get('title', 'Unknown Title'),
                                'page_count': pages,
                                'ai_search_size': ai_search_size,
                                'storage_account_size': storage_size,
                                'upload_date': doc_date.strftime('%Y-%m-%d %H:%M:%S'),
                                'document_type': 'Personal'
                            })
                        except Exception as e:
                            debug_print(f"Could not parse personal document timestamp {timestamp}: {e}")
                
                result['personal_documents'] = personal_document_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(personal_document_records)} personal document records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting personal document data: {e}")
                result['personal_documents'] = []
        
        # Group Documents
        if 'group_documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting group document records from activity logs...")
            try:
                group_docs_query = """
                    SELECT c.timestamp, c.created_at, c.user_id, c.document.document_id,
                           c.document.file_name, c.document.file_type, c.document.file_size_bytes,
                           c.document.page_count, c.document_metadata, c.embedding_usage,
                           c.workspace_context.group_id
                    FROM c 
                    WHERE c.activity_type = 'document_creation'
                    AND c.workspace_type = 'group'
                    AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                       OR (c.created_at >= @start_date AND c.created_at <= @end_date))
                """
                
                group_docs = list(cosmos_activity_logs_container.query_items(
                    query=group_docs_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                group_document_records = []
                for doc in group_docs:
                    user_id = doc.get('user_id', '')
                    user_info = get_user_info(user_id)
                    timestamp = doc.get('timestamp') or doc.get('created_at')
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                doc_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                            else:
                                doc_date = timestamp
                            
                            document_info = doc.get('document', {})
                            doc_metadata = doc.get('document_metadata', {})
                            pages = document_info.get('page_count', 0) or 0
                            
                            # Calculate AI Search size (pages × 80KB)
                            ai_search_size = pages * 80 * 1024 if pages else 0
                            
                            # Get file size from activity log
                            storage_size = document_info.get('file_size_bytes', 0) or 0
                            
                            group_document_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'document_id': document_info.get('document_id', ''),
                                'filename': document_info.get('file_name', ''),
                                'title': doc_metadata.get('title', 'Unknown Title'),
                                'page_count': pages,
                                'ai_search_size': ai_search_size,
                                'storage_account_size': storage_size,
                                'upload_date': doc_date.strftime('%Y-%m-%d %H:%M:%S'),
                                'document_type': 'Group'
                            })
                        except Exception as e:
                            debug_print(f"Could not parse group document timestamp {timestamp}: {e}")
                
                result['group_documents'] = group_document_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(group_document_records)} group document records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting group document data: {e}")
                result['group_documents'] = []
        
        # Public Documents
        if 'public_documents' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting public document records from activity logs...")
            try:
                public_docs_query = """
                    SELECT c.timestamp, c.created_at, c.user_id, c.document.document_id,
                           c.document.file_name, c.document.file_type, c.document.file_size_bytes,
                           c.document.page_count, c.document_metadata, c.embedding_usage,
                           c.workspace_context.public_workspace_id
                    FROM c 
                    WHERE c.activity_type = 'document_creation'
                    AND c.workspace_type = 'public'
                    AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                       OR (c.created_at >= @start_date AND c.created_at <= @end_date))
                """
                
                public_docs = list(cosmos_activity_logs_container.query_items(
                    query=public_docs_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                public_document_records = []
                for doc in public_docs:
                    user_id = doc.get('user_id', '')
                    user_info = get_user_info(user_id)
                    timestamp = doc.get('timestamp') or doc.get('created_at')
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                doc_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                            else:
                                doc_date = timestamp
                            
                            document_info = doc.get('document', {})
                            doc_metadata = doc.get('document_metadata', {})
                            pages = document_info.get('page_count', 0) or 0
                            
                            # Calculate AI Search size (pages × 80KB)
                            ai_search_size = pages * 80 * 1024 if pages else 0
                            
                            # Get file size from activity log
                            storage_size = document_info.get('file_size_bytes', 0) or 0
                            
                            public_document_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'document_id': document_info.get('document_id', ''),
                                'filename': document_info.get('file_name', ''),
                                'title': doc_metadata.get('title', 'Unknown Title'),
                                'page_count': pages,
                                'ai_search_size': ai_search_size,
                                'storage_account_size': storage_size,
                                'upload_date': doc_date.strftime('%Y-%m-%d %H:%M:%S'),
                                'document_type': 'Public'
                            })
                        except Exception as e:
                            debug_print(f"Could not parse public document timestamp {timestamp}: {e}")
                
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
        
        # 3. Chat Data - From activity_logs container using conversation_creation activity_type
        if 'chats' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting chat records from activity logs...")
            try:
                conversations_query = """
                    SELECT c.timestamp, c.created_at, c.user_id, 
                           c.conversation.conversation_id as conversation_id, 
                           c.conversation.title as conversation_title
                    FROM c 
                    WHERE c.activity_type = 'conversation_creation'
                    AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                       OR (c.created_at >= @start_date AND c.created_at <= @end_date))
                """
                
                conversations = list(cosmos_activity_logs_container.query_items(
                    query=conversations_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                chat_records = []
                for conv in conversations:
                    user_id = conv.get('user_id', '')
                    user_info = get_user_info(user_id)
                    conversation_id = conv.get('conversation_id', '')
                    conversation_title = conv.get('conversation_title', '')
                    timestamp = conv.get('timestamp') or conv.get('created_at')
                    
                    # Get message count and total size for this conversation (still from messages container)
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
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                conv_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                            else:
                                conv_date = timestamp
                            
                            created_date_str = conv_date.strftime('%Y-%m-%d %H:%M:%S')
                            
                            chat_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'chat_id': conversation_id,
                                'chat_title': conversation_title,
                                'message_count': message_count,
                                'total_size': total_size,
                                'created_date': created_date_str
                            })
                        except Exception as e:
                            debug_print(f"Could not parse conversation timestamp {timestamp}: {e}")
                
                result['chats'] = chat_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(chat_records)} chat records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting chat data: {e}")
                result['chats'] = []
        
        # 4. Token Usage Data - From activity_logs container using token_usage activity_type
        if 'tokens' in charts:
            debug_print("🔍 [RAW ACTIVITY DEBUG] Getting token usage records from activity logs...")
            try:
                tokens_query = """
                    SELECT c.timestamp, c.created_at, c.user_id, c.token_type,
                           c.usage.model as model_name,
                           c.usage.prompt_tokens as prompt_tokens, 
                           c.usage.completion_tokens as completion_tokens, 
                           c.usage.total_tokens as total_tokens
                    FROM c 
                    WHERE c.activity_type = 'token_usage'
                    AND ((c.timestamp >= @start_date AND c.timestamp <= @end_date)
                       OR (c.created_at >= @start_date AND c.created_at <= @end_date))
                """
                
                token_activities = list(cosmos_activity_logs_container.query_items(
                    query=tokens_query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                token_records = []
                for token_log in token_activities:
                    user_id = token_log.get('user_id', '')
                    user_info = get_user_info(user_id)
                    timestamp = token_log.get('timestamp') or token_log.get('created_at')
                    token_type = token_log.get('token_type', 'unknown')
                    
                    if timestamp:
                        try:
                            if isinstance(timestamp, str):
                                token_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp)
                            else:
                                token_date = timestamp
                            
                            # Handle both chat and embedding tokens
                            prompt_tokens = token_log.get('prompt_tokens', 0) if token_type == 'chat' else 0
                            completion_tokens = token_log.get('completion_tokens', 0) if token_type == 'chat' else 0
                            
                            token_records.append({
                                'display_name': user_info['display_name'],
                                'email': user_info['email'],
                                'user_id': user_id,
                                'token_type': token_type,
                                'model_name': token_log.get('model_name', 'Unknown'),
                                'prompt_tokens': prompt_tokens,
                                'completion_tokens': completion_tokens,
                                'total_tokens': token_log.get('total_tokens', 0),
                                'timestamp': token_date.strftime('%Y-%m-%d %H:%M:%S')
                            })
                        except Exception as e:
                            debug_print(f"Could not parse token timestamp {timestamp}: {e}")
                
                result['tokens'] = token_records
                debug_print(f"🔍 [RAW ACTIVITY DEBUG] Found {len(token_records)} token usage records")
                
            except Exception as e:
                debug_print(f"❌ [RAW ACTIVITY DEBUG] Error getting token usage data: {e}")
                result['tokens'] = []
        
        debug_print(f"🔍 [RAW ACTIVITY DEBUG] Returning raw data with {len(result)} chart types")
        return result
        
    except Exception as e:
        debug_print(f"Error getting raw activity trends data: {e}")
        debug_print(f"❌ [RAW ACTIVITY DEBUG] Fatal error: {e}")
        return {}


def register_route_backend_control_center(app):
    
    # User Management APIs
    @app.route('/api/admin/control-center/users', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
            debug_print(f"Error getting users: {e}")
            return jsonify({'error': 'Failed to retrieve users'}), 500
    
    @app.route('/api/admin/control-center/users/<user_id>/access', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
            debug_print(f"Error updating user access: {e}")
            return jsonify({'error': 'Failed to update user access'}), 500
    
    @app.route('/api/admin/control-center/users/<user_id>/file-uploads', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
            debug_print(f"Error updating user file uploads: {e}")
            return jsonify({'error': 'Failed to update user file upload permissions'}), 500
    
    @app.route('/api/admin/control-center/users/<user_id>/delete-documents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_delete_user_documents_admin(user_id):
        """
        Create an approval request to delete all documents for a user.
        Requires approval from another admin.
        
        Body:
            reason (str): Explanation for deleting documents (required)
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for document deletion'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Validate user exists by trying to get their data from Cosmos
            try:
                user_doc = cosmos_user_settings_container.read_item(
                    item=user_id,
                    partition_key=user_id
                )
                user_email = user_doc.get('email', 'unknown')
                user_name = user_doc.get('display_name', user_email)
            except Exception:
                return jsonify({'error': 'User not found'}), 404
            
            # Create approval request using user_id as both group_id (for partition) and storing user_id in metadata
            from functions_approvals import create_approval_request, TYPE_DELETE_USER_DOCUMENTS
            approval = create_approval_request(
                request_type=TYPE_DELETE_USER_DOCUMENTS,
                group_id=user_id,  # Using user_id as partition key for user-related approvals
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'user_id': user_id,
                    'user_name': user_name,
                    'user_email': user_email
                }
            )
            
            # Log event
            log_event("[ControlCenter] Delete User Documents Request Created", {
                "admin_user": admin_email,
                "user_id": user_id,
                "user_email": user_email,
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Document deletion request created successfully. Awaiting approval from another admin.',
                'approval_id': approval['id']
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating user document deletion request: {e}")
            log_event("[ControlCenter] Delete User Documents Request Failed", {
                "error": str(e),
                "user_id": user_id
            })
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/admin/control-center/users/bulk-action', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
                    debug_print(f"Error updating user {user_id}: {e}")
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
            debug_print(f"Error performing bulk user action: {e}")
            return jsonify({'error': 'Failed to perform bulk action'}), 500

    # Group Management APIs
    @app.route('/api/admin/control-center/groups', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
            debug_print(f"Error getting groups: {e}")
            return jsonify({'error': 'Failed to retrieve groups'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/status', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_update_group_status(group_id):
        """
        Update group status (active, locked, upload_disabled, inactive)
        Tracks who made the change and when, logs to activity_logs
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
                
            new_status = data.get('status')
            reason = data.get('reason')  # Optional reason for the status change
            
            if not new_status:
                return jsonify({'error': 'Status is required'}), 400
            
            # Validate status values
            valid_statuses = ['active', 'locked', 'upload_disabled', 'inactive']
            if new_status not in valid_statuses:
                return jsonify({'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400
                
            # Get the group
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Get admin user info
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid', 'unknown')
            admin_email = admin_user.get('preferred_username', 'unknown')
            
            # Get old status for logging
            old_status = group.get('status', 'active')  # Default to 'active' if not set
            
            # Only update and log if status actually changed
            if old_status != new_status:
                # Update group status
                group['status'] = new_status
                group['modifiedDate'] = datetime.utcnow().isoformat()
                
                # Add status change metadata
                if 'statusHistory' not in group:
                    group['statusHistory'] = []
                
                group['statusHistory'].append({
                    'old_status': old_status,
                    'new_status': new_status,
                    'changed_by_user_id': admin_user_id,
                    'changed_by_email': admin_email,
                    'changed_at': datetime.utcnow().isoformat(),
                    'reason': reason
                })
                
                # Update in database
                cosmos_groups_container.upsert_item(group)
                
                # Log to activity_logs container for audit trail
                from functions_activity_logging import log_group_status_change
                log_group_status_change(
                    group_id=group_id,
                    group_name=group.get('name', 'Unknown'),
                    old_status=old_status,
                    new_status=new_status,
                    changed_by_user_id=admin_user_id,
                    changed_by_email=admin_email,
                    reason=reason
                )
                
                # Log admin action (legacy logging)
                log_event("[ControlCenter] Group Status Update", {
                    "admin_user": admin_email,
                    "admin_user_id": admin_user_id,
                    "group_id": group_id,
                    "group_name": group.get('name'),
                    "old_status": old_status,
                    "new_status": new_status,
                    "reason": reason
                })
                
                return jsonify({
                    'message': 'Group status updated successfully',
                    'old_status': old_status,
                    'new_status': new_status
                }), 200
            else:
                return jsonify({
                    'message': 'Group status unchanged',
                    'status': new_status
                }), 200
            
        except Exception as e:
            debug_print(f"Error updating group status: {e}")
            return jsonify({'error': 'Failed to update group status'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
            debug_print(f"Error getting group details: {e}")
            return jsonify({'error': 'Failed to retrieve group details'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_delete_group_admin(group_id):
        """
        Create an approval request to delete a group and all its documents.
        Requires approval from group owner or another admin.
        
        Body:
            reason (str): Explanation for deleting the group (required)
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for group deletion'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Validate group exists
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Create approval request
            approval = create_approval_request(
                request_type=TYPE_DELETE_GROUP,
                group_id=group_id,
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'group_name': group.get('name'),
                    'owner_id': group.get('owner', {}).get('id'),
                    'owner_email': group.get('owner', {}).get('email')
                }
            )
            
            # Log event
            log_event("[ControlCenter] Delete Group Request Created", {
                "admin_user": admin_email,
                "group_id": group_id,
                "group_name": group.get('name'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Group deletion request created and pending approval',
                'approval_id': approval['id'],
                'status': 'pending'
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating group deletion request: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/delete-documents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_delete_group_documents_admin(group_id):
        """
        Create an approval request to delete all documents in a group.
        Requires approval from group owner or another admin.
        
        Body:
            reason (str): Explanation for deleting documents (required)
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for document deletion'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Validate group exists
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Create approval request
            approval = create_approval_request(
                request_type=TYPE_DELETE_DOCUMENTS,
                group_id=group_id,
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'group_name': group.get('name')
                }
            )
            
            # Log event
            log_event("[ControlCenter] Delete Documents Request Created", {
                "admin_user": admin_email,
                "group_id": group_id,
                "group_name": group.get('name'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Document deletion request created and pending approval',
                'approval_id': approval['id'],
                'status': 'pending'
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating document deletion request: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/members', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_get_group_members_admin(group_id):
        """
        Get list of group members for ownership transfer selection
        """
        try:
            # Get the group
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Get member list with user details
            members = []
            for member in group.get('users', []):
                # Skip the current owner from the list
                if member.get('userId') == group.get('owner', {}).get('id'):
                    continue
                    
                members.append({
                    'userId': member.get('userId'),
                    'email': member.get('email', 'No email'),
                    'displayName': member.get('displayName', 'Unknown User')
                })
            
            return jsonify({'members': members}), 200
            
        except Exception as e:
            debug_print(f"Error getting group members: {e}")
            return jsonify({'error': 'Failed to retrieve group members'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/take-ownership', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_take_group_ownership(group_id):
        """
        Create an approval request for admin to take ownership of a group.
        Requires approval from group owner or another admin.
        
        Body:
            reason (str): Explanation for taking ownership (required)
        """
        try:
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            if not admin_user_id:
                return jsonify({'error': 'Could not identify admin user'}), 400
            
            # Get request body
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for ownership transfer'}), 400
            
            # Validate group exists
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Create approval request
            approval = create_approval_request(
                request_type=TYPE_TAKE_OWNERSHIP,
                group_id=group_id,
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'old_owner_id': group.get('owner', {}).get('id'),
                    'old_owner_email': group.get('owner', {}).get('email')
                }
            )
            
            # Log event
            log_event("[ControlCenter] Take Ownership Request Created", {
                "admin_user": admin_email,
                "group_id": group_id,
                "group_name": group.get('name'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Ownership transfer request created and pending approval',
                'approval_id': approval['id'],
                'status': 'pending'
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating take ownership request: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/transfer-ownership', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_transfer_group_ownership(group_id):
        """
        Create an approval request to transfer group ownership to another member.
        Requires approval from group owner or another admin.
        
        Body:
            newOwnerId (str): User ID of the new owner (required)
            reason (str): Explanation for ownership transfer (required)
        """
        try:
            data = request.get_json()
            new_owner_user_id = data.get('newOwnerId')
            reason = data.get('reason', '').strip()
            
            if not new_owner_user_id:
                return jsonify({'error': 'Missing newOwnerId'}), 400
            
            if not reason:
                return jsonify({'error': 'Reason is required for ownership transfer'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Get the group
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Find the new owner in members list
            new_owner_member = None
            for member in group.get('users', []):
                if member.get('userId') == new_owner_user_id:
                    new_owner_member = member
                    break
            
            if not new_owner_member:
                return jsonify({'error': 'Selected user is not a member of this group'}), 400
            
            # Create approval request
            approval = create_approval_request(
                request_type=TYPE_TRANSFER_OWNERSHIP,
                group_id=group_id,
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'new_owner_id': new_owner_user_id,
                    'new_owner_email': new_owner_member.get('email'),
                    'new_owner_name': new_owner_member.get('displayName'),
                    'old_owner_id': group.get('owner', {}).get('id'),
                    'old_owner_email': group.get('owner', {}).get('email')
                }
            )
            
            # Log event
            log_event("[ControlCenter] Transfer Ownership Request Created", {
                "admin_user": admin_email,
                "group_id": group_id,
                "group_name": group.get('name'),
                "new_owner": new_owner_member.get('email'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Ownership transfer request created and pending approval',
                'approval_id': approval['id'],
                'status': 'pending'
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating transfer ownership request: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/add-member', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_add_group_member(group_id):
        """
        Admin adds a member to a group (used by both single add and CSV bulk upload)
        """
        try:
            data = request.get_json()
            user_id = data.get('userId')
            # Support both 'name' (from CSV) and 'displayName' (from single add form)
            name = data.get('displayName') or data.get('name')
            email = data.get('email')
            role = data.get('role', 'user').lower()
            
            if not user_id or not name or not email:
                return jsonify({'error': 'Missing required fields: userId, name/displayName, email'}), 400
            
            # Validate role
            valid_roles = ['admin', 'document_manager', 'user']
            if role not in valid_roles:
                return jsonify({'error': f'Invalid role. Must be: {", ".join(valid_roles)}'}), 400
            
            admin_user = session.get('user', {})
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            
            # Get the group
            try:
                group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            except:
                return jsonify({'error': 'Group not found'}), 404
            
            # Check if user already exists (skip duplicate)
            existing_user = False
            for member in group.get('users', []):
                if member.get('userId') == user_id:
                    existing_user = True
                    break
            
            if existing_user:
                return jsonify({
                    'message': f'User {email} already exists in group',
                    'skipped': True
                }), 200
            
            # Add user to users array
            group.setdefault('users', []).append({
                'userId': user_id,
                'email': email,
                'displayName': name
            })
            
            # Add to appropriate role array
            if role == 'admin':
                if user_id not in group.get('admins', []):
                    group.setdefault('admins', []).append(user_id)
            elif role == 'document_manager':
                if user_id not in group.get('documentManagers', []):
                    group.setdefault('documentManagers', []).append(user_id)
            
            # Update modification timestamp
            group['modifiedDate'] = datetime.utcnow().isoformat()
            
            # Save group
            cosmos_groups_container.upsert_item(group)
            
            # Determine the action source (single add vs bulk CSV)
            source = data.get('source', 'csv')  # Default to 'csv' for backward compatibility
            action_type = 'add_member_directly' if source == 'single' else 'admin_add_member_csv'
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'activity_type': action_type,
                'timestamp': datetime.utcnow().isoformat(),
                'admin_user_id': admin_user.get('oid') or admin_user.get('sub'),
                'admin_email': admin_email,
                'group_id': group_id,
                'group_name': group.get('name', 'Unknown'),
                'member_user_id': user_id,
                'member_email': email,
                'member_name': name,
                'member_role': role,
                'source': source,
                'description': f"Admin {admin_email} added member {name} ({email}) to group {group.get('name', group_id)} as {role}"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            # Log to Application Insights
            log_event("[ControlCenter] Admin Add Group Member", {
                "admin_user": admin_email,
                "group_id": group_id,
                "group_name": group.get('name'),
                "member_email": email,
                "member_role": role
            })
            
            return jsonify({
                'message': f'Member {email} added successfully',
                'skipped': False
            }), 200
            
        except Exception as e:
            debug_print(f"Error adding group member: {e}")
            return jsonify({'error': 'Failed to add member'}), 500

    @app.route('/api/admin/control-center/groups/<group_id>/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_get_group_activity(group_id):
        """
        Get activity timeline for a specific group from activity logs
        Returns document creation/deletion, member changes, status changes, and conversations
        """
        try:
            # Get time range filter (default: last 30 days)
            days = request.args.get('days', '30')
            
            # Calculate date filter
            cutoff_date = None
            if days != 'all':
                try:
                    days_int = int(days)
                    cutoff_date = (datetime.utcnow() - timedelta(days=days_int)).isoformat()
                except ValueError:
                    pass
            
            # Build queries - use two separate queries to avoid nested property access issues
            # Query 1: Activities with c.group.group_id (member/status changes)
            # Query 2: Activities with c.workspace_context.group_id (document operations)
            
            time_filter = "AND c.timestamp >= @cutoff_date" if cutoff_date else ""
            
            # Query 1: Member and status activities (all activity types with c.group.group_id)
            # Use SELECT * to get complete raw documents for modal display
            query1 = f"""
                SELECT *
                FROM c
                WHERE c.group.group_id = @group_id
                {time_filter}
            """
            
            # Query 2: Document activities (all activity types with c.workspace_context.group_id)
            # Use SELECT * to get complete raw documents for modal display
            query2 = f"""
                SELECT *
                FROM c
                WHERE c.workspace_context.group_id = @group_id
                {time_filter}
            """
            
            # Log the queries for debugging
            debug_print(f"[Group Activity] Querying for group: {group_id}, days: {days}")
            debug_print(f"[Group Activity] Query 1: {query1}")
            debug_print(f"[Group Activity] Query 2: {query2}")
            
            parameters = [
                {"name": "@group_id", "value": group_id}
            ]
            
            if cutoff_date:
                parameters.append({"name": "@cutoff_date", "value": cutoff_date})
            
            debug_print(f"[Group Activity] Parameters: {parameters}")
            
            # Execute both queries
            activities = []
            
            try:
                # Query 1: Member and status activities
                activities1 = list(cosmos_activity_logs_container.query_items(
                    query=query1,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                debug_print(f"[Group Activity] Query 1 returned {len(activities1)} activities")
                activities.extend(activities1)
            except Exception as e:
                debug_print(f"[Group Activity] Query 1 failed: {e}")
            
            try:
                # Query 2: Document activities
                activities2 = list(cosmos_activity_logs_container.query_items(
                    query=query2,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                debug_print(f"[Group Activity] Query 2 returned {len(activities2)} activities")
                activities.extend(activities2)
            except Exception as e:
                debug_print(f"[Group Activity] Query 2 failed: {e}")
            
            # Sort combined results by timestamp descending
            activities.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            # Format activities for timeline display
            formatted_activities = []
            for activity in activities:
                formatted = {
                    'id': activity.get('id'),
                    'type': activity.get('activity_type'),
                    'timestamp': activity.get('timestamp'),
                    'user_id': activity.get('user_id'),
                    'description': activity.get('description', '')
                }
                
                # Add type-specific details
                activity_type = activity.get('activity_type')
                
                if activity_type == 'document_creation':
                    doc = activity.get('document', {})
                    formatted['document'] = {
                        'file_name': doc.get('file_name'),
                        'file_type': doc.get('file_type'),
                        'file_size_bytes': doc.get('file_size_bytes'),
                        'page_count': doc.get('page_count')
                    }
                    formatted['icon'] = 'file-earmark-plus'
                    formatted['color'] = 'success'
                
                elif activity_type == 'document_deletion':
                    doc = activity.get('document', {})
                    formatted['document'] = {
                        'file_name': doc.get('file_name'),
                        'file_type': doc.get('file_type')
                    }
                    formatted['icon'] = 'file-earmark-minus'
                    formatted['color'] = 'danger'
                
                elif activity_type == 'document_metadata_update':
                    doc = activity.get('document', {})
                    formatted['document'] = {
                        'file_name': doc.get('file_name')
                    }
                    formatted['icon'] = 'pencil-square'
                    formatted['color'] = 'info'
                
                elif activity_type == 'group_member_added':
                    added_by = activity.get('added_by', {})
                    added_member = activity.get('added_member', {})
                    formatted['member'] = {
                        'name': added_member.get('name'),
                        'email': added_member.get('email'),
                        'role': added_member.get('role')
                    }
                    formatted['added_by'] = {
                        'email': added_by.get('email'),
                        'role': added_by.get('role')
                    }
                    formatted['icon'] = 'person-plus'
                    formatted['color'] = 'primary'
                
                elif activity_type == 'group_member_deleted':
                    removed_by = activity.get('removed_by', {})
                    removed_member = activity.get('removed_member', {})
                    formatted['member'] = {
                        'name': removed_member.get('name'),
                        'email': removed_member.get('email')
                    }
                    formatted['removed_by'] = {
                        'email': removed_by.get('email'),
                        'role': removed_by.get('role')
                    }
                    formatted['icon'] = 'person-dash'
                    formatted['color'] = 'warning'
                
                elif activity_type == 'group_status_change':
                    status_change = activity.get('status_change', {})
                    formatted['status_change'] = {
                        'from_status': status_change.get('old_status'),  # Use old_status from log
                        'to_status': status_change.get('new_status')    # Use new_status from log
                    }
                    formatted['icon'] = 'shield-lock'
                    formatted['color'] = 'secondary'
                
                elif activity_type == 'conversation_creation':
                    formatted['icon'] = 'chat-dots'
                    formatted['color'] = 'info'
                
                elif activity_type == 'token_usage':
                    usage = activity.get('usage', {})
                    formatted['token_usage'] = {
                        'total_tokens': usage.get('total_tokens'),
                        'prompt_tokens': usage.get('prompt_tokens'),
                        'completion_tokens': usage.get('completion_tokens'),
                        'model': usage.get('model'),
                        'token_type': activity.get('token_type')  # 'chat' or 'embedding'
                    }
                    # Add chat details if available
                    chat_details = activity.get('chat_details', {})
                    if chat_details:
                        formatted['token_usage']['conversation_id'] = chat_details.get('conversation_id')
                        formatted['token_usage']['message_id'] = chat_details.get('message_id')
                    # Add embedding details if available
                    embedding_details = activity.get('embedding_details', {})
                    if embedding_details:
                        formatted['token_usage']['document_id'] = embedding_details.get('document_id')
                        formatted['token_usage']['file_name'] = embedding_details.get('file_name')
                    formatted['icon'] = 'cpu'
                    formatted['color'] = 'info'
                
                else:
                    # Fallback for unknown activity types - still show them!
                    formatted['icon'] = 'circle'
                    formatted['color'] = 'secondary'
                    # Keep any additional data that might be in the activity
                    if activity.get('status_change'):
                        formatted['status_change'] = activity.get('status_change')
                    if activity.get('document'):
                        formatted['document'] = activity.get('document')
                    if activity.get('group'):
                        formatted['group'] = activity.get('group')
                
                formatted_activities.append(formatted)
            
            return jsonify({
                'group_id': group_id,
                'activities': formatted_activities,
                'raw_activities': activities,  # Include raw activities for modal display
                'count': len(formatted_activities),
                'time_range_days': days
            }), 200
            
        except Exception as e:
            debug_print(f"Error fetching group activity: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Failed to fetch group activity: {str(e)}'}), 500

    # Public Workspaces API
    @app.route('/api/admin/control-center/public-workspaces', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
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
                    debug_print(f"Error enhancing workspace {workspace.get('id', 'unknown')}: {enhance_e}")
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
            debug_print(f"Error getting public workspaces for control center: {e}")
            return jsonify({'error': 'Failed to retrieve public workspaces'}), 500

    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/status', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_update_public_workspace_status(workspace_id):
        """
        Update public workspace status (active, locked, upload_disabled, inactive)
        Tracks who made the change and when, logs to activity_logs
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
                
            new_status = data.get('status')
            reason = data.get('reason')  # Optional reason for the status change
            
            if not new_status:
                return jsonify({'error': 'Status is required'}), 400
            
            # Validate status values
            valid_statuses = ['active', 'locked', 'upload_disabled', 'inactive']
            if new_status not in valid_statuses:
                return jsonify({'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400
                
            # Get the workspace
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            except:
                return jsonify({'error': 'Public workspace not found'}), 404
            
            # Get admin user info
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid', 'unknown')
            admin_email = admin_user.get('preferred_username', 'unknown')
            
            # Get old status for logging
            old_status = workspace.get('status', 'active')  # Default to 'active' if not set
            
            # Only update and log if status actually changed
            if old_status != new_status:
                # Update workspace status
                workspace['status'] = new_status
                workspace['modifiedDate'] = datetime.utcnow().isoformat()
                
                # Add status change metadata
                if 'statusHistory' not in workspace:
                    workspace['statusHistory'] = []
                
                workspace['statusHistory'].append({
                    'old_status': old_status,
                    'new_status': new_status,
                    'changed_by_user_id': admin_user_id,
                    'changed_by_email': admin_email,
                    'changed_at': datetime.utcnow().isoformat(),
                    'reason': reason
                })
                
                # Update in database
                cosmos_public_workspaces_container.upsert_item(workspace)
                
                # Log to activity_logs container for audit trail
                from functions_activity_logging import log_public_workspace_status_change
                log_public_workspace_status_change(
                    workspace_id=workspace_id,
                    workspace_name=workspace.get('name', 'Unknown'),
                    old_status=old_status,
                    new_status=new_status,
                    changed_by_user_id=admin_user_id,
                    changed_by_email=admin_email,
                    reason=reason
                )
                
                # Log admin action (legacy logging)
                log_event("[ControlCenter] Public Workspace Status Update", {
                    "admin_user": admin_email,
                    "admin_user_id": admin_user_id,
                    "workspace_id": workspace_id,
                    "workspace_name": workspace.get('name'),
                    "old_status": old_status,
                    "new_status": new_status,
                    "reason": reason
                })
                
                return jsonify({
                    'message': 'Public workspace status updated successfully',
                    'old_status': old_status,
                    'new_status': new_status
                }), 200
            else:
                return jsonify({
                    'message': 'Status unchanged',
                    'status': new_status
                }), 200
                
        except Exception as e:
            debug_print(f"Error updating public workspace status: {e}")
            return jsonify({'error': 'Failed to update public workspace status'}), 500

    @app.route('/api/admin/control-center/public-workspaces/bulk-action', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_bulk_public_workspace_action():
        """
        Perform bulk actions on multiple public workspaces.
        Actions: lock, unlock, disable_uploads, enable_uploads, delete_documents
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
                
            workspace_ids = data.get('workspace_ids', [])
            action = data.get('action')
            reason = data.get('reason')  # Optional reason
            
            if not workspace_ids or not isinstance(workspace_ids, list):
                return jsonify({'error': 'workspace_ids must be a non-empty array'}), 400
                
            if not action:
                return jsonify({'error': 'Action is required'}), 400
            
            # Validate action
            valid_actions = ['lock', 'unlock', 'disable_uploads', 'enable_uploads', 'delete_documents']
            if action not in valid_actions:
                return jsonify({'error': f'Invalid action. Must be one of: {", ".join(valid_actions)}'}), 400
            
            # Get admin user info
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid', 'unknown')
            admin_email = admin_user.get('preferred_username', 'unknown')
            
            # Map actions to status values
            action_to_status = {
                'lock': 'locked',
                'unlock': 'active',
                'disable_uploads': 'upload_disabled',
                'enable_uploads': 'active'
            }
            
            successful = []
            failed = []
            
            for workspace_id in workspace_ids:
                try:
                    # Get the workspace
                    workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
                    
                    if action == 'delete_documents':
                        # Delete all documents for this workspace
                        # Query all documents
                        doc_query = "SELECT c.id FROM c WHERE c.public_workspace_id = @workspace_id"
                        doc_params = [{"name": "@workspace_id", "value": workspace_id}]
                        
                        docs_to_delete = list(cosmos_public_documents_container.query_items(
                            query=doc_query,
                            parameters=doc_params,
                            enable_cross_partition_query=True
                        ))
                        
                        deleted_count = 0
                        for doc in docs_to_delete:
                            try:
                                delete_document_chunks(doc['id'])
                                delete_document(doc['id'])
                                deleted_count += 1
                            except Exception as del_e:
                                debug_print(f"Error deleting document {doc['id']}: {del_e}")
                        
                        successful.append({
                            'workspace_id': workspace_id,
                            'workspace_name': workspace.get('name', 'Unknown'),
                            'action': action,
                            'documents_deleted': deleted_count
                        })
                        
                        # Log the action
                        log_event("[ControlCenter] Bulk Public Workspace Documents Deleted", {
                            "admin_user": admin_email,
                            "admin_user_id": admin_user_id,
                            "workspace_id": workspace_id,
                            "workspace_name": workspace.get('name'),
                            "documents_deleted": deleted_count,
                            "reason": reason
                        })
                        
                    else:
                        # Status change action
                        new_status = action_to_status[action]
                        old_status = workspace.get('status', 'active')
                        
                        if old_status != new_status:
                            workspace['status'] = new_status
                            workspace['modifiedDate'] = datetime.utcnow().isoformat()
                            
                            # Add status history
                            if 'statusHistory' not in workspace:
                                workspace['statusHistory'] = []
                            
                            workspace['statusHistory'].append({
                                'old_status': old_status,
                                'new_status': new_status,
                                'changed_by_user_id': admin_user_id,
                                'changed_by_email': admin_email,
                                'changed_at': datetime.utcnow().isoformat(),
                                'reason': reason,
                                'bulk_action': True
                            })
                            
                            cosmos_public_workspaces_container.upsert_item(workspace)
                            
                            # Log activity
                            from functions_activity_logging import log_public_workspace_status_change
                            log_public_workspace_status_change(
                                workspace_id=workspace_id,
                                workspace_name=workspace.get('name', 'Unknown'),
                                old_status=old_status,
                                new_status=new_status,
                                changed_by_user_id=admin_user_id,
                                changed_by_email=admin_email,
                                reason=f"Bulk action: {reason}" if reason else "Bulk action"
                            )
                        
                        successful.append({
                            'workspace_id': workspace_id,
                            'workspace_name': workspace.get('name', 'Unknown'),
                            'action': action,
                            'old_status': old_status,
                            'new_status': new_status
                        })
                    
                except Exception as e:
                    failed.append({
                        'workspace_id': workspace_id,
                        'error': str(e)
                    })
                    debug_print(f"Error processing workspace {workspace_id}: {e}")
            
            return jsonify({
                'message': 'Bulk action completed',
                'successful': successful,
                'failed': failed,
                'summary': {
                    'total': len(workspace_ids),
                    'success': len(successful),
                    'failed': len(failed)
                }
            }), 200
            
        except Exception as e:
            debug_print(f"Error performing bulk public workspace action: {e}")
            return jsonify({'error': 'Failed to perform bulk action'}), 500

    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_get_public_workspace_details(workspace_id):
        """
        Get detailed information about a specific public workspace.
        """
        try:
            # Get the workspace
            workspace = cosmos_public_workspaces_container.read_item(
                item=workspace_id,
                partition_key=workspace_id
            )
            
            # Enhance with activity information
            enhanced_workspace = enhance_public_workspace_with_activity(workspace)
            
            return jsonify(enhanced_workspace), 200
            
        except Exception as e:
            debug_print(f"Error getting public workspace details: {e}")
            return jsonify({'error': 'Failed to retrieve workspace details'}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/members', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_get_public_workspace_members(workspace_id):
        """
        Get all members of a specific public workspace with their roles.
        Returns admins, document managers, and owner information.
        """
        try:
            # Get the workspace
            workspace = cosmos_public_workspaces_container.read_item(
                item=workspace_id,
                partition_key=workspace_id
            )
            
            # Create members list with roles
            members = []
            
            # Add owner - owner is an object with userId, email, displayName
            owner = workspace.get('owner')
            if owner:
                members.append({
                    'userId': owner.get('userId', ''),
                    'email': owner.get('email', ''),
                    'displayName': owner.get('displayName', owner.get('email', 'Unknown')),
                    'role': 'owner'
                })
            
            # Add admins - admins is an array of objects with userId, email, displayName
            admins = workspace.get('admins', [])
            for admin in admins:
                # Handle both object format and string format (for backward compatibility)
                if isinstance(admin, dict):
                    members.append({
                        'userId': admin.get('userId', ''),
                        'email': admin.get('email', ''),
                        'displayName': admin.get('displayName', admin.get('email', 'Unknown')),
                        'role': 'admin'
                    })
                else:
                    # Legacy format where admin is just a userId string
                    try:
                        user = cosmos_user_settings_container.read_item(
                            item=admin,
                            partition_key=admin
                        )
                        members.append({
                            'userId': admin,
                            'email': user.get('email', ''),
                            'displayName': user.get('display_name', user.get('email', '')),
                            'role': 'admin'
                        })
                    except:
                        pass
            
            # Add document managers - documentManagers is an array of objects with userId, email, displayName
            doc_managers = workspace.get('documentManagers', [])
            for dm in doc_managers:
                # Handle both object format and string format (for backward compatibility)
                if isinstance(dm, dict):
                    members.append({
                        'userId': dm.get('userId', ''),
                        'email': dm.get('email', ''),
                        'displayName': dm.get('displayName', dm.get('email', 'Unknown')),
                        'role': 'documentManager'
                    })
                else:
                    # Legacy format where documentManager is just a userId string
                    try:
                        user = cosmos_user_settings_container.read_item(
                            item=dm,
                            partition_key=dm
                        )
                        members.append({
                            'userId': dm,
                            'email': user.get('email', ''),
                            'displayName': user.get('display_name', user.get('email', '')),
                            'role': 'documentManager'
                        })
                    except:
                        pass
            
            return jsonify({
                'success': True,
                'members': members,
                'workspace_name': workspace.get('name', 'Unknown')
            }), 200
            
        except Exception as e:
            debug_print(f"Error getting workspace members: {e}")
            return jsonify({'error': 'Failed to retrieve workspace members'}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/add-member', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_add_workspace_member(workspace_id):
        """
        Admin adds a member to a public workspace (used by both single add and CSV bulk upload)
        """
        try:
            data = request.get_json()
            user_id = data.get('userId')
            name = data.get('displayName') or data.get('name')
            email = data.get('email')
            role = data.get('role', 'user').lower()
            
            if not user_id or not name or not email:
                return jsonify({'error': 'Missing required fields: userId, name/displayName, email'}), 400
            
            # Validate role
            valid_roles = ['admin', 'document_manager', 'user']
            if role not in valid_roles:
                return jsonify({'error': f'Invalid role. Must be: {", ".join(valid_roles)}'}), 400
            
            admin_user = session.get('user', {})
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            
            # Get the workspace
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            except:
                return jsonify({'error': 'Public workspace not found'}), 404
            
            # Check if user already exists
            owner = workspace.get('owner', {})
            owner_id = owner.get('userId') if isinstance(owner, dict) else owner
            admins = workspace.get('admins', [])
            doc_managers = workspace.get('documentManagers', [])
            
            # Extract user IDs from arrays (handle both object and string formats)
            admin_ids = [a.get('userId') if isinstance(a, dict) else a for a in admins]
            doc_manager_ids = [dm.get('userId') if isinstance(dm, dict) else dm for dm in doc_managers]
            
            if user_id == owner_id or user_id in admin_ids or user_id in doc_manager_ids:
                return jsonify({
                    'message': f'User {email} already exists in workspace',
                    'skipped': True
                }), 200
            
            # Create full user object
            user_obj = {
                'userId': user_id,
                'displayName': name,
                'email': email
            }
            
            # Add to appropriate role array with full user object
            if role == 'admin':
                workspace.setdefault('admins', []).append(user_obj)
            elif role == 'document_manager':
                workspace.setdefault('documentManagers', []).append(user_obj)
            # Note: 'user' role doesn't have a separate array in public workspaces
            # They are implicit members through document access
            
            # Update modification timestamp
            workspace['modifiedDate'] = datetime.utcnow().isoformat()
            
            # Save workspace
            cosmos_public_workspaces_container.upsert_item(workspace)
            
            # Determine the action source
            source = data.get('source', 'csv')
            action_type = 'add_workspace_member_directly' if source == 'single' else 'admin_add_workspace_member_csv'
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'activity_type': activity_type,
                'timestamp': datetime.utcnow().isoformat(),
                'admin_user_id': admin_user.get('oid') or admin_user.get('sub'),
                'admin_email': admin_email,
                'workspace_id': workspace_id,
                'workspace_name': workspace.get('name', 'Unknown'),
                'member_user_id': user_id,
                'member_email': email,
                'member_name': name,
                'member_role': role,
                'source': source,
                'description': f"Admin {admin_email} added member {name} ({email}) to workspace {workspace.get('name', workspace_id)} as {role}",
                'workspace_context': {
                    'public_workspace_id': workspace_id
                }
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            # Log to Application Insights
            log_event("[ControlCenter] Admin Add Workspace Member", {
                "admin_user": admin_email,
                "workspace_id": workspace_id,
                "workspace_name": workspace.get('name'),
                "member_email": email,
                "member_role": role
            })
            
            return jsonify({
                'message': f'Member {email} added successfully',
                'skipped': False
            }), 200
            
        except Exception as e:
            debug_print(f"Error adding workspace member: {e}")
            return jsonify({'error': 'Failed to add workspace member'}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/add-member-single', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_add_workspace_member_single(workspace_id):
        """
        Admin adds a single member to a public workspace via the Add Member modal
        """
        try:
            data = request.get_json()
            user_id = data.get('userId')
            display_name = data.get('displayName')
            email = data.get('email')
            role = data.get('role', 'document_manager').lower()
            
            if not user_id or not display_name or not email:
                return jsonify({'error': 'Missing required fields: userId, displayName, email'}), 400
            
            # Validate role - workspaces only support admin and document_manager
            valid_roles = ['admin', 'document_manager']
            if role not in valid_roles:
                return jsonify({'error': f'Invalid role. Must be: {", ".join(valid_roles)}'}), 400
            
            admin_user = session.get('user', {})
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            
            # Get the workspace
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            except:
                return jsonify({'error': 'Public workspace not found'}), 404
            
            # Check if user already exists
            owner = workspace.get('owner', {})
            owner_id = owner.get('userId') if isinstance(owner, dict) else owner
            admins = workspace.get('admins', [])
            doc_managers = workspace.get('documentManagers', [])
            
            # Extract user IDs from arrays (handle both object and string formats)
            admin_ids = [a.get('userId') if isinstance(a, dict) else a for a in admins]
            doc_manager_ids = [dm.get('userId') if isinstance(dm, dict) else dm for dm in doc_managers]
            
            if user_id == owner_id or user_id in admin_ids or user_id in doc_manager_ids:
                return jsonify({
                    'error': f'User {email} already exists in workspace'
                }), 400
            
            # Add to appropriate role array with full user info
            user_obj = {
                'userId': user_id,
                'displayName': display_name,
                'email': email
            }
            
            if role == 'admin':
                workspace.setdefault('admins', []).append(user_obj)
            elif role == 'document_manager':
                workspace.setdefault('documentManagers', []).append(user_obj)
            
            # Update modification timestamp
            workspace['modifiedDate'] = datetime.utcnow().isoformat()
            
            # Save workspace
            cosmos_public_workspaces_container.upsert_item(workspace)
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'activity_type': 'add_workspace_member_directly',
                'timestamp': datetime.utcnow().isoformat(),
                'admin_user_id': admin_user.get('oid') or admin_user.get('sub'),
                'admin_email': admin_email,
                'workspace_id': workspace_id,
                'workspace_name': workspace.get('name', 'Unknown'),
                'member_user_id': user_id,
                'member_email': email,
                'member_name': display_name,
                'member_role': role,
                'source': 'single',
                'description': f"Admin {admin_email} added member {display_name} ({email}) to workspace {workspace.get('name', workspace_id)} as {role}",
                'workspace_context': {
                    'public_workspace_id': workspace_id
                }
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            # Log to Application Insights
            log_event("[ControlCenter] Admin Add Workspace Member (Single)", {
                "admin_user": admin_email,
                "workspace_id": workspace_id,
                "workspace_name": workspace.get('name'),
                "member_email": email,
                "member_role": role
            })
            
            return jsonify({
                'message': f'Successfully added {display_name} as {role}',
                'success': True
            }), 200
            
        except Exception as e:
            debug_print(f"Error adding workspace member: {e}")
            return jsonify({'error': 'Failed to add workspace member'}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_get_public_workspace_activity(workspace_id):
        """
        Get activity timeline for a specific public workspace from activity logs
        Returns document creation/deletion, member changes, status changes, and conversations
        """
        try:
            # Get time range filter (default: last 30 days)
            days = request.args.get('days', '30')
            export = request.args.get('export', 'false').lower() == 'true'
            
            # Calculate date filter
            cutoff_date = None
            if days != 'all':
                try:
                    days_int = int(days)
                    cutoff_date = (datetime.utcnow() - timedelta(days=days_int)).isoformat()
                except ValueError:
                    pass
            
            time_filter = "AND c.timestamp >= @cutoff_date" if cutoff_date else ""
            
            # Query: All activities for public workspaces (no activity type filter to show everything)
            # Use SELECT * to get complete raw documents for modal display
            query = f"""
                SELECT *
                FROM c
                WHERE c.workspace_context.public_workspace_id = @workspace_id
                {time_filter}
                ORDER BY c.timestamp DESC
            """
            
            # Log the query for debugging
            debug_print(f"[Workspace Activity] Querying for workspace: {workspace_id}, days: {days}")
            debug_print(f"[Workspace Activity] Query: {query}")
            
            parameters = [
                {"name": "@workspace_id", "value": workspace_id}
            ]
            
            if cutoff_date:
                parameters.append({"name": "@cutoff_date", "value": cutoff_date})
            
            debug_print(f"[Workspace Activity] Parameters: {parameters}")
            
            # Execute query
            activities = list(cosmos_activity_logs_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"[Workspace Activity] Query returned {len(activities)} activities")
            
            # Format activities for timeline display
            formatted_activities = []
            for activity in activities:
                formatted = {
                    'id': activity.get('id'),
                    'type': activity.get('activity_type'),
                    'timestamp': activity.get('timestamp'),
                    'user_id': activity.get('user_id'),
                    'description': activity.get('description', '')
                }
                
                # Add type-specific details
                activity_type = activity.get('activity_type')
                
                if activity_type == 'document_creation':
                    doc = activity.get('document', {})
                    formatted['document'] = {
                        'file_name': doc.get('file_name'),
                        'file_type': doc.get('file_type'),
                        'file_size_bytes': doc.get('file_size_bytes'),
                        'page_count': doc.get('page_count')
                    }
                    formatted['icon'] = 'file-earmark-plus'
                    formatted['color'] = 'success'
                
                elif activity_type == 'document_deletion':
                    doc = activity.get('document', {})
                    formatted['document'] = {
                        'file_name': doc.get('file_name'),
                        'file_type': doc.get('file_type')
                    }
                    formatted['icon'] = 'file-earmark-minus'
                    formatted['color'] = 'danger'
                
                elif activity_type == 'document_metadata_update':
                    doc = activity.get('document', {})
                    formatted['document'] = {
                        'file_name': doc.get('file_name')
                    }
                    formatted['icon'] = 'pencil-square'
                    formatted['color'] = 'info'
                
                elif activity_type == 'public_workspace_status_change':
                    status_change = activity.get('status_change', {})
                    formatted['status_change'] = {
                        'from_status': status_change.get('old_status'),
                        'to_status': status_change.get('new_status'),
                        'changed_by': activity.get('changed_by')
                    }
                    formatted['icon'] = 'shield-check'
                    formatted['color'] = 'warning'
                
                elif activity_type == 'token_usage':
                    usage = activity.get('usage', {})
                    formatted['token_usage'] = {
                        'total_tokens': usage.get('total_tokens'),
                        'prompt_tokens': usage.get('prompt_tokens'),
                        'completion_tokens': usage.get('completion_tokens'),
                        'model': usage.get('model'),
                        'token_type': activity.get('token_type')  # 'chat' or 'embedding'
                    }
                    # Add chat details if available
                    chat_details = activity.get('chat_details', {})
                    if chat_details:
                        formatted['token_usage']['conversation_id'] = chat_details.get('conversation_id')
                        formatted['token_usage']['message_id'] = chat_details.get('message_id')
                    # Add embedding details if available
                    embedding_details = activity.get('embedding_details', {})
                    if embedding_details:
                        formatted['token_usage']['document_id'] = embedding_details.get('document_id')
                        formatted['token_usage']['file_name'] = embedding_details.get('file_name')
                    formatted['icon'] = 'cpu'
                    formatted['color'] = 'info'
                
                else:
                    # Fallback for unknown activity types - still show them!
                    formatted['icon'] = 'circle'
                    formatted['color'] = 'secondary'
                    # Keep any additional data that might be in the activity
                    if activity.get('status_change'):
                        formatted['status_change'] = activity.get('status_change')
                    if activity.get('document'):
                        formatted['document'] = activity.get('document')
                    if activity.get('workspace_context'):
                        formatted['workspace_context'] = activity.get('workspace_context')
                
                formatted_activities.append(formatted)
            
            if export:
                # Return CSV for export
                import io
                import csv
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(['Timestamp', 'Type', 'User ID', 'Description', 'Details'])
                for activity in formatted_activities:
                    details = ''
                    if activity.get('document'):
                        doc = activity['document']
                        details = f"{doc.get('file_name', '')} - {doc.get('file_type', '')}"
                    elif activity.get('status_change'):
                        sc = activity['status_change']
                        details = f"{sc.get('from_status', '')} -> {sc.get('to_status', '')}"
                    
                    writer.writerow([
                        activity['timestamp'],
                        activity['type'],
                        activity['user_id'],
                        activity['description'],
                        details
                    ])
                
                csv_content = output.getvalue()
                output.close()
                
                from flask import make_response
                response = make_response(csv_content)
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = f'attachment; filename="workspace_{workspace_id}_activity.csv"'
                return response
            
            return jsonify({
                'success': True,
                'activities': formatted_activities,
                'raw_activities': activities  # Include raw activities for modal display
            }), 200
            
        except Exception as e:
            debug_print(f"Error getting workspace activity: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to retrieve workspace activity'}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/take-ownership', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_take_workspace_ownership(workspace_id):
        """
        Create an approval request for admin to take ownership of a public workspace.
        Requires approval from workspace owner or another admin.
        
        Body:
            reason (str): Explanation for taking ownership (required)
        """
        try:
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            if not admin_user_id:
                return jsonify({'error': 'Could not identify admin user'}), 400
            
            # Get request body
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for ownership transfer'}), 400
            
            # Validate workspace exists
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            except:
                return jsonify({'error': 'Workspace not found'}), 404
            
            # Get old owner info
            old_owner = workspace.get('owner', {})
            if isinstance(old_owner, dict):
                old_owner_id = old_owner.get('userId')
                old_owner_email = old_owner.get('email')
            else:
                old_owner_id = old_owner
                old_owner_email = 'unknown'
            
            # Create approval request (use group_id parameter as partition key for workspace)
            approval = create_approval_request(
                request_type=TYPE_TAKE_OWNERSHIP,
                group_id=workspace_id,
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'old_owner_id': old_owner_id,
                    'old_owner_email': old_owner_email,
                    'entity_type': 'workspace'
                }
            )
            
            # Log event
            log_event("[ControlCenter] Take Workspace Ownership Request Created", {
                "admin_user": admin_email,
                "workspace_id": workspace_id,
                "workspace_name": workspace.get('name'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Ownership transfer request created and pending approval',
                'approval_id': approval['id'],
                'requires_approval': True,
                'status': 'pending'
            }), 201
            
        except Exception as e:
            debug_print(f"Error creating take workspace ownership request: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/ownership', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_update_public_workspace_ownership(workspace_id):
        """
        Create an approval request to transfer public workspace ownership to another member.
        Requires approval from workspace owner or another admin.
        
        Body:
            newOwnerId (str): User ID of the new owner (required)
            reason (str): Explanation for ownership transfer (required)
        """
        try:
            data = request.get_json()
            new_owner_user_id = data.get('newOwnerId')
            reason = data.get('reason', '').strip()
            
            if not new_owner_user_id:
                return jsonify({'error': 'Missing newOwnerId'}), 400
            
            if not reason:
                return jsonify({'error': 'Reason is required for ownership transfer'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Get the workspace
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            except:
                return jsonify({'error': 'Workspace not found'}), 404
            
            # Get new owner user details
            try:
                new_owner_user = cosmos_user_settings_container.read_item(
                    item=new_owner_user_id,
                    partition_key=new_owner_user_id
                )
                new_owner_email = new_owner_user.get('email', 'unknown')
                new_owner_name = new_owner_user.get('display_name', new_owner_email)
            except:
                return jsonify({'error': 'New owner user not found'}), 404
            
            # Check if new owner is a member of the workspace
            is_member = False
            current_owner = workspace.get('owner', {})
            if isinstance(current_owner, dict):
                if current_owner.get('userId') == new_owner_user_id:
                    is_member = True
            elif current_owner == new_owner_user_id:
                is_member = True
            
            # Check admins
            for admin in workspace.get('admins', []):
                admin_id = admin.get('userId') if isinstance(admin, dict) else admin
                if admin_id == new_owner_user_id:
                    is_member = True
                    break
            
            # Check documentManagers
            if not is_member:
                for dm in workspace.get('documentManagers', []):
                    dm_id = dm.get('userId') if isinstance(dm, dict) else dm
                    if dm_id == new_owner_user_id:
                        is_member = True
                        break
            
            if not is_member:
                return jsonify({'error': 'Selected user is not a member of this workspace'}), 400
            
            # Get old owner info
            old_owner_id = None
            old_owner_email = None
            if isinstance(current_owner, dict):
                old_owner_id = current_owner.get('userId')
                old_owner_email = current_owner.get('email')
            else:
                old_owner_id = current_owner
            
            # Create approval request (use group_id parameter as partition key for workspace)
            approval = create_approval_request(
                request_type=TYPE_TRANSFER_OWNERSHIP,
                group_id=workspace_id,
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'new_owner_id': new_owner_user_id,
                    'new_owner_email': new_owner_email,
                    'new_owner_name': new_owner_name,
                    'old_owner_id': old_owner_id,
                    'old_owner_email': old_owner_email,
                    'entity_type': 'workspace'
                }
            )
            
            # Log event
            log_event("[ControlCenter] Transfer Workspace Ownership Request Created", {
                "admin_user": admin_email,
                "workspace_id": workspace_id,
                "workspace_name": workspace.get('name'),
                "new_owner": new_owner_email,
                "old_owner_id": old_owner_id,
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'message': 'Ownership transfer approval request created',
                'approval_id': approval['id'],
                'requires_approval': True
            }), 201
            
        except Exception as e:
            debug_print(f"Error creating workspace ownership transfer request: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to create ownership transfer request'}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>/documents', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_delete_public_workspace_documents_admin(workspace_id):
        """
        Create an approval request to delete all documents in a public workspace.
        Requires approval from workspace owner or another admin.
        
        Body:
            reason (str): Explanation for deleting documents (required)
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for document deletion'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Validate workspace exists
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            except:
                return jsonify({'error': 'Public workspace not found'}), 404
            
            # Create approval request
            approval = create_approval_request(
                request_type=TYPE_DELETE_DOCUMENTS,
                group_id=workspace_id,  # Use workspace_id as group_id for approval system
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'workspace_name': workspace.get('name'),
                    'entity_type': 'workspace'
                }
            )
            
            # Log event
            log_event("[ControlCenter] Delete Public Workspace Documents Request Created", {
                "admin_user": admin_email,
                "workspace_id": workspace_id,
                "workspace_name": workspace.get('name'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Document deletion request created and pending approval',
                'approval_id': approval['id'],
                'status': 'pending'
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating document deletion request: {e}")
            return jsonify({'error': str(e)}), 500


    @app.route('/api/admin/control-center/public-workspaces/<workspace_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_delete_public_workspace_admin(workspace_id):
        """
        Create an approval request to delete an entire public workspace.
        Requires approval from workspace owner or another admin.
        
        Body:
            reason (str): Explanation for deleting the workspace (required)
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({'error': 'Reason is required for workspace deletion'}), 400
            
            admin_user = session.get('user', {})
            admin_user_id = admin_user.get('oid') or admin_user.get('sub')
            admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
            admin_display_name = admin_user.get('name', admin_email)
            
            # Validate workspace exists
            try:
                workspace = cosmos_public_workspaces_container.read_item(
                    item=workspace_id,
                    partition_key=workspace_id
                )
            except:
                return jsonify({'error': 'Public workspace not found'}), 404
            
            # Create approval request
            approval = create_approval_request(
                request_type=TYPE_DELETE_GROUP,  # Reuse TYPE_DELETE_GROUP for workspace deletion
                group_id=workspace_id,  # Use workspace_id as group_id for approval system
                requester_id=admin_user_id,
                requester_email=admin_email,
                requester_name=admin_display_name,
                reason=reason,
                metadata={
                    'workspace_name': workspace.get('name'),
                    'entity_type': 'workspace'
                }
            )
            
            # Log event
            log_event("[ControlCenter] Delete Public Workspace Request Created", {
                "admin_user": admin_email,
                "workspace_id": workspace_id,
                "workspace_name": workspace.get('name'),
                "approval_id": approval['id'],
                "reason": reason
            })
            
            return jsonify({
                'success': True,
                'message': 'Workspace deletion request created and pending approval',
                'approval_id': approval['id'],
                'status': 'pending'
            }), 200
            
        except Exception as e:
            debug_print(f"Error creating workspace deletion request: {e}")
            return jsonify({'error': str(e)}), 500

    # Activity Trends API
    @app.route('/api/admin/control-center/activity-trends', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('dashboard')
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
            debug_print(f"Error getting activity trends: {e}")
            print(f"❌ [Activity Trends API] Error: {e}")
            return jsonify({'error': 'Failed to retrieve activity trends'}), 500



    @app.route('/api/admin/control-center/activity-trends/export', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('dashboard')
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
                    
                    elif chart_type == 'tokens':
                        debug_print(f"🔍 [CSV DEBUG] Writing token usage headers for {chart_type}")
                        writer.writerow([
                            'Display Name', 'Email', 'User ID', 'Token Type', 'Model Name', 
                            'Prompt Tokens', 'Completion Tokens', 'Total Tokens', 'Timestamp'
                        ])
                        record_count = 0
                        for record in raw_data[chart_type]:
                            record_count += 1
                            if record_count <= 3:  # Debug first 3 records
                                debug_print(f"🔍 [CSV DEBUG] Token record {record_count} structure: {list(record.keys())}")
                                debug_print(f"🔍 [CSV DEBUG] Token record {record_count} data: {record}")
                            writer.writerow([
                                record.get('display_name', ''),
                                record.get('email', ''),
                                record.get('user_id', ''),
                                record.get('token_type', ''),
                                record.get('model_name', ''),
                                record.get('prompt_tokens', ''),
                                record.get('completion_tokens', ''),
                                record.get('total_tokens', ''),
                                record.get('timestamp', '')
                            ])
                        debug_print(f"🔍 [CSV DEBUG] Finished writing {record_count} token usage records")
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
            debug_print(f"Error exporting activity trends: {e}")
            return jsonify({'error': 'Failed to export data'}), 500

    @app.route('/api/admin/control-center/activity-trends/chat', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('dashboard')
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
            debug_print(f"Error creating activity trends chat: {e}")
            return jsonify({'error': 'Failed to create chat conversation'}), 500
    
    # Data Refresh API
    @app.route('/api/admin/control-center/refresh', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_refresh_control_center_data():
        """
        Refresh all Control Center metrics data and update admin timestamp.
        This will recalculate all user metrics and cache them in user settings.
        """
        try:
            debug_print("🔄 [REFRESH DEBUG] Starting Control Center data refresh...")
            debug_print("Starting Control Center data refresh...")
            
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
                    debug_print(f"Refreshed metrics for user {user_id}")
                except Exception as user_error:
                    failed_count += 1
                    debug_print(f"❌ [REFRESH DEBUG] Failed to refresh user {user.get('id')}: {user_error}")
                    debug_print(f"❌ [REFRESH DEBUG] User error traceback:")
                    import traceback
                    debug_print(traceback.format_exc())
                    debug_print(f"Failed to refresh metrics for user {user.get('id')}: {user_error}")
            
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
                        debug_print(f"Refreshed metrics for group {group_id}")
                    except Exception as group_error:
                        groups_failed_count += 1
                        debug_print(f"❌ [REFRESH DEBUG] Failed to refresh group {group.get('id')}: {group_error}")
                        debug_print(f"❌ [REFRESH DEBUG] Group error traceback:")
                        import traceback
                        debug_print(traceback.format_exc())
                        debug_print(f"Failed to refresh metrics for group {group.get('id')}: {group_error}")
                        
            except Exception as groups_error:
                debug_print(f"❌ [REFRESH DEBUG] Error querying groups: {groups_error}")
                debug_print(f"Error querying groups for refresh: {groups_error}")
            
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
                        debug_print("Failed to update admin settings with refresh timestamp")
                    else:
                        debug_print("✅ [REFRESH DEBUG] Admin settings updated successfully")
                        debug_print("Updated admin settings with refresh timestamp")
                else:
                    debug_print("⚠️ [REFRESH DEBUG] Could not get admin settings")
                    
            except Exception as admin_error:
                debug_print(f"❌ [REFRESH DEBUG] Admin settings update failed: {admin_error}")
                debug_print(f"Error updating admin settings: {admin_error}")
            
            debug_print(f"🎉 [REFRESH DEBUG] Refresh completed! Users - Refreshed: {refreshed_count}, Failed: {failed_count}. Groups - Refreshed: {groups_refreshed_count}, Failed: {groups_failed_count}")
            debug_print(f"Control Center data refresh completed. Users: {refreshed_count} refreshed, {failed_count} failed. Groups: {groups_refreshed_count} refreshed, {groups_failed_count} failed")
            
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
            debug_print(f"Error refreshing Control Center data: {e}")
            return jsonify({'error': 'Failed to refresh data'}), 500
    
    # Get refresh status API
    @app.route('/api/admin/control-center/refresh-status', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')  
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
            debug_print(f"Error getting refresh status: {e}")
            return jsonify({'error': 'Failed to get refresh status'}), 500
    
    # Activity Log Migration APIs
    @app.route('/api/admin/control-center/migrate/status', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_get_migration_status():
        """
        Check if there are conversations and documents that need to be migrated to activity logs.
        Returns counts of records without the 'added_to_activity_log' flag.
        """
        try:
            migration_status = {
                'conversations_without_logs': 0,
                'personal_documents_without_logs': 0,
                'group_documents_without_logs': 0,
                'public_documents_without_logs': 0,
                'total_documents_without_logs': 0,
                'migration_needed': False,
                'estimated_total_records': 0
            }
            
            # Check conversations without the flag
            try:
                conversations_query = """
                    SELECT VALUE COUNT(1) 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                conversations_result = list(cosmos_conversations_container.query_items(
                    query=conversations_query,
                    enable_cross_partition_query=True
                ))
                migration_status['conversations_without_logs'] = conversations_result[0] if conversations_result else 0
            except Exception as e:
                debug_print(f"Error checking conversations migration status: {e}")
            
            # Check personal documents without the flag
            try:
                personal_docs_query = """
                    SELECT VALUE COUNT(1) 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                personal_docs_result = list(cosmos_user_documents_container.query_items(
                    query=personal_docs_query,
                    enable_cross_partition_query=True
                ))
                migration_status['personal_documents_without_logs'] = personal_docs_result[0] if personal_docs_result else 0
            except Exception as e:
                debug_print(f"Error checking personal documents migration status: {e}")
            
            # Check group documents without the flag
            try:
                group_docs_query = """
                    SELECT VALUE COUNT(1) 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                group_docs_result = list(cosmos_group_documents_container.query_items(
                    query=group_docs_query,
                    enable_cross_partition_query=True
                ))
                migration_status['group_documents_without_logs'] = group_docs_result[0] if group_docs_result else 0
            except Exception as e:
                debug_print(f"Error checking group documents migration status: {e}")
            
            # Check public documents without the flag
            try:
                public_docs_query = """
                    SELECT VALUE COUNT(1) 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                public_docs_result = list(cosmos_public_documents_container.query_items(
                    query=public_docs_query,
                    enable_cross_partition_query=True
                ))
                migration_status['public_documents_without_logs'] = public_docs_result[0] if public_docs_result else 0
            except Exception as e:
                debug_print(f"Error checking public documents migration status: {e}")
            
            # Calculate totals
            migration_status['total_documents_without_logs'] = (
                migration_status['personal_documents_without_logs'] +
                migration_status['group_documents_without_logs'] +
                migration_status['public_documents_without_logs']
            )
            
            migration_status['estimated_total_records'] = (
                migration_status['conversations_without_logs'] +
                migration_status['total_documents_without_logs']
            )
            
            migration_status['migration_needed'] = migration_status['estimated_total_records'] > 0
            
            return jsonify(migration_status), 200
            
        except Exception as e:
            debug_print(f"Error getting migration status: {e}")
            return jsonify({'error': 'Failed to get migration status'}), 500
    
    @app.route('/api/admin/control-center/migrate/all', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_migrate_to_activity_logs():
        """
        Migrate all conversations and documents without activity logs.
        This adds activity log records and sets the 'added_to_activity_log' flag.
        
        WARNING: This may take a while for large datasets and could impact performance.
        Recommended to run during off-peak hours.
        """
        try:
            from functions_activity_logging import log_conversation_creation, log_document_creation_transaction
            
            results = {
                'conversations_migrated': 0,
                'conversations_failed': 0,
                'personal_documents_migrated': 0,
                'personal_documents_failed': 0,
                'group_documents_migrated': 0,
                'group_documents_failed': 0,
                'public_documents_migrated': 0,
                'public_documents_failed': 0,
                'total_migrated': 0,
                'total_failed': 0,
                'errors': []
            }
            
            # Migrate conversations
            debug_print("Starting conversation migration...")
            try:
                conversations_query = """
                    SELECT * 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                conversations = list(cosmos_conversations_container.query_items(
                    query=conversations_query,
                    enable_cross_partition_query=True
                ))
                
                debug_print(f"Found {len(conversations)} conversations to migrate")
                
                for conv in conversations:
                    try:
                        # Create activity log directly to preserve original timestamp
                        activity_log = {
                            'id': str(uuid.uuid4()),
                            'activity_type': 'conversation_creation',
                            'user_id': conv.get('user_id'),
                            'timestamp': conv.get('created_at') or conv.get('last_updated') or datetime.utcnow().isoformat(),
                            'created_at': conv.get('created_at') or conv.get('last_updated') or datetime.utcnow().isoformat(),
                            'conversation': {
                                'conversation_id': conv.get('id'),
                                'title': conv.get('title', 'Untitled'),
                                'context': conv.get('context', []),
                                'tags': conv.get('tags', [])
                            },
                            'workspace_type': 'personal',
                            'workspace_context': {}
                        }
                        
                        # Save to activity logs container
                        cosmos_activity_logs_container.upsert_item(activity_log)
                        
                        # Add flag to conversation
                        conv['added_to_activity_log'] = True
                        cosmos_conversations_container.upsert_item(conv)
                        
                        results['conversations_migrated'] += 1
                        
                    except Exception as conv_error:
                        results['conversations_failed'] += 1
                        error_msg = f"Failed to migrate conversation {conv.get('id')}: {str(conv_error)}"
                        debug_print(error_msg)
                        results['errors'].append(error_msg)
                        
            except Exception as e:
                error_msg = f"Error during conversation migration: {str(e)}"
                debug_print(error_msg)
                results['errors'].append(error_msg)
            
            # Migrate personal documents
            debug_print("Starting personal documents migration...")
            try:
                personal_docs_query = """
                    SELECT * 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                personal_docs = list(cosmos_user_documents_container.query_items(
                    query=personal_docs_query,
                    enable_cross_partition_query=True
                ))
                
                for doc in personal_docs:
                    try:
                        # Create activity log directly to preserve original timestamp
                        activity_log = {
                            'id': str(uuid.uuid4()),
                            'user_id': doc.get('user_id'),
                            'activity_type': 'document_creation',
                            'workspace_type': 'personal',
                            'timestamp': doc.get('upload_date') or datetime.utcnow().isoformat(),
                            'created_at': doc.get('upload_date') or datetime.utcnow().isoformat(),
                            'document': {
                                'document_id': doc.get('id'),
                                'file_name': doc.get('file_name', 'Unknown'),
                                'file_type': doc.get('file_type', 'unknown'),
                                'file_size_bytes': doc.get('file_size', 0),
                                'page_count': doc.get('number_of_pages', 0),
                                'version': doc.get('version', 1)
                            },
                            'embedding_usage': {
                                'total_tokens': doc.get('embedding_tokens', 0),
                                'model_deployment_name': doc.get('embedding_model_deployment_name', 'unknown')
                            },
                            'document_metadata': {
                                'author': doc.get('author'),
                                'title': doc.get('title'),
                                'subject': doc.get('subject'),
                                'publication_date': doc.get('publication_date'),
                                'keywords': doc.get('keywords', []),
                                'abstract': doc.get('abstract')
                            },
                            'workspace_context': {}
                        }
                        
                        # Save to activity logs container
                        cosmos_activity_logs_container.upsert_item(activity_log)
                        
                        # Add flag to document
                        doc['added_to_activity_log'] = True
                        cosmos_user_documents_container.upsert_item(doc)
                        
                        results['personal_documents_migrated'] += 1
                        
                    except Exception as doc_error:
                        results['personal_documents_failed'] += 1
                        error_msg = f"Failed to migrate personal document {doc.get('id')}: {str(doc_error)}"
                        debug_print(error_msg)
                        results['errors'].append(error_msg)
                        
            except Exception as e:
                error_msg = f"Error during personal documents migration: {str(e)}"
                debug_print(error_msg)
                results['errors'].append(error_msg)
            
            # Migrate group documents
            debug_print("Starting group documents migration...")
            try:
                group_docs_query = """
                    SELECT * 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                group_docs = list(cosmos_group_documents_container.query_items(
                    query=group_docs_query,
                    enable_cross_partition_query=True
                ))
                
                for doc in group_docs:
                    try:
                        # Create activity log directly to preserve original timestamp
                        activity_log = {
                            'id': str(uuid.uuid4()),
                            'user_id': doc.get('user_id'),
                            'activity_type': 'document_creation',
                            'workspace_type': 'group',
                            'timestamp': doc.get('upload_date') or datetime.utcnow().isoformat(),
                            'created_at': doc.get('upload_date') or datetime.utcnow().isoformat(),
                            'document': {
                                'document_id': doc.get('id'),
                                'file_name': doc.get('file_name', 'Unknown'),
                                'file_type': doc.get('file_type', 'unknown'),
                                'file_size_bytes': doc.get('file_size', 0),
                                'page_count': doc.get('number_of_pages', 0),
                                'version': doc.get('version', 1)
                            },
                            'embedding_usage': {
                                'total_tokens': doc.get('embedding_tokens', 0),
                                'model_deployment_name': doc.get('embedding_model_deployment_name', 'unknown')
                            },
                            'document_metadata': {
                                'author': doc.get('author'),
                                'title': doc.get('title'),
                                'subject': doc.get('subject'),
                                'publication_date': doc.get('publication_date'),
                                'keywords': doc.get('keywords', []),
                                'abstract': doc.get('abstract')
                            },
                            'workspace_context': {
                                'group_id': doc.get('group_id')
                            }
                        }
                        
                        # Save to activity logs container
                        cosmos_activity_logs_container.upsert_item(activity_log)
                        
                        # Add flag to document
                        doc['added_to_activity_log'] = True
                        cosmos_group_documents_container.upsert_item(doc)
                        
                        results['group_documents_migrated'] += 1
                        
                    except Exception as doc_error:
                        results['group_documents_failed'] += 1
                        error_msg = f"Failed to migrate group document {doc.get('id')}: {str(doc_error)}"
                        debug_print(error_msg)
                        results['errors'].append(error_msg)
                        
            except Exception as e:
                error_msg = f"Error during group documents migration: {str(e)}"
                debug_print(error_msg)
                results['errors'].append(error_msg)
            
            # Migrate public documents
            debug_print("Starting public documents migration...")
            try:
                public_docs_query = """
                    SELECT * 
                    FROM c 
                    WHERE NOT IS_DEFINED(c.added_to_activity_log) OR c.added_to_activity_log = false
                """
                public_docs = list(cosmos_public_documents_container.query_items(
                    query=public_docs_query,
                    enable_cross_partition_query=True
                ))
                
                for doc in public_docs:
                    try:
                        # Create activity log directly to preserve original timestamp
                        activity_log = {
                            'id': str(uuid.uuid4()),
                            'user_id': doc.get('user_id'),
                            'activity_type': 'document_creation',
                            'workspace_type': 'public',
                            'timestamp': doc.get('upload_date') or datetime.utcnow().isoformat(),
                            'created_at': doc.get('upload_date') or datetime.utcnow().isoformat(),
                            'document': {
                                'document_id': doc.get('id'),
                                'file_name': doc.get('file_name', 'Unknown'),
                                'file_type': doc.get('file_type', 'unknown'),
                                'file_size_bytes': doc.get('file_size', 0),
                                'page_count': doc.get('number_of_pages', 0),
                                'version': doc.get('version', 1)
                            },
                            'embedding_usage': {
                                'total_tokens': doc.get('embedding_tokens', 0),
                                'model_deployment_name': doc.get('embedding_model_deployment_name', 'unknown')
                            },
                            'document_metadata': {
                                'author': doc.get('author'),
                                'title': doc.get('title'),
                                'subject': doc.get('subject'),
                                'publication_date': doc.get('publication_date'),
                                'keywords': doc.get('keywords', []),
                                'abstract': doc.get('abstract')
                            },
                            'workspace_context': {
                                'public_workspace_id': doc.get('public_workspace_id')
                            }
                        }
                        
                        # Save to activity logs container
                        cosmos_activity_logs_container.upsert_item(activity_log)
                        
                        # Add flag to document
                        doc['added_to_activity_log'] = True
                        cosmos_public_documents_container.upsert_item(doc)
                        
                        results['public_documents_migrated'] += 1
                        
                    except Exception as doc_error:
                        results['public_documents_failed'] += 1
                        error_msg = f"Failed to migrate public document {doc.get('id')}: {str(doc_error)}"
                        debug_print(error_msg)
                        results['errors'].append(error_msg)
                        
            except Exception as e:
                error_msg = f"Error during public documents migration: {str(e)}"
                debug_print(error_msg)
                results['errors'].append(error_msg)
            
            # Calculate totals
            results['total_migrated'] = (
                results['conversations_migrated'] +
                results['personal_documents_migrated'] +
                results['group_documents_migrated'] +
                results['public_documents_migrated']
            )
            
            results['total_failed'] = (
                results['conversations_failed'] +
                results['personal_documents_failed'] +
                results['group_documents_failed'] +
                results['public_documents_failed']
            )
            
            debug_print(f"Migration complete: {results['total_migrated']} migrated, {results['total_failed']} failed")
            
            return jsonify(results), 200
            
        except Exception as e:
            debug_print(f"Error during migration: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Migration failed: {str(e)}'}), 500

    @app.route('/api/admin/control-center/activity-logs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_get_activity_logs():
        """
        Get paginated and filtered activity logs from cosmos_activity_logs_container.
        Supports search and filtering by activity type.
        """
        try:
            # Get query parameters
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))
            search_term = request.args.get('search', '').strip().lower()
            activity_type_filter = request.args.get('activity_type_filter', 'all').strip()
            
            # Build query conditions
            query_conditions = []
            parameters = []
            
            # Filter by activity type if not 'all'
            if activity_type_filter and activity_type_filter != 'all':
                query_conditions.append("c.activity_type = @activity_type")
                parameters.append({"name": "@activity_type", "value": activity_type_filter})
            
            # Build WHERE clause (empty if no conditions)
            where_clause = " WHERE " + " AND ".join(query_conditions) if query_conditions else ""
            
            # Get total count for pagination
            count_query = f"SELECT VALUE COUNT(1) FROM c{where_clause}"
            total_items_result = list(cosmos_activity_logs_container.query_items(
                query=count_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            total_items = total_items_result[0] if total_items_result and isinstance(total_items_result[0], int) else 0
            
            # Calculate pagination
            offset = (page - 1) * per_page
            total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
            
            # Get paginated results
            logs_query = f"""
                SELECT * FROM c{where_clause}
                ORDER BY c.timestamp DESC
                OFFSET {offset} LIMIT {per_page}
            """
            
            debug_print(f"Activity logs query: {logs_query}")
            debug_print(f"Query parameters: {parameters}")
            
            logs = list(cosmos_activity_logs_container.query_items(
                query=logs_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            # Apply search filter in Python (after fetching from Cosmos)
            if search_term:
                filtered_logs = []
                for log in logs:
                    # Search in various fields
                    searchable_text = ' '.join([
                        str(log.get('activity_type', '')),
                        str(log.get('user_id', '')),
                        str(log.get('login_method', '')),
                        str(log.get('conversation', {}).get('title', '')),
                        str(log.get('document', {}).get('file_name', '')),
                        str(log.get('token_type', '')),
                        str(log.get('workspace_type', ''))
                    ]).lower()
                    
                    if search_term in searchable_text:
                        filtered_logs.append(log)
                
                logs = filtered_logs
                # Recalculate total_items for filtered results
                total_items = len(logs)
                total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
            
            # Get unique user IDs from logs
            user_ids = set(log.get('user_id') for log in logs if log.get('user_id'))
            
            # Fetch user information for display names/emails
            user_map = {}
            if user_ids:
                for user_id in user_ids:
                    try:
                        user_doc = cosmos_user_settings_container.read_item(
                            item=user_id,
                            partition_key=user_id
                        )
                        user_map[user_id] = {
                            'email': user_doc.get('email', ''),
                            'display_name': user_doc.get('display_name', '')
                        }
                    except:
                        user_map[user_id] = {
                            'email': '',
                            'display_name': ''
                        }
            
            return jsonify({
                'logs': logs,
                'user_map': user_map,
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
            debug_print(f"Error getting activity logs: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to fetch activity logs'}), 500

    # ============================================================================
    # APPROVAL WORKFLOW ENDPOINTS
    # ============================================================================

    @app.route('/api/admin/control-center/approvals', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_get_approvals():
        """
        Get approval requests visible to the current user.
        
        Query Parameters:
            page (int): Page number (default: 1)
            page_size (int): Items per page (default: 20)
            status (str): Filter by status (pending, approved, denied, all)
            action_type (str): Filter by action type
            search (str): Search by group name or reason
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            
            # Get user roles from session
            user_roles = user.get('roles', [])
            
            # Get query parameters
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
            status_filter = request.args.get('status', 'all')
            action_type_filter = request.args.get('action_type', 'all')
            search_query = request.args.get('search', '')
            
            # Determine include_completed based on status filter
            include_completed = (status_filter == 'all' or status_filter in ['approved', 'denied'])
            
            # Map action_type to request_type_filter
            request_type_filter = None if action_type_filter == 'all' else action_type_filter
            
            # Fetch approvals
            result = get_pending_approvals(
                user_id=user_id,
                user_roles=user_roles,
                page=page,
                per_page=page_size,
                include_completed=include_completed,
                request_type_filter=request_type_filter
            )
            
            # Add can_approve field to each approval
            approvals_with_permission = []
            for approval in result.get('approvals', []):
                approval_copy = dict(approval)
                # User can approve if they didn't create the request OR if they're the only admin
                approval_copy['can_approve'] = (approval.get('requester_id') != user_id)
                approvals_with_permission.append(approval_copy)
            
            # Rename fields to match frontend expectations
            return jsonify({
                'success': True,
                'approvals': approvals_with_permission,
                'total_count': result.get('total', 0),
                'page': result.get('page', 1),
                'page_size': result.get('per_page', page_size),
                'total_pages': result.get('total_pages', 0)
            }), 200
            
        except Exception as e:
            debug_print(f"Error fetching approvals: {e}")
            import traceback
            debug_print(traceback.format_exc())
            return jsonify({'error': 'Failed to fetch approvals', 'details': str(e)}), 500

    @app.route('/api/admin/control-center/approvals/<approval_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_get_approval_by_id(approval_id):
        """
        Get a single approval request by ID.
        
        Query Parameters:
            group_id (str): Group ID (partition key)
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            
            group_id = request.args.get('group_id')
            if not group_id:
                return jsonify({'error': 'group_id query parameter is required'}), 400
            
            # Get the approval
            approval = cosmos_approvals_container.read_item(
                item=approval_id,
                partition_key=group_id
            )
            
            # Add can_approve field
            approval['can_approve'] = (approval.get('requester_id') != user_id)
            
            return jsonify(approval), 200
            
        except Exception as e:
            debug_print(f"Error fetching approval {approval_id}: {e}")
            import traceback
            debug_print(traceback.format_exc())
            return jsonify({'error': 'Failed to fetch approval', 'details': str(e)}), 500

    @app.route('/api/admin/control-center/approvals/<approval_id>/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_approve_request(approval_id):
        """
        Approve an approval request and execute the action.
        
        Body:
            group_id (str): Group ID (partition key)
            comment (str, optional): Approval comment
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            user_email = user.get('preferred_username', user.get('email', 'unknown'))
            user_name = user.get('name', user_email)
            
            data = request.get_json()
            group_id = data.get('group_id')
            comment = data.get('comment', '')
            
            if not group_id:
                return jsonify({'error': 'group_id is required'}), 400
            
            # Approve the request
            approval = approve_request(
                approval_id=approval_id,
                group_id=group_id,
                approver_id=user_id,
                approver_email=user_email,
                approver_name=user_name,
                comment=comment
            )
            
            # Execute the approved action
            execution_result = _execute_approved_action(approval, user_id, user_email, user_name)
            
            return jsonify({
                'success': True,
                'message': 'Request approved and executed',
                'approval': approval,
                'execution_result': execution_result
            }), 200
            
        except Exception as e:
            debug_print(f"Error approving request: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin/control-center/approvals/<approval_id>/deny', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @control_center_required('admin')
    def api_admin_deny_request(approval_id):
        """
        Deny an approval request.
        
        Body:
            group_id (str): Group ID (partition key)
            comment (str): Reason for denial (required)
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            user_email = user.get('preferred_username', user.get('email', 'unknown'))
            user_name = user.get('name', user_email)
            
            data = request.get_json()
            group_id = data.get('group_id')
            comment = data.get('comment', '')
            
            if not group_id:
                return jsonify({'error': 'group_id is required'}), 400
            
            if not comment:
                return jsonify({'error': 'comment is required for denial'}), 400
            
            # Deny the request
            approval = deny_request(
                approval_id=approval_id,
                group_id=group_id,
                denier_id=user_id,
                denier_email=user_email,
                denier_name=user_name,
                comment=comment,
                auto_denied=False
            )
            
            return jsonify({
                'success': True,
                'message': 'Request denied',
                'approval': approval
            }), 200
            
        except Exception as e:
            debug_print(f"Error denying request: {e}")
            return jsonify({'error': str(e)}), 500
    
    # New standalone approvals API endpoints (accessible to all users with permissions)
    @app.route('/api/approvals', methods=['GET'])
    @login_required
    def api_get_approvals():
        """
        Get approval requests visible to the current user (admins, control center admins, and group owners).
        
        Query Parameters:
            page (int): Page number (default: 1)
            page_size (int): Items per page (default: 20)
            status (str): Filter by status (pending, approved, denied, all)
            action_type (str): Filter by action type
            search (str): Search by group name or reason
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            user_roles = user.get('roles', [])
            
            # Get query parameters
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
            status_filter = request.args.get('status', 'pending')
            action_type_filter = request.args.get('action_type', 'all')
            search_query = request.args.get('search', '')
            
            debug_print(f"📋 [APPROVALS API] Fetching approvals - status_filter: {status_filter}, action_type: {action_type_filter}")
            
            # Determine include_completed based on status filter
            # 'all' means show everything, specific statuses mean show only those
            include_completed = (status_filter in ['all', 'approved', 'denied', 'executed'])
            
            debug_print(f"📋 [APPROVALS API] include_completed: {include_completed}")
            
            # Map action_type to request_type_filter
            request_type_filter = None if action_type_filter == 'all' else action_type_filter
            
            # Fetch approvals
            result = get_pending_approvals(
                user_id=user_id,
                user_roles=user_roles,
                page=page,
                per_page=page_size,
                include_completed=include_completed,
                request_type_filter=request_type_filter,
                status_filter=status_filter
            )
            
            # Add can_approve field to each approval
            approvals_with_permission = []
            for approval in result.get('approvals', []):
                approval_copy = dict(approval)
                # User can approve if they didn't create the request
                approval_copy['can_approve'] = (approval.get('requester_id') != user_id)
                approvals_with_permission.append(approval_copy)
            
            return jsonify({
                'success': True,
                'approvals': approvals_with_permission,
                'total_count': result.get('total', 0),
                'page': result.get('page', 1),
                'page_size': result.get('per_page', page_size),
                'total_pages': result.get('total_pages', 0)
            }), 200
            
        except Exception as e:
            debug_print(f"Error fetching approvals: {e}")
            import traceback
            debug_print(traceback.format_exc())
            return jsonify({'error': 'Failed to fetch approvals', 'details': str(e)}), 500

    @app.route('/api/approvals/<approval_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    def api_get_approval_by_id(approval_id):
        """
        Get a single approval request by ID.
        
        Query Parameters:
            group_id (str): Group ID (partition key)
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            
            group_id = request.args.get('group_id')
            if not group_id:
                return jsonify({'error': 'group_id query parameter is required'}), 400
            
            # Get the approval
            approval = cosmos_approvals_container.read_item(
                item=approval_id,
                partition_key=group_id
            )
            
            # Add can_approve field
            approval['can_approve'] = (approval.get('requester_id') != user_id)
            
            return jsonify(approval), 200
            
        except Exception as e:
            debug_print(f"Error fetching approval {approval_id}: {e}")
            import traceback
            debug_print(traceback.format_exc())
            return jsonify({'error': 'Failed to fetch approval', 'details': str(e)}), 500

    @app.route('/api/approvals/<approval_id>/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    def api_approve_request(approval_id):
        """
        Approve an approval request and execute the action.
        
        Body:
            group_id (str): Group ID (partition key)
            comment (str, optional): Approval comment
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            user_email = user.get('preferred_username', user.get('email', 'unknown'))
            user_name = user.get('name', user_email)
            
            data = request.get_json()
            group_id = data.get('group_id')
            comment = data.get('comment', '')
            
            if not group_id:
                return jsonify({'error': 'group_id is required'}), 400
            
            # Approve the request
            approval = approve_request(
                approval_id=approval_id,
                group_id=group_id,
                approver_id=user_id,
                approver_email=user_email,
                approver_name=user_name,
                comment=comment
            )
            
            # Execute the approved action
            execution_result = _execute_approved_action(approval, user_id, user_email, user_name)
            
            return jsonify({
                'success': True,
                'message': 'Request approved and executed',
                'approval': approval,
                'execution_result': execution_result
            }), 200
            
        except Exception as e:
            debug_print(f"Error approving request: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/approvals/<approval_id>/deny', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    def api_deny_request(approval_id):
        """
        Deny an approval request.
        
        Body:
            group_id (str): Group ID (partition key)
            comment (str): Reason for denial (required)
        """
        try:
            user = session.get('user', {})
            user_id = user.get('oid') or user.get('sub')
            user_email = user.get('preferred_username', user.get('email', 'unknown'))
            user_name = user.get('name', user_email)
            
            data = request.get_json()
            group_id = data.get('group_id')
            comment = data.get('comment', '')
            
            if not group_id:
                return jsonify({'error': 'group_id is required'}), 400
            
            if not comment:
                return jsonify({'error': 'comment is required for denial'}), 400
            
            # Deny the request
            approval = deny_request(
                approval_id=approval_id,
                group_id=group_id,
                denier_id=user_id,
                denier_email=user_email,
                denier_name=user_name,
                comment=comment,
                auto_denied=False
            )
            
            return jsonify({
                'success': True,
                'message': 'Request denied',
                'approval': approval
            }), 200
            
        except Exception as e:
            debug_print(f"Error denying request: {e}")
            return jsonify({'error': str(e)}), 500

    def _execute_approved_action(approval, executor_id, executor_email, executor_name):
        """
        Execute the action specified in an approved request.
        
        Args:
            approval: Approved request document
            executor_id: User ID executing the action
            executor_email: Email of executor
            executor_name: Display name of executor
        
        Returns:
            Result dictionary with success status and message
        """
        try:
            request_type = approval['request_type']
            group_id = approval['group_id']
            
            if request_type == TYPE_TAKE_OWNERSHIP:
                # Execute take ownership
                # Check if this is for a public workspace or group
                if approval.get('metadata', {}).get('entity_type') == 'workspace':
                    result = _execute_take_workspace_ownership(approval, executor_id, executor_email, executor_name)
                else:
                    result = _execute_take_ownership(approval, executor_id, executor_email, executor_name)
            
            elif request_type == TYPE_TRANSFER_OWNERSHIP:
                # Execute transfer ownership
                # Check if this is for a public workspace or group
                if approval.get('metadata', {}).get('entity_type') == 'workspace':
                    result = _execute_transfer_workspace_ownership(approval, executor_id, executor_email, executor_name)
                else:
                    result = _execute_transfer_ownership(approval, executor_id, executor_email, executor_name)
            
            elif request_type == TYPE_DELETE_DOCUMENTS:
                # Check if this is for a public workspace or group
                if approval.get('metadata', {}).get('entity_type') == 'workspace':
                    result = _execute_delete_public_workspace_documents(approval, executor_id, executor_email, executor_name)
                else:
                    result = _execute_delete_documents(approval, executor_id, executor_email, executor_name)
            
            elif request_type == TYPE_DELETE_GROUP:
                # Check if this is for a public workspace or group
                if approval.get('metadata', {}).get('entity_type') == 'workspace':
                    result = _execute_delete_public_workspace(approval, executor_id, executor_email, executor_name)
                else:
                    result = _execute_delete_group(approval, executor_id, executor_email, executor_name)
            
            elif request_type == TYPE_DELETE_USER_DOCUMENTS:
                # Execute delete user documents
                result = _execute_delete_user_documents(approval, executor_id, executor_email, executor_name)
            
            else:
                result = {'success': False, 'message': f'Unknown request type: {request_type}'}
            
            # Mark approval as executed
            mark_approval_executed(
                approval_id=approval['id'],
                group_id=group_id,
                success=result['success'],
                result_message=result['message']
            )
            
            return result
            
        except Exception as e:
            # Mark as failed
            mark_approval_executed(
                approval_id=approval['id'],
                group_id=approval['group_id'],
                success=False,
                result_message=f"Execution error: {str(e)}"
            )
            raise

    def _execute_take_ownership(approval, executor_id, executor_email, executor_name):
        """Execute admin take ownership action."""
        try:
            group_id = approval['group_id']
            requester_id = approval['requester_id']
            requester_email = approval['requester_email']
            
            # Get the group
            group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            
            old_owner = group.get('owner', {})
            old_owner_id = old_owner.get('id')
            old_owner_email = old_owner.get('email', 'unknown')
            
            # Update owner to requester (the admin who requested)
            group['owner'] = {
                'id': requester_id,
                'email': requester_email,
                'displayName': approval['requester_name']
            }
            
            # Remove requester from special roles if present
            if requester_id in group.get('admins', []):
                group['admins'].remove(requester_id)
            if requester_id in group.get('documentManagers', []):
                group['documentManagers'].remove(requester_id)
            
            # Ensure requester is in users list
            requester_in_users = any(m.get('userId') == requester_id for m in group.get('users', []))
            if not requester_in_users:
                group.setdefault('users', []).append({
                    'userId': requester_id,
                    'email': requester_email,
                    'displayName': approval['requester_name']
                })
            
            # Demote old owner to regular member
            if old_owner_id:
                old_owner_in_users = any(m.get('userId') == old_owner_id for m in group.get('users', []))
                if not old_owner_in_users:
                    group.setdefault('users', []).append({
                        'userId': old_owner_id,
                        'email': old_owner_email,
                        'displayName': old_owner.get('displayName', old_owner_email)
                    })
                
                if old_owner_id in group.get('admins', []):
                    group['admins'].remove(old_owner_id)
                if old_owner_id in group.get('documentManagers', []):
                    group['documentManagers'].remove(old_owner_id)
            
            group['modifiedDate'] = datetime.utcnow().isoformat()
            cosmos_groups_container.upsert_item(group)
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'group_ownership_change',
                'activity_type': 'admin_take_ownership_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'admin_user_id': requester_id,
                'admin_email': requester_email,
                'approver_id': executor_id,
                'approver_email': executor_email,
                'group_id': group_id,
                'group_name': group.get('name', 'Unknown'),
                'old_owner_id': old_owner_id,
                'old_owner_email': old_owner_email,
                'new_owner_id': requester_id,
                'new_owner_email': requester_email,
                'approval_id': approval['id'],
                'description': f"Admin {requester_email} took ownership (approved by {executor_email})"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            return {
                'success': True,
                'message': f'Ownership transferred to {requester_email}'
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Failed to take ownership: {str(e)}'}

    def _execute_take_workspace_ownership(approval, executor_id, executor_email, executor_name):
        """Execute admin take workspace ownership action."""
        try:
            workspace_id = approval.get('workspace_id') or approval.get('group_id')
            requester_id = approval['requester_id']
            requester_email = approval['requester_email']
            requester_name = approval['requester_name']
            
            # Get the workspace
            workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            
            # Get old owner info
            old_owner = workspace.get('owner', {})
            if isinstance(old_owner, dict):
                old_owner_id = old_owner.get('userId')
                old_owner_email = old_owner.get('email')
                old_owner_name = old_owner.get('displayName')
            else:
                # Old format where owner is just a string
                old_owner_id = old_owner
                # Try to get user info
                try:
                    old_owner_user = cosmos_user_settings_container.read_item(
                        item=old_owner_id,
                        partition_key=old_owner_id
                    )
                    old_owner_email = old_owner_user.get('email', 'unknown')
                    old_owner_name = old_owner_user.get('display_name', old_owner_email)
                except:
                    old_owner_email = 'unknown'
                    old_owner_name = 'unknown'
            
            # Update owner to requester (the admin who requested) with full user object
            workspace['owner'] = {
                'userId': requester_id,
                'email': requester_email,
                'displayName': requester_name
            }
            
            # Remove requester from admins/documentManagers if present
            new_admins = []
            for admin in workspace.get('admins', []):
                admin_id = admin.get('userId') if isinstance(admin, dict) else admin
                if admin_id != requester_id:
                    # Ensure admin is full object
                    if isinstance(admin, dict):
                        new_admins.append(admin)
                    else:
                        # Convert string ID to object if needed
                        try:
                            admin_user = cosmos_user_settings_container.read_item(
                                item=admin,
                                partition_key=admin
                            )
                            new_admins.append({
                                'userId': admin,
                                'email': admin_user.get('email', 'unknown'),
                                'displayName': admin_user.get('display_name', 'unknown')
                            })
                        except:
                            pass
            workspace['admins'] = new_admins
            
            new_dms = []
            for dm in workspace.get('documentManagers', []):
                dm_id = dm.get('userId') if isinstance(dm, dict) else dm
                if dm_id != requester_id:
                    # Ensure dm is full object
                    if isinstance(dm, dict):
                        new_dms.append(dm)
                    else:
                        # Convert string ID to object if needed
                        try:
                            dm_user = cosmos_user_settings_container.read_item(
                                item=dm,
                                partition_key=dm
                            )
                            new_dms.append({
                                'userId': dm,
                                'email': dm_user.get('email', 'unknown'),
                                'displayName': dm_user.get('display_name', 'unknown')
                            })
                        except:
                            pass
            workspace['documentManagers'] = new_dms
            
            # Demote old owner to admin if not already there
            if old_owner_id and old_owner_id != requester_id:
                old_owner_in_admins = any(
                    (a.get('userId') if isinstance(a, dict) else a) == old_owner_id 
                    for a in workspace.get('admins', [])
                )
                old_owner_in_dms = any(
                    (dm.get('userId') if isinstance(dm, dict) else dm) == old_owner_id 
                    for dm in workspace.get('documentManagers', [])
                )
                
                if not old_owner_in_admins and not old_owner_in_dms:
                    # Add old owner as admin
                    workspace.setdefault('admins', []).append({
                        'userId': old_owner_id,
                        'email': old_owner_email,
                        'displayName': old_owner_name
                    })
            
            workspace['modifiedDate'] = datetime.utcnow().isoformat()
            cosmos_public_workspaces_container.upsert_item(workspace)
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'workspace_ownership_change',
                'activity_type': 'admin_take_ownership_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': requester_id,
                'requester_email': requester_email,
                'approver_id': executor_id,
                'approver_email': executor_email,
                'workspace_id': workspace_id,
                'workspace_name': workspace.get('name', 'Unknown'),
                'old_owner_id': old_owner_id,
                'old_owner_email': old_owner_email,
                'new_owner_id': requester_id,
                'new_owner_email': requester_email,
                'approval_id': approval['id'],
                'description': f"Admin {requester_email} took ownership (approved by {executor_email})"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            return {
                'success': True,
                'message': f"Ownership transferred to {requester_email}"
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Failed to take workspace ownership: {str(e)}'}

    def _execute_transfer_ownership(approval, executor_id, executor_email, executor_name):
        """Execute transfer ownership action."""
        try:
            group_id = approval['group_id']
            new_owner_id = approval['metadata'].get('new_owner_id')
            
            if not new_owner_id:
                return {'success': False, 'message': 'new_owner_id not found in approval metadata'}
            
            # Get the group
            group = cosmos_groups_container.read_item(item=group_id, partition_key=group_id)
            
            # Find new owner in members
            new_owner_member = None
            for member in group.get('users', []):
                if member.get('userId') == new_owner_id:
                    new_owner_member = member
                    break
            
            if not new_owner_member:
                return {'success': False, 'message': 'New owner not found in group members'}
            
            old_owner = group.get('owner', {})
            old_owner_id = old_owner.get('id')
            
            # Update owner
            group['owner'] = {
                'id': new_owner_id,
                'email': new_owner_member.get('email'),
                'displayName': new_owner_member.get('displayName')
            }
            
            # Remove new owner from special roles
            if new_owner_id in group.get('admins', []):
                group['admins'].remove(new_owner_id)
            if new_owner_id in group.get('documentManagers', []):
                group['documentManagers'].remove(new_owner_id)
            
            # Demote old owner to member
            if old_owner_id:
                old_owner_in_users = any(m.get('userId') == old_owner_id for m in group.get('users', []))
                if not old_owner_in_users:
                    group.setdefault('users', []).append({
                        'userId': old_owner_id,
                        'email': old_owner.get('email'),
                        'displayName': old_owner.get('displayName')
                    })
                
                if old_owner_id in group.get('admins', []):
                    group['admins'].remove(old_owner_id)
                if old_owner_id in group.get('documentManagers', []):
                    group['documentManagers'].remove(old_owner_id)
            
            group['modifiedDate'] = datetime.utcnow().isoformat()
            cosmos_groups_container.upsert_item(group)
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'group_ownership_change',
                'activity_type': 'transfer_ownership_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'group_id': group_id,
                'group_name': group.get('name', 'Unknown'),
                'old_owner_id': old_owner_id,
                'old_owner_email': old_owner.get('email'),
                'new_owner_id': new_owner_id,
                'new_owner_email': new_owner_member.get('email'),
                'approval_id': approval['id'],
                'description': f"Ownership transferred to {new_owner_member.get('email')} (approved by {executor_email})"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            return {
                'success': True,
                'message': f"Ownership transferred to {new_owner_member.get('email')}"
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Failed to transfer ownership: {str(e)}'}

    def _execute_transfer_workspace_ownership(approval, executor_id, executor_email, executor_name):
        """Execute transfer workspace ownership action."""
        try:
            workspace_id = approval.get('workspace_id') or approval.get('group_id')
            new_owner_id = approval['metadata'].get('new_owner_id')
            new_owner_email = approval['metadata'].get('new_owner_email')
            new_owner_name = approval['metadata'].get('new_owner_name')
            
            if not new_owner_id:
                return {'success': False, 'message': 'new_owner_id not found in approval metadata'}
            
            # Get the workspace
            workspace = cosmos_public_workspaces_container.read_item(item=workspace_id, partition_key=workspace_id)
            
            # Get old owner info
            old_owner = workspace.get('owner', {})
            if isinstance(old_owner, dict):
                old_owner_id = old_owner.get('userId')
                old_owner_email = old_owner.get('email')
                old_owner_name = old_owner.get('displayName')
            else:
                # Handle case where owner is just a string (old format)
                old_owner_id = old_owner
                # Try to get full user info
                try:
                    old_owner_user = cosmos_user_settings_container.read_item(
                        item=old_owner_id,
                        partition_key=old_owner_id
                    )
                    old_owner_email = old_owner_user.get('email', 'unknown')
                    old_owner_name = old_owner_user.get('display_name', old_owner_email)
                except:
                    old_owner_email = 'unknown'
                    old_owner_name = 'unknown'
            
            # Update owner with full user object
            workspace['owner'] = {
                'userId': new_owner_id,
                'email': new_owner_email,
                'displayName': new_owner_name
            }
            
            # Remove new owner from admins/documentManagers if present
            new_admins = []
            for admin in workspace.get('admins', []):
                admin_id = admin.get('userId') if isinstance(admin, dict) else admin
                if admin_id != new_owner_id:
                    # Ensure admin is full object
                    if isinstance(admin, dict):
                        new_admins.append(admin)
                    else:
                        # Convert string ID to object if needed
                        try:
                            admin_user = cosmos_user_settings_container.read_item(
                                item=admin,
                                partition_key=admin
                            )
                            new_admins.append({
                                'userId': admin,
                                'email': admin_user.get('email', 'unknown'),
                                'displayName': admin_user.get('display_name', 'unknown')
                            })
                        except:
                            pass
            workspace['admins'] = new_admins
            
            new_dms = []
            for dm in workspace.get('documentManagers', []):
                dm_id = dm.get('userId') if isinstance(dm, dict) else dm
                if dm_id != new_owner_id:
                    # Ensure dm is full object
                    if isinstance(dm, dict):
                        new_dms.append(dm)
                    else:
                        # Convert string ID to object if needed
                        try:
                            dm_user = cosmos_user_settings_container.read_item(
                                item=dm,
                                partition_key=dm
                            )
                            new_dms.append({
                                'userId': dm,
                                'email': dm_user.get('email', 'unknown'),
                                'displayName': dm_user.get('display_name', 'unknown')
                            })
                        except:
                            pass
            workspace['documentManagers'] = new_dms
            
            # Add old owner to admins if not already there
            if old_owner_id and old_owner_id != new_owner_id:
                old_owner_in_admins = any(
                    (a.get('userId') if isinstance(a, dict) else a) == old_owner_id 
                    for a in workspace.get('admins', [])
                )
                old_owner_in_dms = any(
                    (dm.get('userId') if isinstance(dm, dict) else dm) == old_owner_id 
                    for dm in workspace.get('documentManagers', [])
                )
                
                if not old_owner_in_admins and not old_owner_in_dms:
                    # Add old owner as admin
                    workspace.setdefault('admins', []).append({
                        'userId': old_owner_id,
                        'email': old_owner_email,
                        'displayName': old_owner_name
                    })
            
            workspace['modifiedDate'] = datetime.utcnow().isoformat()
            cosmos_public_workspaces_container.upsert_item(workspace)
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'workspace_ownership_change',
                'activity_type': 'transfer_ownership_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'workspace_id': workspace_id,
                'workspace_name': workspace.get('name', 'Unknown'),
                'old_owner_id': old_owner_id,
                'old_owner_email': old_owner_email,
                'new_owner_id': new_owner_id,
                'new_owner_email': new_owner_email,
                'approval_id': approval['id'],
                'description': f"Ownership transferred to {new_owner_email} (approved by {executor_email})"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            return {
                'success': True,
                'message': f"Ownership transferred to {new_owner_email}"
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Failed to transfer workspace ownership: {str(e)}'}

    def _execute_delete_documents(approval, executor_id, executor_email, executor_name):
        """Execute delete all documents action."""
        try:
            group_id = approval['group_id']
            
            debug_print(f"🔍 [DELETE_GROUP_DOCS] Starting deletion for group_id: {group_id}")
            
            # Query all document metadata for this group
            query = "SELECT * FROM c WHERE c.group_id = @group_id AND c.type = 'document_metadata'"
            parameters = [{"name": "@group_id", "value": group_id}]
            
            debug_print(f"🔍 [DELETE_GROUP_DOCS] Query: {query}")
            debug_print(f"🔍 [DELETE_GROUP_DOCS] Parameters: {parameters}")
            debug_print(f"🔍 [DELETE_GROUP_DOCS] Using partition_key: {group_id}")
            
            # Query with partition key for better performance
            documents = list(cosmos_group_documents_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=group_id
            ))
            
            debug_print(f"📊 [DELETE_GROUP_DOCS] Found {len(documents)} documents with partition key query")
            
            # If no documents found with partition key, try cross-partition query
            if len(documents) == 0:
                debug_print(f"⚠️ [DELETE_GROUP_DOCS] No documents found with partition key, trying cross-partition query")
                documents = list(cosmos_group_documents_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                debug_print(f"📊 [DELETE_GROUP_DOCS] Cross-partition query found {len(documents)} documents")
                
                # Log sample document for debugging
                if len(documents) > 0:
                    sample_doc = documents[0]
                    debug_print(f"📄 [DELETE_GROUP_DOCS] Sample document structure: id={sample_doc.get('id')}, type={sample_doc.get('type')}, group_id={sample_doc.get('group_id')}")
            
            deleted_count = 0
            
            # Use proper deletion APIs for each document
            for doc in documents:
                try:
                    doc_id = doc['id']
                    debug_print(f"🗑️ [DELETE_GROUP_DOCS] Deleting document {doc_id}")
                    
                    # Use delete_document API which handles:
                    # - Blob storage deletion
                    # - AI Search index deletion
                    # - Cosmos DB metadata deletion
                    # Note: For group documents, we don't have a user_id, so we pass None
                    delete_result = delete_document(
                        user_id=None,
                        document_id=doc_id,
                        group_id=group_id
                    )
                    
                    # Check if delete_result is valid and successful
                    if delete_result and delete_result.get('success'):
                        # Delete document chunks using proper API
                        delete_document_chunks(
                            document_id=doc_id,
                            group_id=group_id
                        )
                        
                        deleted_count += 1
                        debug_print(f"✅ [DELETE_GROUP_DOCS] Successfully deleted document {doc_id}")
                    else:
                        error_msg = delete_result.get('message') if delete_result else 'delete_document returned None'
                        debug_print(f"❌ [DELETE_GROUP_DOCS] Failed to delete document {doc_id}: {error_msg}")
                    
                except Exception as doc_error:
                    debug_print(f"❌ [DELETE_GROUP_DOCS] Error deleting document {doc.get('id')}: {doc_error}")
            
            # Invalidate group search cache after deletion
            try:
                invalidate_group_search_cache(group_id)
                debug_print(f"🔄 [DELETE_GROUP_DOCS] Invalidated search cache for group {group_id}")
            except Exception as cache_error:
                debug_print(f"⚠️ [DELETE_GROUP_DOCS] Could not invalidate search cache: {cache_error}")
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'group_documents_deletion',
                'activity_type': 'delete_all_documents_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'group_id': group_id,
                'group_name': approval['group_name'],
                'documents_deleted': deleted_count,
                'approval_id': approval['id'],
                'description': f"All documents deleted from group (approved by {executor_email})"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            debug_print(f"[ControlCenter] Group Documents Deleted (Approved) -- group_id: {group_id}, documents_deleted: {deleted_count}")
            
            return {
                'success': True,
                'message': f'Deleted {deleted_count} documents'
            }
            
        except Exception as e:
            debug_print(f"[DELETE_GROUP_DOCS] Fatal error: {e}")
            return {'success': False, 'message': f'Failed to delete documents: {str(e)}'}

    def _execute_delete_public_workspace_documents(approval, executor_id, executor_email, executor_name):
        """Execute delete all documents in a public workspace."""
        try:
            workspace_id = approval['group_id']  # workspace_id is stored as group_id
            
            debug_print(f"🔍 [DELETE_WORKSPACE_DOCS] Starting deletion for workspace_id: {workspace_id}")
            
            # Query all documents for this workspace
            query = "SELECT c.id FROM c WHERE c.public_workspace_id = @workspace_id"
            parameters = [{"name": "@workspace_id", "value": workspace_id}]
            
            debug_print(f"🔍 [DELETE_WORKSPACE_DOCS] Query: {query}")
            debug_print(f"🔍 [DELETE_WORKSPACE_DOCS] Parameters: {parameters}")
            
            documents = list(cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            debug_print(f"📊 [DELETE_WORKSPACE_DOCS] Found {len(documents)} documents")
            
            deleted_count = 0
            for doc in documents:
                try:
                    doc_id = doc['id']
                    debug_print(f"🗑️ [DELETE_WORKSPACE_DOCS] Deleting document {doc_id}")
                    
                    # Delete document chunks and metadata using proper APIs
                    delete_document_chunks(
                        document_id=doc_id,
                        public_workspace_id=workspace_id
                    )
                    
                    delete_document(
                        user_id=None,
                        document_id=doc_id,
                        public_workspace_id=workspace_id
                    )
                    
                    deleted_count += 1
                    debug_print(f"✅ [DELETE_WORKSPACE_DOCS] Successfully deleted document {doc_id}")
                    
                except Exception as doc_error:
                    debug_print(f"❌ [DELETE_WORKSPACE_DOCS] Error deleting document {doc_id}: {doc_error}")
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'public_workspace_documents_deletion',
                'activity_type': 'delete_all_documents_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'workspace_id': workspace_id,
                'workspace_name': approval.get('metadata', {}).get('workspace_name', 'Unknown'),
                'documents_deleted': deleted_count,
                'approval_id': approval['id'],
                'description': f"All documents deleted from public workspace (approved by {executor_email})",
                'workspace_context': {
                    'public_workspace_id': workspace_id
                }
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            debug_print(f"[ControlCenter] Public Workspace Documents Deleted (Approved) -- workspace_id: {workspace_id}, documents_deleted: {deleted_count}")
            
            return {
                'success': True,
                'message': f'Deleted {deleted_count} documents from public workspace'
            }
            
        except Exception as e:
            debug_print(f"[DELETE_WORKSPACE_DOCS] Fatal error: {e}")
            return {'success': False, 'message': f'Failed to delete workspace documents: {str(e)}'}

    def _execute_delete_public_workspace(approval, executor_id, executor_email, executor_name):
        """Execute delete entire public workspace action."""
        try:
            workspace_id = approval['group_id']  # workspace_id is stored as group_id
            
            debug_print(f"🔍 [DELETE_WORKSPACE] Starting deletion for workspace_id: {workspace_id}")
            
            # First delete all documents
            doc_result = _execute_delete_public_workspace_documents(approval, executor_id, executor_email, executor_name)
            
            if not doc_result['success']:
                return doc_result
            
            # Delete the workspace itself
            try:
                cosmos_public_workspaces_container.delete_item(
                    item=workspace_id,
                    partition_key=workspace_id
                )
                debug_print(f"✅ [DELETE_WORKSPACE] Successfully deleted workspace {workspace_id}")
            except Exception as del_e:
                debug_print(f"❌ [DELETE_WORKSPACE] Error deleting workspace {workspace_id}: {del_e}")
                return {'success': False, 'message': f'Failed to delete workspace: {str(del_e)}'}
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'public_workspace_deletion',
                'activity_type': 'delete_workspace_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'workspace_id': workspace_id,
                'workspace_name': approval.get('metadata', {}).get('workspace_name', 'Unknown'),
                'approval_id': approval['id'],
                'description': f"Public workspace completely deleted (approved by {executor_email})",
                'workspace_context': {
                    'public_workspace_id': workspace_id
                }
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            debug_print(f"[ControlCenter] Public Workspace Deleted (Approved) -- workspace_id: {workspace_id}")
            
            return {
                'success': True,
                'message': 'Public workspace and all documents deleted successfully'
            }
            
        except Exception as e:
            debug_print(f"[DELETE_WORKSPACE] Fatal error: {e}")
            return {'success': False, 'message': f'Failed to delete workspace: {str(e)}'}

    def _execute_delete_group(approval, executor_id, executor_email, executor_name):
        """Execute delete entire group action."""
        try:
            group_id = approval['group_id']
            
            # First delete all documents
            doc_result = _execute_delete_documents(approval, executor_id, executor_email, executor_name)
            
            # Delete group conversations (optional - could keep for audit)
            try:
                query = "SELECT * FROM c WHERE c.group_id = @group_id"
                parameters = [{"name": "@group_id", "value": group_id}]
                
                conversations = list(cosmos_group_conversations_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                for conv in conversations:
                    cosmos_group_conversations_container.delete_item(
                        item=conv['id'],
                        partition_key=group_id
                    )
            except Exception as conv_error:
                debug_print(f"Error deleting conversations: {conv_error}")
            
            # Delete group messages (optional)
            try:
                messages = list(cosmos_group_messages_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                
                for msg in messages:
                    cosmos_group_messages_container.delete_item(
                        item=msg['id'],
                        partition_key=group_id
                    )
            except Exception as msg_error:
                debug_print(f"Error deleting messages: {msg_error}")
            
            # Finally, delete the group itself using proper API
            debug_print(f"🗑️ [DELETE GROUP] Deleting group document using delete_group() API")
            delete_group(group_id)
            debug_print(f"✅ [DELETE GROUP] Group {group_id} successfully deleted")
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'group_deletion',
                'activity_type': 'delete_group_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'group_id': group_id,
                'group_name': approval['group_name'],
                'approval_id': approval['id'],
                'description': f"Group completely deleted (approved by {executor_email})"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            return {
                'success': True,
                'message': 'Group completely deleted'
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Failed to delete group: {str(e)}'}

    def _execute_delete_user_documents(approval, executor_id, executor_email, executor_name):
        """Execute delete all user documents action."""
        try:
            from functions_documents import delete_document, delete_document_chunks
            from utils_cache import invalidate_personal_search_cache
            
            user_id = approval['metadata'].get('user_id')
            user_email = approval['metadata'].get('user_email', 'unknown')
            user_name = approval['metadata'].get('user_name', user_email)
            
            if not user_id:
                return {'success': False, 'message': 'User ID not found in approval metadata'}
            
            # Query all personal documents for this user
            # Personal documents are stored in cosmos_user_documents_container with user_id as partition key
            query = "SELECT * FROM c WHERE c.user_id = @user_id"
            parameters = [{"name": "@user_id", "value": user_id}]
            
            debug_print(f"🔍 [DELETE_USER_DOCS] Querying for user_id: {user_id}")
            debug_print(f"🔍 [DELETE_USER_DOCS] Query: {query}")
            debug_print(f"🔍 [DELETE_USER_DOCS] Container: cosmos_user_documents_container")
            
            documents = list(cosmos_user_documents_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=user_id  # Use partition key for efficient query
            ))
            
            debug_print(f"📊 [DELETE_USER_DOCS] Found {len(documents)} documents with partition key query")
            if len(documents) > 0:
                debug_print(f"📄 [DELETE_USER_DOCS] First document sample: id={documents[0].get('id', 'no-id')}, file_name={documents[0].get('file_name', 'no-filename')}, type={documents[0].get('type', 'no-type')}")
            else:
                # Try a cross-partition query to see if documents exist elsewhere
                debug_print(f"⚠️ [DELETE_USER_DOCS] No documents found with partition key, trying cross-partition query...")
                documents = list(cosmos_user_documents_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True
                ))
                debug_print(f"📊 [DELETE_USER_DOCS] Cross-partition query found {len(documents)} documents")
                if len(documents) > 0:
                    sample_doc = documents[0]
                    debug_print(f"📄 [DELETE_USER_DOCS] Sample doc fields: {list(sample_doc.keys())}")
                    debug_print(f"📄 [DELETE_USER_DOCS] Sample doc: id={sample_doc.get('id')}, type={sample_doc.get('type')}, user_id={sample_doc.get('user_id')}, file_name={sample_doc.get('file_name')}")
            
            deleted_count = 0
            
            # Use the existing delete_document function for proper cleanup
            for doc in documents:
                try:
                    document_id = doc['id']
                    debug_print(f"🗑️ [DELETE_USER_DOCS] Deleting document {document_id}: {doc.get('file_name', 'unknown')}")
                    
                    # Use the proper delete_document function which handles:
                    # - Blob storage deletion
                    # - AI Search index deletion
                    # - Cosmos DB document deletion
                    delete_document(user_id, document_id)
                    delete_document_chunks(document_id)
                    
                    deleted_count += 1
                    debug_print(f"✅ [DELETE_USER_DOCS] Successfully deleted document {document_id}")
                    
                except Exception as doc_error:
                    debug_print(f"❌ [DELETE_USER_DOCS] Error deleting document {doc.get('id')}: {doc_error}")
            
            # Invalidate search cache for this user
            try:
                invalidate_personal_search_cache(user_id)
                debug_print(f"🔄 [DELETE_USER_DOCS] Invalidated search cache for user {user_id}")
            except Exception as cache_error:
                debug_print(f"⚠️ [DELETE_USER_DOCS] Failed to invalidate search cache: {cache_error}")
            
            # Log to activity logs
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'user_documents_deletion',
                'activity_type': 'delete_all_user_documents_approved',
                'timestamp': datetime.utcnow().isoformat(),
                'requester_id': approval['requester_id'],
                'requester_email': approval['requester_email'],
                'approver_id': executor_id,
                'approver_email': executor_email,
                'target_user_id': user_id,
                'target_user_email': user_email,
                'target_user_name': user_name,
                'documents_deleted': deleted_count,
                'approval_id': approval['id'],
                'description': f"All documents deleted for user {user_name} ({user_email}) - approved by {executor_email}"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
            
            # Log to AppInsights
            log_event("[ControlCenter] User Documents Deleted (Approved)", {
                "executor": executor_email,
                "user_id": user_id,
                "user_email": user_email,
                "documents_deleted": deleted_count,
                "approval_id": approval['id']
            })
            
            return {
                'success': True,
                'message': f'Deleted {deleted_count} documents for user {user_name}'
            }
            
        except Exception as e:
            debug_print(f"Error deleting user documents: {e}")
            return {'success': False, 'message': f'Failed to delete user documents: {str(e)}'}

            return jsonify({'error': 'Failed to retrieve activity logs'}), 500