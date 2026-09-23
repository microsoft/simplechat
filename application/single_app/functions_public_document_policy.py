# functions_public_document_policy.py
"""Public-workspace management capability projections; write routes reauthorize.

Public workspaces have no cross-workspace share relationship (that arrives with
M3C), so these projections describe only owner-scoped management eligibility.
"""

from content_screening.contracts import SCREENING_FIELD


PUBLIC_DOCUMENT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
PUBLIC_DOCUMENT_OPERATIONS = (
    "upload", "edit_metadata", "tag_documents", "manage_tags",
    "delete", "download", "extract_metadata", "reprocess",
)
PUBLIC_DOCUMENT_MUTABLE_SCREENING_STATES = frozenset({
    "pending_review", "scan_error", "incomplete", "rejected", "deleting",
})


def public_document_approval_pending(document):
    promotion_status = document.get("generated_artifact_promotion_status")
    return promotion_status == "pending_approval" or (
        promotion_status is None and str(document.get("status") or "").strip().lower() == "pending approval"
    )


def public_document_management_operations(workspace, role, settings, *, download_enabled):
    if role not in PUBLIC_DOCUMENT_MANAGER_ROLES or not settings.get("enable_public_workspaces", False):
        return []
    status = workspace.get("status", "active")
    if status not in {"active", "locked", "upload_disabled"}:
        return []
    operations = set()
    if status == "active":
        operations.update({"upload", "edit_metadata", "tag_documents", "manage_tags"})
        if settings.get("enable_extract_meta_data", False):
            operations.add("extract_metadata")
    if status in {"active", "upload_disabled"}:
        operations.update({"delete", "reprocess"})
    if download_enabled:
        operations.add("download")
    return [operation for operation in PUBLIC_DOCUMENT_OPERATIONS if operation in operations]


def public_document_actions(
    document, workspace, role, settings, *, available, source_available,
    reprocess_supported, extraction_supported, cleanup_allowed, download_enabled,
    current_revision,
):
    """Intersect workspace policy with freshly established resource eligibility."""
    operations = public_document_management_operations(workspace, role, settings, download_enabled=download_enabled)
    if document.get("public_workspace_id") != workspace["id"]:
        return []
    if public_document_approval_pending(document):
        return []

    allowed = set()
    if available and source_available:
        allowed.add("download")
    if cleanup_allowed:
        allowed.add("delete")
    if available and current_revision:
        marker = document.get(SCREENING_FIELD) or {}
        can_rescan = SCREENING_FIELD not in document or settings.get("enable_content_screening") is True
        if can_rescan:
            allowed.update({"edit_metadata", "tag_documents"})
            if extraction_supported:
                allowed.add("extract_metadata")
            if source_available and reprocess_supported and not marker.get("sanitized"):
                allowed.add("reprocess")
    return [operation for operation in operations if operation in allowed]
