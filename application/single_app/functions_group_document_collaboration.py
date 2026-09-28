# functions_group_document_collaboration.py
"""Revision-bound group sharing state, decisions and explicit effect receipts."""

from copy import deepcopy
from datetime import datetime, timezone
import logging
from urllib.parse import quote
import uuid

from azure.core import MatchConditions
from azure.core.exceptions import ServiceRequestError, ServiceResponseError

from config import cosmos_group_documents_container
from content_screening.access import public_document_payload
from content_screening.contracts import SCREENING_FIELD
from functions_appinsights import log_event
from functions_document_access_index import sync_document_access_index_for_document_fail_open
from functions_documents import _execute_document_search_write, _get_search_client
from functions_group import discover_group_records, find_group_by_id, get_group_document_reviewer_ids
from functions_group_document_access import (
    GroupDocumentReadError,
    _group_document_share_status,
    _validate_group_read_id,
    is_current_group_document,
    read_group_document_record,
    require_group_document_read_context,
)
from functions_group_document_management import require_payload, validate_group_document_id
from functions_group_document_policy import (
    GROUP_DOCUMENT_COLLABORATION_STATUSES,
    GROUP_DOCUMENT_MANAGER_ROLES,
    group_document_approval_pending,
    group_document_collaboration_operations,
)
from functions_group_document_projection_fence import (
    GroupDocumentProjectionConflict,
    assert_no_group_document_projection_writer,
    group_collaboration_projection_context,
)
from functions_notifications import create_notification, delete_notifications_by_metadata
from functions_settings import get_settings
from utils_cache import invalidate_group_search_cache


COLLABORATION_OPERATION = "group_document_collaboration_operation"
COLLABORATION_EFFECTS = ("search", "index", "cache", "notifications")
NEGATIVE_SHARE_ACTIONS = frozenset({"unshare", "remove_share"})


class GroupDocumentCollaborationError(GroupDocumentReadError):
    def __init__(self, error_code, message, status_code):
        super().__init__(message, status_code)
        self.error_code = error_code


def collaboration_error_response(error, *, group_id=None, document_id=None):
    if isinstance(error, GroupDocumentCollaborationError):
        code, message, status = error.error_code, error.description, error.code
    elif isinstance(error, GroupDocumentReadError):
        code, message, status = "collaboration_unavailable", error.description, error.code
    elif isinstance(error, GroupDocumentProjectionConflict):
        code, message, status = "projection_busy", "A document projection must finish or be reconciled before changing access.", 409
    elif getattr(error, "status_code", None) in {409, 412}:
        code, message, status = "state_conflict", "The document state changed. Refresh before retrying.", 409
    elif getattr(error, "status_code", None) == 404 or isinstance(error, LookupError):
        code, message, status = "collaboration_gone", "The document or request is no longer available.", 404
    else:
        log_event(
            "[DOCUMENTS] Scoped group collaboration could not be confirmed.",
            extra={"group_id": group_id, "document_id": document_id, "exception_type": type(error).__name__},
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
        raise GroupDocumentCollaborationError("revision_unavailable", "The document revision is unavailable.", 409)
    return int(value)


def _expected_etag(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or value != value.strip():
        raise GroupDocumentCollaborationError("invalid_etag", "A current expected_etag is required.", 400)
    return value


def _check_etag(document, expected):
    _expected_etag(expected)
    if not document.get("_etag") or document["_etag"] != expected:
        raise GroupDocumentCollaborationError("state_conflict", "The document state changed. Refresh before retrying.", 409)


def _group_projection(group, fallback_id=None):
    group = group or {}
    return {
        "id": group.get("id") or fallback_id,
        "name": str(group.get("name") or "Unknown Group"),
        "description": str(group.get("description") or ""),
    }


def _details(document, target_group_id):
    groups = (document.get("document_share_details") or {}).get("groups") or {}
    detail = groups.get(target_group_id)
    return detail if isinstance(detail, dict) else {}


def _operation(document):
    value = document.get(COLLABORATION_OPERATION)
    return value if isinstance(value, dict) and value.get("schema_version") == 1 else {}


def _operation_bound(document, operation):
    return (
        operation.get("document_id") == document.get("id")
        and operation.get("source_group_id") == document.get("group_id")
        and operation.get("document_version") == _version(document)
        and isinstance(operation.get("id"), str) and bool(operation["id"])
    )


def _unfinished(operation):
    return operation.get("phase") != "complete"


def _terminal_relationship(document, group_id):
    detail = _details(document, group_id)
    operation = _operation(document)
    if (
        _operation_bound(document, operation)
        and operation.get("target_group_id") == group_id
        and operation.get("action") in NEGATIVE_SHARE_ACTIONS
        and operation.get("had_relationship") is True
        and operation.get("state") in {"removed", "denied"}
        and detail.get("status") == operation["state"]
        and detail.get("request_id") == operation.get("request_id")
        and detail.get("source_group_id") == document["group_id"]
        and detail.get("target_group_id") == group_id
        and detail.get("document_id") == document["id"]
        and detail.get("document_version") == _version(document)
        and _unfinished(operation)
    ):
        return operation["state"]
    return None


def _context(user_id, group_id):
    group, role = require_group_document_read_context(user_id, group_id)
    settings = get_settings()
    operations = group_document_collaboration_operations(group, role, settings)
    if not operations:
        raise GroupDocumentCollaborationError("collaboration_disabled", "Group document collaboration is unavailable.", 403)
    return group, role, settings, operations


def _read_state(user_id, group_id, document_id, *, allow_terminal=True):
    validate_group_document_id(document_id)
    context = _context(user_id, group_id)
    document = read_group_document_record(document_id)
    relationship = _group_document_share_status(document, group_id)
    if relationship is None and allow_terminal and context[1] in GROUP_DOCUMENT_MANAGER_ROLES:
        relationship = _terminal_relationship(document, group_id)
    if relationship is None:
        raise GroupDocumentCollaborationError("collaboration_gone", "The document is not available in this group.", 404)
    if not document.get("_etag"):
        raise GroupDocumentCollaborationError("state_unavailable", "Conditional document state is unavailable.", 409)
    _version(document)
    return document, relationship, context


def _available(document, public_payload=None):
    if group_document_approval_pending(document):
        return False
    payload = public_payload if public_payload is not None else public_document_payload(document)
    return SCREENING_FIELD not in document or (payload.get(SCREENING_FIELD) or {}).get("available") is True


def _positive_group(group):
    return bool(
        group and group.get("type", "group") == "group"
        and group.get("status", "active") in GROUP_DOCUMENT_COLLABORATION_STATUSES
    )


def _publication_view(document, user_id, group_id, context):
    # Publication loading is deferred because ordinary sharing has no dependency
    # on private artifact/source material and must not probe it.
    from functions_group_document_publication import group_publication_view

    return group_publication_view(document, user_id, group_id, context=context)


def get_group_document_collaboration_actions(
    document, user_id, group_id, *, context=None, settings=None, public_payload=None,
    source_groups=None, current_revision=None,
):
    if context is None:
        group, role, settings, supported = _context(user_id, group_id)
    else:
        group, role = context
        settings = settings if settings is not None else get_settings()
        supported = group_document_collaboration_operations(group, role, settings)
    if not supported:
        return []
    try:
        assert_no_group_document_projection_writer(document)
    except GroupDocumentProjectionConflict:
        return ["inspect"] if "inspect" in supported else []
    relationship = _group_document_share_status(document, group_id)
    if relationship is None:
        return []
    actions = {"inspect"}
    operation = _operation(document)
    if operation and _unfinished(operation):
        if operation.get("phase") in {"claimed", "repair"} and _operation_bound(document, operation):
            pending_action = operation.get("action")
            if pending_action in NEGATIVE_SHARE_ACTIONS:
                actions.add("unshare" if relationship == "owner" else "remove_share")
            elif pending_action == "share" and relationship == "owner":
                actions.add("share")
            elif pending_action == "approve_share" and operation.get("target_group_id") == group_id:
                actions.add("approve_share")
            elif pending_action in {"approve_artifact", "reject_artifact", "cancel_artifact"}:
                publication_state = _publication_view(document, user_id, group_id, (group, role, settings, supported))
                if publication_state and pending_action in publication_state["actions"]:
                    actions.add(pending_action)
        elif (
            operation.get("phase") == "executing" and _operation_bound(document, operation)
            and operation.get("action") == "approve_artifact"
        ):
            # Only receipt-proven pre-queue bootstrap recovery is advertised by
            # the publication adapter; no other executing operation is replayable.
            publication_state = _publication_view(document, user_id, group_id, (group, role, settings, supported))
            if publication_state and "approve_artifact" in publication_state["actions"]:
                actions.add("approve_artifact")
        return [action for action in supported if action in actions]
    if role in GROUP_DOCUMENT_MANAGER_ROLES:
        if relationship == "owner":
            if document.get("shared_group_ids"):
                actions.add("unshare")
            if current_revision is None:
                current_revision = is_current_group_document(document)
            if current_revision and _available(document, public_payload):
                actions.add("share")
        else:
            actions.add("remove_share")
            source = (source_groups or {}).get(document["group_id"]) or find_group_by_id(document["group_id"])
            if current_revision is None:
                current_revision = is_current_group_document(document)
            if relationship == "not_approved" and current_revision and _positive_group(source) and _available(document, public_payload):
                actions.add("approve_share")
    publication = _publication_view(document, user_id, group_id, (group, role, settings, supported))
    if publication:
        actions.update(publication["actions"])
    return [action for action in supported if action in actions]


def group_document_sharing_state(user_id, group_id, document_id):
    document, relationship, context = _read_state(user_id, group_id, document_id)
    group, role, settings, supported = context
    source = group if relationship == "owner" else find_group_by_id(document["group_id"])
    terminal = relationship in {"removed", "denied"}
    recipients = []
    if not terminal:
        if relationship == "owner" and role in GROUP_DOCUMENT_MANAGER_ROLES:
            seen = set()
            for entry in document.get("shared_group_ids") or []:
                if not isinstance(entry, str):
                    raise GroupDocumentCollaborationError("sharing_state_unavailable", "The sharing state needs reconciliation.", 409)
                target = entry.split(",", 1)[0]
                if target in seen:
                    continue
                seen.add(target)
                approval = _group_document_share_status(document, target)
                if approval not in {"approved", "not_approved"}:
                    raise GroupDocumentCollaborationError("sharing_state_unavailable", "The sharing state needs reconciliation.", 409)
                recipients.append({**_group_projection(find_group_by_id(target), target), "approval_status": approval})
        elif relationship != "owner":
            recipients.append({**_group_projection(group), "approval_status": relationship})
    if terminal:
        actions = ["inspect"]
        operation = _operation(document)
        if operation.get("phase") in {"claimed", "repair"} and "remove_share" in supported:
            actions.append("remove_share")
        publication = None
    else:
        actions = get_group_document_collaboration_actions(
            document, user_id, group_id, context=(group, role), settings=settings,
            source_groups={document["group_id"]: source},
        )
        publication = _publication_view(document, user_id, group_id, context)
    _context(user_id, group_id)
    return {
        "schema_version": 1, "group_id": group_id, "document_id": document_id,
        "document_version": _version(document), "etag": document["_etag"],
        "owner_group": {key: value for key, value in _group_projection(source, document["group_id"]).items() if key != "description"},
        "relationship": relationship, "actions": actions, "recipients": recipients, "publication": publication,
    }


def group_document_sharing_targets(user_id, group_id, document_id, args):
    document, relationship, context = _read_state(user_id, group_id, document_id, allow_terminal=False)
    if relationship != "owner" or context[1] not in GROUP_DOCUMENT_MANAGER_ROLES:
        raise GroupDocumentCollaborationError("owner_required", "Only source group managers can search sharing targets.", 403)
    try:
        page = int(args.get("page", "1"))
        page_size = int(args.get("page_size", "10"))
    except (TypeError, ValueError) as error:
        raise GroupDocumentCollaborationError("invalid_page", "Pagination must use positive integers.", 400) from error
    if page < 1 or page_size < 1:
        raise GroupDocumentCollaborationError("invalid_page", "Pagination must use positive integers.", 400)
    groups = [
        _group_projection(group) for group in discover_group_records(args.get("search", ""))
        if group.get("id") != group_id and _positive_group(group)
    ]
    groups.sort(key=lambda group: (group["name"].casefold(), group["id"]))
    _context(user_id, group_id)
    offset = (page - 1) * page_size
    return {"groups": groups[offset:offset + page_size], "page": page, "page_size": page_size, "total_count": len(groups)}


def _require_share_action(user_id, group_id, document, action, target_group_id):
    group, role, _settings, supported = _context(user_id, group_id)
    if role not in GROUP_DOCUMENT_MANAGER_ROLES or action not in supported:
        raise GroupDocumentCollaborationError("collaboration_forbidden", "Your current group role or status does not permit this action.", 403)
    owner = document["group_id"] == group_id
    relationship = _group_document_share_status(document, group_id)
    if action in {"share", "unshare"} and not owner:
        raise GroupDocumentCollaborationError("owner_required", "Only the source group can change its recipient grants.", 403)
    if action in {"approve_share", "remove_share"}:
        if owner:
            raise GroupDocumentCollaborationError("recipient_required", "This action requires an incoming group share.", 400)
        if relationship is None and not (action == "remove_share" and _terminal_relationship(document, group_id)):
            raise GroupDocumentCollaborationError("collaboration_gone", "The incoming share is no longer available.", 404)
    if action in {"share", "approve_share"}:
        source = group if owner else find_group_by_id(document["group_id"])
        target = find_group_by_id(target_group_id)
        if not target:
            raise GroupDocumentCollaborationError("target_not_found", "The recipient group was not found.", 404)
        if not _positive_group(source) or not _positive_group(target):
            raise GroupDocumentCollaborationError("sharing_unavailable", "The source and recipient must currently allow sharing.", 403)
        if not is_current_group_document(document) or not _available(document):
            raise GroupDocumentCollaborationError("source_unavailable", "The exact current document must be available before granting access.", 409)


def _replace(document, updates):
    replacement = {**deepcopy(document), **deepcopy(updates)}
    assert_no_group_document_projection_writer(document)
    try:
        saved = cosmos_group_documents_container.replace_item(
            item=document["id"], body=replacement, etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except Exception as error:
        if getattr(error, "status_code", None) in {404, 409, 412}:
            raise GroupDocumentCollaborationError("state_conflict", "The document state changed. Refresh before retrying.", 409) from error
        raise GroupDocumentCollaborationError(
            "write_outcome_uncertain", "A conditional write could not be confirmed. Refresh; do not blindly repeat the action.", 503,
        ) from error
    if not isinstance(saved, dict) or not saved.get("_etag") or saved.get("id") != document["id"]:
        raise GroupDocumentCollaborationError("write_outcome_uncertain", "The document update could not be confirmed.", 503)
    return saved


def _operation_document(document_id, operation_id):
    document = read_group_document_record(document_id)
    operation = _operation(document)
    if not _operation_bound(document, operation) or operation.get("id") != operation_id:
        raise GroupDocumentCollaborationError("operation_changed", "The collaboration operation changed. Refresh before continuing.", 409)
    return document, operation


def _checkpoint(document_id, operation_id, change, *, execution_token=None):
    for _attempt in range(3):
        document, operation = _operation_document(document_id, operation_id)
        if execution_token is not None and operation.get("execution_token") != execution_token:
            raise GroupDocumentCollaborationError("operation_busy", "This operation is being reconciled by another request.", 409)
        updated = change(deepcopy(operation))
        try:
            return _replace(document, {COLLABORATION_OPERATION: updated})
        except GroupDocumentCollaborationError as error:
            if error.error_code != "state_conflict":
                raise
    raise GroupDocumentCollaborationError("operation_busy", "The document is changing. Refresh before continuing.", 409)


def _operation_receipt(group_id, document, action, target_group_id, status, state, errors):
    result = {
        "schema_version": 1, "group_id": group_id, "document_id": document["id"],
        "action": action, "status": status, "state": state, "errors": errors,
    }
    if action in {"share", "unshare"}:
        result["target_group_id"] = target_group_id
    return result


def _ambiguous_transport_failure(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (TimeoutError, ConnectionError, ServiceRequestError, ServiceResponseError)):
            return True
        if type(error).__name__ in {"ReadTimeout", "ConnectTimeout", "Timeout", "ConnectionError"}:
            return True
        error = error.__cause__ or error.__context__
    return False


def _search_acl(document, *, operation_guard):
    client = _get_search_client(group_id=document["group_id"])
    escaped_id = document["id"].replace("'", "''")
    chunks = list(client.search(
        search_text="*", filter=f"document_id eq '{escaped_id}'", select=["id", "document_id", "group_id", "version"],
    ))
    document = operation_guard()
    available = _available(document) and is_current_group_document(document)
    entries = list(document.get("shared_group_ids") or []) if available else []
    updates = []
    for chunk in chunks:
        if (
            chunk.get("document_id") != document["id"]
            or str(chunk.get("version")) != str(document.get("version", 1))
            or available and chunk.get("group_id") != document["group_id"]
        ):
            raise RuntimeError("The exact document Search projection could not be confirmed.")
        updates.append({"id": chunk["id"], "shared_group_ids": entries})
    if updates:
        _execute_document_search_write(
            client, "merge_documents", documents=updates, group_id=document["group_id"],
            document_id=document["id"], document_version=document.get("version", 1),
        )


def _notification_effect(document, operation, *, operation_guard):
    target_id = operation["target_group_id"]
    source_id = document["group_id"]
    metadata = {
        "share_scope": "group", "document_id": document["id"], "document_version": _version(document),
        "source_group_id": source_id, "target_group_id": target_id, "request_id": operation["request_id"],
    }
    context = {"workspace_type": "group", "group_id": target_id, "document_id": document["id"]}
    target_url = f"/v2/groups/{quote(target_id, safe='')}/documents?document_id={quote(document['id'], safe='')}"
    if operation["action"] == "share":
        target = find_group_by_id(target_id)
        reviewers = get_group_document_reviewer_ids(target)
        for reviewer in reviewers:
            operation_guard()
            if reviewer not in get_group_document_reviewer_ids(find_group_by_id(target_id)):
                continue
            notification = create_notification(
                user_id=reviewer, notification_type="group_document_share_pending",
                title="Group document share needs approval",
                message=f'"{document.get("file_name") or "Document"}" was shared with {str((target or {}).get("name") or "your group")}.',
                link_url=target_url, link_context=context, metadata=metadata,
                idempotency_key=f"group-share:{operation['request_id']}:pending", strict=True,
            )
            if not notification:
                raise RuntimeError("Share notification delivery was not confirmed.")
        return
    delete_notifications_by_metadata(
        metadata_filters=metadata, notification_types=["group_document_share_pending"], strict=True,
        operation_guard=operation_guard,
    )
    if operation.get("legacy_pending_notice"):
        delete_notifications_by_metadata(
            metadata_filters={key: value for key, value in metadata.items() if key not in {"request_id", "document_version"}},
            notification_types=["group_document_share_pending"], strict=True,
            missing_metadata_fields=("request_id", "document_version"),
            operation_guard=operation_guard,
        )
    if operation["action"] == "unshare":
        return
    source = find_group_by_id(source_id) or {}
    detail = _details(document, target_id)
    recipient = detail.get("shared_by_user_id") or (source.get("owner") or {}).get("id")
    if not recipient:
        raise RuntimeError("The share decision audience could not be confirmed.")
    state = operation["state"]
    notification_type = {
        "approved": "group_document_share_approved", "denied": "group_document_share_denied",
        "removed": "group_document_share_removed",
    }[state]
    operation_guard()
    notification = create_notification(
        user_id=recipient, notification_type=notification_type,
        title="Group document access removed" if state == "removed" else f"Group document share {state}",
        message=f'The recipient group {state} access to "{document.get("file_name") or "Document"}".',
        link_url=f"/v2/groups/{quote(source_id, safe='')}/documents?document_id={quote(document['id'], safe='')}",
        link_context={"workspace_type": "group", "group_id": source_id, "document_id": document["id"]},
        metadata={**metadata, "decision": state},
        idempotency_key=f"group-share:{operation['request_id']}:decision:{state}", strict=True,
    )
    if not notification:
        raise RuntimeError("Share decision notification delivery was not confirmed.")


def _run_share_effects(user_id, actor_group_id, document, action, target_group_id, *, changed):
    operation = _operation(document)
    operation_id = operation["id"]
    token = str(uuid.uuid4())

    def guard():
        current, executing = _operation_document(document["id"], operation_id)
        if executing.get("phase") != "executing" or executing.get("execution_token") != token:
            raise GroupDocumentCollaborationError("operation_changed", "The collaboration execution changed.", 409)
        _require_share_action(user_id, actor_group_id, current, action, target_group_id)
        return current

    def claim(current):
        if current.get("phase") not in {"claimed", "repair"}:
            raise GroupDocumentCollaborationError("operation_busy", "The existing operation needs reconciliation before another action.", 409)
        return {**current, "phase": "executing", "execution_token": token}

    document = _checkpoint(document["id"], operation["id"], claim)
    errors = []
    for stage in COLLABORATION_EFFECTS:
        current, operation = _operation_document(document["id"], operation["id"])
        if operation.get("execution_token") != token:
            raise GroupDocumentCollaborationError("operation_changed", "The collaboration execution changed.", 409)
        if operation["effects"].get(stage) == "complete":
            continue
        effect_started = False
        try:
            _require_share_action(user_id, actor_group_id, current, action, target_group_id)
            effect_started = True
            if stage == "search":
                with group_collaboration_projection_context(current["id"], operation["id"], token):
                    _search_acl(current, operation_guard=guard)
            elif stage == "index":
                with group_collaboration_projection_context(current["id"], operation["id"], token):
                    result = sync_document_access_index_for_document_fail_open(
                        current, operation="group_document_collaboration", raise_on_error=True,
                    )
                if not result.get("success"):
                    raise RuntimeError("Access index repair is required.")
            elif stage == "cache":
                for scope_id in {current["group_id"], target_group_id}:
                    guard()
                    invalidate_group_search_cache(scope_id, document_id=current["id"], strict=True)
            else:
                _notification_effect(current, operation, operation_guard=guard)
            document = _checkpoint(
                current["id"], operation["id"],
                lambda value: {**value, "effects": {**value["effects"], stage: "complete"}},
                execution_token=token,
            )
        except Exception as error:
            log_event(
                "[DOCUMENTS] Group collaboration effect needs reconciliation.",
                extra={"document_id": current["id"], "stage": stage, "exception_type": type(error).__name__},
                level=logging.ERROR,
            )
            errors.append({"stage": stage, "code": f"{stage}_repair_required", "message": f"The {stage} update could not be confirmed. Refresh before retrying."})
            phase = "uncertain" if effect_started and _ambiguous_transport_failure(error) else "repair"
            try:
                document = _checkpoint(
                    current["id"], operation["id"], lambda value: {**value, "phase": phase},
                    execution_token=token,
                )
            except GroupDocumentReadError:
                raise GroupDocumentCollaborationError("effect_outcome_uncertain", "The operation changed stored state but its effects could not be confirmed.", 503) from error
            break
    if not errors:
        document = _checkpoint(
            document["id"], operation["id"], lambda value: {**value, "phase": "complete"},
            execution_token=token,
        )
    return _operation_receipt(
        actor_group_id, document, action, target_group_id,
        "partial" if errors else "applied" if changed else "unchanged", _operation(document)["state"], errors,
    ), 207 if errors else 200


def change_group_document_share(user_id, group_id, document_id, action, payload, *, target_group_id=None):
    allowed = {"expected_etag", "target_group_id"} if action == "share" else {"expected_etag"}
    require_payload(payload, allowed, allowed)
    expected = _expected_etag(payload["expected_etag"])
    if action == "share":
        target_group_id = payload["target_group_id"]
    if action in {"approve_share", "remove_share"}:
        target_group_id = group_id
    _validate_group_read_id(target_group_id)
    document, relationship, _ctx = _read_state(user_id, group_id, document_id)
    _check_etag(document, expected)
    if action in {"share", "unshare"} and target_group_id == group_id:
        raise GroupDocumentCollaborationError("self_share", "A group cannot share a document with itself.", 400)
    _require_share_action(user_id, group_id, document, action, target_group_id)
    existing = _operation(document)
    if existing and _unfinished(existing):
        same_target = existing.get("target_group_id") == target_group_id
        same_action = existing.get("action") == action or action in NEGATIVE_SHARE_ACTIONS and existing.get("action") in NEGATIVE_SHARE_ACTIONS
        if not _operation_bound(document, existing) or not same_target or not same_action:
            raise GroupDocumentCollaborationError("operation_busy", "Finish or reconcile the existing collaboration operation first.", 409)
        return _run_share_effects(user_id, group_id, document, action, target_group_id, changed=False)
    before = _group_document_share_status(document, target_group_id)
    state = (
        before if action == "share" and before in {"approved", "not_approved"} else
        "not_approved" if action == "share" else "approved" if action == "approve_share" else
        "denied" if action == "remove_share" and before == "not_approved" else "removed"
    )
    unchanged = action == "share" and before in {"approved", "not_approved"} or action == "approve_share" and before == "approved"
    if unchanged:
        return _operation_receipt(group_id, document, action, target_group_id, "unchanged", state, []), 200
    if action == "unshare" and before is None and existing and existing.get("target_group_id") == target_group_id and not _unfinished(existing):
        return _operation_receipt(group_id, document, action, target_group_id, "unchanged", "removed", []), 200
    timestamp = datetime.now(timezone.utc).isoformat()
    detail = deepcopy(_details(document, target_group_id))
    legacy_pending_notice = before in {"not_approved", "approved"} and not detail.get("request_id")
    request_id = str(uuid.uuid4()) if action == "share" else detail.get("request_id") or str(uuid.uuid4())
    detail.update({
        "request_id": request_id, "document_id": document_id, "document_version": _version(document),
        "source_group_id": document["group_id"], "target_group_id": target_group_id, "status": state,
    })
    if action == "share":
        detail.update(shared_by_user_id=user_id, shared_at=timestamp)
    else:
        detail.update(decided_by_user_id=user_id, decided_at=timestamp)
    groups = deepcopy((document.get("document_share_details") or {}).get("groups") or {})
    groups[target_group_id] = detail
    entries = [
        entry for entry in document.get("shared_group_ids") or []
        if str(entry).split(",", 1)[0] != target_group_id
    ]
    if state in {"approved", "not_approved"}:
        entries.append(f"{target_group_id},{state}")
    operation = {
        "schema_version": 1, "id": str(uuid.uuid4()), "request_id": request_id,
        "document_id": document_id, "document_version": _version(document), "source_group_id": document["group_id"],
        "target_group_id": target_group_id, "actor_group_id": group_id, "actor_user_id": user_id,
        "action": action, "state": state, "had_relationship": before is not None,
        "legacy_pending_notice": legacy_pending_notice,
        "phase": "claimed", "effects": {stage: "pending" for stage in COLLABORATION_EFFECTS},
        "created_at": timestamp,
    }
    _require_share_action(user_id, group_id, document, action, target_group_id)
    document = _replace(document, {
        "shared_group_ids": entries,
        "document_share_details": {**(document.get("document_share_details") or {}), "groups": groups},
        "last_updated": timestamp, COLLABORATION_OPERATION: operation,
    })
    return _run_share_effects(user_id, group_id, document, action, target_group_id, changed=True)
