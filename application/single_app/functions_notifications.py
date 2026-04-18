# functions_notifications.py

"""
Notifications Management

This module handles all operations related to notifications stored in the
notifications container. Supports personal, group, and public workspace scoped
notifications with per-user read/dismiss tracking.

Version: 0.234.032
Implemented in: 0.234.032
"""

# Imports (grouped after docstring)
import uuid
from datetime import datetime, timezone
from azure.cosmos import exceptions
from flask import current_app
import logging
from config import cosmos_notifications_container
from functions_group import find_group_by_id
from functions_debug import debug_print
from functions_public_workspaces import find_public_workspace_by_id, get_user_public_workspaces

# Constants
TTL_60_DAYS = 60 * 24 * 60 * 60  # 60 days in seconds (5184000)
ASSIGNMENT_NOTIFICATIONS_PARTITION_KEY = 'assignment-notifications'
WORKFLOW_ALERT_NOTIFICATION_TYPE = 'workflow_priority_alert'
WORKFLOW_ALERT_PRIORITY_CONFIG = {
    'low': {
        'icon': 'bi-bell',
        'color': 'info',
    },
    'medium': {
        'icon': 'bi-exclamation-circle',
        'color': 'warning',
    },
    'high': {
        'icon': 'bi-exclamation-triangle',
        'color': 'danger',
    },
}

# Notification type registry for extensibility
NOTIFICATION_TYPES = {
    'document_processing_complete': {
        'icon': 'bi-file-earmark-check',
        'color': 'success'
    },
    'group_created': {
        'icon': 'bi-people-fill',
        'color': 'success'
    },
    'group_member_added': {
        'icon': 'bi-person-plus',
        'color': 'info'
    },
    'conversation_created': {
        'icon': 'bi-chat-square-text',
        'color': 'info'
    },
    'collaboration_message_received': {
        'icon': 'bi-people-fill',
        'color': 'info'
    },
    'chat_response_complete': {
        'icon': 'bi-chat-dots',
        'color': 'success'
    },
    'document_processing_failed': {
        'icon': 'bi-file-earmark-x',
        'color': 'danger'
    },
    'ownership_transfer_request': {
        'icon': 'bi-arrow-left-right',
        'color': 'warning'
    },
    'group_deletion_request': {
        'icon': 'bi-trash',
        'color': 'danger'
    },
    'document_deletion_request': {
        'icon': 'bi-trash',
        'color': 'warning'
    },
    'system_announcement': {
        'icon': 'bi-megaphone',
        'color': 'info'
    },
    'approval_request_pending': {
        'icon': 'bi-hourglass-split',
        'color': 'warning'
    },
    'approval_request_pending_submitter': {
        'icon': 'bi-hourglass',
        'color': 'info'
    },
    'approval_request_approved': {
        'icon': 'bi-check-circle',
        'color': 'success'
    },
    'approval_request_denied': {
        'icon': 'bi-x-circle',
        'color': 'danger'
    },
    'agent_template_pending_admin': {
        'icon': 'bi-layers',
        'color': 'warning'
    },
    'agent_template_pending_submitter': {
        'icon': 'bi-layers-half',
        'color': 'info'
    },
    'agent_template_approved': {
        'icon': 'bi-check2-square',
        'color': 'success'
    },
    'agent_template_rejected': {
        'icon': 'bi-x-octagon',
        'color': 'danger'
    },
    'agent_template_deleted': {
        'icon': 'bi-trash',
        'color': 'secondary'
    },
    WORKFLOW_ALERT_NOTIFICATION_TYPE: {
        'icon': 'bi-bell',
        'color': 'secondary'
    }
}


def _get_notification_partition_key(notification):
    """Resolve the Cosmos partition key for a notification document."""
    if notification.get('scope') == 'assignment':
        return ASSIGNMENT_NOTIFICATIONS_PARTITION_KEY

    return (
        notification.get('user_id')
        or notification.get('group_id')
        or notification.get('public_workspace_id')
    )


def _get_notification_display_message(notification):
    """Normalize display text and backfill reviewer reasons from metadata when needed."""
    message = str(notification.get('message') or '').strip()
    metadata = notification.get('metadata') or {}
    notification_type = notification.get('notification_type')

    reason = None
    if notification_type == 'approval_request_denied':
        reason = str(metadata.get('comment') or '').strip()
    elif notification_type == 'agent_template_rejected':
        reason = str(metadata.get('rejection_reason') or '').strip()

    if reason and reason not in message:
        if message:
            return f"{message} Reason provided: {reason}"
        return f"Reason provided: {reason}"

    return message


def _get_workflow_alert_priority(notification):
    metadata = notification.get('metadata') or {}
    priority = str(metadata.get('priority') or 'medium').strip().lower()
    if priority not in WORKFLOW_ALERT_PRIORITY_CONFIG:
        return 'medium'
    return priority


def _get_notification_type_config(notification):
    notification_type = notification.get('notification_type')
    if notification_type == WORKFLOW_ALERT_NOTIFICATION_TYPE:
        return WORKFLOW_ALERT_PRIORITY_CONFIG.get(
            _get_workflow_alert_priority(notification),
            NOTIFICATION_TYPES[WORKFLOW_ALERT_NOTIFICATION_TYPE],
        )

    return NOTIFICATION_TYPES.get(
        notification_type,
        NOTIFICATION_TYPES['system_announcement'],
    )


def get_notifications_by_metadata(metadata_filters=None, notification_types=None):
    """Fetch notifications matching metadata values and optional types."""
    try:
        query_parts = ["SELECT * FROM c WHERE 1=1"]
        parameters = []

        if notification_types:
            type_clauses = []
            for index, notification_type in enumerate(notification_types):
                parameter_name = f"@notification_type_{index}"
                type_clauses.append(f"c.notification_type = {parameter_name}")
                parameters.append({"name": parameter_name, "value": notification_type})
            query_parts.append(f"AND ({' OR '.join(type_clauses)})")

        for key, value in (metadata_filters or {}).items():
            if value is None:
                continue
            parameter_name = f"@metadata_{key}"
            query_parts.append(f"AND c.metadata.{key} = {parameter_name}")
            parameters.append({"name": parameter_name, "value": value})

        return list(cosmos_notifications_container.query_items(
            query=" ".join(query_parts),
            parameters=parameters or None,
            enable_cross_partition_query=True
        ))
    except Exception as e:
        debug_print(f"Error fetching notifications by metadata: {e}")
        return []


def delete_notifications_by_metadata(metadata_filters=None, notification_types=None):
    """Delete notifications matching metadata values and optional types."""
    deleted_count = 0
    notifications = get_notifications_by_metadata(
        metadata_filters=metadata_filters,
        notification_types=notification_types
    )

    for notification in notifications:
        partition_key = _get_notification_partition_key(notification)
        if not partition_key:
            continue

        try:
            cosmos_notifications_container.delete_item(
                item=notification['id'],
                partition_key=partition_key
            )
            deleted_count += 1
        except Exception as e:
            debug_print(
                f"Error deleting notification {notification.get('id')} by metadata: {e}"
            )

    return deleted_count


def create_notification(
    user_id=None,
    group_id=None,
    public_workspace_id=None,
    notification_type='system_announcement',
    title='',
    message='',
    link_url='',
    link_context=None,
    metadata=None,
    assignment=None
):
    """
    Create a notification for personal, group, or public workspace scope.
    
    Args:
        user_id (str, optional): User ID for personal notifications (deprecated if using assignment)
        group_id (str, optional): Group ID for group-scoped notifications
        public_workspace_id (str, optional): Public workspace ID for workspace notifications
        notification_type (str): Type of notification (must be in NOTIFICATION_TYPES)
        title (str): Notification title
        message (str): Notification message
        link_url (str): URL to navigate to when clicked
        link_context (dict, optional): Additional context for navigation
        metadata (dict, optional): Flexible metadata for type-specific data
        assignment (dict, optional): Role and ownership-based assignment:
            {
                'roles': ['Admin', 'ControlCenterAdmin'],  # Users with these roles see notification
                'personal_workspace_owner_id': 'user123',   # Personal workspace owner
                'group_owner_id': 'user456',                # Group owner
                'public_workspace_owner_id': 'user789'      # Public workspace owner
            }
            If any role matches or any owner ID matches user's ID, notification is visible.
        
    Returns:
        dict: Created notification document or None on error
    """
    try:
        # Determine scope and partition key
        scope = 'personal'
        partition_key = user_id
        
        # If assignment is provided, always use assignment partition for role-based notifications
        if assignment:
            # Assignment-based notifications always use the special assignment partition
            # This allows role-based filtering across all users
            scope = 'assignment'
            partition_key = ASSIGNMENT_NOTIFICATIONS_PARTITION_KEY
        else:
            # Legacy behavior - partition by specific workspace
            if group_id:
                scope = 'group'
                partition_key = group_id
            elif public_workspace_id:
                scope = 'public_workspace'
                partition_key = public_workspace_id
        
        if not partition_key:
            debug_print("create_notification: No partition key provided")
            return None
        
        # Validate notification type
        if notification_type not in NOTIFICATION_TYPES:
            debug_print(f"Unknown notification type: {notification_type}")
        
        notification_doc = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'group_id': group_id,
            'public_workspace_id': public_workspace_id,
            'scope': scope,
            'notification_type': notification_type,
            'title': title,
            'message': message,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'ttl': TTL_60_DAYS,
            'read_by': [],
            'dismissed_by': [],
            'link_url': link_url or '',
            'link_context': link_context or {},
            'metadata': metadata or {},
            'assignment': assignment or None
        }
        
        # Create in Cosmos with partition key based on scope
        cosmos_notifications_container.create_item(notification_doc)
        
        debug_print(
            f"Notification created: {notification_doc['id']} "
            f"[{scope}] [{notification_type}] for partition: {partition_key}"
        )
        
        return notification_doc
        
    except Exception as e:
        debug_print(f"Error creating notification: {e}")
        return None


def broadcast_system_notification(title, message, metadata=None):
    """Create a system announcement visible to all users regardless of role."""
    return create_notification(
        notification_type='system_announcement',
        title=title,
        message=message,
        metadata=metadata or {},
        assignment={'all_users': True}
    )


def create_group_notification(group_id, notification_type, title, message, link_url='', link_context=None, metadata=None):
    """
    Create a notification for all members of a group.
    
    Args:
        group_id (str): Group ID
        notification_type (str): Type of notification
        title (str): Notification title
        message (str): Notification message
        link_url (str): URL to navigate to when clicked
        link_context (dict, optional): Additional context for navigation
        metadata (dict, optional): Additional metadata
        
    Returns:
        dict: Created notification or None on error
    """
    return create_notification(
        group_id=group_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link_url=link_url,
        link_context=link_context or {'workspace_type': 'group', 'group_id': group_id},
        metadata=metadata
    )


def create_public_workspace_notification(
    public_workspace_id,
    notification_type,
    title,
    message,
    link_url='',
    link_context=None,
    metadata=None
):
    """
    Create a notification for all members of a public workspace.
    
    Args:
        public_workspace_id (str): Public workspace ID
        notification_type (str): Type of notification
        title (str): Notification title
        message (str): Notification message
        link_url (str): URL to navigate to when clicked
        link_context (dict, optional): Additional context for navigation
        metadata (dict, optional): Additional metadata
        
    Returns:
        dict: Created notification or None on error
    """
    return create_notification(
        public_workspace_id=public_workspace_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link_url=link_url,
        link_context=link_context or {
            'workspace_type': 'public',
            'public_workspace_id': public_workspace_id
        },
        metadata=metadata
    )


def create_chat_response_notification(
    user_id,
    conversation_id,
    message_id,
    conversation_title='',
    response_preview='',
):
    """Create a personal notification when a chat response completes."""
    normalized_title = str(conversation_title or '').strip() or 'Conversation'
    normalized_preview = str(response_preview or '').strip()
    if len(normalized_preview) > 160:
        normalized_preview = f"{normalized_preview[:157]}..."

    notification_message = (
        normalized_preview
        or f'The AI model responded in {normalized_title}.'
    )

    return create_notification(
        user_id=user_id,
        notification_type='chat_response_complete',
        title=f'AI responded in {normalized_title}',
        message=notification_message,
        link_url=f'/chats?conversationId={conversation_id}',
        link_context={
            'workspace_type': 'personal',
            'conversation_id': conversation_id,
        },
        metadata={
            'conversation_id': conversation_id,
            'message_id': message_id,
        }
    )


def create_collaboration_message_notification(
    user_id,
    conversation_id,
    message_id,
    conversation_title='',
    sender_display_name='',
    message_preview='',
    chat_type='',
    group_id=None,
    mentioned_user=False,
):
    """Create a personal notification when another participant posts in a shared conversation."""
    normalized_title = str(conversation_title or '').strip() or 'Shared Conversation'
    normalized_sender = str(sender_display_name or '').strip() or 'A participant'
    normalized_preview = str(message_preview or '').strip()
    if len(normalized_preview) > 160:
        normalized_preview = f"{normalized_preview[:157]}..."

    notification_title = f"New shared message in {normalized_title}"
    if mentioned_user:
        notification_title = f"{normalized_sender} tagged you in {normalized_title}"

    notification_message = normalized_preview or f"{normalized_sender} posted in {normalized_title}."

    return create_notification(
        user_id=user_id,
        notification_type='collaboration_message_received',
        title=notification_title,
        message=notification_message,
        link_url=f'/chats?conversationId={conversation_id}',
        link_context={
            'workspace_type': 'group' if str(chat_type or '').strip().lower().startswith('group') else 'personal',
            'conversation_id': conversation_id,
            'group_id': group_id,
            'conversation_kind': 'collaborative',
        },
        metadata={
            'conversation_id': conversation_id,
            'message_id': message_id,
            'sender_display_name': normalized_sender,
            'mentioned_user': bool(mentioned_user),
            'conversation_kind': 'collaborative',
            'chat_type': chat_type,
            'group_id': group_id,
        }
    )


def create_workflow_priority_notification(
    user_id,
    workflow_id,
    workflow_name,
    priority,
    title,
    message,
    link_url='',
    link_context=None,
    metadata=None,
):
    """Create a personal workflow alert notification with a priority-aware display."""
    normalized_priority = str(priority or 'medium').strip().lower()
    if normalized_priority not in WORKFLOW_ALERT_PRIORITY_CONFIG:
        normalized_priority = 'medium'

    alert_metadata = dict(metadata or {})
    alert_metadata.setdefault('priority', normalized_priority)
    alert_metadata.setdefault('workflow_id', workflow_id)
    alert_metadata.setdefault('workflow_name', workflow_name)

    return create_notification(
        user_id=user_id,
        notification_type=WORKFLOW_ALERT_NOTIFICATION_TYPE,
        title=title,
        message=message,
        link_url=link_url,
        link_context=link_context or {},
        metadata=alert_metadata,
    )


def get_user_notifications(user_id, page=1, per_page=20, include_read=True, include_dismissed=False, user_roles=None):
    """
    Fetch notifications visible to a user from personal, group, and public workspace scopes.
    Supports assignment-based notifications that target users by roles and/or ownership.
    
    Args:
        user_id (str): User's unique identifier
        page (int): Page number (1-indexed)
        per_page (int): Items per page
        include_read (bool): Include notifications already read by user
        include_dismissed (bool): Include notifications dismissed by user
        user_roles (list, optional): User's roles for assignment-based notifications
        
    Returns:
        dict: {
            'notifications': [...],
            'total': int,
            'page': int,
            'per_page': int,
            'has_more': bool
        }
    """
    try:
        all_notifications = []
        
        # 1. Fetch personal notifications
        personal_query = "SELECT * FROM c WHERE c.user_id = @user_id"
        personal_params = [{"name": "@user_id", "value": user_id}]
        
        personal_notifications = list(cosmos_notifications_container.query_items(
            query=personal_query,
            parameters=personal_params,
            partition_key=user_id
        ))
        all_notifications.extend(personal_notifications)
        
        # 2. Fetch group notifications for user's groups
        from functions_group import get_user_groups
        user_groups = get_user_groups(user_id)
        
        for group in user_groups:
            group_id = group['id']
            group_query = "SELECT * FROM c WHERE c.group_id = @group_id"
            group_params = [{"name": "@group_id", "value": group_id}]
            
            group_notifications = list(cosmos_notifications_container.query_items(
                query=group_query,
                parameters=group_params,
                enable_cross_partition_query=True
            ))
            all_notifications.extend(group_notifications)
        
        # 3. Fetch public workspace notifications
        from functions_public_workspaces import get_user_public_workspaces
        user_workspaces = get_user_public_workspaces(user_id)
        
        for workspace in user_workspaces:
            workspace_id = workspace['id']
            workspace_query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id"
            workspace_params = [{"name": "@workspace_id", "value": workspace_id}]
            
            workspace_notifications = list(cosmos_notifications_container.query_items(
                query=workspace_query,
                parameters=workspace_params,
                enable_cross_partition_query=True
            ))
            all_notifications.extend(workspace_notifications)
        
        # 4. Fetch assignment-based notifications
        assignment_query = "SELECT * FROM c WHERE c.scope = 'assignment'"
        assignment_notifications = list(cosmos_notifications_container.query_items(
            query=assignment_query,
            enable_cross_partition_query=True
        ))
        
        # Filter assignment notifications based on user's roles and ownership
        for notif in assignment_notifications:
            assignment = notif.get('assignment')
            if not assignment:
                continue
            
            # Check if user matches assignment criteria
            user_matches = False

            # Broadcast to all users regardless of role/ownership
            if assignment.get('all_users'):
                user_matches = True
            
            # Check roles
            if not user_matches and user_roles and assignment.get('roles'):
                for role in assignment.get('roles', []):
                    if role in user_roles:
                        user_matches = True
                        break
            
            # Check ownership IDs
            if not user_matches:
                if assignment.get('personal_workspace_owner_id') == user_id:
                    user_matches = True
                elif assignment.get('group_owner_id') == user_id:
                    user_matches = True
                elif assignment.get('public_workspace_owner_id') == user_id:
                    user_matches = True
            
            if user_matches:
                all_notifications.append(notif)
        
        # Filter based on read/dismissed status
        filtered_notifications = []
        for notif in all_notifications:
            notif_id = notif.get('id', 'unknown')
            read_by = notif.get('read_by', [])
            dismissed_by = notif.get('dismissed_by', [])
            
            if not include_dismissed and user_id in dismissed_by:
                continue
            if not include_read and user_id in read_by:
                continue
            
            # Add UI metadata
            notif['message'] = _get_notification_display_message(notif)
            notif['is_read'] = user_id in read_by
            notif['is_dismissed'] = user_id in dismissed_by
            notif['type_config'] = _get_notification_type_config(notif)
            if notif.get('notification_type') == WORKFLOW_ALERT_NOTIFICATION_TYPE:
                notif['priority'] = _get_workflow_alert_priority(notif)
            
            filtered_notifications.append(notif)
        
        # Sort by created_at descending (newest first)
        filtered_notifications.sort(
            key=lambda x: x.get('created_at', ''),
            reverse=True
        )
        
        # Pagination
        total = len(filtered_notifications)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated = filtered_notifications[start_idx:end_idx]
        
        return {
            'notifications': paginated,
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': end_idx < total
        }
        
    except Exception as e:
        debug_print(f"Error fetching notifications for user {user_id}: {e}")
        return {
            'notifications': [],
            'total': 0,
            'page': page,
            'per_page': per_page,
            'has_more': False
        }


def get_unread_notification_count(user_id):
    """
    Get count of unread notifications for a user across all scopes.
    
    Args:
        user_id (str): User's unique identifier
        
    Returns:
        int: Count of unread notifications (capped at 10 for efficiency)
    """
    try:
        # Get notifications without pagination
        result = get_user_notifications(
            user_id=user_id,
            page=1,
            per_page=10,  # Only need first 10 for badge display
            include_read=False,
            include_dismissed=False
        )
        
        return min(result['total'], 10)  # Cap at 10 for display purposes
        
    except Exception as e:
        debug_print(f"Error counting unread notifications for {user_id}: {e}")
        return 0


def get_unread_workflow_priority_notifications(user_id, limit=5):
    """Return the most recent unread workflow alert notifications for a user."""
    try:
        normalized_limit = max(1, min(int(limit or 5), 10))
    except (TypeError, ValueError):
        normalized_limit = 5

    try:
        notifications = list(cosmos_notifications_container.query_items(
            query=(
                'SELECT * FROM c '
                'WHERE c.user_id = @user_id '
                'AND c.notification_type = @notification_type '
                'ORDER BY c.created_at DESC'
            ),
            parameters=[
                {'name': '@user_id', 'value': user_id},
                {'name': '@notification_type', 'value': WORKFLOW_ALERT_NOTIFICATION_TYPE},
            ],
            partition_key=user_id,
        ))

        unread_notifications = []
        for notification in notifications:
            if user_id in notification.get('dismissed_by', []):
                continue
            if user_id in notification.get('read_by', []):
                continue

            notification['message'] = _get_notification_display_message(notification)
            notification['is_read'] = False
            notification['is_dismissed'] = False
            notification['priority'] = _get_workflow_alert_priority(notification)
            notification['type_config'] = _get_notification_type_config(notification)
            unread_notifications.append(notification)

            if len(unread_notifications) >= normalized_limit:
                break

        return unread_notifications
    except Exception as e:
        debug_print(f"Error fetching unread workflow alerts for {user_id}: {e}")
        return []


def mark_notification_read(notification_id, user_id):
    """
    Mark a notification as read by a specific user.
    
    Args:
        notification_id (str): Notification ID
        user_id (str): User ID marking as read
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # First, find the notification across all partition keys
        query = "SELECT * FROM c WHERE c.id = @notification_id"
        params = [{"name": "@notification_id", "value": notification_id}]
        
        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        if not notifications:
            debug_print(f"Notification {notification_id} not found")
            return False
        
        notification = notifications[0]
        
        # Determine partition key
        partition_key = _get_notification_partition_key(notification)
        
        if not partition_key:
            debug_print(f"No partition key found for notification {notification_id}")
            return False
        
        # Add user to read_by if not already present
        read_by = notification.get('read_by', [])
        if user_id not in read_by:
            read_by.append(user_id)
            notification['read_by'] = read_by
            
            cosmos_notifications_container.upsert_item(notification)
            debug_print(f"Notification {notification_id} marked read by {user_id}")
        
        return True
        
    except Exception as e:
        debug_print(f"Error marking notification {notification_id} as read: {e}")
        return False


def mark_chat_response_notifications_read_for_conversation(user_id, conversation_id):
    """Mark personal chat-completion notifications read for a conversation."""
    try:
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.notification_type = @notification_type
            AND c.metadata.conversation_id = @conversation_id
        """
        params = [
            {'name': '@user_id', 'value': user_id},
            {'name': '@notification_type', 'value': 'chat_response_complete'},
            {'name': '@conversation_id', 'value': conversation_id},
        ]

        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))

        marked_count = 0
        for notification in notifications:
            read_by = notification.get('read_by', [])
            if user_id in read_by:
                continue

            read_by.append(user_id)
            notification['read_by'] = read_by
            cosmos_notifications_container.upsert_item(notification)
            marked_count += 1

        return marked_count
    except Exception as e:
        debug_print(
            f"Error marking chat response notifications as read for conversation {conversation_id}: {e}"
        )
        return 0


def mark_collaboration_message_notifications_read_for_conversation(user_id, conversation_id):
    """Mark personal collaboration-message notifications read for a conversation."""
    try:
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.notification_type = @notification_type
            AND c.metadata.conversation_id = @conversation_id
        """
        params = [
            {'name': '@user_id', 'value': user_id},
            {'name': '@notification_type', 'value': 'collaboration_message_received'},
            {'name': '@conversation_id', 'value': conversation_id},
        ]

        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))

        marked_count = 0
        for notification in notifications:
            read_by = notification.get('read_by', [])
            if user_id in read_by:
                continue

            read_by.append(user_id)
            notification['read_by'] = read_by
            cosmos_notifications_container.upsert_item(notification)
            marked_count += 1

        return marked_count
    except Exception as e:
        debug_print(
            f"Error marking collaboration notifications as read for conversation {conversation_id}: {e}"
        )
        return 0


def dismiss_notification(notification_id, user_id):
    """
    Dismiss a notification for a specific user (adds to dismissed_by).
    
    Args:
        notification_id (str): Notification ID
        user_id (str): User ID dismissing the notification
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Find notification across all partitions
        query = "SELECT * FROM c WHERE c.id = @notification_id"
        params = [{"name": "@notification_id", "value": notification_id}]
        
        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        if not notifications:
            debug_print(f"Notification {notification_id} not found")
            return False
        
        notification = notifications[0]
        
        # Determine partition key
        partition_key = _get_notification_partition_key(notification)
        
        if not partition_key:
            debug_print(f"No partition key found for notification {notification_id}")
            return False
        
        # Add user to dismissed_by
        dismissed_by = notification.get('dismissed_by', [])
        if user_id not in dismissed_by:
            dismissed_by.append(user_id)
            notification['dismissed_by'] = dismissed_by
            
            cosmos_notifications_container.upsert_item(notification)
            debug_print(f"Notification {notification_id} dismissed by {user_id}")
        
        return True
        
    except Exception as e:
        debug_print(f"Error dismissing notification {notification_id}: {e}")
        return False


def mark_all_read(user_id):
    """
    Mark all unread notifications as read for a user.
    
    Args:
        user_id (str): User's unique identifier
        
    Returns:
        int: Number of notifications marked as read
    """
    try:
        # Get all unread notifications
        result = get_user_notifications(
            user_id=user_id,
            page=1,
            per_page=1000,  # Get all unread
            include_read=False,
            include_dismissed=True
        )
        
        count = 0
        for notification in result['notifications']:
            if mark_notification_read(notification['id'], user_id):
                count += 1
        
        debug_print(f"Marked {count} notifications as read for user {user_id}")
        return count
        
    except Exception as e:
        debug_print(f"Error marking all notifications as read for {user_id}: {e}")
        return 0


def delete_notification(notification_id):
    """
    Permanently delete a notification (admin only).
    
    Args:
        notification_id (str): Notification ID to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Find notification to get partition key
        query = "SELECT * FROM c WHERE c.id = @notification_id"
        params = [{"name": "@notification_id", "value": notification_id}]
        
        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        if not notifications:
            return False
        
        notification = notifications[0]
        partition_key = _get_notification_partition_key(notification)
        
        if not partition_key:
            return False
        
        cosmos_notifications_container.delete_item(
            item=notification_id,
            partition_key=partition_key
        )
        
        debug_print(f"Notification {notification_id} permanently deleted")
        return True
        
    except Exception as e:
        debug_print(f"Error deleting notification {notification_id}: {e}")
        return False
