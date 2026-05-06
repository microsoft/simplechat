#!/usr/bin/env python3
# test_tabular_generated_output_exports.py
"""
Functional test for generated tabular output exports.
Version: 0.241.121
Implemented in: 0.241.121

This test ensures large tabular structured-output requests persist reusable
chat-scoped export metadata, expose a secure download route, and render a
downloadable preview card in the chat UI.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
ENHANCED_CITATIONS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_enhanced_citations.py"
SIMPLECHAT_OPERATIONS_FILE = ROOT / "application" / "single_app" / "functions_simplechat_operations.py"
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_generated_tabular_output_backend_plumbing() -> None:
    print("Testing generated tabular output backend plumbing...")

    config_content = read_text(CONFIG_FILE)
    chat_route_content = read_text(CHAT_ROUTE_FILE)
    simplechat_operations_content = read_text(SIMPLECHAT_OPERATIONS_FILE)

    assert 'VERSION = "0.241.121"' in config_content, (
        "Expected config.py version 0.241.121 for the chat-scoped generated tabular output export feature."
    )
    assert 'def upload_generated_chat_artifact_for_current_user(' in simplechat_operations_content, (
        "Expected functions_simplechat_operations.py to expose upload_generated_chat_artifact_for_current_user()."
    )
    assert 'def delete_blob_backed_chat_message_files(' in simplechat_operations_content, (
        "Expected functions_simplechat_operations.py to expose chat blob cleanup for conversation deletion paths."
    )
    assert 'maybe_create_tabular_generated_output(' in chat_route_content, (
        "Expected route_backend_chats.py to create generated tabular outputs from tabular invocations."
    )
    assert 'upload_generated_chat_artifact_for_current_user(' in chat_route_content, (
        "Expected route_backend_chats.py to save generated exports into chat-scoped artifacts."
    )
    assert chat_route_content.count("'generated_tabular_outputs': generated_tabular_outputs_list") >= 2, (
        "Expected assistant message metadata to persist generated_tabular_outputs in the main and streaming save paths."
    )
    assert "'metadata': assistant_doc.get('metadata', {})" in chat_route_content, (
        "Expected the non-streaming chat response payload to expose assistant metadata for immediate UI rendering."
    )
    assert '_build_tabular_generated_output_system_message(' in chat_route_content, (
        "Expected the chat route to add system guidance telling the model not to inline the full generated dataset."
    )
    assert "metadata.get('is_generated_chat_artifact', False)" in chat_route_content, (
        "Expected generated chat artifacts to stay out of reconstructed prompt history."
    )

    print("Backend plumbing checks passed")


def test_generated_tabular_output_download_route() -> None:
    print("Testing generated tabular output download route...")

    enhanced_citations_route_content = read_text(ENHANCED_CITATIONS_ROUTE_FILE)

    assert '@app.route("/api/chat_artifacts/download", methods=["GET"])' in enhanced_citations_route_content, (
        "Expected route_enhanced_citations.py to register /api/chat_artifacts/download."
    )
    assert 'def _get_authorized_chat_artifact_message(' in enhanced_citations_route_content, (
        "Expected route_enhanced_citations.py to authorize chat artifact access before downloading."
    )
    assert "'blob_container': message_item.get('blob_container')" in enhanced_citations_route_content, (
        "Expected the chat artifact download route to reuse the blob download helper with the stored blob reference."
    )

    print("Download route checks passed")


def test_generated_tabular_output_chat_ui_hooks() -> None:
    print("Testing generated tabular output chat UI hooks...")

    chat_messages_content = read_text(CHAT_MESSAGES_FILE)

    assert 'function getGeneratedTabularOutputs(fullMessageObject = null)' in chat_messages_content, (
        "Expected chat-messages.js to normalize generated tabular output metadata from assistant messages."
    )
    assert 'function hydrateGeneratedTabularOutputs(messageDiv, fullMessageObject = null)' in chat_messages_content, (
        "Expected chat-messages.js to hydrate a generated tabular output card into AI messages."
    )
    assert 'generated-tabular-outputs-container d-none' in chat_messages_content, (
        "Expected AI message markup to include a generated tabular outputs container."
    )
    assert '/api/chat_artifacts/download?conversation_id=' in chat_messages_content, (
        "Expected the generated export download button to target the chat artifact download route."
    )
    assert 'Saved to this chat for download in this conversation.' in chat_messages_content, (
        "Expected generated export cards to describe chat-scoped storage to the user."
    )
    assert 'output.artifact_message_id' in chat_messages_content, (
        "Expected generated export metadata normalization to accept chat artifact ids."
    )
    assert 'Download ${outputFormat.toUpperCase()}' in chat_messages_content, (
        "Expected the generated export card to label the download button using the output format."
    )

    print("Chat UI hook checks passed")


def run_tests() -> bool:
    tests = [
        test_generated_tabular_output_backend_plumbing,
        test_generated_tabular_output_download_route,
        test_generated_tabular_output_chat_ui_hooks,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)