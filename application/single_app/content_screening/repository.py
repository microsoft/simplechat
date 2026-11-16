# repository.py
"""Bounded, conditional persistence for screening metadata and document markers.

Application configuration and policy normalization are resolved lazily. Importing
this module never starts Flask, creates containers, or connects to Azure.
"""

import base64
import copy
import importlib
import json
import uuid
from datetime import datetime, timezone
from itertools import islice

from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError

from content_screening.contracts import (
    AVAILABLE_STATES,
    SCREENING_FIELD,
    SCOPE_TYPES,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    hash_payload,
    normalize_identifier,
    subject_from_document,
)


MAX_RECORD_BYTES = 512 * 1024
MAX_PAGE_SIZE = 200
MAX_CURSOR_BYTES = 32768
MAX_DOCUMENT_SELECTION = 1000
RECORD_KINDS = frozenset({
    "policy", "scan", "job", "work_item", "checkpoint", "finding", "event", "audit", "review",
    "model_window",
})
QUERY_FIELDS = frozenset({
    "actor_id", "job_id", "document_id", "subject_key", "scan_id", "state", "status",
    "scope_type", "scope_id", "partition_key", "review_required", "action", "started",
    "postprocess_pending",
})
DOCUMENT_CONTAINERS = {
    "personal": "cosmos_user_documents_container",
    "group": "cosmos_group_documents_container",
    "public": "cosmos_public_documents_container",
}
DOCUMENT_SCOPE_FIELDS = {
    "personal": "user_id", "group": "group_id", "public": "public_workspace_id",
}
SYSTEM_FIELDS = frozenset({"_etag", "_rid", "_self", "_attachments", "_ts"})
DOCUMENT_IDENTITY_FIELDS = frozenset({"id", "version", "user_id", "group_id", "public_workspace_id"})
EVENT_DETAIL_FIELDS = frozenset({
    "state", "previous_state", "finding_count", "error_code", "policy_fingerprint",
    "content_fingerprint", "generation", "job_id",
})


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _not_found(exc):
    return getattr(exc, "status_code", None) == 404 or isinstance(exc, ResourceNotFoundError)


def _raise_write_error(exc):
    if getattr(exc, "status_code", None) in {404, 409, 412}:
        raise ScreeningConflictError() from None
    raise exc


def _identifier(value, field_name="record id"):
    value = normalize_identifier(value, field_name)
    if any(character in value for character in "/\\?#"):
        raise ScreeningValidationError(f"The {field_name} is invalid.")
    return value


def _composite_identifier(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or any(ord(character) < 32 for character in value):
        raise ScreeningValidationError("The screening scope or partition is invalid.")
    return value


def _subject(value):
    return value if isinstance(value, Subject) else Subject.from_dict(value)


def _bounded_json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise ScreeningValidationError("Screening records must contain valid JSON.") from None
    if len(encoded) > MAX_RECORD_BYTES:
        raise ScreeningValidationError("Screening metadata exceeds its storage limit.")
    return encoded


def _page_size(value):
    if type(value) is not int or not 1 <= value <= MAX_PAGE_SIZE:
        raise ScreeningValidationError("The screening page size is invalid.")
    return value


def _cursor(continuation, signature):
    if continuation is None:
        return None
    if not isinstance(continuation, str) or len(continuation) > MAX_CURSOR_BYTES:
        raise ScreeningValidationError("The screening continuation is invalid.")
    try:
        envelope = json.loads(base64.b64decode(continuation, altchars=b"-_", validate=True))
        if envelope["version"] != 1 or envelope["query"] != signature:
            raise ValueError()
        return envelope["token"]
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ScreeningValidationError("The screening continuation is invalid.") from None


def _encode_cursor(token, signature):
    if token is None:
        return None
    result = base64.urlsafe_b64encode(json.dumps(
        {"version": 1, "query": signature, "token": token}, separators=(",", ":"),
    ).encode("utf-8")).decode("ascii")
    if len(result) > MAX_CURSOR_BYTES:
        raise ScreeningError(code="screening_continuation_too_large")
    return result


def _read_page(container, query, parameters, continuation, page_size):
    page_size = _page_size(page_size)
    signature = hash_payload({"query": query, "parameters": parameters})
    after = _cursor(continuation, signature)
    prefix, _separator, ordering = query.rpartition(" ORDER BY ")
    if ordering not in {"c.id", "c.sort_key"}:
        raise ScreeningValidationError("The screening query ordering is invalid.")
    parameters = copy.deepcopy(parameters)
    if after is not None:
        after = _composite_identifier(after)
        prefix += f"{' AND' if ' WHERE ' in prefix else ' WHERE'} {ordering} > @after"
        parameters.append({"name": "@after", "value": after})
    parameters.append({"name": "@page_limit", "value": page_size + 1})
    query = f"{prefix} ORDER BY {ordering}".replace("SELECT *", "SELECT TOP @page_limit *", 1)
    # Python Cosmos cross-partition continuation tokens cannot safely be
    # replayed on a rebuilt query. Persist our stable keyset boundary instead.
    result = container.query_items(
        query=query, parameters=parameters, enable_cross_partition_query=True,
        max_item_count=page_size + 1,
    )
    fetched = list(islice(result, page_size + 1))
    items = fetched[:page_size]
    sort_field = ordering.removeprefix("c.")
    previous = after
    for item in fetched:
        current = _composite_identifier(item.get(sort_field))
        if previous is not None and current <= previous:
            raise ScreeningError(code="screening_page_order_invalid")
        previous = current
    return {
        "items": items,
        "continuation": _encode_cursor(items[-1][sort_field], signature) if len(fetched) > page_size else None,
    }


def _record_query(kind, scope_key=None, filters=None, *, count=False):
    if not isinstance(kind, str) or kind not in RECORD_KINDS:
        raise ScreeningValidationError("The screening record kind is invalid.")
    if filters is not None and not isinstance(filters, dict):
        raise ScreeningValidationError("Screening filters must be an object.")
    if any(field not in QUERY_FIELDS for field in (filters or {})):
        raise ScreeningValidationError("A screening filter is not supported.")
    predicates = ["c.kind = @kind"]
    parameters = [{"name": "@kind", "value": kind}]
    if scope_key is not None:
        predicates.append("c.scope_key = @scope_key")
        parameters.append({"name": "@scope_key", "value": _composite_identifier(scope_key)})
    for index, (field, value) in enumerate(sorted((filters or {}).items())):
        if field not in QUERY_FIELDS:
            raise ScreeningValidationError("A screening filter is not supported.")
        parameter = f"@filter_{index}"
        if isinstance(value, (list, tuple)):
            if not value or len(value) > 32 or any(type(item) not in (str, bool, int) for item in value):
                raise ScreeningValidationError("A screening filter is invalid.")
            value = list(value)
            predicates.append(f"ARRAY_CONTAINS({parameter}, c.{field})")
        elif value is None or type(value) in (str, bool, int):
            predicates.append(f"c.{field} = {parameter}")
        else:
            raise ScreeningValidationError("A screening filter is invalid.")
        if len(json.dumps(value)) > 4096:
            raise ScreeningValidationError("A screening filter exceeds its limit.")
        parameters.append({"name": parameter, "value": value})
    projection = "VALUE COUNT(1)" if count else "*"
    query = f"SELECT {projection} FROM c WHERE {' AND '.join(predicates)}"
    if not count:
        query += " ORDER BY c.sort_key"
    return query, parameters


class ScreeningRepository:
    def __init__(self, container=None, document_containers=None):
        self._container = container
        self._document_containers = dict(document_containers) if document_containers is not None else None

    @property
    def container(self):
        if self._container is None:
            configuration = importlib.import_module("config")
            self._container = getattr(configuration, "cosmos_content_screening_container", None)
        if self._container is None:
            raise ScreeningConfigurationError()
        return self._container

    def document_container(self, scope_type):
        if not isinstance(scope_type, str) or scope_type not in SCOPE_TYPES:
            raise ScreeningValidationError("The content scope is invalid.")
        if self._document_containers is not None:
            container = self._document_containers.get(scope_type)
        else:
            container = getattr(importlib.import_module("config"), DOCUMENT_CONTAINERS[scope_type], None)
        if container is None:
            raise ScreeningConfigurationError()
        return container

    def get(self, record_id, partition_key):
        record_id = _identifier(record_id)
        partition_key = _composite_identifier(partition_key)
        try:
            record = self.container.read_item(item=record_id, partition_key=partition_key)
        except Exception as exc:
            if _not_found(exc):
                return None
            raise
        if record.get("id") != record_id or record.get("partition_key") != partition_key:
            raise ScreeningConflictError()
        return record

    def _prepare_record(self, record):
        if not isinstance(record, dict) or not isinstance(record.get("kind"), str) or record["kind"] not in RECORD_KINDS:
            raise ScreeningValidationError("The screening record is invalid.")
        body = {key: copy.deepcopy(value) for key, value in record.items() if key not in SYSTEM_FIELDS}
        body["id"] = _identifier(body.get("id"))
        body["partition_key"] = _composite_identifier(body.get("partition_key"))
        body["sort_key"] = hash_payload([body["partition_key"], body["id"]])
        if body["kind"] != "event":
            body["ttl"] = -1
        body.setdefault("created_at", _timestamp())
        body.setdefault("updated_at", body["created_at"])
        body.setdefault("schema_version", 1)
        if body.get("subject") is not None:
            subject = _subject(body["subject"])
            if body.get("scope_key", subject.scope_key) != subject.scope_key:
                raise ScreeningConflictError()
            body.update({
                "subject": subject.to_dict(), "subject_key": subject.key, "scope_key": subject.scope_key,
                "scope_type": subject.scope_type, "scope_id": subject.scope_id,
                "document_id": subject.document_id,
            })
        _bounded_json(body)
        return body

    def create(self, record):
        body = self._prepare_record(record)
        try:
            return self.container.create_item(body=body)
        except Exception as exc:
            _raise_write_error(exc)

    def replace(self, record, etag):
        if not isinstance(etag, str) or not etag:
            raise ScreeningConflictError()
        body = self._prepare_record(record)
        try:
            return self.container.replace_item(
                item=body["id"], body=body, etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            _raise_write_error(exc)

    def query(self, kind, scope_key=None, *, filters=None, continuation=None, page_size=50):
        query, parameters = _record_query(kind, scope_key, filters)
        return _read_page(self.container, query, parameters, continuation, page_size)

    def count(self, kind, scope_key=None, *, filters=None):
        """Use a scalar aggregate rather than loading a job's work-item history."""
        query, parameters = _record_query(kind, scope_key, filters, count=True)
        values = list(self.container.query_items(
            query=query, parameters=parameters, enable_cross_partition_query=True,
        ))
        if len(values) != 1 or type(values[0]) is not int or values[0] < 0:
            raise ScreeningError(code="screening_count_unavailable")
        return values[0]

    def query_documents(self, scope_type, scope_id=None, *, document_ids=None, continuation=None, page_size=50):
        """Enumerate physical records, including archived/reachable revisions."""
        container = self.document_container(scope_type)
        conditions, parameters = [], []
        if scope_id is not None:
            conditions.append(f"c.{DOCUMENT_SCOPE_FIELDS[scope_type]} = @scope_id")
            parameters.append({"name": "@scope_id", "value": normalize_identifier(scope_id, "scope")})
        if document_ids is not None:
            if not isinstance(document_ids, (list, tuple)) or not 1 <= len(document_ids) <= MAX_DOCUMENT_SELECTION:
                raise ScreeningValidationError("The document selection is invalid.")
            conditions.append("ARRAY_CONTAINS(@document_ids, c.id)")
            parameters.append({
                "name": "@document_ids",
                "value": [normalize_identifier(value, "document") for value in document_ids],
            })
        query = "SELECT * FROM c"
        if conditions:
            query += f" WHERE {' AND '.join(conditions)}"
        query += " ORDER BY c.id"
        return _read_page(container, query, parameters, continuation, page_size)

    def read_document(self, subject):
        subject = _subject(subject)
        try:
            document = self.document_container(subject.scope_type).read_item(
                item=subject.document_id, partition_key=subject.document_id,
            )
        except Exception as exc:
            if _not_found(exc):
                raise ScreeningConflictError(code="screening_source_missing") from None
            raise
        if subject_from_document(document) != subject:
            raise ScreeningConflictError()
        return document

    def update_document(self, subject, updates, *, etag):
        subject = _subject(subject)
        if not isinstance(updates, dict):
            raise ScreeningValidationError("Document changes must be an object.")
        if any(key in DOCUMENT_IDENTITY_FIELDS or key.startswith("_") for key in updates):
            raise ScreeningValidationError("Document identity cannot be changed by screening.")
        document = self.read_document(subject)
        if not isinstance(etag, str) or not etag or document.get("_etag") != etag:
            raise ScreeningConflictError()
        body = {key: copy.deepcopy(value) for key, value in document.items() if key not in SYSTEM_FIELDS}
        body.update(copy.deepcopy(updates))
        _bounded_json(body)
        marker = updates.get(SCREENING_FIELD)
        if isinstance(marker, dict) and marker.get("state") in AVAILABLE_STATES:
            # Fence the actual release write, including processors that forgot
            # to check their job lease before returning a successful result.
            jobs = importlib.import_module("content_screening.jobs")
            context = jobs.PROCESSOR_CONTEXT.get()
            if context is not None:
                # Checkpoint the exact projection before its release CAS. A
                # restarted worker cannot waive an unrelated source change.
                jobs.checkpoint_scan_job_item(context["job_id"], subject, {
                    "publication_source_fingerprint": jobs._source_fingerprint(body),
                }, repository=self)
                jobs.assert_scan_job_active(context["job_id"], subject, repository=self)
        try:
            return self.document_container(subject.scope_type).replace_item(
                item=subject.document_id, body=body, etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            _raise_write_error(exc)

    def _policy_identity(self, scope_type, scope_id):
        if not isinstance(scope_type, str) or scope_type not in SCOPE_TYPES | {"global"}:
            raise ScreeningValidationError("The policy scope is invalid.")
        scope_id = normalize_identifier(scope_id, "scope")
        if scope_type == "global" and scope_id != "global":
            raise ScreeningValidationError("The baseline policy scope is invalid.")
        return f"policy-{hash_payload([scope_type, scope_id])}", f"policy:{scope_type}:{scope_id}"

    def get_policy(self, scope_type, scope_id):
        scope_id = normalize_identifier(scope_id, "scope")
        record_id, partition = self._policy_identity(scope_type, scope_id)
        record = self.get(record_id, partition)
        if record and (
            record.get("kind") != "policy" or record.get("scope_type") != scope_type
            or record.get("scope_id") != str(scope_id)
        ):
            raise ScreeningConflictError()
        return record

    def save_policy(self, scope_type, scope_id, policy, actor_id, *, etag=None):
        scope_id = normalize_identifier(scope_id, "scope")
        record_id, partition = self._policy_identity(scope_type, scope_id)
        # Policy code is optional until an application policy operation is requested.
        policies = importlib.import_module("content_screening.policies")
        normalized = policies.normalize_policy(policy, scope_type=scope_type)
        if scope_type != "global":
            baseline = self.get_policy("global", "global")
            policies.compose_policy(
                baseline["policy"] if baseline else policies.default_policy(), normalized,
            )
        existing = self.get_policy(scope_type, scope_id)
        body = {
            "id": record_id, "partition_key": partition, "kind": "policy",
            "scope_key": f"{scope_type}:{scope_id}", "scope_type": scope_type,
            "scope_id": str(scope_id), "policy": normalized,
            "actor_id": normalize_identifier(actor_id, "actor"),
            "revision": int(existing.get("revision", 0)) + 1 if existing else 1,
            "policy_fingerprint": hash_payload(normalized), "updated_at": _timestamp(),
            "created_at": existing["created_at"] if existing else _timestamp(),
        }
        if existing:
            if not etag or existing.get("_etag") != etag:
                raise ScreeningConflictError()
            return self.replace(body, etag)
        if etag is not None:
            raise ScreeningConflictError()
        return self.create(body)

    def get_scan(self, scan_id):
        record = self.get(scan_id, scan_id)
        if record and record.get("kind") != "scan":
            raise ScreeningConflictError()
        return record

    def append_event(self, subject, action, actor_id, details=None, scan_id=None, event_id=None):
        subject = _subject(subject)
        action = normalize_identifier(action, "action")
        if len(action) > 80 or not action.replace("_", "").isalnum():
            raise ScreeningValidationError("The screening event action is invalid.")
        if details is not None and (
            not isinstance(details, dict) or set(details) - EVENT_DETAIL_FIELDS
            or any(type(value) not in (str, bool, int, type(None)) for value in details.values())
        ):
            raise ScreeningValidationError("The screening event details are invalid.")
        if len(json.dumps(details or {})) > 2048:
            raise ScreeningValidationError("The screening event exceeds its limit.")
        record = {
            "id": f"event-{hash_payload([subject.key, event_id or uuid.uuid4().hex])}",
            "partition_key": subject.key, "kind": "event", "subject": subject.to_dict(),
            "action": action, "actor_id": normalize_identifier(actor_id, "actor"),
            "scan_id": scan_id, "details": copy.deepcopy(details or {}),
            "ttl": 90 * 24 * 60 * 60,
        }
        try:
            return self.create(record)
        except ScreeningConflictError:
            existing = self.get(record["id"], record["partition_key"])
            if not existing or any(existing.get(key) != record[key] for key in ("subject", "action", "actor_id", "scan_id", "details")):
                raise
            return existing


def preserve_screening_on_transfer(document, *, operation, previous_document=None):
    """Require explicit dependency revalidation after a restore or migration.

    Blob ETags are account-specific. A copied approval cannot authorize a different
    account's artifacts merely because its Cosmos marker was successfully copied.
    """
    result = copy.deepcopy(document)
    if operation not in {"restore", "migration"}:
        raise ScreeningValidationError("The screening transfer operation is invalid.")
    if result.get("kind") in {"job", "work_item"} and result.get("partition_key"):
        result.update({
            "status": "incomplete", "lease": None, "dependency_validation_required": True,
            "error_code": "screening_transferred_dependencies",
        })
    previous = (previous_document or {}).get(SCREENING_FIELD)
    if SCREENING_FIELD not in result and previous is None:
        return result
    incoming = result.get(SCREENING_FIELD)
    marker = copy.deepcopy(incoming) if isinstance(incoming, dict) else {}
    if isinstance(previous, dict):
        if not marker:
            marker = copy.deepcopy(previous)
        if previous.get("review_required") or previous.get("finding_count"):
            marker["review_required"] = True
            marker["previous_review_scan_id"] = previous.get("scan_id")
        if previous.get("state") in {"rejected", "deleting", "deleted"}:
            marker["state"] = previous["state"]
    marker.update({
        "state": marker.get("state") if marker.get("state") in {
            "pending_review", "remediating", "rejected", "deleting", "deleted",
        } else "incomplete",
        "dependency_validation_required": True,
        "error_code": "screening_transferred_dependencies",
        "transfer_operation": operation, "updated_at": _timestamp(),
        "generation": int(marker.get("generation", 0) or 0) + 1,
    })
    result[SCREENING_FIELD] = marker
    return result


def get_repository():
    return ScreeningRepository()
