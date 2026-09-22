# functions_group_document_publication.py
"""Scoped adapters for the existing durable artifact-publication lifecycle."""

from copy import deepcopy
import logging
from urllib.parse import quote
import uuid

from config import cosmos_group_documents_container
from content_screening.contracts import ScreeningError
from functions_appinsights import log_event
import functions_artifact_publication as publication
from functions_artifact_publication_readiness import (
    PUBLICATION_BINDING, PUBLICATION_SCREENING_CONSUMPTION, SCREENING_BOOTSTRAP_REMEDY,
    publication_handoff_observed,
)
from functions_documents import delete_document_revision, select_current_documents
from functions_group_document_access import (
    GroupDocumentReadError,
    group_document_family_records,
    is_current_group_document,
    read_group_document_record,
    require_group_document_read_context,
)
from functions_group_document_policy import (
    GROUP_DOCUMENT_MANAGER_ROLES,
    group_document_approval_pending,
    group_document_collaboration_operations,
)
from functions_group_document_projection_fence import (
    GROUP_DOCUMENT_COLLABORATION_OPERATION, group_collaboration_projection_context,
)
from functions_notifications import delete_notifications_by_metadata
from functions_settings import get_settings
from utils_cache import invalidate_group_search_cache


PUBLICATION_ACTIONS = {
    "approve_artifact": "approved",
    "reject_artifact": "rejected",
    "cancel_artifact": "cancelled",
}


def _text_or_none(value):
    return value if isinstance(value, str) and value else None


def _has_publication(document):
    return bool(
        group_document_approval_pending(document) or document.get("generated_artifact_promotion_status")
        or document.get("generated_artifact_publication_receipt_id") or document.get(PUBLICATION_BINDING)
    )


def _bootstrap_retry_operation_id(document, receipt, user_id):
    operation = document.get(GROUP_DOCUMENT_COLLABORATION_OPERATION) or {}
    consumption = receipt.get(PUBLICATION_SCREENING_CONSUMPTION) or {}
    if (
        isinstance(operation, dict) and isinstance(consumption, dict)
        and operation.get("schema_version") == 1 and operation.get("action") == "approve_artifact"
        and operation.get("phase") in {"executing", "repair"}
        and operation.get("actor_user_id") == user_id
        and operation.get("actor_group_id") == operation.get("source_group_id") == document.get("group_id")
        and operation.get("document_id") == document.get("id")
        and operation.get("document_version") == document.get("version")
        and isinstance(operation.get("id"), str) and operation["id"]
        and isinstance(operation.get("execution_token"), str) and operation["execution_token"]
        and consumption.get("operation_id") == operation["id"] and "scan_id" not in consumption
        and "approval_queue" not in (receipt.get("stages") or {})
    ):
        return operation["id"]
    return None


def _approval_available(document, settings, *, operation_id=None):
    try:
        return publication.artifact_publication_approval_available(
            document, settings=settings, operation_id=operation_id,
        )
    except ScreeningError as error:
        log_event(
            "[DOCUMENTS] Publication screening admission could not be established.",
            extra={"document_id": document.get("id"), "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        return False


def group_publication_view(document, user_id, group_id, *, context):
    if not _has_publication(document):
        return None
    _group, role, settings, supported = context
    status = "pending_approval" if group_document_approval_pending(document) else document.get("generated_artifact_promotion_status")
    if status not in {"pending_approval", "approved", "approval_failed", "rejected", "cancelled"}:
        status = "unavailable"
    actions = []
    requester = None
    try:
        _artifact, receipt, _bound = publication.read_artifact_publication_request(document)
        requester = receipt["actor_user_id"]
        retry_id = _bootstrap_retry_operation_id(document, receipt, user_id)
        operation = document.get(GROUP_DOCUMENT_COLLABORATION_OPERATION) or {}
        can_approve = operation.get("phase") != "executing" or retry_id is not None
        decision = (receipt.get("decision") or {}).get("choice")
        if decision == "approved":
            status = "approved" if (receipt.get("stages") or {}).get("approval_queue") == "complete" else "approval_failed"
        elif decision in {"rejected", "cancelled"}:
            status = decision
        elif decision is not None or status != "pending_approval":
            status = "unavailable"
        if document.get("group_id") == group_id:
            if decision is None and status == "pending_approval":
                if role in GROUP_DOCUMENT_MANAGER_ROLES:
                    actions.append("reject_artifact")
                    if (
                        can_approve and is_current_group_document(document)
                        and _approval_available(document, settings, operation_id=retry_id)
                    ):
                        actions.append("approve_artifact")
                if requester == user_id:
                    actions.append("cancel_artifact")
            elif decision == "approved" and status in {"approved", "approval_failed"}:
                # A repeated approval observes/reconciles the existing handoff;
                # the canonical receipt never queues it a second time.
                if (
                    can_approve and role in GROUP_DOCUMENT_MANAGER_ROLES
                    and is_current_group_document(document)
                    and _approval_available(document, settings, operation_id=retry_id)
                ):
                    actions.append("approve_artifact")
            elif decision == "rejected" and role in GROUP_DOCUMENT_MANAGER_ROLES:
                actions.append("reject_artifact")
            elif decision == "cancelled" and requester == user_id:
                actions.append("cancel_artifact")
    except (LookupError, PermissionError, ValueError, KeyError):
        status = "unavailable"
        actions = []
    except Exception as error:
        status = "unavailable"
        actions = []
        log_event(
            "[DOCUMENTS] Publication action eligibility could not be established.",
            extra={"document_id": document.get("id"), "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
    return {
        "status": status,
        "is_requester": bool(requester and requester == user_id),
        "requested_by_user_id": _text_or_none(requester or document.get("generated_artifact_requested_by_user_id")),
        "requested_by_display_name": _text_or_none(document.get("generated_artifact_requested_by_display_name")),
        "requested_at": _text_or_none(document.get("generated_artifact_requested_at")),
        "actions": [action for action in supported if action in actions],
    }


def decide_group_document_publication(user_id, group_id, document_id, action, payload):
    # Imported here to keep the state projection and publication adapter acyclic.
    from functions_group_document_collaboration import (
        COLLABORATION_OPERATION,
        GroupDocumentCollaborationError,
        _check_etag,
        _checkpoint,
        _context,
        _operation,
        _operation_document,
        _operation_receipt,
        _replace,
        _unfinished,
        _version,
    )
    from functions_group_document_management import require_payload, validate_group_document_id

    require_payload(payload, {"expected_etag"}, {"expected_etag"})
    validate_group_document_id(document_id)
    group, role, settings, supported = _context(user_id, group_id)
    if action not in PUBLICATION_ACTIONS or action not in supported:
        raise GroupDocumentCollaborationError("publication_forbidden", "Your current group role or status cannot make this decision.", 403)
    document = read_group_document_record(document_id)
    if document.get("group_id") != group_id:
        raise GroupDocumentCollaborationError("publication_forbidden", "Only the destination group can decide this request.", 403)
    _check_etag(document, payload["expected_etag"])
    try:
        artifact, receipt, bound = publication.read_artifact_publication_request(document)
    except (LookupError, PermissionError, ValueError, KeyError) as error:
        raise GroupDocumentCollaborationError(
            "publication_unverifiable", "The existing source and publication request could not be verified. Reconcile it in Classic.", 409,
        ) from error
    choice = PUBLICATION_ACTIONS[action]
    old_choice = (receipt.get("decision") or {}).get("choice")
    if old_choice is not None and old_choice != choice:
        raise GroupDocumentCollaborationError("decision_conflict", "A different publication decision has already committed.", 409)
    if action == "cancel_artifact" and receipt.get("actor_user_id") != user_id:
        raise GroupDocumentCollaborationError("requester_required", "Only the actual requester can cancel this publication.", 403)
    if action != "cancel_artifact" and role not in GROUP_DOCUMENT_MANAGER_ROLES:
        raise GroupDocumentCollaborationError("manager_required", "A destination document manager must make this decision.", 403)
    if choice == "approved" and not is_current_group_document(document):
        raise GroupDocumentCollaborationError("revision_unavailable", "A historical publication request cannot be approved.", 409)
    retry_id = _bootstrap_retry_operation_id(document, receipt, user_id) if choice == "approved" else None
    if choice == "approved" and not _approval_available(document, settings, operation_id=retry_id):
        raise GroupDocumentCollaborationError("publication_unavailable", SCREENING_BOOTSTRAP_REMEDY, 409)
    previous_operation = _operation(document)
    if (
        previous_operation and _unfinished(previous_operation)
        and previous_operation.get("phase") in {"executing", "uncertain"} and not retry_id
    ):
        raise GroupDocumentCollaborationError("operation_busy", "Reconcile the existing document operation before making another decision.", 409)
    if previous_operation and previous_operation.get("phase") not in {"complete", None} and previous_operation.get("action") != action:
        raise GroupDocumentCollaborationError("operation_busy", "A different collaboration operation needs reconciliation.", 409)
    operation_id = retry_id or str(uuid.uuid4())
    execution_token = str(uuid.uuid4())
    operation = {
        "schema_version": 1, "id": operation_id, "document_id": document_id,
        "document_version": _version(document), "source_group_id": group_id,
        "actor_group_id": group_id, "actor_user_id": user_id, "action": action,
        "phase": "executing", "effects": {"decision": "pending"}, "state": "pending_approval",
        "execution_token": execution_token,
    }
    document = _replace(document, {COLLABORATION_OPERATION: operation})
    expected_version = _version(document)
    deleted = False

    def require_execution(current_operation):
        if (
            current_operation.get("phase") != "executing"
            or current_operation.get("execution_token") != execution_token
        ):
            raise GroupDocumentCollaborationError(
                "operation_changed", "The publication operation changed. Refresh before continuing.", 409,
            )

    def checkpoint(change):
        def owned_change(current_operation):
            require_execution(current_operation)
            return change(current_operation)

        return _checkpoint(
            document_id, operation_id, owned_change, execution_token=execution_token,
        )

    def guard():
        current_group, current_role = require_group_document_read_context(user_id, group_id)
        operations = group_document_collaboration_operations(current_group, current_role, get_settings())
        if action not in operations:
            raise PermissionError("The destination no longer permits this decision.")
        if not deleted:
            current, current_operation = _operation_document(document_id, operation_id)
            require_execution(current_operation)
            if current["group_id"] != group_id or _version(current) != expected_version:
                raise ValueError("The destination revision changed.")
            if choice == "approved" and not is_current_group_document(current):
                raise ValueError("The destination became historical.")
            # The canonical receipt checks screening at decision and queue
            # admission. A successfully queued scan remains held during notices.

    def cleanup(current):
        nonlocal deleted
        guard()
        if (
            current.get("group_id") != group_id or current.get("id") != document_id
            or _version(current) != expected_version
        ):
            raise ValueError("The publication cleanup target changed.")
        family = group_document_family_records(current)
        selected_current = select_current_documents(family)
        was_current = bool(selected_current and selected_current[0]["id"] == current["id"])

        def cleanup_guard(document_id=None):
            if document_id is None:
                current_group, current_role = require_group_document_read_context(user_id, group_id)
                if action not in group_document_collaboration_operations(current_group, current_role, get_settings()):
                    raise PermissionError("The destination no longer permits cleanup.")
                return
            guard()
            if document_id is not None and document_id != current["id"]:
                raise PermissionError("Only the requested publication revision may be deleted.")
            latest = read_group_document_record(current["id"])
            if is_current_group_document(latest) != was_current:
                raise ValueError("The publication cleanup revision selection changed.")

        with group_collaboration_projection_context(document_id, operation_id, execution_token):
            delete_document_revision(
                user_id, current["id"], group_id=group_id, delete_mode="current_only",
                family_documents=family, strict=True, operation_guard=cleanup_guard,
                persisted_sources_only=True,
            )
        deleted = True

    errors = []
    try:
        with group_collaboration_projection_context(document_id, operation_id, execution_token):
            if not bound:
                document = publication.enroll_legacy_artifact_publication(
                    document, operation_guard=guard, cleanup_only=choice in {"rejected", "cancelled"},
                )
                artifact, receipt, _bound = publication.read_artifact_publication_request(document)
            publication.decide_artifact_publication(
                user_id, document, choice, operation_guard=guard, delete_destination=cleanup,
                decision_link_url=f"/v2/groups/{quote(group_id, safe='')}/documents?document_id={quote(document_id, safe='')}",
                operation_id=operation_id,
            )
    except Exception as error:
        log_event(
            "[DOCUMENTS] Scoped publication decision needs reconciliation.",
            extra={"document_id": document_id, "action": action, "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        errors.append({"stage": "publication", "code": "publication_reconciliation_required", "message": "The existing decision or processing handoff needs reconciliation; no second copy was requested."})
    latest = publication.cosmos_messages_container.read_item(
        item=artifact["id"], partition_key=artifact["conversation_id"],
    )
    confirmed = ((latest.get("metadata") or {}).get(publication.RECEIPTS_FIELD) or {}).get(receipt["id"]) or {}
    committed_choice = (confirmed.get("decision") or {}).get("choice")
    if committed_choice != choice:
        if not deleted:
            checkpoint(lambda op: {**op, "phase": "repair"})
        raise GroupDocumentCollaborationError(
            "publication_unconfirmed", "The decision was not confirmed. Refresh the existing request before retrying.", 409,
        )
    if choice == "approved":
        current = read_group_document_record(document_id)
        queue_complete = confirmed.get("stages", {}).get("approval_queue") == "complete"
        if not queue_complete and not publication_handoff_observed(confirmed, current):
            errors.append({"stage": "queue", "code": "publication_handoff_unconfirmed", "message": "Approval was recorded, but processing has not been confirmed. Reconcile the existing handoff."})
        state = "approval_failed" if not queue_complete else "approved"
    else:
        try:
            read_group_document_record(document_id)
        except GroupDocumentReadError as error:
            if error.code != 404:
                raise
            deleted = True
        if not deleted:
            errors.append({"stage": "cleanup", "code": "publication_cleanup_incomplete", "message": "The decision was recorded, but its exact destination cleanup is incomplete."})
        state = choice
    required_notification = choice != "cancelled"
    if required_notification and confirmed.get("stages", {}).get("decision_notification") != "complete":
        errors.append({"stage": "notifications", "code": "publication_notification_incomplete", "message": "Decision notification delivery has not been confirmed."})
    if not errors:
        try:
            guard()
            delete_notifications_by_metadata(
                metadata_filters={
                    "group_id": group_id, "document_id": document_id, "publication_receipt_id": receipt["id"],
                    "request_type": "generated_artifact_promotion",
                },
                notification_types=["approval_request_pending", "approval_request_pending_submitter"],
                strict=True,
            )
            guard()
            invalidate_group_search_cache(group_id, document_id=document_id, strict=True)
        except Exception as error:
            log_event(
                "[DOCUMENTS] Publication notice or cache cleanup needs reconciliation.",
                extra={"document_id": document_id, "exception_type": type(error).__name__}, level=logging.ERROR,
            )
            errors.append({"stage": "cleanup", "code": "publication_cleanup_incomplete", "message": "The decision was recorded but notice/cache cleanup needs reconciliation."})
    if not deleted:
        checkpoint(
            lambda op: {**op, "phase": "repair" if errors else "complete", "effects": {"decision": "complete"}, "state": state},
        )
    status = "partial" if errors else "unchanged" if old_choice else "queued" if choice == "approved" else "applied"
    return _operation_receipt(group_id, document, action, None, status, state, errors), (
        207 if errors else 202 if status == "queued" else 200
    )
