# test_document_intelligence_extraction_ui_contract.py
"""
UI test for Document Intelligence extraction mode controls.

Version: 0.241.167
Implemented in: 0.241.163
Fixed in: 0.241.164
UI terminology updated in: 0.241.166
Extraction action terminology updated in: 0.241.167

This test ensures the admin Auto guidance, workspace Standard/Enhanced badges, and
single/bulk PDF extraction-change controls are present across personal, group, and
public workspace document surfaces. It also ensures extraction badges stay in
expanded metadata/details views instead of top-level document rows or cards.
"""

import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
WORKSPACE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"
WORKSPACE_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-documents.js"
WORKSPACE_TAGS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-tags.js"
GROUP_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"
PUBLIC_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "public_workspaces.html"
PUBLIC_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "public" / "public_workspace.js"


@pytest.mark.ui
def test_document_intelligence_extraction_ui_static_contract():
    """Validate stable selectors and handlers for extraction controls."""
    admin_template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    admin_js = ADMIN_JS.read_text(encoding="utf-8")
    workspace_template = WORKSPACE_TEMPLATE.read_text(encoding="utf-8")
    workspace_js = WORKSPACE_JS.read_text(encoding="utf-8")
    workspace_tags_js = WORKSPACE_TAGS_JS.read_text(encoding="utf-8")
    group_template = GROUP_TEMPLATE.read_text(encoding="utf-8")
    public_template = PUBLIC_TEMPLATE.read_text(encoding="utf-8")
    public_js = PUBLIC_JS.read_text(encoding="utf-8")

    assert 'id="document_intelligence_pdf_image_extraction_mode"' in admin_template
    assert '<option value="auto"' in admin_template
    assert 'id="document_intelligence_auto_sample_pages"' in admin_template
    assert 'id="document_intelligence_auto_sample_pages_group"' in admin_template
    assert 'id="documentIntelligenceExtractionHelpModal"' in admin_template
    assert '6X increase for every 1000 pages' in admin_template
    assert 'Standard - faster text extraction' in admin_template
    assert 'Enhanced - richer structure, tables, and checkbox states' in admin_template
    assert 'Auto - sample first pages, then choose Standard or Enhanced' in admin_template
    assert 'updateDocumentIntelligenceAutoControls' in admin_js
    assert 'document_intelligence_auto_sample_pages: autoSamplePages' in admin_js

    assert 'id="reprocess-selected-dropdown"' in workspace_template
    assert 'Change Extraction' in workspace_template
    assert "window.reprocessSelectedDocumentExtraction('read')\">Extract Again as Standard" in workspace_template
    assert "window.reprocessSelectedDocumentExtraction('layout')\">Extract Again as Enhanced" in workspace_template
    assert 'getDocumentExtractionModeBadge' in workspace_js
    assert 'window.reprocessDocumentExtraction' in workspace_js
    assert 'window.reprocessSelectedDocumentExtraction' in workspace_js
    assert 'getDocumentTargetExtractionMode' in workspace_js
    assert 'Change to ${targetLabel}' in workspace_js
    assert 'Reprocess PDF' not in workspace_js
    assert 'Standard extraction uses Document Intelligence Read' in workspace_js
    assert 'Enhanced extraction uses Document Intelligence Layout' in workspace_js
    assert 'Standard citations reference indexed text chunks' in workspace_js
    assert 'Enhanced citations preserve source-file context' in workspace_js
    assert 'getWorkspaceDocumentReprocessDropdownItems' in workspace_tags_js
    assert '<strong>Extraction:</strong> ${getDocumentExtractionModeBadge(doc)}' in workspace_js
    assert '<span class="ms-1">${getDocumentExtractionModeBadge(doc)}</span>' not in workspace_js
    assert 'extractionBadge' not in workspace_tags_js

    assert 'id="group-reprocess-selected-dropdown"' in group_template
    assert 'Change Extraction' in group_template
    assert "reprocessGroupSelectedDocumentExtraction('read')\">Extract Again as Standard" in group_template
    assert "reprocessGroupSelectedDocumentExtraction('layout')\">Extract Again as Enhanced" in group_template
    assert 'getGroupDocumentExtractionModeBadge' in group_template
    assert 'reprocessGroupDocumentExtraction' in group_template
    assert 'reprocessGroupSelectedDocumentExtraction' in group_template
    assert 'getGroupDocumentTargetExtractionMode' in group_template
    assert 'Change to ${targetLabel}' in group_template
    assert 'Reprocess PDF' not in group_template
    assert 'Standard extraction uses Document Intelligence Read' in group_template
    assert 'Enhanced extraction uses Document Intelligence Layout' in group_template
    assert '<strong>Extraction:</strong> ${getGroupDocumentExtractionModeBadge(doc)}' in group_template
    assert '<span class="ms-1">${getGroupDocumentExtractionModeBadge(doc)}</span>' not in group_template

    assert 'id="public-reprocess-selected-dropdown"' in public_template
    assert 'Change Extraction' in public_template
    assert "reprocessPublicSelectedDocumentExtraction('read')\">Extract Again as Standard" in public_template
    assert "reprocessPublicSelectedDocumentExtraction('layout')\">Extract Again as Enhanced" in public_template
    assert 'getPublicDocumentExtractionModeBadgeHtml' in public_js
    assert 'reprocessPublicDocumentExtraction' in public_js
    assert 'reprocessPublicSelectedDocumentExtraction' in public_js
    assert 'getPublicDocumentTargetExtractionMode' in public_js
    assert 'Change to ${extractionActionLabel}' in public_js
    assert 'Reprocess PDF' not in public_js
    assert 'Standard extraction uses Document Intelligence Read' in public_js
    assert 'Enhanced extraction uses Document Intelligence Layout' in public_js
    assert 'This document was uploaded manually and is not managed by File Sync.' in public_js
    assert '<strong>Extraction:</strong> ${getPublicDocumentExtractionModeBadgeHtml(doc)}' in public_js
    assert '<span class="ms-1">${getPublicDocumentExtractionModeBadgeHtml(doc)}</span>' not in public_js
    assert 'createPublicDocumentExtractionModeBadge(doc);' not in public_js


@pytest.mark.ui
def test_document_intelligence_admin_controls_render_from_template():
    """Render the admin extraction section and validate visible controls."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI render test.")

    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    section_match = re.search(
        r'<div class="card p-3 mb-3" id="document-intelligence-section"[\s\S]*?<div class="form-group form-check form-switch mb-3 d-flex align-items-center">',
        template,
    )
    assert section_match, "Expected to find the Document Intelligence admin section."
    section_html = section_match.group(0)
    section_html = re.sub(r"\{\%[^%]*\%\}", "", section_html)
    section_html = re.sub(r"\{\{[^}]*\}\}", "3", section_html)

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.set_content(f"<main>{section_html}</main>")
        expect(page.locator("#document-intelligence-section")).to_be_visible()
        expect(page.locator("#document_intelligence_pdf_image_extraction_mode")).to_be_visible()
        expect(page.locator("#document_intelligence_pdf_image_extraction_mode option[value='auto']")).to_have_count(1)
        expect(page.locator("#document_intelligence_auto_sample_pages")).to_have_attribute("min", "1")
        expect(page.locator("#document_intelligence_auto_sample_pages")).to_have_attribute("max", "20")
        expect(page.locator("#documentIntelligenceExtractionHelpModal")).to_be_attached()
        expect(page.locator("#document_intelligence_pdf_image_extraction_mode option[value='read']")).to_contain_text("Standard - faster text extraction")
        expect(page.locator("#document_intelligence_pdf_image_extraction_mode option[value='layout']")).to_contain_text("Enhanced - richer structure, tables, and checkbox states")
        expect(page.get_by_text("6X increase for every 1000 pages").first).to_be_visible()
    finally:
        browser.close()
        playwright_context.stop()