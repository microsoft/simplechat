# functions_review_center.py

"""Shared helpers for the admin Review center's feedback and safety APIs.

The Feedback and Safety review APIs both serve the V2 Review center. This module keeps the
parts they share in one place: the dashboard window an analytics request may ask for, the
daily series a chart reads, the batched lookup that turns the owners of records into
display names, and the bulk operation envelope with its per-call cap.

Every user id looked up here comes from a review record the caller is already authorized
to read through the route's role decorator; nothing here accepts a user id from a client
as a reason to read a profile.
"""

import copy
import logging
import re
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from config import cosmos_user_settings_container
from functions_access_restriction import ACCESS_STATE_RESTRICTED, describe_access_restriction
from functions_appinsights import log_event
from functions_review_assist import (
    SUGGESTION_ID_PATTERN,
    SUGGESTION_NOT_PENDING_CODE,
    SUGGESTION_NOT_PENDING_MESSAGE,
    SUGGESTION_STATUS_APPLIED,
    SUGGESTION_STATUS_DISMISSED,
    mark_suggestion,
    review_record_fingerprint,
    stored_suggestion,
    suggestion_problem,
    suggestion_was_edited,
)
from functions_review_lifecycle import log_review_suggestion_action


REVIEW_WINDOW_DAYS = (7, 30, 90)
REVIEW_BULK_MAX_OPERATIONS = 100
REVIEW_IDS_CAP = 500
REVIEW_SEARCH_MAX_LENGTH = 200
REVIEW_NAME_BATCH = 100
REVIEW_EXCERPT_LENGTH = 160
REVIEW_WRITE_ATTEMPTS = 3
REVIEW_BULK_OPERATIONS = ('update', 'archive', 'delete', 'dismiss_suggestion')
# Every key an operation may carry. Unknown keys are refused, so a later field, such as an
# attribution to the suggestion that proposed the change, is added here on purpose.
# ``suggestion_id`` names the AI suggestion an ``update`` applies or a ``dismiss_suggestion``
# dismisses; the server checks it against the record.
REVIEW_BULK_OPERATION_KEYS = frozenset({'id', 'op', 'etag', 'changes', 'archived', 'suggestion_id'})
REVIEW_RECORD_ID_MAX_LENGTH = 200

REVIEW_RECORD_CHANGED_CODE = 'record_changed'
REVIEW_NOT_FOUND_CODE = 'not_found'
REVIEW_INVALID_OPERATION_CODE = 'invalid_operation'
REVIEW_DUPLICATE_OPERATION_CODE = 'duplicate_operation'
REVIEW_OPERATION_FAILED_CODE = 'operation_failed'

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class ReviewRequestError(ValueError):
    """A request the Review center APIs refuse as a whole, with a stable code."""

    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class ReviewRecordConflict(Exception):
    """A record kept changing while it was being written."""


def replace_review_record(container, item_id, mutate, *, base_item=None, attempts=REVIEW_WRITE_ATTEMPTS):
    """Apply ``mutate`` to a record and replace it on the condition that it has not changed.

    ``mutate(record)`` changes the record in place and returns False to stop without
    writing. The first attempt applies it to ``base_item`` when given; after a conflict, to
    a fresh read, so only what ``mutate`` sets is ever written over another writer's change.
    Returns the stored record, or None when ``mutate`` stopped. Raises
    ``ReviewRecordConflict`` when every attempt conflicts, and lets a missing record's
    ``CosmosResourceNotFoundError`` through. The record's id must be its partition key.
    """
    current = base_item
    for _attempt in range(max(1, attempts)):
        if current is None:
            current = container.read_item(item=item_id, partition_key=item_id)
        record = copy.deepcopy(current)
        if mutate(record) is False:
            return None
        etag = current.get('_etag')
        try:
            if etag:
                stored = container.replace_item(
                    item=item_id,
                    body=record,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            else:
                stored = container.upsert_item(record)
        except cosmos_exceptions.CosmosAccessConditionFailedError:
            current = None
            continue
        return stored if isinstance(stored, dict) else record
    raise ReviewRecordConflict(f'Record {item_id} changed while it was being written.')


def parse_review_window(value):
    """Return the requested dashboard window in days, or None when none was asked for.

    Only the windows the dashboards offer are accepted, so a request cannot ask the server
    to scan an arbitrary history.
    """
    if value is None or str(value).strip() == '':
        return None
    text = str(value).strip()
    if not text.isdigit() or int(text) not in REVIEW_WINDOW_DAYS:
        raise ReviewRequestError('The window must be 7, 30 or 90 days.', code='invalid_window')
    return int(text)


def parse_review_date(value):
    """Return a ``YYYY-MM-DD`` day filter, or None. Anything else is refused."""
    if value is None or str(value).strip() == '':
        return None
    text = str(value).strip()
    if not _DATE_RE.match(text):
        raise ReviewRequestError('The date must be YYYY-MM-DD.', code='invalid_date')
    try:
        datetime.strptime(text, '%Y-%m-%d')
    except ValueError as exc:
        raise ReviewRequestError('The date must be YYYY-MM-DD.', code='invalid_date') from exc
    return text


def parse_review_timestamp(value):
    """Return a stored timestamp as an aware UTC datetime, or None when it can't be read.

    Records written with ``datetime.utcnow().isoformat()`` carry no offset; they are UTC.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def review_day(value):
    """The UTC day a timestamp falls on, as ``YYYY-MM-DD``, or None."""
    parsed = parse_review_timestamp(value)
    return parsed.date().isoformat() if parsed else None


def review_window(days, now=None):
    """Describe a window of ``days`` UTC days ending today, oldest day first."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = current.date()
    dates = [(end - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    start = datetime.combine(end - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)
    return {
        'days': days,
        'start_date': dates[0],
        'end_date': dates[-1],
        'dates': dates,
        'start': start,
    }


def in_review_window(value, window):
    """True when a timestamp falls inside the window."""
    parsed = parse_review_timestamp(value)
    return bool(parsed and parsed >= window['start'])


def normalize_review_search(value):
    """Return search text as the lists match it: trimmed, lowercased and bounded."""
    if not isinstance(value, str):
        return ''
    return value.strip().lower()[:REVIEW_SEARCH_MAX_LENGTH]


def review_text_matches(needle, *values):
    """True when the search text appears in any of the values."""
    if not needle:
        return True
    for value in values:
        if isinstance(value, str) and needle in value.lower():
            return True
    return False


def review_excerpt(value, limit=REVIEW_EXCERPT_LENGTH):
    """The first ``limit`` characters of text on one line, for a list row."""
    if not isinstance(value, str):
        return ''
    flattened = ' '.join(value.split())
    return flattened if len(flattened) <= limit else f"{flattened[:limit - 1].rstrip()}…"


def _normalize_user_ids(user_ids):
    return [
        user_id for user_id in dict.fromkeys(user_ids or [])
        if isinstance(user_id, str) and user_id.strip()
    ]


def resolve_review_users(user_ids, include_access=False, now=None):
    """Return ``{user_id: {display_name, email[, access]}}`` with one query per batch.

    Names are a convenience for the reviewer, so a failed lookup is logged and leaves the
    affected ids out rather than failing the list. ``access`` describes whether the user is
    restricted now: ``{'restricted': bool, 'kind': ..., 'until': ...}``.
    """
    pending = _normalize_user_ids(user_ids)
    found = {}
    projection = 'c.id, c.display_name, c.email'
    if include_access:
        projection += ', c.settings.access AS access'
    query = f"SELECT {projection} FROM c WHERE ARRAY_CONTAINS(@ids, c.id)"
    for start in range(0, len(pending), REVIEW_NAME_BATCH):
        batch = pending[start:start + REVIEW_NAME_BATCH]
        try:
            rows = list(cosmos_user_settings_container.query_items(
                query=query,
                parameters=[{'name': '@ids', 'value': batch}],
                enable_cross_partition_query=True,
            ))
        except Exception as exc:
            log_event(
                '[REVIEW_CENTER] User names could not be resolved for a review list.',
                extra={'user_count': len(batch), 'error_type': type(exc).__name__},
                level=logging.WARNING,
            )
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get('id') not in batch:
                continue
            entry = {
                'display_name': str(row.get('display_name') or '').strip(),
                'email': str(row.get('email') or '').strip(),
            }
            if include_access:
                state, restriction = describe_access_restriction(row.get('access'), now=now)
                entry['access'] = {
                    'restricted': state == ACCESS_STATE_RESTRICTED,
                    'kind': (restriction or {}).get('kind'),
                    'until': (restriction or {}).get('until'),
                }
            found[row['id']] = entry
    return found


def review_user_label(user_id, users):
    """The name a reviewer reads for a user: display name, then email, then id."""
    entry = (users or {}).get(user_id) or {}
    return entry.get('display_name') or entry.get('email') or user_id or ''


def cap_review_ids(ids, owners=None):
    """The ids a "select all matching" may act on, capped, and whether the cap applied.

    ``owners`` maps a record id to the user the record is about. When given, the result carries
    it for the returned ids, so the Review center can send each user's records to the AI
    assistant together.
    """
    unique = [item for item in dict.fromkeys(ids or []) if isinstance(item, str) and item]
    result = {
        'ids': unique[:REVIEW_IDS_CAP],
        'total': len(unique),
        'capped': len(unique) > REVIEW_IDS_CAP,
        'cap': REVIEW_IDS_CAP,
    }
    if owners is not None:
        result['owners'] = {
            record_id: owners[record_id] for record_id in result['ids']
            if isinstance(owners.get(record_id), str) and owners[record_id]
        }
    return result


def review_version_matches(section, record, expected_etag, expected_fingerprint=None):
    """Whether a save that read a record at ``expected_etag`` may still be made on this read of it.

    Without ``expected_etag`` there is nothing to check. Otherwise the record must be the version
    the save read, or one whose reviewable fields -- and for a violation, its request and warning
    state -- still match ``expected_fingerprint``: then only an AI suggestion or other bookkeeping
    was written since, and the save goes ahead on this read, written conditionally on its version.
    """
    if not expected_etag or record.get('_etag') == expected_etag:
        return True
    return (
        isinstance(expected_fingerprint, str)
        and bool(expected_fingerprint)
        and review_record_fingerprint(section, record) == expected_fingerprint
    )


def _operation_error(index, record_id, op, message):
    return {
        'index': index,
        'id': record_id if isinstance(record_id, str) else None,
        'op': op if isinstance(op, str) else None,
        'error': {
            'status': 400,
            'body': {'error': message, 'code': REVIEW_INVALID_OPERATION_CODE},
        },
    }


def parse_review_bulk_operations(payload):
    """Validate a bulk request and return its operations, in the order they were sent.

    A request is ``{"operations": [...]}`` with 1 to 100 operations. Each operation is
    ``{"id", "op", "etag"?, ...}``: ``update`` carries ``changes`` (the same fields the
    single-record PATCH accepts), ``archive`` carries ``archived`` (a boolean) and
    ``delete`` carries nothing more. ``etag``, when present, must match the stored record.
    An ``update`` may carry ``suggestion_id`` to apply the record's pending AI suggestion
    with the reviewer's changes, and ``dismiss_suggestion`` carries the ``suggestion_id`` it
    dismisses.

    A malformed request as a whole raises ``ReviewRequestError``. A malformed operation is
    returned with an ``error`` so the rest of the request still runs and the caller can
    report it per item. A second operation on an id already in the request is refused.
    """
    if not isinstance(payload, dict) or set(payload) - {'operations'}:
        raise ReviewRequestError('Send {"operations": [...]}.', code='invalid_request')
    operations = payload.get('operations')
    if not isinstance(operations, list) or not operations:
        raise ReviewRequestError('Send at least one operation.', code='invalid_request')
    if len(operations) > REVIEW_BULK_MAX_OPERATIONS:
        raise ReviewRequestError(
            f'Send at most {REVIEW_BULK_MAX_OPERATIONS} operations at a time.',
            code='too_many_operations',
        )

    parsed = []
    seen = set()
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            parsed.append(_operation_error(index, None, None, 'Each operation must be an object.'))
            continue
        record_id = raw.get('id')
        op = raw.get('op')
        if set(raw) - REVIEW_BULK_OPERATION_KEYS:
            parsed.append(_operation_error(index, record_id, op, 'The operation has fields this API does not accept.'))
            continue
        if not isinstance(record_id, str) or not record_id.strip() or len(record_id) > REVIEW_RECORD_ID_MAX_LENGTH:
            parsed.append(_operation_error(index, record_id, op, 'Each operation needs the id of a record.'))
            continue
        if op not in REVIEW_BULK_OPERATIONS:
            parsed.append(_operation_error(
                index, record_id, op, 'The operation must be update, archive, delete or dismiss_suggestion.',
            ))
            continue
        etag = raw.get('etag')
        if etag is not None and (not isinstance(etag, str) or not etag):
            parsed.append(_operation_error(index, record_id, op, 'The etag must be text.'))
            continue
        if op == 'update' and not isinstance(raw.get('changes'), dict):
            parsed.append(_operation_error(index, record_id, op, 'An update needs its changes.'))
            continue
        if op == 'archive' and not isinstance(raw.get('archived'), bool):
            parsed.append(_operation_error(index, record_id, op, 'The archived field must be a boolean.'))
            continue
        if (op != 'update' and 'changes' in raw) or (op != 'archive' and 'archived' in raw):
            parsed.append(_operation_error(index, record_id, op, 'The operation has fields this API does not accept.'))
            continue
        suggestion_id = raw.get('suggestion_id')
        if 'suggestion_id' in raw and op not in ('update', 'dismiss_suggestion'):
            parsed.append(_operation_error(index, record_id, op, 'The operation has fields this API does not accept.'))
            continue
        if op == 'dismiss_suggestion' and suggestion_id is None:
            parsed.append(_operation_error(index, record_id, op, 'A dismissal needs the suggestion_id it dismisses.'))
            continue
        if suggestion_id is not None and (
            not isinstance(suggestion_id, str) or not SUGGESTION_ID_PATTERN.match(suggestion_id)
        ):
            parsed.append(_operation_error(index, record_id, op, 'The suggestion_id is not valid.'))
            continue
        if record_id in seen:
            duplicate = _operation_error(index, record_id, op, 'This record already has an operation in this request.')
            duplicate['error']['body']['code'] = REVIEW_DUPLICATE_OPERATION_CODE
            parsed.append(duplicate)
            continue
        seen.add(record_id)
        parsed.append({
            'index': index,
            'id': record_id,
            'op': op,
            'etag': etag,
            'changes': raw.get('changes') if op == 'update' else None,
            'archived': raw.get('archived') if op == 'archive' else None,
            'suggestion_id': suggestion_id,
        })
    return parsed


def review_bulk_result(operation, body, status):
    """One operation's result: the single-record route's response body, with its outcome."""
    body = body if isinstance(body, dict) else {}
    result = {
        'index': operation.get('index'),
        'id': operation.get('id'),
        'op': operation.get('op'),
        'ok': 200 <= int(status) < 300,
        'status': int(status),
    }
    for key, value in body.items():
        if key not in result:
            result[key] = value
    if not result['ok'] and 'code' not in result:
        result['code'] = {
            404: REVIEW_NOT_FOUND_CODE,
            409: REVIEW_RECORD_CHANGED_CODE,
        }.get(int(status), REVIEW_OPERATION_FAILED_CODE)
    return result


def summarize_review_bulk_results(results):
    """The bulk response: every result in request order, and how many succeeded."""
    ordered = sorted(results, key=lambda item: item.get('index') or 0)
    succeeded = sum(1 for item in ordered if item.get('ok'))
    return {
        'results': ordered,
        'succeeded': succeeded,
        'failed': len(ordered) - succeeded,
    }


def daily_counts(records, window, timestamp_of, group_of):
    """Count records per day of the window, split by group.

    Returns ``{'dates': [...], 'series': [{'key': group, 'counts': [...]}, ...]}`` with the
    groups ordered by their total, largest first. ``group_of`` may return several groups
    for one record, which is then counted once in each.
    """
    dates = window['dates']
    index = {date: position for position, date in enumerate(dates)}
    counts = {}
    for record in records:
        day = review_day(timestamp_of(record))
        if day not in index:
            continue
        groups = group_of(record)
        if isinstance(groups, str) or groups is None:
            groups = [groups or 'Unknown']
        for group in dict.fromkeys(groups):
            series = counts.setdefault(group, [0] * len(dates))
            series[index[day]] += 1
    ordered = sorted(counts.items(), key=lambda item: (-sum(item[1]), str(item[0])))
    return {
        'dates': list(dates),
        'series': [{'key': key, 'counts': values} for key, values in ordered],
    }


# ---------------------------------------------------------------------------
# AI suggestions: applying and dismissing them
# ---------------------------------------------------------------------------

REVIEW_SUGGESTION_RECORD_TYPES = {'feedback': 'feedback', 'safety': 'safety_violation'}
REVIEW_SUGGESTION_RECORD_CHANGED_MESSAGE = (
    'This record changed after you opened it. Reload it to see the latest version, then try again.'
)
REVIEW_SUGGESTION_NOT_MARKED_WARNING = (
    'The review was saved, but the AI suggestion could not be marked as applied. Dismiss it from the queue.'
)
REVIEW_ASSISTANT_DISABLED_CODE = 'review_assistant_disabled'
REVIEW_ASSISTANT_OFF_MESSAGE = (
    'AI assist for the Review center is turned off in Admin Settings, so AI suggestions cannot be applied '
    'or dismissed.'
)
REVIEW_SUGGESTION_OPERATION_FAILED_MESSAGE = (
    'This record could not be read or written, so nothing was changed for it. Try again.'
)


def _suggestion_operation_failed(section, record_id, step, exc):
    """Log a suggestion operation's unexpected failure, and fail that one operation."""
    log_event(
        '[REVIEW_ASSIST] An AI suggestion operation failed.',
        extra={'section': section, 'record_id': record_id, 'step': step, 'error_type': type(exc).__name__},
        level=logging.ERROR,
    )
    return {'error': REVIEW_SUGGESTION_OPERATION_FAILED_MESSAGE, 'code': REVIEW_OPERATION_FAILED_CODE}, 500


def run_suggestion_operation(section, operation, run):
    """Run one bulk operation on an AI suggestion; an unexpected failure fails only that operation.

    The operations before it in the request may already have sent a warning or created a request,
    so the rest of the request still runs and every result is reported.
    """
    try:
        return run()
    except Exception as exc:
        return _suggestion_operation_failed(section, operation.get('id'), operation.get('op'), exc)


def refuse_suggestion_operations_while_off(operations, assistant_enabled):
    """While AI assist is off, refuse each operation that applies or dismisses an AI suggestion.

    The rest of the request runs as usual. Turning the assistant off therefore stops a suggestion
    reaching a review even from a page loaded while it was on; stored suggestions stay on their
    records and are offered again if it is turned back on.
    """
    if assistant_enabled:
        return operations
    checked = []
    for operation in operations:
        if not operation.get('error') and operation.get('suggestion_id'):
            operation = dict(operation)
            operation['error'] = {
                'status': 403,
                'body': {'error': REVIEW_ASSISTANT_OFF_MESSAGE, 'code': REVIEW_ASSISTANT_DISABLED_CODE},
            }
        checked.append(operation)
    return checked


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_review_record(container, record_id):
    return container.read_item(item=record_id, partition_key=record_id)


def mark_review_suggestion(container, section, record_id, suggestion_id, actor, *, status, edited=None):
    """Mark a record's pending AI suggestion applied or dismissed. Returns whether it was marked.

    Only ``ai_suggestion`` changes, conditionally on the stored version and again on a fresh
    copy after a conflict, so a concurrent save of anything else survives. A suggestion that was
    replaced or already decided meanwhile is left as it is.
    """
    at = _utc_now_iso()

    def mutate(record):
        return mark_suggestion(record, suggestion_id, status=status, actor=actor, at=at, edited=edited)

    try:
        stored = replace_review_record(container, record_id, mutate)
    except (ReviewRecordConflict, cosmos_exceptions.CosmosResourceNotFoundError):
        return False
    except Exception as exc:
        log_event(
            '[REVIEW_ASSIST] An AI suggestion could not be marked.',
            extra={'section': section, 'record_id': record_id, 'status': status, 'error_type': type(exc).__name__},
            level=logging.WARNING,
        )
        return False
    return stored is not None


def apply_suggested_review(container, section, record_id, suggestion_id, changes, actor, run_update):
    """Apply a record's pending AI suggestion, as the reviewer edited it, through the normal save.

    ``run_update(changes)`` is the section's single-record save and returns ``(body, status)``;
    it enforces every rule a hand-made save does. The suggestion must still be pending and still
    match its record, and unless the reviewer sent an etag of their own, the save is conditional
    on the version that was checked, so the record cannot change between the check and the save.
    Once saved, the suggestion is marked applied, with whether the reviewer edited it first, and
    the decision is credited to the suggestion in the audit log. Returns ``(body, status)``; a
    record that can't be read fails with ``operation_failed``.
    """
    try:
        record = _read_review_record(container, record_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return {'error': 'The record was not found.', 'code': REVIEW_NOT_FOUND_CODE}, 404
    except Exception as exc:
        return _suggestion_operation_failed(section, record_id, 'read', exc)
    problem = suggestion_problem(section, record, suggestion_id)
    if problem:
        code, message = problem
        return {'error': message, 'code': code}, 409
    checked = dict(changes or {})
    if not checked.get('etag') and record.get('_etag'):
        # Pinned to the version just checked; only an AI suggestion or other bookkeeping written
        # in between, which leaves the fingerprint as it is, lets the save go ahead.
        checked['etag'] = record.get('_etag')
        checked['fingerprint'] = review_record_fingerprint(section, record)
    body, status = run_update(checked)
    if not 200 <= int(status) < 300:
        return body, status

    payload = (stored_suggestion(record) or {}).get('payload')
    edited = suggestion_was_edited(section, payload, changes)
    marked = mark_review_suggestion(
        container, section, record_id, suggestion_id, actor, status=SUGGESTION_STATUS_APPLIED, edited=edited,
    )
    audit_logged = log_review_suggestion_action(
        REVIEW_SUGGESTION_RECORD_TYPES[section], 'applied', record, actor, suggestion_id, edited=edited,
    )
    result = dict(body if isinstance(body, dict) else {})
    result['suggestion'] = {
        'id': suggestion_id,
        'status': SUGGESTION_STATUS_APPLIED if marked else 'pending',
        'edited': edited,
    }
    if not marked:
        result['suggestion_warning'] = REVIEW_SUGGESTION_NOT_MARKED_WARNING
    if not audit_logged:
        log_event(
            '[REVIEW_ASSIST] Applying an AI suggestion could not be audited.',
            extra={'section': section, 'record_id': record_id, 'suggestion_id': suggestion_id},
            level=logging.ERROR,
        )
    return result, status


def dismiss_review_suggestion(container, section, record_id, suggestion_id, actor, expected_etag=None):
    """Dismiss a record's pending AI suggestion, stale or not. Returns ``(body, status)``.

    Nothing about the review changes. ``expected_etag``, when sent, must match the stored record,
    and is then honoured strictly: a record that changes before the write is refused, not merged.
    A record that can't be read fails with ``operation_failed``.
    """
    try:
        record = _read_review_record(container, record_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return {'error': 'The record was not found.', 'code': REVIEW_NOT_FOUND_CODE}, 404
    except Exception as exc:
        return _suggestion_operation_failed(section, record_id, 'read', exc)
    if expected_etag and record.get('_etag') != expected_etag:
        return {'error': REVIEW_SUGGESTION_RECORD_CHANGED_MESSAGE, 'code': REVIEW_RECORD_CHANGED_CODE}, 409
    problem = suggestion_problem(section, record, suggestion_id, allow_stale=True)
    if problem:
        code, message = problem
        return {'error': message, 'code': code}, 409

    at = _utc_now_iso()

    def mutate(current):
        return mark_suggestion(current, suggestion_id, status=SUGGESTION_STATUS_DISMISSED, actor=actor, at=at)

    try:
        stored = replace_review_record(
            container,
            record_id,
            mutate,
            base_item=record,
            attempts=1 if expected_etag else REVIEW_WRITE_ATTEMPTS,
        )
    except ReviewRecordConflict:
        return {'error': REVIEW_SUGGESTION_RECORD_CHANGED_MESSAGE, 'code': REVIEW_RECORD_CHANGED_CODE}, 409
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return {'error': 'The record was not found.', 'code': REVIEW_NOT_FOUND_CODE}, 404
    except Exception as exc:
        log_event(
            '[REVIEW_ASSIST] An AI suggestion could not be dismissed.',
            extra={'section': section, 'record_id': record_id, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return {'error': 'The AI suggestion could not be dismissed.', 'code': REVIEW_OPERATION_FAILED_CODE}, 500
    if stored is None:
        return {'error': SUGGESTION_NOT_PENDING_MESSAGE, 'code': SUGGESTION_NOT_PENDING_CODE}, 409

    audit_logged = log_review_suggestion_action(
        REVIEW_SUGGESTION_RECORD_TYPES[section], 'dismissed', record, actor, suggestion_id,
    )
    body = {
        'success': True,
        'message': 'AI suggestion dismissed.',
        'suggestion': {'id': suggestion_id, 'status': SUGGESTION_STATUS_DISMISSED},
        'audit_logged': audit_logged,
    }
    if not audit_logged:
        body['audit_warning'] = 'The suggestion was dismissed, but the audit activity could not be recorded.'
    return body, 200
