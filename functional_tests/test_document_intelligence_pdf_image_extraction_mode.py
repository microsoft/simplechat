# test_document_intelligence_pdf_image_extraction_mode.py
"""
Functional test for Document Intelligence PDF/image extraction mode.
Version: 0.241.167
Implemented in: 0.241.158
Enhanced in: 0.241.163
Fixed in: 0.241.165
UI terminology updated in: 0.241.166
Extraction action terminology updated in: 0.241.167

This test ensures admins can select Standard, Enhanced, or Auto extraction for
PDFs/images while internal values remain read/layout/auto, the setting is saved and tested, and ingestion records the
resolved mode as document metadata. It also validates that the shared
Document Intelligence extractor imports its mode normalizer directly.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content, expected_text, description):
    """Raise a clear assertion error when expected text is missing."""
    if expected_text not in content:
        raise AssertionError(f"Missing {description}: {expected_text}")


def test_document_intelligence_pdf_image_extraction_mode_contract():
    """Validate the PDF/image extraction mode is wired through the app."""
    print("Testing Document Intelligence PDF/image extraction mode contract...")

    config = read_repo_file("application/single_app/config.py")
    settings = read_repo_file("application/single_app/functions_settings.py")
    extractor = read_repo_file("application/single_app/functions_content.py")
    documents = read_repo_file("application/single_app/functions_documents.py")
    admin_route = read_repo_file("application/single_app/route_frontend_admin_settings.py")
    backend_route = read_repo_file("application/single_app/route_backend_settings.py")
    admin_html = read_repo_file("application/single_app/templates/admin_settings.html")
    admin_js = read_repo_file("application/single_app/static/js/admin/admin_settings.js")
    chat_route = read_repo_file("application/single_app/route_frontend_chats.py")
    smart_http_plugin = read_repo_file("application/single_app/semantic_kernel_plugins/smart_http_plugin.py")

    assert_contains(config, 'VERSION = "', "application version declaration")

    assert_contains(settings, 'DOCUMENT_INTELLIGENCE_PDF_IMAGE_EXTRACTION_MODES = {"read", "layout", "auto"}', "allowed extraction modes")
    assert_contains(settings, "DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_DEFAULT = 3", "Auto sample page default")
    assert_contains(settings, "'document_intelligence_pdf_image_extraction_mode': 'read'", "default extraction mode")
    assert_contains(settings, "'document_intelligence_auto_sample_pages': DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_DEFAULT", "default Auto sample pages")
    assert_contains(settings, "def normalize_document_intelligence_pdf_image_extraction_mode", "mode normalizer")
    assert_contains(settings, "def normalize_document_intelligence_auto_sample_pages", "Auto sample normalizer")

    assert_contains(admin_html, 'id="document_intelligence_pdf_image_extraction_mode"', "admin extraction mode selector")
    assert_contains(admin_html, 'name="document_intelligence_pdf_image_extraction_mode"', "admin extraction mode form field")
    assert_contains(admin_html, '<option value="read"', "Standard option value")
    assert_contains(admin_html, 'Standard - faster text extraction', "Standard option label")
    assert_contains(admin_html, '<option value="layout"', "Enhanced option value")
    assert_contains(admin_html, 'Enhanced - richer structure, tables, and checkbox states', "Enhanced option label")
    assert_contains(admin_html, '<option value="auto"', "Auto option")
    assert_contains(admin_html, 'Auto - sample first pages, then choose Standard or Enhanced', "Auto option label")
    assert_contains(admin_html, 'id="document_intelligence_auto_sample_pages"', "Auto sample pages input")
    assert_contains(admin_html, "6X increase for every 1000 pages", "Enhanced cost explanation")
    assert_contains(admin_html, "documentIntelligenceExtractionHelpModal", "extraction guidance modal")
    assert_contains(admin_html, "Standard, Enhanced, and Auto", "extraction guidance modal title")

    assert_contains(admin_route, "document_intelligence_pdf_image_extraction_mode = normalize_document_intelligence_pdf_image_extraction_mode", "admin save normalizer")
    assert_contains(admin_route, "document_intelligence_auto_sample_pages = normalize_document_intelligence_auto_sample_pages", "admin save Auto sample normalizer")
    assert_contains(admin_route, "'document_intelligence_pdf_image_extraction_mode': document_intelligence_pdf_image_extraction_mode", "admin save setting")
    assert_contains(admin_route, "'document_intelligence_auto_sample_pages': document_intelligence_auto_sample_pages", "admin save Auto sample setting")

    assert_contains(admin_js, "document_intelligence_pdf_image_extraction_mode: extractionMode", "admin JS test payload")
    assert_contains(admin_js, "document_intelligence_auto_sample_pages: autoSamplePages", "admin JS Auto sample test payload")
    assert_contains(admin_js, "updateDocumentIntelligenceAutoControls", "admin JS Auto visibility toggle")
    assert_contains(admin_js, "resultDiv.textContent = data.message", "safe success rendering")
    assert_contains(admin_js, "#document_intelligence_pdf_image_extraction_mode", "walkthrough change hook")
    assert_contains(admin_js, "#document_intelligence_auto_sample_pages", "walkthrough Auto sample change hook")

    assert_contains(backend_route, 'test_extraction_mode = "layout" if extraction_mode in ("layout", "auto") else "read"', "backend Auto test mode selection")
    assert_contains(backend_route, 'model_id = "prebuilt-layout" if test_extraction_mode == "layout" else "prebuilt-read"', "backend test model selection")
    assert_contains(backend_route, 'analyze_options["output_content_format"] = "markdown"', "backend layout markdown option")
    assert_contains(backend_route, 'extraction_mode_label = "Enhanced" if extraction_mode == "layout" else "Standard"', "backend test mode label")

    assert_contains(extractor, "def extract_content_with_azure_di(file_path, extraction_mode='read', pages=None)", "extractor mode and pages parameter")
    assert_contains(extractor, "functions_settings.normalize_document_intelligence_pdf_image_extraction_mode(extraction_mode)", "extractor module-qualified mode normalizer call")
    assert_contains(extractor, 'model_id = "prebuilt-layout" if normalized_extraction_mode == "layout" else "prebuilt-read"', "extractor model selection")
    assert_contains(extractor, 'analyze_options["output_content_format"] = "markdown"', "extractor layout markdown option")
    assert_contains(extractor, 'analyze_options["pages"] = str(pages)', "extractor page sampling option")
    assert_contains(extractor, "Selection marks detected", "selection mark summary")

    assert_contains(documents, "def _resolve_document_intelligence_auto_mode", "document Auto resolver")
    assert_contains(documents, "document_intelligence_extraction_mode_requested=document_intelligence_requested_mode", "document requested mode metadata update")
    assert_contains(documents, "document_intelligence_auto_reason=document_intelligence_auto_reason", "document Auto reason metadata update")
    assert_contains(documents, "extraction_mode=document_intelligence_extraction_mode", "document extractor call")
    assert_contains(documents, '"mark_enhanced_citations": False', "source-only PDF/image blob persistence")

    assert_contains(chat_route, "get_document_intelligence_pdf_image_extraction_mode(settings)", "chat upload mode lookup")
    assert_contains(chat_route, "extraction_mode = 'layout' if is_image_file else 'read'", "chat upload Auto fallback")
    assert_contains(smart_http_plugin, "get_document_intelligence_pdf_image_extraction_mode(settings)", "Smart HTTP PDF mode lookup")
    assert_contains(smart_http_plugin, "if extraction_mode == 'auto':", "Smart HTTP Auto fallback guard")

    print("Document Intelligence PDF/image extraction mode contract passed.")
    return True


if __name__ == "__main__":
    try:
        success = test_document_intelligence_pdf_image_extraction_mode_contract()
    except Exception as exc:
        print(f"Test failed: {exc}")
        sys.exit(1)
    sys.exit(0 if success else 1)