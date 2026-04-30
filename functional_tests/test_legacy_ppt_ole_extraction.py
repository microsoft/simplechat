# test_legacy_ppt_ole_extraction.py
"""
Functional test for legacy .ppt OLE extraction.
Version: 0.241.005
Implemented in: 0.241.005

This test ensures legacy PowerPoint .ppt files use OLE metadata and slide-text
extraction while remaining on the shared document-processing workflow for
enhanced citations and final metadata extraction.
"""

import importlib.util
import os
import re
import sys
import tempfile
import types
import zipfile


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

SAMPLE_PPT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "artifacts",
    "UCCSChapter2_Spring2012.ppt",
)


def _load_functions_content_module():
    """Load functions_content with lightweight stubs for config-heavy imports."""
    module_name = "functions_content_legacy_ppt_test"
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


def test_pptx_metadata_extraction_from_core_properties():
    """Verify OOXML PowerPoint metadata is parsed from core.xml."""
    print("🔍 Testing .pptx metadata extraction...")

    temp_path = None
    try:
        core_xml = """<?xml version='1.0' encoding='UTF-8'?>
<cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties'
    xmlns:dc='http://purl.org/dc/elements/1.1/'>
    <dc:title>Quarterly Review</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:subject>Finance Update</dc:subject>
    <cp:keywords>finance; accounting</cp:keywords>
</cp:coreProperties>
"""

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as temp_file:
            temp_path = temp_file.name

        with zipfile.ZipFile(temp_path, "w") as archive:
            archive.writestr("docProps/core.xml", core_xml)

        title, author, subject, keywords = FUNCTIONS_CONTENT.extract_presentation_metadata(temp_path, ".pptx")

        if title != "Quarterly Review":
            print(f"❌ Expected PPTX title metadata, got '{title}'")
            return False

        if author != "Jane Doe":
            print(f"❌ Expected PPTX author metadata, got '{author}'")
            return False

        if subject != "Finance Update":
            print(f"❌ Expected PPTX subject metadata, got '{subject}'")
            return False

        if keywords != ["finance", "accounting"]:
            print(f"❌ Expected PPTX keyword metadata, got '{keywords}'")
            return False

        print("✅ PPTX metadata extraction works")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def test_legacy_ppt_metadata_from_sample():
    """Verify legacy PowerPoint metadata comes from OLE summary information."""
    print("🔍 Testing legacy .ppt metadata extraction...")

    try:
        title, author, subject, keywords = FUNCTIONS_CONTENT.extract_presentation_metadata(SAMPLE_PPT_PATH, ".ppt")

        if title != "Chapter 2 Transaction Analysis":
            print(f"❌ Expected PPT title metadata, got '{title}'")
            return False

        if author != "Cheryl L. Prachyl":
            print(f"❌ Expected PPT author metadata, got '{author}'")
            return False

        if subject not in ("", None):
            print(f"❌ Expected empty PPT subject metadata, got '{subject}'")
            return False

        if keywords not in ([], None):
            print(f"❌ Expected empty PPT keyword metadata, got '{keywords}'")
            return False

        print("✅ Legacy .ppt metadata extraction works")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_legacy_ppt_slide_extraction_from_sample():
    """Verify slide text is extracted and grouped by slide number."""
    print("🔍 Testing legacy .ppt slide extraction...")

    try:
        pages = FUNCTIONS_CONTENT.extract_legacy_ppt_pages(SAMPLE_PPT_PATH)
        slide_map = {page["page_number"]: page.get("content", "") for page in pages}

        if len(pages) < 21:
            print(f"❌ Expected at least 21 slide entries, got {len(pages)}")
            return False

        slide_one_text = slide_map.get(1, "")
        if "Chapter 2" not in slide_one_text or "Accounting for Business Transactions:" not in slide_one_text:
            print(f"❌ Expected slide 1 title text, got '{slide_map.get(1, '')}'")
            return False

        if "Transactions" not in slide_map.get(2, ""):
            print(f"❌ Expected slide 2 transaction text, got '{slide_map.get(2, '')}'")
            return False

        if "Do NOT proceed until you learn these rules!" not in slide_map.get(21, ""):
            print(f"❌ Expected slide 21 warning text, got '{slide_map.get(21, '')}'")
            return False

        print("✅ Legacy .ppt slide extraction works")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


def test_legacy_ppt_uses_shared_document_pipeline():
    """Verify the shared upload pipeline calls the legacy PPT extractor."""
    print("🔍 Testing legacy .ppt shared processing pipeline...")

    try:
        with open(FUNCTIONS_DOCUMENTS_PATH, "r", encoding="utf-8") as source_file:
            source_text = source_file.read()

        required_snippets = [
            "is_legacy_ppt = file_ext == '.ppt'",
            "extract_presentation_metadata(temp_file_path, file_ext)",
            "extract_legacy_ppt_pages(chunk_path)",
        ]

        missing_snippets = [snippet for snippet in required_snippets if snippet not in source_text]
        if missing_snippets:
            print(f"❌ Missing expected shared-pipeline snippets: {missing_snippets}")
            return False

        print("✅ Legacy .ppt files use the shared document-processing flow")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        traceback_module = __import__("traceback")
        traceback_module.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_pptx_metadata_extraction_from_core_properties,
        test_legacy_ppt_metadata_from_sample,
        test_legacy_ppt_slide_extraction_from_sample,
        test_legacy_ppt_uses_shared_document_pipeline,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)