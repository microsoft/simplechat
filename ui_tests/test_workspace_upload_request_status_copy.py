#!/usr/bin/env python3
"""
UI test for workspace upload request status copy.
Version: 0.261.005
Implemented in: 0.261.005

This test ensures workspace upload progress summaries distinguish request
confirmation from final document processing results.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_SURFACES = [
    REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-documents.js",
    REPO_ROOT / "application" / "single_app" / "static" / "js" / "public" / "public_workspace.js",
    REPO_ROOT / "application" / "single_app" / "templates" / "group_workspaces.html",
]


def test_upload_summaries_do_not_label_request_failures_as_document_failures():
    """Upload summaries should not present unconfirmed requests as final document failures."""
    for path in UPLOAD_SURFACES:
        source = path.read_text(encoding="utf-8")

        assert "Upload requests not confirmed" in source
        assert "Check the document list below for final processing status" in source
        assert "Uploaded ${completed}/${files.length}${failed ? `, Failed: ${failed}` : ''}" not in source


if __name__ == "__main__":
    test_upload_summaries_do_not_label_request_failures_as_document_failures()
    print("Workspace upload request status copy test passed")
