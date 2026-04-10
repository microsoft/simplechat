# test_document_upload_traceback_shadow_fix.py
"""
Functional test for document upload traceback shadowing fix.
Version: 0.239.165
Implemented in: 0.239.165

This test ensures PDF and DOCX upload processing no longer shadows the traceback
module inside process_di_document, which previously caused upload failures when
exception handling tried to call traceback.format_exc().
"""

import ast
import os
import sys


FUNCTIONS_DOCUMENTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "application",
    "single_app",
    "functions_documents.py",
)


def _load_module_ast():
    with open(FUNCTIONS_DOCUMENTS_PATH, "r", encoding="utf-8") as source_file:
        return ast.parse(source_file.read(), filename=FUNCTIONS_DOCUMENTS_PATH)


def test_traceback_import_is_module_scoped():
    """Verify traceback is imported at module scope for functions_documents."""
    print("🔍 Checking module-level traceback import...")

    try:
        module_ast = _load_module_ast()
        has_module_import = any(
            isinstance(node, ast.Import)
            and any(alias.name == "traceback" for alias in node.names)
            for node in module_ast.body
        )

        if not has_module_import:
            print("❌ Module-level 'import traceback' not found")
            return False

        print("✅ Module-level 'import traceback' found")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_process_di_document_has_no_local_traceback_import():
    """Verify process_di_document no longer defines traceback as a local name."""
    print("🔍 Checking process_di_document for local traceback imports...")

    try:
        module_ast = _load_module_ast()
        process_di_document_node = next(
            (
                node
                for node in module_ast.body
                if isinstance(node, ast.FunctionDef) and node.name == "process_di_document"
            ),
            None,
        )

        if process_di_document_node is None:
            print("❌ process_di_document function not found")
            return False

        local_traceback_imports = [
            node
            for node in ast.walk(process_di_document_node)
            if isinstance(node, ast.Import)
            and any(alias.name == "traceback" for alias in node.names)
        ]

        if local_traceback_imports:
            print("❌ Found function-local 'import traceback' in process_di_document")
            return False

        uses_traceback_format_exc = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "traceback"
            and node.func.attr == "format_exc"
            for node in ast.walk(process_di_document_node)
        )

        if not uses_traceback_format_exc:
            print("❌ process_di_document no longer calls traceback.format_exc(); expected regression guard missing")
            return False

        print("✅ process_di_document uses traceback.format_exc() without local shadowing")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_traceback_import_is_module_scoped,
        test_process_di_document_has_no_local_traceback_import,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)