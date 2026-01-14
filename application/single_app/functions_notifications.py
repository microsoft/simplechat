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

# Notification type registry for extensibility
NOTIFICATION_TYPES = {
    'document_processing_complete': {
        'icon': 'bi-file-earmark-check',
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
    }
}


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
            partition_key = 'assignment-notifications'
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
            
            # Check roles
            if user_roles and assignment.get('roles'):
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
            notif['is_read'] = user_id in read_by
            notif['is_dismissed'] = user_id in dismissed_by
            notif['type_config'] = NOTIFICATION_TYPES.get(
                notif.get('notification_type'),
                NOTIFICATION_TYPES['system_announcement']
            )
            
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
        partition_key = notification.get('user_id') or notification.get('group_id') or notification.get('public_workspace_id')
        
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
        partition_key = notification.get('user_id') or notification.get('group_id') or notification.get('public_workspace_id')
        
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
        partition_key = notification.get('user_id') or notification.get('group_id') or notification.get('public_workspace_id')
        
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
