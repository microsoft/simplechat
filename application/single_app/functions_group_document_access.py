# functions_group_document_access.py
"""Current group/document authorization shared by browsing and management."""

import logging
import re

from werkzeug.exceptions import HTTPException

from config import cosmos_content_screening_container, cosmos_group_documents_container
from content_screening.access import _active_blob_reference, _read_authorized_document, public_document_payload
from content_screening.contracts import SCREENING_FIELD, ScreeningError, subject_from_document
from functions_appinsights import log_event
from functions_documents import _blob_exists, _get_document_family_key, is_pdf_or_image_file_name, select_current_documents
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_document_policy import (
    GROUP_DOCUMENT_MANAGER_ROLES,
    GROUP_DOCUMENT_MUTABLE_SCREENING_STATES,
    group_document_approval_pending,
    group_document_actions,
    group_document_management_operations,
)
from functions_settings import get_settings, is_group_workspace_file_download_enabled


GROUP_DOCUMENT_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
GROUP_DOCUMENT_READ_STATUSES = ("active", "locked", "upload_disabled")
INVALID_GROUP_READ_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class GroupDocumentReadError(HTTPException):
    """A stable, non-sensitive failure at a group document boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_group_read_id(group_id):
    if (
        not isinstance(group_id, str) or not group_id or len(group_id) > 512
        or group_id != group_id.strip() or group_id in (".", "..")
        or INVALID_GROUP_READ_ID.search(group_id)
    ):
        raise GroupDocumentReadError("Invalid group identifier.", 400)


def require_group_document_read_context(user_id, group_id):
    _validate_group_read_id(group_id)
    if not user_id:
        raise GroupDocumentReadError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_DOCUMENT_READER_ROLES)
    except LookupError as error:
        raise GroupDocumentReadError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupDocumentReadError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupDocumentReadError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_DOCUMENT_READER_ROLES:
        raise GroupDocumentReadError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_DOCUMENT_READ_STATUSES:
        raise GroupDocumentReadError("Documents are unavailable for this group's current status.", 403)
    return group, role


def _group_document_share_status(document, group_id):
    if document.get("group_id") == group_id:
        return "owner"
    entries = document.get("shared_group_ids")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if entry == group_id or entry == f"{group_id},approved":
            return "approved"
        if entry == f"{group_id},not_approved":
            return "not_approved"
    return None


def require_group_document_management_context(user_id, group_id, operation):
    group, role = require_group_document_read_context(user_id, group_id)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_DOCUMENT_MANAGER_ROLES)
    except (LookupError, PermissionError) as error:
        raise GroupDocumentReadError("You do not have permission to manage this group's documents.", 403) from error
    settings = get_settings()
    operations = group_document_management_operations(
        group, role, settings, download_enabled=is_group_workspace_file_download_enabled(settings, group),
    )
    if operation not in operations:
        raise GroupDocumentReadError("This operation is unavailable for the selected group.", 403)
    return group, role, settings


def read_group_document_record(document_id):
    try:
        document = cosmos_group_documents_container.read_item(item=document_id, partition_key=document_id)
    except Exception as error:
        if getattr(error, "status_code", None) == 404:
            raise GroupDocumentReadError("Document not found or access denied.", 404) from error
        raise
    if (
        not isinstance(document, dict) or document.get("id") != document_id
        or not document.get("group_id") or document.get("public_workspace_id")
    ):
        raise GroupDocumentReadError("Document not found or access denied.", 404)
    return document


def group_document_cleanup_allowed(document, available):
    if group_document_approval_pending(document):
        return False
    if SCREENING_FIELD not in document or available:
        return True
    marker = document.get(SCREENING_FIELD)
    if not isinstance(marker, dict) or marker.get("state") not in GROUP_DOCUMENT_MUTABLE_SCREENING_STATES:
        return False
    scan_id = marker.get("scan_id")
    if not isinstance(scan_id, str) or not scan_id:
        return False
    try:
        scan = cosmos_content_screening_container.read_item(item=scan_id, partition_key=scan_id)
    except Exception as error:
        if getattr(error, "status_code", None) == 404:
            return False
        raise
    return (
        scan.get("kind") == "scan" and scan.get("id") == scan_id
        and scan.get("subject") == subject_from_document(document).to_dict()
        and scan.get("state") == marker.get("state")
    )


def group_document_family_records(document):
    field = (
        "revision_family_id" if document.get("revision_family_id") else
        "xsd_revision_identity" if document.get("document_kind") == "xml_schema" and document.get("xsd_revision_identity")
        else "file_name"
    )
    records = list(cosmos_group_documents_container.query_items(
        query=f"SELECT * FROM c WHERE c.group_id = @owner_group_id AND c.{field} = @family_identity",
        parameters=[
            {"name": "@owner_group_id", "value": document["group_id"]},
            {"name": "@family_identity", "value": document.get(field)},
        ],
        enable_cross_partition_query=True,
    ))
    return [
        record for record in records
        if record.get("group_id") == document["group_id"]
        and _get_document_family_key(record) == _get_document_family_key(document)
    ]


def is_current_group_document(document):
    if document.get("is_current_version") is False:
        return False
    family = group_document_family_records(document)
    current = select_current_documents(family)
    return bool(current and current[0].get("is_current_version") is not False and current[0]["id"] == document["id"])


def get_group_document_actions(
    document, user_id, group_id, *, context=None, settings=None, public_payload=None, source_groups=None,
    current_revision=None,
):
    group, role = context or require_group_document_read_context(user_id, group_id)
    settings = settings if settings is not None else get_settings()
    download_enabled = is_group_workspace_file_download_enabled(settings, group)
    operations = group_document_management_operations(group, role, settings, download_enabled=download_enabled)
    if not operations:
        return []
    relationship = _group_document_share_status(document, group_id)
    if relationship not in {"owner", "approved"}:
        return []
    if group_document_approval_pending(document):
        return []
    public_payload = public_payload if public_payload is not None else public_document_payload(document)
    available = SCREENING_FIELD not in document or (public_payload.get(SCREENING_FIELD) or {}).get("available") is True
    try:
        if document.get("is_current_version") is False:
            current_revision = False
        elif current_revision is None:
            current_revision = is_current_group_document(document)
        reprocess_supported = is_pdf_or_image_file_name(document.get("file_name"))
        source_available = False
        if available and ("download" in operations or ("reprocess" in operations and reprocess_supported)):
            try:
                container, path = _active_blob_reference(document)
                source_available = _blob_exists(container, path)
            except ScreeningError:
                source_available = False
            except Exception as error:
                log_event(
                    "[DOCUMENTS] Group document source availability could not be established.",
                    extra={"document_id": document.get("id"), "group_id": group_id, "exception_type": type(error).__name__},
                    level=logging.ERROR,
                )
        if relationship == "owner":
            source_group = group
        elif source_groups is not None and document["group_id"] in source_groups:
            source_group = source_groups[document["group_id"]]
        else:
            source_group = find_group_by_id(document["group_id"])
        source_download_allowed = bool(
            source_group and source_group.get("status", "active") in GROUP_DOCUMENT_READ_STATUSES
            and is_group_workspace_file_download_enabled(settings, source_group)
        )
        cleanup_allowed = relationship == "owner" and "delete" in operations and group_document_cleanup_allowed(document, available)
        return group_document_actions(
            document, group, role, settings, available=available,
            source_available=source_available,
            reprocess_supported=reprocess_supported,
            extraction_supported=bool(document.get("num_chunks") or document.get("number_of_pages")),
            cleanup_allowed=cleanup_allowed, source_download_allowed=source_download_allowed,
            download_enabled=download_enabled,
            current_revision=current_revision,
        )
    except Exception as error:
        log_event(
            "[DOCUMENTS] Group document operation eligibility could not be established.",
            extra={"document_id": document.get("id"), "group_id": group_id, "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        return []


def authorize_group_document_operation(user_id, group_id, document_id, operation, *, expected_version=None):
    group, role, settings = require_group_document_management_context(user_id, group_id, operation)
    document = read_group_document_record(document_id)
    relationship = _group_document_share_status(document, group_id)
    if relationship is None:
        raise GroupDocumentReadError("Document not found or access denied.", 404)
    if operation != "download" and relationship != "owner":
        raise GroupDocumentReadError("Only documents owned by the selected group can be changed.", 403)
    if expected_version is not None and str(document.get("version")) != str(expected_version):
        raise GroupDocumentReadError("The document revision changed. Refresh and try again.", 409)
    actions = get_group_document_actions(
        document, user_id, group_id, context=(group, role), settings=settings,
    )
    if operation not in actions:
        raise GroupDocumentReadError("This operation is unavailable for the selected document.", 409)
    require_group_document_management_context(user_id, group_id, operation)
    return document


def read_group_download_metadata(document_id, user_id, group_id, public_workspace_id=None, *, actor_id, target_group_id):
    """A download reader bound to the recipient even during source-provenance refresh."""
    if user_id != actor_id or public_workspace_id:
        raise PermissionError("Document not found or access denied.")
    document = authorize_group_document_operation(actor_id, target_group_id, document_id, "download")
    fresh = _read_authorized_document(document_id, actor_id, group_id=target_group_id)
    if fresh.get("group_id") != document["group_id"] or fresh.get("version") != document.get("version"):
        raise GroupDocumentReadError("The document revision changed. Refresh and try again.", 409)
    require_group_document_management_context(actor_id, target_group_id, "download")
    return fresh
