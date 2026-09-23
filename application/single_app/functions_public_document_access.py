# functions_public_document_access.py
"""Current public-workspace/document authorization shared by read browsing.

The workspace identity is always taken from the caller's explicit target, never
from a stored active-workspace preference, so a stale or concurrently changed
selection can never redirect a read into a different public workspace.
"""

import logging
import re

from werkzeug.exceptions import HTTPException

from config import cosmos_content_screening_container, cosmos_public_documents_container
from content_screening.access import _active_blob_reference, _read_authorized_document, public_document_payload
from content_screening.contracts import SCREENING_FIELD, ScreeningError, subject_from_document
from functions_appinsights import log_event
from functions_documents import (
    _blob_exists,
    _get_document_family_key,
    is_pdf_or_image_file_name,
    select_current_documents,
)
from functions_public_document_policy import (
    PUBLIC_DOCUMENT_MANAGER_ROLES,
    PUBLIC_DOCUMENT_MUTABLE_SCREENING_STATES,
    public_document_actions,
    public_document_approval_pending,
    public_document_management_operations,
)
from functions_public_workspaces import (
    check_public_workspace_status_allows_operation,
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)
from functions_settings import get_settings, is_public_workspace_file_download_enabled


PUBLIC_DOCUMENT_READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
PUBLIC_DOCUMENT_READ_STATUSES = ("active", "locked", "upload_disabled")
INVALID_PUBLIC_READ_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class PublicDocumentReadError(HTTPException):
    """A stable, non-sensitive failure at a public document boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_public_read_id(workspace_id):
    if (
        not isinstance(workspace_id, str) or not workspace_id or len(workspace_id) > 512
        or workspace_id != workspace_id.strip() or workspace_id in (".", "..")
        or INVALID_PUBLIC_READ_ID.search(workspace_id)
    ):
        raise PublicDocumentReadError("Invalid public workspace identifier.", 400)


def require_public_document_read_context(user_id, workspace_id):
    """Independently revalidate membership and status on every request.

    A stored active-workspace preference is never an authorization grant: the
    workspace is resolved only from the caller's explicit target.
    """
    _validate_public_read_id(workspace_id)
    if not user_id:
        raise PublicDocumentReadError("User not authenticated.", 401)
    workspace = find_public_workspace_by_id(workspace_id)
    if not workspace:
        raise PublicDocumentReadError("The selected public workspace was not found.", 404)
    role = get_user_role_in_public_workspace(workspace, user_id)
    if role not in PUBLIC_DOCUMENT_READER_ROLES:
        raise PublicDocumentReadError("You do not have access to the selected public workspace.", 403)
    allowed, _reason = check_public_workspace_status_allows_operation(workspace, "view")
    if not allowed or workspace.get("status", "active") not in PUBLIC_DOCUMENT_READ_STATUSES:
        raise PublicDocumentReadError(
            "Documents are unavailable for this public workspace's current status.", 403,
        )
    return workspace, role


def public_document_family_records(document):
    field = (
        "revision_family_id" if document.get("revision_family_id") else
        "xsd_revision_identity" if document.get("document_kind") == "xml_schema" and document.get("xsd_revision_identity")
        else "file_name"
    )
    records = list(cosmos_public_documents_container.query_items(
        query=f"SELECT * FROM c WHERE c.public_workspace_id = @owner_workspace_id AND c.{field} = @family_identity",
        parameters=[
            {"name": "@owner_workspace_id", "value": document["public_workspace_id"]},
            {"name": "@family_identity", "value": document.get(field)},
        ],
        enable_cross_partition_query=True,
    ))
    return [
        record for record in records
        if record.get("public_workspace_id") == document["public_workspace_id"]
        and _get_document_family_key(record) == _get_document_family_key(document)
    ]


def is_current_public_document(document):
    if document.get("is_current_version") is False:
        return False
    family = public_document_family_records(document)
    current = select_current_documents(family)
    return bool(current and current[0].get("is_current_version") is not False and current[0]["id"] == document["id"])


def require_public_document_management_context(user_id, workspace_id, operation):
    """Revalidate reader access, manager role, status, and operation policy per request."""
    workspace, role = require_public_document_read_context(user_id, workspace_id)
    if role not in PUBLIC_DOCUMENT_MANAGER_ROLES:
        raise PublicDocumentReadError(
            "You do not have permission to manage this public workspace's documents.", 403,
        )
    settings = get_settings()
    operations = public_document_management_operations(
        workspace, role, settings,
        download_enabled=is_public_workspace_file_download_enabled(settings, workspace),
    )
    if operation not in operations:
        raise PublicDocumentReadError("This operation is unavailable for the selected public workspace.", 403)
    return workspace, role, settings


def read_public_document_record(document_id):
    try:
        document = cosmos_public_documents_container.read_item(item=document_id, partition_key=document_id)
    except Exception as error:
        if getattr(error, "status_code", None) == 404:
            raise PublicDocumentReadError("Document not found or access denied.", 404) from error
        raise
    if (
        not isinstance(document, dict) or document.get("id") != document_id
        or not document.get("public_workspace_id") or document.get("group_id")
    ):
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    return document


def public_document_cleanup_allowed(document, available):
    if public_document_approval_pending(document):
        return False
    if SCREENING_FIELD not in document or available:
        return True
    marker = document.get(SCREENING_FIELD)
    if not isinstance(marker, dict) or marker.get("state") not in PUBLIC_DOCUMENT_MUTABLE_SCREENING_STATES:
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


def get_public_document_actions(
    document, user_id, workspace_id, *, context=None, settings=None, public_payload=None, current_revision=None,
):
    """Compute per-document operations fresh from current authorization and resource state."""
    workspace, role = context or require_public_document_read_context(user_id, workspace_id)
    settings = settings if settings is not None else get_settings()
    download_enabled = is_public_workspace_file_download_enabled(settings, workspace)
    operations = public_document_management_operations(workspace, role, settings, download_enabled=download_enabled)
    if not operations:
        return []
    if document.get("public_workspace_id") != workspace_id:
        return []
    if public_document_approval_pending(document):
        return []
    public_payload = public_payload if public_payload is not None else public_document_payload(document)
    available = SCREENING_FIELD not in document or (public_payload.get(SCREENING_FIELD) or {}).get("available") is True
    try:
        if document.get("is_current_version") is False:
            current_revision = False
        elif current_revision is None:
            current_revision = is_current_public_document(document)
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
                    "[DOCUMENTS] Public document source availability could not be established.",
                    extra={"document_id": document.get("id"), "public_workspace_id": workspace_id, "exception_type": type(error).__name__},
                    level=logging.ERROR,
                )
        cleanup_allowed = "delete" in operations and public_document_cleanup_allowed(document, available)
        return public_document_actions(
            document, workspace, role, settings, available=available,
            source_available=source_available,
            reprocess_supported=reprocess_supported,
            extraction_supported=bool(document.get("num_chunks") or document.get("number_of_pages")),
            cleanup_allowed=cleanup_allowed, download_enabled=download_enabled,
            current_revision=current_revision,
        )
    except Exception as error:
        log_event(
            "[DOCUMENTS] Public document operation eligibility could not be established.",
            extra={"document_id": document.get("id"), "public_workspace_id": workspace_id, "exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        return []


def authorize_public_document_operation(user_id, workspace_id, document_id, operation, *, expected_version=None):
    workspace, role, settings = require_public_document_management_context(user_id, workspace_id, operation)
    document = read_public_document_record(document_id)
    if document.get("public_workspace_id") != workspace_id:
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    if expected_version is not None and str(document.get("version")) != str(expected_version):
        raise PublicDocumentReadError("The document revision changed. Refresh and try again.", 409)
    actions = get_public_document_actions(
        document, user_id, workspace_id, context=(workspace, role), settings=settings,
    )
    if operation not in actions:
        raise PublicDocumentReadError("This operation is unavailable for the selected document.", 409)
    require_public_document_management_context(user_id, workspace_id, operation)
    return document


def read_public_download_metadata(
    document_id, user_id, group_id=None, public_workspace_id=None, *, actor_id, target_workspace_id,
):
    """A download reader bound to the recipient even during source-provenance refresh."""
    if user_id != actor_id or group_id:
        raise PermissionError("Document not found or access denied.")
    document = authorize_public_document_operation(actor_id, target_workspace_id, document_id, "download")
    fresh = _read_authorized_document(document_id, actor_id, public_workspace_id=target_workspace_id)
    if (
        fresh.get("public_workspace_id") != document["public_workspace_id"]
        or fresh.get("version") != document.get("version")
    ):
        raise PublicDocumentReadError("The document revision changed. Refresh and try again.", 409)
    require_public_document_management_context(actor_id, target_workspace_id, "download")
    return fresh
