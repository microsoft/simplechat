#!/usr/bin/env python3
"""
Functional test for the V2 chat conversation drawer.

Version: 0.261.005
Implemented in: 0.261.005

This test ensures the V2 right-hand drawer agrees with the conversation metadata contract
it renders from. The drawer's Documents mode reads used_documents, legacy_used_documents
and linked_workspace_documents, and its Contents mode is gated on the same admin plus
user preference check the server applies.

Shapes are asserted against the Python source rather than a live server, because
config.py builds Azure clients at import time and cannot be imported in a test
environment.
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


def test_metadata_response_fields_match_the_client_type():
    """Every metadata field the drawer relies on is still returned by the route."""
    print("Testing conversation metadata contract...")

    route_source = _read(APP_DIR / "route_backend_conversations.py")
    types_source = _read(V2_SRC / "lib" / "types.ts")

    # These are the fields the drawer and details view read. The identifier is
    # conversation_id, not id -- a mismatch here silently empties the drawer.
    required_fields = [
        "conversation_id",
        "title",
        "last_updated",
        "used_documents",
        "legacy_used_documents",
        "linked_workspace_documents",
        "is_pinned",
        "is_hidden",
        "scope_locked",
        "locked_contexts",
        "chat_type",
        "summary",
    ]

    for field in required_fields:
        assert f'"{field}"' in route_source, (
            f"The metadata route no longer returns {field!r}, which the V2 drawer reads"
        )
        assert field in types_source, (
            f"ConversationMetadata is missing {field!r}"
        )

    # The route returns conversation_id; asserting the client never expects a bare `id`
    # guards against reintroducing the mismatch that broke earlier work.
    assert "conversation_id: string;" in types_source, (
        "ConversationMetadata must key on conversation_id, matching the route"
    )

    print("Metadata contract test passed!")
    return True


def test_used_document_shape_matches_the_citation_builder():
    """The drawer reads the fields build_used_documents actually produces."""
    print("Testing used-document shape...")

    tracking_source = _read(APP_DIR / "functions_citation_tracking.py")
    types_source = _read(V2_SRC / "lib" / "types.ts")

    for field in ("document_id", "citation_ids", "page_numbers", "sheet_names", "scope"):
        assert f'"{field}"' in tracking_source, (
            f"build_used_documents no longer produces {field!r}"
        )
        assert field in types_source, f"UsedDocument is missing {field!r}"

    drawer = _read(V2_SRC / "components" / "chat" / "ConversationDrawer.tsx")

    # The Cited badge distinguishes a document that was merely available from one that was
    # actually referenced, which is the whole point of the panel.
    assert "citation_ids ?? []" in drawer, (
        "The drawer must derive its Cited badge from citation_ids"
    )
    assert "page_numbers" in drawer and "sheet_names" in drawer, (
        "The drawer must show where in the document the citations landed"
    )

    print("Used-document shape test passed!")
    return True


def test_contents_mode_is_gated_like_the_server():
    """Contents mode honours the same gate the server computes."""
    print("Testing contents drawer gating...")

    contents_source = _read(APP_DIR / "functions_conversation_contents.py")
    assert "enable_conversation_contents_drawer" in contents_source
    assert "conversationContentsDrawerEnabled" in contents_source, (
        "The server gate combines an admin setting with a user preference"
    )

    bootstrap_source = _read(APP_DIR / "route_backend_v2.py")
    assert "is_conversation_contents_drawer_enabled(" in bootstrap_source, (
        "The bootstrap must compute the drawer gate per user rather than forwarding the "
        "raw admin setting, since the user preference also applies"
    )

    drawer = _read(V2_SRC / "components" / "chat" / "ConversationDrawer.tsx")
    assert "enable_conversation_contents_drawer" in drawer, (
        "The drawer must hide Contents mode when the computed gate is off"
    )

    print("Contents gating test passed!")
    return True


def test_drawer_merges_all_three_document_sources():
    """Documents mode reads all three document lists and de-duplicates them."""
    print("Testing document source merge...")

    drawer = _read(V2_SRC / "components" / "chat" / "ConversationDrawer.tsx")

    for source in ("used_documents", "legacy_used_documents", "linked_workspace_documents"):
        assert source in drawer, (
            f"Documents mode must include {source}; omitting it hides real documents"
        )

    # A document can appear in more than one list, so a de-duplicating structure is
    # required rather than a plain concatenation.
    assert re.search(r"new Map<string, UsedDocument>", drawer), (
        "Documents mode must de-duplicate by document_id across the three sources"
    )

    print("Document source merge test passed!")
    return True


def test_message_anchors_exist_for_contents_navigation():
    """Contents jump-to depends on stable per-message DOM anchors."""
    print("Testing message anchors...")

    message_list = _read(V2_SRC / "components" / "chat" / "MessageList.tsx")
    assert "id={`message-${message.id}`}" in message_list, (
        "Each message needs a stable DOM id for the Contents jump-to list to target"
    )

    drawer = _read(V2_SRC / "components" / "chat" / "ConversationDrawer.tsx")
    assert "message-${messageId}" in drawer, (
        "The Contents list must resolve the same anchor id the message list renders"
    )

    print("Message anchor test passed!")
    return True


def test_details_render_only_real_metadata_fields():
    """The details view shows only fields the metadata route actually returns."""
    print("Testing details field fidelity...")

    route_source = _read(APP_DIR / "route_backend_conversations.py")
    # The details view is the component plus the module that reads the payload for it, so
    # both are searched: a field surfaced through a helper is still surfaced.
    details = _read(V2_SRC / "components" / "chat" / "ConversationDetails.tsx") + _read(
        V2_SRC / "lib" / "conversationDetails.ts"
    )

    for field in (
        "conversation_id",
        "last_updated",
        "chat_type",
        "workflow_id",
        "is_pinned",
        "is_hidden",
        "scope_locked",
        "locked_contexts",
        "classification",
        "summary",
    ):
        assert field in details, f"The details view should surface {field!r}"
        assert f'"{field}"' in route_source, (
            f"The metadata route no longer returns {field!r}, which the details view reads"
        )

    # An exploration pass produced a plausible sample response containing these; none of
    # them exist, and showing them would mean rendering permanently blank rows. Matching
    # on property access rather than the bare word so documentation may still mention them.
    for invented in ("participants", "created_at", "can_delete_conversation"):
        assert f"metadata.{invented}" not in details, (
            f"The details view reads metadata.{invented}, which the route does not return"
        )
        assert f"metadata?.{invented}" not in details, (
            f"The details view reads metadata?.{invented}, which the route does not return"
        )

    print("Details field fidelity test passed!")
    return True


def test_dialog_surfaces_are_opaque_enough_to_read():
    """Overlay surfaces use the near-opaque modal token, not the chrome glass token.

    The chrome glass surface is translucent by design, which leaves page text legible
    straight through anything layered over content. Dialogs and popovers therefore use a
    dedicated near-opaque surface.
    """
    print("Testing overlay surface opacity...")

    theme = _read(V2_SRC / "styles" / "theme.css")
    assert "--surface-modal:" in theme, "A dedicated modal surface token is required"
    assert ".glass-modal {" in theme, "A .glass-modal overlay class is required"

    # Reduced-transparency users must get the solid treatment for overlays too.
    reduced_block = theme[theme.index("prefers-reduced-transparency") :]
    assert ".glass-modal" in reduced_block[:400], (
        "The reduced-transparency rule must cover .glass-modal"
    )

    overlay_files = [
        V2_SRC / "components" / "chat" / "ConversationDetails.tsx",
        V2_SRC / "components" / "chat" / "ConversationRail.tsx",
        V2_SRC / "components" / "ui" / "Dropdown.tsx",
        V2_SRC / "components" / "layout" / "Sidebar.tsx",
    ]
    for path in overlay_files:
        source = _read(path)
        assert "glass-raised" not in source, (
            f"{path.name} uses the translucent glass-raised surface for an overlay; "
            "use glass-modal so content behind it is not legible through the panel"
        )

    print("Overlay surface opacity test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added the drawer."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.006")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_metadata_response_fields_match_the_client_type,
        test_used_document_shape_matches_the_citation_builder,
        test_contents_mode_is_gated_like_the_server,
        test_drawer_merges_all_three_document_sources,
        test_message_anchors_exist_for_contents_navigation,
        test_details_render_only_real_metadata_fields,
        test_dialog_surfaces_are_opaque_enough_to_read,
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
