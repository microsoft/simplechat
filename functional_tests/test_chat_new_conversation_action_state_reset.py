#!/usr/bin/env python3
# test_chat_new_conversation_action_state_reset.py
"""
Functional test for chat New Conversation action-state reset.
Version: 0.241.106
Implemented in: 0.241.106

This test ensures explicit New Chat clears per-chat toolbar actions while
Deep Research keeps the user's saved default for later Web Search and URL use.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(ROOT_DIR, "application", "single_app")

CHAT_INPUT_ACTIONS_FILE = os.path.join(APP_ROOT, "static", "js", "chat", "chat-input-actions.js")
CHAT_DOCUMENTS_FILE = os.path.join(APP_ROOT, "static", "js", "chat", "chat-documents.js")
CHAT_PROMPTS_FILE = os.path.join(APP_ROOT, "static", "js", "chat", "chat-prompts.js")
CHATS_TEMPLATE_FILE = os.path.join(APP_ROOT, "templates", "chats.html")
CONFIG_FILE = os.path.join(APP_ROOT, "config.py")


def read_file(path):
    """Read a source file as UTF-8 text."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_input_actions_reset_transient_toolbar_state():
    """Verify explicit context resets clear per-chat toolbar buttons."""
    print("Testing chat input action reset wiring...")
    source = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_snippets = [
        "export function resetContextualSourceActionState(event = null)",
        "if (detail.preserveSelections) {",
        "resetImageGenerationActionState();",
        "setToggleButtonActive(webSearchBtn, false);",
        "setToggleButtonActive(urlAccessBtn, false);",
        "setToggleButtonActive(sourceReviewBtn, false);",
        "resetFileButton();",
        "updateWebSearchNotice(false);",
        "includeDefaultUrlPrompt: false",
        "restoreDeepResearchDefault: false",
        'window.addEventListener("chat:conversation-context-changed", resetContextualSourceActionState);',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing input action reset snippets: {missing}"

    print("Input action reset wiring verified.")
    return True


def test_deep_research_default_preference_is_preserved():
    """Verify Deep Research remembers manual user preference but resets visible state."""
    print("Testing Deep Research default preference wiring...")
    source = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_snippets = [
        'const DEEP_RESEARCH_DEFAULT_SETTING_KEY = "deepResearchDefaultEnabled";',
        'const DEEP_RESEARCH_DEFAULT_STORAGE_KEY = "simplechat.deepResearchDefaultEnabled";',
        "let deepResearchDefaultPreferenceDirty = false;",
        "function setDeepResearchDefaultPreference(isEnabled, options = {})",
        "saveUserSetting({ [DEEP_RESEARCH_DEFAULT_SETTING_KEY]: deepResearchDefaultEnabled });",
        "function initializeDeepResearchDefaultPreference()",
        "loadUserSettings()",
        "includeDefaultUrlPrompt && deepResearchDefaultEnabled && promptUrls.length > 0",
        "if (restoreDeepResearchDefault && deepResearchDefaultEnabled) {",
        "setDeepResearchDefaultPreference(isToggleButtonActive(this));",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing Deep Research default snippets: {missing}"
    assert "setDeepResearchDefaultPreference(false" not in source, (
        "Programmatic reset should not overwrite the remembered Deep Research default."
    )

    print("Deep Research default preference wiring verified.")
    return True


def test_workspace_and_prompt_surfaces_reset_on_context_change():
    """Verify workspace and prompt UI state listens to conversation context resets."""
    print("Testing workspace and prompt reset listeners...")
    documents_source = read_file(CHAT_DOCUMENTS_FILE)
    prompts_source = read_file(CHAT_PROMPTS_FILE)

    document_required_snippets = [
        "function resetWorkspaceSearchActionState(event = null)",
        "if (detail.preserveSelections) {",
        "userWorkspaceContextActive = false;",
        "documentActionSelect.value = DOCUMENT_ACTION_NONE;",
        "resetTagSelectionState();",
        "hideSearchDocumentsPanel();",
        "handleDocumentSelectChange();",
        "window.addEventListener('chat:conversation-context-changed', resetWorkspaceSearchActionState);",
    ]
    prompt_required_snippets = [
        "function resetPromptSelectionState(event = null)",
        "if (detail.preserveSelections) {",
        "setPromptSelectionVisible(false);",
        'window.addEventListener("chat:conversation-context-changed", resetPromptSelectionState);',
    ]

    missing_documents = [snippet for snippet in document_required_snippets if snippet not in documents_source]
    missing_prompts = [snippet for snippet in prompt_required_snippets if snippet not in prompts_source]

    assert not missing_documents, f"Missing workspace reset snippets: {missing_documents}"
    assert not missing_prompts, f"Missing prompt reset snippets: {missing_prompts}"

    print("Workspace and prompt reset listeners verified.")
    return True


def test_web_search_notice_uses_class_based_visibility():
    """Verify the web search notice can be reset with Bootstrap hidden state."""
    print("Testing web search notice hidden-state wiring...")
    input_source = read_file(CHAT_INPUT_ACTIONS_FILE)
    template_source = read_file(CHATS_TEMPLATE_FILE)

    assert 'id="web-search-notice-container" class="mb-2 d-none"' in template_source
    assert 'webSearchNoticeContainer.classList.toggle("d-none", !shouldShowNotice);' in input_source
    assert 'webSearchNoticeContainer.style.display' not in input_source

    print("Web search notice hidden-state wiring verified.")
    return True


def test_config_version_updated():
    """Verify config.py reflects the action-state reset implementation version."""
    print("Testing config.py version update...")
    config_source = read_file(CONFIG_FILE)
    assert 'VERSION = "0.241.106"' in config_source
    print("Config version update verified.")
    return True


def main():
    """Run all regression checks."""
    tests = [
        test_input_actions_reset_transient_toolbar_state,
        test_deep_research_default_preference_is_preserved,
        test_workspace_and_prompt_surfaces_reset_on_context_change,
        test_web_search_notice_uses_class_based_visibility,
        test_config_version_updated,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())