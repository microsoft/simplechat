# route_backend_safety.py

import csv
import io
import logging

from flask import make_response

from config import *
from functions_appinsights import log_event
from functions_approvals import (
    TYPE_BLOCK_USER,
    TYPE_SUSPEND_USER,
    TYPE_WARN_USER,
    approve_request,
    create_approval_request,
    get_approval_roles_for_request_type,
    mark_approval_executed,
)
from functions_authentication import *
from functions_review_lifecycle import (
    apply_archive_state,
    append_archive_query_filter,
    log_review_lifecycle_action,
    normalize_archive_state,
    serialize_archive_metadata,
)
from functions_safety_remediation import (
    SAFETY_REMEDIATION_BLOCK,
    SAFETY_REMEDIATION_SUSPEND,
    SAFETY_REMEDIATION_WARNING,
    execute_safety_violation_action,
    resolve_safety_target_user,
)
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security


ALLOWED_SAFETY_PAGE_SIZES = {10, 20, 50, 100}
ALLOWED_SAFETY_STATUSES = {'New', 'In-Review', 'Resolved', 'Dismissed'}
ALLOWED_SAFETY_ACTIONS = {'None', 'WarnUser', 'SuspendUser', 'Escalate', 'BlockUser'}
SAFETY_REMEDIATION_ACTIONS = {
    SAFETY_REMEDIATION_WARNING,
    SAFETY_REMEDIATION_SUSPEND,
    SAFETY_REMEDIATION_BLOCK,
}
SAFETY_ACTION_REQUEST_TYPE_MAP = {
    SAFETY_REMEDIATION_WARNING: TYPE_WARN_USER,
    SAFETY_REMEDIATION_SUSPEND: TYPE_SUSPEND_USER,
    SAFETY_REMEDIATION_BLOCK: TYPE_BLOCK_USER,
}


def _get_safety_session_user_id():
    if "user" not in session:
        return None

    return session["user"].get("oid") or session["user"].get("sub")


def _normalize_safety_page_size(page_size):
    return page_size if page_size in ALLOWED_SAFETY_PAGE_SIZES else 10


def _parse_safety_filters(include_archive_state=False):
    filters = (
        request.args.get('status', None, type=str),
        request.args.get('action', None, type=str),
    )
    if include_archive_state:
        return filters + (
            normalize_archive_state(request.args.get('archive', None, type=str)),
        )
    return filters


def _format_triggered_categories(log_item):
    categories = log_item.get('triggered_categories') or []
    formatted_categories = []
    for category in categories:
        category_name = str(category.get('category') or '').strip()
        severity = category.get('severity')
        if category_name and severity is not None:
            formatted_categories.append(f"{category_name}(s={severity})")
        elif category_name:
            formatted_categories.append(category_name)

    return ', '.join(formatted_categories)


def _get_safety_actor_context():
    user = session.get('user', {}) or {}
    actor_id = _get_safety_session_user_id()
    return {
        'id': actor_id,
        'email': user.get('preferred_username') or user.get('email') or '',
        'name': user.get('name') or user.get('preferred_username') or actor_id or 'Unknown User',
        'roles': user.get('roles', []) or [],
    }


def _validate_safety_remediation_request(action, datetime_to_allow):
    normalized_datetime_to_allow = datetime_to_allow or None
    if normalized_datetime_to_allow:
        try:
            datetime.fromisoformat(
                normalized_datetime_to_allow.replace('Z', '+00:00')
                if 'Z' in normalized_datetime_to_allow
                else normalized_datetime_to_allow
            )
        except ValueError as exc:
            raise ValueError('Invalid datetime format. Use ISO 8601 format.') from exc

    if action == SAFETY_REMEDIATION_SUSPEND and not normalized_datetime_to_allow:
        raise ValueError('Suspend user actions require a restore date and time.')

    if action == SAFETY_REMEDIATION_BLOCK:
        return None

    return normalized_datetime_to_allow


def _actor_can_self_approve_safety_request(request_type, actor_roles):
    """Requester-created safety approvals must be reviewed by another eligible user."""
    return False


def _build_safety_approval_metadata(
    log_item,
    action,
    notification_title,
    notification_message,
    datetime_to_allow,
    target_user,
):
    return {
        'user_id': log_item.get('user_id'),
        'user_name': target_user.get('display_name'),
        'user_email': target_user.get('email'),
        'safety_log_id': log_item.get('id'),
        'violation_action': action,
        'notification_title': notification_title,
        'notification_message': notification_message,
        'datetime_to_allow': datetime_to_allow,
        'violation_message': log_item.get('message') or '',
        'triggered_categories': log_item.get('triggered_categories') or [],
    }


def _query_safety_logs(
    user_id=None,
    filter_status=None,
    filter_action=None,
    archive_state='active',
):
    query = "SELECT * FROM c"
    where_clauses = []
    parameters = []

    if user_id:
        where_clauses.append("c.user_id = @user_id")
        parameters.append({"name": "@user_id", "value": user_id})

    if filter_status:
        where_clauses.append("c.status = @status")
        parameters.append({"name": "@status", "value": filter_status})

    if filter_action:
        where_clauses.append("c.action = @action")
        parameters.append({"name": "@action", "value": filter_action})

    append_archive_query_filter(where_clauses, archive_state)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += " ORDER BY c.created_at DESC"

    logs = list(cosmos_safety_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    ))
    for log_item in logs:
        log_item.update(serialize_archive_metadata(log_item))
    return logs


def _paginate_safety_logs(logs, page, page_size):
    if page < 1:
        page = 1

    page_size = _normalize_safety_page_size(page_size)
    offset = (page - 1) * page_size
    return logs[offset: offset + page_size], page, page_size


def _build_safety_stats(logs):
    stats = {
        "total_count": len(logs),
        "new_count": 0,
        "in_review_count": 0,
        "resolved_count": 0,
        "dismissed_count": 0,
        "warn_user_count": 0,
        "suspend_user_count": 0,
        "escalate_count": 0,
        "block_user_count": 0,
        "none_action_count": 0,
        "recent_30_day_count": 0,
        "latest_timestamp": None,
    }

    recent_cutoff = datetime.utcnow() - timedelta(days=30)

    for index, log_item in enumerate(logs):
        if index == 0:
            stats['latest_timestamp'] = log_item.get('last_updated') or log_item.get('created_at')

        status = str(log_item.get('status') or 'New')
        if status == 'New':
            stats['new_count'] += 1
        elif status == 'In-Review':
            stats['in_review_count'] += 1
        elif status == 'Resolved':
            stats['resolved_count'] += 1
        elif status == 'Dismissed':
            stats['dismissed_count'] += 1

        action = str(log_item.get('action') or 'None')
        if action == 'WarnUser':
            stats['warn_user_count'] += 1
        elif action == 'SuspendUser':
            stats['suspend_user_count'] += 1
        elif action == 'Escalate':
            stats['escalate_count'] += 1
        elif action == 'BlockUser':
            stats['block_user_count'] += 1
        else:
            stats['none_action_count'] += 1

        timestamp = log_item.get('last_updated') or log_item.get('created_at')
        if timestamp:
            try:
                parsed_timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed_timestamp.replace(tzinfo=None) >= recent_cutoff:
                    stats['recent_30_day_count'] += 1
            except ValueError:
                pass

    return stats


def _build_safety_export_response(logs, filename_prefix, include_user_id=False):
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        'Violation ID',
        'Status',
        'Action',
        'Message',
        'Triggered Categories',
        'User Notes',
        'Admin Notes',
        'Created At',
        'Last Updated',
        'Archived',
        'Archived At',
        'Archived By',
    ]
    if include_user_id:
        headers.insert(1, 'User ID')

    writer.writerow(headers)

    for log_item in logs:
        row = [
            log_item.get('id') or '',
            log_item.get('status') or 'New',
            log_item.get('action') or 'None',
            log_item.get('message') or '',
            _format_triggered_categories(log_item),
            log_item.get('user_notes') or '',
            log_item.get('notes') or '',
            log_item.get('created_at') or '',
            log_item.get('last_updated') or '',
            'Yes' if log_item.get('isArchived') else 'No',
            log_item.get('archivedAt') or '',
            log_item.get('archivedBy') or '',
        ]
        if include_user_id:
            row.insert(1, log_item.get('user_id') or '')
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = (
        f'attachment; filename={filename_prefix}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    )
    return response


def _safety_lifecycle_response(message, audit_logged):
    response = {
        'success': True,
        'message': message,
        'audit_logged': audit_logged,
    }
    if not audit_logged:
        response['audit_warning'] = (
            'The record was updated, but the audit activity could not be recorded.'
        )
    return jsonify(response)


def _log_safety_audit_failure(log_id, lifecycle_action):
    log_event(
        '[SafetyLifecycle] Failed to persist lifecycle audit event',
        {
            'safety_log_id': log_id,
            'lifecycle_action': lifecycle_action,
        },
        level=logging.ERROR,
    )

def register_route_backend_safety(bp):
    @bp.route('/api/safety/logs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def get_safety_logs():
        """
        Returns safety logs with server-side pagination and filtering.
        Query Parameters:
            page (int): The page number to retrieve (default: 1).
            page_size (int): The number of items per page (default: 10).
            status (str): Filter logs by status.
            action (str): Filter logs by action.
        """
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            filter_status, filter_action, archive_state = _parse_safety_filters(
                include_archive_state=True,
            )
            logs = _query_safety_logs(
                filter_status=filter_status,
                filter_action=filter_action,
                archive_state=archive_state,
            )
            paginated_items, page, page_size = _paginate_safety_logs(logs, page, page_size)

            return jsonify({
                "logs": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": len(logs)
            }), 200

        except ValueError:
            logging.exception("Invalid request parameters in get_safety_logs")
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception:
            logging.exception("Error in get_safety_logs")
            return jsonify({"error": "An internal error occurred while fetching safety logs."}), 500

    @bp.route('/api/safety/logs/stats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def get_safety_log_stats():
        """Return aggregate safety violation statistics for the admin page."""
        try:
            filter_status, filter_action, archive_state = _parse_safety_filters(
                include_archive_state=True,
            )
            logs = _query_safety_logs(
                filter_status=filter_status,
                filter_action=filter_action,
                archive_state=archive_state,
            )
            return jsonify(_build_safety_stats(logs)), 200
        except ValueError:
            logging.exception("Invalid request parameters in get_safety_log_stats")
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception:
            logging.exception("Error in get_safety_log_stats")
            return jsonify({"error": "Failed to retrieve safety stats."}), 500

    @bp.route('/api/safety/logs/export', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def export_safety_logs():
        """Export safety violation rows as CSV for the active filter set."""
        try:
            filter_status, filter_action, archive_state = _parse_safety_filters(
                include_archive_state=True,
            )
            logs = _query_safety_logs(
                filter_status=filter_status,
                filter_action=filter_action,
                archive_state=archive_state,
            )
            return _build_safety_export_response(logs, 'admin_safety_violations_export', include_user_id=True)
        except ValueError as e:
            logging.exception("Invalid parameters when exporting safety logs")
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception as e:
            return jsonify({"error": f"Failed to export safety logs: {str(e)}"}), 500

    @bp.route('/api/safety/logs/<string:log_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def update_safety_log(log_id):
        """
        Updates status, action, and notes on a safety log.
        Also sets timestamps (created_at if missing, and last_updated).
        """
        data = request.get_json() or {}
        status = data.get("status")
        action = data.get("action")
        notes = data.get("notes")
        notification_title = str(data.get('notification_title') or '').strip()
        notification_message = str(data.get('notification_message') or '').strip()
        datetime_to_allow = data.get('datetime_to_allow')
        
        try:
            if status and status not in ALLOWED_SAFETY_STATUSES:
                return jsonify({'error': 'Invalid safety status'}), 400

            if action and action not in ALLOWED_SAFETY_ACTIONS:
                return jsonify({'error': 'Invalid safety action'}), 400

            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)

            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()

            existing_request_status = str(item.get('action_request_status') or '').strip().lower()
            if existing_request_status == 'pending':
                return jsonify({
                    'error': 'This violation already has a pending remediation approval request.'
                }), 409

            normalized_datetime_to_allow = None
            if action in SAFETY_REMEDIATION_ACTIONS:
                normalized_datetime_to_allow = _validate_safety_remediation_request(action, datetime_to_allow)

            if status:
                item["status"] = status
            if action:
                item["action"] = action

            if notes is not None:
                item["notes"] = notes

            actor = _get_safety_actor_context()
            if not actor.get('id'):
                return jsonify({'error': 'No user ID found in session'}), 403

            if action in SAFETY_REMEDIATION_ACTIONS:
                target_user = resolve_safety_target_user(item.get('user_id'))
                request_type = SAFETY_ACTION_REQUEST_TYPE_MAP[action]
                approval_reason = notes or notification_message or f"Requested {action} for safety violation {log_id}."
                approval_metadata = _build_safety_approval_metadata(
                    item,
                    action,
                    notification_title,
                    notification_message,
                    normalized_datetime_to_allow,
                    target_user,
                )

                approval = create_approval_request(
                    request_type=request_type,
                    group_id=item.get('user_id'),
                    requester_id=actor['id'],
                    requester_email=actor['email'],
                    requester_name=actor['name'],
                    reason=approval_reason,
                    metadata=approval_metadata,
                )

                item['action_request_id'] = approval.get('id')
                item['action_request_type'] = request_type
                item['action_requested_at'] = approval.get('created_at')
                item['action_execution_error'] = None
                item['action_notification_title'] = notification_title or None
                item['action_notification_message'] = notification_message or None
                item['action_datetime_to_allow'] = normalized_datetime_to_allow

                if _actor_can_self_approve_safety_request(request_type, actor['roles']):
                    approval = approve_request(
                        approval_id=approval['id'],
                        group_id=approval['group_id'],
                        approver_id=actor['id'],
                        approver_email=actor['email'],
                        approver_name=actor['name'],
                        comment='Automatically approved by an eligible safety reviewer.',
                        approval=approval,
                    )

                    execution_result = execute_safety_violation_action(
                        action=action,
                        safety_log=item,
                        notification_title=notification_title,
                        notification_message=notification_message,
                        datetime_to_allow=normalized_datetime_to_allow,
                        actor=actor,
                    )

                    mark_approval_executed(
                        approval_id=approval['id'],
                        group_id=approval['group_id'],
                        success=execution_result['success'],
                        result_message=execution_result['message'],
                    )

                    item['action_request_status'] = 'executed'
                    item['action_approved_at'] = approval.get('approved_at')
                    item['action_executed_at'] = datetime.utcnow().isoformat()
                else:
                    item['action_request_status'] = 'pending'
                    item['action_approved_at'] = None
                    item['action_executed_at'] = None

            item["last_updated"] = datetime.utcnow().isoformat()

            cosmos_safety_container.upsert_item(item)

            if action in SAFETY_REMEDIATION_ACTIONS:
                if item.get('action_request_status') == 'pending':
                    return jsonify({
                        'message': 'Safety log updated and remediation approval request created.',
                        'approval_required': True,
                        'approval_id': item.get('action_request_id'),
                    }), 200

                return jsonify({
                    'message': 'Safety log updated and remediation executed successfully.',
                    'approval_required': False,
                    'approval_id': item.get('action_request_id'),
                }), 200

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosHttpResponseError as e:
            return jsonify({"error": str(e)}), 404
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            log_event('[SafetyViolations] Failed to update safety log', {
                'safety_log_id': log_id,
                'error': str(e),
            }, level=logging.ERROR)
            return jsonify({'error': f'Failed to update safety log: {str(e)}'}), 500

    @bp.route('/api/safety/logs/<string:log_id>/archive', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def archive_safety_log(log_id):
        """Archive or unarchive a safety violation record."""
        data = request.get_json() or {}
        archived = data.get('archived')
        if not isinstance(archived, bool):
            return jsonify({'error': 'The archived field must be a boolean.'}), 400

        actor = _get_safety_actor_context()
        if not actor.get('id'):
            return jsonify({'error': 'No user ID found in session'}), 403

        try:
            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
            was_archived = bool(item.get('is_archived'))
            apply_archive_state(item, archived, actor['id'])
            item['last_updated'] = datetime.utcnow().isoformat()
            cosmos_safety_container.upsert_item(item)
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Safety violation not found'}), 404
        except Exception as e:
            log_event(
                '[SafetyLifecycle] Failed to update safety violation archive state',
                {'safety_log_id': log_id, 'error': str(e)},
                level=logging.ERROR,
            )
            return jsonify({'error': 'Failed to update safety violation archive state'}), 500

        lifecycle_action = 'archive' if archived else 'unarchive'
        audit_logged = log_review_lifecycle_action(
            'safety_violation',
            lifecycle_action,
            item,
            actor,
            was_archived=was_archived,
        )
        if not audit_logged:
            _log_safety_audit_failure(log_id, lifecycle_action)

        message = (
            'Safety violation archived successfully.'
            if archived
            else 'Safety violation unarchived successfully.'
        )
        return _safety_lifecycle_response(message, audit_logged), 200

    @bp.route('/api/safety/logs/<string:log_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def delete_safety_log(log_id):
        """Permanently delete a safety violation without deleting its audit history."""
        actor = _get_safety_actor_context()
        if not actor.get('id'):
            return jsonify({'error': 'No user ID found in session'}), 403

        try:
            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
            if str(item.get('action_request_status') or '').strip().lower() == 'pending':
                return jsonify({
                    'error': (
                        'This safety violation cannot be deleted while a remediation '
                        'approval request is pending.'
                    )
                }), 409
            cosmos_safety_container.delete_item(item=log_id, partition_key=log_id)
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Safety violation not found'}), 404
        except Exception as e:
            log_event(
                '[SafetyLifecycle] Failed to delete safety violation',
                {'safety_log_id': log_id, 'error': str(e)},
                level=logging.ERROR,
            )
            return jsonify({'error': 'Failed to delete safety violation'}), 500

        audit_logged = log_review_lifecycle_action(
            'safety_violation',
            'delete',
            item,
            actor,
        )
        if not audit_logged:
            _log_safety_audit_failure(log_id, 'delete')

        return _safety_lifecycle_response(
            'Safety violation permanently deleted.',
            audit_logged,
        ), 200
        
    @bp.route('/api/safety/logs/my', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def get_my_safety_logs():
        """
        Returns the current user's safety logs with server-side pagination and filtering.
        Query Parameters:
            page (int): The page number to retrieve (default: 1).
            page_size (int): The number of items per page (default: 10).
            status (str): Filter logs by status.
            action (str): Filter logs by action.
        """
        user_id = _get_safety_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            filter_status, filter_action = _parse_safety_filters()
            logs = _query_safety_logs(
                user_id=user_id,
                filter_status=filter_status,
                filter_action=filter_action,
            )
            paginated_items, page, page_size = _paginate_safety_logs(logs, page, page_size)

            return jsonify({
                "logs": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": len(logs)
            }), 200

        except Exception as e:
            print(f"Error in get_my_safety_logs: {str(e)}")
            return jsonify({"error": f"An error occurred while fetching your safety logs: {str(e)}"}), 500

    @bp.route('/api/safety/logs/my/stats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def get_my_safety_log_stats():
        """Return aggregate safety violation statistics for the current user."""
        user_id = _get_safety_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            filter_status, filter_action = _parse_safety_filters()
            logs = _query_safety_logs(
                user_id=user_id,
                filter_status=filter_status,
                filter_action=filter_action,
            )
            return jsonify(_build_safety_stats(logs)), 200
        except Exception as e:
            return jsonify({"error": f"Failed to retrieve safety stats: {str(e)}"}), 500

    @bp.route('/api/safety/logs/my/export', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def export_my_safety_logs():
        """Export the current user's safety violation rows as CSV for the active filter set."""
        user_id = _get_safety_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            filter_status, filter_action = _parse_safety_filters()
            logs = _query_safety_logs(
                user_id=user_id,
                filter_status=filter_status,
                filter_action=filter_action,
            )
            return _build_safety_export_response(logs, 'my_safety_violations_export', include_user_id=False)
        except Exception as e:
            return jsonify({"error": f"Failed to export safety logs: {str(e)}"}), 500

    @bp.route('/api/safety/logs/my/<string:log_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def update_my_safety_log(log_id):
        """
        Allows the user to update only their own safety log, 
        specifically the user_notes field (separate from admin notes).
        """
        data = request.json
        user_notes = data.get("user_notes")

        user_id = None
        if "user" in session:
            user_id = session["user"].get("oid") or session["user"].get("sub")
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)

            if item.get("user_id") != user_id:
                return jsonify({"error": "You do not have permission to update this record."}), 403

            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()

            if user_notes is not None:
                item["user_notes"] = user_notes

            item["last_updated"] = datetime.utcnow().isoformat()
            cosmos_safety_container.upsert_item(item)

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosHttpResponseError as e:
            return jsonify({"error": str(e)}), 404
