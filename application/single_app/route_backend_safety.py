# route_backend_safety.py

import csv
import io
import logging

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError
from flask import make_response

from config import *
from functions_appinsights import log_event
from functions_chat_content_checks import strip_private_chat_checks
from functions_chat_content_review import (
    ChatContentReviewConflict,
    content_checks_report_enabled,
    list_unchecked_chat_content,
    recheck_chat_message,
)
from content_screening.contracts import ScreeningError, ScreeningValidationError
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
    SAFETY_WARNING_REPLACED_CODE,
    SAFETY_WARNING_REPLACED_MESSAGE,
    acknowledge_safety_warning,
    build_safety_action_execution_updates,
    claim_safety_warning_send,
    execute_safety_violation_action,
    is_interrupted_safety_warning_send,
    list_pending_safety_warnings,
    mark_interrupted_safety_warning_send,
    present_safety_warning_send_state,
    record_safety_warning_send,
    resolve_safety_target_user,
    safety_warning_send_in_progress,
    serialize_safety_warning_state,
)
from functions_activity_logging import log_general_admin_action
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security


ALLOWED_SAFETY_PAGE_SIZES = {10, 20, 50, 100}
ALLOWED_SAFETY_STATUSES = {'New', 'In-Review', 'Resolved', 'Dismissed'}
# Escalate was a label with no workflow behind it. It can no longer be chosen, but a record
# that already carries it stays editable, so it is still accepted when it is unchanged.
SAFETY_ACTION_ESCALATE_LEGACY = 'Escalate'
SELECTABLE_SAFETY_ACTIONS = {'None', 'WarnUser', 'SuspendUser', 'BlockUser'}
ALLOWED_SAFETY_ACTIONS = SELECTABLE_SAFETY_ACTIONS | {SAFETY_ACTION_ESCALATE_LEGACY}
SAFETY_ESCALATE_RETIRED_MESSAGE = (
    'Escalate is no longer available as a safety action. '
    'Choose None, Warn user, Suspend user or Block user.'
)
SAFETY_WARNING_SEND_FAILED_MESSAGE = 'The warning notification could not be sent.'
# Of two overlapping saves that would send a warning -- a double-click, or two reviewers --
# only the one that claims the violation first sends it; the other is refused with this code.
SAFETY_WARNING_IN_PROGRESS_CODE = 'safety_warning_in_progress'
SAFETY_WARNING_SENDING_MESSAGE = (
    'A warning for this violation is being sent right now, so nothing was saved. '
    'Reload the violation in a moment to see the result.'
)
SAFETY_WARNING_CLAIM_CONFLICT_MESSAGE = (
    'Another save of this violation got there first, so this one saved nothing and sent no '
    'warning. Reload the violation in a moment to see the result.'
)
SAFETY_WARNING_NOT_RECORDED_CODE = 'safety_warning_not_recorded'
SAFETY_WARNING_NOT_RECORDED_MESSAGE = (
    'The warning was sent to the user, but it could not be recorded on this violation. '
    'Reload the violation before saving it again, so the warning is not sent twice.'
)
SAFETY_REMEDIATION_ACTIONS = {
    SAFETY_REMEDIATION_WARNING,
    SAFETY_REMEDIATION_SUSPEND,
    SAFETY_REMEDIATION_BLOCK,
}
# Suspend and block restrict access, so another eligible reviewer must approve them.
SAFETY_APPROVAL_REQUIRED_ACTIONS = {
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
        where_clauses.append("(NOT IS_DEFINED(c.content_origin) OR c.content_origin = 'user')")
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
        present_safety_warning_send_state(log_item)
        log_item.update(serialize_safety_warning_state(log_item))
    return strip_private_chat_checks(logs) if user_id else logs


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
        '[SAFETY_LIFECYCLE] Failed to persist lifecycle audit event',
        {
            'safety_log_id': log_id,
            'lifecycle_action': lifecycle_action,
        },
        level=logging.ERROR,
    )


def _log_safety_warning_sent(item, actor, notification_id):
    """Record the reviewer's warning in the activity log, the audit an approval used to be."""
    return log_general_admin_action(
        admin_user_id=actor.get('id'),
        admin_email=actor.get('email') or '',
        action='safety_violation_warning_sent',
        description='Sent a safety violation warning to a user.',
        additional_context={
            'record_type': 'safety_violation',
            'record_id': item.get('id'),
            'target_user_id': item.get('user_id'),
            'notification_id': notification_id,
        },
    )


def _send_safety_warning_now(item, actor, notification_title, notification_message):
    """Send a warning as the reviewer saves it, and record it on the violation.

    A suspension or block restricts access, so it waits for a second reviewer. A warning
    restricts nothing, so it is sent at once: the reviewer's decision is audited, and the
    user has to acknowledge the warning before carrying on.

    Nothing is sent until this save has claimed the violation, with a write conditional on
    the version it read, so of two overlapping saves -- a double-click, or two reviewers --
    only one sends the warning. The outcome is then written on the claimed version.
    Returns ``(response, status)``.
    """
    item['action_request_id'] = None
    item['action_request_type'] = None
    item['action_requested_at'] = None
    item['action_approved_at'] = None
    item['action_notification_title'] = notification_title or None
    item['action_notification_message'] = notification_message or None
    item['action_datetime_to_allow'] = None
    item['action_executed_at'] = None
    item['action_execution_error'] = None
    item['last_updated'] = datetime.utcnow().isoformat()

    try:
        claimed, claim_id = claim_safety_warning_send(item)
    except CosmosAccessConditionFailedError:
        log_event(
            '[SAFETY_REMEDIATION] An overlapping save claimed the safety warning first; this save sent nothing.',
            {'safety_log_id': item.get('id'), 'actor_id': actor.get('id')},
            level=logging.WARNING,
        )
        return jsonify({
            'error': SAFETY_WARNING_CLAIM_CONFLICT_MESSAGE,
            'code': SAFETY_WARNING_IN_PROGRESS_CODE,
        }), 409

    try:
        execution_result = execute_safety_violation_action(
            action=SAFETY_REMEDIATION_WARNING,
            safety_log=claimed,
            notification_title=notification_title,
            notification_message=notification_message,
            datetime_to_allow=None,
            actor=actor,
        )
    except Exception as exc:
        log_event(
            '[SAFETY_REMEDIATION] A safety warning could not be sent.',
            {
                'safety_log_id': item.get('id'),
                'actor_id': actor.get('id'),
                'error_type': type(exc).__name__,
            },
            level=logging.ERROR,
        )
        try:
            recorded = record_safety_warning_send(claimed, claim_id, {
                'action_request_status': 'failed',
                'action_executed_at': None,
                'action_execution_error': SAFETY_WARNING_SEND_FAILED_MESSAGE,
            })
        except Exception:
            recorded = None
        if recorded is None:
            log_event(
                '[SAFETY_REMEDIATION] A failed safety warning could not be recorded on its violation.',
                {'safety_log_id': item.get('id'), 'actor_id': actor.get('id')},
                level=logging.ERROR,
            )
        return jsonify({
            'error': 'The warning could not be sent. The rest of the review was saved; save it again to retry.',
        }), 500

    notification_id = execution_result.get('notification_id')
    updates = build_safety_action_execution_updates(SAFETY_REMEDIATION_WARNING, execution_result)
    record_error_type = None
    try:
        stored = record_safety_warning_send(claimed, claim_id, updates)
    except Exception as exc:
        stored = None
        record_error_type = type(exc).__name__
    # The warning reached the user either way, so the reviewer's decision is audited.
    audit_logged = _log_safety_warning_sent(stored or claimed, actor, notification_id)

    if stored is None:
        log_event(
            '[SAFETY_REMEDIATION] A safety warning was sent, but it could not be recorded on its violation.',
            {
                'safety_log_id': item.get('id'),
                'target_user_id': item.get('user_id'),
                'actor_id': actor.get('id'),
                'notification_id': notification_id,
                'error_type': record_error_type or 'claim_lost',
            },
            level=logging.ERROR,
        )
        return jsonify({
            'error': SAFETY_WARNING_NOT_RECORDED_MESSAGE,
            'code': SAFETY_WARNING_NOT_RECORDED_CODE,
            'audit_logged': audit_logged,
        }), 500 if record_error_type else 409

    log_event(
        '[SAFETY_REMEDIATION] Safety warning sent without a second reviewer.',
        {
            'safety_log_id': item.get('id'),
            'target_user_id': item.get('user_id'),
            'actor_id': actor.get('id'),
            'actor_email': actor.get('email'),
            'notification_id': notification_id,
        },
    )
    response = {
        'message': 'Warning sent to the user.',
        'approval_required': False,
        'approval_id': None,
        'audit_logged': audit_logged,
    }
    if not response['audit_logged']:
        response['audit_warning'] = 'The warning was sent, but the audit activity could not be recorded.'
    return jsonify(response), 200

def register_route_backend_safety(bp):
    def chat_check_error(error):
        if isinstance(error, (CosmosAccessConditionFailedError, CosmosResourceNotFoundError)):
            error = ChatContentReviewConflict()
        log_event(
            "[CHAT_CONTENT_CHECKS] Administrator chat check request failed.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        if isinstance(error, ScreeningError):
            return jsonify({"error": error.public_message, "code": error.code}), error.status_code
        return jsonify({
            "error": "The chat content check could not be completed. Reload and try again.",
            "code": "chat_content_check_unavailable",
        }), 503

    @bp.route("/api/safety/chat-checks", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def get_unchecked_chat_content():
        try:
            allowed = {"source", "checkpoint", "scanner", "continuation", "page_size"}
            if set(request.args) - allowed or any(len(values) != 1 for _key, values in request.args.lists()):
                raise ScreeningValidationError()
            page_size = request.args.get("page_size", "25")
            if not page_size.isascii() or not page_size.isdigit() or len(page_size) > 3:
                raise ScreeningValidationError()
            page = list_unchecked_chat_content(
                source=request.args.get("source", "all"),
                checkpoint=request.args.get("checkpoint") or None,
                scanner=request.args.get("scanner") or None,
                continuation=request.args.get("continuation") or None,
                page_size=int(page_size),
            )
            return jsonify(page)
        except (ScreeningError, AzureError) as error:
            return chat_check_error(error)

    @bp.route("/api/safety/chat-checks/recheck", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def recheck_unchecked_chat_content():
        try:
            if not request.is_json or request.content_length and request.content_length > 8192:
                raise ScreeningValidationError()
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) != {"source", "conversation_id", "message_id", "etag"}:
                raise ScreeningValidationError()
            result = recheck_chat_message(
                **data, actor_id=_get_safety_session_user_id(), settings=get_settings(),
            )
            return jsonify(result)
        except (ScreeningError, AzureError) as error:
            return chat_check_error(error)

    @bp.route('/api/safety/logs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
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
    @content_checks_report_enabled
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
    @content_checks_report_enabled
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
    @content_checks_report_enabled
    def update_safety_log(log_id):
        """
        Updates status, action, and notes on a safety log.
        Also sets timestamps (created_at if missing, and last_updated).

        Warn user sends the warning as soon as the review is saved; saving the record again
        does not send it twice, and of two overlapping saves only the one that claims the
        violation first sends it. Suspend user and Block user restrict access, so they create an
        approval request that another eligible reviewer must approve. Escalate can no longer
        be chosen; it is only accepted unchanged on a record that already carries it.
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
            previous_action = str(item.get('action') or 'None')
            existing_request_status = str(item.get('action_request_status') or '').strip().lower()

            if action == SAFETY_ACTION_ESCALATE_LEGACY and previous_action != SAFETY_ACTION_ESCALATE_LEGACY:
                return jsonify({'error': SAFETY_ESCALATE_RETIRED_MESSAGE}), 400

            if action in SAFETY_REMEDIATION_ACTIONS and item.get("content_origin", "user") != "user":
                return jsonify({"error": "AI-generated findings cannot be used to warn or restrict a user."}), 400

            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()

            if existing_request_status == 'pending':
                return jsonify({
                    'error': 'This violation already has a pending remediation approval request.'
                }), 409

            # While another save is sending a warning, the violation waits for it to finish.
            if safety_warning_send_in_progress(item):
                return jsonify({
                    'error': SAFETY_WARNING_SENDING_MESSAGE,
                    'code': SAFETY_WARNING_IN_PROGRESS_CODE,
                }), 409
            if is_interrupted_safety_warning_send(item):
                mark_interrupted_safety_warning_send(item)
                existing_request_status = 'failed'

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

            # Saving a warned record again, for example to resolve it, must not warn twice.
            warning_already_sent = (
                action == SAFETY_REMEDIATION_WARNING
                and previous_action == SAFETY_REMEDIATION_WARNING
                and existing_request_status == 'executed'
            )
            if action == SAFETY_REMEDIATION_WARNING and not warning_already_sent:
                return _send_safety_warning_now(item, actor, notification_title, notification_message)

            if action in SAFETY_APPROVAL_REQUIRED_ACTIONS:
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

            if action in SAFETY_APPROVAL_REQUIRED_ACTIONS:
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

            if warning_already_sent:
                return jsonify({
                    'message': 'Safety log updated. The warning was already sent, so it was not sent again.',
                    'approval_required': False,
                    'warning_already_sent': True,
                }), 200

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Safety violation not found'}), 404
        except exceptions.CosmosHttpResponseError as e:
            log_event('[SAFETY_VIOLATIONS] Failed to update safety log', {
                'safety_log_id': log_id,
                'error_type': type(e).__name__,
            }, level=logging.ERROR)
            return jsonify({'error': 'Failed to update safety log.'}), 500
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            log_event('[SAFETY_VIOLATIONS] Failed to update safety log', {
                'safety_log_id': log_id,
                'error_type': type(e).__name__,
            }, level=logging.ERROR)
            return jsonify({'error': 'Failed to update safety log.'}), 500

    @bp.route('/api/safety/logs/<string:log_id>/archive', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
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
                '[SAFETY_LIFECYCLE] Failed to update safety violation archive state',
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
    @content_checks_report_enabled
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
            if safety_warning_send_in_progress(item):
                return jsonify({
                    'error': (
                        'This safety violation cannot be deleted while a warning for it is '
                        'being sent. Try again in a moment.'
                    ),
                    'code': SAFETY_WARNING_IN_PROGRESS_CODE,
                }), 409
            cosmos_safety_container.delete_item(item=log_id, partition_key=log_id)
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Safety violation not found'}), 404
        except Exception as e:
            log_event(
                '[SAFETY_LIFECYCLE] Failed to delete safety violation',
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
    @content_checks_report_enabled
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
            log_event("[CONTENT_SAFETY] User content-check records could not be read.", extra={"error_type": type(e).__name__}, level=logging.WARNING)
            return jsonify({"error": "Your content-check records could not be loaded."}), 500

    @bp.route('/api/safety/logs/my/stats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @content_checks_report_enabled
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
            log_event("[CONTENT_SAFETY] User content-check statistics could not be read.", extra={"error_type": type(e).__name__}, level=logging.WARNING)
            return jsonify({"error": "Your content-check statistics could not be loaded."}), 500

    @bp.route('/api/safety/logs/my/export', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @content_checks_report_enabled
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
            log_event("[CONTENT_SAFETY] User content-check export failed.", extra={"error_type": type(e).__name__}, level=logging.WARNING)
            return jsonify({"error": "Your content-check records could not be exported."}), 500

    @bp.route('/api/safety/logs/my/<string:log_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @content_checks_report_enabled
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
            if item.get("content_origin", "user") != "user":
                return jsonify({"error": "Content-check record not found."}), 404

            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()

            if user_notes is not None:
                item["user_notes"] = user_notes

            item["last_updated"] = datetime.utcnow().isoformat()
            cosmos_safety_container.upsert_item(item)

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosHttpResponseError as e:
            log_event("[CONTENT_SAFETY] User content-check note could not be saved.", extra={"error_type": type(e).__name__}, level=logging.WARNING)
            return jsonify({"error": "The content-check note could not be saved."}), 404

    # A warning that was sent must stay acknowledgeable even if an administrator later turns
    # content checks reporting off, so these two routes are not gated on that setting.
    @bp.route('/api/safety/warnings/pending', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_pending_safety_warnings():
        """Return the signed-in user's own safety warnings that still need acknowledgment.

        Only what the user was sent is returned: the title, message, when it was issued,
        the violation id and its triggered categories.
        """
        user_id = _get_safety_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            warnings = list_pending_safety_warnings(user_id)
        except Exception as e:
            log_event(
                "[SAFETY_WARNINGS] Pending safety warnings could not be read.",
                extra={"user_id": user_id, "error_type": type(e).__name__},
                level=logging.WARNING,
            )
            return jsonify({"error": "Your warnings could not be loaded."}), 500, {"Cache-Control": "no-store"}

        return jsonify({"warnings": warnings, "count": len(warnings)}), 200, {"Cache-Control": "no-store"}

    @bp.route('/api/safety/warnings/<string:log_id>/acknowledge', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def acknowledge_pending_safety_warning(log_id):
        """Record that the signed-in user acknowledged one of their own safety warnings.

        Repeating it changes nothing. Any record that isn't the caller's own warning is
        answered 404, so the response never confirms that another user's record exists.
        The body may carry ``issued_at``, as listed by the pending route: when the
        violation has since been warned about again, the warning the user read was
        replaced, and 409 ``safety_warning_replaced`` records nothing.
        """
        user_id = _get_safety_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        payload = request.get_json(silent=True)
        issued_at = payload.get('issued_at') if isinstance(payload, dict) else None
        if issued_at is not None and not isinstance(issued_at, str):
            return jsonify({"error": "issued_at must be a string."}), 400

        try:
            status, warning = acknowledge_safety_warning(log_id, user_id, issued_at=issued_at)
        except Exception as e:
            log_event(
                "[SAFETY_WARNINGS] A safety warning acknowledgment could not be saved.",
                extra={"user_id": user_id, "error_type": type(e).__name__},
                level=logging.ERROR,
            )
            return jsonify({"error": "Your acknowledgment could not be saved. Try again."}), 500

        if status == 'not_found':
            return jsonify({"error": "Warning not found."}), 404
        if status == 'replaced':
            return jsonify({
                "error": SAFETY_WARNING_REPLACED_MESSAGE,
                "code": SAFETY_WARNING_REPLACED_CODE,
            }), 409
        return jsonify({
            "success": True,
            "already_acknowledged": status == 'already_acknowledged',
            "warning": warning,
        }), 200
