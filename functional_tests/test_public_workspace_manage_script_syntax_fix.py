#!/usr/bin/env python3
# test_public_workspace_manage_script_syntax_fix.py
"""
Functional test for public workspace manage script syntax recovery.
Version: 0.241.009
Implemented in: 0.241.009

This test ensures the public workspace management script parses cleanly and
that the document-ready handler block no longer contains spliced template
fragments that prevent the page from loading.
"""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MANAGE_PUBLIC_WORKSPACE_JS = (
    ROOT_DIR
    / "application"
    / "single_app"
    / "static"
    / "js"
    / "public"
    / "manage_public_workspace.js"
)
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"
FIX_DOC = (
    ROOT_DIR
    / "docs"
    / "explanation"
    / "fixes"
    / "v0.241.009"
    / "PUBLIC_WORKSPACE_MANAGE_SCRIPT_SYNTAX_FIX.md"
)
UI_TEST = ROOT_DIR / "ui_tests" / "test_public_workspace_manage_script_parse.py"


def read_file_text(file_path):
    """Read a UTF-8 text file."""
    return file_path.read_text(encoding="utf-8")


def read_config_version():
    """Read the application version from config.py."""
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def extract_document_ready_source(source):
    """Extract the top-level jQuery document-ready block from the script."""
    start_marker = "$(document).ready(function () {"
    end_marker = "// --- API & Rendering Functions ---"
    start_index = source.index(start_marker)
    end_index = source.index(end_marker)
    return source[start_index:end_index]


def test_public_workspace_manage_script_parses_with_node():
    """Verify Node can parse the public workspace management script."""
    print("Testing public workspace manage script syntax with Node.js...")

    node_path = shutil.which("node")
    if not node_path:
        print("Node.js was not found; structural syntax regression checks will still run.")
        return

    result = subprocess.run(
        [node_path, "--check", str(MANAGE_PUBLIC_WORKSPACE_JS)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Expected manage_public_workspace.js to parse cleanly. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    print("Public workspace manage script parsed cleanly with Node.js.")


def test_document_ready_handlers_are_restored():
    """Verify the repaired event handlers are present without stray template fragments."""
    print("Testing public workspace document-ready handler recovery...")

    source = read_file_text(MANAGE_PUBLIC_WORKSPACE_JS)
    document_ready_source = extract_document_ready_source(source)

    required_snippets = [
        '$(document).on("click", ".select-user-btn", function () {',
        '$("#pendingRequestsTable").on("click", ".approve-request-btn", function () {',
        '$("#pendingRequestsTable").on("click", ".reject-request-btn", function () {',
        '$("#addBulkMemberBtn").on("click", function () {',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in document_ready_source]
    assert not missing, f"Missing repaired handler snippets: {missing}"

    assert document_ready_source.count('$("#searchUsersBtn").on("click", function () {') == 1
    assert document_ready_source.count('$("#userSearchTerm").on("keydown", function (event)') == 0
    assert document_ready_source.count('$("#userSearchTerm").on("keydown", function (e)') == 1
    assert document_ready_source.count('$("#pendingRequestsTable").on("click", ".approve-request-btn"') == 1
    assert document_ready_source.count('$("#pendingRequestsTable").on("click", ".reject-request-btn"') == 1

    forbidden_fragments = [
        '          `;',
        '          }).join("");',
        'const safeUserId = escapeHtml(u.id || "");',
        '<td>${safeDisplayName}</td>',
        '<td>${safeEmail}</td>',
        'data-user-email="${safeEmail}">',
    ]
    present = [fragment for fragment in forbidden_fragments if fragment in document_ready_source]
    assert not present, f"Unexpected spliced template fragments remain: {present}"

    print("Public workspace document-ready handlers are restored.")


def test_fix_artifacts_and_version_are_in_sync():
    """Verify versioned regression artifacts landed for this fix."""
    print("Testing public workspace manage syntax fix artifact alignment...")

    assert read_config_version() == "0.241.009"
    assert FIX_DOC.exists(), f"Expected fix documentation at {FIX_DOC}"
    assert UI_TEST.exists(), f"Expected UI regression test at {UI_TEST}"

    fix_doc_source = read_file_text(FIX_DOC)
    assert "Fixed/Implemented in version: **0.241.009**" in fix_doc_source
    assert "functional_tests/test_public_workspace_manage_script_syntax_fix.py" in fix_doc_source
    assert "ui_tests/test_public_workspace_manage_script_parse.py" in fix_doc_source

    print("Public workspace manage syntax fix artifacts are aligned.")


if __name__ == "__main__":
    tests = [
        test_public_workspace_manage_script_parses_with_node,
        test_document_ready_handlers_are_restored,
        test_fix_artifacts_and_version_are_in_sync,
    ]

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        test()

    print(f"\nResults: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)