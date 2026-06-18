# test_upload_dlp_workspace_scopes.py
#!/usr/bin/env python3
"""
Functional test for upload DLP workspace scope coverage.
Version: 0.242.074
Implemented in: 0.242.073

This test ensures personal, group, public, and external public upload routes
continue using the shared document processing path protected by upload DLP.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")


ROUTE_FILES = {
    "personal": os.path.join(APP_DIR, "route_backend_documents.py"),
    "group": os.path.join(APP_DIR, "route_backend_group_documents.py"),
    "public": os.path.join(APP_DIR, "route_backend_public_documents.py"),
    "external_public": os.path.join(APP_DIR, "route_external_public_documents.py"),
}
FUNCTIONS_DOCUMENTS_FILE = os.path.join(APP_DIR, "functions_documents.py")


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_upload_routes_remain_present_for_all_workspace_scopes():
    """All supported upload route files should expose upload endpoints."""
    print("Testing upload route coverage...")
    expectations = {
        "personal": "/api/documents/upload",
        "group": "/api/group_documents/upload",
        "public": "/api/public_documents/upload",
        "external_public": "/external/public_documents/upload",
    }

    for scope, route_file in ROUTE_FILES.items():
        source = read_file_text(route_file)
        assert expectations[scope] in source, f"Missing upload route for {scope}"
        assert "process_document_upload_background" in source, f"{scope} route does not use shared processing"


def test_shared_processing_path_carries_workspace_scope_to_upload_dlp():
    """functions_documents should map upload DLP context for personal/group/public scopes."""
    print("Testing upload DLP workspace context...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)

    assert "workspace_scope" in source
    assert '"personal"' in source
    assert '"group"' in source
    assert '"public"' in source
    assert "public_workspace_id" in source
    assert "group_id" in source


if __name__ == "__main__":
    tests = [
        test_upload_routes_remain_present_for_all_workspace_scopes,
        test_shared_processing_path_carries_workspace_scope_to_upload_dlp,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} upload DLP workspace scope tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
