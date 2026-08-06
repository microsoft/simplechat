# functions_retention_policy.py

"""
Retention Policy Management

This module handles automated deletion of aged conversations and documents
based on configurable retention policies for personal, group, and public workspaces.

Version: 0.250.103
Implemented in: 0.234.067
Updated in: 0.236.012 - Fixed race condition handling for NotFound errors during deletion
Updated in: 0.237.004 - Fixed critical bug where conversations with null/undefined last_activity_at were deleted regardless of age
Updated in: 0.237.005 - Fixed field name: use last_updated (actual field) instead of last_activity_at (non-existent)
Updated in: 0.250.103 - Applied retention by conversation ownership across current, legacy, and collaboration stores
"""

from config import *
from functions_settings import get_settings, update_settings, cosmos_user_settings_container
from functions_group import get_user_groups, cosmos_groups_container
from functions_public_workspaces import get_user_public_workspaces, cosmos_public_workspaces_container
from functions_documents import delete_document, delete_document_chunks
from functions_simplechat_operations import delete_blob_backed_chat_message_files
from functions_activity_logging import log_conversation_deletion, log_conversation_archival
from functions_collaboration import delete_collaboration_conversation_for_retention
from functions_conversation_cache import invalidate_conversation_cache_for_item
from functions_notifications import create_notification, create_group_notification, create_public_workspace_notification
from functions_thoughts import archive_thoughts_for_conversation, delete_thoughts_for_conversation
from functions_debug import debug_print
from functions_appinsights import log_event
from datetime import datetime, timezone, timedelta


GROUP_SINGLE_USER_CHAT_TYPES = {'group', 'group-single-user', 'group_single_user'}
PERSONAL_MULTI_USER_CHAT_TYPE = 'personal_multi_user'
GROUP_MULTI_USER_CHAT_TYPE = 'group_multi_user'


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
        log_event("get_all_user_settings_error", {"error": str(e)})
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
        log_event("get_all_groups_error", {"error": str(e)})
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
        log_event("get_all_public_workspaces_error", {"error": str(e)})
        debug_print(f"Error fetching all public workspaces: {e}")
        return []


def resolve_retention_value(value, workspace_type, retention_type, settings=None):
    """
    Resolve a retention value, handling 'default' by looking up organization defaults.
    
    Args:
        value: The retention value ('none', 'default', or a number/string of days)
        workspace_type: 'personal', 'group', or 'public'
        retention_type: 'conversation' or 'document'
        settings: Optional pre-loaded settings dict (to avoid repeated lookups)
        
    Returns:
        str or int: 'none' if no deletion, or the number of days as int
    """
    if value is None or value == 'default' or value == '':
        # Look up the organization default
        if settings is None:
            settings = get_settings()
        
        setting_key = f'default_retention_{retention_type}_{workspace_type}'
        default_value = settings.get(setting_key, 'none')
        
        # If the org default is also 'none', return 'none'
        if default_value == 'none' or default_value is None:
            return 'none'
        
        # Return the org default as the effective value
        try:
            return int(default_value)
        except (ValueError, TypeError):
            return 'none'
    
    # User/workspace has their own explicit value
    if value == 'none':
        return 'none'
    
    try:
        return int(value)
    except (ValueError, TypeError):
        return 'none'


def _parse_retention_timestamp(value):
    """Return a timezone-aware activity timestamp or None when the value is invalid."""
    if not isinstance(value, str) or not value.strip():
        return None

    normalized_value = value.strip()
    if normalized_value.endswith('Z'):
        normalized_value = f"{normalized_value[:-1]}+00:00"

    try:
        parsed_value = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None

    if parsed_value.tzinfo is None:
        return parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)


def _get_primary_group_id(conversation_item):
    """Return the group that governs a single-user conversation."""
    for context_item in list((conversation_item or {}).get('context', []) or []):
        if not isinstance(context_item, dict):
            continue
        if context_item.get('type') != 'primary' or context_item.get('scope') != 'group':
            continue
        return str(context_item.get('id') or '').strip()
    return str((conversation_item or {}).get('group_id') or '').strip()


def _is_group_single_user_conversation(conversation_item):
    chat_type = str((conversation_item or {}).get('chat_type') or '').strip().lower()
    return chat_type in GROUP_SINGLE_USER_CHAT_TYPES or bool(_get_primary_group_id(conversation_item))


def _is_converted_conversation_source(conversation_item):
    return bool(str((conversation_item or {}).get('collaboration_conversation_id') or '').strip())


def _is_aged_conversation(conversation_item, timestamp_field, cutoff_date):
    activity_at = _parse_retention_timestamp((conversation_item or {}).get(timestamp_field))
    return activity_at is not None and activity_at < cutoff_date


def _build_group_scope_query(timestamp_field):
    return f"""
        SELECT * FROM c
        WHERE (
            c.group_id = @scope_id
            OR (
                IS_ARRAY(c.context)
                AND EXISTS(
                SELECT VALUE context_item
                FROM context_item IN c.context
                WHERE context_item.type = 'primary'
                AND context_item.scope = 'group'
                AND context_item.id = @scope_id
                )
            )
        )
        AND IS_DEFINED(c.{timestamp_field})
        AND IS_STRING(c.{timestamp_field})
        AND c.{timestamp_field} < @cutoff_date
    """


def _build_conversation_retention_sources(
    workspace_type,
    cutoff_iso,
    user_id=None,
    group_id=None,
    public_workspace_id=None,
):
    """Describe the backing stores governed by a workspace retention policy."""
    if workspace_type == 'personal':
        return [
            {
                'name': 'personal_single_user',
                'container': cosmos_conversations_container,
                'messages_container': cosmos_messages_container,
                'timestamp_field': 'last_updated',
                'query': """
                    SELECT * FROM c
                    WHERE c.user_id = @scope_id
                    AND IS_DEFINED(c.last_updated)
                    AND IS_STRING(c.last_updated)
                    AND c.last_updated < @cutoff_date
                """,
                'parameters': [
                    {'name': '@scope_id', 'value': user_id},
                    {'name': '@cutoff_date', 'value': cutoff_iso},
                ],
                'matches_scope': lambda item: (
                    not _is_group_single_user_conversation(item)
                    and not _is_converted_conversation_source(item)
                ),
            },
            {
                'name': PERSONAL_MULTI_USER_CHAT_TYPE,
                'container': cosmos_collaboration_conversations_container,
                'timestamp_field': 'updated_at',
                'query': """
                    SELECT * FROM c
                    WHERE c.chat_type = @chat_type
                    AND c.created_by_user_id = @scope_id
                    AND IS_DEFINED(c.updated_at)
                    AND IS_STRING(c.updated_at)
                    AND c.updated_at < @cutoff_date
                """,
                'parameters': [
                    {'name': '@chat_type', 'value': PERSONAL_MULTI_USER_CHAT_TYPE},
                    {'name': '@scope_id', 'value': user_id},
                    {'name': '@cutoff_date', 'value': cutoff_iso},
                ],
                'matches_scope': lambda item: (
                    item.get('chat_type') == PERSONAL_MULTI_USER_CHAT_TYPE
                    and item.get('created_by_user_id') == user_id
                ),
                'collaboration': True,
            },
        ]

    if workspace_type == 'group':
        group_parameters = [
            {'name': '@scope_id', 'value': group_id},
            {'name': '@cutoff_date', 'value': cutoff_iso},
        ]
        return [
            {
                'name': 'legacy_group',
                'container': cosmos_group_conversations_container,
                'messages_container': cosmos_group_messages_container,
                'timestamp_field': 'last_updated',
                'query': _build_group_scope_query('last_updated'),
                'parameters': group_parameters,
                'matches_scope': lambda item: (
                    _get_primary_group_id(item) == group_id
                    and not _is_converted_conversation_source(item)
                ),
            },
            {
                'name': 'group_single_user',
                'container': cosmos_conversations_container,
                'messages_container': cosmos_messages_container,
                'timestamp_field': 'last_updated',
                'query': _build_group_scope_query('last_updated'),
                'parameters': group_parameters,
                'matches_scope': lambda item: (
                    _is_group_single_user_conversation(item)
                    and _get_primary_group_id(item) == group_id
                    and not _is_converted_conversation_source(item)
                ),
            },
            {
                'name': GROUP_MULTI_USER_CHAT_TYPE,
                'container': cosmos_collaboration_conversations_container,
                'timestamp_field': 'updated_at',
                'query': """
                    SELECT * FROM c
                    WHERE c.chat_type = @chat_type
                    AND c.scope.group_id = @scope_id
                    AND IS_DEFINED(c.updated_at)
                    AND IS_STRING(c.updated_at)
                    AND c.updated_at < @cutoff_date
                """,
                'parameters': [
                    {'name': '@chat_type', 'value': GROUP_MULTI_USER_CHAT_TYPE},
                    {'name': '@scope_id', 'value': group_id},
                    {'name': '@cutoff_date', 'value': cutoff_iso},
                ],
                'matches_scope': lambda item: (
                    item.get('chat_type') == GROUP_MULTI_USER_CHAT_TYPE
                    and str((item.get('scope') or {}).get('group_id') or '').strip() == group_id
                ),
                'collaboration': True,
            },
        ]

    return [
        {
            'name': 'public',
            'container': cosmos_public_conversations_container,
            'messages_container': cosmos_public_messages_container,
            'timestamp_field': 'last_updated',
            'query': """
                SELECT * FROM c
                WHERE c.public_workspace_id = @scope_id
                AND IS_DEFINED(c.last_updated)
                AND IS_STRING(c.last_updated)
                AND c.last_updated < @cutoff_date
            """,
            'parameters': [
                {'name': '@scope_id', 'value': public_workspace_id},
                {'name': '@cutoff_date', 'value': cutoff_iso},
            ],
            'matches_scope': lambda item: item.get('public_workspace_id') == public_workspace_id,
        },
    ]


def _delete_standard_conversation_for_retention(
    conversation_item,
    source,
    workspace_type,
    archiving_enabled,
    cutoff_date,
):
    """Archive and delete a non-collaboration conversation and its dependent records."""
    conversation_id = conversation_item.get('id')
    conversation_title = conversation_item.get('title', 'Untitled')
    container = source['container']
    messages_container = source['messages_container']

    selected_conversation_item = conversation_item
    try:
        live_conversation_item = container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError:
        return {
            'id': conversation_id,
            'title': conversation_title,
            source['timestamp_field']: selected_conversation_item.get(
                source['timestamp_field']
            ),
            'already_deleted': True,
        }

    if (
        not source['matches_scope'](live_conversation_item)
        or not _is_aged_conversation(
            live_conversation_item,
            source['timestamp_field'],
            cutoff_date,
        )
    ):
        return None

    if (
        live_conversation_item.get(source['timestamp_field'])
        != selected_conversation_item.get(source['timestamp_field'])
    ):
        return None

    conversation_item = live_conversation_item

    if archiving_enabled:
        archived_item = dict(conversation_item)
        archived_item['archived_at'] = datetime.now(timezone.utc).isoformat()
        archived_item['archived_by_retention_policy'] = True
        archived_item['retention_source'] = source['name']
        cosmos_archived_conversations_container.upsert_item(archived_item)

        log_conversation_archival(
            user_id=conversation_item.get('user_id'),
            conversation_id=conversation_id,
            title=conversation_title,
            workspace_type=workspace_type,
            context=conversation_item.get('context', []),
            tags=conversation_item.get('tags', []),
            group_id=_get_primary_group_id(conversation_item) or None,
            public_workspace_id=conversation_item.get('public_workspace_id'),
            additional_context={'deletion_reason': 'retention_policy'},
        )

    messages = list(messages_container.query_items(
        query='SELECT * FROM c WHERE c.conversation_id = @conversation_id',
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        partition_key=conversation_id,
    ))

    if not archiving_enabled:
        delete_blob_backed_chat_message_files(messages, raise_on_error=True)

    for message_item in messages:
        if archiving_enabled:
            archived_message = dict(message_item)
            archived_message['archived_at'] = datetime.now(timezone.utc).isoformat()
            archived_message['archived_by_retention_policy'] = True
            archived_message['retention_source'] = source['name']
            cosmos_archived_messages_container.upsert_item(archived_message)

        try:
            messages_container.delete_item(
                item=message_item.get('id'),
                partition_key=conversation_id,
            )
        except CosmosResourceNotFoundError:
            debug_print(
                f"[RETENTION_POLICY] Message {message_item.get('id')} was already deleted"
            )

    thought_user_id = conversation_item.get('user_id')
    if archiving_enabled:
        archive_thoughts_for_conversation(
            conversation_id,
            thought_user_id,
            raise_on_error=True,
        )
    else:
        delete_thoughts_for_conversation(
            conversation_id,
            thought_user_id,
            raise_on_error=True,
        )

    log_conversation_deletion(
        user_id=conversation_item.get('user_id'),
        conversation_id=conversation_id,
        title=conversation_title,
        workspace_type=workspace_type,
        context=conversation_item.get('context', []),
        tags=conversation_item.get('tags', []),
        is_archived=archiving_enabled,
        is_bulk_operation=True,
        group_id=_get_primary_group_id(conversation_item) or None,
        public_workspace_id=conversation_item.get('public_workspace_id'),
        additional_context={
            'deletion_reason': 'retention_policy',
            'retention_source': source['name'],
        },
    )

    try:
        container.delete_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError:
        debug_print(
            f"[RETENTION_POLICY] Conversation {conversation_id} was already deleted"
        )

    invalidate_conversation_cache_for_item(
        conversation_item,
        reason='retention_policy_deleted',
    )
    return {
        'id': conversation_id,
        'title': conversation_title,
        source['timestamp_field']: conversation_item.get(source['timestamp_field']),
    }


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
        log_event("execute_retention_policy_error", {"error": str(e), "workspace_scopes": workspace_scopes, "manual_execution": manual_execution})
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
        
        # Pre-load settings once for efficiency
        settings = get_settings()
        
        for user in all_users:
            user_id = user.get('id')
            if not user_id:
                continue
            
            # Get user's retention settings
            user_settings = user.get('settings', {})
            retention_settings = user_settings.get('retention_policy', {})
            
            # Get raw values (may be 'default', 'none', or a number)
            raw_conversation_days = retention_settings.get('conversation_retention_days')
            raw_document_days = retention_settings.get('document_retention_days')
            
            # Resolve to effective values (handles 'default' -> org default lookup)
            conversation_retention_days = resolve_retention_value(raw_conversation_days, 'personal', 'conversation', settings)
            document_retention_days = resolve_retention_value(raw_document_days, 'personal', 'document', settings)
            
            # Skip if both resolve to "none"
            if conversation_retention_days == 'none' and document_retention_days == 'none':
                continue
            
            debug_print(f"Processing retention for user {user_id}: conversations={conversation_retention_days} days, documents={document_retention_days} days")
            
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
                    log_event("process_personal_retention_conversations_error", {"error": str(e), "user_id": user_id})
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
                    log_event("process_personal_retention_documents_error", {"error": str(e), "user_id": user_id})
                    debug_print(f"Error processing documents for user {user_id}: {e}")
            
            # Send notification if anything was deleted
            if user_deletion_summary['conversations_deleted'] > 0 or user_deletion_summary['documents_deleted'] > 0:
                send_retention_notification(user_id, user_deletion_summary, 'personal')
                results['users_affected'] += 1
                results['details'].append(user_deletion_summary)
        
        return results
        
    except Exception as e:
        log_event("process_personal_retention_error", {"error": str(e)})
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
        
        # Pre-load settings once for efficiency
        settings = get_settings()
        
        for group in all_groups:
            group_id = group.get('id')
            if not group_id:
                continue
            
            # Get group's retention settings
            retention_settings = group.get('retention_policy', {})
            
            # Get raw values (may be 'default', 'none', or a number)
            raw_conversation_days = retention_settings.get('conversation_retention_days')
            raw_document_days = retention_settings.get('document_retention_days')
            
            # Resolve to effective values (handles 'default' -> org default lookup)
            conversation_retention_days = resolve_retention_value(raw_conversation_days, 'group', 'conversation', settings)
            document_retention_days = resolve_retention_value(raw_document_days, 'group', 'document', settings)
            
            # Skip if both resolve to "none"
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
                    log_event("process_group_retention_conversations_error", {"error": str(e), "group_id": group_id})
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
                    log_event("process_group_retention_documents_error", {"error": str(e), "group_id": group_id})
                    debug_print(f"Error processing documents for group {group_id}: {e}")
            
            # Send notification if anything was deleted
            if group_deletion_summary['conversations_deleted'] > 0 or group_deletion_summary['documents_deleted'] > 0:
                send_retention_notification(group_id, group_deletion_summary, 'group')
                results['workspaces_affected'] += 1
                results['details'].append(group_deletion_summary)
        
        return results
        
    except Exception as e:
        log_event("process_group_retention_error", {"error": str(e)})
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
        
        # Pre-load settings once for efficiency
        settings = get_settings()
        
        for workspace in all_workspaces:
            workspace_id = workspace.get('id')
            if not workspace_id:
                continue
            
            # Get workspace's retention settings
            retention_settings = workspace.get('retention_policy', {})
            
            # Get raw values (may be 'default', 'none', or a number)
            raw_conversation_days = retention_settings.get('conversation_retention_days')
            raw_document_days = retention_settings.get('document_retention_days')
            
            # Resolve to effective values (handles 'default' -> org default lookup)
            conversation_retention_days = resolve_retention_value(raw_conversation_days, 'public', 'conversation', settings)
            document_retention_days = resolve_retention_value(raw_document_days, 'public', 'document', settings)
            
            # Skip if both resolve to "none"
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
            
            # Note: Public workspaces do not have a separate conversations container.
            # Conversations are only stored in personal (cosmos_conversations_container) or 
            # group (cosmos_group_conversations_container) workspaces.
            # Therefore, we skip conversation processing for public workspaces.
            # Only documents are processed for public workspace retention.
            
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
                    log_event("process_public_retention_documents_error", {"error": str(e), "public_workspace_id": workspace_id})
                    debug_print(f"Error processing documents for public workspace {workspace_id}: {e}")
            
            # Send notification if anything was deleted
            if workspace_deletion_summary['conversations_deleted'] > 0 or workspace_deletion_summary['documents_deleted'] > 0:
                send_retention_notification(workspace_id, workspace_deletion_summary, 'public')
                results['workspaces_affected'] += 1
                results['details'].append(workspace_deletion_summary)
        
        return results
        
    except Exception as e:
        log_event("process_public_retention_error", {"error": str(e)})
        debug_print(f"Error in process_public_retention: {e}")
        return results


def delete_aged_conversations(retention_days, workspace_type='personal', user_id=None, group_id=None, public_workspace_id=None):
    """
    Delete conversations governed by a workspace policy across all backing stores.
    
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
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.isoformat()
    deleted_details = []
    sources = _build_conversation_retention_sources(
        workspace_type,
        cutoff_iso,
        user_id=user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )

    for source in sources:
        try:
            candidates = list(source['container'].query_items(
                query=source['query'],
                parameters=source['parameters'],
                enable_cross_partition_query=True,
            ))
        except Exception as query_error:
            log_event(
                "[RETENTION_POLICY] Conversation query failed",
                {
                    'error': str(query_error),
                    'workspace_type': workspace_type,
                    'retention_source': source['name'],
                },
            )
            debug_print(
                f"[RETENTION_POLICY] Failed querying {source['name']}: {query_error}"
            )
            continue

        aged_conversations = [
            candidate
            for candidate in candidates
            if source['matches_scope'](candidate)
            and _is_aged_conversation(
                candidate,
                source['timestamp_field'],
                cutoff_date,
            )
        ]
        debug_print(
            f"[RETENTION_POLICY] Found {len(aged_conversations)} aged "
            f"{source['name']} conversations for {workspace_type}"
        )

        for conversation_item in aged_conversations:
            conversation_id = conversation_item.get('id', 'unknown')
            try:
                if source.get('collaboration'):
                    deletion_detail = delete_collaboration_conversation_for_retention(
                        conversation_item,
                        workspace_type=workspace_type,
                        archiving_enabled=archiving_enabled,
                    )
                else:
                    deletion_detail = _delete_standard_conversation_for_retention(
                        conversation_item,
                        source,
                        workspace_type,
                        archiving_enabled,
                        cutoff_date,
                    )

                if deletion_detail is None:
                    debug_print(
                        f"[RETENTION_POLICY] Skipped {conversation_id} because it "
                        "changed after selection"
                    )
                    continue

                deleted_details.append(deletion_detail)
                debug_print(
                    f"[RETENTION_POLICY] Deleted {source['name']} conversation "
                    f"{conversation_id}"
                )
            except CosmosResourceNotFoundError:
                debug_print(
                    f"[RETENTION_POLICY] Conversation {conversation_id} was already deleted"
                )
                deleted_details.append({
                    'id': conversation_id,
                    'title': conversation_item.get('title', 'Untitled'),
                    source['timestamp_field']: conversation_item.get(source['timestamp_field']),
                    'already_deleted': True,
                })
            except Exception as deletion_error:
                log_event(
                    "[RETENTION_POLICY] Conversation deletion failed",
                    {
                        'error': str(deletion_error),
                        'conversation_id': conversation_id,
                        'workspace_type': workspace_type,
                        'retention_source': source['name'],
                    },
                )
                debug_print(
                    f"[RETENTION_POLICY] Failed deleting {conversation_id}: "
                    f"{deletion_error}"
                )

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
    # Documents use format like '2026-01-08T21:49:15Z' so we match that format
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # Query for aged documents
    # Documents use 'last_updated' field (not 'last_activity_at' like conversations)
    # Use simple date comparison - documents always have last_updated field
    query = f"""
        SELECT c.id, c.file_name, c.title, c.last_updated, c.user_id
        FROM c
        WHERE c.{partition_field} = @partition_value
        AND c.last_updated < @cutoff_date
    """
    
    parameters = [
        {"name": "@partition_value", "value": partition_value},
        {"name": "@cutoff_date", "value": cutoff_iso}
    ]
    
    debug_print(f"Querying aged documents: workspace_type={workspace_type}, partition_field={partition_field}, partition_value={partition_value}, cutoff_date={cutoff_iso}, retention_days={retention_days}")
    
    try:
        aged_documents = list(container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        debug_print(f"Found {len(aged_documents)} aged documents for {workspace_type} workspace")
    except Exception as query_error:
        log_event("delete_aged_documents_query_error", {"error": str(query_error), "workspace_type": workspace_type, "partition_value": partition_value})
        debug_print(f"Error querying aged documents for {workspace_type} (partition_value={partition_value}): {query_error}")
        return {'count': 0, 'details': []}
    
    deleted_details = []
    
    for doc in aged_documents:
        try:
            document_id = doc.get('id')
            file_name = doc.get('file_name', 'Unknown')
            title = doc.get('title', file_name)
            doc_user_id = doc.get('user_id') or deletion_user_id
            
            # Delete document chunks from search index
            try:
                delete_document_chunks(document_id, group_id, public_workspace_id)
            except CosmosResourceNotFoundError:
                # Document chunks already deleted - this is fine
                debug_print(f"Document chunks for {document_id} already deleted (not found)")
            except Exception as chunk_error:
                # Log chunk deletion errors but continue with document deletion
                debug_print(f"Error deleting chunks for document {document_id}: {chunk_error}")
            
            # Delete document from Cosmos DB and blob storage
            try:
                delete_document(doc_user_id, document_id, group_id, public_workspace_id)
            except CosmosResourceNotFoundError:
                # Document was already deleted (race condition) - this is fine
                debug_print(f"Document {document_id} already deleted (not found)")
            
            deleted_details.append({
                'id': document_id,
                'file_name': file_name,
                'title': title,
                'last_updated': doc.get('last_updated')
            })
            
            debug_print(f"Deleted document {document_id} ({file_name}) due to retention policy")
            
        except CosmosResourceNotFoundError:
            # Document was already deleted - count as success
            doc_id = doc.get('id', 'unknown') if doc else 'unknown'
            debug_print(f"Document {doc_id} already deleted (not found)")
            deleted_details.append({
                'id': doc_id,
                'file_name': doc.get('file_name', 'Unknown'),
                'title': doc.get('title', doc.get('file_name', 'Unknown')),
                'last_updated': doc.get('last_updated'),
                'already_deleted': True
            })
        except Exception as e:
            doc_id = doc.get('id', 'unknown') if doc else 'unknown'
            log_event("delete_aged_documents_deletion_error", {"error": str(e), "document_id": doc_id, "workspace_type": workspace_type})
            debug_print(f"Error deleting document {doc_id}: {e}")
    
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
            link_url='/chats',
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
            link_url='/chats',
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
            link_url='/chats',
            metadata={
                'conversations_deleted': conversations_deleted,
                'documents_deleted': documents_deleted,
                'deletion_date': datetime.now(timezone.utc).isoformat()
            }
        )
    
    debug_print(f"Sent retention notification to {workspace_type} workspace {workspace_id}")
