# functions_group_document_projection_fence.py
"""Per-source coordination for group ACL projections and collaboration changes.

Storage is supplied by callers. Unknown remote outcomes retain their claim;
time passing is not evidence that an old publisher can no longer finish.
"""

import copy
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError


GROUP_DOCUMENT_PROJECTION_WRITER = "group_document_projection_writer"
GROUP_DOCUMENT_COLLABORATION_OPERATION = "group_document_collaboration_operation"
_collaboration_context = ContextVar("group_collaboration_projection_context", default=None)
_writer_context = ContextVar("group_document_projection_writer_context", default=None)


class GroupDocumentProjectionConflict(RuntimeError):
    """A source cannot safely accept another writer or collaboration change."""


def _identity(document):
    return document.get("id"), document.get("group_id"), str(document.get("version") or 1)


def _owns_collaboration(document):
    context = _collaboration_context.get()
    operation = document.get(GROUP_DOCUMENT_COLLABORATION_OPERATION)
    return bool(
        context and isinstance(operation, dict) and operation.get("schema_version") == 1
        and operation.get("document_id") == document.get("id")
        and operation.get("source_group_id") == document.get("group_id")
        and str(operation.get("document_version") or 1) == _identity(document)[2]
        and operation.get("phase") == "executing"
        and context == (document.get("id"), operation.get("id"), operation.get("execution_token"))
        and all(context)
    )


def assert_no_group_document_projection_writer(document):
    if GROUP_DOCUMENT_PROJECTION_WRITER in document:
        raise GroupDocumentProjectionConflict(
            "A document projection is active or unconfirmed. Refresh before changing access."
        )


def assert_group_document_source_writable(document):
    writer = document.get(GROUP_DOCUMENT_PROJECTION_WRITER)
    if GROUP_DOCUMENT_PROJECTION_WRITER in document:
        context = _writer_context.get()
        if not (
            isinstance(writer, dict) and context
            and context == (*_identity(document), writer.get("token"))
            and writer.get("state") == "executing"
        ):
            raise GroupDocumentProjectionConflict("A document projection must finish or be reconciled first.")
    operation = document.get(GROUP_DOCUMENT_COLLABORATION_OPERATION)
    if GROUP_DOCUMENT_COLLABORATION_OPERATION in document and not (
        isinstance(operation, dict) and operation.get("schema_version") == 1
        and operation.get("phase") == "complete"
    ) and not _owns_collaboration(document):
        raise GroupDocumentProjectionConflict("A collaboration operation must finish or be reconciled first.")


@contextmanager
def group_collaboration_projection_context(document_id, operation_id, execution_token):
    if not all(isinstance(value, str) and value for value in (document_id, operation_id, execution_token)):
        raise GroupDocumentProjectionConflict("The collaboration execution identity is unavailable.")
    marker = _collaboration_context.set((document_id, operation_id, execution_token))
    try:
        yield
    finally:
        _collaboration_context.reset(marker)


def _read_source(container, document_id, group_id, expected_version=None, *, allow_missing=False):
    try:
        document = container.read_item(item=document_id, partition_key=document_id)
    except HttpResponseError as error:
        if error.status_code == 404 and allow_missing:
            return None
        if error.status_code == 404:
            raise GroupDocumentProjectionConflict("The document no longer exists.") from error
        raise
    if (
        not isinstance(document, dict) or document.get("id") != document_id
        or document.get("group_id") != group_id or document.get("public_workspace_id")
        or not document.get("_etag")
        or (expected_version is not None and _identity(document)[2] != str(expected_version))
    ):
        raise GroupDocumentProjectionConflict("The document identity or revision changed.")
    return document


def _replace_source(container, document, body):
    try:
        result = container.replace_item(
            item=document["id"], body=body,
            etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except HttpResponseError as error:
        if error.status_code in {404, 409, 412}:
            raise GroupDocumentProjectionConflict("The document changed before its projection could be coordinated.") from error
        raise
    if not isinstance(result, dict) or not result.get("_etag") or _identity(result) != _identity(document):
        raise GroupDocumentProjectionConflict("The conditional document write could not be confirmed.")
    return result


def _finish_writer(container, identity, token, *, uncertain):
    document_id, group_id, version = identity
    for _attempt in range(3):
        current = _read_source(container, document_id, group_id, version, allow_missing=True)
        if current is None:
            return
        writer = current.get(GROUP_DOCUMENT_PROJECTION_WRITER)
        if not isinstance(writer, dict) or writer.get("token") != token:
            raise GroupDocumentProjectionConflict("The document projection claim changed.")
        body = copy.deepcopy(current)
        if uncertain:
            body[GROUP_DOCUMENT_PROJECTION_WRITER] = {**writer, "state": "uncertain"}
        else:
            body.pop(GROUP_DOCUMENT_PROJECTION_WRITER)
        try:
            _replace_source(container, current, body)
            return
        except GroupDocumentProjectionConflict:
            continue
    raise GroupDocumentProjectionConflict("The document projection claim needs reconciliation.")


@contextmanager
def hold_group_document_projection(
    container, document_id, group_id, *, expected_version=None, allow_missing=False, log=None,
):
    document = _read_source(container, document_id, group_id, expected_version, allow_missing=allow_missing)
    if document is None:
        yield None
        return
    assert_group_document_source_writable(document)
    identity = _identity(document)
    if _owns_collaboration(document) or (
        _writer_context.get() and GROUP_DOCUMENT_PROJECTION_WRITER in document
        and _writer_context.get() == (*identity, document[GROUP_DOCUMENT_PROJECTION_WRITER].get("token"))
    ):
        yield document
        return
    token = str(uuid.uuid4())
    writer = {
        "schema_version": 1, "token": token, "document_id": document_id,
        "group_id": group_id, "document_version": document.get("version") or 1,
        "state": "executing", "started_at": datetime.now(timezone.utc).isoformat(),
    }
    claimed = _replace_source(container, document, {**copy.deepcopy(document), GROUP_DOCUMENT_PROJECTION_WRITER: writer})
    marker = _writer_context.set((*identity, token))
    try:
        yield claimed
    except BaseException as error:
        known_refusal = isinstance(error, HttpResponseError) and error.status_code in {400, 401, 403, 404, 409, 412, 422}
        if log:
            log(
                "[DOCUMENTS] Group document projection stopped.",
                extra={"document_id": document_id, "group_id": group_id, "uncertain": not known_refusal,
                       "exception_type": type(error).__name__},
                level=logging.ERROR,
            )
        _finish_writer(container, identity, token, uncertain=not known_refusal)
        raise
    else:
        _finish_writer(container, identity, token, uncertain=False)
    finally:
        _writer_context.reset(marker)
