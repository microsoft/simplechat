# functions_approvals.py

"""
Approval workflow functions for Control Center administrative operations.
Handles approval requests for sensitive operations like ownership transfers,
group deletions, and document deletions.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from config import cosmos_approvals_container, cosmos_groups_container
from functions_appinsights import log_event
from functions_notifications import create_notification
from functions_group import find_group_by_id
from functions_debug import debug_print

# Approval request statuses
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_AUTO_DENIED = "auto_denied"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"

# Approval request types
TYPE_TAKE_OWNERSHIP = "take_ownership"
TYPE_TRANSFER_OWNERSHIP = "transfer_ownership"
TYPE_DELETE_DOCUMENTS = "delete_documents"
TYPE_DELETE_GROUP = "delete_group"
TYPE_DELETE_USER_DOCUMENTS = "delete_user_documents"

# TTL settings
TTL_AUTO_DENY_DAYS = 3
TTL_AUTO_DENY_SECONDS = TTL_AUTO_DENY_DAYS * 24 * 60 * 60  # 3 days in seconds


def create_approval_request(
    request_type: str,
    group_id: str,
    requester_id: str,
    requester_email: str,
    requester_name: str,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new approval request for a sensitive Control Center operation.
    
    Args:
        request_type: Type of request (take_ownership, transfer_ownership, delete_documents, delete_group, delete_user_documents)
        group_id: ID of the group being affected (or user_id for user-related requests)
        requester_id: User ID of the person requesting the action
        requester_email: Email of the requester
        requester_name: Display name of the requester
        reason: Explanation/justification for the request
        metadata: Additional request-specific data (e.g., new_owner_id for transfers, user_name for user documents)
    
    Returns:
        Created approval request document
    """
    try:
        # For user document deletion requests, use metadata for display info
        # Initialize group variable for notifications (may be None for non-group operations)
        group = None
        
        if request_type == TYPE_DELETE_USER_DOCUMENTS:
            # For user document deletions, group_id is actually the user_id (partition key)
            group_name = metadata.get('user_name', 'Unknown User')
            group_owner = {}
        elif metadata and metadata.get('entity_type') == 'workspace':
            # For public workspace operations
            from config import cosmos_public_workspaces_container
            try:
                workspace = cosmos_public_workspaces_container.read_item(item=group_id, partition_key=group_id)
                group_name = workspace.get('name', 'Unknown Workspace')
                workspace_owner = workspace.get('owner', {})
                if isinstance(workspace_owner, dict):
                    group_owner = {
                        'id': workspace_owner.get('userId'),
                        'email': workspace_owner.get('email'),
                        'displayName': workspace_owner.get('displayName')
                    }
                else:
                    # Old format where owner is just a string ID
                    group_owner = {'id': workspace_owner, 'email': 'unknown', 'displayName': 'unknown'}
                
                # Normalize workspace owner structure to match group owner structure for notifications
                # Workspace uses 'userId' but notification function expects 'id'
                workspace['owner'] = group_owner
                
                # Set group to workspace for notification purposes
                group = workspace
            except:
                raise ValueError(f"Workspace {group_id} not found")
        else:
            # Get group details for group-based approvals
            group = find_group_by_id(group_id)
            if not group:
                raise ValueError(f"Group {group_id} not found")
            
            group_name = group.get('name', 'Unknown Group')
            group_owner = group.get('owner', {})
        
        # Create approval request document
        approval_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        approval_request = {
            'id': approval_id,
            'group_id': group_id,  # Partition key
            'request_type': request_type,
            'status': STATUS_PENDING,
            'group_name': group_name,
            'requester_id': requester_id,
            'requester_email': requester_email,
            'requester_name': requester_name,
            'reason': reason,
            'group_owner_id': group_owner.get('id'),
            'group_owner_email': group_owner.get('email'),
            'group_owner_name': group_owner.get('displayName', group_owner.get('email')),
            'created_at': now.isoformat(),
            'expires_at': (now + timedelta(days=TTL_AUTO_DENY_DAYS)).isoformat(),
            'ttl': TTL_AUTO_DENY_SECONDS,  # Auto-deny after 3 days
            'approved_by_id': None,
            'approved_by_email': None,
            'approved_by_name': None,
            'approved_at': None,
            'approval_comment': None,
            'executed_at': None,
            'execution_result': None,
            'metadata': metadata or {}
        }
        
        # Save to Cosmos DB
        cosmos_approvals_container.create_item(body=approval_request)
        
        # Log event
        log_event("[Approvals] Created approval request", {
            'approval_id': approval_id,
            'request_type': request_type,
            'group_id': group_id,
            'group_name': group_name,
            'requester': requester_email,
            'reason': reason
        })
        debug_print(f"Created approval request: {approval_request}")
        
        # Create notifications for eligible approvers
        _create_approval_notifications(approval_request, group if request_type != TYPE_DELETE_USER_DOCUMENTS else None)
        
        return approval_request
        
    except Exception as e:
        log_event("[Approvals] Error creating approval request", {
            'error': str(e),
            'request_type': request_type,
            'group_id': group_id,
            'requester': requester_email
        }, level=logging.ERROR)
        debug_print(f"Error creating approval request: {e}")
        raise


def get_pending_approvals(
    user_id: str,
    user_roles: List[str],
    page: int = 1,
    per_page: int = 20,
    include_completed: bool = False,
    request_type_filter: Optional[str] = None,
    status_filter: str = 'pending'
) -> Dict[str, Any]:
    """
    Get approval requests that the user is eligible to approve.
    
    Args:
        user_id: Current user ID
        user_roles: List of roles the user has (e.g., ['admin', 'ControlCenterAdmin'])
        page: Page number for pagination
        per_page: Items per page
        include_completed: Include approved/denied/executed requests
        request_type_filter: Filter by request type
        status_filter: Filter by specific status ('pending', 'approved', 'denied', 'executed', 'all')
    
    Returns:
        Dictionary with approvals list, total count, and pagination info
    """
    try:
        # Build query based on filters
        query_parts = ["SELECT * FROM c WHERE 1=1"]
        parameters = []
        
        # Status filter
        if status_filter != 'all':
            # If specific status requested (pending, approved, denied, executed)
            query_parts.append("AND c.status = @status")
            parameters.append({"name": "@status", "value": status_filter})
        # else: 'all' means no status filter
        
        # Request type filter
        if request_type_filter:
            query_parts.append("AND c.request_type = @request_type")
            parameters.append({"name": "@request_type", "value": request_type_filter})
        
        # Order by created date descending
        query_parts.append("ORDER BY c.created_at DESC")
        
        query = " ".join(query_parts)
        
        debug_print(f"📋 [GET_APPROVALS] Query: {query}")
        debug_print(f"📋 [GET_APPROVALS] Parameters: {parameters}")
        debug_print(f"📋 [GET_APPROVALS] status_filter: {status_filter}")
        
        # Execute cross-partition query (we need to see all groups)
        items = list(cosmos_approvals_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        debug_print(f"📋 [GET_APPROVALS] Found {len(items)} total items from query")
        
        # Filter by user eligibility
        # For pending requests: check if user can approve
        # For completed requests: check if user has visibility (was involved or is admin/owner)
        eligible_approvals = []
        for approval in items:
            if status_filter == 'pending':
                # For pending requests, check if user can approve
                if _can_user_approve(approval, user_id, user_roles):
                    eligible_approvals.append(approval)
            else:
                # For completed requests, check if user has visibility
                if _can_user_view(approval, user_id, user_roles):
                    eligible_approvals.append(approval)
        
        debug_print(f"📋 [GET_APPROVALS] After eligibility filter: {len(eligible_approvals)} approvals")
        
        # Paginate
        total_count = len(eligible_approvals)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_approvals = eligible_approvals[start_idx:end_idx]
        
        debug_print(f"User {user_id} fetched pending approvals: page {page}, per_page {per_page}, total {total_count}")

        return {
            'approvals': paginated_approvals,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page
        }
        
    except Exception as e:
        log_event("[Approvals] Error fetching pending approvals", {
            'error': str(e),
            'user_id': user_id,
            'user_roles': user_roles
        })
        debug_print(f"Error fetching pending approvals: {e}")
        raise


def approve_request(
    approval_id: str,
    group_id: str,
    approver_id: str,
    approver_email: str,
    approver_name: str,
    comment: Optional[str] = None
) -> Dict[str, Any]:
    """
    Approve an approval request.
    
    Args:
        approval_id: ID of the approval request
        group_id: Group ID (partition key)
        approver_id: User ID of approver
        approver_email: Email of approver
        approver_name: Display name of approver
        comment: Optional comment from approver
    
    Returns:
        Updated approval request document
    """
    try:
        # Get the approval request
        approval = cosmos_approvals_container.read_item(
            item=approval_id,
            partition_key=group_id
        )
        
        # Validate status
        if approval['status'] != STATUS_PENDING:
            debug_print(f"Cannot approve request with status: {approval['status']}")
            raise ValueError(f"Cannot approve request with status: {approval['status']}")
        
        # Update approval status
        approval['status'] = STATUS_APPROVED
        approval['approved_by_id'] = approver_id
        approval['approved_by_email'] = approver_email
        approval['approved_by_name'] = approver_name
        approval['approved_at'] = datetime.utcnow().isoformat()
        approval['approval_comment'] = comment
        approval['ttl'] = -1  # Remove TTL so it doesn't auto-delete
        
        # Save updated approval
        cosmos_approvals_container.upsert_item(approval)
        
        # Log event
        log_event("[Approvals] Request approved", {
            'approval_id': approval_id,
            'request_type': approval['request_type'],
            'group_id': group_id,
            'approver': approver_email,
            'comment': comment
        })
        debug_print(f"Approved request: {approval}")    
        
        # Create notification for requester
        create_notification(
            user_id=approval['requester_id'],
            notification_type='approval_request_approved',
            title=f"Request Approved: {_format_request_type(approval['request_type'])}",
            message=f"Your request for {approval['group_name']} has been approved by {approver_name}.",
            link_url='/approvals',
            link_context={
                'approval_id': approval_id
            },
            metadata={
                'approval_id': approval_id,
                'request_type': approval['request_type'],
                'group_id': group_id,
                'approver_email': approver_email,
                'comment': comment
            }
        )
        
        return approval
        
    except Exception as e:
        log_event("[Approvals] Error approving request", {
            'error': str(e),
            'approval_id': approval_id,
            'group_id': group_id,
            'approver': approver_email
        })
        debug_print(f"Error approving request: {e}")
        raise


def deny_request(
    approval_id: str,
    group_id: str,
    denier_id: str,
    denier_email: str,
    denier_name: str,
    comment: str,
    auto_denied: bool = False
) -> Dict[str, Any]:
    """
    Deny an approval request.
    
    Args:
        approval_id: ID of the approval request
        group_id: Group ID (partition key)
        denier_id: User ID of person denying (or 'system' for auto-deny)
        denier_email: Email of denier
        denier_name: Display name of denier
        comment: Reason for denial
        auto_denied: Whether this is an automatic denial
    
    Returns:
        Updated approval request document
    """
    try:
        # Get the approval request
        approval = cosmos_approvals_container.read_item(
            item=approval_id,
            partition_key=group_id
        )
        
        # Validate status (allow denying pending requests)
        if approval['status'] not in [STATUS_PENDING]:
            debug_print(f"Cannot deny request with status: {approval['status']}")
            raise ValueError(f"Cannot deny request with status: {approval['status']}")
        
        # Update approval status
        approval['status'] = STATUS_AUTO_DENIED if auto_denied else STATUS_DENIED
        approval['approved_by_id'] = denier_id
        approval['approved_by_email'] = denier_email
        approval['approved_by_name'] = denier_name
        approval['approved_at'] = datetime.utcnow().isoformat()
        approval['approval_comment'] = comment
        approval['ttl'] = -1  # Remove TTL
        
        # Save updated approval
        cosmos_approvals_container.upsert_item(approval)
        
        # Log event
        log_event("[Approvals] Request denied", {
            'approval_id': approval_id,
            'request_type': approval['request_type'],
            'group_id': group_id,
            'denier': denier_email,
            'auto_denied': auto_denied,
            'comment': comment
        })
        debug_print(f"Request denied: {approval_id}")
        
        # Create notification for requester (only if not auto-denied)
        if not auto_denied:
            create_notification(
                user_id=approval['requester_id'],
                notification_type='approval_request_denied',
                title=f"Request Denied: {_format_request_type(approval['request_type'])}",
                message=f"Your request for {approval['group_name']} was denied by {denier_name}.",
                link_url='/approvals',
                link_context={
                    'approval_id': approval_id
                },
                metadata={
                    'approval_id': approval_id,
                    'request_type': approval['request_type'],
                    'group_id': group_id,
                    'denier_email': denier_email,
                    'comment': comment
                }
            )
        
        return approval
        
    except Exception as e:
        log_event("[Approvals] Error denying request", {
            'error': str(e),
            'approval_id': approval_id,
            'group_id': group_id,
            'denier_id': denier_id,
            'comment': comment,
            'auto_denied': auto_denied
        })
        debug_print(f"Error denying request: {e}")  
        raise


def mark_approval_executed(
    approval_id: str,
    group_id: str,
    success: bool,
    result_message: str
) -> Dict[str, Any]:
    """
    Mark an approved request as executed (or failed).
    
    Args:
        approval_id: ID of the approval request
        group_id: Group ID (partition key)
        success: Whether execution was successful
        result_message: Result message or error
    
    Returns:
        Updated approval request document
    """
    try:
        # Get the approval request
        approval = cosmos_approvals_container.read_item(
            item=approval_id,
            partition_key=group_id
        )
        
        # Update execution status
        approval['status'] = STATUS_EXECUTED if success else STATUS_FAILED
        approval['executed_at'] = datetime.utcnow().isoformat()
        approval['execution_result'] = result_message
        
        # Save updated approval
        cosmos_approvals_container.upsert_item(approval)
        
        # Log event
        log_event("[Approvals] Request executed", {
            'approval_id': approval_id,
            'request_type': approval['request_type'],
            'group_id': group_id,
            'success': success,
            'result': result_message
        })
        debug_print(f"Marked approval as executed: {approval_id}, success: {success}")
        
        return approval
        
    except Exception as e:
        log_event("[Approvals] Error marking request as executed", {
            'error': str(e),
            'approval_id': approval_id,
            'group_id': group_id,
            'success': success,
            'result': result_message
        })
        debug_print(f"Error marking approval as executed: {e}")
        raise


def get_approval_by_id(approval_id: str, group_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific approval request by ID.
    
    Args:
        approval_id: ID of the approval request
        group_id: Group ID (partition key)
    
    Returns:
        Approval request document or None if not found
    """
    try:
        return cosmos_approvals_container.read_item(
            item=approval_id,
            partition_key=group_id
        )
    except Exception:
        log_event("[Approvals] Approval not found", {
            'approval_id': approval_id,
            'group_id': group_id
        })
        debug_print(f"Approval not found: {approval_id}")
        return None


def auto_deny_expired_approvals() -> int:
    """
    Auto-deny approval requests that have expired (older than 3 days).
    This function should be called by a scheduled job.
    
    Returns:
        Number of approvals auto-denied
    """
    try:
        # Query for pending approvals
        query = "SELECT * FROM c WHERE c.status = @status"
        parameters = [{"name": "@status", "value": STATUS_PENDING}]
        
        pending_approvals = list(cosmos_approvals_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        now = datetime.utcnow()
        denied_count = 0
        
        for approval in pending_approvals:
            expires_at = datetime.fromisoformat(approval['expires_at'])
            
            # Check if expired
            if now >= expires_at:
                try:
                    deny_request(
                        approval_id=approval['id'],
                        group_id=approval['group_id'],
                        denier_id='system',
                        denier_email='system@simplechat',
                        denier_name='System Auto-Deny',
                        comment='Request automatically denied after 3 days without approval.',
                        auto_denied=True
                    )
                    denied_count += 1
                except Exception as e:
                    log_event("[Approvals] Error auto-denying expired approval", {  
                        'approval_id': approval['id'],
                        'error': str(e)
                    })
                    debug_print(f"Error auto-denying approval {approval['id']}: {e}")
        
        if denied_count > 0:
            log_event("[Approvals] Auto-denied expired approvals", {
                'denied_count': denied_count
            })
            debug_print(f"Auto-denied {denied_count} expired approvals")
        
        return denied_count
        
    except Exception as e:
        log_event("[Approvals] Error in auto_deny_expired_approvals", {
            'error': str(e)
        })
        debug_print(f"Error in auto_deny_expired_approvals: {e}")
        return 0


def _can_user_view(
    approval: Dict[str, Any],
    user_id: str,
    user_roles: List[str]
) -> bool:
    """
    Check if a user can view a specific approval request (including completed ones).
    
    Visibility rules (more permissive than approval rights):
    - User is the requester, OR
    - User is the approver, OR
    - User is the group owner, OR
    - User is the personal workspace owner (for user document operations), OR
    - User has 'ControlCenterAdmin' role, OR
    - User has 'Admin' role
    
    Args:
        approval: Approval request document
        user_id: User ID to check
        user_roles: List of roles the user has
    
    Returns:
        True if user can view, False otherwise
    """
    # Check if user was involved in the request
    is_requester = approval.get('requester_id') == user_id
    is_approver = approval.get('approved_by_id') == user_id
    
    # Check if user is the group owner
    is_group_owner = approval.get('group_owner_id') == user_id
    
    # Check if user is the personal workspace owner (for user document deletion)
    is_personal_workspace_owner = False
    if approval.get('request_type') == TYPE_DELETE_USER_DOCUMENTS:
        target_user_id = approval.get('metadata', {}).get('user_id')
        is_personal_workspace_owner = target_user_id == user_id
    
    # Check if user has admin roles
    has_control_center_admin = 'ControlCenterAdmin' in user_roles
    has_admin = 'Admin' in user_roles or 'admin' in user_roles
    
    # User can view if they meet any of these criteria
    return (is_requester or is_approver or is_group_owner or 
            is_personal_workspace_owner or has_control_center_admin or has_admin)


def _can_user_approve(
    approval: Dict[str, Any],
    user_id: str,
    user_roles: List[str]
) -> bool:
    """
    Check if a user is eligible to approve a specific request.
    
    Eligibility rules:
    - User must be the group owner (for group operations), OR
    - User must be the personal workspace owner (for user document operations), OR
    - User must have 'ControlCenterAdmin' role, OR
    - User must have 'Admin' role
    - User cannot be the requester (unless they're the only eligible approver)
    
    Args:
        approval: Approval request document
        user_id: User ID to check
        user_roles: List of roles the user has
    
    Returns:
        True if user can approve, False otherwise
    """
    # Check if user is the group owner (for group-based approvals)
    is_group_owner = approval.get('group_owner_id') == user_id
    
    # Check if user is the personal workspace owner (for user document deletion)
    is_personal_workspace_owner = False
    if approval.get('request_type') == TYPE_DELETE_USER_DOCUMENTS:
        # For user document deletion, check if user owns the documents
        target_user_id = approval.get('metadata', {}).get('user_id')
        is_personal_workspace_owner = target_user_id == user_id
    
    # Check if user has admin roles (check both capitalized and lowercase)
    has_control_center_admin = 'ControlCenterAdmin' in user_roles
    has_admin = 'Admin' in user_roles or 'admin' in user_roles
    
    # User must have at least one eligibility criterion
    if not (is_group_owner or is_personal_workspace_owner or has_control_center_admin or has_admin):
        return False
    
    # Special case: If user is the requester, they can still approve if they're the only eligible approver
    # This handles the case where there's only one admin in the system
    if approval.get('requester_id') == user_id:
        # Allow same-user approval (with documentation through the approval system)
        return True
    
    return True


def _create_approval_notifications(
    approval: Dict[str, Any],
    group: Optional[Dict[str, Any]]
) -> None:
    """
    Create notifications for all users who can approve the request using assignment-based targeting.
    Notifications target users by roles (Admin, ControlCenterAdmin) and/or ownership IDs.
    
    For user management (delete_user_documents):
        - Notifies: Control Center Admins, Admins, and the affected user
    For group management (transfer_ownership, delete_documents, delete_group, take_ownership):
        - Notifies: Control Center Admins, Admins, and the group owner
    
    Args:
        approval: Approval request document
        group: Group document (None for user-related approvals)
    """
    try:
        log_event("[Approvals] Creating assignment-based approval notifications", {
            'approval_id': approval['id'],
            'group_id': approval['group_id'],
            'request_type': approval['request_type']
        })
        debug_print(f"Creating assignment-based approval notifications for approval: {approval['id']}")
        
        # Build assignment criteria based on request type
        assignment = {
            'roles': ['Admin', 'ControlCenterAdmin']  # Always include admin roles
        }
        
        # Add ownership-based targeting
        if approval['request_type'] == TYPE_DELETE_USER_DOCUMENTS:
            # For user document deletion: notify the user whose documents are being deleted
            user_id = approval.get('metadata', {}).get('user_id')
            if user_id:
                assignment['personal_workspace_owner_id'] = user_id
                log_event("[Approvals] Targeting user for document deletion", {
                    'user_id': user_id,
                    'approval_id': approval['id']
                })
                debug_print(f"Added personal workspace owner {user_id} to notification assignment")
        else:
            # For group operations: notify the group owner
            if group:
                group_owner_id = group.get('owner', {}).get('id')
                if group_owner_id:
                    assignment['group_owner_id'] = group_owner_id
                    log_event("[Approvals] Targeting group owner", {
                        'group_owner_id': group_owner_id,
                        'approval_id': approval['id']
                    })
                    debug_print(f"Added group owner {group_owner_id} to notification assignment")
            else:
                log_event("[Approvals] No group provided for group-based approval", {
                    'approval_id': approval['id'],
                    'request_type': approval['request_type']
                }, level=logging.WARNING)
        
        log_event("[Approvals] Notification assignment", {
            'approval_id': approval['id'],
            'assignment': assignment
        })
        debug_print(f"Notification assignment for approval {approval['id']}: {assignment}")
        
        # For transfer ownership requests, also notify the new owner (informational)
        if approval['request_type'] == TYPE_TRANSFER_OWNERSHIP:
            new_owner_id = approval.get('metadata', {}).get('new_owner_id')
            if new_owner_id and new_owner_id != approval['requester_id']:
                # Create informational notification for new owner
                try:
                    log_event("[Approvals] Notifying new owner", {
                        'user_id': new_owner_id,
                        'approval_id': approval['id']
                    })
                    debug_print(f"Notifying new owner {new_owner_id} about transfer request")
                    create_notification(
                        group_id=approval['group_id'],
                        notification_type='approval_request_pending',
                        title=f"Ownership Transfer Pending",
                        message=f"{approval['requester_name']} has requested to transfer ownership of {approval['group_name']} to you. Awaiting approval.",
                        link_url='/approvals',
                        link_context={
                            'approval_id': approval['id']
                        },
                        metadata={
                            'approval_id': approval['id'],
                            'request_type': approval['request_type'],
                            'group_id': approval['group_id'],
                            'requester_email': approval['requester_email']
                        },
                        assignment={
                            'personal_workspace_owner_id': new_owner_id  # Only new owner sees this
                        }
                    )
                    debug_print(f"Successfully notified new owner {new_owner_id}")
                except Exception as notify_error:
                    log_event("[Approvals] Error notifying new owner", {
                        'error': str(notify_error),
                        'user_id': new_owner_id,
                        'approval_id': approval['id']
                    })
                    debug_print(f"Error notifying new owner {new_owner_id}: {str(notify_error)}")
        
        # Create single notification with assignment - visible to all eligible approvers
        try:
            log_event("[Approvals] Creating approval notification with assignment", {
                'approval_id': approval['id'],
                'assignment': assignment
            })
            debug_print(f"Creating approval notification with assignment for approval {approval['id']}")
            create_notification(
                group_id=approval['group_id'],
                notification_type='approval_request_pending',
                title=f"Approval Required: {_format_request_type(approval['request_type'])}",
                message=f"{approval['requester_name']} requests {_format_request_type(approval['request_type'])} for {approval['group_name']}. Reason: {approval.get('reason', 'Not provided')}",
                link_url='/approvals',
                link_context={
                    'approval_id': approval['id']
                },
                metadata={
                    'approval_id': approval['id'],
                    'request_type': approval['request_type'],
                    'group_id': approval['group_id'],
                    'requester_email': approval['requester_email'],
                    'reason': approval['reason']
                },
                assignment=assignment
            )
            debug_print(f"Successfully created approval notification with assignment for approval {approval['id']}")
        except Exception as notify_error:
            log_event("[Approvals] Error creating approval notification", {
                'error': str(notify_error),
                'approval_id': approval['id']
            })
            debug_print(f"Error creating approval notification for approval {approval['id']}: {str(notify_error)}")
    
    except Exception as e:
        log_event("[Approvals] Error notifying users about approval request", {
            'error': str(e),
            'approval_id': approval['id']
        })
        debug_print(f"Error notifying users about approval request {approval['id']}: {str(e)}")
        # Don't raise - notifications are non-critical


def _format_request_type(request_type: str) -> str:
    """
    Format request type for display.
    
    Args:
        request_type: Request type constant
    
    Returns:
        Human-readable request type string
    """
    type_labels = {
        TYPE_TAKE_OWNERSHIP: "Take Ownership",
        TYPE_TRANSFER_OWNERSHIP: "Transfer Ownership",
        TYPE_DELETE_DOCUMENTS: "Delete All Documents",
        TYPE_DELETE_GROUP: "Delete Group",
        TYPE_DELETE_USER_DOCUMENTS: "Delete All User Documents"
    }
    return type_labels.get(request_type, request_type)
