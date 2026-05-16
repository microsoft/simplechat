#!/usr/bin/env python3
# test_standard_chat_document_action_payload_fix.py
"""
Functional test for standard chat document action payload fix.
Version: 0.241.095
Implemented in: 0.241.075

This test ensures standard chat omits disabled document-action payload fields
so the default chat path keeps the legacy tabular-analysis request shape.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_standard_chat_omits_disabled_document_action_payloads():
    """Verify standard chat keeps the legacy payload shape unless an action is selected."""
    print("🔍 Testing standard chat payload shape...")

    config_content = read_text("application/single_app/config.py")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    feature_doc_content = read_text("docs/explanation/features/v0.241.072/DOCUMENT_ACTIONS_AND_COMPARISON.md")

    assert 'VERSION = "0.241.095"' in config_content, (
        "Expected config.py version 0.241.095 for the search-documents label update."
    )
    assert '`Search Documents` keeps the normal prompt flow while searching the selected documents for relevant context.' in feature_doc_content, (
        "Expected the document actions feature doc to describe the renamed default search behavior."
    )
    assert 'const requestPayload = {' in chat_messages_content, (
        "Expected chat payload assembly to build a mutable request payload before opt-in action fields are added."
    )
    assert 'if (documentActionType !== DOCUMENT_ACTION_NONE) {' in chat_messages_content, (
        "Expected standard chat to omit disabled document_action payloads."
    )
    assert 'requestPayload.document_action = documentAction;' in chat_messages_content, (
        "Expected document_action payloads to be attached only when an action is selected."
    )
    assert 'if (documentActionType === DOCUMENT_ACTION_ANALYZE) {' in chat_messages_content, (
        "Expected legacy analysis compatibility payloads to be limited to analysis runs."
    )
    assert 'requestPayload.analyze = {' in chat_messages_content, (
        "Expected analysis compatibility payloads to remain available for analysis runs."
    )
    assert 'document_action: documentAction,' not in chat_messages_content, (
        "Standard chat should no longer serialize document_action unconditionally."
    )
    assert 'return requestPayload;' in chat_messages_content, (
        "Expected buildChatRequestPayload to return the trimmed request payload."
    )

    print("✅ Standard chat payload shape verified")


def run_tests():
    tests = [test_standard_chat_omits_disabled_document_action_payloads]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)