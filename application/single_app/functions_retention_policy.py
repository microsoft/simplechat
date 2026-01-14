# functions_retention_policy.py

"""
Retention Policy Management

This module handles automated deletion of aged conversations and documents
based on configurable retention policies for personal, group, and public workspaces.

Version: 0.234.067
Implemented in: 0.234.067
"""

from config import *
from functions_settings import get_settings, update_settings, cosmos_user_settings_container
from functions_group import get_user_groups, cosmos_groups_container
from functions_public_workspaces import get_user_public_workspaces, cosmos_public_workspaces_container
from functions_documents import delete_document, delete_document_chunks
from functions_activity_logging import log_conversation_deletion, log_conversation_archival
from functions_notifications import create_notification, create_group_notification, create_public_workspace_notification
from functions_debug import debug_print
from datetime import datetime, timezone, timedelta


def get_all_user_settings():
    """
    Get all user settings from Cosmos DB.
    
    Returns:
        list: List of all user setting documents
    """
    try:
        query = "SELECT * FROM c"
        users = list(cosmos_user_settings_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return users
    except Exception as e:
        debug_print(f"Error fetching all user settings: {e}")
        return []


def get_all_groups():
    """
    Get all groups from Cosmos DB.
    
    Returns:
        list: List of all group documents
    """
    try:
        query = "SELECT * FROM c"
        groups = list(cosmos_groups_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return groups
    except Exception as e:
        debug_print(f"Error fetching all groups: {e}")
        return []


def get_all_public_workspaces():
    """
    Get all public workspaces from Cosmos DB.
    
    Returns:
        list: List of all public workspace documents
    """
    try:
        query = "SELECT * FROM c"
        workspaces = list(cosmos_public_workspaces_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return workspaces
    except Exception as e:
        debug_print(f"Error fetching all public workspaces: {e}")
        return []


def execute_retention_policy(workspace_scopes=None, manual_execution=False):
    """
    Execute retention policy for specified workspace scopes.
    
    Args:
        workspace_scopes (list, optional): List of workspace types to process.
            Can include 'personal', 'group', 'public'. If None, processes all enabled scopes.
        manual_execution (bool): Whether this is a manual execution (bypasses schedule check)
        
    Returns:
        dict: Summary of deletion results
    """
    settings = get_settings()
    
    # Determine which scopes to process
    if workspace_scopes is None:
        workspace_scopes = []
        if settings.get('enable_retention_policy_personal', False):
            workspace_scopes.append('personal')
        if settings.get('enable_retention_policy_group', False):
            workspace_scopes.append('group')
        if settings.get('enable_retention_policy_public', False):
            workspace_scopes.append('public')
    
    if not workspace_scopes:
        debug_print("No retention policy scopes enabled")
        return {
            'success': False,
            'message': 'No retention policy scopes enabled',
            'scopes_processed': []
        }
    
    results = {
        'success': True,
        'execution_time': datetime.now(timezone.utc).isoformat(),
        'manual_execution': manual_execution,
        'scopes_processed': workspace_scopes,
        'personal': {'conversations': 0, 'documents': 0, 'users_affected': 0},
        'group': {'conversations': 0, 'documents': 0, 'workspaces_affected': 0},
        'public': {'conversations': 0, 'documents': 0, 'workspaces_affected': 0},
        'errors': []
    }
    
    try:
        # Process personal workspaces
        if 'personal' in workspace_scopes:
            debug_print("Processing personal workspace retention policies...")
            personal_results = process_personal_retention()
            results['personal'] = personal_results
        
        # Process group workspaces
        if 'group' in workspace_scopes:
            debug_print("Processing group workspace retention policies...")
            group_results = process_group_retention()
            results['group'] = group_results
        
        # Process public workspaces
        if 'public' in workspace_scopes:
            debug_print("Processing public workspace retention policies...")
            public_results = process_public_retention()
            results['public'] = public_results
        
        # Update last run time in settings
        settings['retention_policy_last_run'] = datetime.now(timezone.utc).isoformat()
        
        # Calculate next run time (scheduled for configured hour next day)
        execution_hour = settings.get('retention_policy_execution_hour', 2)
        next_run = datetime.now(timezone.utc).replace(hour=execution_hour, minute=0, second=0, microsecond=0)
        if next_run <= datetime.now(timezone.utc):
            next_run += timedelta(days=1)
        settings['retention_policy_next_run'] = next_run.isoformat()
        
        update_settings(settings)
        
        debug_print(f"Retention policy execution completed: {results}")
        return results
        
    except Exception as e:
        debug_print(f"Error executing retention policy: {e}")
        results['success'] = False
        results['errors'].append(str(e))
        return results


def process_personal_retention():
    """
    Process retention policies for all personal workspaces.
    
    Returns:
        dict: Deletion statistics
    """
    results = {
        'conversations': 0,
        'documents': 0,
        'users_affected': 0,
        'details': []
    }
    
    try:
        # Get all user settings
        all_users = get_all_user_settings()
        
        for user in all_users:
            user_id = user.get('id')
            if not user_id:
                continue
            
            # Get user's retention settings
            user_settings = user.get('settings', {})
            retention_settings = user_settings.get('retention_policy', {})
            
            conversation_retention_days = retention_settings.get('conversation_retention_days', 'none')
            document_retention_days = retention_settings.get('document_retention_days', 'none')
            
            # Skip if both are set to "none"
            if conversation_retention_days == 'none' and document_retention_days == 'none':
                continue
            
            user_deletion_summary = {
                'user_id': user_id,
                'conversations_deleted': 0,
                'documents_deleted': 0,
                'conversation_details': [],
                'document_details': []
            }
            
            # Process conversations
            if conversation_retention_days != 'none':
                try:
                    conv_results = delete_aged_conversations(
                        user_id=user_id,
                        retention_days=int(conversation_retention_days),
                        workspace_type='personal'
                    )
                    user_deletion_summary['conversations_deleted'] = conv_results['count']
                    user_deletion_summary['conversation_details'] = conv_results['details']
                    results['conversations'] += conv_results['count']
                except Exception as e:
                    debug_print(f"Error processing conversations for user {user_id}: {e}")
            
            # Process documents
            if document_retention_days != 'none':
                try:
                    doc_results = delete_aged_documents(
                        user_id=user_id,
                        retention_days=int(document_retention_days),
                        workspace_type='personal'
                    )
                    user_deletion_summary['documents_deleted'] = doc_results['count']
                    user_deletion_summary['document_details'] = doc_results['details']
                    results['documents'] += doc_results['count']
                except Exception as e:
                    debug_print(f"Error processing documents for user {user_id}: {e}")
            
            # Send notification if anything was deleted
            if user_deletion_summary['conversations_deleted'] > 0 or user_deletion_summary['documents_deleted'] > 0:
                send_retention_notification(user_id, user_deletion_summary, 'personal')
                results['users_affected'] += 1
                results['details'].append(user_deletion_summary)
        
        return results
        
    except Exception as e:
        debug_print(f"Error in process_personal_retention: {e}")
        return results


def process_group_retention():
    """
    Process retention policies for all group workspaces.
    
    Returns:
        dict: Deletion statistics
    """
    results = {
        'conversations': 0,
        'documents': 0,
        'workspaces_affected': 0,
        'details': []
    }
    
    try:
        # Get all groups
        all_groups = get_all_groups()
        
        for group in all_groups:
            group_id = group.get('id')
            if not group_id:
                continue
            
            # Get group's retention settings
            retention_settings = group.get('retention_policy', {})
            
            conversation_retention_days = retention_settings.get('conversation_retention_days', 'none')
            document_retention_days = retention_settings.get('document_retention_days', 'none')
            
            # Skip if both are set to "none"
            if conversation_retention_days == 'none' and document_retention_days == 'none':
                continue
            
            group_deletion_summary = {
                'group_id': group_id,
                'group_name': group.get('name', 'Unnamed Group'),
                'conversations_deleted': 0,
                'documents_deleted': 0,
                'conversation_details': [],
                'document_details': []
            }
            
            # Process conversations
            if conversation_retention_days != 'none':
                try:
                    conv_results = delete_aged_conversations(
                        group_id=group_id,
                        retention_days=int(conversation_retention_days),
                        workspace_type='group'
                    )
                    group_deletion_summary['conversations_deleted'] = conv_results['count']
                    group_deletion_summary['conversation_details'] = conv_results['details']
                    results['conversations'] += conv_results['count']
                except Exception as e:
                    debug_print(f"Error processing conversations for group {group_id}: {e}")
            
            # Process documents
            if document_retention_days != 'none':
                try:
                    doc_results = delete_aged_documents(
                        group_id=group_id,
                        retention_days=int(document_retention_days),
                        workspace_type='group'
                    )
                    group_deletion_summary['documents_deleted'] = doc_results['count']
                    group_deletion_summary['document_details'] = doc_results['details']
                    results['documents'] += doc_results['count']
                except Exception as e:
                    debug_print(f"Error processing documents for group {group_id}: {e}")
            
            # Send notification if anything was deleted
            if group_deletion_summary['conversations_deleted'] > 0 or group_deletion_summary['documents_deleted'] > 0:
                send_retention_notification(group_id, group_deletion_summary, 'group')
                results['workspaces_affected'] += 1
                results['details'].append(group_deletion_summary)
        
        return results
        
    except Exception as e:
        debug_print(f"Error in process_group_retention: {e}")
        return results


def process_public_retention():
    """
    Process retention policies for all public workspaces.
    
    Returns:
        dict: Deletion statistics
    """
    results = {
        'conversations': 0,
        'documents': 0,
        'workspaces_affected': 0,
        'details': []
    }
    
    try:
        # Get all public workspaces
        all_workspaces = get_all_public_workspaces()
        
        for workspace in all_workspaces:
            workspace_id = workspace.get('id')
            if not workspace_id:
                continue
            
            # Get workspace's retention settings
            retention_settings = workspace.get('retention_policy', {})
            
            conversation_retention_days = retention_settings.get('conversation_retention_days', 'none')
            document_retention_days = retention_settings.get('document_retention_days', 'none')
            
            # Skip if both are set to "none"
            if conversation_retention_days == 'none' and document_retention_days == 'none':
                continue
            
            workspace_deletion_summary = {
                'public_workspace_id': workspace_id,
                'workspace_name': workspace.get('name', 'Unnamed Workspace'),
                'conversations_deleted': 0,
                'documents_deleted': 0,
                'conversation_details': [],
                'document_details': []
            }
            
            # Process conversations
            if conversation_retention_days != 'none':
                try:
                    conv_results = delete_aged_conversations(
                        public_workspace_id=workspace_id,
                        retention_days=int(conversation_retention_days),
                        workspace_type='public'
                    )
                    workspace_deletion_summary['conversations_deleted'] = conv_results['count']
                    workspace_deletion_summary['conversation_details'] = conv_results['details']
                    results['conversations'] += conv_results['count']
                except Exception as e:
                    debug_print(f"Error processing conversations for public workspace {workspace_id}: {e}")
            
            # Process documents
            if document_retention_days != 'none':
                try:
                    doc_results = delete_aged_documents(
                        public_workspace_id=workspace_id,
                        retention_days=int(document_retention_days),
                        workspace_type='public'
                    )
                    workspace_deletion_summary['documents_deleted'] = doc_results['count']
                    workspace_deletion_summary['document_details'] = doc_results['details']
                    results['documents'] += doc_results['count']
                except Exception as e:
                    debug_print(f"Error processing documents for public workspace {workspace_id}: {e}")
            
            # Send notification if anything was deleted
            if workspace_deletion_summary['conversations_deleted'] > 0 or workspace_deletion_summary['documents_deleted'] > 0:
                send_retention_notification(workspace_id, workspace_deletion_summary, 'public')
                results['workspaces_affected'] += 1
                results['details'].append(workspace_deletion_summary)
        
        return results
        
    except Exception as e:
        debug_print(f"Error in process_public_retention: {e}")
        return results


def delete_aged_conversations(retention_days, workspace_type='personal', user_id=None, group_id=None, public_workspace_id=None):
    """
    Delete conversations that exceed the retention period based on last_activity_at.
    
    Args:
        retention_days (int): Number of days to retain conversations
        workspace_type (str): 'personal', 'group', or 'public'
        user_id (str, optional): User ID for personal workspaces
        group_id (str, optional): Group ID for group workspaces
        public_workspace_id (str, optional): Public workspace ID for public workspaces
        
    Returns:
        dict: {'count': int, 'details': list}
    """
    settings = get_settings()
    archiving_enabled = settings.get('enable_conversation_archiving', False)
    
    # Determine which container to use
    if workspace_type == 'group':
        container = cosmos_group_conversations_container
        partition_field = 'group_id'
        partition_value = group_id
    elif workspace_type == 'public':
        container = cosmos_public_conversations_container
        partition_field = 'public_workspace_id'
        partition_value = public_workspace_id
    else:
        container = cosmos_conversations_container
        partition_field = 'user_id'
        partition_value = user_id
    
    # Calculate cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.isoformat()
    
    # Query for aged conversations
    query = f"""
        SELECT c.id, c.title, c.last_activity_at, c.{partition_field}
        FROM c
        WHERE c.{partition_field} = @partition_value
        AND (c.last_activity_at < @cutoff_date OR IS_NULL(c.last_activity_at))
    """
    
    parameters = [
        {"name": "@partition_value", "value": partition_value},
        {"name": "@cutoff_date", "value": cutoff_iso}
    ]
    
    aged_conversations = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    deleted_details = []
    
    for conv in aged_conversations:
        conversation_id = conv.get('id')
        conversation_title = conv.get('title', 'Untitled')
        
        try:
            # Read full conversation for archiving/logging
            conversation_item = container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Archive if enabled
            if archiving_enabled:
                archived_item = dict(conversation_item)
                archived_item["archived_at"] = datetime.now(timezone.utc).isoformat()
                archived_item["archived_by_retention_policy"] = True
                cosmos_archived_conversations_container.upsert_item(archived_item)
                
                log_conversation_archival(
                    user_id=conversation_item.get('user_id'),
                    conversation_id=conversation_id,
                    title=conversation_title,
                    workspace_type=workspace_type,
                    context=conversation_item.get('context', []),
                    tags=conversation_item.get('tags', []),
                    group_id=conversation_item.get('group_id'),
                    public_workspace_id=conversation_item.get('public_workspace_id')
                )
            
            # Delete messages
            
            if workspace_type == 'group':
                messages_container = cosmos_group_messages_container
            elif workspace_type == 'public':
                messages_container = cosmos_public_messages_container
            else:
                messages_container = cosmos_messages_container
            
            message_query = f"SELECT * FROM c WHERE c.conversation_id = @conversation_id"
            message_params = [{"name": "@conversation_id", "value": conversation_id}]
            
            messages = list(messages_container.query_items(
                query=message_query,
                parameters=message_params,
                partition_key=conversation_id
            ))
            
            for msg in messages:
                if archiving_enabled:
                    archived_msg = dict(msg)
                    archived_msg["archived_at"] = datetime.now(timezone.utc).isoformat()
                    archived_msg["archived_by_retention_policy"] = True
                    cosmos_archived_messages_container.upsert_item(archived_msg)
                
                messages_container.delete_item(msg['id'], partition_key=conversation_id)
            
            # Log deletion
            log_conversation_deletion(
                user_id=conversation_item.get('user_id'),
                conversation_id=conversation_id,
                title=conversation_title,
                workspace_type=workspace_type,
                context=conversation_item.get('context', []),
                tags=conversation_item.get('tags', []),
                is_archived=archiving_enabled,
                is_bulk_operation=True,
                group_id=conversation_item.get('group_id'),
                public_workspace_id=conversation_item.get('public_workspace_id'),
                deletion_reason='retention_policy'
            )
            
            # Delete conversation
            container.delete_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            deleted_details.append({
                'id': conversation_id,
                'title': conversation_title,
                'last_activity_at': conv.get('last_activity_at')
            })
            
            debug_print(f"Deleted conversation {conversation_id} ({conversation_title}) due to retention policy")
            
        except Exception as e:
            debug_print(f"Error deleting conversation {conversation_id}: {e}")
    
    return {
        'count': len(deleted_details),
        'details': deleted_details
    }


def delete_aged_documents(retention_days, workspace_type='personal', user_id=None, group_id=None, public_workspace_id=None):
    """
    Delete documents that exceed the retention period based on last_activity_at.
    
    Args:
        retention_days (int): Number of days to retain documents
        workspace_type (str): 'personal', 'group', or 'public'
        user_id (str, optional): User ID for personal workspaces
        group_id (str, optional): Group ID for group workspaces
        public_workspace_id (str, optional): Public workspace ID for public workspaces
        
    Returns:
        dict: {'count': int, 'details': list}
    """
    # Determine which container to use
    if workspace_type == 'group':
        container = cosmos_group_documents_container
        partition_field = 'group_id'
        partition_value = group_id
        deletion_user_id = None  # Will be extracted from document
    elif workspace_type == 'public':
        container = cosmos_public_documents_container
        partition_field = 'public_workspace_id'
        partition_value = public_workspace_id
        deletion_user_id = None  # Will be extracted from document
    else:
        container = cosmos_user_documents_container
        partition_field = 'user_id'
        partition_value = user_id
        deletion_user_id = user_id
    
    # Calculate cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.isoformat()
    
    # Query for aged documents
    query = f"""
        SELECT c.id, c.file_name, c.title, c.last_activity_at, c.{partition_field}, c.user_id
        FROM c
        WHERE c.{partition_field} = @partition_value
        AND (c.last_activity_at < @cutoff_date OR IS_NULL(c.last_activity_at))
    """
    
    parameters = [
        {"name": "@partition_value", "value": partition_value},
        {"name": "@cutoff_date", "value": cutoff_iso}
    ]
    
    aged_documents = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ))
    
    deleted_details = []
    
    for doc in aged_documents:
        document_id = doc.get('id')
        file_name = doc.get('file_name', 'Unknown')
        title = doc.get('title', file_name)
        doc_user_id = doc.get('user_id') or deletion_user_id
        
        try:
            # Delete document chunks from search index
            delete_document_chunks(document_id, group_id, public_workspace_id)
            
            # Delete document from Cosmos DB and blob storage
            delete_document(doc_user_id, document_id, group_id, public_workspace_id)
            
            deleted_details.append({
                'id': document_id,
                'file_name': file_name,
                'title': title,
                'last_activity_at': doc.get('last_activity_at')
            })
            
            debug_print(f"Deleted document {document_id} ({file_name}) due to retention policy")
            
        except Exception as e:
            debug_print(f"Error deleting document {document_id}: {e}")
    
    return {
        'count': len(deleted_details),
        'details': deleted_details
    }


def send_retention_notification(workspace_id, deletion_summary, workspace_type):
    """
    Send notification about retention policy deletions.
    
    Args:
        workspace_id (str): User ID, group ID, or public workspace ID
        deletion_summary (dict): Summary of deletions
        workspace_type (str): 'personal', 'group', or 'public'
    """
    conversations_deleted = deletion_summary.get('conversations_deleted', 0)
    documents_deleted = deletion_summary.get('documents_deleted', 0)
    
    # Build message
    message_parts = []
    if conversations_deleted > 0:
        message_parts.append(f"{conversations_deleted} conversation{'s' if conversations_deleted != 1 else ''}")
    if documents_deleted > 0:
        message_parts.append(f"{documents_deleted} document{'s' if documents_deleted != 1 else ''}")
    
    message = f"Retention policy automatically deleted {' and '.join(message_parts)}."
    
    # Build details list
    details = []
    
    if conversations_deleted > 0:
        conv_details = deletion_summary.get('conversation_details', [])
        if conv_details:
            details.append("**Conversations:**")
            for conv in conv_details[:10]:  # Limit to first 10
                details.append(f"• {conv.get('title', 'Untitled')}")
            if len(conv_details) > 10:
                details.append(f"• ...and {len(conv_details) - 10} more")
    
    if documents_deleted > 0:
        doc_details = deletion_summary.get('document_details', [])
        if doc_details:
            details.append("\n**Documents:**")
            for doc in doc_details[:10]:  # Limit to first 10
                details.append(f"• {doc.get('file_name', 'Unknown')}")
            if len(doc_details) > 10:
                details.append(f"• ...and {len(doc_details) - 10} more")
    
    full_message = message
    if details:
        full_message += "\n\n" + "\n".join(details)
    
    # Create notification based on workspace type
    if workspace_type == 'group':
        create_group_notification(
            group_id=workspace_id,
            notification_type='system_announcement',
            title='Retention Policy Cleanup',
            message=full_message,
            link_url='/chat',
            metadata={
                'conversations_deleted': conversations_deleted,
                'documents_deleted': documents_deleted,
                'deletion_date': datetime.now(timezone.utc).isoformat()
            }
        )
    elif workspace_type == 'public':
        create_public_workspace_notification(
            public_workspace_id=workspace_id,
            notification_type='system_announcement',
            title='Retention Policy Cleanup',
            message=full_message,
            link_url='/chat',
            metadata={
                'conversations_deleted': conversations_deleted,
                'documents_deleted': documents_deleted,
                'deletion_date': datetime.now(timezone.utc).isoformat()
            }
        )
    else:  # personal
        create_notification(
            user_id=workspace_id,
            notification_type='system_announcement',
            title='Retention Policy Cleanup',
            message=full_message,
            link_url='/chat',
            metadata={
                'conversations_deleted': conversations_deleted,
                'documents_deleted': documents_deleted,
                'deletion_date': datetime.now(timezone.utc).isoformat()
            }
        )
    
    debug_print(f"Sent retention notification to {workspace_type} workspace {workspace_id}")
