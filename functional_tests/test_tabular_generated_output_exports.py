#!/usr/bin/env python3
# test_tabular_generated_output_exports.py
"""
Functional test for generated tabular output exports and diagnostics.
Version: 0.241.144
Implemented in: 0.241.144

This test ensures large tabular structured-output requests now persist both
generic analysis artifact metadata and tabular compatibility metadata, expose
a secure download route, render a downloadable preview card in the chat UI,
and retain diagnostics that explain export candidate selection and summary handoff behavior.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
ENHANCED_CITATIONS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_enhanced_citations.py"
SIMPLECHAT_OPERATIONS_FILE = ROOT / "application" / "single_app" / "functions_simplechat_operations.py"
FUNCTIONS_SETTINGS_FILE = ROOT / "application" / "single_app" / "functions_settings.py"
SEARCH_SERVICE_FILE = ROOT / "application" / "single_app" / "functions_search_service.py"
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
EXPECTED_VERSION = "0.241.144"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_current_version() -> str:
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError("Expected config.py to define VERSION")


def test_generated_tabular_output_backend_plumbing() -> None:
    print("Testing generated tabular output backend plumbing...")

    current_version = read_current_version()
    chat_route_content = read_text(CHAT_ROUTE_FILE)
    simplechat_operations_content = read_text(SIMPLECHAT_OPERATIONS_FILE)
    functions_settings_content = read_text(FUNCTIONS_SETTINGS_FILE)
    search_service_content = read_text(SEARCH_SERVICE_FILE)

    assert current_version == EXPECTED_VERSION, (
        f"Expected config.py version {EXPECTED_VERSION} for the generated analysis artifact foundation feature."
    )
    assert 'def upload_generated_analysis_artifact_for_current_user(' in simplechat_operations_content, (
        "Expected functions_simplechat_operations.py to expose upload_generated_analysis_artifact_for_current_user()."
    )
    assert 'def upload_generated_chat_artifact_for_current_user(' in simplechat_operations_content, (
        "Expected functions_simplechat_operations.py to expose upload_generated_chat_artifact_for_current_user()."
    )
    assert "max_generated_chat_artifact_size_mb" in functions_settings_content, (
        "Expected functions_settings.py to define the generated analysis artifact size cap setting."
    )
    assert 'def delete_blob_backed_chat_message_files(' in simplechat_operations_content, (
        "Expected functions_simplechat_operations.py to expose chat blob cleanup for conversation deletion paths."
    )
    assert 'maybe_create_tabular_generated_output(' in chat_route_content, (
        "Expected route_backend_chats.py to create generated tabular outputs from tabular invocations."
    )
    assert 'upload_generated_analysis_artifact_for_current_user(' in chat_route_content, (
        "Expected route_backend_chats.py to save generated exports through the generic analysis artifact helper."
    )
    assert '_build_generated_analysis_metadata(' in chat_route_content, (
        "Expected route_backend_chats.py to normalize generic generated analysis artifact metadata."
    )
    assert chat_route_content.count("**generated_analysis_metadata") >= 3, (
        "Expected assistant message metadata to persist generated_analysis_artifacts in the document-action, main, and streaming save paths."
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
    assert '"source_subtype": "generated_chat_artifact"' in search_service_content, (
        "Expected generated chat artifacts to be distinguishable from normal chat uploads in search resolution."
    )

    print("Backend plumbing checks passed")


def test_generated_tabular_output_diagnostics_hooks() -> None:
    print("Testing generated tabular output diagnostics hooks...")

    current_version = read_current_version()
    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert current_version == EXPECTED_VERSION, (
        f"Expected config.py version {EXPECTED_VERSION} for the generated output diagnostics follow-up."
    )
    assert 'def _build_tabular_generated_output_candidate_diagnostic(' in chat_route_content, (
        "Expected route_backend_chats.py to summarize each tabular invocation considered for export selection."
    )
    assert 'def _build_tabular_generated_output_candidate_diagnostics(' in chat_route_content, (
        "Expected route_backend_chats.py to collect export-source diagnostics across tabular invocations."
    )
    assert "'[Tabular Generated Output] Evaluated source candidates'" in chat_route_content, (
        "Expected route_backend_chats.py to log the tabular export candidate set before choosing an export source."
    )
    assert "'[Tabular Generated Output] Selected source candidate'" in chat_route_content, (
        "Expected route_backend_chats.py to log the selected tabular export source candidate."
    )
    assert "'[Tabular Generated Output] Structured export batch attempt mismatch'" in chat_route_content, (
        "Expected route_backend_chats.py to log structured-export batch parse mismatches with a response preview."
    )
    assert "'[Tabular Related Documents] Resolved row-linked document evidence'" in chat_route_content, (
        "Expected route_backend_chats.py to log when row-linked related-document evidence is successfully resolved."
    )
    assert 'def _log_tabular_generated_output_handoff(' in chat_route_content, (
        "Expected route_backend_chats.py to centralize logging for the summary-only generated-output handoff."
    )
    assert chat_route_content.count('_log_tabular_generated_output_handoff(') >= 7, (
        "Expected each generated-output handoff path to emit an explicit summary-only diagnostic log."
    )

    print("Diagnostics hook checks passed")


def test_generated_tabular_output_attachment_context_normalization() -> None:
    print("Testing generated tabular output attachment-context normalization...")

    current_version = read_current_version()
    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert current_version == EXPECTED_VERSION, (
        f"Expected config.py version {EXPECTED_VERSION} for the generated output attachment-context fix."
    )
    assert 'def _build_tabular_generated_output_input_row(' in chat_route_content, (
        "Expected route_backend_chats.py to normalize generated-output rows with canonical attachment context fields."
    )
    assert "normalized_row['attachment_text'] = attachment_text" in chat_route_content, (
        "Expected generated-output row normalization to surface attachment_text when referenced document excerpts are available."
    )
    assert "normalized_row['attachment_present'] = True" in chat_route_content, (
        "Expected generated-output row normalization to mark attachment presence when attachment evidence or names are present."
    )
    assert "Do not say attachment text is unavailable when such excerpts are present." in chat_route_content, (
        "Expected the structured export batch prompt to forbid claiming attachment text is unavailable when referenced excerpts are present."
    )
    assert '_build_tabular_generated_output_input_row(' in chat_route_content.split('async def _generate_tabular_structured_output_entries', 1)[1], (
        "Expected structured export generation to normalize batch rows before sending them to the model."
    )

    print("Attachment-context normalization checks passed")


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

    assert 'function getGeneratedAnalysisArtifacts(fullMessageObject = null)' in chat_messages_content, (
        "Expected chat-messages.js to normalize generic generated analysis artifact metadata from assistant messages."
    )
    assert 'function getGeneratedTabularOutputs(fullMessageObject = null)' in chat_messages_content, (
        "Expected chat-messages.js to normalize generated tabular output metadata from assistant messages."
    )
    assert 'function hydrateGeneratedAnalysisArtifacts(messageDiv, fullMessageObject = null)' in chat_messages_content, (
        "Expected chat-messages.js to hydrate generic generated analysis artifact cards into AI messages."
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
    assert 'generated_analysis_artifacts' in chat_messages_content, (
        "Expected generated export metadata normalization to read generic generated analysis artifacts first."
    )
    assert 'output.artifact_message_id' in chat_messages_content, (
        "Expected generated export metadata normalization to accept chat artifact ids."
    )
    assert 'Download ${outputFormat.toUpperCase()}' in chat_messages_content, (
        "Expected the generated export card to label the download button using the output format."
    )

    print("Chat UI hook checks passed")


def test_table_request_marker_variants_cover_natural_phrasing() -> None:
    print("Testing table request marker variants for natural phrasing...")

    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert "'put that into a table'" in chat_route_content, (
        "Expected route_backend_chats.py to recognize 'put that into a table' as a table-export request."
    )
    assert "'turn that into a table'" in chat_route_content, (
        "Expected route_backend_chats.py to recognize 'turn that into a table' as a table-export request."
    )
    assert "'put this into a table'" in chat_route_content, (
        "Expected route_backend_chats.py to recognize 'put this into a table' as a table-export request."
    )

    print("Table marker variant checks passed")


def run_tests() -> bool:
    tests = [
        test_generated_tabular_output_backend_plumbing,
        test_generated_tabular_output_diagnostics_hooks,
        test_generated_tabular_output_attachment_context_normalization,
        test_generated_tabular_output_download_route,
        test_generated_tabular_output_chat_ui_hooks,
        test_table_request_marker_variants_cover_natural_phrasing,
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