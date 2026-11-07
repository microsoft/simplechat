# test_react_v2_development_integration.py
"""
Regression checks for the React V2 and Development integration.
Version: 0.261.419
Implemented in: 0.261.419

Prevent automatic merges from duplicating configuration helpers or appending
unreachable projection work. Runtime suites cover the owners' behavior.
"""

import ast
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


@pytest.mark.parametrize("filename,names", [
    ("route_backend_chats.py", {
        "_normalize_default_reasoning_effort",
        "_apply_admin_new_conversation_model_defaults",
    }),
    ("functions_documents.py", {"_normalize_search_acl_entries"}),
])
def test_shared_python_helpers_are_defined_once(filename, names):
    source = (APP_ROOT / filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name in names:
        definitions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        assert len(definitions) == 1, f"{filename}: duplicate or missing {name}"


def test_metadata_update_has_no_work_after_its_terminal_return():
    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    update = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "update_document")
    transaction = next(node for node in update.body if isinstance(node, ast.Try))
    for index, statement in enumerate(transaction.body):
        if isinstance(statement, ast.Return):
            assert index == len(transaction.body) - 1, "Metadata projection work follows an unconditional return"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
