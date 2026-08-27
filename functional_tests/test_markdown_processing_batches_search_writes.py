#!/usr/bin/env python3
"""
Functional test for Markdown document processing batch Search writes.
Version: 0.261.004
Implemented in: 0.261.004

This test ensures Markdown processing uses the batch chunk writer so large
workspace uploads do not reserve the Data Management Search write gate once per
chunk.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_DOCUMENTS_PATH = REPO_ROOT / "application" / "single_app" / "functions_documents.py"


def _find_function(module_tree, function_name):
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"Could not find {function_name} in functions_documents.py")


def _called_function_names(function_node):
    names = []
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def test_process_md_uses_batch_chunk_writer():
    """Markdown processing should use one batched Search write path per file."""
    module_tree = ast.parse(FUNCTIONS_DOCUMENTS_PATH.read_text(encoding="utf-8"))
    process_md = _find_function(module_tree, "process_md")
    call_names = _called_function_names(process_md)

    assert "save_chunks_batch" in call_names
    assert "save_chunks" not in call_names


if __name__ == "__main__":
    try:
        test_process_md_uses_batch_chunk_writer()
    except Exception as exc:
        print(f"Test failed: {exc}")
        raise

    print("Markdown processing batch Search write test passed")
    sys.exit(0)
