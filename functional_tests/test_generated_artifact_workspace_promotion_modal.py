#!/usr/bin/env python3
# test_generated_artifact_workspace_promotion_modal.py
"""
Functional test for generated artifact workspace promotion target selection.
Version: 0.241.096
Implemented in: 0.241.096

This test ensures generated chat artifact promotion uses a confirmation or
target-selection modal instead of blocking users with a one-scope warning toast.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def test_promotion_modal_replaces_scope_warning_toast():
    """Validate the chat artifact promotion flow exposes a modal chooser."""
    chat_messages_content = CHAT_MESSAGES_FILE.read_text(encoding="utf-8")

    assert "Select exactly one workspace scope before adding this artifact." not in chat_messages_content, (
        "Expected workspace promotion to avoid the old dead-end warning toast."
    )
    assert "function chooseGeneratedArtifactPromotionTarget" in chat_messages_content, (
        "Expected chat-messages.js to show a target confirmation or selection modal."
    )
    assert "generated-artifact-workspace-modal" in chat_messages_content, (
        "Expected a Bootstrap modal shell for workspace promotion target selection."
    )
    assert "activeConversationScope === 'personal'" in chat_messages_content, (
        "Expected personal conversations to default to personal workspace promotion."
    )
    assert "Add to Selected Workspace" in chat_messages_content, (
        "Expected ambiguous promotion targets to require an explicit modal selection."
    )
    return True


def run_tests():
    tests = [
        test_promotion_modal_replaces_scope_warning_toast,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
            print("PASS")
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)