#!/usr/bin/env python3
"""
Functional test for V2 UI API payload shape agreement.

Version: 0.261.004
Implemented in: 0.261.004

This test ensures the V2 TypeScript client agrees with the shapes the Flask API actually
returns. Two live-deployment failures came from assumed shapes that local fixtures happened
to mirror: workspace tags are objects rather than strings (which crashed React), and the
personal mark-read endpoint 404s for collaboration conversations.

The checks read both sides -- the Python route/helper source and the TypeScript client --
and assert they still agree, so a future change to either surfaces here rather than in a
browser console.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_workspace_tags_are_treated_as_objects():
    """Workspace tags are objects, and the V2 client must not render them directly."""
    print("Testing workspace tag shape agreement...")

    documents_source = _read(APP_DIR / "functions_documents.py")
    assert "Returns: [{'name': 'tag1', 'count': 5, 'color': '#3b82f6'}, ...]" in documents_source, (
        "build_workspace_tags_from_counts no longer documents the object tag shape; "
        "if the contract changed, update the V2 client to match"
    )

    workspace_page = _read(V2_SRC / "pages" / "WorkspacePage.tsx")

    assert "function tagName(" in workspace_page, (
        "WorkspacePage must funnel tags through tagName() so an object tag is never "
        "rendered directly (this caused React error #31)"
    )
    assert "'name' in tag" in workspace_page, (
        "tagName() must handle the object tag shape returned by /api/documents/tags"
    )

    # The crash was rendering the raw tag as a JSX child. Guard against its return.
    assert re.search(r"\{tag\}", workspace_page) is None, (
        "WorkspacePage renders a raw tag value as a JSX child; render tagName(tag) instead"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "tags?: WorkspaceTag[]" in endpoints, (
        "fetchPersonalDocumentTags must be typed as returning WorkspaceTag objects"
    )

    print("Workspace tag shape test passed!")
    return True


def test_mark_read_is_conditional_and_routed_by_conversation_kind():
    """mark-read is only called when unread, and collaboration uses its own endpoint."""
    print("Testing mark-read routing...")

    conversations_source = _read(APP_DIR / "route_backend_conversations.py")
    # The personal endpoint reads from the personal container and 404s otherwise, which is
    # why a collaboration conversation must not be sent here.
    assert "def mark_conversation_read_api(conversation_id):" in conversations_source
    assert "except CosmosResourceNotFoundError:" in conversations_source, (
        "The personal mark-read endpoint no longer 404s on a missing conversation; "
        "re-check whether the V2 routing split is still required"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "/api/collaboration/conversations/" in endpoints, (
        "The V2 client must route collaboration conversations to the collaboration "
        "mark-read endpoint"
    )
    assert "isCollaborative" in endpoints, (
        "markConversationRead must take the conversation kind into account"
    )

    chat_store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert "conversation?.has_unread_assistant_response" in chat_store, (
        "mark-read must only be called when the conversation is actually unread"
    )
    assert "conversation.conversation_kind === 'collaborative'" in chat_store, (
        "mark-read must be routed using the conversation kind"
    )

    print("mark-read routing test passed!")
    return True


def test_conversation_field_names_match_the_server():
    """The V2 rail reads the field names the conversation feed actually emits."""
    print("Testing conversation field name agreement...")

    feed_source = _read(APP_DIR / "functions_conversation_feed.py")
    for server_field in ("is_pinned", "has_unread_assistant_response"):
        assert server_field in feed_source, (
            f"The conversation feed no longer references {server_field}; "
            "the V2 client reads this field name"
        )

    rail = _read(V2_SRC / "components" / "chat" / "ConversationRail.tsx")
    assert "conversation.is_pinned" in rail, "The rail must read is_pinned"
    assert "conversation.has_unread_assistant_response" in rail, (
        "The rail must read has_unread_assistant_response"
    )

    # The original mistake: shorter, plausible-looking names that never exist.
    for wrong_field in ("conversation.pinned", "conversation.unread", "conversation.hidden"):
        assert wrong_field not in rail, (
            f"The rail reads {wrong_field}, which the server never returns"
        )

    print("Conversation field name test passed!")
    return True


def test_pin_and_hide_are_treated_as_server_side_toggles():
    """/pin and /hide toggle server-side and ignore the request body."""
    print("Testing pin/hide toggle semantics...")

    conversations_source = _read(APP_DIR / "route_backend_conversations.py")
    assert "current_pinned = conversation_item.get('is_pinned', False)" in conversations_source
    assert "conversation_item['is_pinned'] = not current_pinned" in conversations_source, (
        "The pin endpoint is no longer a toggle; the V2 client assumes it is"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "toggleConversationPinned" in endpoints and "toggleConversationHidden" in endpoints, (
        "Pin and hide must be modelled as toggles in the V2 client"
    )
    # Sending a desired state is meaningless against a toggle and was the original bug.
    assert "{ pinned }" not in endpoints and "{ hidden }" not in endpoints, (
        "The V2 client sends a desired pin/hide state, but the endpoints are toggles"
    )

    print("Pin/hide toggle test passed!")
    return True


def test_render_failures_are_contained_by_an_error_boundary():
    """A render error is contained to the content pane rather than blanking the app."""
    print("Testing error boundary...")

    boundary_file = V2_SRC / "components" / "ui" / "ErrorBoundary.tsx"
    assert boundary_file.is_file(), "The V2 error boundary component is missing"

    boundary = _read(boundary_file)
    assert "getDerivedStateFromError" in boundary, (
        "The error boundary must implement getDerivedStateFromError"
    )

    app_source = _read(V2_SRC / "App.tsx")
    assert "<ErrorBoundary" in app_source, (
        "Routed content must be wrapped in the error boundary so one failed view does not "
        "unmount the whole interface"
    )
    assert "resetKey={location.pathname}" in app_source, (
        "The boundary must reset on navigation so a failed view can be left"
    )

    print("Error boundary test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that carried these fixes."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.004")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_workspace_tags_are_treated_as_objects,
        test_mark_read_is_conditional_and_routed_by_conversation_kind,
        test_conversation_field_names_match_the_server,
        test_pin_and_hide_are_treated_as_server_side_toggles,
        test_render_failures_are_contained_by_an_error_boundary,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
