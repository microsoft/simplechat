# functions_artifact_publication.py
"""Explicit workspace publication of existing artifacts, with scoped retry receipts."""

from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
import uuid

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from config import (
    cosmos_conversations_container,
    cosmos_group_documents_container,
    cosmos_messages_container,
    cosmos_notifications_container,
    cosmos_public_documents_container,
    cosmos_user_documents_container,
)
from content_screening.access import public_document_payload
from content_screening.contracts import SCREENING_FIELD, ScreeningError, hash_payload, subject_from_document
from functions_appinsights import log_event
from functions_artifact_publication_readiness import (
    PUBLICATION_BINDING, PUBLICATION_SCREENING_CONSUMPTION, PUBLICATION_SCREENING_RESERVATION,
    SCREENING_BOOTSTRAP_REMEDY, inspect_publication_readiness, publication_binding_matches,
    publication_handoff_observed, publication_processing_observation, public_publication_status,
    publication_screening_reservation,
)
from functions_collaboration import build_conversation_participation_context
from functions_documents import allowed_file, create_document, update_document
from functions_generated_file_approvals import assert_generated_file_approval_allows_download
from functions_generated_artifact_sources import authorize_generated_artifact_source, has_generated_artifact_source
from functions_group import assert_group_role, check_group_status_allows_operation, find_group_by_id
from functions_notifications import create_group_notification, create_notification, create_public_workspace_notification
from functions_personal_workflows import normalize_workflow_publication
from functions_public_workspaces import (
    check_public_workspace_status_allows_operation,
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)
from functions_saved_analysis import authorize_analysis_artifact
from functions_simplechat_operations import (
    _write_temp_generated_file,
    assert_generated_chat_artifact_is_published_for_user,
    download_blob_content,
    queue_generated_document_processing,
)
from utils_cache import invalidate_group_search_cache, invalidate_personal_search_cache


RECEIPTS_FIELD = "generated_artifact_workspace_publications"
MAX_ARTIFACT_PUBLICATION_REQUESTS = 100


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(f"{label} is required.")
    return value.strip()


def _authorize_artifact(user_id, conversation_id, message_id):
    conversation = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
    build_conversation_participation_context(user_id, conversation)
    artifact = cosmos_messages_container.read_item(item=message_id, partition_key=conversation_id)
    metadata = artifact.get("metadata") or {}
    if (
        artifact.get("id") != message_id or artifact.get("conversation_id") != conversation_id
        or artifact.get("role") != "file" or not metadata.get("is_generated_chat_artifact")
        or artifact.get("file_content_source") != "blob"
        or not artifact.get("blob_container") or not artifact.get("blob_path")
    ):
        raise LookupError("Generated artifact is unavailable.")
    assert_generated_file_approval_allows_download(user_id, artifact)
    assert_generated_chat_artifact_is_published_for_user(user_id, artifact)
    authorize_generated_artifact_source(
        user_id, artifact, for_publication=True, native_authorizer=authorize_analysis_artifact,
    )
    return artifact


def _authorize_destination(user_id, destination, *, operation="upload"):
    if not isinstance(destination, dict):
        raise ValueError("Choose an explicit publication destination.")
    scope = _text(destination.get("workspace_scope"), "Publication destination").lower()
    if scope not in {"personal", "group", "public"}:
        raise ValueError("Publication destination must be personal, group, or public.")
    field = {"group": "group_id", "public": "public_workspace_id"}.get(scope)
    if any(destination.get(key) for key in ("group_id", "public_workspace_id") if key != field):
        raise ValueError("Publication must have exactly one destination.")
    normalized = {"workspace_scope": scope}
    if scope == "personal":
        return normalized, "your personal workspace", cosmos_user_documents_container
    target_id = _text(destination.get(field), "Publication workspace id")
    normalized[field] = target_id
    if scope == "group":
        assert_group_role(user_id, target_id, allowed_roles=("Owner", "Admin", "DocumentManager", "User"))
        workspace = find_group_by_id(target_id)
        if not workspace:
            raise LookupError("Publication workspace is unavailable.")
        allowed, _ = check_group_status_allows_operation(workspace, operation)
        container = cosmos_group_documents_container
    else:
        workspace = find_public_workspace_by_id(target_id)
        if not workspace or get_user_role_in_public_workspace(workspace, user_id) not in {
            "Owner", "Admin", "DocumentManager",
        }:
            raise PermissionError("You cannot publish to this public workspace.")
        allowed, _ = check_public_workspace_status_allows_operation(workspace, operation)
        container = cosmos_public_documents_container
    if not allowed:
        raise PermissionError(
            "This workspace does not currently allow uploads." if operation == "upload"
            else "This workspace does not currently allow publication cleanup."
        )
    return normalized, str(workspace.get("name") or f"{scope} workspace"), container


def _artifact_identity(artifact):
    metadata = artifact.get("metadata") or {}
    identity = {
        "conversation_id": artifact["conversation_id"],
        "message_id": artifact["id"],
        "blob_container": artifact["blob_container"],
        "blob_path": artifact["blob_path"],
        "producer": metadata.get("analysis_producer"),
        "contexts": metadata.get("analysis_result_contexts"),
        "content_sha256": metadata.get("generated_artifact_content_sha256"),
    }
    if has_generated_artifact_source(metadata):
        identity["generated_source"] = deepcopy(metadata.get("generated_artifact_source"))
        identity["source_required"] = metadata.get("generated_artifact_source_required")
    return identity


def _artifact_producer(artifact):
    metadata = artifact.get("metadata") or {}
    if has_generated_artifact_source(metadata):
        return {"kind": "workflow_saved_output", **metadata["generated_artifact_source"]["producer"]}
    return metadata.get("analysis_producer")


def _publication_destination(publication):
    return {key: value for key, value in publication.items()
            if key not in {"artifact_format", "completion_policy", "source_kind"}}


def _read_publication_artifact_content(artifact, resources, expected_digest, *, check=None):
    if has_generated_artifact_source(artifact.get("metadata") or {}):
        # The existing transport verifies into bounded private storage before any handoff.
        from functions_simplechat_operations import open_generated_chat_artifact_stream

        if (artifact.get("metadata") or {}).get("generated_artifact_content_sha256") != expected_digest:
            raise ValueError("The generated artifact bytes changed.")
        return resources.enter_context(open_generated_chat_artifact_stream(artifact, check=check))
    content = download_blob_content(artifact["blob_container"], artifact["blob_path"])
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ValueError("The generated artifact bytes changed.")
    return content


def _receipt_change(artifact, key, change):
    """CAS only this artifact's receipt; an unacknowledged write grants no execution right."""
    for _ in range(8):
        current = cosmos_messages_container.read_item(item=artifact["id"], partition_key=artifact["conversation_id"])
        if _artifact_identity(current) != _artifact_identity(artifact):
            raise ValueError("The generated artifact changed. Reload it before publishing.")
        receipts = (current.get("metadata") or {}).get(RECEIPTS_FIELD) or {}
        receipt = deepcopy(receipts.get(key))
        updated = change(receipt)
        if updated is None:
            return receipt, False
        if updated.get("completion_policy") and any(
            other_key != key and other.get("request_id") == updated.get("request_id")
            for other_key, other in receipts.items()
        ):
            raise ValueError("This publication request is already bound to different artifact bytes.")
        if receipt is None and len(receipts) >= MAX_ARTIFACT_PUBLICATION_REQUESTS:
            raise ValueError("This artifact has reached its publication request limit.")
        if not current.get("_etag"):
            raise RuntimeError("Conditional publication persistence is unavailable.")
        current = deepcopy(current)
        current.setdefault("metadata", {})[RECEIPTS_FIELD] = {**receipts, key: updated}
        try:
            cosmos_messages_container.replace_item(
                item=current["id"], body=current, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return updated, True
        except CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
    raise RuntimeError("Publication is busy. Retry this same request.")


def _stage(artifact, receipt, name, *, complete=False):
    def change(current):
        if current is None:
            raise RuntimeError("Publication receipt is unavailable.")
        state = current.setdefault("stages", {}).get(name)
        if state == "complete" or (state and not complete):
            return None
        current["stages"][name] = "complete" if complete else "started"
        return current

    return _receipt_change(artifact, receipt["id"], change)[1]


def _destination_document(container, receipt):
    try:
        document = container.read_item(item=receipt["document_id"], partition_key=receipt["document_id"])
    except CosmosResourceNotFoundError:
        return None
    destination = receipt["destination"]
    scope_field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[
        destination["workspace_scope"]
    ]
    expected_scope = receipt["actor_user_id"] if scope_field == "user_id" else destination[scope_field]
    if (
        document.get(scope_field) != expected_scope or document.get("file_name") != receipt["file_name"]
        or document.get("generated_artifact_publication_receipt_id") not in (None, receipt["id"])
    ):
        raise PermissionError("The publication destination could not be confirmed.")
    return document


def _reservation_has_screening_history(document):
    # Screening clients are resolved only for an enrolled publication operation.
    from content_screening.repository import get_repository

    repository = get_repository()
    subject = subject_from_document(document)
    if repository.get_scan(document[SCREENING_FIELD]["scan_id"]) is not None:
        return True
    return any(
        repository.query(
            kind, subject.scope_key, filters={"document_id": subject.document_id}, page_size=1,
        )["items"]
        for kind in ("scan", "review", "finding", "model_window", "event", "audit", "checkpoint", "work_item")
    )


def _enroll_screening_reservation(artifact, receipt, container):
    """Capture proof only while preparing a new canonical, stored destination."""
    def enroll(current):
        document = _destination_document(container, current)
        proof = publication_screening_reservation(document) if document else None
        if (
            proof is None or current.get("decision")
            or PUBLICATION_SCREENING_CONSUMPTION in current
            or "approval_queue" in (current.get("stages") or {})
            or _reservation_has_screening_history(document)
        ):
            raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
        if PUBLICATION_SCREENING_RESERVATION in current:
            if current[PUBLICATION_SCREENING_RESERVATION] != proof:
                raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
            return None
        current[PUBLICATION_SCREENING_RESERVATION] = proof
        return current

    return _receipt_change(artifact, receipt["id"], enroll)[0]


def _publication_approval_screening(receipt, document, *, settings=None, operation_id=None, queue_claimed=False):
    """The bootstrap result admits only this receipt's approval-to-scan handoff."""
    if SCREENING_FIELD in document:
        if (public_document_payload(document).get(SCREENING_FIELD) or {}).get("available") is True:
            return "available"
    elif PUBLICATION_SCREENING_RESERVATION in receipt or PUBLICATION_SCREENING_CONSUMPTION in receipt:
        return None
    if settings is None:
        # Do not introduce settings/bootstrap initialization into readiness imports.
        from functions_settings import get_settings

        settings = get_settings()
    if SCREENING_FIELD not in document:
        if settings.get("enable_content_screening") is not True:
            return "available"
        from content_screening.service import document_requires_screening

        return None if document_requires_screening(document, settings) else "available"
    if settings.get("enable_content_screening") is not True:
        return None
    proof = publication_screening_reservation(document)
    stages = receipt.get("stages") or {}
    if (
        proof is None or receipt.get(PUBLICATION_SCREENING_RESERVATION) != proof
        or stages.get("create") != "complete" or stages.get("prepare") != "complete"
        or "queue" in stages
        or "approval_queue" in stages and not (queue_claimed and stages["approval_queue"] == "started")
    ):
        return None
    consumption = receipt.get(PUBLICATION_SCREENING_CONSUMPTION)
    decision = receipt.get("decision")
    if PUBLICATION_SCREENING_CONSUMPTION in receipt:
        if (
            not isinstance(consumption, dict) or not operation_id
            or consumption.get("operation_id") != operation_id
            or consumption.get("fingerprint") != proof["fingerprint"]
            or "scan_id" in consumption
            or decision and (
                decision.get("choice") != "approved" or decision.get("operation_id") != operation_id
            )
        ):
            return None
    elif decision or queue_claimed:
        return None
    if _reservation_has_screening_history(document):
        return None
    return "bootstrap"


def artifact_publication_approval_available(document, *, settings=None, operation_id=None):
    """Read fresh receipt and destination evidence without consuming the latch."""
    _artifact, receipt, _bound = read_artifact_publication_request(document)
    container = cosmos_group_documents_container if document.get("group_id") else cosmos_public_documents_container
    current = _destination_document(container, receipt)
    if current is None or current.get("_etag") != document.get("_etag"):
        return False
    return _publication_approval_screening(
        receipt, current, settings=settings, operation_id=operation_id,
    ) is not None


def consume_artifact_publication_screening_scan(document, scan_id):
    """Write ahead of every scan entry; neither errors nor deletion unlatch it.

    A scan that races initial receipt preparation consumes an unverified
    reservation too. Preparation cannot subsequently manufacture positive proof.
    """
    artifact, receipt, _bound = read_artifact_publication_request(document)
    subject = subject_from_document(document).to_dict()

    def consume(current):
        proof = current.get(PUBLICATION_SCREENING_RESERVATION)
        if proof is not None and (not isinstance(proof, dict) or proof.get("subject") != subject):
            raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
        fingerprint = proof["fingerprint"] if proof else hash_payload({
            "subject": subject, "marker": document.get(SCREENING_FIELD),
        })
        consumption = current.get(PUBLICATION_SCREENING_CONSUMPTION)
        if PUBLICATION_SCREENING_CONSUMPTION in current:
            if not isinstance(consumption, dict) or not consumption.get("operation_id"):
                raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
            if proof and consumption.get("fingerprint") != fingerprint:
                raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
            if "scan_id" in consumption:
                return None
        else:
            consumption = {"operation_id": f"scan:{scan_id}", "fingerprint": fingerprint}
        current[PUBLICATION_SCREENING_CONSUMPTION] = {**consumption, "scan_id": scan_id}
        return current

    _receipt_change(artifact, receipt["id"], consume)


def _log_uncertain(stage, exc):
    log_event(
        "[SIMPLE_CHAT] Artifact publication needs reconciliation",
        {"stage": stage, "exception_type": type(exc).__name__}, debug_only=True,
    )


def _notification_exists(receipt, notification_type):
    return bool(list(cosmos_notifications_container.query_items(
        query=(
            "SELECT TOP 1 c.id FROM c WHERE c.metadata.publication_receipt_id = @receipt "
            "AND c.notification_type = @notification_type"
        ),
        parameters=[
            {"name": "@receipt", "value": receipt["id"]},
            {"name": "@notification_type", "value": notification_type},
        ],
        enable_cross_partition_query=True,
    )))


def _notify_once(artifact, receipt, stage, notification_type, create, *, before=None):
    if _stage(artifact, receipt, stage):
        if before is not None:
            before()
        try:
            if create():
                _stage(artifact, receipt, stage, complete=True)
                return
        except (AzureError, OSError, RuntimeError) as exc:
            _log_uncertain(stage, exc)
    if _notification_exists(receipt, notification_type):
        _stage(artifact, receipt, stage, complete=True)


def _publication_response(artifact, receipt, container):
    receipt, _ = _receipt_change(artifact, receipt["id"], lambda current: None)
    document = _destination_document(container, receipt)
    if receipt.get("completion_policy"):
        return _completion_response(receipt, document)
    scope = receipt["destination"]["workspace_scope"]
    stages = receipt.get("stages") or {}
    required = ["create", "prepare", "queue"] if scope == "personal" else [
        "create", "prepare", "workspace_notification", "submitter_notification",
    ]
    unresolved = [stage for stage in required if stages.get(stage) != "complete"]
    state = "uncertain" if unresolved or not document else ("queued" if scope == "personal" else "pending_approval")
    if document and document.get("generated_artifact_promotion_status") in {"approved", "approval_failed"}:
        state = document["generated_artifact_promotion_status"]
        unresolved = []
    message = {
        "queued": "Generated artifact added to your personal workspace.",
        "pending_approval": "Generated artifact submitted to the destination workspace for approval.",
        "approved": "This artifact publication has already been approved.",
        "approval_failed": "The existing approval could not finish processing. No second copy was created.",
        "uncertain": "Publication could not be fully confirmed. Check the existing destination; no second copy was created.",
    }[state]
    return {
        "message": message,
        **receipt["destination"],
        "approval_required": scope != "personal",
        "document": {
            "id": receipt["document_id"], "file_name": receipt["file_name"],
            "status": document.get("status") if document else "Publication unconfirmed",
        },
        "publication": {
            "id": receipt["id"], "state": state, "document_id": receipt["document_id"],
            "destination": receipt["destination"], "unresolved_stages": unresolved,
        },
    }


def _completion_response(receipt, document):
    scope = receipt["destination"]["workspace_scope"]
    required = ["create", "prepare", "queue"] if scope == "personal" else [
        "create", "prepare", "workspace_notification", "submitter_notification",
    ]
    decision = (receipt.get("decision") or {}).get("choice", "pending")
    if decision not in {"pending", "approved", "rejected", "cancelled"}:
        raise ValueError("The saved publication decision is unsupported.")
    if decision == "approved":
        required.append("approval_queue")
    unresolved = [name for name in required if receipt.get("stages", {}).get(name) != "complete"]
    processing = publication_processing_observation(receipt, document)
    if processing == "not_started" and receipt.get("stages", {}).get("queue") == "complete":
        processing = "queued"
    status = {
        "version": 1, "id": receipt["id"], "document_id": receipt["document_id"],
        "document_version": receipt.get("document_version"), "destination": deepcopy(receipt["destination"]),
        "completion_policy": receipt["completion_policy"], "policy_satisfied": False,
        "state": "uncertain", "submission": "uncertain" if unresolved else "confirmed",
        "approval": "not_required" if scope == "personal" else decision,
        "processing": processing, "screening": "not_required", "index": "pending",
        "reason_code": "", "retryable": False, "unresolved_stages": unresolved,
    }
    facts = {}
    if publication_binding_matches(receipt, document):
        facts = inspect_publication_readiness(receipt, document, check_index=False)
        status.update({key: facts[key] for key in ("processing", "screening", "index")})
        if status["processing"] == "not_started" and any(
            receipt.get("stages", {}).get(stage) == "complete" for stage in ("queue", "approval_queue")
        ):
            status["processing"] = "queued"
    if decision in {"rejected", "cancelled"}:
        status.update(state=decision, reason_code=f"publication_{decision}")
    elif document is None and receipt.get("stages", {}).get("create") != "complete":
        status.update(reason_code="publication_effect_uncertain", retryable=True)
    elif document is None:
        status.update(state="unavailable", reason_code="publication_destination_unavailable")
    elif not publication_binding_matches(receipt, document):
        status.update(state="content_changed", reason_code="publication_revision_changed")
    elif document.get("generated_artifact_promotion_status") == "approval_failed" and receipt.get("stages", {}).get("approval_queue") != "complete":
        status.update(state="approval_failed", approval="failed", reason_code="publication_approval_failed", retryable=True)
    elif unresolved:
        status.update(reason_code="publication_effect_uncertain", retryable=True)
    elif facts.get("reason_code") == "publication_content_changed":
        status.update(state="content_changed", reason_code="publication_content_changed")
    elif status["processing"] == "failed":
        status.update(state="processing_failed", reason_code="publication_processing_failed", retryable=True)
    elif receipt["completion_policy"] == "submitted":
        status.update(state="submitted", policy_satisfied=True)
    elif status["approval"] == "pending":
        status["state"] = "waiting_approval"
    elif receipt["completion_policy"] == "approved":
        status.update(state="approved", policy_satisfied=True)
    else:
        status.update(inspect_publication_readiness(receipt, document))
        reason = status["reason_code"]
        if reason:
            status.update(
                state="content_changed" if reason in {"publication_content_changed", "publication_revision_changed"} else
                "processing_failed" if reason == "publication_processing_failed" else "unavailable",
                retryable=reason in {"publication_processing_failed", "publication_screening_unavailable"},
            )
        elif status["index"] == "ready":
            status.update(state="indexed_ready", policy_satisfied=True)
        else:
            status["state"] = (
                "waiting_screening" if status["screening"] in {"pending", "held"} else
                "waiting_index" if status["processing"] == "complete" else "waiting_processing"
            )
    messages = {
        "submitted": "The existing artifact was submitted. Approval and index readiness were not requested.",
        "approved": "Publication approval is satisfied. Index readiness was not requested.",
        "indexed_ready": "The original artifact's exact destination revision is indexed and available.",
        "waiting_approval": "Waiting for destination approval in the existing workspace review.",
        "waiting_processing": "Waiting for the existing destination document to finish processing.",
        "waiting_screening": "Waiting for the destination's content screening and review.",
        "waiting_index": "Waiting for the complete destination revision to become visible in the index.",
        "uncertain": "An existing publication effect could not be confirmed. Check the same receipt; do not create another copy.",
        "rejected": "The destination rejected this publication. Cancel this run before starting a new request.",
        "cancelled": "The destination publication request was cancelled.",
        "approval_failed": "Destination approval could not finish processing. Check the existing request.",
        "processing_failed": "The existing destination document could not finish processing.",
        "unavailable": "The exact destination or its readiness proof is unavailable. No replacement was published.",
        "content_changed": "The destination content or revision changed. The original publication policy was not satisfied.",
    }
    return {
        "message": messages[status["state"]], **receipt["destination"], "approval_required": scope != "personal",
        "document": {"id": receipt["document_id"], "file_name": receipt["file_name"]},
        "publication": public_publication_status(status),
    }


def publish_generated_chat_artifact_for_user(
    user_id, *, conversation_id, message_id, destination, request_id, requester_display_name="", file_name="",
    completion_policy=None, source_receipt=None, execution_check=None,
):
    with ExitStack() as resources:
        return _publish_generated_chat_artifact_for_user(
            user_id, conversation_id=conversation_id, message_id=message_id, destination=destination,
            request_id=request_id, requester_display_name=requester_display_name, file_name=file_name,
            completion_policy=completion_policy, source_receipt=source_receipt,
            execution_check=execution_check, resources=resources,
        )


def _publish_generated_chat_artifact_for_user(
    user_id, *, conversation_id, message_id, destination, request_id, requester_display_name="", file_name="",
    completion_policy=None, source_receipt=None, execution_check=None, resources,
):
    """Copy or request approval once; uncertain external work is never blindly repeated."""
    user_id = _text(user_id, "Acting user")
    request_id = _text(request_id, "Explicit publication request id")
    artifact = _authorize_artifact(
        user_id, _text(conversation_id, "Conversation id"), _text(message_id, "Artifact message id"),
    )
    destination, workspace_name, container = _authorize_destination(user_id, destination)
    if completion_policy is not None:
        # Kept at this opt-in boundary so ordinary artifact publication needs no workflow compiler.
        from functions_workflow_definitions import normalize_publication_completion_policy

        completion_policy = normalize_publication_completion_policy(completion_policy)
        if not isinstance(source_receipt, dict) or (source_receipt.get("producer") or {}).get("kind") == "chat":
            raise ValueError("Publication completion needs an exact saved workflow source receipt.")

    def reauthorize():
        if execution_check is not None:
            execution_check()
        current = _authorize_artifact(user_id, artifact["conversation_id"], artifact["id"])
        if _artifact_identity(current) != _artifact_identity(artifact):
            raise ValueError("The generated artifact changed before publication.")
        _authorize_destination(user_id, destination)

    metadata = artifact.get("metadata") or {}
    bound_source = has_generated_artifact_source(metadata)
    recheck_effect = completion_policy is not None or bound_source
    if bound_source and source_receipt is None:
        source_receipt = deepcopy(metadata["generated_artifact_source"]["source_receipt"])
    name = str(file_name or artifact.get("filename") or "generated-artifact.json").replace("\\", "/").split("/")[-1]
    output_format = str(metadata.get("generated_artifact_output_format") or "").lower()
    extension = {"markdown": ".md", "md": ".md", "csv": ".csv", "json": ".json"}.get(output_format)
    if extension and os.path.splitext(name)[1].lower() in {"", ".json"}:
        name = f"{os.path.splitext(name)[0]}{extension}"
    if not allowed_file(name):
        raise ValueError("Generated file type is not supported.")
    artifact_bytes = None
    content_sha256 = metadata.get("generated_artifact_content_sha256")
    if not content_sha256:
        artifact_bytes = download_blob_content(artifact["blob_container"], artifact["blob_path"])
        content_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    identity = {
        "source": _artifact_identity(artifact), "content_sha256": content_sha256,
        "destination": destination, "actor_user_id": user_id, "request_id": request_id,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if key not in (metadata.get(RECEIPTS_FIELD) or {}):
        if artifact_bytes is None:
            artifact_bytes = _read_publication_artifact_content(
                artifact, resources, content_sha256, check=execution_check,
            )
        if not bound_source and hashlib.sha256(artifact_bytes).hexdigest() != content_sha256:
            raise ValueError("The generated artifact bytes changed.")
    if destination["workspace_scope"] != "personal":
        stem, suffix = os.path.splitext(name)
        name = f"{stem} (artifact {key[:12]}){suffix}"
    receipt = {
        "id": key, "request_id": request_id, "actor_user_id": user_id, "destination": destination,
        "content_sha256": content_sha256, "document_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"simplechat-publication:{key}")),
        "file_name": name, "created_at": datetime.now(timezone.utc).isoformat(), "stages": {},
    }
    if recheck_effect:
        receipt.update(
            source_receipt=deepcopy(source_receipt),
            artifact_reference={"conversation_id": conversation_id, "artifact_message_id": message_id},
            source_identity=_artifact_identity(artifact),
        )
        if completion_policy is not None:
            receipt["completion_policy"] = completion_policy
    if len(metadata.get(RECEIPTS_FIELD) or {}) >= MAX_ARTIFACT_PUBLICATION_REQUESTS and key not in metadata[RECEIPTS_FIELD]:
        raise ValueError("This artifact has reached its publication request limit.")
    reauthorize()
    receipt, new_request = _receipt_change(artifact, key, lambda current: None if current else receipt)
    if receipt.get("completion_policy") != completion_policy or completion_policy is not None and receipt.get("source_receipt") != source_receipt:
        raise ValueError("The publication request is already bound to different inputs or a different policy.")
    document = _destination_document(container, receipt)
    if completion_policy and (receipt.get("decision") or {}).get("choice") in {"rejected", "cancelled"}:
        return _completion_response(receipt, document)
    scope_args = {field: value for field, value in destination.items() if field != "workspace_scope"}
    scope = destination["workspace_scope"]
    created_destination = False
    if document is None:
        reauthorize()
    if document is None and _stage(artifact, receipt, "create"):
        if recheck_effect:
            reauthorize()
        try:
            with ExitStack() as cleanup:
                source_file_path = None
                if scope == "personal" and os.path.splitext(name)[1].lower() == ".xsd":
                    if artifact_bytes is None:
                        artifact_bytes = download_blob_content(artifact["blob_container"], artifact["blob_path"])
                    if hashlib.sha256(artifact_bytes).hexdigest() != content_sha256:
                        raise ValueError("The generated artifact bytes changed.")
                    source_file_path = _write_temp_generated_file(artifact_bytes, ".xsd")
                    cleanup.callback(os.remove, source_file_path)
                create_document(
                    file_name=name, user_id=user_id, document_id=receipt["document_id"], num_file_chunks=0,
                    status="Queued for processing" if scope == "personal" else "Pending approval",
                    source_file_path=source_file_path, allow_deferred_xsd_source=scope != "personal",
                    **scope_args,
                )
        except (AzureError, OSError, RuntimeError) as exc:
            _log_uncertain("create", exc)
        document = _destination_document(container, receipt)
        created_destination = document is not None
    if document is None:
        return _publication_response(artifact, receipt, container)
    _stage(artifact, receipt, "create", complete=True)
    if recheck_effect and "document_version" not in receipt:
        if type(document.get("version")) is not int or document["version"] < 1:
            raise ValueError("The publication destination has no valid native revision.")
        reauthorize()
        receipt, _ = _receipt_change(
            artifact, key, lambda current: {**current, "document_version": document["version"]}
            if "document_version" not in current else None,
        )
    if not document.get("generated_artifact_publication_receipt_id"):
        reauthorize()
    if not document.get("generated_artifact_publication_receipt_id") and _stage(artifact, receipt, "prepare"):
        if recheck_effect:
            reauthorize()
        updates = {"generated_artifact_publication_receipt_id": key}
        if recheck_effect:
            updates[PUBLICATION_BINDING] = {
                "version": 1, "receipt_id": key, "document_version": receipt["document_version"],
                "content_sha256": content_sha256, "conversation_id": conversation_id,
                "artifact_message_id": message_id,
            }
        if scope != "personal":
            updates.update(
                generated_artifact_promotion_status="pending_approval",
                generated_artifact_original_file_name=str(file_name or artifact.get("filename") or name),
                generated_artifact_source_conversation_id=conversation_id,
                generated_artifact_source_message_id=message_id,
                generated_artifact_source_blob_container=artifact["blob_container"],
                generated_artifact_source_blob_path=artifact["blob_path"],
                generated_artifact_requested_by_user_id=user_id,
                generated_artifact_requested_by_display_name=requester_display_name or "A workspace member",
                generated_artifact_requested_at=receipt["created_at"],
                generated_artifact_capability=metadata.get("generated_artifact_capability") or "",
                generated_artifact_output_format=metadata.get("generated_artifact_output_format") or "",
                generated_artifact_summary=metadata.get("generated_artifact_summary") or "",
            )
        try:
            # These are destination documents, not saved-result projections: do not inherit source ACL metadata.
            update_document(document_id=receipt["document_id"], user_id=user_id, **scope_args, **updates)
        except (AzureError, OSError, RuntimeError) as exc:
            _log_uncertain("prepare", exc)
        document = _destination_document(container, receipt)
        if (
            new_request and created_destination and scope == "group" and document
            and document.get("generated_artifact_publication_receipt_id") == key
            and SCREENING_FIELD in document
        ):
            receipt = _enroll_screening_reservation(artifact, receipt, container)
    if not document or document.get("generated_artifact_publication_receipt_id") != key:
        return _publication_response(artifact, receipt, container)
    _stage(artifact, receipt, "prepare", complete=True)
    if scope == "personal":
        if not (receipt.get("stages") or {}).get("queue"):
            if artifact_bytes is None:
                artifact_bytes = _read_publication_artifact_content(
                    artifact, resources, receipt["content_sha256"], check=execution_check,
                )
            if not bound_source and hashlib.sha256(artifact_bytes).hexdigest() != receipt["content_sha256"]:
                raise ValueError("The generated artifact bytes changed.")
        reauthorize()
        if _stage(artifact, receipt, "queue"):
            if recheck_effect:
                reauthorize()
            try:
                queue_generated_document_processing(
                    document_id=receipt["document_id"], owner_user_id=user_id,
                    normalized_file_name=name, file_content_bytes=artifact_bytes,
                )
                _stage(artifact, receipt, "queue", complete=True)
                invalidate_personal_search_cache(user_id)
            except (AzureError, OSError, RuntimeError) as exc:
                _log_uncertain("queue", exc)
        elif (
            publication_handoff_observed(receipt, document)
            if completion_policy else document.get("status") not in {None, "", "Queued for processing"}
        ):
            _stage(artifact, receipt, "queue", complete=True)
    elif document.get("generated_artifact_promotion_status") == "pending_approval":
        reauthorize()
        target_field = "group_id" if scope == "group" else "public_workspace_id"
        link_url = "/group_workspaces" if scope == "group" else "/public_workspaces"
        link_context = {"workspace_type": scope, **scope_args, "document_id": receipt["document_id"]}
        notification_metadata = {
            **scope_args, "document_id": receipt["document_id"], "request_type": "generated_artifact_promotion",
            "publication_receipt_id": key, "conversation_id": conversation_id, "message_id": message_id,
        }
        notify_workspace = create_group_notification if scope == "group" else create_public_workspace_notification
        def workspace_notice():
            kwargs = {
                "notification_type": "approval_request_pending", "title": "Approval required: generated artifact",
                "message": f"{requester_display_name or 'A workspace member'} requested approval for {name} in {workspace_name}.",
                "link_url": link_url, "link_context": link_context, "metadata": notification_metadata,
            }
            if recheck_effect:
                return create_notification(**scope_args, **kwargs, idempotency_key=f"publication:{key}:workspace")
            return notify_workspace(destination[target_field], kwargs.pop("notification_type"), kwargs.pop("title"), kwargs.pop("message"), **kwargs)

        _notify_once(
            artifact, receipt, "workspace_notification", "approval_request_pending",
            workspace_notice, before=reauthorize if recheck_effect else None,
        )
        reauthorize()
        _notify_once(
            artifact, receipt, "submitter_notification", "approval_request_pending_submitter",
            lambda: create_notification(
                user_id=user_id, notification_type="approval_request_pending_submitter",
                title="Generated artifact submitted for approval",
                message=f"{name} is waiting for approval in {workspace_name}.",
                link_url=link_url, link_context=link_context, metadata=notification_metadata,
                **({"idempotency_key": f"publication:{key}:submitter"} if recheck_effect else {}),
            ),
            before=reauthorize if recheck_effect else None,
        )
        if scope == "group":
            invalidate_group_search_cache(destination["group_id"])
    if recheck_effect:
        reauthorize()
    return _publication_response(artifact, receipt, container)


def publish_workflow_artifact(
    user_id, *, publication, artifact_reference, request_id, source_receipt=None, execution_check=None,
):
    """Dispatch only a configured publication task using an actual upstream artifact address."""
    if publication is None:
        return {"reply": "", "execution_status": "skipped", "publication": {"state": "not_requested"}, "model_calls": 0}
    publication = normalize_workflow_publication(publication)
    if not isinstance(artifact_reference, dict):
        raise ValueError("This publication task needs an existing upstream analysis artifact.")
    conversation_id = _text(artifact_reference.get("conversation_id"), "Artifact conversation id")
    message_id = _text(artifact_reference.get("artifact_message_id"), "Upstream artifact message id")
    artifact = _authorize_artifact(user_id, conversation_id, message_id)
    metadata = artifact.get("metadata") or {}
    saved_output = publication.get("source_kind") == "saved_output"
    if saved_output:
        if not has_generated_artifact_source(metadata):
            raise ValueError("The upstream artifact is not bound to saved workflow records.")
        bound_receipt = metadata["generated_artifact_source"]["source_receipt"]
        if not isinstance(source_receipt, dict) or any(
            source_receipt.get(key) != bound_receipt[key]
            for key in ("producer", "result_ref", "output_name", "output_ref")
        ):
            raise ValueError("Publication requires the exact saved-output source receipt.")
    elif not metadata.get("analysis_result_required") or has_generated_artifact_source(metadata):
        raise ValueError("The upstream artifact is not bound to a saved final analysis.")
    if (saved_output or artifact_reference.get("producer") is not None) and artifact_reference.get("producer") != _artifact_producer(artifact):
        raise ValueError("The upstream artifact belongs to a different analysis result.")
    output_format = str(metadata.get("generated_artifact_output_format") or "").lower()
    if output_format == "markdown":
        output_format = "md"
    if output_format != publication["artifact_format"]:
        raise ValueError("The requested format is not available. Publish an existing upstream artifact.")
    if "completion_policy" in publication:
        producer = _artifact_producer(artifact) or {}
        if (
            producer.get("kind") != ("workflow_saved_output" if saved_output else "workflow") or not producer.get("execution_id")
            or not isinstance(source_receipt, dict)
            or source_receipt.get("producer") != {key: value for key, value in producer.items() if key != "kind"}
            or not isinstance(source_receipt.get("result_ref"), dict)
            or not isinstance(source_receipt.get("output_ref"), dict)
            or not source_receipt.get("output_name")
        ):
            raise ValueError("Publication completion needs the exact saved workflow result and attempt.")
    result = publish_generated_chat_artifact_for_user(
        user_id, conversation_id=conversation_id, message_id=message_id,
        destination=_publication_destination(publication),
        request_id=request_id,
        completion_policy=publication.get("completion_policy"), source_receipt=source_receipt,
        execution_check=execution_check,
    )
    response = {
        "reply": result["message"], "publication": result["publication"], "model_calls": 0,
        "execution_status": "blocked" if result["publication"]["state"] in {"uncertain", "approval_failed"} else "succeeded",
        "authoritative_result": {"kind": "json", "value": {"publication": result["publication"]}},
    }
    if "completion_policy" in publication:
        response["execution_status"] = "succeeded" if result["publication"]["policy_satisfied"] else "pending"
        response["_publication_request"] = {
            "publication": deepcopy(publication), "artifact_reference": deepcopy(artifact_reference),
            "request_id": request_id, "receipt_id": result["publication"]["id"],
            "source_receipt": deepcopy(source_receipt),
        }
    return response


def publish_workflow_analysis_artifact(
    user_id, *, publication, artifact_reference, request_id, source_receipt=None, execution_check=None,
):
    """Compatibility entry point; native definitions retain their original source checks."""
    return publish_workflow_artifact(
        user_id, publication=publication, artifact_reference=artifact_reference, request_id=request_id,
        source_receipt=source_receipt, execution_check=execution_check,
    )


def read_workflow_artifact_publication(
    user_id, request, *, reconcile=False, execution_check=None, authorization_only=False,
):
    """Observe one exact receipt. Only the leased workflow may reconcile stage acknowledgements."""
    publication = normalize_workflow_publication(request["publication"])
    address = request["artifact_reference"]
    artifact = _authorize_artifact(user_id, address["conversation_id"], address["artifact_message_id"])
    receipt, _ = _receipt_change(artifact, request["receipt_id"], lambda current: None)
    if not receipt or any(receipt.get(name) != expected for name, expected in (
        ("actor_user_id", user_id), ("request_id", request["request_id"]),
        ("completion_policy", publication.get("completion_policy")), ("source_receipt", request["source_receipt"]),
        ("artifact_reference", {key: address[key] for key in ("conversation_id", "artifact_message_id")}),
    )):
        raise PermissionError("The publication receipt does not match this workflow request.")
    destination = _publication_destination(publication)
    if (
        receipt["destination"] != destination or receipt.get("source_identity") != _artifact_identity(artifact)
        or address.get("producer") != _artifact_producer(artifact)
    ):
        raise PermissionError("The publication receipt belongs to a different producer or destination.")
    _, _, container = _authorize_destination(user_id, destination)
    document = _destination_document(container, receipt)
    if authorization_only:
        # A fulfilled checkpoint is historical; later deletion must not rewrite it.
        if reconcile or document is not None and not publication_binding_matches(receipt, document):
            raise PermissionError("The completed publication destination could not be confirmed.")
        if execution_check is not None:
            execution_check()
        return None
    if reconcile:
        if execution_check is None:
            raise ValueError("Publication reconciliation requires the current workflow write fence.")
        execution_check()
        confirmed = []
        if document:
            confirmed.append("create")
        if publication_binding_matches(receipt, document):
            confirmed.append("prepare")
            if publication_handoff_observed(receipt, document):
                confirmed.append("queue")
                if (receipt.get("decision") or {}).get("choice") == "approved":
                    confirmed.append("approval_queue")
        for stage, notification in (
            ("workspace_notification", "approval_request_pending"),
            ("submitter_notification", "approval_request_pending_submitter"),
        ):
            if receipt.get("stages", {}).get(stage) == "started" and _notification_exists(receipt, notification):
                confirmed.append(stage)
        for stage in confirmed:
            if receipt.get("stages", {}).get(stage) == "started":
                execution_check()
                _stage(artifact, receipt, stage, complete=True)
        receipt, _ = _receipt_change(artifact, receipt["id"], lambda current: None)
    result = _completion_response(receipt, document)
    _authorize_artifact(user_id, address["conversation_id"], address["artifact_message_id"])
    _authorize_destination(user_id, destination)
    if execution_check is not None:
        execution_check()
    return result


def _replace_publication_destination(container, receipt, updates):
    for _ in range(8):
        document = _destination_document(container, receipt)
        if not publication_binding_matches(receipt, document):
            raise ValueError("The publication destination revision is unavailable.")
        try:
            container.replace_item(
                item=document["id"], body={**document, **updates}, etag=document["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return
        except CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
    raise RuntimeError("The publication destination is busy.")


def authorize_publication_status_read(user_id, status, *, actor_user_id):
    """A workflow viewer does not inherit the publisher's destination permissions."""
    destination = status["destination"]
    scope = destination["workspace_scope"]
    if scope == "personal":
        if user_id != actor_user_id:
            raise PermissionError("This publication destination is private to its requester.")
        container = cosmos_user_documents_container
    elif scope == "group":
        assert_group_role(user_id, destination["group_id"], allowed_roles=("Owner", "Admin", "DocumentManager", "User"))
        container = cosmos_group_documents_container
    elif scope == "public" and find_public_workspace_by_id(destination["public_workspace_id"]):
        container = cosmos_public_documents_container
    else:
        raise PermissionError("Publication destination access could not be confirmed.")
    try:
        document = container.read_item(item=status["document_id"], partition_key=status["document_id"])
    except CosmosResourceNotFoundError:
        return
    field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[scope]
    if (
        document.get(field) != (actor_user_id if scope == "personal" else destination[field])
        or document.get("generated_artifact_publication_receipt_id") != status["id"]
    ):
        raise PermissionError("Publication destination access could not be confirmed.")


def read_artifact_publication_request(document):
    """Resolve an existing request without granting source-content access."""
    binding = document.get(PUBLICATION_BINDING) or {}
    if not isinstance(binding, dict):
        raise ValueError("The publication binding could not be confirmed.")
    conversation_id = binding.get("conversation_id") or document.get("generated_artifact_source_conversation_id")
    message_id = binding.get("artifact_message_id") or document.get("generated_artifact_source_message_id")
    receipt_id = binding.get("receipt_id") or document.get("generated_artifact_publication_receipt_id")
    try:
        artifact = cosmos_messages_container.read_item(
            item=_text(message_id, "Artifact reference"), partition_key=_text(conversation_id, "Artifact reference"),
        )
    except CosmosResourceNotFoundError as error:
        raise ValueError("The original publication artifact could not be confirmed.") from error
    receipt = (artifact.get("metadata") or {}).get(RECEIPTS_FIELD, {}).get(_text(receipt_id, "Publication request"))
    if not isinstance(receipt, dict) or receipt.get("id") != receipt_id:
        raise ValueError("The existing publication request could not be confirmed.")
    destination = receipt.get("destination") or {}
    scope = destination.get("workspace_scope")
    field = {"group": "group_id", "public": "public_workspace_id"}.get(scope)
    if (
        not field or destination.get(field) != document.get(field)
        or receipt.get("document_id") != document.get("id")
        or receipt.get("file_name") != document.get("file_name")
        or document.get("generated_artifact_publication_receipt_id") != receipt_id
        or artifact.get("conversation_id") != conversation_id or artifact.get("id") != message_id
    ):
        raise PermissionError("The publication request belongs to a different source or destination.")
    identity = {
        "source": _artifact_identity(artifact), "content_sha256": receipt.get("content_sha256"),
        "destination": destination, "actor_user_id": receipt.get("actor_user_id"), "request_id": receipt.get("request_id"),
    }
    expected_key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if (
        expected_key != receipt_id
        or document.get("id") != str(uuid.uuid5(uuid.NAMESPACE_URL, f"simplechat-publication:{receipt_id}"))
        or document.get("generated_artifact_requested_by_user_id") != receipt.get("actor_user_id")
        or document.get("generated_artifact_source_blob_container") != artifact.get("blob_container")
        or document.get("generated_artifact_source_blob_path") != artifact.get("blob_path")
        or type(document.get("version")) is not int or document["version"] < 1
    ):
        raise ValueError("The publication request needs source reconciliation.")
    if binding:
        if not publication_binding_matches(receipt, document):
            raise ValueError("The publication destination revision changed.")
        return artifact, deepcopy(receipt), True
    return artifact, deepcopy(receipt), False


def enroll_legacy_artifact_publication(document, *, operation_guard, cleanup_only=False):
    """Conditionally bind a verifiable old request; never create another receipt."""
    artifact, receipt, bound = read_artifact_publication_request(document)
    if bound:
        return document
    if receipt.get("decision") or document.get("generated_artifact_promotion_status") != "pending_approval":
        raise ValueError("Only an undecided pending legacy request may be enrolled.")
    operation_guard()
    source = _authorize_artifact(receipt["actor_user_id"], artifact["conversation_id"], artifact["id"])
    _authorize_destination(
        receipt["actor_user_id"], receipt["destination"], operation="delete" if cleanup_only else "upload",
    )
    if _artifact_identity(source) != _artifact_identity(artifact):
        raise ValueError("The original publication source changed.")
    with ExitStack() as resources:
        _read_publication_artifact_content(source, resources, receipt["content_sha256"], check=operation_guard)
        operation_guard()
    reference = {"conversation_id": artifact["conversation_id"], "artifact_message_id": artifact["id"]}
    updates = {
        "document_version": document["version"], "artifact_reference": reference,
        "source_identity": _artifact_identity(artifact),
    }

    def bind(current):
        if current.get("decision") or any(
            key in current and current[key] != value for key, value in updates.items()
        ):
            raise ValueError("The legacy request changed before enrollment.")
        return {**current, **updates}

    receipt, _ = _receipt_change(artifact, receipt["id"], bind)
    operation_guard()
    binding = {
        "version": 1, "receipt_id": receipt["id"], "document_version": document["version"],
        "content_sha256": receipt["content_sha256"], **reference,
    }
    container = cosmos_group_documents_container if document.get("group_id") else cosmos_public_documents_container
    return container.replace_item(
        item=document["id"], body={**document, PUBLICATION_BINDING: binding},
        etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
    )


def decide_artifact_publication(
    user_id, document, choice, *, operation_guard=None, delete_destination=None, decision_link_url=None,
    operation_id=None,
):
    """Use the destination's existing review role, while retaining a durable receipt outcome."""
    try:
        return _decide_artifact_publication(
            user_id, document, choice, operation_guard=operation_guard,
            delete_destination=delete_destination, decision_link_url=decision_link_url, operation_id=operation_id,
        )
    except PermissionError as exc:
        _log_uncertain("destination_authorization", exc)
        raise PermissionError("Current publication source or destination access could not be confirmed.") from exc
    except (AzureError, OSError, RuntimeError, ScreeningError) as exc:
        _log_uncertain("destination_decision", exc)
        raise RuntimeError("The publication decision could not be fully confirmed. Refresh the existing request.") from exc


def _decide_artifact_publication(
    user_id, document, choice, *, operation_guard=None, delete_destination=None, decision_link_url=None,
    operation_id=None,
):
    with ExitStack() as resources:
        return _decide_artifact_publication_with_content(
            user_id, document, choice, resources=resources, operation_guard=operation_guard,
            delete_destination=delete_destination, decision_link_url=decision_link_url, operation_id=operation_id,
        )


def _decide_artifact_publication_with_content(
    user_id, document, choice, *, resources, operation_guard=None, delete_destination=None, decision_link_url=None,
    operation_id=None,
):
    if choice not in {"approved", "rejected", "cancelled"}:
        raise ValueError("Invalid publication decision.")
    roles = ("Owner", "Admin", "DocumentManager", "User") if choice == "cancelled" else ("Owner", "Admin", "DocumentManager")
    if document.get("group_id"):
        assert_group_role(user_id, document["group_id"], allowed_roles=roles)
    elif document.get("public_workspace_id"):
        workspace = find_public_workspace_by_id(document["public_workspace_id"])
        if not workspace or get_user_role_in_public_workspace(workspace, user_id) not in roles:
            raise PermissionError("You cannot decide this publication request.")
    else:
        raise ValueError("Personal publication does not require workspace approval.")
    binding = document.get(PUBLICATION_BINDING) or {}
    artifact = cosmos_messages_container.read_item(
        item=binding["artifact_message_id"], partition_key=binding["conversation_id"],
    )
    receipt, _ = _receipt_change(artifact, binding["receipt_id"], lambda current: None)
    if not receipt or not publication_binding_matches(receipt, document):
        raise ValueError("The publication decision does not match its destination.")
    operation_id = operation_id or (receipt.get("decision") or {}).get("operation_id") or str(uuid.uuid4())
    destination = receipt["destination"]
    scope = destination["workspace_scope"]
    if scope not in {"group", "public"}:
        raise ValueError("Personal publication does not require workspace approval.")
    if (
        scope == "group" and destination["group_id"] != document.get("group_id")
        or scope == "public" and destination["public_workspace_id"] != document.get("public_workspace_id")
        or receipt["document_id"] != document["id"]
    ):
        raise PermissionError("The publication belongs to a different workspace.")
    container = cosmos_group_documents_container if scope == "group" else cosmos_public_documents_container
    recorded_negative = (
        choice in {"rejected", "cancelled"} and (receipt.get("decision") or {}).get("choice") == choice
    )
    destination_deleted = False

    def authorize_decision():
        if operation_guard is not None:
            operation_guard()
        if scope == "group":
            assert_group_role(user_id, destination["group_id"], allowed_roles=roles)
        else:
            workspace = find_public_workspace_by_id(destination["public_workspace_id"])
            if not workspace or get_user_role_in_public_workspace(workspace, user_id) not in roles:
                raise PermissionError("You cannot decide this publication request.")
        if choice == "cancelled" and receipt["actor_user_id"] != user_id:
            raise PermissionError("Only the publication requester can cancel this request.")
        current = _destination_document(container, receipt)
        if current is None:
            if not (recorded_negative or destination_deleted):
                raise ValueError("The publication destination is unavailable.")
        elif not publication_binding_matches(receipt, current):
            raise ValueError("The publication destination revision changed.")
        return current

    authorize_decision()
    source_bytes = None
    if choice == "approved":
        if receipt.get("source_identity") != _artifact_identity(artifact):
            raise ValueError("The original publication artifact changed.")
        _authorize_artifact(receipt["actor_user_id"], artifact["conversation_id"], artifact["id"])
        _authorize_destination(receipt["actor_user_id"], destination)
        source_bytes = _read_publication_artifact_content(
            artifact, resources, receipt["content_sha256"], check=operation_guard,
        )
        _authorize_artifact(receipt["actor_user_id"], artifact["conversation_id"], artifact["id"])
        _authorize_destination(receipt["actor_user_id"], destination)
    authorize_decision()

    def record_decision(current):
        current_document = authorize_decision()
        previous = current.get("decision")
        if previous and previous.get("choice") != choice:
            raise ValueError("A different publication decision already committed.")
        bootstrap = False
        if choice == "approved":
            admission = _publication_approval_screening(current, current_document, operation_id=operation_id)
            if admission is None:
                raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
            bootstrap = admission == "bootstrap"
            if bootstrap and PUBLICATION_SCREENING_CONSUMPTION not in current:
                current[PUBLICATION_SCREENING_CONSUMPTION] = {
                    "operation_id": operation_id,
                    "fingerprint": current[PUBLICATION_SCREENING_RESERVATION]["fingerprint"],
                }
        if previous:
            return None
        current["decision"] = {
            "choice": choice, "actor_user_id": user_id, "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        if bootstrap:
            current["decision"]["operation_id"] = operation_id
        return current

    receipt, _ = _receipt_change(artifact, receipt["id"], record_decision)
    scope_args = {key: destination[key] for key in ("group_id", "public_workspace_id") if key in destination}
    if choice == "approved":
        if has_generated_artifact_source(artifact.get("metadata") or {}):
            _authorize_artifact(receipt["actor_user_id"], artifact["conversation_id"], artifact["id"])
            _authorize_destination(receipt["actor_user_id"], destination)
        authorize_decision()
        _replace_publication_destination(container, receipt, {
            "generated_artifact_promotion_status": "approved",
            "generated_artifact_approved_at": receipt["decision"]["decided_at"],
            "generated_artifact_approved_by_user_id": receipt["decision"]["actor_user_id"],
        })
        if _stage(artifact, receipt, "approval_queue"):
            try:
                _authorize_artifact(receipt["actor_user_id"], artifact["conversation_id"], artifact["id"])
                _authorize_destination(receipt["actor_user_id"], destination)
                receipt, _ = _receipt_change(artifact, receipt["id"], lambda saved: None)
                current = authorize_decision()
                if _publication_approval_screening(
                    receipt, current, operation_id=operation_id, queue_claimed=True,
                ) is None:
                    raise ValueError(SCREENING_BOOTSTRAP_REMEDY)
                queue_generated_document_processing(
                    document_id=receipt["document_id"], owner_user_id=receipt["actor_user_id"],
                    normalized_file_name=receipt["file_name"], file_content_bytes=source_bytes, **scope_args,
                )
                _stage(artifact, receipt, "approval_queue", complete=True)
            except (AzureError, OSError, RuntimeError, ValueError, PermissionError, ScreeningError) as exc:
                _log_uncertain("approval_queue", exc)
                _replace_publication_destination(container, receipt, {
                    "generated_artifact_promotion_status": "approval_failed",
                })
                raise RuntimeError("Approval was recorded, but its existing processing handoff needs reconciliation.") from exc
        elif publication_handoff_observed(receipt, _destination_document(container, receipt)):
            _stage(artifact, receipt, "approval_queue", complete=True)
        elif operation_guard is not None and receipt.get("stages", {}).get("approval_queue") == "started":
            _replace_publication_destination(container, receipt, {
                "generated_artifact_promotion_status": "approval_failed",
            })
    else:
        # The durable decision survives removal of the pending destination shell.
        from functions_documents import delete_document_revision

        authorize_decision()
        if _destination_document(container, receipt):
            if delete_destination is not None:
                delete_destination(_destination_document(container, receipt))
            else:
                delete_document_revision(
                    user_id=user_id, document_id=receipt["document_id"], delete_mode="current_only", **scope_args,
                )
            destination_deleted = True
    if choice != "cancelled":
        notification_type = "approval_request_approved" if choice == "approved" else "approval_request_denied"
        _notify_once(
            artifact, receipt, "decision_notification", notification_type,
            lambda: create_notification(
                user_id=receipt["actor_user_id"], notification_type=notification_type,
                title="Generated artifact approved" if choice == "approved" else "Generated artifact denied",
                message="The destination approved your generated artifact." if choice == "approved" else
                "The destination rejected your generated artifact.",
                link_url=decision_link_url or ("/group_workspaces" if scope == "group" else "/public_workspaces"),
                link_context={"workspace_type": scope, **scope_args, "document_id": receipt["document_id"]},
                metadata={**scope_args, "document_id": receipt["document_id"], "publication_receipt_id": receipt["id"],
                          "request_type": "generated_artifact_promotion"},
                idempotency_key=f"publication:{receipt['id']}:decision",
            ),
            before=authorize_decision,
        )
    return {"message": f"Publication {choice}.", "document_id": receipt["document_id"]}
