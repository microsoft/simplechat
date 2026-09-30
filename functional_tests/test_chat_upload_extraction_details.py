#!/usr/bin/env python3
# test_chat_upload_extraction_details.py
"""
Functional test for chat upload extraction details.
Version: 0.261.210
Implemented in: 0.261.210

This test ensures a chat upload backed by a workspace document returns what ingestion
extracted for it (the indexed text and the stored image analysis) instead of
"File content not found", and that the response never carries storage or screening state.
"""

import ast
import logging
import sys
from pathlib import Path

from flask import Flask, jsonify

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
ROUTE_FILE = APP_DIR / "route_backend_documents.py"

sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

import functions_chat_upload_extraction as extraction  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

VISION_ANALYSIS = {
    "model": "gpt-5.4",
    "description": "A grayscale image of a large indoor lab with a mostly empty tiled floor.",
    "objects": ["checkerboard calibration panels", " ", "equipment rack"],
    "text": "",
    "analysis": "Likely a robotics or computer vision test space.",
}

LINKED_DOCUMENT = {
    "id": "doc-lab",
    "file_name": "lab.png",
    "title": "AI Vision Analysis of Indoor Environment",
    "abstract": "An indoor lab.",
    "keywords": ["lab", "calibration"],
    "status": "Processing complete - final metadata extracted",
    "percentage_complete": 100,
    "number_of_pages": 1,
    "extraction_engine": "document_intelligence",
    "extraction_engine_reason": "Content Understanding returned no content, so Document Intelligence Layout was used",
    "vision_analysis": VISION_ANALYSIS,
    # Server-only state that must never reach the browser through this response.
    "blob_container": "user-documents",
    "blob_path": "user/lab.png",
    "user_id": "user-1",
    "content_screening": {"state": "released"},
}


def test_summarize_vision_analysis_keeps_only_displayable_parts():
    """Errors and empty analyses are dropped; aliases and lists are normalized."""
    summary = extraction.summarize_vision_analysis(VISION_ANALYSIS)
    assert summary == {
        "model": "gpt-5.4",
        "description": VISION_ANALYSIS["description"],
        "objects": ["checkerboard calibration panels", "equipment rack"],
        "text": "",
        "analysis": VISION_ANALYSIS["analysis"],
    }, summary

    assert extraction.summarize_vision_analysis(None) is None
    assert extraction.summarize_vision_analysis("text") is None
    assert extraction.summarize_vision_analysis({
        "description": "Model returned empty content with no refusal message",
        "error": "Model returned empty content with no refusal message",
        "parse_failed": True,
    }) is None
    assert extraction.summarize_vision_analysis({"model": "gpt-5.4", "objects": []}) is None

    aliased = extraction.summarize_vision_analysis({
        "model_name": "gpt-4o",
        "objects": "chair",
        "contextual_analysis": "An office.",
    })
    assert aliased["model"] == "gpt-4o"
    assert aliased["objects"] == ["chair"]
    assert aliased["analysis"] == "An office."


def test_indexed_upload_returns_joined_chunks_and_details():
    """Indexed chunks are the body; details describe how the file was read."""
    chunks = [
        {"chunk_text": "<!-- PageNumber=\"J\" -->\n\n=== AI Vision Analysis ===\nModel: gpt-5.4"},
        {"chunk_text": "   "},
        "not-a-chunk",
        {"chunk_text": "Second page"},
    ]
    payload, status = extraction.build_workspace_upload_file_content("lab.png", LINKED_DOCUMENT, chunks)

    assert status == 200, payload
    assert payload["file_content"].startswith("<!-- PageNumber=\"J\" -->")
    assert payload["file_content"].endswith("Second page")
    assert payload["filename"] == "lab.png"
    assert payload["is_table"] is False
    assert payload["file_content_source"] == "workspace"
    assert payload["indexed_text_available"] is True

    details = payload["workspace_document"]
    assert details["document_id"] == "doc-lab"
    assert details["extraction_engine"] == "document_intelligence"
    assert details["extraction_engine_reason"].startswith("Content Understanding returned no content")
    assert details["indexed_chunk_count"] == 3
    assert details["keywords"] == ["lab", "calibration"]
    assert details["vision_analysis"]["description"] == VISION_ANALYSIS["description"]

    exposed = set(details)
    for server_only in ("blob_container", "blob_path", "user_id", "content_screening", "id"):
        assert server_only not in exposed, f"{server_only} leaked into the response"


def test_unindexed_image_falls_back_to_the_stored_vision_analysis():
    """An image ingestion never indexed still shows what the vision model saw."""
    document = {**LINKED_DOCUMENT, "status": "Processing complete - no text found in image", "title": ""}
    payload, status = extraction.build_workspace_upload_file_content("22222.png", document, [])

    assert status == 200, payload
    assert payload["indexed_text_available"] is False
    assert payload["workspace_document"]["indexed_chunk_count"] == 0
    assert "AI Vision Analysis" in payload["file_content"]
    assert VISION_ANALYSIS["description"] in payload["file_content"]
    assert "Objects Detected: checkerboard calibration panels, equipment rack" in payload["file_content"]


def test_nothing_to_show_explains_processing_or_absence():
    """No chunks and no analysis is a clear 404, worded by whether ingestion finished."""
    processing = {"id": "doc-new", "status": "Sending lab.png to Azure AI Content Understanding...", "percentage_complete": 35}
    payload, status = extraction.build_workspace_upload_file_content("lab.png", processing, [])
    assert status == 404
    assert payload["error"] == extraction.STILL_PROCESSING_MESSAGE
    assert payload["workspace_document"]["percentage_complete"] == 35

    finished = {"id": "doc-done", "status": "Processing complete - no text found in image", "percentage_complete": 100}
    payload, status = extraction.build_workspace_upload_file_content("lab.png", finished, [])
    assert status == 404
    assert payload["error"] == extraction.NO_EXTRACTED_CONTENT_MESSAGE

    status_only = {"id": "doc-queued", "status": "Queued for processing"}
    payload, status = extraction.build_workspace_upload_file_content("lab.png", status_only, None)
    assert status == 404
    assert payload["error"] == extraction.STILL_PROCESSING_MESSAGE

    # A failed document is final: ingestion saves percentage 0 with an Error status.
    failed = {"id": "doc-failed", "status": "Error: Processing failed: The chunk is too large", "percentage_complete": 0}
    assert extraction.is_workspace_upload_processing(failed) is False
    payload, status = extraction.build_workspace_upload_file_content("lab.png", failed, [])
    assert status == 404
    assert payload["error"] == extraction.PROCESSING_FAILED_MESSAGE
    assert payload["workspace_document"]["status"].startswith("Error:")

    # A failed document that still stored its vision analysis shows it rather than an error.
    failed_with_vision = {**failed, "vision_analysis": VISION_ANALYSIS}
    payload, status = extraction.build_workspace_upload_file_content("lab.png", failed_with_vision, [])
    assert status == 200 and payload["indexed_text_available"] is False


def _load_route_helper():
    """Compile the route's helper on its own, with its collaborators supplied by the test."""
    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8-sig"))
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_workspace_upload_file_content_response"
    )
    module = ast.Module(body=[helper], type_ignores=[])

    class ScreeningError(Exception):
        def __init__(self, public_message, code, status_code):
            super().__init__(public_message)
            self.public_message = public_message
            self.code = code
            self.status_code = status_code

    logged = []
    namespace = {
        "jsonify": jsonify,
        "logging": logging,
        "ScreeningError": ScreeningError,
        "build_workspace_upload_file_content": extraction.build_workspace_upload_file_content,
        "log_event": lambda message, **kwargs: logged.append((message, kwargs)),
        "get_ordered_document_chunks": None,
    }
    exec(compile(module, str(ROUTE_FILE), "exec"), namespace)
    return namespace, ScreeningError, logged


def test_route_helper_reads_chunks_in_the_linked_documents_scope():
    """The helper reads chunks with the stored document's own scope and returns them."""
    namespace, _screening_error, _logged = _load_route_helper()
    calls = []

    def fake_chunks(document_id, user_id=None, group_id=None, public_workspace_id=None):
        calls.append((document_id, user_id, group_id, public_workspace_id))
        return [{"chunk_text": "Indexed image description"}]

    namespace["get_ordered_document_chunks"] = fake_chunks
    group_document = {**LINKED_DOCUMENT, "group_id": "group-1"}
    app = Flask(__name__)
    with app.app_context():
        response, status = namespace["_workspace_upload_file_content_response"](
            {"filename": "fallback.png"}, group_document, "user-1", "file-1",
        )
    assert status == 200
    assert response.get_json()["file_content"] == "Indexed image description"
    assert response.get_json()["filename"] == "lab.png"
    assert calls == [("doc-lab", "user-1", "group-1", None)], calls


def test_route_helper_never_returns_raw_exception_text():
    """Screening errors keep their public wording; anything else is a stable message."""
    namespace, screening_error, logged = _load_route_helper()
    app = Flask(__name__)

    def held(*_args, **_kwargs):
        raise screening_error("This document is unavailable pending review.", "document_held", 409)

    namespace["get_ordered_document_chunks"] = held
    with app.app_context():
        response, status = namespace["_workspace_upload_file_content_response"]({}, LINKED_DOCUMENT, "user-1", "file-1")
    assert status == 409
    assert response.get_json() == {
        "error": "This document is unavailable pending review.",
        "error_code": "document_held",
    }

    def missing(*_args, **_kwargs):
        raise LookupError("Document not found or access denied.")

    namespace["get_ordered_document_chunks"] = missing
    with app.app_context():
        response, status = namespace["_workspace_upload_file_content_response"]({}, LINKED_DOCUMENT, "user-1", "file-1")
    assert status == 404
    assert response.get_json() == {"error": "File not found in conversation"}

    def broken(*_args, **_kwargs):
        raise RuntimeError("search endpoint https://secret.search.windows.net failed with key abc123")

    namespace["get_ordered_document_chunks"] = broken
    with app.app_context():
        response, status = namespace["_workspace_upload_file_content_response"]({}, LINKED_DOCUMENT, "user-1", "file-1")
    assert status == 500
    body = response.get_json()
    assert body == {"error": "Unable to load the extracted content for this file."}
    assert "secret" not in str(body)
    assert logged and logged[-1][0].startswith("[GET_FILE_CONTENT]")
    assert logged[-1][1]["extra"]["error_type"] == "RuntimeError"


def test_get_file_content_routes_workspace_uploads_before_the_empty_content_404():
    """Workspace-backed, unscreened, non-table uploads use the helper before combining text."""
    source = ROUTE_FILE.read_text(encoding="utf-8-sig")
    route_start = source.index("def get_file_content():")
    branch = source.index("return _workspace_upload_file_content_response(", route_start)
    combine = source.index("combined_parts = []", route_start)
    not_found = source.index("'File content not found'", route_start)
    assert branch < combine < not_found

    guard = source[source.rindex("if (", route_start, branch):branch]
    for condition in (
        "linked_document is not None",
        "SCREENING_FIELD not in linked_document",
        "not items[0].get('is_table')",
        "not items[0].get('file_content')",
    ):
        assert condition in guard, f"Missing guard: {condition}"

    # Ownership is checked before any message or document read happens.
    ownership = source.index("if conversation_item.get('user_id') != user_id:", route_start)
    assert ownership < branch


def test_version_includes_the_change():
    assert_app_version_at_least("0.261.210")


if __name__ == "__main__":
    tests = [
        test_summarize_vision_analysis_keeps_only_displayable_parts,
        test_indexed_upload_returns_joined_chunks_and_details,
        test_unindexed_image_falls_back_to_the_stored_vision_analysis,
        test_nothing_to_show_explains_processing_or_absence,
        test_route_helper_reads_chunks_in_the_linked_documents_scope,
        test_route_helper_never_returns_raw_exception_text,
        test_get_file_content_routes_workspace_uploads_before_the_empty_content_404,
        test_version_includes_the_change,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Passed")
            results.append(True)
        except Exception as error:  # noqa: BLE001 - report every failure in the runner.
            print(f"Failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
