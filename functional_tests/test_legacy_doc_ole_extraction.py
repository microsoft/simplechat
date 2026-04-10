# test_legacy_doc_ole_extraction.py
"""
Functional test for legacy .doc OLE extraction.
Version: 0.241.004
Implemented in: 0.241.004

This test ensures Word 97-2003 .doc files are parsed through the OLE piece-table
path and routed through the shared document-processing workflow instead of the
OOXML archive path that expects word/document.xml.
"""

import importlib.util
import os
import re
import struct
import sys
import types
from unittest.mock import patch


FUNCTIONS_CONTENT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "application",
    "single_app",
    "functions_content.py",
)

FUNCTIONS_DOCUMENTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "application",
    "single_app",
    "functions_documents.py",
)


def _load_functions_content_module():
    """Load functions_content with lightweight stubs for config-heavy imports."""
    module_name = "functions_content_legacy_doc_test"
    spec = importlib.util.spec_from_file_location(module_name, FUNCTIONS_CONTENT_PATH)
    module = importlib.util.module_from_spec(spec)

    config_stub = types.ModuleType("config")
    config_stub.os = os
    config_stub.re = re
    config_stub.CLIENTS = {}
    config_stub.AZURE_ENVIRONMENT = "public"
    config_stub.WORD_CHUNK_SIZE = 400

    debug_stub = types.ModuleType("functions_debug")
    debug_stub.debug_print = lambda *args, **kwargs: None

    settings_stub = types.ModuleType("functions_settings")
    logging_stub = types.ModuleType("functions_logging")

    original_modules = {
        "config": sys.modules.get("config"),
        "functions_debug": sys.modules.get("functions_debug"),
        "functions_settings": sys.modules.get("functions_settings"),
        "functions_logging": sys.modules.get("functions_logging"),
    }

    sys.modules["config"] = config_stub
    sys.modules["functions_debug"] = debug_stub
    sys.modules["functions_settings"] = settings_stub
    sys.modules["functions_logging"] = logging_stub

    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for module_key, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_key, None)
            else:
                sys.modules[module_key] = original_module


FUNCTIONS_CONTENT = _load_functions_content_module()


def _build_piece_table_stream(text, compressed=True):
    """Build a minimal PlcPcd stream for a single legacy Word text piece."""
    if compressed:
        word_stream = text.encode("cp1252")
        fc_value = 0x40000000
    else:
        word_stream = text.encode("utf-16le")
        fc_value = 0

    piece_descriptor = b"\x00\x00" + struct.pack("<I", fc_value) + b"\x00\x00"
    piece_table = struct.pack("<II", 0, len(text)) + piece_descriptor
    table_stream = b"\x01\x00\x00" + b"\x02" + struct.pack("<I", len(piece_table)) + piece_table
    return word_stream, table_stream


def test_compressed_legacy_doc_piece_table():
    """Verify ANSI-compressed legacy Word pieces decode correctly."""
    print("🔍 Testing compressed legacy .doc piece-table extraction...")

    try:
        expected_text = "Hello legacy doc"
        word_stream, table_stream = _build_piece_table_stream(expected_text, compressed=True)
        extracted_text = FUNCTIONS_CONTENT._extract_legacy_doc_text_from_table_stream(word_stream, table_stream)

        if extracted_text != expected_text:
            print(f"❌ Expected '{expected_text}' but got '{extracted_text}'")
            return False

        print("✅ Compressed legacy piece-table extraction works")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_unicode_legacy_doc_piece_table():
    """Verify UTF-16 legacy Word pieces decode correctly."""
    print("🔍 Testing Unicode legacy .doc piece-table extraction...")

    try:
        expected_text = "Unicode legacy"
        word_stream, table_stream = _build_piece_table_stream(expected_text, compressed=False)
        extracted_text = FUNCTIONS_CONTENT._extract_legacy_doc_text_from_table_stream(word_stream, table_stream)

        if extracted_text != expected_text:
            print(f"❌ Expected '{expected_text}' but got '{extracted_text}'")
            return False

        print("✅ Unicode legacy piece-table extraction works")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_word_dispatch_uses_ole_for_doc_only():
    """Verify .doc files use olefile while .docm files stay on the OOXML path."""
    print("🔍 Testing .doc/.docm dispatch behavior...")

    try:
        with patch.object(FUNCTIONS_CONTENT.olefile, "isOleFile", return_value=True), patch.object(
            FUNCTIONS_CONTENT,
            "extract_legacy_doc_text",
            return_value="legacy text",
        ) as legacy_extract, patch.object(
            FUNCTIONS_CONTENT,
            "extract_docx_text",
            return_value="ooxml text",
        ) as ooxml_extract:
            doc_result = FUNCTIONS_CONTENT.extract_word_text("sample.doc", ".doc")
            docm_result = FUNCTIONS_CONTENT.extract_word_text("sample.docm", ".docm")

        if doc_result != "legacy text":
            print(f"❌ Expected .doc dispatch to return legacy text, got '{doc_result}'")
            return False

        if docm_result != "ooxml text":
            print(f"❌ Expected .docm dispatch to return ooxml text, got '{docm_result}'")
            return False

        if legacy_extract.call_count != 1:
            print(f"❌ Expected one legacy extractor call, got {legacy_extract.call_count}")
            return False

        if ooxml_extract.call_count != 1:
            print(f"❌ Expected one OOXML extractor call, got {ooxml_extract.call_count}")
            return False

        print("✅ Word dispatch separates .doc and .docm correctly")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_field_code_cleanup_keeps_display_text():
    """Verify Word field instructions are removed while display text stays visible."""
    print("🔍 Testing legacy field-code cleanup...")

    try:
        raw_text = 'See \x13 HYPERLINK "https://example.com" \x14example link\x15 now'
        cleaned_text = FUNCTIONS_CONTENT._normalize_legacy_doc_text(raw_text)

        if cleaned_text != 'See example link now':
            print(f"❌ Expected cleaned field text, got '{cleaned_text}'")
            return False

        print("✅ Field-code cleanup keeps visible link text only")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_legacy_doc_metadata_normalization():
    """Verify OLE metadata byte values are normalized into plain strings."""
    print("🔍 Testing legacy .doc metadata normalization...")

    try:
        normalized_author = FUNCTIONS_CONTENT._normalize_legacy_doc_metadata_value(b"Paul Lizer\x00")
        normalized_blank = FUNCTIONS_CONTENT._normalize_legacy_doc_metadata_value(b"\x00")

        if normalized_author != "Paul Lizer":
            print(f"❌ Expected decoded author metadata, got '{normalized_author}'")
            return False

        if normalized_blank != "":
            print(f"❌ Expected blank metadata to normalize to empty string, got '{normalized_blank}'")
            return False

        print("✅ Legacy metadata values normalize correctly")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_legacy_doc_dispatch_uses_shared_document_pipeline():
    """Verify .doc files use the shared document-processing path while .docm stays direct."""
    print("🔍 Testing legacy .doc processing dispatch...")

    try:
        with open(FUNCTIONS_DOCUMENTS_PATH, "r", encoding="utf-8") as source_file:
            source_text = source_file.read()

        required_snippets = [
            "is_legacy_doc = file_ext == '.doc'",
            "extract_word_text(chunk_path, file_ext)",
            "elif file_ext == '.docm':",
            "elif file_ext in di_supported_extensions or file_ext == '.doc':",
        ]

        missing_snippets = [snippet for snippet in required_snippets if snippet not in source_text]
        if missing_snippets:
            print(f"❌ Missing expected shared-pipeline snippets: {missing_snippets}")
            return False

        print("✅ Legacy .doc files use the shared document-processing flow")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_compressed_legacy_doc_piece_table,
        test_unicode_legacy_doc_piece_table,
        test_word_dispatch_uses_ole_for_doc_only,
        test_field_code_cleanup_keeps_display_text,
        test_legacy_doc_metadata_normalization,
        test_legacy_doc_dispatch_uses_shared_document_pipeline,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)