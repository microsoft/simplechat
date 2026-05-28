#!/usr/bin/env python3
# test_group_file_share_approval_notifications.py
"""
Functional test for group file share approval notifications.
Version: 0.241.111
Implemented in: 0.241.111

This test ensures group document shares are created as pending approvals,
review actions are restricted to group owners/admins/document managers,
personal and group share notifications are emitted, and receiving groups see
Remove/Approve behavior instead of owner-only delete/share controls.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
NOTIFICATIONS_FILE = ROOT / "application" / "single_app" / "functions_notifications.py"
DOCUMENTS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_documents.py"
GROUP_DOCUMENTS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_group_documents.py"
GROUP_WORKSPACE_TEMPLATE = ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"
FUNCTIONS_DOCUMENTS_FILE = ROOT / "application" / "single_app" / "functions_documents.py"


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding="utf-8")


def read_version() -> str:
    """Extract the application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('"')[1]
    raise AssertionError("VERSION assignment was not found in config.py")


def assert_contains(source: str, snippets: list[str], description: str) -> None:
    """Assert all snippets exist in a source file."""
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f"Missing {description} snippets: {missing}"


def test_version_header_matches_config() -> None:
    """Verify this regression test tracks the config.py version."""
    assert read_version() == "0.241.111", "Expected config.py VERSION to be 0.241.111."


def test_notification_types_and_personal_share_decisions() -> None:
    """Verify personal document sharing creates review and owner decision notifications."""
    notifications_source = read_text(NOTIFICATIONS_FILE)
    personal_route_source = read_text(DOCUMENTS_ROUTE_FILE)

    assert_contains(
        notifications_source,
        [
            "'personal_document_share_pending'",
            "'personal_document_share_approved'",
            "'personal_document_share_denied'",
            "'group_document_share_pending'",
            "'group_document_share_approved'",
            "'group_document_share_denied'",
        ],
        "document share notification registry",
    )
    assert_contains(
        personal_route_source,
        [
            "_create_personal_document_share_pending_notification(",
            "_create_personal_document_share_decision_notification(document_item, user_id, 'approved')",
            "_create_personal_document_share_decision_notification(doc, user_id, 'denied')",
            "_clear_personal_document_share_pending_notifications(document_id, user_id)",
        ],
        "personal share notification flow",
    )


def test_group_share_backend_requires_approval_and_manager_roles() -> None:
    """Verify group shares use pending status and manager-only approval/removal endpoints."""
    group_route_source = read_text(GROUP_DOCUMENTS_ROUTE_FILE)
    functions_documents_source = read_text(FUNCTIONS_DOCUMENTS_FILE)

    assert_contains(
        group_route_source,
        [
            'GROUP_DOCUMENT_SHARE_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")',
            "_set_group_share_status(",
            "'not_approved'",
            "_create_group_document_share_pending_notifications(",
            "_create_group_document_share_decision_notification(",
            "allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES",
            "Only the owning group can view document sharing",
            "Shared documents can be removed from this group, not deleted",
            "Share denied' if was_pending",
        ],
        "group share approval backend",
    )
    assert_contains(
        functions_documents_source,
        [
            "OR EXISTS(SELECT VALUE s FROM s IN c.shared_group_ids WHERE STARTSWITH(s, @group_id_prefix))",
            "OR ARRAY_CONTAINS(c.shared_group_ids, @group_id_approved)",
        ],
        "status-qualified group document lookup",
    )


def test_group_workspace_ui_shows_approval_and_remove_actions() -> None:
    """Verify receiving-group UI branches expose Approve/Remove instead of Share/Delete."""
    template_source = read_text(GROUP_WORKSPACE_TEMPLATE)

    assert_contains(
        template_source,
        [
            "function getGroupDocumentAccess(doc)",
            "access.requiresApproval",
            "approveSharedGroupDocument('${docId}')",
            "removeSharedGroupDocument('${docId}', event)",
            "id=\"groupSharedDocumentApprovalModal\"",
            "submitGroupSharedDocumentAction(documentId, 'approve', approveBtn)",
            "submitGroupSharedDocumentAction(documentId, 'deny', denyBtn)",
            "canManage && access.isOwnerGroup",
            "!access.isOwnerGroup && Boolean(access.sharedGroupEntry)",
        ],
        "group workspace shared document UI",
    )


def run_tests() -> bool:
    tests = [
        test_version_header_matches_config,
        test_notification_types_and_personal_share_decisions,
        test_group_share_backend_requires_approval_and_manager_roles,
        test_group_workspace_ui_shows_approval_and_remove_actions,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)