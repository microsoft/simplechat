#!/usr/bin/env python3
# test_chat_document_action_select_all_toggle.py
"""
Functional test for chat document action select-all toggle.
Version: 0.241.095
Implemented in: 0.241.085

This test ensures the chat document picker switches its top action from
"All Documents" search mode to a select-all toggle when a deterministic
folder-backed document action is active.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_chat_document_action_select_all_toggle_wiring() -> None:
    print("🔍 Testing chat document action select-all toggle wiring...")

    config_content = read_text("application/single_app/config.py")
    chat_documents_content = read_text("application/single_app/static/js/chat/chat-documents.js")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    chat_template_content = read_text("application/single_app/templates/chats.html")

    assert 'VERSION = "0.241.095"' in config_content, (
        "Expected config.py version 0.241.095 for the chat document select-all toggle update."
    )
    assert 'const documentActionSelect = document.getElementById("document-action-select");' in chat_documents_content, (
        "Expected the chat document picker to inspect the current document action selection."
    )
    assert 'function getDocumentDropdownActionLabel() {' in chat_documents_content, (
        "Expected chat documents logic to expose a dedicated top-action label helper."
    )
    assert '"Select All Documents"' in chat_documents_content, (
        "Expected the chat document picker to offer a select-all action label in document-action mode."
    )
    assert '"Clear Selected Documents"' in chat_documents_content, (
        "Expected the chat document picker to allow clearing an all-selected action state."
    )
    assert 'textEl.textContent = isExplicitDocumentSelectionMode() ? "Select Documents" : "All Documents";' in chat_documents_content, (
        "Expected the picker button text to stop showing All Documents when a document action requires explicit targets."
    )
    assert 'const shouldClearSelections = areAllSelectableDocumentsSelected();' in chat_documents_content, (
        "Expected the top picker action to toggle between select-all and clear-selected behavior."
    )
    assert 'option.selected = !shouldClearSelections && !option.disabled;' in chat_documents_content, (
        "Expected select-all mode to check all currently selectable documents without selecting disabled ones."
    )
    assert 'documentActionSelect.addEventListener("change", function() {' in chat_documents_content, (
        "Expected document action changes to resync the picker labels immediately."
    )
    assert 'const DOCUMENT_ACTION_ANALYZE = \'analyze\';' in chat_messages_content, (
        "Expected chat message handling to keep using the deterministic document action mode that drives the picker toggle."
    )
    assert 'id="document-action-select"' in chat_template_content, (
        "Expected the chat template to continue rendering the document action selector used by the picker toggle."
    )

    print("✅ Chat document action select-all toggle wiring verified")


def run_tests() -> bool:
    tests = [test_chat_document_action_select_all_toggle_wiring]
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
