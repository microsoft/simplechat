# functions_group_document_policy.py
"""Management capability projections; operation routes must reauthorize writes."""

from content_screening.contracts import SCREENING_FIELD


GROUP_DOCUMENT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
GROUP_DOCUMENT_OPERATIONS = (
    "upload", "edit_metadata", "tag_documents", "manage_tags",
    "delete", "download", "extract_metadata", "reprocess",
)
GROUP_DOCUMENT_MUTABLE_SCREENING_STATES = frozenset({
    "pending_review", "scan_error", "incomplete", "rejected", "deleting",
})


def group_document_approval_pending(document):
    promotion_status = document.get("generated_artifact_promotion_status")
    return promotion_status == "pending_approval" or (
        promotion_status is None and str(document.get("status") or "").strip().lower() == "pending approval"
    )


def group_document_management_operations(group, role, settings, *, download_enabled):
    if role not in GROUP_DOCUMENT_MANAGER_ROLES or not settings.get("enable_group_workspaces", False):
        return []
    status = group.get("status", "active")
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
    return [operation for operation in GROUP_DOCUMENT_OPERATIONS if operation in operations]


def group_document_actions(
    document, group, role, settings, *, available, source_available,
    reprocess_supported, extraction_supported, cleanup_allowed, source_download_allowed, download_enabled,
    current_revision,
):
    """Intersect workspace policy with freshly established resource eligibility."""
    operations = group_document_management_operations(group, role, settings, download_enabled=download_enabled)
    owned = document.get("group_id") == group["id"]
    shares = document.get("shared_group_ids")
    approved_share = isinstance(shares, list) and any(
        entry in (group["id"], f"{group['id']},approved") for entry in shares
    )
    if not owned and not approved_share:
        return []
    if group_document_approval_pending(document):
        return []

    allowed = set()
    if available and source_available and source_download_allowed:
        allowed.add("download")
    if owned and cleanup_allowed:
        allowed.add("delete")
    if owned and available and current_revision:
        marker = document.get(SCREENING_FIELD) or {}
        can_rescan = SCREENING_FIELD not in document or settings.get("enable_content_screening") is True
        if can_rescan:
            allowed.update({"edit_metadata", "tag_documents"})
            if extraction_supported:
                allowed.add("extract_metadata")
            if source_available and reprocess_supported and not marker.get("sanitized"):
                allowed.add("reprocess")
    return [operation for operation in operations if operation in allowed]
