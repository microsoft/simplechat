# test_chat_follow_up_prompt_actions.py
"""
Functional test for chat follow-up prompt actions.
Version: 0.241.051
Implemented in: 0.241.050

This test ensures assistant next-step suggestions are rendered as prompt actions
that stage text in the chat input with a cancelable send countdown, without
duplicating the source suggestion text in the rendered assistant message.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_MESSAGES_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def test_chat_follow_up_prompt_actions_are_available():
    """Validate the chat UI includes safe follow-up action helpers."""
    print("Testing chat follow-up prompt action helpers...")

    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")

    assert "function extractSuggestedFollowUpPrompts" in source
    assert "function extractFollowUpSuggestionCandidates" in source
    assert "function extractQuestionFollowUpCandidates" in source
    assert "function normalizeFollowUpQuestionCandidate" in source
    assert "const MAX_SUGGESTED_FOLLOW_UP_ACTIONS = 3" in source
    assert "function buildFollowUpRenderModel" in source
    assert "function stripSuggestedFollowUpSourceText" in source
    assert "function findTrailingFollowUpTriggerLineIndex" in source
    assert "function renderSuggestedFollowUpButtons" in source
    assert "function stageFollowUpPrompt" in source
    assert "function startFollowUpAutoSendCountdown" in source
    assert "followUpSuggestions: followUpRenderModel.suggestions" in source
    assert "visibleMarkdown: stripSuggestedFollowUpSourceText(rawText)" in source
    assert "button.textContent = suggestion.label" in source
    assert "button.addEventListener('click'" in source
    assert "sendBtn.addEventListener('click', followUpAutoSendCancel, true)" in source
    assert "sendMessage();" in source
    assert "innerHTML = suggestion" not in source


def test_chat_follow_up_question_prompts_are_recognized():
    """Validate closing follow-up questions are recognized as button candidates."""
    print("Testing chat follow-up question prompt recognition...")

    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")

    assert "do\\s+you\\s+want\\s+me\\s+to" in source
    assert "would\\s+you\\s+like\\b" in source
    assert "suggested\\s+(?:follow" in source
    assert "normalizeFollowUpPromptPerspective" in source
    assert "give me" in source
    assert "formatSuggestedPromptLabel" in source


def test_chat_follow_up_prompt_buttons_render_after_message_text():
    """Validate follow-up actions are attached to completed assistant messages."""
    print("Testing chat follow-up prompt action rendering hook...")

    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")
    render_call_pattern = re.compile(
        r"chatbox\.appendChild\(messageDiv\);\s*// Append AI message\s*\n\s*renderSuggestedFollowUpButtons\(messageDiv, renderedAiContent\.followUpSuggestions\);",
        re.MULTILINE,
    )

    assert render_call_pattern.search(source)


def test_chat_inline_export_prompt_variants_are_recognized():
    """Validate natural presentation/deck wording is included in export intent detection."""
    print("Testing chat inline export prompt variants...")

    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")

    assert "create|make|generate|draft|write|prepare|compose|build|send|export|provide|turn|convert" in source
    assert "slide deck|presentation deck|executive deck|board deck|deck|slides?" in source
    assert "hasPresentationIntent && !hasPowerPointIntent" in source


if __name__ == "__main__":
    tests = [
        test_chat_follow_up_prompt_actions_are_available,
        test_chat_follow_up_question_prompts_are_recognized,
        test_chat_follow_up_prompt_buttons_render_after_message_text,
        test_chat_inline_export_prompt_variants_are_recognized,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"Test passed: {test.__name__}")
            results.append(True)
        except Exception as test_error:
            print(f"Test failed: {test.__name__}: {test_error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
