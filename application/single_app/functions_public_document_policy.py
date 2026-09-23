# functions_public_document_policy.py
"""Public-workspace management capability projections; write routes reauthorize.

Public workspaces have no cross-workspace share relationship (that arrives with
M3D), so these projections describe only owner-scoped management and
generated-artifact eligibility.
"""

from content_screening.contracts import SCREENING_FIELD
from functions_artifact_publication_readiness import PUBLICATION_BINDING


PUBLIC_DOCUMENT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
PUBLIC_DOCUMENT_OPERATIONS = (
    "upload", "edit_metadata", "tag_documents", "manage_tags",
    "delete", "download", "extract_metadata", "reprocess",
)
PUBLIC_DOCUMENT_MUTABLE_SCREENING_STATES = frozenset({
    "pending_review", "scan_error", "incomplete", "rejected", "deleting",
})
# Public workspaces have no cross-workspace share relationship yet (M3D), so the
# only collaboration operations are the owner-side generated-artifact decisions.
PUBLIC_DOCUMENT_COLLABORATION_OPERATIONS = (
    "inspect", "approve_artifact", "reject_artifact", "cancel_artifact",
)
PUBLIC_DOCUMENT_COLLABORATION_STATUSES = frozenset({"active", "upload_disabled"})


def public_document_collaboration_operations(workspace, role, settings):
    if (
        role not in (*PUBLIC_DOCUMENT_MANAGER_ROLES, "User")
        or not settings.get("enable_public_workspaces", False)
        or workspace.get("status", "active") not in {"active", "locked", "upload_disabled"}
    ):
        return []
    operations = {"inspect"}
    if workspace.get("status", "active") in PUBLIC_DOCUMENT_COLLABORATION_STATUSES:
        operations.add("cancel_artifact")
        if role in PUBLIC_DOCUMENT_MANAGER_ROLES:
            operations.add("reject_artifact")
            if workspace.get("status", "active") == "active":
                operations.add("approve_artifact")
    return [operation for operation in PUBLIC_DOCUMENT_COLLABORATION_OPERATIONS if operation in operations]


def public_document_approval_pending(document):
    promotion_status = document.get("generated_artifact_promotion_status")
    return promotion_status == "pending_approval" or (
        promotion_status is None and str(document.get("status") or "").strip().lower() == "pending approval"
    )


def public_document_has_publication(document):
    """Single source of truth for whether a public document carries a
    generated-artifact publication.

    Defined in this lightweight, adapter-free policy layer so both the
    publication adapter and the read/list projection share one rule. The list
    path uses it to decide whether to consult the artifact-publication adapter
    at all, so the adapter import and its per-document Cosmos read stay off the
    common list path. Keeping one definition prevents the silent drift where a
    mirror lacks a condition and hides pending approve/reject/cancel from a
    reviewer behind a plain read-only document.
    """
    return bool(
        public_document_approval_pending(document)
        or document.get("generated_artifact_promotion_status")
        or document.get("generated_artifact_publication_receipt_id")
        or document.get(PUBLICATION_BINDING)
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
