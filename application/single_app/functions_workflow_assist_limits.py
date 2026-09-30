# functions_workflow_assist_limits.py
"""
Per-user limits for the AI workflow assistant: one request in flight and a fixed request window.

Version: 0.261.206
Implemented in: 0.261.206

The limits must hold across Gunicorn workers and App Service instances, so the counter lives in
Cosmos. It follows ``check_inbound_mcp_tool_rate_limit``: one document per user in the settings
container (partition ``/id``), read and then created or replaced under an etag compare-and-swap.

* **One request in flight.** Acquiring sets a lease that outlives the request deadline. A second
  request while the lease is set gets 429 ``assistant_busy``. Releasing clears the lease.
* **A fixed window.** At most ``ASSIST_LIMIT_REQUESTS`` requests per
  ``ASSIST_LIMIT_WINDOW_SECONDS``. Over it, 429 ``assistant_rate_limited``, with ``Retry-After``
  set to the seconds until the window ends.
* **Refunds.** A request that ends before any model call (a stale base, say) is refunded when it
  releases, so it doesn't use up the window.
* **Fails closed.** When the store can't be read or written, the request gets 503
  ``assistant_limit_unavailable``; the model is never called without the limit.

This document is the assistant's only write. It holds a SHA-256 of the user ID, a count and
timestamps, and never any request content.
"""

import hashlib
import math
import time
import uuid
from datetime import datetime, timezone

from azure.core import MatchConditions

from functions_workflow_assist import WorkflowAssistError


ASSIST_LIMIT_DOCUMENT_TYPE = 'workflow_assist_rate_limit'
ASSIST_LIMIT_REQUESTS = 20
ASSIST_LIMIT_WINDOW_SECONDS = 600
# Longer than the 150-second request deadline, so a lease outlives its request only when the
# worker holding it died; it then expires on its own.
ASSIST_LEASE_SECONDS = 180
ASSIST_BUSY_RETRY_AFTER_SECONDS = 1
ASSIST_LIMIT_WRITE_ATTEMPTS = 4


class AssistLimitStoreError(Exception):
    """The rate-limit store could not be read or written."""


class AssistLimitConflict(Exception):
    """A compare-and-swap write lost a race with another request."""


def assist_limit_document_id(user_id):
    """The user's limit document ID; the user ID itself is never stored."""
    digest = hashlib.sha256(str(user_id).encode('utf-8')).hexdigest()
    return f'{ASSIST_LIMIT_DOCUMENT_TYPE}:{digest}'


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _whole_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(value)


class CosmosAssistLimitStore:
    """The limit documents, in a Cosmos container partitioned by ``/id``."""

    def __init__(self, container):
        self._container = container

    def read(self, document_id):
        """The document, or None when there is none. Raises ``AssistLimitStoreError``."""
        try:
            return self._container.read_item(item=document_id, partition_key=document_id)
        except Exception as exc:
            if getattr(exc, 'status_code', None) == 404:
                return None
            raise AssistLimitStoreError('The rate-limit document could not be read.') from exc

    def create(self, document):
        """Create the document. Raises ``AssistLimitConflict`` when it already exists."""
        try:
            self._container.create_item(body=document)
        except Exception as exc:
            if getattr(exc, 'status_code', None) == 409:
                raise AssistLimitConflict() from exc
            raise AssistLimitStoreError('The rate-limit document could not be created.') from exc

    def replace(self, document, etag):
        """Replace the document if it still has ``etag``. Raises ``AssistLimitConflict`` otherwise."""
        try:
            self._container.replace_item(
                item=document['id'], body=document, etag=etag, match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            if getattr(exc, 'status_code', None) in (404, 409, 412):
                raise AssistLimitConflict() from exc
            raise AssistLimitStoreError('The rate-limit document could not be updated.') from exc


class AssistLease:
    """One acquired request: what ``release`` needs to clear its lease and refund its count."""

    __slots__ = ('user_id', 'document_id', 'lease_id', 'window_start')

    def __init__(self, user_id, document_id, lease_id, window_start):
        self.user_id = user_id
        self.document_id = document_id
        self.lease_id = lease_id
        self.window_start = window_start


class WorkflowAssistLimiter:
    """The per-user limits over a store with ``read``, ``create`` and ``replace`` (see ``CosmosAssistLimitStore``)."""

    def __init__(self, store, *, clock=time.time, max_requests=ASSIST_LIMIT_REQUESTS,
                 window_seconds=ASSIST_LIMIT_WINDOW_SECONDS, lease_seconds=ASSIST_LEASE_SECONDS):
        self._store = store
        self._clock = clock
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lease_seconds = lease_seconds

    def _window(self, current, now):
        """The current window's start and count, starting a new window when the last one ended."""
        if not isinstance(current, dict):
            return now, 0
        start = _whole_number(current.get('window_start_epoch'))
        count = _whole_number(current.get('count'))
        if start is None or count is None or count < 0 or not 0 <= now - start < self._window_seconds:
            return now, 0
        return start, count

    def acquire(self, user_id):
        """Count one request and set its lease, or raise ``WorkflowAssistError`` (429 or 503)."""
        document_id = assist_limit_document_id(user_id)
        for _attempt in range(ASSIST_LIMIT_WRITE_ATTEMPTS):
            now = int(self._clock())
            try:
                current = self._store.read(document_id)
            except AssistLimitStoreError as exc:
                raise WorkflowAssistError('assistant_limit_unavailable') from exc
            lease_expires_at = _whole_number((current or {}).get('lease_expires_at'))
            if (current or {}).get('lease_id') and lease_expires_at is not None and lease_expires_at > now:
                raise WorkflowAssistError('assistant_busy', retry_after=ASSIST_BUSY_RETRY_AFTER_SECONDS)
            window_start, count = self._window(current, now)
            if count >= self._max_requests:
                retry_after = min(self._window_seconds, max(1, window_start + self._window_seconds - now))
                raise WorkflowAssistError('assistant_rate_limited', retry_after=retry_after)
            lease_id = uuid.uuid4().hex
            document = {
                'id': document_id,
                'type': ASSIST_LIMIT_DOCUMENT_TYPE,
                'window_start_epoch': window_start,
                'window_seconds': self._window_seconds,
                'count': count + 1,
                'lease_id': lease_id,
                'lease_expires_at': now + self._lease_seconds,
                'updated_at': _utc_now_iso(),
            }
            try:
                if current is None:
                    self._store.create(document)
                else:
                    self._store.replace(document, current.get('_etag'))
            except AssistLimitConflict:
                continue
            except AssistLimitStoreError as exc:
                raise WorkflowAssistError('assistant_limit_unavailable') from exc
            return AssistLease(user_id, document_id, lease_id, window_start)
        # Every write lost a race, so another request for this user is starting right now.
        raise WorkflowAssistError('assistant_busy', retry_after=ASSIST_BUSY_RETRY_AFTER_SECONDS)

    def release(self, lease, *, refund=False):
        """Clear ``lease``, refunding its count when ``refund`` is set and its window is still current.

        A lease that already expired and was replaced by a later request is left alone. Raises
        ``AssistLimitStoreError`` when the store fails; the caller logs it, and the lease expires
        on its own.
        """
        if lease is None:
            return
        for _attempt in range(ASSIST_LIMIT_WRITE_ATTEMPTS):
            current = self._store.read(lease.document_id)
            if not isinstance(current, dict) or current.get('lease_id') != lease.lease_id:
                return
            document = {key: value for key, value in current.items() if not str(key).startswith('_')}
            document.update({'lease_id': None, 'lease_expires_at': 0, 'updated_at': _utc_now_iso()})
            count = _whole_number(current.get('count'))
            if refund and _whole_number(current.get('window_start_epoch')) == lease.window_start and count:
                document['count'] = max(0, count - 1)
            try:
                self._store.replace(document, current.get('_etag'))
                return
            except AssistLimitConflict:
                continue
        raise AssistLimitStoreError('The rate-limit lease could not be released.')
