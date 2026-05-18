#!/usr/bin/env python3
# test_chat_document_progress_details_toggle_contract.py
"""
Functional test for chat document progress detail toggles.
Version: 0.241.037
Implemented in: 0.241.037

This test ensures the document-analysis progress card keeps overall progress
visible while document-level sub actions are collapsed by default and can be
expanded through a persisted toggle state.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_chat_document_progress_details_toggle_contract():
    config_content = read_text("application/single_app/config.py")
    thoughts_content = read_text("application/single_app/static/js/chat/chat-thoughts.js")
    chats_css_content = read_text("application/single_app/static/css/chats.css")
    ui_test_content = read_text("ui_tests/test_chat_document_progress_details_toggle.py")

    assert 'VERSION = "0.241.037"' in config_content, (
        "Expected config.py version 0.241.037 for the chat document progress details toggle."
    )
    assert "progressDetailsExpandedStates" in thoughts_content, (
        "Expected the progress detail expanded state to persist across streaming re-renders."
    )
    assert "action-progress-details-toggle" in thoughts_content, (
        "Expected document progress cards to render a details toggle button."
    )
    assert "document-analysis-progress-details" in thoughts_content, (
        "Expected document-level sub actions to live in a dedicated collapsible details container."
    )
    assert "detailsElement.classList.toggle('d-none', !isExpanded);" in thoughts_content, (
        "Expected document progress details to use Bootstrap's d-none class for hiding."
    )
    assert "aria-expanded" in thoughts_content and "aria-controls" in thoughts_content, (
        "Expected the progress details toggle to expose accessible expanded state and target linkage."
    )
    assert ".action-progress-details-toggle" in chats_css_content, (
        "Expected the compact details toggle to have stable dimensions in chat CSS."
    )
    assert "preserve that expanded state across streaming updates" in ui_test_content, (
        "Expected UI regression coverage for expanded-state persistence."
    )


if __name__ == "__main__":
    test_chat_document_progress_details_toggle_contract()
    print("Chat document progress details toggle checks passed.")