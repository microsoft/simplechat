# test_msg_processor_auto_metadata_argument.py
"""
Functional test for Outlook MSG processor metadata argument compatibility.
Version: 0.250.031
Implemented in: 0.250.031

This test ensures the document upload dispatcher can pass the shared
auto_extract_metadata argument to the Outlook MSG processor without raising a
TypeError during .msg upload processing.
"""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_DOCUMENTS = REPO_ROOT / "application" / "single_app" / "functions_documents.py"


def _load_functions_documents_tree():
    return ast.parse(FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8"))


def _find_function(tree, function_name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"Could not find {function_name} in functions_documents.py")


def test_process_msg_accepts_auto_extract_metadata():
    """Validate process_msg accepts the dispatcher's shared metadata flag."""
    tree = _load_functions_documents_tree()
    process_msg = _find_function(tree, "process_msg")
    argument_names = [argument.arg for argument in process_msg.args.args]

    assert "auto_extract_metadata" in argument_names


def test_msg_dispatch_uses_processor_args_without_file_ext():
    """Validate .msg dispatch keeps the shared no-auto-metadata argument shape."""
    source = FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8")

    expected_call = (
        "process_msg(**{k: v for k, v in processor_args_without_auto_metadata.items() "
        "if k != \"file_ext\"})"
    )

    assert expected_call in source


if __name__ == "__main__":
    test_process_msg_accepts_auto_extract_metadata()
    test_msg_dispatch_uses_processor_args_without_file_ext()
    print("MSG processor metadata argument compatibility tests passed.")