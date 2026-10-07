#!/usr/bin/env python3
# test_v2_admin_review_pages.py
"""
Functional test for React v2 administrator feedback and safety review pages.
Version: 0.261.277
Implemented in: 0.261.277

This test ensures the v2 review pages are routed and linked with their role and
feature gates, and remain wired to the existing administrator review APIs.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
V2_SRC = ROOT / "application" / "v2_ui" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_review_pages_are_routed_and_role_gated():
    app = read(V2_SRC / "App.tsx")
    sidebar = read(V2_SRC / "components" / "layout" / "Sidebar.tsx")

    assert 'path="/admin/feedback-review"' in app
    assert 'path="/admin/safety-violations"' in app
    assert "to=\"/admin/feedback-review\"" in sidebar
    assert "to=\"/admin/safety-violations\"" in sidebar
    assert "features?.enable_user_feedback" in sidebar
    assert "features?.enable_content_safety || features?.enable_content_screening" in sidebar
    assert "settings?.require_member_of_feedback_admin === true" in sidebar
    assert "roles.includes('FeedbackAdmin')" in sidebar
    assert "settings?.require_member_of_safety_violation_admin === true" in sidebar
    assert "roles.includes('SafetyViolationAdmin')" in sidebar


def test_feedback_review_uses_admin_contract_and_confirmation():
    page = read(V2_SRC / "pages" / "AdminFeedbackReviewPage.tsx")
    backend = read(ROOT / "application" / "single_app" / "route_backend_feedback.py")

    for marker in (
        "/feedback/review?",
        "/feedback/review/stats?",
        "/feedback/review/${encodeURIComponent(item.id)}",
        "/feedback/retest/${encodeURIComponent(item.id)}",
        "feedbackType",
        "analysisNotes",
        "responseToUser",
        "actionTaken",
        "acknowledged",
        "archive",
        "Permanently delete feedback?",
        "Permanently delete",
        "Export CSV",
        "List view",
        "Card view",
    ):
        assert marker in page, f"Feedback review page is missing {marker!r}"

    assert '@feedback_admin_required' in backend
    assert '@enabled_required("enable_user_feedback")' in backend


def test_safety_review_preserves_admin_and_unchecked_chat_workflows():
    page = read(V2_SRC / "pages" / "AdminSafetyViolationsPage.tsx")
    backend = read(ROOT / "application" / "single_app" / "route_backend_safety.py")
    auth = read(ROOT / "application" / "single_app" / "functions_authentication.py")

    for marker in (
        "/api/safety/logs?",
        "/api/safety/logs/stats?",
        "/api/safety/logs/export?",
        "/api/safety/logs/${encodeURIComponent(selected.id)}",
        "/api/safety/chat-checks?",
        "/api/safety/chat-checks/recheck",
        "notification_message",
        "datetime_to_allow",
        "action_request_status",
        "Permanently delete safety violation?",
        "Recheck this message?",
        "continuation",
        "source: item.source",
        "conversation_id: item.conversation_id",
        "message_id: item.message_id",
        "etag: item.etag",
    ):
        assert marker in page, f"Safety review page is missing {marker!r}"

    assert "@safety_violation_admin_required" in backend
    assert "@content_checks_report_enabled" in backend
    assert "SafetyViolationAdmin" in auth


if __name__ == "__main__":
    tests = [
        test_review_pages_are_routed_and_role_gated,
        test_feedback_review_uses_admin_contract_and_confirmation,
        test_safety_review_preserves_admin_and_unchecked_chat_workflows,
    ]
    for test in tests:
        test()
