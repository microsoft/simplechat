#!/usr/bin/env python3
# test_file_sync_tag_definition_application.py
"""
Functional test for File Sync tag definition application.
Version: 0.241.178
Implemented in: 0.241.131

This test ensures File Sync applies source-defined tags to new and unchanged
synced documents so source definition changes do not leave documents untagged.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def get_function_source(relative_path, function_name):
    source_text = read_text(relative_path)
    parsed_source = ast.parse(source_text)
    source_lines = source_text.splitlines()

    for node in ast.walk(parsed_source):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return "\n".join(source_lines[node.lineno - 1:node.end_lineno])

    raise AssertionError(f"Function {function_name} not found in {relative_path}")


def test_config_version_updated():
    """Validate the fix version is tracked in config.py."""
    config_text = read_text("application/single_app/config.py")
    assert 'VERSION = "0.241.178"' in config_text


def test_unchanged_file_paths_reconcile_tags():
    """Validate unchanged remote files still reconcile source-defined tags."""
    process_source = get_function_source(
        "application/single_app/functions_file_sync.py",
        "_process_file_sync_source",
    )

    assert "_remote_file_unchanged(existing_item, remote_file)" in process_source
    assert "existing_item.get(\"content_hash\") == content_hash" in process_source
    assert process_source.count("_apply_sync_tags_to_existing_document(source, existing_item, remote_file)") >= 2


def test_tag_reconciliation_updates_existing_document_metadata():
    """Validate existing synced documents are updated when derived tags differ."""
    helper_source = get_function_source(
        "application/single_app/functions_file_sync.py",
        "_apply_sync_tags_to_existing_document",
    )

    required_snippets = [
        "tags = _derive_tags_for_remote_file(source, remote_file)",
        "_ensure_sync_tag_definitions(user_id, scope_type, group_id, public_workspace_id, tags)",
        "document_metadata = get_document_metadata(",
        "current_tags = document_metadata.get(\"tags\") or []",
        "if current_tags == tags:",
        "update_document(",
        "tags=tags",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in helper_source]
    assert not missing, f"Missing tag reconciliation snippets: {missing}"


def test_new_and_existing_paths_share_tag_definition_creation():
    """Validate new and existing synced docs use the same tag definition path."""
    create_source = get_function_source(
        "application/single_app/functions_file_sync.py",
        "_create_document_from_remote_file",
    )
    definition_source = get_function_source(
        "application/single_app/functions_file_sync.py",
        "_ensure_sync_tag_definitions",
    )
    workspace_type_source = get_function_source(
        "application/single_app/functions_file_sync.py",
        "_tag_definition_workspace_type",
    )

    assert "_ensure_sync_tag_definitions(user_id, scope_type, group_id, public_workspace_id, tags)" in create_source
    assert "get_or_create_tag_definition(" in definition_source
    assert "workspace_type=_tag_definition_workspace_type(scope_type)" in definition_source
    assert "FILE_SYNC_SCOPE_PUBLIC" in workspace_type_source


if __name__ == "__main__":
    tests = [
        test_config_version_updated,
        test_unchanged_file_paths_reconcile_tags,
        test_tag_reconciliation_updates_existing_document_metadata,
        test_new_and_existing_paths_share_tag_definition_creation,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"Passed {test.__name__}")
            results.append(True)
        except Exception as error:
            print(f"Failed {test.__name__}: {error}")
            results.append(False)

    sys.exit(0 if all(results) else 1)