# permissions.py
"""Object-level content review permissions, independent of application startup.

Application administrators may operate cross-workspace jobs, but that role is
deliberately not an evidence permission. Application helpers are imported at the
operation boundary to avoid initializing Flask/Azure when loading the contracts.
"""

from datetime import datetime

from content_screening.contracts import (
    SCREENING_FIELD,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    normalize_identifier,
    subject_from_document,
)


REVIEW_ROLES = ("Owner", "Admin", "DocumentManager")


class ScreeningPermissionError(ScreeningError, PermissionError):
    code = "screening_forbidden"
    status_code = 403
    public_message = "You do not have permission to access this content screening resource."


class ScreeningNotFoundError(ScreeningError, LookupError):
    code = "screening_not_found"
    status_code = 404
    public_message = "The content screening resource was not found."


def assert_scope_access(actor_id, scope_type, scope_id, *, review=True):
    """Re-read the exact workspace relationship; never consult active-scope IDs."""
    actor_id = normalize_identifier(actor_id, "actor_id")
    scope_id = normalize_identifier(scope_id, "scope_id")
    if scope_type == "personal":
        if actor_id != scope_id:
            raise ScreeningPermissionError()
        return "Owner"
    if scope_type == "group":
        from functions_group import assert_group_role

        try:
            return assert_group_role(
                actor_id, scope_id,
                allowed_roles=REVIEW_ROLES if review else (*REVIEW_ROLES, "User"),
            )
        except (LookupError, PermissionError) as error:
            raise ScreeningPermissionError() from error
    if scope_type == "public":
        from functions_public_workspaces import (
            find_public_workspace_by_id,
            get_user_role_in_public_workspace,
        )

        workspace = find_public_workspace_by_id(scope_id)
        if not workspace:
            raise ScreeningPermissionError()
        role = get_user_role_in_public_workspace(workspace, actor_id)
        if not role or (review and role not in REVIEW_ROLES):
            raise ScreeningPermissionError()
        return role
    raise ScreeningValidationError()


def assert_subject_access(subject, actor_id, *, repository, review=True):
    """Authorize before reading dependent evidence, then prove stored identity."""
    if not isinstance(subject, Subject):
        subject = Subject.from_dict(subject)
    assert_scope_access(actor_id, subject.scope_type, subject.scope_id, review=review)
    document = repository.read_document(subject)
    if not document or subject_from_document(document) != subject:
        raise ScreeningPermissionError()
    return document


def assert_review_metadata_access(scan, actor_id, *, repository):
    """Allow only recorded deletion metadata after the exact source record is gone."""
    subject = Subject.from_dict(scan.get("subject"))
    try:
        return assert_subject_access(subject, actor_id, repository=repository)
    except ScreeningConflictError as error:
        if error.code != "screening_source_missing" or scan.get("state") not in {"deleting", "deleted"}:
            raise
        if not isinstance(scan.get("deleted_by"), str):
            raise
        try:
            normalize_identifier(scan.get("deleted_by"), "deleted_by")
            started_at = datetime.fromisoformat(scan.get("deletion_started_at"))
        except (ScreeningValidationError, TypeError, ValueError):
            raise error from None
        if started_at.tzinfo is None:
            raise error
        assert_scope_access(actor_id, subject.scope_type, subject.scope_id)
        return None


def can_review_approval(approval, actor_id, *, repository=None):
    """Validate a generic approval's binding before any legacy admin fallback."""
    try:
        metadata = approval.get("metadata")
        if not isinstance(metadata, dict):
            return False
        subject = Subject.from_dict(metadata.get("subject"))
        if approval.get("group_id") != subject.scope_key:
            return False
        assert_scope_access(actor_id, subject.scope_type, subject.scope_id)
        if repository is None:
            from content_screening.repository import get_repository

            repository = get_repository()
        scan = repository.get_scan(normalize_identifier(metadata.get("scan_id"), "scan_id"))
        if (
            not scan or scan.get("kind") != "scan"
            or scan.get("subject") != subject.to_dict()
            or scan.get("approval_id") != approval.get("id")
        ):
            return False
        document = assert_review_metadata_access(scan, actor_id, repository=repository)
        if (
            document is not None and approval.get("status") == "pending"
            and (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan["id"]
        ):
            return False
        return True
    except Exception:
        # Permissions and missing dependencies fail closed without logging content.
        return False


def reviewer_ids(subject):
    """Return current scoped reviewers for minimal, individually routed notices."""
    if subject.scope_type == "personal":
        return [subject.scope_id]
    if subject.scope_type == "group":
        from functions_group import find_group_by_id

        workspace = find_group_by_id(subject.scope_id) or {}
        owner = workspace.get("owner") or {}
        candidates = [owner.get("id")] if isinstance(owner, dict) else []
    else:
        from functions_public_workspaces import find_public_workspace_by_id

        workspace = find_public_workspace_by_id(subject.scope_id) or {}
        owner = workspace.get("owner") or {}
        candidates = [owner.get("userId")] if isinstance(owner, dict) else []
    for field in ("admins", "documentManagers"):
        for member in workspace.get(field) or []:
            candidates.append(member.get("userId") if isinstance(member, dict) else member)
    eligible = []
    for actor_id in sorted({value for value in candidates if isinstance(value, str) and value}):
        try:
            assert_scope_access(actor_id, subject.scope_type, subject.scope_id)
            eligible.append(actor_id)
        except (ScreeningError, LookupError, PermissionError):
            continue
    return eligible
