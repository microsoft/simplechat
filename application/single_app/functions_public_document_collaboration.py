# functions_public_document_collaboration.py
"""Public-workspace document collaboration primitives: operation lifecycle and
explicit effect receipts.

Public workspaces have no cross-workspace share relationship yet (that arrives
with M3D). This module therefore ships only the generic, revision-bound
operation/write-safety machinery that the generated-artifact publication
adapter needs; the share roster, sharing state, and share/unshare decisions
land in M3D onto this same module, exactly as the group collaboration module
holds both today.

The workspace identity is always taken from the caller's explicit target, never
from a stored active-workspace preference.
"""

from copy import deepcopy
import logging

from azure.core import MatchConditions

from config import cosmos_public_documents_container
from functions_appinsights import log_event
from functions_group_document_projection_fence import (
    GroupDocumentProjectionConflict,
    assert_no_public_document_projection_writer,
)
from functions_public_document_access import (
    PublicDocumentReadError,
    read_public_document_record,
    require_public_document_read_context,
)
from functions_public_document_policy import (
    PUBLIC_DOCUMENT_MANAGER_ROLES,
    public_document_collaboration_operations,
    public_document_has_publication,
)
from functions_settings import get_settings


COLLABORATION_OPERATION = "public_document_collaboration_operation"
ARTIFACT_ACTIONS = frozenset({"approve_artifact", "reject_artifact", "cancel_artifact"})


class PublicDocumentCollaborationError(PublicDocumentReadError):
    def __init__(self, error_code, message, status_code):
        super().__init__(message, status_code)
        self.error_code = error_code


def collaboration_error_response(error, *, public_workspace_id=None, document_id=None):
    if isinstance(error, PublicDocumentCollaborationError):
        code, message, status = error.error_code, error.description, error.code
    elif isinstance(error, PublicDocumentReadError):
        code, message, status = "collaboration_unavailable", error.description, error.code
    elif isinstance(error, GroupDocumentProjectionConflict):
        code, message, status = "projection_busy", "A document projection must finish or be reconciled before this decision.", 409
    elif getattr(error, "status_code", None) in {409, 412}:
        code, message, status = "state_conflict", "The document state changed. Refresh before retrying.", 409
    elif getattr(error, "status_code", None) == 404 or isinstance(error, LookupError):
        code, message, status = "collaboration_gone", "The document or request is no longer available.", 404
    else:
        log_event(
            "[DOCUMENTS] Scoped public collaboration could not be confirmed.",
            extra={"public_workspace_id": public_workspace_id, "document_id": document_id, "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        code, message, status = (
            "collaboration_unconfirmed",
            "The outcome could not be confirmed. Refresh the existing request before any further action.",
            503,
        )
    return {"error": code, "message": message}, status


def _version(document):
    value = document.get("version", 1)
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit() or int(value) < 1:
        raise PublicDocumentCollaborationError("revision_unavailable", "The document revision is unavailable.", 409)
    return int(value)


def _expected_etag(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or value != value.strip():
        raise PublicDocumentCollaborationError("invalid_etag", "A current expected_etag is required.", 400)
    return value


def _check_etag(document, expected):
    _expected_etag(expected)
    if not document.get("_etag") or document["_etag"] != expected:
        raise PublicDocumentCollaborationError("state_conflict", "The document state changed. Refresh before retrying.", 409)


def _operation(document):
    value = document.get(COLLABORATION_OPERATION)
    return value if isinstance(value, dict) and value.get("schema_version") == 1 else {}


def _operation_bound(document, operation):
    return (
        operation.get("document_id") == document.get("id")
        and operation.get("source_public_workspace_id") == document.get("public_workspace_id")
        and operation.get("document_version") == _version(document)
        and isinstance(operation.get("id"), str) and bool(operation["id"])
    )


def _unfinished(operation):
    return operation.get("phase") != "complete"


def _context(user_id, public_workspace_id):
    workspace, role = require_public_document_read_context(user_id, public_workspace_id)
    settings = get_settings()
    operations = public_document_collaboration_operations(workspace, role, settings)
    if not operations:
        raise PublicDocumentCollaborationError("collaboration_disabled", "Public document collaboration is unavailable.", 403)
    return workspace, role, settings, operations


def _replace(document, updates):
    replacement = {**deepcopy(document), **deepcopy(updates)}
    assert_no_public_document_projection_writer(document)
    try:
        saved = cosmos_public_documents_container.replace_item(
            item=document["id"], body=replacement, etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except Exception as error:
        if getattr(error, "status_code", None) in {404, 409, 412}:
            raise PublicDocumentCollaborationError("state_conflict", "The document state changed. Refresh before retrying.", 409) from error
        raise PublicDocumentCollaborationError(
            "write_outcome_uncertain", "A conditional write could not be confirmed. Refresh; do not blindly repeat the action.", 503,
        ) from error
    if not isinstance(saved, dict) or not saved.get("_etag") or saved.get("id") != document["id"]:
        raise PublicDocumentCollaborationError("write_outcome_uncertain", "The document update could not be confirmed.", 503)
    return saved


def _operation_document(document_id, operation_id):
    document = read_public_document_record(document_id)
    operation = _operation(document)
    if not _operation_bound(document, operation) or operation.get("id") != operation_id:
        raise PublicDocumentCollaborationError("operation_changed", "The collaboration operation changed. Refresh before continuing.", 409)
    return document, operation


def _checkpoint(document_id, operation_id, change, *, execution_token=None):
    for _attempt in range(3):
        document, operation = _operation_document(document_id, operation_id)
        if execution_token is not None and operation.get("execution_token") != execution_token:
            raise PublicDocumentCollaborationError("operation_busy", "This operation is being reconciled by another request.", 409)
        updated = change(deepcopy(operation))
        try:
            return _replace(document, {COLLABORATION_OPERATION: updated})
        except PublicDocumentCollaborationError as error:
            if error.error_code != "state_conflict":
                raise
    raise PublicDocumentCollaborationError("operation_busy", "The document is changing. Refresh before continuing.", 409)


def _operation_receipt(public_workspace_id, document, action, status, state, errors):
    return {
        "schema_version": 1, "public_workspace_id": public_workspace_id, "document_id": document["id"],
        "action": action, "status": status, "state": state, "errors": errors,
    }


def _publication_view(document, user_id, public_workspace_id, context):
    # Deferred import keeps the operation lifecycle and the publication adapter
    # acyclic, matching the group collaboration/publication split.
    from functions_public_document_publication import public_publication_view

    return public_publication_view(document, user_id, public_workspace_id, context=context)


def public_document_publication_state(user_id, public_workspace_id, document_id):
    """Read-only generated-artifact publication state for one public document.

    There is no share relationship to project (that arrives with M3D), so this
    envelope carries only the fresh collaboration actions and the publication
    block. Authorization and workspace status are revalidated on every read.
    """
    from functions_public_document_management import validate_public_document_id

    validate_public_document_id(document_id)
    workspace, role, settings, supported = _context(user_id, public_workspace_id)
    document = read_public_document_record(document_id)
    if document.get("public_workspace_id") != public_workspace_id:
        raise PublicDocumentCollaborationError("collaboration_gone", "The document is not available in this public workspace.", 404)
    if not document.get("_etag"):
        raise PublicDocumentCollaborationError("state_unavailable", "Conditional document state is unavailable.", 409)
    actions = get_public_document_collaboration_actions(
        document, user_id, public_workspace_id, context=(workspace, role), settings=settings, supported=supported,
    )
    publication = _publication_view(document, user_id, public_workspace_id, (workspace, role, settings, supported))
    _context(user_id, public_workspace_id)
    return {
        "schema_version": 1, "public_workspace_id": public_workspace_id, "document_id": document_id,
        "document_version": _version(document), "etag": document["_etag"],
        "actions": actions, "publication": publication,
    }


def get_public_document_collaboration_actions(
    document, user_id, public_workspace_id, *, context=None, settings=None, supported=None,
):
    """Compute per-document collaboration actions fresh from current authorization.

    Only generated-artifact actions exist for public workspaces today; sharing
    actions arrive with M3D. Never served from storage — a stored copy is
    redacted by ``PRIVATE_DOCUMENT_FIELDS`` precisely so it cannot go stale.
    """
    if context is None:
        workspace, role, settings, supported = _context(user_id, public_workspace_id)
    else:
        workspace, role = context
        settings = settings if settings is not None else get_settings()
        supported = supported if supported is not None else public_document_collaboration_operations(workspace, role, settings)
    if not supported:
        return []
    try:
        assert_no_public_document_projection_writer(document)
    except GroupDocumentProjectionConflict:
        return ["inspect"] if "inspect" in supported else []
    if document.get("public_workspace_id") != public_workspace_id:
        return []
    has_publication = public_document_has_publication(document)
    actions = {"inspect"}
    operation = _operation(document)
    if operation and _unfinished(operation):
        if operation.get("phase") in {"claimed", "repair"} and _operation_bound(document, operation):
            pending_action = operation.get("action")
            if pending_action in ARTIFACT_ACTIONS and has_publication:
                publication_state = _publication_view(document, user_id, public_workspace_id, (workspace, role, settings, supported))
                if publication_state and pending_action in publication_state["actions"]:
                    actions.add(pending_action)
        elif (
            operation.get("phase") == "executing" and _operation_bound(document, operation)
            and operation.get("action") == "approve_artifact" and has_publication
        ):
            # Only receipt-proven pre-queue bootstrap recovery is advertised by
            # the publication adapter; no other executing operation is replayable.
            publication_state = _publication_view(document, user_id, public_workspace_id, (workspace, role, settings, supported))
            if publication_state and "approve_artifact" in publication_state["actions"]:
                actions.add("approve_artifact")
        return [action for action in supported if action in actions]
    if has_publication:
        publication = _publication_view(document, user_id, public_workspace_id, (workspace, role, settings, supported))
        if publication:
            actions.update(publication["actions"])
    return [action for action in supported if action in actions]
