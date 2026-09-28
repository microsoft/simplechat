# functions_group_document_projection_fence.py
"""Per-source coordination for scoped ACL projections and collaboration changes.

Storage is supplied by callers. Unknown remote outcomes retain their claim;
time passing is not evidence that an old publisher can no longer finish.

The fence is scope-aware rather than group-only: a group hold can never act on a
public document and a public hold can never act on a group document, because
each scope matches its own identity exactly and rejects the other scope's field.
The group entry points keep their original names and behaviour; the public
entry points are thin wrappers over the same implementation.
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
PUBLIC_DOCUMENT_PROJECTION_WRITER = "public_document_projection_writer"
PUBLIC_DOCUMENT_COLLABORATION_OPERATION = "public_document_collaboration_operation"


class GroupDocumentProjectionConflict(RuntimeError):
    """A source cannot safely accept another writer or collaboration change."""

    status_code = 409


class _ProjectionScope:
    """Scope-specific field names so one implementation fences both scopes.

    ``id_field`` is the document field naming the owning scope; ``other_id_field``
    is the field that, when present, proves the document belongs to the *other*
    scope and must therefore be rejected. Per-scope context vars guarantee a
    collaboration or writer context established in one scope can never be read as
    if it belonged to the other.
    """

    __slots__ = (
        "kind", "id_field", "other_id_field", "writer_field",
        "operation_field", "source_key", "collaboration_var", "writer_var",
    )

    def __init__(self, kind, id_field, other_id_field, writer_field, operation_field, source_key):
        self.kind = kind
        self.id_field = id_field
        self.other_id_field = other_id_field
        self.writer_field = writer_field
        self.operation_field = operation_field
        self.source_key = source_key
        self.collaboration_var = ContextVar(f"{kind}_collaboration_projection_context", default=None)
        self.writer_var = ContextVar(f"{kind}_document_projection_writer_context", default=None)


_GROUP_SCOPE = _ProjectionScope(
    kind="group",
    id_field="group_id",
    other_id_field="public_workspace_id",
    writer_field=GROUP_DOCUMENT_PROJECTION_WRITER,
    operation_field=GROUP_DOCUMENT_COLLABORATION_OPERATION,
    source_key="source_group_id",
)
_PUBLIC_SCOPE = _ProjectionScope(
    kind="public",
    id_field="public_workspace_id",
    other_id_field="group_id",
    writer_field=PUBLIC_DOCUMENT_PROJECTION_WRITER,
    operation_field=PUBLIC_DOCUMENT_COLLABORATION_OPERATION,
    source_key="source_public_workspace_id",
)

# Backward-compatible module-level aliases for the group scope's context vars.
# These names predate the scope-aware refactor; they resolve to the exact same
# ContextVar objects the group entry points use, so existing callers and tests
# that introspect the active group collaboration/writer context keep working.
_collaboration_context = _GROUP_SCOPE.collaboration_var
_writer_context = _GROUP_SCOPE.writer_var


def _identity(scope, document):
    return document.get("id"), document.get(scope.id_field), str(document.get("version") or 1)


def _owns_collaboration(scope, document):
    context = scope.collaboration_var.get()
    operation = document.get(scope.operation_field)
    return bool(
        context and isinstance(operation, dict) and operation.get("schema_version") == 1
        and operation.get("document_id") == document.get("id")
        and operation.get(scope.source_key) == document.get(scope.id_field)
        and str(operation.get("document_version") or 1) == _identity(scope, document)[2]
        and operation.get("phase") == "executing"
        and context == (document.get("id"), operation.get("id"), operation.get("execution_token"))
        and all(context)
    )


def _assert_no_projection_writer(scope, document):
    if scope.writer_field in document:
        raise GroupDocumentProjectionConflict(
            "A document projection is active or unconfirmed. Refresh before changing access."
        )


def _assert_source_writable(scope, document):
    writer = document.get(scope.writer_field)
    if scope.writer_field in document:
        context = scope.writer_var.get()
        if not (
            isinstance(writer, dict) and context
            and context == (*_identity(scope, document), writer.get("token"))
            and writer.get("state") == "executing"
        ):
            raise GroupDocumentProjectionConflict("A document projection must finish or be reconciled first.")
    operation = document.get(scope.operation_field)
    if scope.operation_field in document and not (
        isinstance(operation, dict) and operation.get("schema_version") == 1
        and operation.get("phase") == "complete"
    ) and not _owns_collaboration(scope, document):
        raise GroupDocumentProjectionConflict("A collaboration operation must finish or be reconciled first.")


@contextmanager
def _collaboration_projection_context(scope, document_id, operation_id, execution_token):
    if not all(isinstance(value, str) and value for value in (document_id, operation_id, execution_token)):
        raise GroupDocumentProjectionConflict("The collaboration execution identity is unavailable.")
    marker = scope.collaboration_var.set((document_id, operation_id, execution_token))
    try:
        yield
    finally:
        scope.collaboration_var.reset(marker)


def _read_source(scope, container, document_id, scope_id, expected_version=None, *, allow_missing=False):
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
        or document.get(scope.id_field) != scope_id or document.get(scope.other_id_field)
        or not document.get("_etag")
        or (expected_version is not None and _identity(scope, document)[2] != str(expected_version))
    ):
        raise GroupDocumentProjectionConflict("The document identity or revision changed.")
    return document


def _replace_source(scope, container, document, body):
    try:
        result = container.replace_item(
            item=document["id"], body=body,
            etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except HttpResponseError as error:
        if error.status_code in {404, 409, 412}:
            raise GroupDocumentProjectionConflict("The document changed before its projection could be coordinated.") from error
        raise
    if not isinstance(result, dict) or not result.get("_etag") or _identity(scope, result) != _identity(scope, document):
        raise GroupDocumentProjectionConflict("The conditional document write could not be confirmed.")
    return result


def _finish_writer(scope, container, identity, token, *, uncertain):
    document_id, scope_id, version = identity
    for _attempt in range(3):
        current = _read_source(scope, container, document_id, scope_id, version, allow_missing=True)
        if current is None:
            return
        writer = current.get(scope.writer_field)
        if not isinstance(writer, dict) or writer.get("token") != token:
            raise GroupDocumentProjectionConflict("The document projection claim changed.")
        body = copy.deepcopy(current)
        if uncertain:
            body[scope.writer_field] = {**writer, "state": "uncertain"}
        else:
            body.pop(scope.writer_field)
        try:
            _replace_source(scope, container, current, body)
            return
        except GroupDocumentProjectionConflict:
            continue
    raise GroupDocumentProjectionConflict("The document projection claim needs reconciliation.")


@contextmanager
def _hold_document_projection(
    scope, container, document_id, scope_id, *, expected_version=None, allow_missing=False, log=None,
):
    document = _read_source(scope, container, document_id, scope_id, expected_version, allow_missing=allow_missing)
    if document is None:
        yield None
        return
    _assert_source_writable(scope, document)
    identity = _identity(scope, document)
    if _owns_collaboration(scope, document) or (
        scope.writer_var.get() and scope.writer_field in document
        and scope.writer_var.get() == (*identity, document[scope.writer_field].get("token"))
    ):
        yield document
        return
    token = str(uuid.uuid4())
    writer = {
        "schema_version": 1, "token": token, "document_id": document_id,
        scope.id_field: scope_id, "document_version": document.get("version") or 1,
        "state": "executing", "started_at": datetime.now(timezone.utc).isoformat(),
    }
    claimed = _replace_source(scope, container, document, {**copy.deepcopy(document), scope.writer_field: writer})
    marker = scope.writer_var.set((*identity, token))
    try:
        yield claimed
    except BaseException as error:
        known_refusal = isinstance(error, HttpResponseError) and error.status_code in {400, 401, 403, 404, 409, 412, 422}
        if log:
            log(
                f"[DOCUMENTS] {scope.kind.capitalize()} document projection stopped.",
                extra={"document_id": document_id, scope.id_field: scope_id, "uncertain": not known_refusal,
                       "exception_type": type(error).__name__},
                level=logging.ERROR,
            )
        _finish_writer(scope, container, identity, token, uncertain=not known_refusal)
        raise
    else:
        _finish_writer(scope, container, identity, token, uncertain=False)
    finally:
        scope.writer_var.reset(marker)


# --- Group entry points (names and behaviour preserved) --------------------

def assert_no_group_document_projection_writer(document):
    _assert_no_projection_writer(_GROUP_SCOPE, document)


def assert_group_document_source_writable(document):
    _assert_source_writable(_GROUP_SCOPE, document)


@contextmanager
def group_collaboration_projection_context(document_id, operation_id, execution_token):
    with _collaboration_projection_context(_GROUP_SCOPE, document_id, operation_id, execution_token):
        yield


@contextmanager
def hold_group_document_projection(
    container, document_id, group_id, *, expected_version=None, allow_missing=False, log=None,
):
    with _hold_document_projection(
        _GROUP_SCOPE, container, document_id, group_id,
        expected_version=expected_version, allow_missing=allow_missing, log=log,
    ) as document:
        yield document


# --- Public entry points (same implementation, public scope) ---------------

def assert_no_public_document_projection_writer(document):
    _assert_no_projection_writer(_PUBLIC_SCOPE, document)


def assert_public_document_source_writable(document):
    _assert_source_writable(_PUBLIC_SCOPE, document)


@contextmanager
def public_collaboration_projection_context(document_id, operation_id, execution_token):
    with _collaboration_projection_context(_PUBLIC_SCOPE, document_id, operation_id, execution_token):
        yield


@contextmanager
def hold_public_document_projection(
    container, document_id, public_workspace_id, *, expected_version=None, allow_missing=False, log=None,
):
    with _hold_document_projection(
        _PUBLIC_SCOPE, container, document_id, public_workspace_id,
        expected_version=expected_version, allow_missing=allow_missing, log=log,
    ) as document:
        yield document
