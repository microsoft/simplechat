# test_document_intelligence_extraction_ui_contract.py
"""
UI test for Document Intelligence extraction mode controls.

Version: 0.241.163
Implemented in: 0.241.163

This test ensures the admin Auto guidance, workspace Read/Layout badges, and
single/bulk PDF reprocess controls are present across personal, group, and
public workspace document surfaces.
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
    assert 'updateDocumentIntelligenceAutoControls' in admin_js
    assert 'document_intelligence_auto_sample_pages: autoSamplePages' in admin_js

    assert 'id="reprocess-selected-dropdown"' in workspace_template
    assert 'getDocumentExtractionModeBadge' in workspace_js
    assert 'window.reprocessDocumentExtraction' in workspace_js
    assert 'window.reprocessSelectedDocumentExtraction' in workspace_js
    assert 'getWorkspaceDocumentReprocessDropdownItems' in workspace_tags_js

    assert 'id="group-reprocess-selected-dropdown"' in group_template
    assert 'getGroupDocumentExtractionModeBadge' in group_template
    assert 'reprocessGroupDocumentExtraction' in group_template
    assert 'reprocessGroupSelectedDocumentExtraction' in group_template

    assert 'id="public-reprocess-selected-dropdown"' in public_template
    assert 'getPublicDocumentExtractionModeBadgeHtml' in public_js
    assert 'reprocessPublicDocumentExtraction' in public_js
    assert 'reprocessPublicSelectedDocumentExtraction' in public_js


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
        expect(page.get_by_text("6X increase for every 1000 pages").first).to_be_visible()
    finally:
        browser.close()
        playwright_context.stop()