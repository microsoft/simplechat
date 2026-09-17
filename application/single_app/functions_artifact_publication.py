# functions_artifact_publication.py
"""Explicit workspace publication of existing artifacts, with scoped retry receipts."""

from copy import deepcopy
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
from functions_appinsights import log_event
from functions_collaboration import build_conversation_participation_context
from functions_documents import allowed_file, create_document, update_document
from functions_generated_file_approvals import assert_generated_file_approval_allows_download
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
    authorize_analysis_artifact(user_id, artifact, for_publication=True)
    return artifact


def _authorize_destination(user_id, destination):
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
        allowed, _ = check_group_status_allows_operation(workspace, "upload")
        container = cosmos_group_documents_container
    else:
        workspace = find_public_workspace_by_id(target_id)
        if not workspace or get_user_role_in_public_workspace(workspace, user_id) not in {
            "Owner", "Admin", "DocumentManager",
        }:
            raise PermissionError("You cannot publish to this public workspace.")
        allowed, _ = check_public_workspace_status_allows_operation(workspace, "upload")
        container = cosmos_public_documents_container
    if not allowed:
        raise PermissionError("This workspace does not currently allow uploads.")
    return normalized, str(workspace.get("name") or f"{scope} workspace"), container


def _artifact_identity(artifact):
    metadata = artifact.get("metadata") or {}
    return {
        "conversation_id": artifact["conversation_id"],
        "message_id": artifact["id"],
        "blob_container": artifact["blob_container"],
        "blob_path": artifact["blob_path"],
        "producer": metadata.get("analysis_producer"),
        "contexts": metadata.get("analysis_result_contexts"),
        "content_sha256": metadata.get("generated_artifact_content_sha256"),
    }


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


def _notify_once(artifact, receipt, stage, notification_type, create):
    if _stage(artifact, receipt, stage):
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


def publish_generated_chat_artifact_for_user(
    user_id, *, conversation_id, message_id, destination, request_id, requester_display_name="", file_name="",
):
    """Copy or request approval once; uncertain external work is never blindly repeated."""
    user_id = _text(user_id, "Acting user")
    request_id = _text(request_id, "Explicit publication request id")
    artifact = _authorize_artifact(
        user_id, _text(conversation_id, "Conversation id"), _text(message_id, "Artifact message id"),
    )
    destination, workspace_name, container = _authorize_destination(user_id, destination)

    def reauthorize():
        current = _authorize_artifact(user_id, artifact["conversation_id"], artifact["id"])
        if _artifact_identity(current) != _artifact_identity(artifact):
            raise ValueError("The generated artifact changed before publication.")
        _authorize_destination(user_id, destination)

    metadata = artifact.get("metadata") or {}
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
            artifact_bytes = download_blob_content(artifact["blob_container"], artifact["blob_path"])
        if hashlib.sha256(artifact_bytes).hexdigest() != content_sha256:
            raise ValueError("The generated artifact bytes changed.")
    if destination["workspace_scope"] != "personal":
        stem, suffix = os.path.splitext(name)
        name = f"{stem} (artifact {key[:12]}){suffix}"
    receipt = {
        "id": key, "request_id": request_id, "actor_user_id": user_id, "destination": destination,
        "content_sha256": content_sha256, "document_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"simplechat-publication:{key}")),
        "file_name": name, "created_at": datetime.now(timezone.utc).isoformat(), "stages": {},
    }
    if len(metadata.get(RECEIPTS_FIELD) or {}) >= MAX_ARTIFACT_PUBLICATION_REQUESTS and key not in metadata[RECEIPTS_FIELD]:
        raise ValueError("This artifact has reached its publication request limit.")
    reauthorize()
    receipt, _ = _receipt_change(artifact, key, lambda current: None if current else receipt)
    document = _destination_document(container, receipt)
    scope_args = {field: value for field, value in destination.items() if field != "workspace_scope"}
    scope = destination["workspace_scope"]
    if document is None:
        reauthorize()
    if document is None and _stage(artifact, receipt, "create"):
        try:
            create_document(
                file_name=name, user_id=user_id, document_id=receipt["document_id"], num_file_chunks=0,
                status="Queued for processing" if scope == "personal" else "Pending approval", **scope_args,
            )
        except (AzureError, OSError, RuntimeError) as exc:
            _log_uncertain("create", exc)
        document = _destination_document(container, receipt)
    if document is None:
        return _publication_response(artifact, receipt, container)
    _stage(artifact, receipt, "create", complete=True)
    if not document.get("generated_artifact_publication_receipt_id"):
        reauthorize()
    if not document.get("generated_artifact_publication_receipt_id") and _stage(artifact, receipt, "prepare"):
        updates = {"generated_artifact_publication_receipt_id": key}
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
    if not document or document.get("generated_artifact_publication_receipt_id") != key:
        return _publication_response(artifact, receipt, container)
    _stage(artifact, receipt, "prepare", complete=True)
    if scope == "personal":
        if not (receipt.get("stages") or {}).get("queue"):
            if artifact_bytes is None:
                artifact_bytes = download_blob_content(artifact["blob_container"], artifact["blob_path"])
            if hashlib.sha256(artifact_bytes).hexdigest() != receipt["content_sha256"]:
                raise ValueError("The generated artifact bytes changed.")
        reauthorize()
        if _stage(artifact, receipt, "queue"):
            try:
                queue_generated_document_processing(
                    document_id=receipt["document_id"], owner_user_id=user_id,
                    normalized_file_name=name, file_content_bytes=artifact_bytes,
                )
                _stage(artifact, receipt, "queue", complete=True)
                invalidate_personal_search_cache(user_id)
            except (AzureError, OSError, RuntimeError) as exc:
                _log_uncertain("queue", exc)
        elif document.get("status") not in {None, "", "Queued for processing"}:
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
        _notify_once(
            artifact, receipt, "workspace_notification", "approval_request_pending",
            lambda: notify_workspace(
                destination[target_field], "approval_request_pending", "Approval required: generated artifact",
                f"{requester_display_name or 'A workspace member'} requested approval for {name} in {workspace_name}.",
                link_url=link_url, link_context=link_context, metadata=notification_metadata,
            ),
        )
        reauthorize()
        _notify_once(
            artifact, receipt, "submitter_notification", "approval_request_pending_submitter",
            lambda: create_notification(
                user_id=user_id, notification_type="approval_request_pending_submitter",
                title="Generated artifact submitted for approval",
                message=f"{name} is waiting for approval in {workspace_name}.",
                link_url=link_url, link_context=link_context, metadata=notification_metadata,
            ),
        )
        if scope == "group":
            invalidate_group_search_cache(destination["group_id"])
    return _publication_response(artifact, receipt, container)


def publish_workflow_analysis_artifact(user_id, *, publication, artifact_reference, request_id):
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
    if not metadata.get("analysis_result_required"):
        raise ValueError("The upstream artifact is not bound to a saved final analysis.")
    if artifact_reference.get("producer") is not None and artifact_reference["producer"] != metadata.get("analysis_producer"):
        raise ValueError("The upstream artifact belongs to a different analysis result.")
    output_format = str(metadata.get("generated_artifact_output_format") or "").lower()
    if output_format == "markdown":
        output_format = "md"
    if output_format != publication["artifact_format"]:
        raise ValueError("The requested format is not available. Publish an existing upstream artifact.")
    result = publish_generated_chat_artifact_for_user(
        user_id, conversation_id=conversation_id, message_id=message_id,
        destination={key: value for key, value in publication.items() if key != "artifact_format"},
        request_id=request_id,
    )
    return {
        "reply": result["message"], "publication": result["publication"], "model_calls": 0,
        "execution_status": "blocked" if result["publication"]["state"] in {"uncertain", "approval_failed"} else "succeeded",
        "authoritative_result": {"kind": "json", "value": {"publication": result["publication"]}},
    }
