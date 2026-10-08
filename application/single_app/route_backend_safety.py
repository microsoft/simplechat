# route_backend_safety.py

import csv
import io
import logging

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError
from flask import make_response

from config import *
from functions_appinsights import log_event
from functions_chat_content_checks import strip_private_chat_checks
from functions_chat_content_review import (
    ChatContentReviewConflict,
    content_checks_report_enabled,
    count_unchecked_chat_content,
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
    withdraw_approval_request,
)
from functions_authentication import *
from functions_review_assist import ReviewAssistError, present_suggestion, strip_suggestion
from functions_review_assist_runtime import (
    ReviewRecordStore,
    handle_review_assist_request,
    review_assist_error_response,
)
from functions_review_center import (
    REVIEW_RECORD_CHANGED_CODE,
    ReviewRecordConflict,
    ReviewRequestError,
    apply_suggested_review,
    cap_review_ids,
    daily_counts,
    dismiss_review_suggestion,
    in_review_window,
    normalize_review_search,
    parse_review_bulk_operations,
    parse_review_date,
    parse_review_window,
    refuse_suggestion_operations_while_off,
    replace_review_record,
    resolve_review_users,
    review_bulk_result,
    review_day,
    review_text_matches,
    review_window,
    summarize_review_bulk_results,
)
from functions_review_lifecycle import (
    ARCHIVE_STATE_ALL,
    apply_archive_state,
    append_archive_query_filter,
    log_review_lifecycle_action,
    normalize_archive_state,
    serialize_archive_metadata,
)
from functions_safety_remediation import (
    SAFETY_LOG_WRITE_ATTEMPTS,
    SAFETY_REMEDIATION_BLOCK,
    SAFETY_REMEDIATION_SUSPEND,
    SAFETY_REMEDIATION_WARNING,
    SAFETY_REQUEST_STATUSES,
    SAFETY_WARNING_REPLACED_CODE,
    SAFETY_WARNING_REPLACED_MESSAGE,
    SAFETY_WARNING_SEND_CLAIM_FIELDS,
    SafetyLogConflict,
    acknowledge_safety_warning,
    build_safety_action_execution_updates,
    claim_safety_warning_send,
    execute_safety_violation_action,
    is_interrupted_safety_warning_send,
    list_pending_safety_warnings,
    mark_interrupted_safety_warning_send,
    present_safety_warning_send_state,
    record_safety_warning_send,
    reconcile_pending_safety_log,
    reconcile_pending_safety_logs,
    resolve_safety_target_user,
    safety_remediation_state,
    safety_warning_send_in_progress,
    serialize_safety_warning_state,
    write_safety_log_updates,
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
SAFETY_PENDING_UPDATE_MESSAGE = 'This violation already has a pending remediation approval request.'
SAFETY_PENDING_DELETE_MESSAGE = (
    'This safety violation cannot be deleted while a remediation approval request is pending.'
)
SAFETY_REMEDIATION_PENDING_CODE = 'remediation_pending'
SAFETY_RECORD_CHANGED_MESSAGE = (
    'This violation changed after you opened it. Reload it to see the latest version, then try again.'
)
SAFETY_REQUEST_NOT_RECORDED_MESSAGE = (
    'This violation changed while the request was being created, so nothing was requested. '
    'Reload it to see the latest version, then try again.'
)
SAFETY_REQUEST_WITHDRAWN_COMMENT = (
    'Withdrawn automatically: the safety violation changed while this request was being created, '
    'so the request was never recorded on it.'
)
SAFETY_ARCHIVE_IN_PROGRESS_MESSAGE = (
    'This safety violation cannot be archived or restored while a warning for it '
    'is being sent. Try again in a moment.'
)
# "Open" is the reviewer's queue: everything not yet resolved or dismissed.
SAFETY_LIST_STATUS_OPEN = 'open'
SAFETY_OPEN_STATUSES = {'New', 'In-Review'}
SAFETY_WARNING_FILTERS = {'pending', 'acknowledged', 'not_tracked'}
# The remediation request fields an approval request writes beside a reviewer's own changes,
# and the archive fields, so a conflicting write is merged field by field and never drops
# another writer's change. A reviewer's save writes only the review fields it was sent.
SAFETY_REQUEST_FIELDS = (
    'action_request_id',
    'action_request_type',
    'action_requested_at',
    'action_approved_at',
    'action_executed_at',
    'action_request_status',
    'action_request_decided_at',
    'action_execution_error',
    'action_notification_title',
    'action_notification_message',
    'action_datetime_to_allow',
)
SAFETY_ARCHIVE_FIELDS = (
    'is_archived',
    'archived_at',
    'archived_by',
    'unarchived_at',
    'unarchived_by',
    'last_updated',
)
SAFETY_REPEAT_USERS_LIMIT = 10
SAFETY_ACTION_LABELS = {
    SAFETY_REMEDIATION_SUSPEND: 'suspension',
    SAFETY_REMEDIATION_BLOCK: 'block',
}
SAFETY_AI_FILTER_PENDING = 'pending'


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
    reconcile=False,
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
    if reconcile:
        # Before anything is added to the records: a settled violation is written back
        # whole, so it must still be exactly the stored document.
        logs = reconcile_pending_safety_logs(logs)
    for log_item in logs:
        if user_id:
            # A user reads their own violations; what an AI suggested about them is for reviewers.
            strip_suggestion(log_item)
        else:
            # Read from the stored fields, before they are prepared for display.
            log_item['ai_suggestion'] = present_suggestion('safety', log_item)
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


def _safety_record_time(log_item):
    return log_item.get('created_at') or log_item.get('timestamp')


def _safety_category_names(log_item):
    names = []
    for entry in log_item.get('triggered_categories') or []:
        if isinstance(entry, dict):
            name = str(entry.get('category') or '').strip()
            if name:
                names.append(name)
    return list(dict.fromkeys(names))


def _safety_highest_severity(log_item):
    severities = [
        entry.get('severity')
        for entry in log_item.get('triggered_categories') or []
        if isinstance(entry, dict)
        and isinstance(entry.get('severity'), (int, float))
        and not isinstance(entry.get('severity'), bool)
    ]
    return int(max(severities)) if severities else None


def _safety_request_state(log_item):
    return str(log_item.get('action_request_status') or '').strip().lower()


def _parse_safety_list_filters():
    """Read the Review center list filters. Raises ValueError for a value that can't be used."""
    args = request.args
    severity_text = (args.get('severity') or '').strip()
    if severity_text and not severity_text.isdigit():
        raise ReviewRequestError('The severity must be a whole number.', code='invalid_severity')
    request_state = (args.get('request') or '').strip().lower() or None
    if request_state and request_state not in SAFETY_REQUEST_STATUSES:
        raise ReviewRequestError('Unknown remediation request state.', code='invalid_request_state')
    warning = (args.get('warning') or '').strip().lower() or None
    if warning and warning not in SAFETY_WARNING_FILTERS:
        raise ReviewRequestError('Unknown warning acknowledgment state.', code='invalid_warning_state')
    ai_state = (args.get('ai') or '').strip().lower() or None
    if ai_state and ai_state != SAFETY_AI_FILTER_PENDING:
        raise ReviewRequestError('Unknown AI suggestion state.', code='invalid_ai_state')
    return {
        'status': (args.get('status') or '').strip() or None,
        'action': (args.get('action') or '').strip() or None,
        'archive': normalize_archive_state(args.get('archive', None, type=str)),
        'search': normalize_review_search(args.get('search')),
        'user_id': (args.get('user_id') or '').strip() or None,
        'category': (args.get('category') or '').strip().lower() or None,
        'severity': int(severity_text) if severity_text else None,
        'request': request_state,
        'warning': warning,
        'restricted': (args.get('restricted') or '').strip().lower() in ('1', 'true'),
        'date': parse_review_date(args.get('date')),
        'days': parse_review_window(args.get('days')),
        'ai': ai_state,
    }


def _safety_restricts_user_now(log_item, users):
    """True for an applied suspension or block whose user is still restricted."""
    if log_item.get('action') not in SAFETY_APPROVAL_REQUIRED_ACTIONS or _safety_request_state(log_item) != 'executed':
        return False
    access = (users.get(log_item.get('user_id')) or {}).get('access') or {}
    return access.get('restricted') is True


def _safety_log_matches(log_item, filters, users, window):
    status = str(log_item.get('status') or 'New')
    if filters['status'] == SAFETY_LIST_STATUS_OPEN and status not in SAFETY_OPEN_STATUSES:
        return False
    if filters['user_id'] and log_item.get('user_id') != filters['user_id']:
        return False
    if filters['category'] and filters['category'] not in {
        name.lower() for name in _safety_category_names(log_item)
    }:
        return False
    if filters['severity'] is not None and _safety_highest_severity(log_item) != filters['severity']:
        return False
    if filters['request'] and _safety_request_state(log_item) != filters['request']:
        return False
    if filters['warning'] and log_item.get('warning_acknowledgment_status') != filters['warning']:
        return False
    if filters['restricted'] and not _safety_restricts_user_now(log_item, users):
        return False
    if filters['date'] and review_day(_safety_record_time(log_item)) != filters['date']:
        return False
    if window and not in_review_window(_safety_record_time(log_item), window):
        return False
    # The AI suggestions queue: suggestions still waiting for a reviewer, stale ones included so
    # they can be dismissed.
    if filters.get('ai') == SAFETY_AI_FILTER_PENDING and (
        (log_item.get('ai_suggestion') or {}).get('status') not in ('pending', 'stale')
    ):
        return False
    if filters['search']:
        user = users.get(log_item.get('user_id')) or {}
        return review_text_matches(
            filters['search'],
            log_item.get('id'),
            log_item.get('message'),
            log_item.get('notes'),
            log_item.get('user_notes'),
            log_item.get('user_id'),
            user.get('display_name'),
            user.get('email'),
            ' '.join(_safety_category_names(log_item)),
        )
    return True


def _load_admin_safety_logs(filters):
    """The violations a Review center list or "select all matching" covers, newest first.

    Violations whose remediation request was decided or has expired are settled first, so
    a list never shows a violation locked by a request that can no longer be decided.
    Returns ``(logs, users)``, where ``users`` holds the names already looked up.
    """
    status = filters['status']
    logs = _query_safety_logs(
        filter_status=None if status == SAFETY_LIST_STATUS_OPEN else status,
        filter_action=filters['action'],
        archive_state=filters['archive'],
        reconcile=True,
    )
    users = {}
    if filters['search'] or filters['restricted']:
        users = resolve_review_users(
            [log_item.get('user_id') for log_item in logs],
            include_access=filters['restricted'],
        )
    window = review_window(filters['days']) if filters['days'] else None
    selected = [log_item for log_item in logs if _safety_log_matches(log_item, filters, users, window)]
    return selected, users


def _with_safety_user_names(items, users=None):
    """Add each record's user display name and email, looked up in one batch."""
    names = dict(users or {})
    missing = [item.get('user_id') for item in items if item.get('user_id') not in names]
    if missing:
        names.update(resolve_review_users(missing))
    for item in items:
        entry = names.get(item.get('user_id')) or {}
        item['user_display_name'] = entry.get('display_name') or None
        item['user_email'] = entry.get('email') or None
    return items


def _count_other_user_violations(user_id, log_id):
    """How many other violations the same user has, or None when that can't be read."""
    if not user_id:
        return 0
    try:
        rows = cosmos_safety_container.query_items(
            query="SELECT c.id, c.content_origin FROM c WHERE c.user_id = @user_id",
            parameters=[{"name": "@user_id", "value": user_id}],
            enable_cross_partition_query=True,
        )
        return sum(
            1 for row in rows
            if isinstance(row, dict)
            and row.get('id') != log_id
            and row.get('content_origin', 'user') == 'user'
        )
    except Exception as exc:
        log_event(
            '[SAFETY_VIOLATIONS] The user violation count could not be read.',
            {'safety_log_id': log_id, 'error_type': type(exc).__name__},
            level=logging.WARNING,
        )
        return None


def _build_safety_window_stats(days):
    """The Safety dashboard for the last ``days`` days, read across active and archived records."""
    window = review_window(days)
    logs = _query_safety_logs(archive_state=ARCHIVE_STATE_ALL, reconcile=True)
    in_window = [log_item for log_item in logs if in_review_window(_safety_record_time(log_item), window)]
    tracked_warnings = [
        log_item for log_item in logs
        if log_item.get('warning_acknowledgment_status') in ('pending', 'acknowledged')
    ]
    sent_in_window = [
        log_item for log_item in tracked_warnings
        if in_review_window(log_item.get('warning_issued_at'), window)
    ]

    restricting = sorted({
        log_item.get('user_id') for log_item in logs
        if log_item.get('user_id')
        and log_item.get('action') in SAFETY_APPROVAL_REQUIRED_ACTIONS
        and _safety_request_state(log_item) == 'executed'
    })
    restricted_user_count = 0
    if restricting:
        access_by_user = resolve_review_users(restricting, include_access=True)
        restricted_user_count = sum(
            1 for user_id in restricting
            if ((access_by_user.get(user_id) or {}).get('access') or {}).get('restricted') is True
        ) if access_by_user else None

    try:
        unchecked_chat_count = count_unchecked_chat_content()
    except Exception as exc:
        log_event(
            '[CHAT_CONTENT_CHECKS] Unchecked chat content could not be counted for the dashboard.',
            {'error_type': type(exc).__name__},
            level=logging.WARNING,
        )
        unchecked_chat_count = None

    per_user = {}
    severity_counts = {}
    action_counts = {}
    for log_item in in_window:
        severity = _safety_highest_severity(log_item)
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        action = str(log_item.get('action') or 'None')
        action_counts[action] = action_counts.get(action, 0) + 1
        user_id = log_item.get('user_id')
        if user_id and log_item.get('content_origin', 'user') == 'user':
            per_user[user_id] = per_user.get(user_id, 0) + 1
    repeat = sorted(
        ((user_id, count) for user_id, count in per_user.items() if count >= 2),
        key=lambda pair: (-pair[1], pair[0]),
    )[:SAFETY_REPEAT_USERS_LIMIT]
    repeat_names = resolve_review_users([user_id for user_id, _count in repeat])

    return {
        'window': {
            'days': window['days'],
            'start_date': window['start_date'],
            'end_date': window['end_date'],
        },
        'received_count': len(in_window),
        'open_count': sum(
            1 for log_item in logs
            if not log_item.get('isArchived') and str(log_item.get('status') or 'New') in SAFETY_OPEN_STATUSES
        ),
        'pending_remediation_count': sum(1 for log_item in logs if _safety_request_state(log_item) == 'pending'),
        'restricted_user_count': restricted_user_count,
        'warnings_sent_count': len(sent_in_window),
        'warnings_acknowledged_count': sum(
            1 for log_item in sent_in_window if log_item.get('warning_acknowledgment_status') == 'acknowledged'
        ),
        'warnings_pending_count': sum(
            1 for log_item in tracked_warnings if log_item.get('warning_acknowledgment_status') == 'pending'
        ),
        'unchecked_chat_count': unchecked_chat_count,
        'daily_by_category': daily_counts(
            in_window,
            window,
            _safety_record_time,
            lambda log_item: _safety_category_names(log_item) or ['Uncategorized'],
        ),
        'severity_mix': [
            {'severity': severity, 'count': count}
            for severity, count in sorted(
                severity_counts.items(),
                key=lambda pair: (pair[0] is None, pair[0] if pair[0] is not None else 0),
            )
        ],
        'action_mix': [
            {'action': action, 'count': count}
            for action, count in sorted(action_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        'repeat_users': [
            {
                'user_id': user_id,
                'display_name': (repeat_names.get(user_id) or {}).get('display_name') or None,
                'email': (repeat_names.get(user_id) or {}).get('email') or None,
                'count': count,
            }
            for user_id, count in repeat
        ],
    }


def _record_changed_body():
    return {'error': SAFETY_RECORD_CHANGED_MESSAGE, 'code': REVIEW_RECORD_CHANGED_CODE}


def _review_assist_client(settings):
    """The draft-instructions deployment's client and model name, as the other AI assistants use."""
    # Lazy: route_backend_agents loads the agent stack, which app.py has already imported by the
    # time a request arrives. Importing it when this module loads would make the safety routes
    # depend on that whole stack.
    from route_backend_agents import _create_agent_instruction_client, _resolve_agent_instruction_model
    return _create_agent_instruction_client(settings), _resolve_agent_instruction_model(settings)


def _write_attempts(expected_etag):
    """How often a save may write: once when it names the version it read, so a conflict is
    refused rather than merged onto a newer version; otherwise it is merged field by field."""
    return 1 if expected_etag else SAFETY_LOG_WRITE_ATTEMPTS


def _remediation_unchanged(read_item):
    """A guard for a reviewer's save: the violation's request and warning are as the save read them.

    A conflicting write is merged onto a fresh read only while nothing a remediation decision
    rests on has moved -- no warning is being sent or was recorded since, and the violation
    waits on the same request -- so a save never lands on another save's warning or request.
    """
    expected = safety_remediation_state(read_item)

    def guard(current):
        return not safety_warning_send_in_progress(current) and safety_remediation_state(current) == expected

    return guard


def _withdraw_safety_request(approval, actor, log_id):
    """Withdraw a remediation request this save created but could not record on its violation.

    Nothing links the violation to the request then, so it is withdrawn at once instead of
    being left for a reviewer to approve. Should withdrawing fail, approval still refuses to
    carry out a request its violation is not waiting on. Returns True when it was withdrawn.
    """
    approval = approval or {}
    try:
        withdrawn = withdraw_approval_request(
            approval_id=approval.get('id'),
            group_id=approval.get('group_id'),
            withdrawn_by_id=actor.get('id'),
            withdrawn_by_email=actor.get('email') or '',
            withdrawn_by_name=actor.get('name') or '',
            comment=SAFETY_REQUEST_WITHDRAWN_COMMENT,
        )
    except Exception as exc:
        log_event(
            '[SAFETY_REMEDIATION] A remediation request its violation could not record was not withdrawn.',
            {'safety_log_id': log_id, 'approval_id': approval.get('id'), 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return False
    log_event(
        '[SAFETY_REMEDIATION] A remediation request was withdrawn because its violation changed while it was created.',
        {
            'safety_log_id': log_id,
            'approval_id': approval.get('id'),
            'actor_id': actor.get('id'),
            'withdrawn': withdrawn is not None,
        },
        level=logging.WARNING,
    )
    return withdrawn is not None


def _response_parts(result):
    """The JSON body and status of a route-style result, for one bulk operation."""
    if isinstance(result, tuple):
        response, status = result[0], result[1]
    else:
        response, status = result, getattr(result, 'status_code', 200)
    body = response.get_json(silent=True) if hasattr(response, 'get_json') else response
    return (body if isinstance(body, dict) else {}), int(status)


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


def _safety_lifecycle_body(message, audit_logged):
    response = {
        'success': True,
        'message': message,
        'audit_logged': audit_logged,
    }
    if not audit_logged:
        response['audit_warning'] = (
            'The record was updated, but the audit activity could not be recorded.'
        )
    return response


def _safety_lifecycle_response(message, audit_logged):
    return jsonify(_safety_lifecycle_body(message, audit_logged))


def _log_safety_audit_failure(log_id, lifecycle_action):
    log_event(
        '[SAFETY_LIFECYCLE] Failed to persist lifecycle audit event',
        {
            'safety_log_id': log_id,
            'lifecycle_action': lifecycle_action,
        },
        level=logging.ERROR,
    )


def _archive_safety_log(log_id, archived, actor, expected_etag=None):
    """Archive or restore one violation. Returns ``(body, status)``.

    Shared by the archive route and the bulk ``archive`` operation. Only the archive fields
    are written, conditionally on the stored version, so a concurrent change to anything
    else on the record survives. ``expected_etag`` refuses a record that changed since the
    caller read it.
    """
    if not isinstance(archived, bool):
        return {'error': 'The archived field must be a boolean.'}, 400
    if not actor.get('id'):
        return {'error': 'No user ID found in session'}, 403

    try:
        item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
        if expected_etag and item.get('_etag') != expected_etag:
            return _record_changed_body(), 409
        # A warning being sent is recorded on the record when it finishes; wait for that.
        if safety_warning_send_in_progress(item):
            return {
                'error': SAFETY_ARCHIVE_IN_PROGRESS_MESSAGE,
                'code': SAFETY_WARNING_IN_PROGRESS_CODE,
            }, 409
        was_archived = bool(item.get('is_archived'))
        apply_archive_state(item, archived, actor['id'])
        item['last_updated'] = datetime.utcnow().isoformat()
        stored = write_safety_log_updates(
            log_id,
            {field: item.get(field) for field in SAFETY_ARCHIVE_FIELDS if field in item},
            base_item=item,
            guard=lambda current: not safety_warning_send_in_progress(current),
            attempts=_write_attempts(expected_etag),
        )
        if stored is None:
            return {
                'error': SAFETY_ARCHIVE_IN_PROGRESS_MESSAGE,
                'code': SAFETY_WARNING_IN_PROGRESS_CODE,
            }, 409
    except exceptions.CosmosResourceNotFoundError:
        return {'error': 'Safety violation not found'}, 404
    except SafetyLogConflict:
        return _record_changed_body(), 409
    except Exception as e:
        log_event(
            '[SAFETY_LIFECYCLE] Failed to update safety violation archive state',
            {'safety_log_id': log_id, 'error_type': type(e).__name__},
            level=logging.ERROR,
        )
        return {'error': 'Failed to update safety violation archive state'}, 500

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
    return _safety_lifecycle_body(message, audit_logged), 200


def _delete_safety_log(log_id, actor, expected_etag=None):
    """Permanently delete one violation, keeping its audit history. Returns ``(body, status)``.

    Shared by the delete route and the bulk ``delete`` operation. A violation whose
    remediation request is still pending is refused; one whose request was decided or has
    expired is settled first, so it can be deleted. The delete is conditional on the version
    read, so a violation that changes in the meantime is not deleted.
    """
    if not actor.get('id'):
        return {'error': 'No user ID found in session'}, 403

    try:
        item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
        if expected_etag and item.get('_etag') != expected_etag:
            return _record_changed_body(), 409
        item = reconcile_pending_safety_log(item)
        if str(item.get('action_request_status') or '').strip().lower() == 'pending':
            return {
                'error': SAFETY_PENDING_DELETE_MESSAGE,
                'code': SAFETY_REMEDIATION_PENDING_CODE,
            }, 409
        if safety_warning_send_in_progress(item):
            return {
                'error': (
                    'This safety violation cannot be deleted while a warning for it is '
                    'being sent. Try again in a moment.'
                ),
                'code': SAFETY_WARNING_IN_PROGRESS_CODE,
            }, 409
        if item.get('_etag'):
            cosmos_safety_container.delete_item(
                item=log_id,
                partition_key=log_id,
                etag=item.get('_etag'),
                match_condition=MatchConditions.IfNotModified,
            )
        else:
            cosmos_safety_container.delete_item(item=log_id, partition_key=log_id)
    except exceptions.CosmosResourceNotFoundError:
        return {'error': 'Safety violation not found'}, 404
    except CosmosAccessConditionFailedError:
        return _record_changed_body(), 409
    except Exception as e:
        log_event(
            '[SAFETY_LIFECYCLE] Failed to delete safety violation',
            {'safety_log_id': log_id, 'error_type': type(e).__name__},
            level=logging.ERROR,
        )
        return {'error': 'Failed to delete safety violation'}, 500

    audit_logged = log_review_lifecycle_action(
        'safety_violation',
        'delete',
        item,
        actor,
    )
    if not audit_logged:
        _log_safety_audit_failure(log_id, 'delete')

    return _safety_lifecycle_body('Safety violation permanently deleted.', audit_logged), 200


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
            status (str): Filter logs by status, or "open" for New and In-Review.
            action (str): Filter logs by action.
            archive (str): "active" (default) or "archived".
            search (str): Text matched against the message, notes, categories and user.
            user_id, category, severity, request, warning, restricted, date, days:
                the Review center's narrower filters, used by its dashboard links.
        Each log carries ``user_display_name`` and ``user_email``. Violations whose
        remediation request was decided or has expired are settled before they are listed.
        """
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            filters = _parse_safety_list_filters()
            logs, users = _load_admin_safety_logs(filters)
            paginated_items, page, page_size = _paginate_safety_logs(logs, page, page_size)
            _with_safety_user_names(paginated_items, users)

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

    @bp.route('/api/safety/logs/ids', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def get_safety_log_ids():
        """Return the ids of the violations matching the list filters, for "select all matching".

        Takes the same filters as GET /api/safety/logs. At most 500 ids are returned:
        ``total`` is how many matched, and ``capped`` says whether the cap applied.
        """
        try:
            filters = _parse_safety_list_filters()
            logs, _users = _load_admin_safety_logs(filters)
            return jsonify(cap_review_ids([log_item.get('id') for log_item in logs])), 200
        except ValueError:
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception as e:
            log_event('[SAFETY_VIOLATIONS] Matching violation ids could not be listed.', {
                'error_type': type(e).__name__,
            }, level=logging.ERROR)
            return jsonify({"error": "The matching violations could not be listed."}), 500

    @bp.route('/api/safety/logs/stats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def get_safety_log_stats():
        """Return aggregate safety violation statistics for the admin page.

        With ``days`` (7, 30 or 90) the response also carries the Review center dashboard:
        open, pending remediation, restricted users, warnings sent and acknowledged,
        unchecked chat content, violations per day by category, and the severity, action
        and repeat-user breakdowns for the window. Every other field is unchanged.
        """
        try:
            filter_status, filter_action, archive_state = _parse_safety_filters(
                include_archive_state=True,
            )
            days = parse_review_window(request.args.get('days'))
            logs = _query_safety_logs(
                filter_status=filter_status,
                filter_action=filter_action,
                archive_state=archive_state,
            )
            stats = _build_safety_stats(logs)
            if days:
                stats.update(_build_safety_window_stats(days))
            return jsonify(stats), 200
        except ValueError:
            logging.exception("Invalid request parameters in get_safety_log_stats")
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception:
            logging.exception("Error in get_safety_log_stats")
            return jsonify({"error": "Failed to retrieve safety stats."}), 500

    @bp.route('/api/safety/logs/<string:log_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def get_safety_log(log_id):
        """Return one violation for the Review center editor.

        Besides the stored record, the response carries ``etag`` (send it back with a save),
        the user's display name and email, whether the user's access is restricted now,
        and how many other violations the user has.
        """
        try:
            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Safety violation not found'}), 404
        except Exception as e:
            log_event('[SAFETY_VIOLATIONS] A violation could not be read.', {
                'safety_log_id': log_id,
                'error_type': type(e).__name__,
            }, level=logging.ERROR)
            return jsonify({'error': 'The violation could not be loaded.'}), 500

        item = reconcile_pending_safety_log(item)
        record = dict(item)
        # Read from the stored fields, before they are prepared for display.
        record['ai_suggestion'] = present_suggestion('safety', item)
        record.update(serialize_archive_metadata(item))
        present_safety_warning_send_state(record)
        record.update(serialize_safety_warning_state(record))
        user_id = item.get('user_id')
        users = resolve_review_users([user_id], include_access=True)
        entry = users.get(user_id) or {}
        record.update({
            'etag': item.get('_etag'),
            'user_display_name': entry.get('display_name') or None,
            'user_email': entry.get('email') or None,
            'user_access': entry.get('access'),
            'user_violation_count': _count_other_user_violations(user_id, log_id),
        })
        return jsonify(record), 200

    @bp.route('/api/safety/logs/export', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def export_safety_logs():
        """Export safety violation rows as CSV for the active filter set.

        Takes the same filters as GET /api/safety/logs, so an export matches the list.
        """
        try:
            filters = _parse_safety_list_filters()
            logs, _users = _load_admin_safety_logs(filters)
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

        Saving a suspension or block again with the same action requests nothing more unless
        the body carries ``reissue: true``. ``etag``, when sent, must match the stored record,
        or the save is refused with 409 ``record_changed``; it is then written on that version
        only, never merged onto a newer one. A suspension or block that can't be recorded on
        the violation, because another save moved it on meanwhile, is withdrawn and refused
        with 409 ``record_changed``.
        """
        data = request.get_json() or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'The request body must be an object.'}), 400
        return apply_safety_review_update(log_id, data)

    def apply_safety_review_update(log_id, data):
        """The single-record save, shared with the bulk ``update`` operation.

        Returns the same response the PATCH route sends, so a bulk update behaves exactly as
        saving that violation on its own would: a warning is sent at once, and a suspension
        or block creates an approval request.
        """
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

            if notes is not None and not isinstance(notes, str):
                return jsonify({'error': 'Notes must be text.'}), 400

            item = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
            expected_etag = data.get('etag')
            if expected_etag and item.get('_etag') != expected_etag:
                return jsonify(_record_changed_body()), 409
            # A request that was denied or has expired no longer locks the violation.
            item = reconcile_pending_safety_log(item)
            # What this save decides from. Its write lands only while that still holds, so it
            # never overwrites a warning being sent or recorded, or another request.
            unchanged_remediation = _remediation_unchanged(item)
            previous_action = str(item.get('action') or 'None')
            existing_request_status = str(item.get('action_request_status') or '').strip().lower()

            if action == SAFETY_ACTION_ESCALATE_LEGACY and previous_action != SAFETY_ACTION_ESCALATE_LEGACY:
                return jsonify({'error': SAFETY_ESCALATE_RETIRED_MESSAGE}), 400

            if action in SAFETY_REMEDIATION_ACTIONS and item.get("content_origin", "user") != "user":
                return jsonify({"error": "AI-generated findings cannot be used to warn or restrict a user."}), 400

            # Only what this save changes is written, so a concurrent change to anything else
            # on the violation survives it.
            review_updates = {}
            if not item.get("created_at"):
                item["created_at"] = datetime.utcnow().isoformat()
                review_updates['created_at'] = item['created_at']

            if existing_request_status == 'pending':
                return jsonify({
                    'error': SAFETY_PENDING_UPDATE_MESSAGE,
                    'code': SAFETY_REMEDIATION_PENDING_CODE,
                }), 409

            # While another save is sending a warning, the violation waits for it to finish.
            if safety_warning_send_in_progress(item):
                return jsonify({
                    'error': SAFETY_WARNING_SENDING_MESSAGE,
                    'code': SAFETY_WARNING_IN_PROGRESS_CODE,
                }), 409
            interrupted_send = is_interrupted_safety_warning_send(item)
            if interrupted_send:
                mark_interrupted_safety_warning_send(item)
                existing_request_status = 'failed'

            # A suspension or block is requested again only when the action changes or the
            # reviewer asks to re-issue it. Saving notes or a status on one already requested
            # or applied must not create a second approval request.
            restriction_requested = action in SAFETY_APPROVAL_REQUIRED_ACTIONS and (
                action != previous_action or data.get('reissue') is True
            )
            normalized_datetime_to_allow = None
            if action == SAFETY_REMEDIATION_WARNING or restriction_requested:
                normalized_datetime_to_allow = _validate_safety_remediation_request(action, datetime_to_allow)

            if status:
                item["status"] = status
                review_updates['status'] = status
            if action:
                item["action"] = action
                review_updates['action'] = action

            if notes is not None:
                item["notes"] = notes
                review_updates['notes'] = notes

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

            if restriction_requested:
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
                item['action_request_decided_at'] = None
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
            review_updates['last_updated'] = item['last_updated']

            if restriction_requested:
                request_updates = {field: item.get(field) for field in SAFETY_REQUEST_FIELDS if field in item}
                if interrupted_send:
                    # A save that stopped while sending a warning can never record it over this request.
                    request_updates.update({field: None for field in SAFETY_WARNING_SEND_CLAIM_FIELDS})
                try:
                    recorded = write_safety_log_updates(
                        log_id,
                        {**review_updates, **request_updates},
                        base_item=item,
                        guard=unchanged_remediation,
                        attempts=_write_attempts(expected_etag),
                    )
                except SafetyLogConflict:
                    recorded = None
                except Exception:
                    _withdraw_safety_request(approval, actor, log_id)
                    raise
                if recorded is None:
                    # The request exists, but the violation moved on -- another save sent a
                    # warning or created a request, or the version this save named changed --
                    # so nothing links the two. Withdraw it rather than leave it approvable.
                    _withdraw_safety_request(approval, actor, log_id)
                    return jsonify({
                        'error': SAFETY_REQUEST_NOT_RECORDED_MESSAGE,
                        'code': REVIEW_RECORD_CHANGED_CODE,
                    }), 409
            else:
                try:
                    written = write_safety_log_updates(
                        log_id,
                        review_updates,
                        base_item=item,
                        guard=unchanged_remediation,
                        attempts=_write_attempts(expected_etag),
                    )
                except SafetyLogConflict:
                    written = None
                if written is None:
                    return jsonify(_record_changed_body()), 409

            if restriction_requested:
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

            if action in SAFETY_APPROVAL_REQUIRED_ACTIONS:
                label = SAFETY_ACTION_LABELS[action]
                if existing_request_status == 'executed':
                    return jsonify({
                        'message': (
                            f'Safety log updated. The {label} was already applied, so it was not requested again. '
                            f'To request it again, select "Request this {label} again" and save.'
                        ),
                        'approval_required': False,
                        'remediation_already_applied': True,
                    }), 200
                return jsonify({
                    'message': (
                        f'Safety log updated. No new {label} was requested. '
                        f'To request it again, select "Request this {label} again" and save.'
                    ),
                    'approval_required': False,
                    'remediation_unchanged': True,
                    'remediation_status': existing_request_status or None,
                }), 200

            return jsonify({"message": "Safety log updated successfully."}), 200
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Safety violation not found'}), 404
        except SafetyLogConflict:
            return jsonify(_record_changed_body()), 409
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

    @bp.route('/api/safety/logs/bulk', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def bulk_update_safety_logs():
        """Apply up to 100 review operations to violations, each as its single route would.

        Body: ``{"operations": [{"id", "op", "etag"?, ...}]}``. ``update`` carries
        ``changes``, the same fields PATCH /api/safety/logs/<id> accepts, and behaves
        exactly as that save would: Warn user sends the warning, Suspend user and Block user
        create approval requests. ``archive`` carries ``archived``; ``delete`` carries
        nothing more. Each result repeats the single route's response with ``ok`` and
        ``status``, in request order; one failure never stops the others. An ``update`` with
        ``suggestion_id`` applies the violation's pending AI suggestion as the reviewer edited
        it, through that same save, and ``dismiss_suggestion`` dismisses one; a suggestion that
        is stale or no longer pending is refused with ``suggestion_stale`` or
        ``suggestion_not_pending``, and while AI assist is off both are refused with
        ``review_assistant_disabled``.
        """
        actor = _get_safety_actor_context()
        if not actor.get('id'):
            return jsonify({'error': 'No user ID found in session'}), 403
        try:
            operations = parse_review_bulk_operations(request.get_json(silent=True))
        except ReviewRequestError as error:
            return jsonify({'error': error.message, 'code': error.code}), error.status
        if any(operation.get('suggestion_id') for operation in operations):
            operations = refuse_suggestion_operations_while_off(
                operations, is_admin_review_assistant_enabled(get_settings()),
            )

        results = []
        for operation in operations:
            if operation.get('error'):
                results.append(review_bulk_result(
                    operation, operation['error']['body'], operation['error']['status'],
                ))
                continue
            if operation['op'] == 'update':
                changes = {key: value for key, value in operation['changes'].items() if key != 'etag'}
                if operation['etag']:
                    changes['etag'] = operation['etag']
                if operation.get('suggestion_id'):
                    body, status = apply_suggested_review(
                        cosmos_safety_container, 'safety', operation['id'], operation['suggestion_id'], changes, actor,
                        lambda checked, record_id=operation['id']: _response_parts(
                            apply_safety_review_update(record_id, checked),
                        ),
                    )
                else:
                    body, status = _response_parts(apply_safety_review_update(operation['id'], changes))
            elif operation['op'] == 'archive':
                body, status = _archive_safety_log(operation['id'], operation['archived'], actor, operation['etag'])
            elif operation['op'] == 'dismiss_suggestion':
                body, status = dismiss_review_suggestion(
                    cosmos_safety_container, 'safety', operation['id'], operation['suggestion_id'], actor,
                    operation['etag'],
                )
            else:
                body, status = _delete_safety_log(operation['id'], actor, operation['etag'])
            results.append(review_bulk_result(operation, body, status))

        summary = summarize_review_bulk_results(results)
        log_event('[SAFETY_VIOLATIONS] Bulk safety review applied.', {
            'actor_id': actor.get('id'),
            'operation_count': len(results),
            'succeeded': summary['succeeded'],
            'failed': summary['failed'],
        })
        return jsonify(summary), 200

    @bp.route('/api/admin/review/safety/assist', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def safety_review_assist():
        """Ask AI to suggest reviews for safety violations.

        Body: ``{"mode": "analyze" | "triage", "ids": [...]}``. ``analyze`` takes one violation
        and returns a suggested review for the editor's unsaved draft; nothing is stored.
        ``triage`` takes up to 10 violations and stores each suggestion on its violation for a
        reviewer to apply or dismiss. A violation held by a pending remediation request or a
        warning being sent is skipped. The model never warns, suspends or blocks anyone: those
        happen only when a reviewer applies a suggestion through the normal save, and a
        suspension or block still needs a second reviewer. Answers are never cached.
        """
        settings = get_settings()
        actor = _get_safety_actor_context()
        if not is_admin_review_assistant_enabled(settings):
            return review_assist_error_response(ReviewAssistError('review_assistant_disabled'), user_id=actor.get('id'))
        store = ReviewRecordStore(
            section='safety',
            container=cosmos_safety_container,
            replace=lambda record_id, mutate, base_item: replace_review_record(
                cosmos_safety_container, record_id, mutate, base_item=base_item,
            ),
            conflict_error=ReviewRecordConflict,
            prepare=reconcile_pending_safety_log,
            is_locked=lambda record: (
                _safety_request_state(record) == 'pending' or safety_warning_send_in_progress(record)
            ),
        )
        return handle_review_assist_request(
            section='safety',
            actor=actor,
            settings=settings,
            store=store,
            client_factory=lambda: _review_assist_client(settings),
        )

    @bp.route('/api/safety/logs/<string:log_id>/archive', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def archive_safety_log(log_id):
        """Archive or unarchive a safety violation record.

        ``etag``, when sent, must match the stored record or 409 ``record_changed`` is returned.
        """
        data = request.get_json() or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'The request body must be an object.'}), 400
        body, status = _archive_safety_log(
            log_id,
            data.get('archived'),
            _get_safety_actor_context(),
            data.get('etag') if isinstance(data.get('etag'), str) else None,
        )
        return jsonify(body), status

    @bp.route('/api/safety/logs/<string:log_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @safety_violation_admin_required
    @content_checks_report_enabled
    def delete_safety_log(log_id):
        """Permanently delete a safety violation without deleting its audit history."""
        body, status = _delete_safety_log(log_id, _get_safety_actor_context())
        return jsonify(body), status
        
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
            # Only the user's own fields, merged onto a fresh copy after a conflict, so a
            # reviewer saving the same violation at that moment is never overwritten.
            write_safety_log_updates(
                log_id,
                {field: item.get(field) for field in ('user_notes', 'created_at', 'last_updated') if field in item},
                base_item=item,
                guard=lambda current: current.get("user_id") == user_id,
            )

            return jsonify({"message": "Safety log updated successfully."}), 200
        except SafetyLogConflict:
            return jsonify({"error": "The content-check record changed while it was being saved. Try again."}), 409
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
