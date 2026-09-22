# functions_public_document_access.py
"""Current public-workspace/document authorization shared by read browsing.

The workspace identity is always taken from the caller's explicit target, never
from a stored active-workspace preference, so a stale or concurrently changed
selection can never redirect a read into a different public workspace.
"""

import re

from werkzeug.exceptions import HTTPException

from config import cosmos_public_documents_container
from functions_documents import _get_document_family_key, select_current_documents
from functions_public_workspaces import (
    check_public_workspace_status_allows_operation,
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)


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
