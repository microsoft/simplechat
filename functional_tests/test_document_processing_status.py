# test_document_processing_status.py
"""
Functional regressions for document terminal-state interpretation.
Version: 0.261.351
Implemented in: 0.261.351

Execute the real Python, React and classic predicates against shared cases,
plus backend progress, safe job updates, facets and chat-readiness decisions.
No settings bootstrap, live storage or provider calls are needed.
"""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_support.app_source import run_definitions
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
UI = ROOT / "application" / "v2_ui"
sys.path.insert(0, str(APP))

from content_screening.contracts import document_is_available  # noqa: E402
from functions_document_queries import (  # noqa: E402
    _document_processing_state, build_document_facets, filter_documents_by_place,
)
from functions_document_status import (  # noqa: E402
    is_document_processing_complete, is_document_processing_failure,
)


CASES = json.loads((ROOT / "functional_tests" / "document_processing_status_cases.json").read_text(encoding="utf-8"))
PREDICATES = {
    "is_document_processing_complete": is_document_processing_complete,
    "is_document_processing_failure": is_document_processing_failure,
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["status"]))
def test_python_status_contract(case):
    failure = is_document_processing_failure(case["status"])
    complete = is_document_processing_complete(case["status"])
    assert failure is case["failure"]
    assert complete is case["complete"]


def test_browser_predicates_match_python_contract(tmp_path):
    bundle = tmp_path / "document-status.cjs"
    subprocess.run([
        "node", str(UI / "node_modules" / "esbuild" / "bin" / "esbuild"),
        str(UI / "src" / "lib" / "documentProcessingStatus.ts"),
        "--bundle", "--platform=node", "--format=cjs", f"--outfile={bundle}", "--log-level=error",
    ], check=True, capture_output=True, text=True)
    probe = r"""
        const fs = require('node:fs');
        const vm = require('node:vm');
        const assert = require('node:assert/strict');
        const react = require(process.argv[1]);
        const context = vm.createContext({window: {}});
        vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
        const classic = context.window.DocumentStatus;
        const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
        for (const value of cases) {
            assert.equal(react.isDocumentProcessingFailure(value.status), value.failure, JSON.stringify(value));
            assert.equal(react.isDocumentProcessingComplete(value.status), value.complete, JSON.stringify(value));
            assert.equal(classic.isFailure(value.status), value.failure, JSON.stringify(value));
            assert.equal(classic.isComplete(value.status), value.complete, JSON.stringify(value));
        }
    """
    subprocess.run([
        "node", "-e", probe, str(bundle), str(APP / "static" / "js" / "document-status.js"),
        str(ROOT / "functional_tests" / "document_processing_status_cases.json"),
    ], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("status", [
    "Processing file failed-complete.md, type: .md",
    "Processing file processing complete.md, type: .md",
    "Processing sheet 'error-completed'...",
    "Retrying Markdown processing after a transient parser concurrency error (1/3)...",
])
def test_backend_progress_and_safe_updates_do_not_infer_terminal_state(status):
    writes = []
    namespace = {
        **PREDICATES, "json": json,
        "update_document": lambda **values: writes.append(values),
    }
    run_definitions("functions_documents.py", {
        "calculate_processing_percentage", "_update_document_for_job",
    }, namespace)
    progress = namespace["calculate_processing_percentage"]({
        "status": status, "percentage_complete": 0,
    })
    namespace["_update_document_for_job"](document_id="doc", status=status, safe_errors=True)
    assert progress == 0
    assert writes == [{"document_id": "doc", "status": status}]


def test_explicit_failure_is_sanitized_and_guarded():
    writes = []
    namespace = {
        **PREDICATES, "update_document": lambda **values: writes.append(values),
    }
    run_definitions("functions_documents.py", {"_update_document_for_job"}, namespace)
    guard = lambda: {"_etag": "revision-1"}
    namespace["_update_document_for_job"](
        document_id="doc", status="Error: PRIVATE PROVIDER DETAIL",
        operation_guard=guard, safe_errors=True,
    )
    [written] = writes
    assert written["status"] == "Document processing failed. Contact an administrator if the problem persists."
    assert written["expected_etag"] == "revision-1"
    assert written["strict"] is True
    assert written["operation_guard"] is guard


def test_facets_and_filters_do_not_confuse_details_with_failures():
    documents = [
        {"id": "filename", "status": "Processing file failed.md, type: .md", "percentage_complete": 0},
        {"id": "retry", "status": "Retrying Markdown after an error", "percentage_complete": 20},
        {"id": "failure", "status": "Error: unavailable", "percentage_complete": 100},
        {"id": "ready", "status": "Processing complete", "percentage_complete": 100},
        {"id": "legacy"},
    ]
    facets = build_document_facets(documents, "owner")
    processing = filter_documents_by_place(documents, "processing", "owner")
    failed = filter_documents_by_place(documents, "errors", "owner")
    legacy_state = _document_processing_state(documents[-1])
    assert facets["processing"] == 2
    assert facets["errors"] == 1
    assert [item["id"] for item in processing] == ["filename", "retry"]
    assert [item["id"] for item in failed] == ["failure"]
    assert legacy_state == "ready"


@pytest.mark.parametrize(("changes", "expected"), [
    ({}, True),
    ({"status": "Processing file processing complete.md, type: .md", "percentage_complete": 0}, False),
    ({"status": "Error: unable to read"}, False),
    ({"number_of_pages": 0}, False),
    ({"chat_upload_link_state": "unlinked"}, False),
    ({"search_visibility_state": "archived"}, False),
])
def test_search_readiness_preserves_independent_requirements(changes, expected):
    namespace = {**PREDICATES, "document_is_available": document_is_available}
    run_definitions("route_backend_chats.py", {"_is_search_ready_chat_upload_workspace_document"}, namespace)
    document = {
        "status": "Processing complete", "percentage_complete": 100, "number_of_pages": 1,
        **changes,
    }
    ready = namespace["_is_search_ready_chat_upload_workspace_document"](document)
    assert ready is expected


def test_implementation_version():
    assert_app_version_at_least("0.261.351")
