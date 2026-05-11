# test_chat_tutorial_selector_coverage.py
#!/usr/bin/env python3
"""
Functional test for chat tutorial selector coverage.
Version: 0.239.180
Implemented in: 0.239.180

This test ensures that the chat tutorial points at the current visible chat-page
controls and does not regress back to stale hidden or removed selectors.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIAL_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-tutorial.js"
CHAT_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
SIDEBAR_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "_sidebar_nav.html"
CHAT_CSS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "css" / "chats.css"


def test_chat_tutorial_selectors() -> bool:
    """Validate that the tutorial references current chat UI controls."""
    print("Testing chat tutorial selector coverage...")

    tutorial_content = TUTORIAL_FILE.read_text(encoding="utf-8")
    chat_template_content = CHAT_TEMPLATE_FILE.read_text(encoding="utf-8")
    sidebar_template_content = SIDEBAR_TEMPLATE_FILE.read_text(encoding="utf-8")
    chat_css_content = CHAT_CSS_FILE.read_text(encoding="utf-8")

    required_tutorial_selectors = [
        "#new-conversation-btn",
        "#sidebar-conversations-list",
        "#conversation-info-btn",
        ".ai-message .message-actions .dropdown > button",
        ".ai-message .copy-btn",
        ".ai-message .mask-btn",
        ".user-message .message-footer .dropdown > button",
        ".ai-message .metadata-container",
        ".metadata-info-btn",
        ".metadata-toggle-btn",
        ".ai-message .thoughts-container",
        ".citation-toggle-btn",
        ".user-message .dropdown-menu .dropdown-edit-btn",
        ".ai-message .dropdown-menu .dropdown-retry-btn",
        ".ai-message .dropdown-menu .feedback-btn",
        ".ai-message .dropdown-menu .dropdown-export-md-btn",
        ".ai-message .dropdown-menu .dropdown-export-word-btn",
        ".ai-message .dropdown-menu .dropdown-copy-prompt-btn",
        ".ai-message .dropdown-menu .dropdown-open-email-btn",
        ".sidebar-conversation-item .dropdown-menu .details-btn",
        ".sidebar-conversation-item .dropdown-menu .pin-btn",
        ".sidebar-conversation-item .dropdown-menu .hide-btn",
        ".sidebar-conversation-item .dropdown-menu .select-btn",
        ".sidebar-conversation-item .dropdown-menu .export-btn",
        "sidebar-nav",
        "floating-expand-btn",
        "#image-generate-btn",
        "#sidebar-search-input",
        "#sidebar-search-expand",
        "#searchMessageInput",
        ".action-type-card[data-format='json']",
        "#search-documents-btn",
        "#scope-dropdown-button",
        "#tags-dropdown-button",
        "#document-dropdown-button",
        "#sidebar-pin-selected-btn",
        "#sidebar-hide-selected-btn",
        "#sidebar-delete-selected-btn",
        "#sidebar-export-selected-btn",
        "#pin-selected-btn",
        "#hide-selected-btn",
        "#delete-selected-btn",
        "#export-selected-btn",
        "#choose-file-btn",
        "#search-web-btn",
        "#search-prompts-btn",
        "#prompt-dropdown-button",
        "#model-dropdown-button",
        "#enable-agents-btn",
        "#reasoning-toggle-btn",
        "#tts-autoplay-toggle-btn",
        "#user-input",
        "#speech-input-btn",
        "#send-btn",
    ]

    required_template_ids = [
        "id=\"new-conversation-btn\"",
        "id=\"sidebar-conversations-list\"",
        "id=\"conversation-info-btn\"",
        "id=\"image-generate-btn\"",
        "id=\"sidebar-nav\"",
        "id=\"floating-expand-btn\"",
        "id=\"sidebar-search-input\"",
        "id=\"sidebar-search-expand\"",
        "id=\"searchMessageInput\"",
        "id=\"search-documents-btn\"",
        "id=\"scope-dropdown-button\"",
        "id=\"tags-dropdown-button\"",
        "id=\"document-dropdown-button\"",
        "id=\"sidebar-pin-selected-btn\"",
        "id=\"sidebar-hide-selected-btn\"",
        "id=\"sidebar-delete-selected-btn\"",
        "id=\"sidebar-export-selected-btn\"",
        "id=\"pin-selected-btn\"",
        "id=\"hide-selected-btn\"",
        "id=\"delete-selected-btn\"",
        "id=\"export-selected-btn\"",
        "id=\"choose-file-btn\"",
        "id=\"search-web-btn\"",
        "id=\"search-prompts-btn\"",
        "id=\"prompt-dropdown-button\"",
        "id=\"model-dropdown-button\"",
        "id=\"enable-agents-btn\"",
        "id=\"reasoning-toggle-btn\"",
        "id=\"tts-autoplay-toggle-btn\"",
        "id=\"user-input\"",
        "id=\"speech-input-btn\"",
        "id=\"send-btn\"",
        "id=\"chat-tutorial-btn\"",
        "Chat Tutorial",
        "Let us walk you through getting the most out of chat",
        "data-bs-trigger=\"hover\"",
        "data-bs-custom-class=\"chat-tutorial-tooltip\"",
        "data-bs-offset=\"0,132\"",
    ]

    removed_tutorial_selectors = [
        "#streaming-toggle-btn",
        "#classification-dropdown-btn",
        "#doc-scope-select",
        "#prompt-select",
        "#agent-select",
        "#model-select",
    ]

    for selector in required_tutorial_selectors:
        if selector not in tutorial_content:
            print(f"Missing tutorial selector: {selector}")
            return False

    combined_template_content = chat_template_content + "\n" + sidebar_template_content
    combined_ui_content = combined_template_content + "\n" + chat_css_content

    for template_id in required_template_ids:
        if template_id not in combined_ui_content:
            print(f"Missing chat template control: {template_id}")
            return False

    for selector in removed_tutorial_selectors:
        if selector in tutorial_content:
            print(f"Stale tutorial selector still present: {selector}")
            return False

    required_behavior_guards = [
        "prepare: false, requireVisible: false",
        "getTarget(step, { prepare: false })",
        "function getConversationStepTarget(step, requireVisible = true)",
        "function schedulePopupTargetRefresh(step, attemptsRemaining = 6)",
        "let popupRefreshToken = 0;",
        "const refreshToken = popupRefreshToken;",
        "activeTarget = target;",
        "function syncPopupTargetHighlight(step, target)",
        "tutorial-popup-target-highlight",
        "updateSidebarDeleteButton(1)",
        "button.style.display = \"inline-flex\";",
        "const selectionKeepAlive = window.setInterval(() => {",
        "tutorialSteps[currentStepIndex]?.id !== \"conversation-bulk-actions\"",
        "function isTutorialLaunchReady()",
        "chat:sidebar-conversations-loaded",
        "function forceModalBackdropAboveTutorial()",
        "launchTooltip.hide();",
        "offset: [0, 132]",
        "let tutorialAdvancedSearchEl = null;",
        "function ensureTutorialAdvancedSearchPopup()",
        "tutorialAdvancedSearchEl = popup;",
        "querySelector(\".modal-content\") || tutorialAdvancedSearchEl",
        "querySelector(\"#advancedSearchModal .modal-dialog\")",
        "return [\"conversation-export-wizard\"].includes(stepId);",
        "function ensureSidebarHeaderControlsVisible()",
        "function ensureConversationInfoVisible()",
        "let tutorialMessagePopupEl = null;",
        "let tutorialMessageExamplesEl = null;",
        "function shouldIncludeMessageTutorialStep(step)",
        "function ensureTutorialMessageExamples(step)",
        "function getMessageStepTarget(step, requireVisible = true)",
        "function ensureTutorialMessageMenuPopup(step)",
        "function ensureMessageMetadataVisible()",
        "function ensureMessageThoughtsVisible()",
        "function ensureMessageCitationsVisible()",
        "tutorialMessageExamplesEl = wrapper;",
        "tutorialMessagePopupEl = popup;",
        "tutorial-message-examples",
        "tutorial-message-popup",
        "chat-tutorial: failed to select tutorial conversation for info step",
        "showElementForTutorial(settingsBtn, \"inline-flex\")",
        "showElementForTutorial(infoButton, \"inline-block\")",
        "function forcePopupAboveTutorial(target)",
        "function getStepScrollAnchor(step, target)",
        "function isPopupStep(stepId)",
        "function isDeferredPopupStep(stepId)",
        "function ensureTutorialConversationMenuPopup(step)",
        "tutorial-conversation-popup",
        "prepareStepTarget(step);",
    ]

    for guard in required_behavior_guards:
        if guard not in tutorial_content:
            print(f"Missing tutorial behavior guard: {guard}")
            return False

    required_ui_guards = [
        "is-ready",
        "tutorial-btn-label",
        "chat-tutorial-tooltip",
        "tutorial-force-backdrop",
        "tutorial-message-examples",
        "tutorial-message-popup",
        "tutorial-example-caption",
        "tutorial-advanced-search-popup",
        ".tutorial-advanced-search-popup .modal-dialog",
        "padding: 18px 40px 36px;",
        "overflow-x: hidden;",
    ]

    for guard in required_ui_guards:
        if guard not in combined_ui_content:
            print(f"Missing tutorial UI guard: {guard}")
            return False

    print("Chat tutorial selector coverage test passed!")
    return True


if __name__ == "__main__":
    success = test_chat_tutorial_selectors()
    sys.exit(0 if success else 1)