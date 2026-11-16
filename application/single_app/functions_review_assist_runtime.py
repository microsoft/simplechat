# functions_review_assist_runtime.py
"""
The Review center assistant's services: the Azure-backed side of ``functions_review_assist``.

Version: 0.261.299
Implemented in: 0.261.299

``handle_review_assist_request`` runs one assist request for a route. The route supplies what only
it may decide: the section, the signed-in reviewer it has already authorized, the settings, the
store its records live in, and the model client factory, because the client reads the signed-in
user from the request and a functions module doesn't import a route module.

The store is the container the route's own reads and writes use, so the assistant reads exactly
the records the route would, by id, and never anything a client sent about them. A violation is
settled first, as the violation editor's read settles it, and one held by a pending remediation
request or a warning being sent is skipped.

The model is the draft-instructions deployment, reached through the workflow assistant's model
invoker, and requests are counted by the shared per-user limiter under a document type of their
own. A triage stores each suggestion on its record with a write conditional on the version read,
and only while the record still matches the fingerprint the suggestion was based on.
"""

import json
import logging
from datetime import datetime, timezone

from azure.cosmos import exceptions as cosmos_exceptions
from flask import current_app, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from functions_appinsights import log_event
from functions_review_assist import (
    REVIEW_ASSIST_MAX_BODY_BYTES,
    SUGGESTION_RECORD_FIELD,
    ReviewAssistError,
    ReviewAssistServices,
    ReviewRecordInput,
    parse_review_assist_body,
    review_record_fingerprint,
    run_review_assist,
)
from functions_workflow_assist import WorkflowAssistError
from functions_workflow_assist_runtime import WorkflowAssistModel


REVIEW_ASSIST_LIMIT_DOCUMENT_TYPE = 'admin_review_assist_rate_limit'
# A triage of hundreds of records is sent ten at a time, one request after another, so reviewers
# get more requests per window than the editor assistants do.
REVIEW_ASSIST_LIMIT_REQUESTS = 60
REVIEW_ASSIST_LIMIT_WINDOW_SECONDS = 600
# A Cosmos item ID cannot hold these, so an id with one names no record.
_COSMOS_ID_FORBIDDEN_CHARACTERS = frozenset('/\\?#')
_PRIOR_VIOLATIONS_QUERY = 'SELECT c.id, c.content_origin, c.created_at FROM c WHERE c.user_id = @user_id'


class ReviewRecordStore:
    """Where one section's records live, as the route that owns them reads and writes them.

    * ``container``: the Cosmos container, partitioned by the record id.
    * ``replace(record_id, mutate, base_item)``: an ETag-conditional replace that applies
      ``mutate`` and returns the stored record, or None when ``mutate`` stopped it; raises
      ``conflict_error`` when every attempt conflicts.
    * ``prepare(record)``: settles a record before it is read, such as a violation whose
      remediation request was decided. Returns the record to use.
    * ``is_locked(record)``: True for a record no review may change right now.
    """

    def __init__(self, *, section, container, replace, conflict_error, prepare=None, is_locked=None):
        self.section = section
        self.container = container
        self.replace = replace
        self.conflict_error = conflict_error
        self.prepare = prepare
        self.is_locked = is_locked


class _ConvertingLimiter:
    """The shared limiter, with its errors converted to ``ReviewAssistError``."""

    def __init__(self, limiter):
        self._limiter = limiter

    def acquire(self, user_id):
        try:
            return self._limiter.acquire(user_id)
        except WorkflowAssistError as exc:
            raise ReviewAssistError.from_assist_error(exc) from exc

    def release(self, lease, refund=False):
        return self._limiter.release(lease, refund=refund)


class _ConvertingModel:
    """The workflow assistant's model invoker, with its errors converted to ``ReviewAssistError``."""

    def __init__(self, model):
        self._model = model

    def __call__(self, messages, timeout):
        try:
            return self._model(messages, timeout)
        except WorkflowAssistError as exc:
            raise ReviewAssistError.from_assist_error(exc) from exc


def _read_record(container, record_id):
    """The stored record, or None when there is none. A store failure is ``assistant_unavailable``."""
    if any(character in _COSMOS_ID_FORBIDDEN_CHARACTERS for character in record_id):
        return None
    try:
        record = container.read_item(item=record_id, partition_key=record_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        if getattr(exc, 'status_code', None) in (400, 404):
            return None
        raise ReviewAssistError('assistant_unavailable') from exc
    return record if isinstance(record, dict) else None


def _flagged_at(value):
    """A violation's stored time as an aware UTC datetime, or None. Stored times without an offset are UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def count_prior_violations(container, records):
    """How many earlier violations each record's user has, with one query per user.

    Counts the user's other violations about content they wrote, flagged before this one. A
    record with no time of its own counts every other one. A user whose history can't be read
    gets None, which the model reads as unknown.
    """
    by_user = {}
    for record_id, record in records.items():
        user_id = record.get('user_id')
        if isinstance(user_id, str) and user_id:
            by_user.setdefault(user_id, []).append(record_id)
    counts = {}
    for user_id, record_ids in by_user.items():
        try:
            rows = [
                row for row in container.query_items(
                    query=_PRIOR_VIOLATIONS_QUERY,
                    parameters=[{'name': '@user_id', 'value': user_id}],
                    enable_cross_partition_query=True,
                )
                if isinstance(row, dict) and row.get('content_origin', 'user') == 'user'
            ]
        except Exception as exc:
            log_event(
                '[REVIEW_ASSIST] A user violation history could not be read.',
                extra={'record_count': len(record_ids), 'error_type': type(exc).__name__},
                level=logging.WARNING,
            )
            for record_id in record_ids:
                counts[record_id] = None
            continue
        for record_id in record_ids:
            flagged_at = _flagged_at(records[record_id].get('created_at'))
            count = 0
            for row in rows:
                if row.get('id') == record_id:
                    continue
                if flagged_at is None:
                    count += 1
                    continue
                other = _flagged_at(row.get('created_at'))
                if other is not None and other < flagged_at:
                    count += 1
            counts[record_id] = count
    return counts


def load_review_records(store, ids):
    """``{id: ReviewRecordInput or None}`` for the requested ids, read and settled on the server."""
    loaded = {}
    for record_id in ids:
        record = _read_record(store.container, record_id)
        if record is None:
            loaded[record_id] = None
            continue
        if store.prepare is not None:
            record = store.prepare(record)
        locked = bool(store.is_locked(record)) if store.is_locked is not None else False
        loaded[record_id] = ReviewRecordInput(record, locked=locked)
    if store.section == 'safety':
        reviewable = {
            record_id: entry.record for record_id, entry in loaded.items()
            if entry is not None and not entry.locked
        }
        for record_id, count in count_prior_violations(store.container, reviewable).items():
            loaded[record_id].prior_violations = count
    return loaded


def persist_review_suggestion(store, record_id, entry, fingerprint, document):
    """Store a suggestion on its record while the record still matches what it was based on.

    The write is conditional on the version read. After a conflict, the latest version is used
    only if its reviewable fields still match the fingerprint: storing a suggestion, or settling
    an unrelated field, does not discard it, but a review saved meanwhile does.
    """

    def mutate(current):
        if review_record_fingerprint(store.section, current) != fingerprint:
            return False
        current[SUGGESTION_RECORD_FIELD] = document
        return True

    try:
        stored = store.replace(record_id, mutate, entry.record)
    except store.conflict_error:
        return 'changed'
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return 'missing'
    return 'saved' if stored is not None else 'changed'


def build_review_assist_services(*, store, client_factory, limiter=None, call_model=None):
    """The real services for one review assist request.

    ``client_factory()`` returns ``(client, model_name)`` for the draft-instructions deployment.
    """
    if limiter is None:
        # Lazy: config connects to Cosmos at import, so tests can build the adapters without it.
        from config import cosmos_settings_container
        from functions_workflow_assist_limits import CosmosAssistLimitStore, WorkflowAssistLimiter
        limiter = WorkflowAssistLimiter(
            CosmosAssistLimitStore(cosmos_settings_container),
            max_requests=REVIEW_ASSIST_LIMIT_REQUESTS,
            window_seconds=REVIEW_ASSIST_LIMIT_WINDOW_SECONDS,
            document_type=REVIEW_ASSIST_LIMIT_DOCUMENT_TYPE,
        )
    answered_by = {}

    def recording_factory():
        client, model_name = client_factory()
        answered_by['model'] = model_name
        return client, model_name

    def log(message, extra, level):
        log_event(message, extra=extra, level=level)

    return ReviewAssistServices(
        limiter=_ConvertingLimiter(limiter),
        call_model=call_model or _ConvertingModel(WorkflowAssistModel(recording_factory)),
        load_records=lambda ids: load_review_records(store, ids),
        persist_suggestion=lambda record_id, entry, fingerprint, document: persist_review_suggestion(
            store, record_id, entry, fingerprint, document,
        ),
        model_name=lambda: answered_by.get('model'),
        log=log,
    )


def read_review_assist_body():
    """The request body as strict JSON. A body that declares too many bytes is refused unread."""
    if not request.is_json:
        raise ReviewAssistError('invalid_request', 'The request body must be a JSON object.')
    declared = request.content_length
    if declared is not None and declared > REVIEW_ASSIST_MAX_BODY_BYTES:
        raise ReviewAssistError('request_too_large')
    try:
        raw = (
            request.get_data(cache=False)
            if declared is not None
            else request.stream.read(REVIEW_ASSIST_MAX_BODY_BYTES + 1)
        )
    except RequestEntityTooLarge:
        raise ReviewAssistError('request_too_large') from None
    except BadRequest:
        raise ReviewAssistError('invalid_request', 'The request body must be a JSON object.') from None
    return parse_review_assist_body(raw)


def review_assist_response(payload, status, *, retry_after=None, user_id=None):
    """The answer as strict JSON, never cached, because it carries review content."""
    try:
        body = json.dumps(payload, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError, RecursionError) as exc:
        log_event(
            '[REVIEW_ASSIST] Assist response could not be serialized',
            extra={'user_id': user_id, 'status': status, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        failure = ReviewAssistError('assistant_failed')
        body = json.dumps(failure.payload(), allow_nan=False, sort_keys=True)
        status, retry_after = failure.status, None
    response = current_app.response_class(f'{body}\n', status=status, mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store, private'
    if retry_after is not None:
        response.headers['Retry-After'] = str(retry_after)
    return response


def review_assist_error_response(error, *, settings=None, user_id=None):
    """The JSON response for a ``ReviewAssistError``."""
    return review_assist_response(error.payload(settings), error.status, retry_after=error.retry_after, user_id=user_id)


def handle_review_assist_request(*, section, actor, settings, store, client_factory):
    """Run one review assist request end to end and return the Flask response.

    The route has already checked the caller's reviewer role and the assistant's toggle. Nothing
    about a review changes here: an analysis is returned for the editor's draft, and a triage
    stores suggestions a reviewer applies or dismisses later.
    """
    user_id = (actor or {}).get('id')
    try:
        if not user_id:
            raise ReviewAssistError('invalid_request', 'No signed-in reviewer was found for this request.')
        body = read_review_assist_body()
        services = build_review_assist_services(store=store, client_factory=client_factory)
        result = run_review_assist(
            body,
            section=section,
            actor=actor,
            guidance=(settings or {}).get('admin_review_ai_guidance'),
            services=services,
        )
    except ReviewAssistError as exc:
        return review_assist_error_response(exc, settings=settings, user_id=user_id)
    except Exception as exc:
        log_event(
            '[REVIEW_ASSIST] Assist request failed before the assistant ran',
            extra={'user_id': user_id, 'section': section, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return review_assist_error_response(ReviewAssistError('assistant_failed'), user_id=user_id)
    return review_assist_response(result, 200, user_id=user_id)
