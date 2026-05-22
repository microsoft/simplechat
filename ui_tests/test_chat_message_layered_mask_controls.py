# test_chat_message_layered_mask_controls.py
"""
UI test for layered chat message mask controls.
Version: 0.241.098
Implemented in: 0.241.098

This test ensures chat messages render independent mask add/remove controls and
that collaboration mask events can update an existing message without a page
reload.
"""

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CHAT_MESSAGES_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
CHAT_COLLABORATION_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-collaboration.js"
STYLES_CSS = ROOT_DIR / "application" / "single_app" / "static" / "css" / "styles.css"
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"


def read_text(path: Path) -> str:
    """Read a UTF-8 repository text file."""
    return path.read_text(encoding="utf-8")


def read_version() -> str:
    """Extract the application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('"')[1]
    raise AssertionError("VERSION assignment was not found in config.py")


def assert_contains(source: str, snippets: list[str], description: str) -> None:
    """Assert every required snippet exists in source."""
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f"Missing {description} snippets: {missing}"


def test_layered_mask_controls_render_add_and_remove_buttons() -> None:
    """Verify the chat footer renders stable mask-plus and mask-minus controls."""
    source = read_text(CHAT_MESSAGES_JS)
    styles = read_text(STYLES_CSS)

    assert_contains(
        source,
        [
            "function buildMaskControlsHtml(messageId, maskState = {})",
            "message-mask-controls d-inline-flex align-items-center gap-1",
            "mask-btn mask-add-btn",
            "mask-btn mask-remove-btn",
            "bi-plus-lg",
            "bi-dash-lg",
            "attachMaskButtonEventListeners(messageDiv);",
        ],
        "layered mask control markup",
    )
    assert_contains(
        styles,
        [
            ".message-mask-controls",
            ".mask-action-icon",
            ".mask-action-modifier",
        ],
        "layered mask control styles",
    )


def test_layered_mask_controls_update_without_destructive_unmask() -> None:
    """Verify the remove control preserves text masks when a full-message mask is active."""
    source = read_text(CHAT_MESSAGES_JS)

    assert_contains(
        source,
        [
            "const action = maskState.fullyMasked ? 'unmask_message' : 'clear_all_masks';",
            "Full-message mask removed; text masks remain",
            "payload.selection = {",
            "masked_ranges: Array.isArray(data?.masked_ranges) ? data.masked_ranges : [],",
        ],
        "non-destructive layered mask updates",
    )
    assert "action: 'unmask_all'" not in source


def test_collaboration_mask_events_apply_to_visible_messages() -> None:
    """Verify shared conversations use the collaboration mask endpoint and event hook."""
    messages_source = read_text(CHAT_MESSAGES_JS)
    collaboration_source = read_text(CHAT_COLLABORATION_JS)

    assert_contains(
        messages_source,
        [
            "window.chatCollaboration?.isCollaborationConversation?.(conversationId)",
            "return `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/messages/${encodedMessageId}/mask`;",
            "applyMaskedState,",
        ],
        "collaboration mask endpoint routing",
    )
    assert_contains(
        collaboration_source,
        [
            "function applyCollaborationMessageMaskUpdate(message = {})",
            "cacheCollaborationMessage(message);",
            "window.chatMessages.applyMaskedState(messageElement, message.metadata || {});",
            "collaboration.message.masked",
        ],
        "collaboration mask UI event handling",
    )


def test_ui_mask_control_version_matches_config() -> None:
    """Verify UI test version tracking matches config.py."""
    assert read_version() == "0.241.098"