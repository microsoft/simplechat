# functions_group_document_management.py
"""Immutable-target group document operations; legacy route contracts stay separate."""

from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
import json
import logging
import os
import tempfile
from urllib.parse import quote
import uuid

from config import cosmos_group_documents_container, cosmos_groups_container
from content_screening.access import assert_document_available
from content_screening.contracts import SCREENING_FIELD, ScreeningError
from content_screening.service import prepare_document_upload
from functions_activity_logging import log_document_metadata_update_transaction
from functions_appinsights import log_event
from functions_documents import (
    DocumentMutationPropagationError,
    DocumentRevisionDeleteError,
    allowed_file,
    build_document_download_response,
    build_documents_zip_download_response,
    create_document,
    delete_document_revision,
    get_default_tag_color,
    get_safe_tag_color,
    normalize_tag,
    process_document_reprocess_extraction_background,
    process_document_upload_background,
    process_metadata_extraction_background,
    select_current_documents,
    update_document,
    validate_tag_color,
    validate_tags,
)
from functions_file_sync import (
    FILE_SYNC_DELETE_ACTIONS,
    FILE_SYNC_SCOPE_GROUP,
    apply_synced_document_delete_action,
    build_synced_document_delete_guard,
)
from functions_group_document_access import (
    GroupDocumentReadError,
    _validate_group_read_id,
    authorize_group_document_operation,
    group_document_family_records,
    read_group_document_record,
    read_group_download_metadata,
    require_group_document_management_context,
)
from functions_settings import get_settings, is_enhanced_extraction_enabled
from utils_cache import invalidate_group_search_cache


GROUP_DOCUMENT_METADATA_FIELDS = frozenset({
    "title", "abstract", "keywords", "publication_date", "document_classification", "authors", "tags",
})
GROUP_DOCUMENT_DELETE_OPTIONS = frozenset({
    "delete_mode", "conversation_linked_delete_confirmed", "file_sync_delete_action",
})
MAX_GROUP_DOCUMENT_BATCH = 1000


class GroupDocumentOperationError(GroupDocumentReadError):
    def __init__(self, message, status_code, *, details=None):
        super().__init__(message, status_code)
        self.payload = {"error": message, **(details or {})}


def validate_group_document_id(document_id):
    _validate_group_read_id(document_id)
    if "'" in document_id:
        raise GroupDocumentOperationError("Invalid document identifier.", 400)
    return document_id


def validate_document_ids(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_GROUP_DOCUMENT_BATCH:
        raise GroupDocumentOperationError("document_ids must contain between 1 and 1000 identifiers.", 400)
    return list(dict.fromkeys(validate_group_document_id(document_id) for document_id in value))


def require_payload(payload, allowed, required=()):
    if not isinstance(payload, dict) or set(payload) - set(allowed) or set(required) - set(payload):
        raise GroupDocumentOperationError("Invalid request fields.", 400)
    return payload


def validate_metadata_changes(payload):
    require_payload(payload, GROUP_DOCUMENT_METADATA_FIELDS)
    if not payload:
        raise GroupDocumentOperationError("No metadata changes were supplied.", 400)
    changes = {}
    for name, value in payload.items():
        if name == "tags":
            valid, message, tags = validate_tags(value)
            if not valid:
                raise GroupDocumentOperationError(message, 400)
            changes[name] = tags
        elif name in {"keywords", "authors"}:
            if isinstance(value, str):
                value = value.split(",") if name == "keywords" else [value]
            if value is None:
                value = []
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise GroupDocumentOperationError(f"{name} must contain text values.", 400)
            changes[name] = [item.strip() for item in value if item.strip()]
        else:
            if value is not None and not isinstance(value, str):
                raise GroupDocumentOperationError(f"{name} must be text.", 400)
            changes[name] = value if value is not None else ""
    return changes


def validate_delete_options(payload, *, query=False):
    require_payload(payload, GROUP_DOCUMENT_DELETE_OPTIONS, {"delete_mode"})
    mode = payload["delete_mode"]
    if not isinstance(mode, str) or mode not in {"current_only", "all_versions"}:
        raise GroupDocumentOperationError("delete_mode must be current_only or all_versions.", 400)
    confirmed = payload.get("conversation_linked_delete_confirmed", False)
    if query and isinstance(confirmed, str):
        if confirmed not in {"true", "false"}:
            raise GroupDocumentOperationError("conversation_linked_delete_confirmed must be a boolean.", 400)
        confirmed = confirmed == "true"
    if type(confirmed) is not bool:
        raise GroupDocumentOperationError("conversation_linked_delete_confirmed must be a boolean.", 400)
    sync_action = payload.get("file_sync_delete_action")
    if sync_action is not None and (not isinstance(sync_action, str) or sync_action not in FILE_SYNC_DELETE_ACTIONS):
        raise GroupDocumentOperationError("Invalid file_sync_delete_action.", 400)
    return {
        "delete_mode": mode,
        "conversation_linked_delete_confirmed": confirmed,
        "file_sync_delete_action": sync_action,
    }


def group_operation_error(error, operation, *, document_id=None, group_id=None):
    if isinstance(error, GroupDocumentOperationError):
        payload, status = dict(error.payload), error.code
    elif isinstance(error, GroupDocumentReadError):
        payload, status = {"error": error.description}, error.code
    elif isinstance(error, ScreeningError):
        payload, status = {"error": error.code, "message": error.public_message}, error.status_code
    elif isinstance(error, PermissionError):
        payload, status = {"error": "Document not found or access denied."}, 403
    elif getattr(error, "status_code", None) in {409, 412}:
        payload, status = {"error": "The resource changed. Refresh and retry the operation."}, 409
    elif getattr(error, "status_code", None) == 404 or isinstance(error, FileNotFoundError):
        payload, status = {"error": "The document source was not found."}, 404
    else:
        log_event(
            "[DOCUMENTS] Scoped group document operation failed.",
            extra={"operation": operation, "document_id": document_id, "group_id": group_id, "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        if isinstance(error, (DocumentMutationPropagationError, DocumentRevisionDeleteError)):
            payload = {
                "error": "document_propagation_incomplete",
                "message": "The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying.",
                "repair_required": True,
            }
        else:
            payload = {"error": "Unable to complete this group document operation."}
        status = 500
        if getattr(error, "deleted_document_ids", None):
            payload["deleted_document_ids"] = error.deleted_document_ids
    if document_id is not None:
        payload["document_id"] = document_id
    if group_id is not None:
        payload["group_id"] = group_id
    return payload, status


def _tag_pointer(tag):
    return f"/tag_definitions/{tag.replace('~', '~0').replace('/', '~1')}"


def _patch_tag_definitions(user_id, group_id, group, changes, removals=()):
    current, _role, _settings = require_group_document_management_context(user_id, group_id, "manage_tags")
    if not group.get("_etag") or current.get("_etag") != group["_etag"]:
        raise GroupDocumentOperationError("The group's tags or permissions changed. Refresh and retry.", 409)
    definitions = group.get("tag_definitions")
    if definitions is not None and not isinstance(definitions, dict):
        raise GroupDocumentOperationError("The group's tag definitions are unavailable.", 409)
    if definitions is None:
        operations = [{"op": "add", "path": "/tag_definitions", "value": changes}]
    else:
        operations = [
            {"op": "set", "path": _tag_pointer(name), "value": value} for name, value in changes.items()
        ]
        operations.extend(
            {"op": "remove", "path": _tag_pointer(name)}
            for name in removals if name in definitions and name not in changes
        )
    if not operations:
        return current
    return cosmos_groups_container.patch_item(
        item=group_id, partition_key=group_id, patch_operations=operations,
        filter_predicate=f"FROM c WHERE c._etag = {json.dumps(group['_etag'])}",
    )


def _new_tag_definition(tag_name, color=None):
    valid, message, normalized_color = validate_tag_color(color, tag_name)
    if not valid:
        raise GroupDocumentOperationError(message, 400)
    return {"color": normalized_color, "created_at": datetime.now(timezone.utc).isoformat()}


def _new_tag_name(value):
    valid, message, tags = validate_tags([value])
    if not valid or len(tags) != 1:
        raise GroupDocumentOperationError(message or "A tag name is required.", 400)
    return tags[0]


def _existing_tag_name(value):
    tag_name = normalize_tag(value)
    if not tag_name or any(ord(character) < 32 for character in tag_name):
        raise GroupDocumentOperationError("A valid tag name is required.", 400)
    return tag_name


def _definition_keys(definitions, tag_name):
    return [name for name in definitions if normalize_tag(name) == tag_name]


def _ensure_document_tag_definitions(user_id, group_id, tags):
    if not tags:
        return
    group, _role, _settings = require_group_document_management_context(user_id, group_id, "tag_documents")
    definitions = group.get("tag_definitions") or {}
    missing = {
        tag: _new_tag_definition(tag) for tag in tags
        if not _definition_keys(definitions, tag)
    }
    if missing:
        _patch_tag_definitions(user_id, group_id, group, missing)


def update_group_document_metadata(
    user_id, group_id, document_id, changes, *, operation="edit_metadata", ensure_definitions=True,
):
    validate_group_document_id(document_id)
    document = authorize_group_document_operation(user_id, group_id, document_id, operation)
    guard = partial(
        authorize_group_document_operation, user_id, group_id, document_id, operation,
        expected_version=document.get("version"),
    )
    saved = update_document(
        document_id=document_id, user_id=user_id, group_id=group_id,
        strict=True, expected_etag=document.get("_etag"), operation_guard=guard, **changes,
    )
    if not isinstance(saved, dict) or saved.get("id") != document_id or saved.get("group_id") != group_id:
        raise DocumentMutationPropagationError("The scoped document update could not be confirmed.")
    if "tags" in changes and ensure_definitions:
        _ensure_document_tag_definitions(user_id, group_id, changes["tags"])
    invalidate_group_search_cache(group_id)
    log_document_metadata_update_transaction(
        user_id=user_id, document_id=document_id, workspace_type="group", group_id=group_id,
        file_name="Screened document" if SCREENING_FIELD in document else document.get("file_name", "Document"),
        updated_fields={name: "[updated]" for name in changes} if SCREENING_FIELD in document else changes,
        file_type=document.get("file_type"),
    )
    queued = SCREENING_FIELD in document and any(document.get(name) != value for name, value in changes.items())
    return {
        "message": "Metadata saved and queued for content screening." if queued else "Group document metadata updated.",
        "document_id": document_id, "group_id": group_id,
        "updated_fields": list(changes), "status": "queued" if queued else "updated",
    }


def tag_group_documents(user_id, group_id, payload):
    require_payload(payload, {"document_ids", "action", "tags"}, {"document_ids", "action", "tags"})
    document_ids = validate_document_ids(payload["document_ids"])
    action = payload["action"]
    if not isinstance(action, str) or action not in {"add_tags", "remove_tags", "set_tags"}:
        raise GroupDocumentOperationError("action must be add_tags, remove_tags, or set_tags.", 400)
    if action == "remove_tags":
        if not isinstance(payload["tags"], list) or not all(isinstance(tag, str) for tag in payload["tags"]):
            raise GroupDocumentOperationError("Tags must be an array of text values.", 400)
        tags = list(dict.fromkeys(_existing_tag_name(tag) for tag in payload["tags"]))
    else:
        valid, message, tags = validate_tags(payload["tags"])
        if not valid:
            raise GroupDocumentOperationError(message, 400)
    require_group_document_management_context(user_id, group_id, "tag_documents")
    result = {"success": [], "errors": []}
    for document_id in document_ids:
        try:
            document = authorize_group_document_operation(user_id, group_id, document_id, "tag_documents")
            current_tags = document.get("tags") or []
            if action == "add_tags":
                updated_tags = list(dict.fromkeys([*current_tags, *tags]))
            elif action == "remove_tags":
                updated_tags = [tag for tag in current_tags if normalize_tag(tag) not in tags]
            else:
                updated_tags = tags
            update_group_document_metadata(
                user_id, group_id, document_id, {"tags": updated_tags}, operation="tag_documents",
            )
            result["success"].append({"document_id": document_id, "tags": updated_tags})
        except Exception as error:
            failure, _status = group_operation_error(error, "tag_documents", document_id=document_id, group_id=group_id)
            result["errors"].append(failure)
    return result, 207 if result["errors"] else 200


def create_group_document_tag(user_id, group_id, payload):
    require_payload(payload, {"tag_name", "color"}, {"tag_name"})
    name = _new_tag_name(payload["tag_name"])
    definition = _new_tag_definition(name, payload.get("color"))
    group, _role, _settings = require_group_document_management_context(user_id, group_id, "manage_tags")
    if _definition_keys(group.get("tag_definitions") or {}, name):
        raise GroupDocumentOperationError("Tag already exists.", 409)
    _patch_tag_definitions(user_id, group_id, group, {name: definition})
    return {"message": "Group tag created.", "tag": {"name": name, "color": definition["color"]}}, 201


def _current_owned_documents(group_id):
    records = list(cosmos_group_documents_container.query_items(
        query="SELECT * FROM c WHERE c.group_id = @group_id",
        parameters=[{"name": "@group_id", "value": group_id}],
        enable_cross_partition_query=True,
    ))
    return [
        document for document in select_current_documents(
            [record for record in records if record.get("group_id") == group_id]
        ) if document.get("is_current_version") is not False
    ]


def change_group_document_tag(user_id, group_id, tag_name, payload=None, *, delete=False):
    old_name = _existing_tag_name(tag_name)
    if delete:
        new_name, new_color = None, None
    else:
        require_payload(payload, {"new_name", "color"})
        if not payload:
            raise GroupDocumentOperationError("No tag changes were supplied.", 400)
        new_name = _new_tag_name(payload["new_name"]) if "new_name" in payload else old_name
        new_color = payload.get("color")
        if "color" in payload:
            _new_tag_definition(new_name, new_color)
    group, _role, _settings = require_group_document_management_context(user_id, group_id, "manage_tags")
    definitions = group.get("tag_definitions") or {}
    old_keys = _definition_keys(definitions, old_name)
    documents = _current_owned_documents(group_id)
    targets = [
        document for document in documents if old_name in [normalize_tag(tag) for tag in document.get("tags") or []]
    ]
    if not old_keys and not targets:
        raise GroupDocumentOperationError("Tag not found.", 404)
    old_definition = deepcopy(definitions[old_keys[0]]) if old_keys and isinstance(definitions[old_keys[0]], dict) else _new_tag_definition(old_name)
    old_definition["color"] = get_safe_tag_color(old_definition.get("color"), old_name)
    result = {"message": "Group tag updated.", "documents_updated": 0, "success": [], "errors": [], "vocabulary_retained": False}
    if not delete and new_name == old_name:
        definition = dict(old_definition)
        if "color" in payload:
            definition["color"] = _new_tag_definition(old_name, new_color)["color"]
        _patch_tag_definitions(user_id, group_id, group, {old_name: definition}, removals=old_keys)
        result["tag"] = {"name": old_name, "color": definition["color"]}
        return result, 200

    changes = {}
    if not old_keys:
        changes[old_name] = old_definition
        old_keys = [old_name]
    if not delete:
        new_keys = _definition_keys(definitions, new_name)
        target_definition = deepcopy(definitions[new_keys[0]]) if new_keys and isinstance(definitions[new_keys[0]], dict) else deepcopy(old_definition)
        target_definition["color"] = get_safe_tag_color(target_definition.get("color"), new_name)
        if "color" in payload:
            target_definition["color"] = _new_tag_definition(new_name, new_color)["color"]
        changes[new_name] = target_definition
        result["tag"] = {"name": new_name, "color": target_definition.get("color") or get_default_tag_color(new_name)}
    group = _patch_tag_definitions(user_id, group_id, group, changes)
    for target in targets:
        document_id = target["id"]
        try:
            document = authorize_group_document_operation(user_id, group_id, document_id, "tag_documents")
            if document.get("is_current_version") is False or document.get("version") != target.get("version"):
                raise GroupDocumentOperationError("The current document revision changed. Refresh and retry.", 409)
            updated_tags = [
                new_name if normalize_tag(tag) == old_name else tag for tag in document.get("tags") or []
                if not (delete and normalize_tag(tag) == old_name)
            ]
            updated_tags = list(dict.fromkeys(updated_tags))
            update_group_document_metadata(
                user_id, group_id, document_id, {"tags": updated_tags}, operation="tag_documents", ensure_definitions=False,
            )
            result["success"].append({"document_id": document_id, "tags": updated_tags})
        except Exception as error:
            failure, _status = group_operation_error(error, "manage_tags", document_id=document_id, group_id=group_id)
            result["errors"].append(failure)
    result["documents_updated"] = len(result["success"])
    if not result["errors"]:
        try:
            _patch_tag_definitions(user_id, group_id, group, {}, removals=old_keys)
        except Exception as error:
            failure, status = group_operation_error(error, "manage_tags", group_id=group_id)
            result["errors"].append({
                "stage": "vocabulary", "group_id": group_id,
                "error": "vocabulary_conflict" if status == 409 else "vocabulary_update_failed",
                "message": failure.get("message") or failure["error"],
            })
    result["vocabulary_retained"] = bool(result["errors"])
    result["message"] = (
        "Some tag changes are incomplete. The original vocabulary has been retained; refresh before retrying."
        if result["errors"] else "Group tag deleted." if delete else "Group tag renamed."
    )
    return result, 207 if result["errors"] else 200


def _delete_guard(document, user_id, group_id, options):
    if document.get("created_from_chat_upload") and document.get("conversation_id") and not options["conversation_linked_delete_confirmed"]:
        conversation_id = str(document["conversation_id"])
        return {
            "error": "conversation_linked_document_delete_requires_confirmation",
            "message": "This document is part of a conversation. Confirm its deletion.",
            "needs_confirmation": True,
            "conversation": {
                "id": conversation_id, "title": document.get("conversation_title_at_upload") or "Conversation",
                "url": f"/chats?conversation_id={quote(conversation_id, safe='')}",
            },
            "document": {"id": document["id"], "file_name": document.get("file_name")},
        }
    guard = build_synced_document_delete_guard(
        FILE_SYNC_SCOPE_GROUP, document["id"], user_id, group_id=group_id,
        requested_action=options["file_sync_delete_action"],
    )
    return {**guard, "needs_confirmation": True} if guard else None


def delete_group_document(user_id, group_id, document_id, options):
    validate_group_document_id(document_id)
    document = authorize_group_document_operation(user_id, group_id, document_id, "delete")
    family = group_document_family_records(document)
    if not any(member["id"] == document_id for member in family):
        raise GroupDocumentOperationError("Document not found or access denied.", 404)
    selected = family if options["delete_mode"] == "all_versions" else [document]
    for member in selected:
        fresh = authorize_group_document_operation(
            user_id, group_id, member["id"], "delete", expected_version=member.get("version"),
        )
        guard = _delete_guard(fresh, user_id, group_id, options)
        if guard:
            raise GroupDocumentOperationError(guard["message"], 409, details=guard)
    for member in selected:
        authorize_group_document_operation(user_id, group_id, member["id"], "delete", expected_version=member.get("version"))
        apply_synced_document_delete_action(
            FILE_SYNC_SCOPE_GROUP, member["id"], user_id, options["file_sync_delete_action"], group_id=group_id,
        )
    def guard(document_id=None):
        if document_id is None:
            return require_group_document_management_context(user_id, group_id, "delete")
        return authorize_group_document_operation(user_id, group_id, document_id, "delete")

    result = delete_document_revision(
        user_id=user_id, document_id=document_id, group_id=group_id, delete_mode=options["delete_mode"],
        family_documents=family, strict=True,
        operation_guard=guard,
    )
    invalidate_group_search_cache(group_id)
    return {
        "message": "Group document deleted.", "deleted": [{"document_id": document_id}], "errors": [],
        "deleted_count": 1, "error_count": 0, **result,
    }


def delete_group_documents(user_id, group_id, payload):
    require_payload(payload, {"document_ids", *GROUP_DOCUMENT_DELETE_OPTIONS}, {"document_ids", "delete_mode"})
    document_ids = validate_document_ids(payload["document_ids"])
    options = validate_delete_options({key: value for key, value in payload.items() if key != "document_ids"})
    require_group_document_management_context(user_id, group_id, "delete")
    result = {"deleted": [], "errors": []}
    already_deleted = set()
    for document_id in document_ids:
        try:
            if document_id not in already_deleted:
                outcome = delete_group_document(user_id, group_id, document_id, options)
                already_deleted.update(outcome["deleted_document_ids"])
            result["deleted"].append({"document_id": document_id})
        except Exception as error:
            already_deleted.update(getattr(error, "deleted_document_ids", []))
            failure, _status = group_operation_error(error, "delete", document_id=document_id, group_id=group_id)
            result["errors"].append(failure)
    result.update(deleted_count=len(result["deleted"]), error_count=len(result["errors"]))
    return result, 207 if result["errors"] else 200


def download_group_documents(user_id, group_id, document_ids):
    document_ids = validate_document_ids(document_ids)
    documents = [
        authorize_group_document_operation(user_id, group_id, document_id, "download")
        for document_id in document_ids
    ]
    reader = partial(read_group_download_metadata, actor_id=user_id, target_group_id=group_id)
    if len(documents) == 1:
        response = build_document_download_response(
            documents[0], user_id=user_id, group_id=group_id, metadata_reader=reader,
        )
    else:
        response = build_documents_zip_download_response(
            documents, "group-documents.zip", user_id=user_id, group_id=group_id, metadata_reader=reader,
        )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response, documents


def validate_group_download_response(user_id, group_id, documents):
    reader = partial(read_group_download_metadata, actor_id=user_id, target_group_id=group_id)
    for document in documents:
        assert_document_available(document, user_id, group_id, purpose="download", metadata_reader=reader)


def _save_upload(file, maximum_bytes):
    suffix = os.path.splitext(file.filename)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
        path = temporary.name
        size = 0
        try:
            while chunk := file.stream.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_bytes:
                    raise GroupDocumentOperationError("The file exceeds the configured upload size limit.", 400)
                temporary.write(chunk)
            if size == 0:
                raise GroupDocumentOperationError("Empty files cannot be uploaded.", 400)
        except Exception:
            temporary.close()
            os.remove(path)
            raise
    return path


def upload_group_documents(user_id, group_id, files, executor):
    _group, _role, settings = require_group_document_management_context(user_id, group_id, "upload")
    if not files:
        raise GroupDocumentOperationError("Select at least one file.", 400)
    maximum_bytes = int(float(settings.get("max_file_size_mb", 16)) * 1024 * 1024)
    if maximum_bytes <= 0:
        raise GroupDocumentOperationError("The upload size limit is unavailable.", 503)
    accepted, errors = [], []
    for file in files:
        path = None
        document_id = None
        try:
            name = file.filename
            if not name or any(character in name for character in "/\\") or any(ord(character) < 32 for character in name):
                raise GroupDocumentOperationError("A valid file name is required.", 400)
            if not allowed_file(name):
                raise GroupDocumentOperationError("This file type is not allowed.", 400)
            path = _save_upload(file, maximum_bytes)
            require_group_document_management_context(user_id, group_id, "upload")
            document_id = str(uuid.uuid4())
            create_document(
                file_name=name, user_id=user_id, group_id=group_id, document_id=document_id,
                num_file_chunks=0, status="Queued for processing", source_file_path=path,
            )
            prepare_document_upload(
                document_id=document_id, user_id=user_id, group_id=group_id,
                temp_file_path=path, original_filename=name,
            )
            source = read_group_document_record(document_id)
            require_group_document_management_context(user_id, group_id, "upload")
            executor.submit_stored(
                f"group:{group_id}:{document_id}:upload", run_group_document_job,
                operation="upload", user_id=user_id, group_id=group_id, document_id=document_id,
                expected_version=source.get("version"), temp_file_path=path, original_filename=name,
            )
            path = None
            accepted.append({"document_id": document_id, "file_name": name})
        except Exception as error:
            failure, _status = group_operation_error(error, "upload", document_id=document_id, group_id=group_id)
            errors.append(f"{file.filename or 'Unnamed file'}: {failure.get('message') or failure['error']}")
            if document_id is not None:
                try:
                    require_group_document_management_context(user_id, group_id, "upload")
                    failed_document = read_group_document_record(document_id)
                    if failed_document["group_id"] == group_id and failed_document.get("file_name") == file.filename:
                        update_document(
                            document_id=document_id, user_id=user_id, group_id=group_id,
                            status="Error: Upload could not be queued.", percentage_complete=0,
                            strict=True, expected_etag=failed_document.get("_etag"),
                            operation_guard=partial(require_group_document_management_context, user_id, group_id, "upload"),
                        )
                except Exception as status_error:
                    log_event(
                        "[DOCUMENTS] Failed upload status could not be recorded.",
                        extra={"document_id": document_id, "group_id": group_id, "exception_type": type(status_error).__name__},
                        level=logging.ERROR,
                    )
        finally:
            if path and os.path.exists(path):
                os.remove(path)
    if accepted:
        invalidate_group_search_cache(group_id)
    return {
        "message": f"Queued {len(accepted)} file(s) for processing.",
        "document_ids": [item["document_id"] for item in accepted],
        "processed_filenames": [item["file_name"] for item in accepted],
        "errors": errors,
    }, 200 if accepted and not errors else 207 if accepted else 400


def queue_group_document_jobs(user_id, group_id, payload, operation, executor):
    allowed = {"document_ids", "extraction_mode"} if operation == "reprocess" else {"document_ids"}
    required = allowed if operation == "reprocess" else {"document_ids"}
    require_payload(payload, allowed, required)
    document_ids = validate_document_ids(payload["document_ids"])
    mode = payload.get("extraction_mode")
    if operation == "reprocess":
        if not isinstance(mode, str) or mode not in {"read", "layout"}:
            raise GroupDocumentOperationError("extraction_mode must be read or layout.", 400)
        if mode == "layout" and not is_enhanced_extraction_enabled(get_settings()):
            raise GroupDocumentOperationError("Enhanced extraction is disabled.", 400)
    require_group_document_management_context(user_id, group_id, operation)
    result = {"queued": [], "errors": []}
    for document_id in document_ids:
        try:
            document = authorize_group_document_operation(user_id, group_id, document_id, operation)
            executor.submit_stored(
                f"group:{group_id}:{document_id}:{operation}:{mode or 'default'}", run_group_document_job,
                operation=operation, user_id=user_id, group_id=group_id, document_id=document_id,
                expected_version=document.get("version"), extraction_mode=mode,
            )
            result["queued"].append({
                "document_id": document_id, **({"extraction_mode": mode} if operation == "reprocess" else {}),
            })
        except Exception as error:
            failure, _status = group_operation_error(error, operation, document_id=document_id, group_id=group_id)
            result["errors"].append(failure)
    if result["queued"]:
        invalidate_group_search_cache(group_id)
    return result, 202 if not result["errors"] else 207 if result["queued"] else 400


def run_group_document_job(
    *, operation, user_id, group_id, document_id, expected_version,
    temp_file_path=None, original_filename=None, extraction_mode=None,
):
    """The executor receives only captured identifiers, never active preferences."""
    def guard():
        if operation == "upload":
            require_group_document_management_context(user_id, group_id, "upload")
            document = read_group_document_record(document_id)
            if (
                document["group_id"] != group_id or document.get("user_id") not in {None, user_id}
                or document.get("file_name") != original_filename
                or str(document.get("version")) != str(expected_version)
            ):
                raise GroupDocumentOperationError("The upload target changed.", 409)
            return document
        return authorize_group_document_operation(
            user_id, group_id, document_id, operation, expected_version=expected_version,
        )

    try:
        guard()
        if operation == "upload":
            return process_document_upload_background(
                document_id=document_id, user_id=user_id, group_id=group_id,
                temp_file_path=temp_file_path, original_filename=original_filename,
                operation_guard=guard, safe_errors=True,
            )
        if operation == "extract_metadata":
            return process_metadata_extraction_background(
                document_id=document_id, user_id=user_id, group_id=group_id,
                operation_guard=guard, safe_errors=True,
            )
        if operation == "reprocess":
            if extraction_mode == "layout" and not is_enhanced_extraction_enabled(get_settings()):
                raise GroupDocumentOperationError("Enhanced extraction is disabled.", 400)
            return process_document_reprocess_extraction_background(
                document_id=document_id, user_id=user_id, group_id=group_id,
                target_extraction_mode=extraction_mode, operation_guard=guard, safe_errors=True,
            )
        raise GroupDocumentOperationError("Unknown document operation.", 400)
    except Exception as error:
        log_event(
            "[DOCUMENTS] Captured group document job stopped.",
            extra={"operation": operation, "group_id": group_id, "document_id": document_id, "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        raise
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
