# functions_safety_remediation.py

"""Helpers for safety violation remediation actions and notifications."""

import copy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from config import cosmos_approvals_container, cosmos_safety_container
from functions_access_restriction import (
    ACCESS_RESTRICTION_KIND_BLOCKED,
    ACCESS_RESTRICTION_KIND_SUSPENDED,
    ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
    build_access_restriction_notice,
    parse_access_restore_time,
)
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_notifications import create_notification, mark_notification_read
from functions_settings import get_user_settings, update_user_settings


SAFETY_REMEDIATION_WARNING = 'WarnUser'
SAFETY_REMEDIATION_SUSPEND = 'SuspendUser'
SAFETY_REMEDIATION_BLOCK = 'BlockUser'

# Warnings the signed-in user still has to acknowledge, read at most this many at a time.
SAFETY_WARNING_PENDING_LIMIT = 20
SAFETY_WARNING_WRITE_ATTEMPTS = 3
SAFETY_WARNING_FALLBACK_MESSAGE = (
    'An administrator reviewed content you submitted and sent you this warning. '
    'Please review the acceptable use requirements before continuing.'
)

WARNING_ACKNOWLEDGMENT_PENDING = 'pending'
WARNING_ACKNOWLEDGMENT_ACKNOWLEDGED = 'acknowledged'
WARNING_ACKNOWLEDGMENT_NOT_TRACKED = 'not_tracked'

# A reviewer can warn about the same violation again, which replaces the warning on it. An
# acknowledgment of the earlier one is refused with this code rather than recorded against
# a warning the user has not read.
SAFETY_WARNING_REPLACED_CODE = 'safety_warning_replaced'
SAFETY_WARNING_REPLACED_MESSAGE = (
    'A newer warning replaced this one. Read the newer warning, then acknowledge it.'
)

# A save claims the violation before it sends a warning, so of two overlapping saves -- a
# double-click, or two reviewers -- only one sends. While the claim is held the violation is
# 'sending', which never counts as a warning to acknowledge. A claim older than the time to
# live is from a save that stopped before it finished: it no longer blocks, and it reads as
# a failed send, which saving the warning again retries.
SAFETY_WARNING_SENDING_STATUS = 'sending'
SAFETY_WARNING_SEND_CLAIM_TTL = timedelta(minutes=5)
SAFETY_WARNING_SEND_CLAIM_FIELDS = ('warning_send_claim_id', 'warning_send_claimed_at')
SAFETY_WARNING_SEND_INTERRUPTED_MESSAGE = (
    'The save that was sending this warning did not finish, so it is not known whether the '
    'warning reached the user. Saving the warning again sends it again.'
)

# What a remediation request leaves on its violation. Pending locks the violation until the
# request is decided; every other state is settled and leaves the violation editable.
SAFETY_REQUEST_PENDING = 'pending'
SAFETY_REQUEST_EXECUTED = 'executed'
SAFETY_REQUEST_FAILED = 'failed'
SAFETY_REQUEST_DENIED = 'denied'
SAFETY_REQUEST_EXPIRED = 'expired'
SAFETY_REQUEST_STATUSES = (
    SAFETY_REQUEST_PENDING,
    SAFETY_REQUEST_EXECUTED,
    SAFETY_REQUEST_FAILED,
    SAFETY_REQUEST_DENIED,
    SAFETY_REQUEST_EXPIRED,
)
# A pending approval request is removed by Cosmos TTL this long after it was created
# (functions_approvals.TTL_AUTO_DENY_SECONDS, which cannot be imported here without a
# cycle). A violation whose request can no longer be found is settled as expired only once
# the request could no longer exist, so a request that is slow to appear in a query never
# unlocks its violation.
SAFETY_APPROVAL_LIFETIME = timedelta(days=3)
SAFETY_LOG_WRITE_ATTEMPTS = 3
SAFETY_REQUEST_LOOKUP_BATCH = 100
SAFETY_REQUEST_FAILED_MESSAGE = (
    'The approved action could not be completed. Open the approval request for details.'
)
SAFETY_REQUEST_NOT_CURRENT_MESSAGE = (
    'The safety violation is no longer waiting on this request, so nothing was changed. '
    'Open the violation to decide what to do now.'
)
# What a remediation decision rests on: the request the violation waits on, a warning being
# sent, and the warning last recorded. A reviewer's save is written only while these are as
# the save read them, so it never lands on another save's warning or request.
SAFETY_REMEDIATION_STATE_FIELDS = (
    'action_request_status',
    'action_request_id',
    'warning_send_claim_id',
    'warning_notification_id',
    'warning_issued_at',
)


class SafetyLogConflict(Exception):
    """A violation kept changing while it was being written."""


def get_safety_log_item(log_id: str) -> Dict[str, Any]:
    """Return a safety log item by its document id."""
    return cosmos_safety_container.read_item(item=log_id, partition_key=log_id)


def write_safety_log_updates(
    log_id: str,
    updates: Dict[str, Any],
    *,
    base_item: Optional[Dict[str, Any]] = None,
    guard: Optional[Callable[[Dict[str, Any]], bool]] = None,
    attempts: int = SAFETY_LOG_WRITE_ATTEMPTS,
) -> Optional[Dict[str, Any]]:
    """Merge ``updates`` onto the stored violation with an ETag-conditional replace.

    The first attempt applies them to ``base_item``, the copy the caller already read, when
    there is one; after a conflict, to a fresh read. Only the named fields are written, so a
    concurrent write to any other field, such as the user acknowledging a warning, survives.
    ``guard(current)`` can refuse a fresh read, for example one that has since moved on to
    another request; nothing is written then and None is returned. Raises
    ``SafetyLogConflict`` when every attempt conflicts, and lets a missing record's
    ``CosmosResourceNotFoundError`` through.
    """
    current = base_item
    for _attempt in range(max(1, attempts)):
        if current is None:
            current = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
            if guard is not None and not guard(current):
                return None
        merged = copy.deepcopy(current)
        merged.update(copy.deepcopy(updates or {}))
        etag = current.get('_etag')
        try:
            if etag:
                stored = cosmos_safety_container.replace_item(
                    item=log_id,
                    body=merged,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            else:
                stored = cosmos_safety_container.upsert_item(merged)
        except cosmos_exceptions.CosmosAccessConditionFailedError:
            current = None
            continue
        return stored if isinstance(stored, dict) else merged
    raise SafetyLogConflict(f'Safety violation {log_id} changed while it was being written.')


def update_safety_log_action_state(log_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Persist remediation state changes onto a safety log item.

    Only the named fields are written, conditionally on the stored version and again on a
    fresh copy after a conflict, so a concurrent write is never overwritten.
    """
    fields = dict(updates or {})
    fields['last_updated'] = datetime.utcnow().isoformat()
    return write_safety_log_updates(log_id, fields)


def _safety_request_status(log_item: Dict[str, Any]) -> str:
    return str((log_item or {}).get('action_request_status') or '').strip().lower()


def _safety_request_still_pending(log_item: Dict[str, Any], approval_id: Optional[str]) -> bool:
    """True while a violation is still waiting on this very remediation request."""
    return (
        bool(approval_id)
        and _safety_request_status(log_item) == SAFETY_REQUEST_PENDING
        and log_item.get('action_request_id') == approval_id
    )


def safety_log_awaits_request(log_item: Optional[Dict[str, Any]], approval_id: Optional[str]) -> bool:
    """True while a violation is waiting on exactly this remediation request.

    An approved request is carried out only then. One its violation has moved on from --
    withdrawn, replaced by a newer request, or settled -- must not change the user's access.
    """
    return _safety_request_still_pending(log_item or {}, approval_id)


def safety_remediation_state(log_item: Optional[Dict[str, Any]]) -> Tuple[Any, ...]:
    """The parts of a violation a remediation decision rests on, to compare a later read with."""
    log_item = log_item or {}
    return tuple(log_item.get(field) for field in SAFETY_REMEDIATION_STATE_FIELDS)


def release_safety_log_after_approval_decision(
    approval: Dict[str, Any],
    outcome: str,
) -> Optional[Dict[str, Any]]:
    """Record that a violation's remediation request was denied or expired, unlocking it.

    Called whenever a warn, suspend or block request is denied by a reviewer or by the
    expiry sweep. Only a violation still waiting on this very request changes: one that
    has since moved on to a newer request, or was already settled, is left as it is.
    Returns the stored violation, or None when nothing changed.
    """
    if outcome not in (SAFETY_REQUEST_DENIED, SAFETY_REQUEST_EXPIRED):
        raise ValueError(f'Unsupported remediation request outcome: {outcome}')
    approval = approval if isinstance(approval, dict) else {}
    metadata = approval.get('metadata') if isinstance(approval.get('metadata'), dict) else {}
    log_id = str(metadata.get('safety_log_id') or '').strip()
    approval_id = approval.get('id')
    if not log_id or not approval_id:
        return None

    now_text = datetime.utcnow().isoformat()
    updates = {
        'action_request_status': outcome,
        'action_request_decided_at': approval.get('approved_at') or now_text,
        'action_execution_error': None,
        'last_updated': now_text,
    }
    try:
        stored = write_safety_log_updates(
            log_id,
            updates,
            guard=lambda current: _safety_request_still_pending(current, approval_id),
        )
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return None
    if stored is not None:
        log_event(
            '[SAFETY_REMEDIATION] A violation was released after its remediation request was decided.',
            extra={
                'safety_log_id': log_id,
                'approval_id': approval_id,
                'request_type': approval.get('request_type'),
                'outcome': outcome,
            },
        )
    return stored


def _settled_request_outcome(
    log_item: Dict[str, Any],
    approval: Optional[Dict[str, Any]],
    now: datetime,
) -> Optional[str]:
    """What a pending violation's request has become, or None while it may still be decided."""
    if approval is None:
        requested_at = parse_access_restore_time(log_item.get('action_requested_at'))
        if requested_at is None or now - requested_at >= SAFETY_APPROVAL_LIFETIME:
            return SAFETY_REQUEST_EXPIRED
        return None
    return {
        'denied': SAFETY_REQUEST_DENIED,
        'auto_denied': SAFETY_REQUEST_EXPIRED,
        'expired': SAFETY_REQUEST_EXPIRED,
        'executed': SAFETY_REQUEST_EXECUTED,
        'failed': SAFETY_REQUEST_FAILED,
    }.get(str(approval.get('status') or '').strip().lower())


def _settled_request_updates(outcome: str, approval: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    approval = approval or {}
    now_text = datetime.utcnow().isoformat()
    updates = {'action_request_status': outcome, 'last_updated': now_text}
    if outcome in (SAFETY_REQUEST_DENIED, SAFETY_REQUEST_EXPIRED):
        updates['action_request_decided_at'] = approval.get('approved_at') or now_text
        updates['action_execution_error'] = None
    elif outcome == SAFETY_REQUEST_EXECUTED:
        # Recorded as executed only: whatever the request sent was sent by the approval
        # path, so no warning is raised for acknowledgment here.
        updates['action_approved_at'] = approval.get('approved_at')
        updates['action_executed_at'] = approval.get('executed_at') or now_text
        updates['action_execution_error'] = None
    elif outcome == SAFETY_REQUEST_FAILED:
        updates['action_approved_at'] = approval.get('approved_at')
        updates['action_execution_error'] = SAFETY_REQUEST_FAILED_MESSAGE
    return updates


def _lookup_remediation_requests(approval_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Return ``{approval_id: request}`` for the remediation requests that still exist."""
    ids = [value for value in dict.fromkeys(approval_ids or []) if isinstance(value, str) and value]
    found: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(ids), SAFETY_REQUEST_LOOKUP_BATCH):
        batch = ids[start:start + SAFETY_REQUEST_LOOKUP_BATCH]
        rows = cosmos_approvals_container.query_items(
            query=(
                "SELECT c.id, c.status, c.request_type, c.approved_at, c.executed_at, "
                "c.metadata.safety_log_id AS safety_log_id FROM c WHERE ARRAY_CONTAINS(@ids, c.id)"
            ),
            parameters=[{'name': '@ids', 'value': batch}],
            enable_cross_partition_query=True,
        )
        for row in rows:
            if isinstance(row, dict) and row.get('id') in batch:
                found[row['id']] = row
    return found


def reconcile_pending_safety_logs(
    logs: Iterable[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Settle violations still marked pending whose remediation request was decided or is gone.

    One lookup covers every pending request in ``logs``. A request that was denied or has
    expired unlocks its violation; one that executed or failed is recorded as such. A request
    that is still pending, or approved and still running, keeps its violation locked, and so
    does a lookup that fails. Returns the list with each settled violation replaced by its
    stored copy.
    """
    logs = list(logs or [])
    pending = [
        (index, log_item) for index, log_item in enumerate(logs)
        if isinstance(log_item, dict)
        and _safety_request_status(log_item) == SAFETY_REQUEST_PENDING
        and log_item.get('action_request_id')
    ]
    if not pending:
        return logs
    try:
        requests = _lookup_remediation_requests(log_item['action_request_id'] for _index, log_item in pending)
    except Exception as exc:
        log_event(
            '[SAFETY_REMEDIATION] Pending remediation requests could not be looked up.',
            extra={'request_count': len(pending), 'error_type': type(exc).__name__},
            level=logging.WARNING,
        )
        return logs

    current_time = now or datetime.now(timezone.utc)
    for index, log_item in pending:
        approval_id = log_item['action_request_id']
        approval = requests.get(approval_id)
        if approval is not None and approval.get('safety_log_id') not in (None, log_item.get('id')):
            # A request that names another violation is never used to settle this one.
            continue
        outcome = _settled_request_outcome(log_item, approval, current_time)
        if outcome is None:
            continue
        try:
            stored = write_safety_log_updates(
                log_item['id'],
                _settled_request_updates(outcome, approval),
                base_item=log_item,
                guard=lambda current, request_id=approval_id: _safety_request_still_pending(current, request_id),
            )
        except (SafetyLogConflict, cosmos_exceptions.CosmosResourceNotFoundError):
            continue
        except Exception as exc:
            log_event(
                '[SAFETY_REMEDIATION] A pending violation could not be settled.',
                extra={'safety_log_id': log_item.get('id'), 'error_type': type(exc).__name__},
                level=logging.WARNING,
            )
            continue
        if stored is not None:
            logs[index] = stored
            log_event(
                '[SAFETY_REMEDIATION] A pending violation was settled from its remediation request.',
                extra={
                    'safety_log_id': log_item.get('id'),
                    'approval_id': approval_id,
                    'outcome': outcome,
                    'request_found': approval is not None,
                },
            )
    return logs


def reconcile_pending_safety_log(log_item: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Settle one violation, as ``reconcile_pending_safety_logs`` does for a list."""
    return reconcile_pending_safety_logs([log_item], now=now)[0]


def resolve_safety_target_user(user_id: str) -> Dict[str, str]:
    """Resolve target user display information from the server-side user settings store."""
    user_doc = get_user_settings(user_id, allow_cross_user=True) or {}
    email = str(user_doc.get('email') or '').strip()
    display_name = str(user_doc.get('display_name') or '').strip()

    return {
        'user_id': user_id,
        'email': email,
        'display_name': display_name or email or user_id,
    }


def _format_triggered_categories_for_notification(safety_log: Dict[str, Any]) -> str:
    categories = safety_log.get('triggered_categories') or []
    formatted_categories = []
    for category in categories:
        category_name = str(category.get('category') or '').strip()
        severity = category.get('severity')
        if category_name and severity is not None:
            formatted_categories.append(f"{category_name}(s={severity})")
        elif category_name:
            formatted_categories.append(category_name)

    return ', '.join(formatted_categories)


def _default_notification_title(action: str) -> str:
    if action == SAFETY_REMEDIATION_WARNING:
        return 'Safety Violation Warning'
    if action == SAFETY_REMEDIATION_SUSPEND:
        return 'Account Suspension Notice'
    if action == SAFETY_REMEDIATION_BLOCK:
        return 'Account Access Blocked'
    return 'Safety Violation Notice'


def _default_notification_message(
    action: str,
    safety_log: Dict[str, Any],
    datetime_to_allow: Optional[str],
) -> str:
    details = [
        'A safety review has been completed for recent activity in your workspace.',
        f"Violation ID: {safety_log.get('id') or 'Unknown'}",
    ]

    categories = _format_triggered_categories_for_notification(safety_log)
    if categories:
        details.append(f"Triggered categories: {categories}")

    if action == SAFETY_REMEDIATION_WARNING:
        details.append('Action taken: Warning issued. Please review our acceptable use requirements before continuing.')
    elif action == SAFETY_REMEDIATION_SUSPEND:
        details.append('Action taken: Your access has been temporarily suspended pending the date below.')
        if datetime_to_allow:
            details.append(f"Access restores automatically after: {datetime_to_allow}")
    elif action == SAFETY_REMEDIATION_BLOCK:
        details.append('Action taken: Your access has been blocked with no automatic restore date.')

    admin_notes = str(safety_log.get('notes') or '').strip()
    if admin_notes:
        details.append(f"Admin notes: {admin_notes}")

    return '\n'.join(details)


def execute_safety_violation_action(
    action: str,
    safety_log: Dict[str, Any],
    notification_title: str,
    notification_message: str,
    datetime_to_allow: Optional[str],
    actor: Dict[str, str],
) -> Dict[str, Any]:
    """Execute a warning or access restriction for a safety violation."""
    if safety_log.get("content_origin", "user") != "user":
        raise ValueError("AI-generated findings cannot be used to warn or restrict a user.")
    target_user_id = str(safety_log.get('user_id') or '').strip()
    if not target_user_id:
        raise ValueError('Safety violation is missing a target user id')

    target_user = resolve_safety_target_user(target_user_id)
    normalized_title = str(notification_title or '').strip() or _default_notification_title(action)
    normalized_message = str(notification_message or '').strip() or _default_notification_message(
        action,
        safety_log,
        datetime_to_allow,
    )

    if action == SAFETY_REMEDIATION_SUSPEND:
        if not datetime_to_allow:
            raise ValueError('Suspend user actions require a restore date and time')

        access_updated = update_user_settings(
            target_user_id,
            {
                'access': {
                    'status': 'deny',
                    'datetime_to_allow': datetime_to_allow,
                    # What the user was told, so the Access restricted screen can show it.
                    'notice': build_access_restriction_notice(
                        ACCESS_RESTRICTION_KIND_SUSPENDED,
                        normalized_title,
                        normalized_message,
                        until=datetime_to_allow,
                        reference_id=safety_log.get('id'),
                        source=ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
                    ),
                }
            },
            allow_cross_user=True,
        )
        if not access_updated:
            raise RuntimeError('Failed to apply the temporary access restriction')
        notification_type = 'safety_violation_suspension'
        result_message = f"User access suspended until {datetime_to_allow}."
    elif action == SAFETY_REMEDIATION_BLOCK:
        access_updated = update_user_settings(
            target_user_id,
            {
                'access': {
                    'status': 'deny',
                    'datetime_to_allow': None,
                    'notice': build_access_restriction_notice(
                        ACCESS_RESTRICTION_KIND_BLOCKED,
                        normalized_title,
                        normalized_message,
                        reference_id=safety_log.get('id'),
                        source=ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
                    ),
                }
            },
            allow_cross_user=True,
        )
        if not access_updated:
            raise RuntimeError('Failed to apply the permanent access block')
        notification_type = 'safety_violation_block'
        result_message = 'User access blocked indefinitely.'
    elif action == SAFETY_REMEDIATION_WARNING:
        notification_type = 'safety_violation_warning'
        result_message = 'Warning notification sent to the user.'
    else:
        raise ValueError(f'Unsupported safety remediation action: {action}')

    notification = create_notification(
        user_id=target_user_id,
        notification_type=notification_type,
        title=normalized_title,
        message=normalized_message,
        link_url='/profile?tab=violations',
        link_context={
            'tab': 'violations',
            'violation_id': safety_log.get('id'),
        },
        metadata={
            'safety_log_id': safety_log.get('id'),
            'violation_action': action,
            'target_user_id': target_user_id,
            'actor_id': actor.get('id'),
            'actor_email': actor.get('email'),
            'datetime_to_allow': datetime_to_allow,
        },
    )

    if notification is None:
        raise RuntimeError('Failed to create the user notification')

    log_event(
        '[SAFETY_REMEDIATION] Executed safety remediation action',
        {
            'safety_log_id': safety_log.get('id'),
            'violation_action': action,
            'target_user_id': target_user_id,
            'target_user_email': target_user.get('email'),
            'datetime_to_allow': datetime_to_allow,
            'actor_id': actor.get('id'),
            'actor_email': actor.get('email'),
        },
    )
    debug_print(
        f"[SAFETY_REMEDIATION] Executed {action} for {target_user_id} on safety log {safety_log.get('id')}"
    )

    return {
        'success': True,
        'message': result_message,
        'notification_id': notification.get('id'),
        'notification_title': normalized_title,
        'notification_message': normalized_message,
        'target_user': target_user,
    }


def build_safety_action_execution_updates(
    action: str,
    execution_result: Dict[str, Any],
    executed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the safety log fields that record an executed remediation action.

    An executed warning is also marked as needing the user's acknowledgment, with the title
    and message the user was sent, so it can be shown to them until they acknowledge it.
    Warnings executed before this was recorded carry none of these fields and are never
    shown again.
    """
    executed_at = executed_at or datetime.now(timezone.utc).isoformat()
    updates = {
        'action_request_status': 'executed',
        'action_executed_at': executed_at,
        'action_execution_error': None,
    }
    if action == SAFETY_REMEDIATION_WARNING:
        result = execution_result or {}
        updates.update({
            'warning_requires_acknowledgment': True,
            'warning_notification_id': result.get('notification_id'),
            'warning_title': result.get('notification_title'),
            'warning_message': result.get('notification_message'),
            'warning_issued_at': executed_at,
            'warning_acknowledged_at': None,
        })
    return updates


def _request_status(log_item: Dict[str, Any]) -> str:
    return str(log_item.get('action_request_status') or '').strip().lower()


def safety_warning_send_in_progress(log_item: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True while a save is sending a warning on this violation, so other writes must wait.

    A claim older than ``SAFETY_WARNING_SEND_CLAIM_TTL`` either way, or one whose time can't
    be read, is from a save that stopped before it finished, and does not block.
    """
    if _request_status(log_item) != SAFETY_WARNING_SENDING_STATUS:
        return False
    # The claim time is stored as an ISO UTC time, read the same way as a restore time.
    claimed_at = parse_access_restore_time(log_item.get('warning_send_claimed_at'))
    if claimed_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return abs(now - claimed_at) < SAFETY_WARNING_SEND_CLAIM_TTL


def is_interrupted_safety_warning_send(log_item: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True for a violation left 'sending' by a save that stopped before it finished."""
    return (
        _request_status(log_item) == SAFETY_WARNING_SENDING_STATUS
        and not safety_warning_send_in_progress(log_item, now)
    )


def mark_interrupted_safety_warning_send(log_item: Dict[str, Any]) -> None:
    """Treat an unfinished send as a failed one, in place, so saving the warning retries it."""
    log_item['action_request_status'] = 'failed'
    log_item['action_execution_error'] = SAFETY_WARNING_SEND_INTERRUPTED_MESSAGE
    for field in SAFETY_WARNING_SEND_CLAIM_FIELDS:
        log_item.pop(field, None)


def present_safety_warning_send_state(log_item: Dict[str, Any], now: Optional[datetime] = None) -> None:
    """Prepare a listed violation's send state for display, in place.

    The claim's id and time are internal. An unfinished send reads as failed, as the next
    save records it, rather than as sending forever.
    """
    if is_interrupted_safety_warning_send(log_item, now):
        mark_interrupted_safety_warning_send(log_item)
    for field in SAFETY_WARNING_SEND_CLAIM_FIELDS:
        log_item.pop(field, None)


def _replace_safety_log_if_unchanged(body: Dict[str, Any]) -> Dict[str, Any]:
    """Write a safety log only if it is still the version that was read."""
    etag = body.get('_etag')
    if not etag:
        # Cosmos DB always returns an ETag; only a store without them lands here.
        stored = cosmos_safety_container.upsert_item(body)
    else:
        stored = cosmos_safety_container.replace_item(
            item=body['id'],
            body=body,
            etag=etag,
            match_condition=MatchConditions.IfNotModified,
        )
    return stored if isinstance(stored, dict) else body


def claim_safety_warning_send(log_item: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Mark a violation as sending a warning, unless it changed since this save read it.

    The write is conditional on the ETag the save read, so of two saves that read the same
    version only one claims it. The other gets ``CosmosAccessConditionFailedError`` and must
    send nothing. The claim also stores the rest of the save's changes. Returns the stored
    record and the claim's id.
    """
    claim_id = str(uuid.uuid4())
    body = dict(log_item)
    body.update({
        'action_request_status': SAFETY_WARNING_SENDING_STATUS,
        'warning_send_claim_id': claim_id,
        'warning_send_claimed_at': datetime.now(timezone.utc).isoformat(),
    })
    return _replace_safety_log_if_unchanged(body), claim_id


def record_safety_warning_send(
    claimed: Dict[str, Any],
    claim_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Store what a claimed send did on its violation, and release the claim.

    The write is conditional on the claimed version. When another writer changed the record
    meanwhile but kept the claim -- archiving it, for example -- the outcome is written on
    the latest version instead. Returns the stored record, or None when the claim was lost:
    the record was deleted, or replaced without the claim, so nothing could be recorded.
    """
    log_id = claimed.get('id')
    current = claimed
    for attempt in range(SAFETY_WARNING_WRITE_ATTEMPTS):
        if attempt:
            try:
                current = cosmos_safety_container.read_item(item=log_id, partition_key=log_id)
            except cosmos_exceptions.CosmosResourceNotFoundError:
                return None
        if current.get('warning_send_claim_id') != claim_id:
            return None
        body = dict(current)
        body.update(updates)
        for field in SAFETY_WARNING_SEND_CLAIM_FIELDS:
            body.pop(field, None)
        body['last_updated'] = datetime.utcnow().isoformat()
        try:
            return _replace_safety_log_if_unchanged(body)
        except cosmos_exceptions.CosmosAccessConditionFailedError:
            continue
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None
    return None


def serialize_safety_warning_state(log_item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a record's warning acknowledgment state for reviewers and the warned user.

    ``warning_acknowledgment_status`` is None unless the record holds an executed warning;
    then it is ``pending``, ``acknowledged`` or ``not_tracked`` for a warning sent before
    acknowledgment was recorded.
    """
    executed_warning = (
        log_item.get('action') == SAFETY_REMEDIATION_WARNING
        and str(log_item.get('action_request_status') or '').strip().lower() == 'executed'
    )
    requires_acknowledgment = log_item.get('warning_requires_acknowledgment') is True
    status = None
    if executed_warning:
        if not requires_acknowledgment:
            status = WARNING_ACKNOWLEDGMENT_NOT_TRACKED
        elif log_item.get('warning_acknowledged_at'):
            status = WARNING_ACKNOWLEDGMENT_ACKNOWLEDGED
        else:
            status = WARNING_ACKNOWLEDGMENT_PENDING
    return {
        'warning_requires_acknowledgment': requires_acknowledgment,
        'warning_issued_at': log_item.get('warning_issued_at'),
        'warning_acknowledged_at': log_item.get('warning_acknowledged_at'),
        'warning_acknowledgment_status': status,
    }


def _user_safe_categories(log_item: Dict[str, Any]) -> List[Dict[str, Any]]:
    categories = []
    for entry in log_item.get('triggered_categories') or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('category') or '').strip()
        if not name:
            continue
        severity = entry.get('severity')
        if isinstance(severity, bool) or not isinstance(severity, (int, float)):
            severity = None
        categories.append({'category': name, 'severity': severity})
    return categories


def _warning_issued_at(log_item: Dict[str, Any]) -> Optional[str]:
    """When the warning now on a violation was sent. Each warning sent on it has its own."""
    return log_item.get('warning_issued_at') or log_item.get('action_executed_at')


def serialize_safety_warning_for_user(log_item: Dict[str, Any]) -> Dict[str, Any]:
    """Return only what the warned user may see of a warning: what they were sent, and when."""
    return {
        'id': log_item.get('id'),
        'violation_id': log_item.get('id'),
        'title': str(log_item.get('warning_title') or '').strip()
        or _default_notification_title(SAFETY_REMEDIATION_WARNING),
        'message': str(log_item.get('warning_message') or '').strip() or SAFETY_WARNING_FALLBACK_MESSAGE,
        'issued_at': _warning_issued_at(log_item),
        'acknowledged_at': log_item.get('warning_acknowledged_at'),
        'triggered_categories': _user_safe_categories(log_item),
    }


def _is_acknowledgeable_warning(log_item: Dict[str, Any], user_id: str) -> bool:
    """True for the caller's own executed warning that asks for acknowledgment."""
    return (
        bool(user_id)
        and log_item.get('user_id') == user_id
        and log_item.get('content_origin', 'user') == 'user'
        and log_item.get('action') == SAFETY_REMEDIATION_WARNING
        and str(log_item.get('action_request_status') or '').strip().lower() == 'executed'
        and log_item.get('warning_requires_acknowledgment') is True
    )


_PENDING_WARNING_CONDITIONS = (
    "c.user_id = @user_id "
    "AND c.action = @action "
    "AND c.action_request_status = 'executed' "
    "AND c.warning_requires_acknowledgment = true "
    "AND (NOT IS_DEFINED(c.warning_acknowledged_at) OR IS_NULL(c.warning_acknowledged_at)) "
    "AND (NOT IS_DEFINED(c.content_origin) OR c.content_origin = 'user')"
)


def _pending_warning_parameters(user_id: str) -> List[Dict[str, Any]]:
    return [
        {'name': '@user_id', 'value': user_id},
        {'name': '@action', 'value': SAFETY_REMEDIATION_WARNING},
    ]


def count_pending_safety_warnings(user_id: str) -> int:
    """Return how many warnings the user still has to acknowledge.

    V2 bootstrap carries this so the interface only asks for the warnings themselves when
    there are some, rather than on every page load.
    """
    if not user_id:
        return 0
    values = cosmos_safety_container.query_items(
        query=f"SELECT VALUE COUNT(1) FROM c WHERE {_PENDING_WARNING_CONDITIONS}",
        parameters=_pending_warning_parameters(user_id),
        enable_cross_partition_query=True,
    )
    return sum(int(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool))


def list_pending_safety_warnings(user_id: str) -> List[Dict[str, Any]]:
    """Return the caller's warnings that still need acknowledgment, oldest first."""
    if not user_id:
        return []
    query = (
        "SELECT c.id, c.user_id, c.content_origin, c.action, c.action_request_status, "
        "c.action_executed_at, c.warning_requires_acknowledgment, c.warning_acknowledged_at, "
        "c.warning_title, c.warning_message, c.warning_issued_at, c.triggered_categories "
        f"FROM c WHERE {_PENDING_WARNING_CONDITIONS}"
    )
    items = list(cosmos_safety_container.query_items(
        query=query,
        parameters=_pending_warning_parameters(user_id),
        enable_cross_partition_query=True,
    ))
    pending = [
        item for item in items
        if _is_acknowledgeable_warning(item, user_id) and not item.get('warning_acknowledged_at')
    ]
    pending.sort(key=lambda item: str(item.get('warning_issued_at') or item.get('action_executed_at') or ''))
    return [serialize_safety_warning_for_user(item) for item in pending[:SAFETY_WARNING_PENDING_LIMIT]]


def _mark_warning_notification_read(log_item: Dict[str, Any], user_id: str) -> None:
    """Mark the bell notification that delivered the warning as read for its recipient."""
    notification_id = str(log_item.get('warning_notification_id') or '').strip()
    if not notification_id:
        return
    if not mark_notification_read(notification_id, user_id):
        log_event(
            '[SAFETY_WARNINGS] The warning notification could not be marked read.',
            extra={'safety_log_id': log_item.get('id'), 'user_id': user_id},
            level=logging.WARNING,
        )


def acknowledge_safety_warning(
    log_id: str,
    user_id: str,
    issued_at: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Record that the signed-in user acknowledged their own warning.

    Returns ``(status, warning)``. ``status`` is ``acknowledged``, ``already_acknowledged``,
    ``replaced`` or ``not_found``. A record that doesn't exist, belongs to someone else, or
    isn't a warning that asks for acknowledgment is ``not_found``, so the answer never
    confirms another user's record. ``issued_at`` is when the warning the user read was
    sent: when the violation now holds a warning sent at another time, the one they read was
    replaced, and nothing is recorded (``replaced``). Without it, the warning now on the
    violation is acknowledged. The write is conditional on the stored ETag and retried, so a
    reviewer saving the record at the same moment is never overwritten.
    """
    normalized_id = str(log_id or '').strip()
    if not normalized_id or not user_id:
        return 'not_found', None
    expected_issued_at = str(issued_at or '').strip()

    for _attempt in range(SAFETY_WARNING_WRITE_ATTEMPTS):
        try:
            item = cosmos_safety_container.read_item(item=normalized_id, partition_key=normalized_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return 'not_found', None
        if not _is_acknowledgeable_warning(item, user_id):
            return 'not_found', None
        if expected_issued_at and expected_issued_at != str(_warning_issued_at(item) or '').strip():
            return 'replaced', None
        if item.get('warning_acknowledged_at'):
            _mark_warning_notification_read(item, user_id)
            return 'already_acknowledged', serialize_safety_warning_for_user(item)

        item['warning_acknowledged_at'] = datetime.now(timezone.utc).isoformat()
        etag = item.get('_etag')
        try:
            if etag:
                stored = cosmos_safety_container.replace_item(
                    item=normalized_id,
                    body=item,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            else:
                stored = cosmos_safety_container.upsert_item(item)
        except cosmos_exceptions.CosmosAccessConditionFailedError:
            continue

        stored = stored if isinstance(stored, dict) else item
        _mark_warning_notification_read(stored, user_id)
        log_event(
            '[SAFETY_WARNINGS] Safety warning acknowledged by its recipient.',
            extra={
                'safety_log_id': normalized_id,
                'user_id': user_id,
                'warning_issued_at': stored.get('warning_issued_at'),
            },
        )
        return 'acknowledged', serialize_safety_warning_for_user(stored)

    raise cosmos_exceptions.CosmosAccessConditionFailedError(
        status_code=412,
        message='The safety warning changed while it was being acknowledged.',
    )
