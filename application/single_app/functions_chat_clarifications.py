# functions_chat_clarifications.py
"""Durable server-authored chat clarification checkpoints."""

import copy
import hashlib
import hmac
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions

from functions_chat_capability_choices import CapabilityChoiceError


CHAT_CLARIFICATION_VERSION = 1
DEFAULT_CHAT_CLARIFICATION_TTL_SECONDS = 86400
MAX_CHAT_CLARIFICATION_TTL_SECONDS = 604800
MAX_CHAT_CLARIFICATION_OPTIONS = 6
MAX_CHAT_CLARIFICATION_OPTION_CHARS = 120
MAX_CONDITIONAL_WRITE_ATTEMPTS = 3
CHAT_CLARIFICATION_RESPONSE_LEASE_SECONDS = 1800
CHAT_CLARIFICATION_CODES = frozenset({
    'ambiguous_reference',
    'document_targets_required',
    'jurisdiction_required',
    'output_format_required',
    'source_scope_required',
    'target_entity_required',
    'time_range_required',
})
CHAT_CLARIFICATION_QUESTIONS = {
    'ambiguous_reference': 'What does the referenced item mean in this request?',
    'document_targets_required': 'Which documents should I use?',
    'jurisdiction_required': 'Which jurisdiction applies?',
    'output_format_required': 'What output format do you want?',
    'source_scope_required': 'Where should I look for this information?',
    'target_entity_required': 'Which person, organization, or item should I use?',
    'time_range_required': 'What time range should I use?',
}
DEFAULT_CLARIFICATION_OPTION_CANDIDATES = {
    'output_format_required': [
        'Concise answer',
        'Detailed answer',
        'Table',
    ],
    'source_scope_required': [
        'My workspace',
        'Public web',
        'Both',
    ],
}


class ChatClarificationError(CapabilityChoiceError):
    """Raised when a durable clarification transition is invalid."""


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_timestamp(value):
    normalized = str(value or '').strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_identifier(value, field_name):
    normalized = str(value or '').strip()
    if not normalized or len(normalized) > 200:
        raise ChatClarificationError(
            f'{field_name} is required',
            code=f'invalid_{field_name}',
        )
    return normalized


def _normalize_options(values):
    normalized = []
    for raw_value in values if isinstance(values, list) else []:
        value = ' '.join(str(raw_value or '').split())[
            :MAX_CHAT_CLARIFICATION_OPTION_CHARS
        ]
        if value and value not in normalized:
            normalized.append(value)
        if len(normalized) >= MAX_CHAT_CLARIFICATION_OPTIONS:
            break
    return normalized


def chat_clarification_response_matches(clarification, response_text):
    """Return whether text matches the stored response hash."""
    if not isinstance(clarification, Mapping):
        return False
    normalized_response = ' '.join(str(response_text or '').split())
    stored_hash = str(clarification.get('_response_hash') or '')
    if not normalized_response or not stored_hash:
        return False
    response_hash = hashlib.sha256(
        normalized_response.encode('utf-8')
    ).hexdigest()
    return hmac.compare_digest(stored_hash, response_hash)


def validate_chat_clarification_retry(
    clarification,
    response_message,
    *,
    proposed_text,
    now=None,
):
    """Validate Retry/Edit before a clarification response is mutated."""
    if not (
        isinstance(clarification, Mapping)
        and isinstance(response_message, Mapping)
    ):
        raise ChatClarificationError(
            'clarification retry state is invalid',
            code='clarification_response_conflict',
        )
    response_user_message_id = str(
        response_message.get('id') or ''
    ).strip()
    if not (
        response_user_message_id
        and response_message.get('role') == 'user'
        and response_user_message_id
        == str(
            clarification.get('_response_user_message_id') or ''
        ).strip()
        and chat_clarification_response_matches(
            clarification,
            response_message.get('content'),
        )
    ):
        raise ChatClarificationError(
            'clarification response no longer matches its checkpoint',
            code='clarification_response_conflict',
        )
    status = str(clarification.get('status') or '').strip().lower()
    if status == 'expired' or (
        status == 'resolving'
        and clarification_is_expired(clarification, now=now)
    ):
        raise ChatClarificationError(
            'clarification is no longer available for retry',
            code='clarification_expired',
        )
    if not chat_clarification_response_matches(
        clarification,
        proposed_text,
    ):
        raise ChatClarificationError(
            'clarification retry does not match the stored response',
            code='clarification_response_conflict',
        )
    if status not in {'resolving', 'resolved'}:
        raise ChatClarificationError(
            'clarification is not available for retry',
            code='clarification_response_conflict',
        )
    return {
        'mode': 'recover' if status == 'resolving' else 'replay',
        'response_user_message_id': response_user_message_id,
        'response_thread_id': str(
            clarification.get('_response_thread_id') or ''
        ).strip(),
        'child_run_id': str(
            clarification.get('child_run_id') or ''
        ).strip(),
    }


def clarification_is_expired(clarification, *, now=None):
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    expires_at = _parse_timestamp(
        clarification.get('expires_at')
        if isinstance(clarification, Mapping)
        else None
    )
    return expires_at is None or current_time >= expires_at


def clarification_response_lease_is_active(clarification, *, now=None):
    """Return whether one resolving clarification still owns a live lease."""
    if not (
        isinstance(clarification, Mapping)
        and clarification.get('status') == 'resolving'
    ):
        return False
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    lease_expires_at = _parse_timestamp(
        clarification.get('lease_expires_at')
    )
    return bool(lease_expires_at and current_time < lease_expires_at)


def build_chat_clarification(
    planner_clarification,
    *,
    parent_run_id,
    conversation_id,
    source_user_message_id,
    source_thread_id,
    assistant_message_id=None,
    now=None,
    ttl_seconds=DEFAULT_CHAT_CLARIFICATION_TTL_SECONDS,
):
    """Build one server-authored clarification checkpoint from validated planner data."""
    if not isinstance(planner_clarification, Mapping):
        raise ChatClarificationError(
            'planner clarification is required',
            code='clarification_missing',
        )
    code = str(planner_clarification.get('code') or '').strip().lower()
    if code not in CHAT_CLARIFICATION_CODES:
        raise ChatClarificationError(
            'clarification code is not supported',
            code='invalid_clarification_code',
        )
    options = _normalize_options(planner_clarification.get('option_values'))
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    try:
        normalized_ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        normalized_ttl = DEFAULT_CHAT_CLARIFICATION_TTL_SECONDS
    normalized_ttl = max(60, min(normalized_ttl, MAX_CHAT_CLARIFICATION_TTL_SECONDS))
    clarification_id = str(assistant_message_id or uuid.uuid4())
    return {
        'version': CHAT_CLARIFICATION_VERSION,
        'clarification_id': clarification_id,
        'parent_run_id': _normalize_identifier(parent_run_id, 'parent_run_id'),
        'code': code,
        'question': CHAT_CLARIFICATION_QUESTIONS[code],
        'status': 'pending',
        'options': options,
        'clarification_budget_used': 1,
        'created_at': current_time.isoformat(),
        'expires_at': (
            current_time + timedelta(seconds=normalized_ttl)
        ).isoformat(),
        'resolved_at': None,
        'response_mode': None,
        'child_run_id': None,
        'claimed_at': None,
        'lease_expires_at': None,
        '_conversation_id': _normalize_identifier(
            conversation_id,
            'conversation_id',
        ),
        '_source_user_message_id': _normalize_identifier(
            source_user_message_id,
            'source_user_message_id',
        ),
        '_source_thread_id': _normalize_identifier(
            source_thread_id,
            'source_thread_id',
        ),
        '_response_user_message_id': None,
        '_response_thread_id': None,
        '_response_hash': None,
    }


def claim_chat_clarification_response(
    clarification,
    *,
    response_user_message_id,
    response_text,
    child_run_id,
    response_thread_id=None,
    now=None,
):
    """Claim one clarification response before planning begins."""
    if not isinstance(clarification, Mapping):
        raise ChatClarificationError(
            'clarification metadata is invalid',
            code='clarification_invalid',
        )
    updated = copy.deepcopy(dict(clarification))
    response_user_message_id = _normalize_identifier(
        response_user_message_id,
        'response_user_message_id',
    )
    child_run_id = _normalize_identifier(child_run_id, 'child_run_id')
    response_thread_id = _normalize_identifier(
        response_thread_id or str(uuid.uuid4()),
        'response_thread_id',
    )
    normalized_response = ' '.join(str(response_text or '').split())
    if not normalized_response:
        raise ChatClarificationError(
            'clarification response is required',
            code='clarification_response_missing',
        )
    response_hash = hashlib.sha256(
        normalized_response.encode('utf-8')
    ).hexdigest()
    status = str(updated.get('status') or '').strip().lower()
    if status == 'resolved':
        if (
            updated.get('_response_user_message_id')
            == response_user_message_id
            and chat_clarification_response_matches(
                updated,
                normalized_response,
            )
        ):
            return updated, True
        raise ChatClarificationError(
            'clarification already has a different response',
            code='clarification_response_conflict',
        )
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if status == 'resolving':
        stored_response_user_message_id = str(
            updated.get('_response_user_message_id') or ''
        ).strip()
        if not chat_clarification_response_matches(
            updated,
            normalized_response,
        ):
            raise ChatClarificationError(
                'clarification already has a different response',
                code='clarification_response_conflict',
            )
        lease_expires_at = _parse_timestamp(updated.get('lease_expires_at'))
        if lease_expires_at and current_time < lease_expires_at:
            raise ChatClarificationError(
                'clarification response is already being processed',
                code='clarification_response_in_progress',
            )
        if stored_response_user_message_id != response_user_message_id:
            raise ChatClarificationError(
                'clarification retry does not match the claimed response',
                code='clarification_response_conflict',
            )
        child_run_id = str(updated.get('child_run_id') or child_run_id)
        response_thread_id = str(
            updated.get('_response_thread_id')
            or response_thread_id
        )
    elif status != 'pending':
        raise ChatClarificationError(
            'clarification is no longer pending',
            code=f'clarification_{status or "invalid"}',
        )
    if clarification_is_expired(updated, now=current_time):
        raise ChatClarificationError(
            'clarification has expired',
            code='clarification_expired',
        )
    options = updated.get('options') if isinstance(updated.get('options'), list) else []
    updated['status'] = 'resolving'
    updated['response_mode'] = (
        'option'
        if normalized_response in options
        else 'free_text'
    )
    updated['child_run_id'] = child_run_id
    updated['claimed_at'] = current_time.isoformat()
    updated['lease_expires_at'] = (
        current_time + timedelta(
            seconds=CHAT_CLARIFICATION_RESPONSE_LEASE_SECONDS
        )
    ).isoformat()
    updated['_response_user_message_id'] = response_user_message_id
    updated['_response_thread_id'] = response_thread_id
    updated['_response_hash'] = response_hash
    return updated, False


def complete_chat_clarification_response(
    clarification,
    *,
    response_user_message_id,
    child_run_id,
    now=None,
):
    """Complete the exact claimed response after its user turn is persisted."""
    updated = copy.deepcopy(dict(clarification or {}))
    response_user_message_id = _normalize_identifier(
        response_user_message_id,
        'response_user_message_id',
    )
    child_run_id = _normalize_identifier(child_run_id, 'child_run_id')
    if updated.get('status') == 'resolved':
        if (
            updated.get('_response_user_message_id') == response_user_message_id
            and updated.get('child_run_id') == child_run_id
        ):
            return updated, True
        raise ChatClarificationError(
            'clarification already completed for another response',
            code='clarification_response_conflict',
        )
    if not (
        updated.get('status') == 'resolving'
        and updated.get('_response_user_message_id')
        == response_user_message_id
        and updated.get('child_run_id') == child_run_id
    ):
        raise ChatClarificationError(
            'clarification response claim does not match',
            code='clarification_response_claim_mismatch',
        )
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    updated['status'] = 'resolved'
    updated['resolved_at'] = current_time.isoformat()
    updated['lease_expires_at'] = None
    return updated, False


def apply_chat_clarification_response(
    clarification,
    *,
    response_user_message_id,
    response_text,
    child_run_id=None,
    now=None,
):
    """Resolve one pending clarification or return an idempotent replay."""
    resolved_child_run_id = child_run_id or str(uuid.uuid4())
    claimed, idempotent = claim_chat_clarification_response(
        clarification,
        response_user_message_id=response_user_message_id,
        response_text=response_text,
        child_run_id=resolved_child_run_id,
        response_thread_id=None,
        now=now,
    )
    if idempotent:
        return claimed, True
    return complete_chat_clarification_response(
        claimed,
        response_user_message_id=claimed.get('_response_user_message_id'),
        child_run_id=claimed.get('child_run_id'),
        now=now,
    )


def expire_chat_clarification(clarification, *, now=None):
    """Return one terminal expired clarification state."""
    updated = copy.deepcopy(dict(clarification or {}))
    if updated.get('status') == 'resolved':
        return updated, True
    if updated.get('status') == 'expired':
        return updated, True
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    updated['status'] = 'expired'
    updated['expired_at'] = current_time.isoformat()
    return updated, False


def invalidate_chat_clarification(clarification, *, reason, now=None):
    """Terminalize a pending claim after source or authorization failure."""
    updated = copy.deepcopy(dict(clarification or {}))
    if updated.get('status') in {'resolved', 'expired'}:
        return updated, True
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    updated['status'] = 'expired'
    updated['expired_at'] = current_time.isoformat()
    updated['lease_expires_at'] = None
    updated['invalidation_reason'] = normalize_clarification_error_type(
        reason
    )
    return updated, False


def read_chat_clarification_message(container, *, conversation_id, clarification_id):
    """Read one exact assistant clarification from its authorized partition."""
    conversation_id = _normalize_identifier(conversation_id, 'conversation_id')
    clarification_id = _normalize_identifier(
        clarification_id,
        'clarification_id',
    )
    message = container.read_item(
        item=clarification_id,
        partition_key=conversation_id,
    )
    metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
    clarification = metadata.get('chat_clarification')
    if (
        message.get('conversation_id') != conversation_id
        or message.get('role') != 'assistant'
        or not isinstance(clarification, Mapping)
        or clarification.get('clarification_id') != clarification_id
        or clarification.get('_conversation_id') != conversation_id
    ):
        raise ChatClarificationError(
            'clarification checkpoint is invalid',
            code='clarification_invalid',
        )
    return message, copy.deepcopy(dict(clarification))


def find_pending_chat_clarification(
    container,
    *,
    conversation_id,
    source_thread_id,
):
    """Find at most one pending checkpoint for an exact predecessor thread."""
    conversation_id = _normalize_identifier(conversation_id, 'conversation_id')
    source_thread_id = _normalize_identifier(
        source_thread_id,
        'source_thread_id',
    )
    rows = list(container.query_items(
        query=(
            'SELECT TOP 2 * FROM c '
            'WHERE c.conversation_id = @conversation_id '
            'AND c.role = "assistant" '
            'AND IS_DEFINED(c.metadata.chat_clarification) '
            'AND c.metadata.thread_info.thread_id = @source_thread_id '
            'ORDER BY c.timestamp DESC'
        ),
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
            {'name': '@source_thread_id', 'value': source_thread_id},
        ],
        partition_key=conversation_id,
    ))
    valid_rows = []
    for message in rows:
        metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
        clarification = metadata.get('chat_clarification')
        if (
            message.get('conversation_id') == conversation_id
            and message.get('role') == 'assistant'
            and isinstance(clarification, Mapping)
            and clarification.get('status') in {
                'pending',
                'resolving',
            }
            and clarification.get('_source_thread_id') == source_thread_id
        ):
            valid_rows.append((message, copy.deepcopy(dict(clarification))))
    if len(valid_rows) > 1:
        raise ChatClarificationError(
            'multiple pending clarifications exist for this goal',
            code='clarification_ambiguous',
        )
    return valid_rows[0] if valid_rows else (None, None)


def find_latest_unresolved_chat_clarification(
    container,
    *,
    conversation_id,
):
    """Find one unresolved checkpoint when latest user lineage is malformed."""
    conversation_id = _normalize_identifier(conversation_id, 'conversation_id')
    rows = list(container.query_items(
        query=(
            'SELECT TOP 2 * FROM c '
            'WHERE c.conversation_id = @conversation_id '
            'AND c.role = "assistant" '
            'AND IS_DEFINED(c.metadata.chat_clarification) '
            'AND (c.metadata.chat_clarification.status = "pending" '
            'OR c.metadata.chat_clarification.status = "resolving") '
            'ORDER BY c.timestamp DESC'
        ),
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
        ],
        partition_key=conversation_id,
    ))
    valid_rows = []
    for message in rows:
        metadata = (
            message.get('metadata')
            if isinstance(message.get('metadata'), Mapping)
            else {}
        )
        clarification = metadata.get('chat_clarification')
        if (
            message.get('conversation_id') == conversation_id
            and message.get('role') == 'assistant'
            and isinstance(clarification, Mapping)
            and clarification.get('status') in {'pending', 'resolving'}
            and clarification.get('clarification_id') == message.get('id')
            and clarification.get('_conversation_id') == conversation_id
        ):
            valid_rows.append((message, copy.deepcopy(dict(clarification))))
    if len(valid_rows) > 1:
        raise ChatClarificationError(
            'multiple unresolved clarifications exist for this conversation',
            code='clarification_ambiguous',
        )
    return valid_rows[0] if valid_rows else (None, None)


def validate_chat_clarification_source(
    container,
    *,
    conversation_id,
    clarification,
):
    """Re-read and validate the exact active source user turn."""
    if not isinstance(clarification, Mapping):
        raise ChatClarificationError(
            'clarification metadata is invalid',
            code='clarification_invalid',
        )
    source_user_message_id = _normalize_identifier(
        clarification.get('_source_user_message_id'),
        'source_user_message_id',
    )
    source_thread_id = _normalize_identifier(
        clarification.get('_source_thread_id'),
        'source_thread_id',
    )
    message = container.read_item(
        item=source_user_message_id,
        partition_key=conversation_id,
    )
    metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
    thread_info = (
        metadata.get('thread_info')
        if isinstance(metadata.get('thread_info'), Mapping)
        else {}
    )
    if not (
        message.get('conversation_id') == conversation_id
        and message.get('role') == 'user'
        and str(thread_info.get('thread_id') or '').strip() == source_thread_id
        and thread_info.get('active_thread') is not False
        and metadata.get('is_deleted') is not True
        and metadata.get('masked') is not True
        and not (metadata.get('masked_ranges') or [])
        and metadata.get('is_generated_chat_artifact') is not True
    ):
        raise ChatClarificationError(
            'clarification source turn is no longer active',
            code='clarification_source_invalid',
        )
    return message


def _replace_clarification_message(container, message, clarification):
    updated_message = copy.deepcopy(dict(message))
    metadata = (
        copy.deepcopy(dict(updated_message.get('metadata')))
        if isinstance(updated_message.get('metadata'), Mapping)
        else {}
    )
    metadata['chat_clarification'] = copy.deepcopy(dict(clarification))
    metadata['awaiting_user_clarification'] = (
        clarification.get('status') in {'pending', 'resolving'}
    )
    updated_message['metadata'] = metadata
    return container.replace_item(
        item=updated_message['id'],
        body=updated_message,
        etag=message.get('_etag'),
        match_condition=MatchConditions.IfNotModified,
    )


def _is_conditional_conflict(exc):
    return getattr(exc, 'status_code', None) in {409, 412}


def persist_chat_clarification_expiry(
    container,
    *,
    conversation_id,
    clarification_id,
    now=None,
):
    """Persist one expired clarification using optimistic concurrency."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, clarification = read_chat_clarification_message(
            container,
            conversation_id=conversation_id,
            clarification_id=clarification_id,
        )
        if clarification.get('status') == 'expired':
            return message, clarification, True
        if clarification.get('status') == 'resolved':
            return message, clarification, True
        if not clarification_is_expired(clarification, now=now):
            return message, clarification, True
        expired, _ = expire_chat_clarification(clarification, now=now)
        try:
            saved_message = _replace_clarification_message(
                container,
                message,
                expired,
            )
            return saved_message, expired, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise ChatClarificationError(
        'clarification changed while it was being expired',
        code='clarification_expiry_write_conflict',
    ) from last_conflict


def persist_chat_clarification_invalidation(
    container,
    *,
    conversation_id,
    clarification_id,
    reason,
    expected_response_user_message_id=None,
    expected_child_run_id=None,
    expected_claimed_at=None,
    now=None,
):
    """Persist one fail-closed clarification invalidation with an ETag."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, clarification = read_chat_clarification_message(
            container,
            conversation_id=conversation_id,
            clarification_id=clarification_id,
        )
        claim_fence_requested = any(
            value is not None
            for value in (
                expected_response_user_message_id,
                expected_child_run_id,
                expected_claimed_at,
            )
        )
        expected_claim = {
            '_response_user_message_id': str(
                expected_response_user_message_id or ''
            ).strip(),
            'child_run_id': str(expected_child_run_id or '').strip(),
            'claimed_at': str(expected_claimed_at or '').strip(),
        }
        if claim_fence_requested and any(
            str(clarification.get(field_name) or '').strip()
            != expected_value
            for field_name, expected_value in expected_claim.items()
        ):
            raise ChatClarificationError(
                'clarification claim changed before invalidation',
                code='clarification_response_claim_mismatch',
            )
        invalidated, idempotent = invalidate_chat_clarification(
            clarification,
            reason=reason,
            now=now,
        )
        if idempotent:
            return message, invalidated, True
        try:
            saved_message = _replace_clarification_message(
                container,
                message,
                invalidated,
            )
            return saved_message, invalidated, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise ChatClarificationError(
        'clarification changed while it was being invalidated',
        code='clarification_invalidation_write_conflict',
    ) from last_conflict


def persist_chat_clarification_response_claim(
    container,
    *,
    conversation_id,
    clarification_id,
    response_user_message_id,
    response_text,
    child_run_id,
    response_thread_id=None,
    source_validator=None,
    expected_response_user_message_id=None,
    expected_child_run_id=None,
    expected_claimed_at=None,
    now=None,
):
    """Claim one clarification response using optimistic concurrency."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, clarification = read_chat_clarification_message(
            container,
            conversation_id=conversation_id,
            clarification_id=clarification_id,
        )
        claim_fence_requested = any(
            value is not None
            for value in (
                expected_response_user_message_id,
                expected_child_run_id,
                expected_claimed_at,
            )
        )
        if claim_fence_requested and any((
            str(
                clarification.get('_response_user_message_id') or ''
            ).strip()
            != str(expected_response_user_message_id or '').strip(),
            str(clarification.get('child_run_id') or '').strip()
            != str(expected_child_run_id or '').strip(),
            str(clarification.get('claimed_at') or '').strip()
            != str(expected_claimed_at or '').strip(),
        )):
            raise ChatClarificationError(
                'clarification claim changed before recovery',
                code='clarification_response_claim_mismatch',
            )
        if (
            clarification.get('status') in {'pending', 'resolving'}
            and clarification_is_expired(clarification, now=now)
        ):
            expired, _ = expire_chat_clarification(
                clarification,
                now=now,
            )
            try:
                _replace_clarification_message(container, message, expired)
            except Exception as exc:
                if _is_conditional_conflict(exc):
                    last_conflict = exc
                    continue
                raise
            raise ChatClarificationError(
                'clarification has expired',
                code='clarification_expired',
            )
        if callable(source_validator):
            try:
                source_validator(clarification)
            except Exception as source_error:
                invalidated, invalidation_idempotent = (
                    invalidate_chat_clarification(
                        clarification,
                        reason='clarification_source_invalid',
                        now=now,
                    )
                )
                if not invalidation_idempotent:
                    try:
                        _replace_clarification_message(
                            container,
                            message,
                            invalidated,
                        )
                    except Exception as exc:
                        if _is_conditional_conflict(exc):
                            last_conflict = exc
                            continue
                        raise
                raise ChatClarificationError(
                    'clarification source turn is no longer active',
                    code='clarification_source_invalid',
                ) from source_error
        claimed, idempotent = claim_chat_clarification_response(
            clarification,
            response_user_message_id=response_user_message_id,
            response_text=response_text,
            child_run_id=child_run_id,
            response_thread_id=response_thread_id,
            now=now,
        )
        if idempotent:
            return message, claimed, True
        try:
            saved_message = _replace_clarification_message(
                container,
                message,
                claimed,
            )
            return saved_message, claimed, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise ChatClarificationError(
        'clarification changed while the response was being claimed',
        code='clarification_claim_write_conflict',
    ) from last_conflict


def persist_chat_clarification_response_completion(
    container,
    *,
    conversation_id,
    clarification_id,
    response_user_message_id,
    child_run_id,
    expected_claimed_at=None,
    response_validator=None,
    now=None,
):
    """Complete one exact claimed response using optimistic concurrency."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, clarification = read_chat_clarification_message(
            container,
            conversation_id=conversation_id,
            clarification_id=clarification_id,
        )
        if (
            expected_claimed_at is not None
            and str(clarification.get('claimed_at') or '').strip()
            != str(expected_claimed_at or '').strip()
        ):
            raise ChatClarificationError(
                'clarification claim changed before completion',
                code='clarification_response_claim_mismatch',
            )
        if callable(response_validator):
            try:
                response_validator(clarification)
            except Exception as response_error:
                invalidated, invalidation_idempotent = (
                    invalidate_chat_clarification(
                        clarification,
                        reason='clarification_response_claim_mismatch',
                        now=now,
                    )
                )
                if not invalidation_idempotent:
                    try:
                        _replace_clarification_message(
                            container,
                            message,
                            invalidated,
                        )
                    except Exception as exc:
                        if _is_conditional_conflict(exc):
                            last_conflict = exc
                            continue
                        raise
                raise ChatClarificationError(
                    'clarification response state is invalid',
                    code='clarification_response_claim_mismatch',
                ) from response_error
        completed, idempotent = complete_chat_clarification_response(
            clarification,
            response_user_message_id=response_user_message_id,
            child_run_id=child_run_id,
            now=now,
        )
        if idempotent:
            return message, completed, True
        try:
            saved_message = _replace_clarification_message(
                container,
                message,
                completed,
            )
            return saved_message, completed, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise ChatClarificationError(
        'clarification changed while the response was being completed',
        code='clarification_completion_write_conflict',
    ) from last_conflict


def persist_chat_clarification_response(
    container,
    *,
    conversation_id,
    clarification_id,
    response_user_message_id,
    response_text,
    child_run_id=None,
    source_validator=None,
    now=None,
):
    """Resolve one clarification with optimistic concurrency."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, clarification = read_chat_clarification_message(
            container,
            conversation_id=conversation_id,
            clarification_id=clarification_id,
        )
        if (
            clarification.get('status') == 'pending'
            and clarification_is_expired(clarification, now=now)
        ):
            expired, _ = expire_chat_clarification(
                clarification,
                now=now,
            )
            try:
                _replace_clarification_message(container, message, expired)
            except Exception as exc:
                if _is_conditional_conflict(exc):
                    last_conflict = exc
                    continue
                raise
            raise ChatClarificationError(
                'clarification has expired',
                code='clarification_expired',
            )
        if callable(source_validator):
            source_validator(clarification)
        updated, idempotent = apply_chat_clarification_response(
            clarification,
            response_user_message_id=response_user_message_id,
            response_text=response_text,
            child_run_id=child_run_id,
            now=now,
        )
        if idempotent:
            return message, updated, True
        try:
            saved_message = _replace_clarification_message(
                container,
                message,
                updated,
            )
            return saved_message, updated, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise ChatClarificationError(
        'clarification changed while the response was being saved',
        code='clarification_write_conflict',
    ) from last_conflict


def normalize_clarification_error_type(value):
    """Return one bounded safe failure code for persistence or evaluation."""
    return re.sub(
        r'[^a-z0-9_]+',
        '_',
        str(value or 'clarification_failed').strip().lower(),
    )[:120]
