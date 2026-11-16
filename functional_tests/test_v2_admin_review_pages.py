#!/usr/bin/env python3
# test_v2_admin_review_pages.py
"""
Functional test for the React v2 administrator Review center.
Version: 0.261.298
Implemented in: 0.261.277
Review center replacement: 0.261.298

This test ensures the Review center replaced the separate V2 Feedback Review and Safety
Violations pages: its routes and the redirects from the old addresses are in place, the
account menu offers one Review center entry gated by the same role and feature rules as the
server's decorators, the rail persists through its own allowlisted user setting, the
workbenches, editors and unchecked chat queue stay wired to the existing review APIs, and
the backend routes keep their role and feature decorators.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
V2_SRC = ROOT / "application" / "v2_ui" / "src"
APP_DIR = ROOT / "application" / "single_app"
REVIEW = V2_SRC / "pages" / "review"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_review_center_is_routed_and_role_gated():
    app = read(V2_SRC / "App.tsx")
    sidebar = read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    access = read(V2_SRC / "lib" / "reviewAccess.ts")

    for path in ('"/admin/review"', '"/admin/review/:section"', '"/admin/review/:section/:view"',
                 '"/admin/review/:section/:view/:recordId"'):
        assert f"path={path}" in app, path
    # The old addresses redirect, keeping their query.
    assert "path=\"/admin/feedback-review\" element={<Navigate to={{ pathname: '/admin/review/feedback/queue', search: location.search }} replace />}" in app
    assert "path=\"/admin/safety-violations\" element={<Navigate to={{ pathname: '/admin/review/safety/violations', search: location.search }} replace />}" in app
    assert not (V2_SRC / "pages" / "AdminFeedbackReviewPage.tsx").exists()
    assert not (V2_SRC / "pages" / "AdminSafetyViolationsPage.tsx").exists()

    # One entry, gated by the shared mirror of the server's decorators.
    assert 'to="/admin/review"' in sidebar and "Review center" in sidebar
    assert "reviewSections(reviewAccessInput(bootstrap)).length > 0" in sidebar
    assert "/admin/feedback-review" not in sidebar and "/admin/safety-violations" not in sidebar
    assert "input.features.enable_user_feedback !== true" in access
    assert "input.features.enable_content_safety === true || input.features.enable_content_screening === true" in access
    assert "input.settings.require_member_of_feedback_admin === true" in access
    assert "input.roles.includes('FeedbackAdmin')" in access
    assert "input.settings.require_member_of_safety_violation_admin === true" in access
    assert "input.roles.includes('SafetyViolationAdmin')" in access


def test_review_rail_setting_is_allowlisted():
    settings = read(V2_SRC / "lib" / "userSettings.ts")
    users = read(APP_DIR / "route_backend_users.py")
    page = read(REVIEW / "ReviewCenterPage.tsx")
    assert settings.count("v2ReviewRailCollapsed") >= 2
    assert "'v2ReviewRailCollapsed'" in users
    assert "updateUserSettings({ v2ReviewRailCollapsed: !railCollapsed })" in page


def test_sections_register_their_pages():
    sections = read(REVIEW / "reviewCenterSections.tsx")
    for marker in ("id: 'feedback-dashboard'", "id: 'feedback-queue'", "id: 'safety-dashboard'",
                   "id: 'safety-violations'", "id: 'safety-unchecked'", "view: 'queue'", "view: 'violations'",
                   "view: 'unchecked'", "renderRecord: (recordId) => <FeedbackEditorPage",
                   "renderRecord: (recordId) => <SafetyEditorPage"):
        assert marker in sections, marker


def test_feedback_review_uses_admin_contract():
    api = read(V2_SRC / "lib" / "reviewCenterApi.ts")
    editor = read(REVIEW / "FeedbackEditorPage.tsx")
    workbench = read(REVIEW / "FeedbackWorkbench.tsx")
    backend = read(APP_DIR / "route_backend_feedback.py")

    for marker in (
        "`/feedback/review?${pagedQuery(feedbackFilterParams(filters), page, pageSize)}`",
        "`/feedback/review/ids${query ? `?${query}` : ''}`",
        "`/feedback/review/stats?${new URLSearchParams({ days })}`",
        "`/feedback/review/${encodeURIComponent(id)}`",
        "`/feedback/retest/${encodeURIComponent(id)}`",
        "runBulk('/feedback/review/bulk', operations, onProgress)",
    ):
        assert marker in api, f"the feedback client is missing {marker!r}"
    for marker in ("analysisNotes", "responseToUser", "actionTaken", "acknowledged", "notify_user: current.notifyUser",
                   "etag: record.etag", "Notify the user", "<FeedbackRetest"):
        assert marker in editor, f"the feedback editor is missing {marker!r}"
    for marker in ("/feedback/review/export?", "Export CSV", "Permanently delete", "op: 'archive', archived: true",
                   "changes: { acknowledged: true }"):
        assert marker in workbench, f"the feedback workbench is missing {marker!r}"
    assert "@feedback_admin_required" in backend
    assert '@enabled_required("enable_user_feedback")' in backend


def test_safety_review_preserves_admin_and_unchecked_chat_workflows():
    api = read(V2_SRC / "lib" / "reviewCenterApi.ts")
    editor = read(REVIEW / "SafetyEditorPage.tsx")
    workbench = read(REVIEW / "SafetyWorkbench.tsx")
    unchecked = read(REVIEW / "UncheckedChatContent.tsx")
    backend = read(APP_DIR / "route_backend_safety.py")
    auth = read(APP_DIR / "functions_authentication.py")

    for marker in (
        "`/api/safety/logs?${pagedQuery(safetyFilterParams(filters), page, pageSize)}`",
        "`/api/safety/logs/ids${query ? `?${query}` : ''}`",
        "`/api/safety/logs/stats?${new URLSearchParams({ days })}`",
        "`/api/safety/logs/${encodeURIComponent(id)}`",
        "runBulk('/api/safety/logs/bulk', operations, onProgress)",
        "`/api/safety/chat-checks?${params}`",
        "'/api/safety/chat-checks/recheck'",
        "source: item.source",
        "conversation_id: item.conversation_id",
        "message_id: item.message_id",
        "etag: item.etag",
    ):
        assert marker in api, f"the safety client is missing {marker!r}"
    for marker in ("payload.notification_message", "payload.notification_title", "payload.datetime_to_allow",
                   "payload.reissue = true", "etag: record.etag", "SUSPEND_PRESETS"):
        assert marker in editor, f"the safety editor is missing {marker!r}"
    assert "/api/safety/logs/export?" in workbench and "Permanently delete" in workbench
    for marker in ("Recheck this message?", "continuation", "Recheck selected", "recheckChatMessage(item)"):
        assert marker in unchecked, f"the unchecked chat queue is missing {marker!r}"
    # Rechecks run one after another, never at once.
    assert "for (let index = 0; index < targets.length; index += 1)" in unchecked
    assert "Promise.all" not in unchecked

    assert "@safety_violation_admin_required" in backend
    assert "@content_checks_report_enabled" in backend
    assert "SafetyViolationAdmin" in auth


def test_admin_settings_links_to_the_v2_unchecked_queue():
    admin = read(V2_SRC / "pages" / "AdminSettingsPage.tsx")
    assert '<Link to="/admin/review/safety/unchecked"' in admin
    assert "/admin/safety_violations#unchecked-chat-content" not in admin


if __name__ == "__main__":
    tests = [
        test_review_center_is_routed_and_role_gated,
        test_review_rail_setting_is_allowlisted,
        test_sections_register_their_pages,
        test_feedback_review_uses_admin_contract,
        test_safety_review_preserves_admin_and_unchecked_chat_workflows,
        test_admin_settings_links_to_the_v2_unchecked_queue,
    ]
    for test in tests:
        test()
    print("All Review center source checks passed.")
