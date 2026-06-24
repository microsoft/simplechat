#!/usr/bin/env python3
# test_chat_layered_message_masking.py
"""
Functional test for layered chat message masking.
Version: 0.250.029
Implemented in: 0.241.098

This test ensures message masking supports additive text ranges, independent
full-message masks, non-destructive full-message unmasking, and shared
conversation endpoint wiring. It also validates rendered Markdown selection
masking added in 0.250.029.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
CONFIG_FILE = APP_DIR / "config.py"
CHAT_MESSAGES_JS = APP_DIR / "static" / "js" / "chat" / "chat-messages.js"
CHAT_COLLABORATION_JS = APP_DIR / "static" / "js" / "chat" / "chat-collaboration.js"
CHAT_ROUTE = APP_DIR / "route_backend_chats.py"
COLLABORATION_ROUTE = APP_DIR / "route_backend_collaboration.py"
FEATURE_DOC = ROOT_DIR / "docs" / "explanation" / "features" / "MESSAGE_LAYERED_MASKING.md"

sys.path.insert(0, str(APP_DIR))

from functions_message_masking import (  # noqa: E402
    apply_message_mask_action,
    remove_masked_content,
)


def read_text(path: Path) -> str:
    """Read a UTF-8 repository text file."""
    return path.read_text(encoding="utf-8")


def read_version() -> str:
    """Extract the application version from config.py without importing app config."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('"')[1]
    raise AssertionError("VERSION assignment was not found in config.py")


def assert_contains(source: str, snippets: list[str], description: str) -> None:
    """Assert every required snippet exists in source."""
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f"Missing {description} snippets: {missing}"


def assert_not_contains(source: str, snippets: list[str], description: str) -> None:
    """Assert no forbidden snippets exist in source."""
    present = [snippet for snippet in snippets if snippet in source]
    assert not present, f"Unexpected {description} snippets: {present}"


def test_layered_masking_state_machine() -> None:
    """Validate independent range masks and full-message mask state transitions."""
    message_doc = {
        "id": "message-1",
        "content": "alpha beta gamma delta",
        "metadata": {},
    }

    apply_message_mask_action(
        message_doc,
        "mask_selection",
        {"start": 6, "end": 10, "text": "beta"},
        "user-1",
        "User One",
        timestamp="2025-01-01T00:00:00+00:00",
    )
    apply_message_mask_action(
        message_doc,
        "mask_selection",
        {"start": 11, "end": 16, "text": "gamma"},
        "user-1",
        "User One",
        timestamp="2025-01-01T00:01:00+00:00",
    )

    masked_ranges = message_doc["metadata"]["masked_ranges"]
    assert [(item["start"], item["end"], item["text"]) for item in masked_ranges] == [
        (6, 10, "beta"),
        (11, 16, "gamma"),
    ]
    masked_content_removed = remove_masked_content(message_doc["content"], masked_ranges)
    assert "beta" not in masked_content_removed
    assert "gamma" not in masked_content_removed
    assert "alpha" in masked_content_removed
    assert "delta" in masked_content_removed

    apply_message_mask_action(
        message_doc,
        "mask_all",
        {},
        "user-1",
        "User One",
        timestamp="2025-01-01T00:02:00+00:00",
    )
    assert message_doc["metadata"]["masked"] is True
    assert len(message_doc["metadata"]["masked_ranges"]) == 2

    apply_message_mask_action(
        message_doc,
        "unmask_message",
        {},
        "user-1",
        "User One",
        timestamp="2025-01-01T00:03:00+00:00",
    )
    assert message_doc["metadata"]["masked"] is False
    assert message_doc["metadata"]["masked_ranges"] == masked_ranges

    apply_message_mask_action(
        message_doc,
        "clear_all_masks",
        {},
        "user-1",
        "User One",
        timestamp="2025-01-01T00:04:00+00:00",
    )
    assert message_doc["metadata"]["masked"] is False
    assert message_doc["metadata"]["masked_ranges"] == []


def test_selection_resolution_uses_canonical_content() -> None:
    """Validate selection fallback only applies when selected text is unique."""
    message_doc = {
        "id": "message-2",
        "content": "prefix unique suffix",
        "metadata": {},
    }
    apply_message_mask_action(
        message_doc,
        "mask_selection",
        {"start": 0, "end": 6, "text": "unique"},
        "user-1",
        "User One",
        timestamp="2025-01-01T00:00:00+00:00",
    )
    assert message_doc["metadata"]["masked_ranges"][0]["start"] == 7
    assert message_doc["metadata"]["masked_ranges"][0]["end"] == 13

    duplicate_doc = {
        "id": "message-3",
        "content": "repeat and repeat",
        "metadata": {},
    }
    try:
        apply_message_mask_action(
            duplicate_doc,
            "mask_selection",
            {"start": 7, "end": 13, "text": "repeat"},
            "user-1",
            "User One",
            timestamp="2025-01-01T00:00:00+00:00",
        )
    except ValueError as error:
        assert "Selection no longer matches" in str(error)
    else:
        raise AssertionError("Ambiguous fallback selection should be rejected")


def test_rendered_markdown_selection_maps_to_canonical_offsets() -> None:
    """Validate rendered selections from formatted Markdown still mask stored content."""
    message_doc = {
        "id": "message-4",
        "content": (
            "You currently have **336 total Office 365 licenses** across three "
            "procurement pools, with **45 in use** and **291 available**."
        ),
        "metadata": {},
    }
    rendered_selection = (
        "You currently have 336 total Office 365 licenses across three "
        "procurement pools"
    )
    apply_message_mask_action(
        message_doc,
        "mask_selection",
        {
            "start": 0,
            "end": len(rendered_selection),
            "text": rendered_selection,
            "display_start": 0,
            "display_end": len(rendered_selection),
            "display_text": rendered_selection,
        },
        "user-1",
        "User One",
        timestamp="2026-06-24T00:00:00+00:00",
    )

    masked_range = message_doc["metadata"]["masked_ranges"][0]
    assert masked_range["start"] == 0
    assert masked_range["text"].startswith("You currently have **336 total Office 365 licenses**")
    assert masked_range["display_start"] == 0
    assert masked_range["display_end"] == len(rendered_selection)

    masked_content_removed = remove_masked_content(message_doc["content"], [masked_range])
    assert "336 total Office 365 licenses" not in masked_content_removed
    assert "45 in use" in masked_content_removed


def test_rendered_markdown_table_selection_maps_to_canonical_offsets() -> None:
    """Validate selected rendered table cell text can be masked from Markdown tables."""
    message_doc = {
        "id": "message-5",
        "content": (
            "| Product | Total Licenses | In Use | Available |\n"
            "| --- | ---: | ---: | ---: |\n"
            "| Office 365 | **336** | 45 | 291 |"
        ),
        "metadata": {},
    }
    apply_message_mask_action(
        message_doc,
        "mask_selection",
        {
            "start": 0,
            "end": len("Office 365"),
            "text": "Office 365",
            "display_start": 0,
            "display_end": len("Office 365"),
            "display_text": "Office 365",
        },
        "user-1",
        "User One",
        timestamp="2026-06-24T00:00:00+00:00",
    )

    masked_range = message_doc["metadata"]["masked_ranges"][0]
    assert masked_range["text"] == "Office 365"
    assert message_doc["content"][masked_range["start"]:masked_range["end"]] == "Office 365"
    assert masked_range["display_start"] == 0
    assert masked_range["display_end"] == len("Office 365")


def test_frontend_and_routes_use_layered_masking_contract() -> None:
    """Verify browser controls and Flask routes use layered actions and server identity."""
    chat_messages_source = read_text(CHAT_MESSAGES_JS)
    chat_collaboration_source = read_text(CHAT_COLLABORATION_JS)
    chat_route_source = read_text(CHAT_ROUTE)
    collaboration_route_source = read_text(COLLABORATION_ROUTE)

    assert_contains(
        chat_messages_source,
        [
            "function buildMaskControlsHtml(messageId, maskState = {})",
            "mask-add-btn",
            "mask-remove-btn",
            "action = maskState.fullyMasked ? 'unmask_message' : 'clear_all_masks';",
            "const action = selectionInfo ? 'mask_selection' : 'mask_all';",
            "display_start: selectionInfo.start,",
            "const rawDisplayStart = Number(range.display_start);",
            "return `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/messages/${encodedMessageId}/mask`;",
            "window.chatMessages = {",
            "applyMaskedState,",
        ],
        "layered frontend masking",
    )
    assert_not_contains(
        chat_messages_source,
        [
            "user_id: userId",
            "display_name: userDisplayName",
            "action: 'unmask_all'",
        ],
        "legacy client-controlled masking payload",
    )

    assert_contains(
        chat_collaboration_source,
        [
            "collaboration.message.masked",
            "applyCollaborationMessageMaskUpdate(payload.message);",
            "window.chatMessages.applyMaskedState(messageElement, message.metadata || {});",
        ],
        "collaboration mask event handling",
    )

    assert_contains(
        chat_route_source,
        [
            "SUPPORTED_MESSAGE_MASK_ACTIONS",
            "apply_message_mask_action(",
            "resolve_mask_display_name(current_user)",
            "request_conversation_id = str(data.get('conversation_id') or '').strip()",
        ],
        "personal mask route contract",
    )
    assert_contains(
        collaboration_route_source,
        [
            "@app.route('/api/collaboration/conversations/<conversation_id>/messages/<message_id>/mask', methods=['POST'])",
            "_assert_user_can_mask_collaboration_message(current_user['user_id'], message_doc)",
            "_sync_collaboration_mask_metadata_to_source(message_doc)",
            "'collaboration.message.masked'",
        ],
        "collaboration mask route contract",
    )


def test_documentation_and_version_are_in_sync() -> None:
    """Verify version tracking for layered message masking."""
    assert read_version() == "0.250.029"
    assert FEATURE_DOC.exists(), f"Expected feature documentation at {FEATURE_DOC}"
    feature_doc = read_text(FEATURE_DOC)
    assert "Implemented in version: **0.241.098**" in feature_doc
    assert "Rendered Markdown selection masking updated in version: **0.250.029**" in feature_doc
    assert "functional_tests/test_chat_layered_message_masking.py" in feature_doc
    assert "ui_tests/test_chat_message_layered_mask_controls.py" in feature_doc


if __name__ == "__main__":
    tests = [
        test_layered_masking_state_machine,
        test_selection_resolution_uses_canonical_content,
        test_rendered_markdown_selection_maps_to_canonical_offsets,
        test_rendered_markdown_table_selection_maps_to_canonical_offsets,
        test_frontend_and_routes_use_layered_masking_contract,
        test_documentation_and_version_are_in_sync,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as error:
            print(f"FAIL: {error}")
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)