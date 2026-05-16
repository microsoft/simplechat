# test_chat_search_panel_document_row_layout.py
"""
UI test for chat search panel document row layout.
Version: 0.241.032
Implemented in: 0.241.032

This test ensures Search and Analyze keep the Document picker on the same
desktop row as Action, Scope, and Tags, keeps opened dropdown menus readable
and capped, bulk-selects only searched documents, and preserves the stacked
mobile drawer layout.
"""

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_CSS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "css" / "bootstrap.min.css"
CHATS_CSS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "css" / "chats.css"
CHAT_DOCUMENTS_JS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-documents.js"
CHAT_SEARCHABLE_SELECT_JS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-searchable-select.js"
CHAT_TOAST_JS_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-toast.js"

DESKTOP_VIEWPORT = {"width": 1024, "height": 768}
MOBILE_VIEWPORT = {"width": 430, "height": 932}


def _build_dropdown_items(prefix, count):
    """Build static dropdown items for layout-only browser fixtures."""
    return "\n".join(
        f'<button type="button" class="dropdown-item" data-search-label="{prefix} item {index}">{prefix} item {index}</button>'
        for index in range(1, count + 1)
    )


def _load_search_panel_fixture(page):
    """Render the grounded-search filter strip with production CSS."""
    bootstrap_css = BOOTSTRAP_CSS_PATH.read_text(encoding="utf-8")
    chats_css = CHATS_CSS_PATH.read_text(encoding="utf-8")
    scope_items = _build_dropdown_items("Workspace", 16)
    tags_items = _build_dropdown_items("Classification", 16)
    document_items = _build_dropdown_items("Very long document title for filtering", 24)

    page.set_content(
        f"""
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Chat Search Panel Layout Regression</title>
    <style>{bootstrap_css}</style>
    <style>{chats_css}</style>
    <style>
        body {{
            margin: 0;
        }}

        .layout-frame {{
            margin: 0 auto;
            max-width: 1000px;
            width: 100%;
        }}
    </style>
</head>
<body>
    <div class="layout-frame">
        <div id="search-documents-container" class="chat-search-panel card p-0 mb-2 offcanvas-lg offcanvas-end" style="display: block; border-radius: 0.5rem;">
            <div class="offcanvas-header chat-search-panel-mobile-header">
                <div>
                    <h5 class="offcanvas-title" id="searchDocumentsDrawerLabel">Grounded Search</h5>
                    <p class="mb-0 text-muted small">Choose scope, tags, and documents.</p>
                </div>
            </div>
            <div class="offcanvas-body p-2">
                <div class="chat-search-panel-grid">
                    <div class="flex-shrink-0 chat-search-panel-field chat-search-panel-field-narrow">
                        <label class="form-label mb-1 small text-muted" for="document-action-select">Action</label>
                        <select class="form-select form-select-sm" id="document-action-select">
                            <option value="none">Search</option>
                            <option value="analyze">Analyze</option>
                            <option value="comparison">Compare</option>
                        </select>
                    </div>
                    <div class="flex-shrink-0 chat-search-panel-field chat-search-panel-field-narrow" data-chat-document-picker-field="scope">
                        <label class="form-label mb-1 small text-muted">Scope</label>
                        <div class="dropdown" id="scope-dropdown">
                            <button class="form-select form-select-sm d-flex justify-content-between align-items-center" type="button" id="scope-dropdown-button">
                                <span class="selected-scope-text text-truncate">All</span>
                            </button>
                            <div class="dropdown-menu p-2" id="scope-dropdown-menu">
                                <div class="chat-dropdown-search mb-2">
                                    <input type="text" class="form-control form-control-sm" placeholder="Search workspaces..." id="scope-search-input" />
                                </div>
                                <div class="dropdown-items-container" id="scope-dropdown-items">
                                    {scope_items}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="flex-shrink-0 chat-search-panel-field chat-search-panel-field-narrow" data-chat-document-picker-field="tags">
                        <label class="form-label mb-1 small text-muted">Tags</label>
                        <div class="dropdown" id="tags-dropdown">
                            <button class="form-select form-select-sm d-flex justify-content-between align-items-center" type="button" id="tags-dropdown-button">
                                <span class="chat-search-dropdown-button-content">
                                    <span class="selected-tags-text text-truncate">All Tags</span>
                                </span>
                            </button>
                            <div class="dropdown-menu p-2" id="tags-dropdown-menu">
                                <div class="chat-dropdown-search mb-2">
                                    <input type="text" class="form-control form-control-sm" placeholder="Search tags..." id="tags-search-input" />
                                </div>
                                <div class="dropdown-items-container" id="tags-dropdown-items">
                                    {tags_items}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="flex-grow-1 chat-search-panel-field chat-search-panel-field-wide" data-chat-document-picker-field="document">
                        <label for="document-select" class="form-label mb-1 small text-muted">Document</label>
                        <div class="dropdown" id="document-dropdown">
                            <button class="form-select form-select-sm d-flex justify-content-between align-items-center" type="button" id="document-dropdown-button">
                                <span class="selected-document-text">All Documents</span>
                            </button>
                            <div class="dropdown-menu p-2" id="document-dropdown-menu">
                                <div class="document-search-container mb-2">
                                    <input type="text" class="form-control form-control-sm" placeholder="Search documents..." id="document-search-input" />
                                </div>
                                <div class="dropdown-items-container" id="document-dropdown-items">
                                    <button type="button" class="dropdown-item" data-search-role="action">All Documents</button>
                                    <button type="button" class="dropdown-item" id="document-filtered-item" data-search-label="Needle document">Needle document</button>
                                    {document_items}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div id="document-comparison-summary-bar" class="chat-search-panel-comparison-row d-none">
                        <div class="border rounded-3 px-2 py-2 bg-body-tertiary d-flex flex-wrap align-items-center gap-2">
                            <div class="small text-uppercase text-muted fw-semibold me-1">Compare</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
""".strip()
    )


def _read_layout_metrics(page):
    return page.evaluate(
        """
        () => {
            const grid = document.querySelector('.chat-search-panel-grid');
            const actionField = document.querySelector('#document-action-select').closest('.chat-search-panel-field');
            const scopeField = document.querySelector('[data-chat-document-picker-field="scope"]');
            const tagsField = document.querySelector('[data-chat-document-picker-field="tags"]');
            const documentField = document.querySelector('[data-chat-document-picker-field="document"]');
            const documentButton = document.querySelector('#document-dropdown-button');

            const gridRect = grid.getBoundingClientRect();
            const actionRect = actionField.getBoundingClientRect();
            const scopeRect = scopeField.getBoundingClientRect();
            const tagsRect = tagsField.getBoundingClientRect();
            const documentRect = documentField.getBoundingClientRect();
            const documentButtonRect = documentButton.getBoundingClientRect();

            return {
                actionTop: actionRect.top,
                actionWidth: actionRect.width,
                scopeTop: scopeRect.top,
                scopeWidth: scopeRect.width,
                tagsTop: tagsRect.top,
                tagsBottom: tagsRect.bottom,
                tagsWidth: tagsRect.width,
                documentTop: documentRect.top,
                documentRight: documentRect.right,
                documentWidth: documentRect.width,
                documentButtonWidth: documentButtonRect.width,
                gridLeft: gridRect.left,
                gridRight: gridRect.right,
                gridWidth: gridRect.width,
                bodyScrollWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
            };
        }
        """
    )


@pytest.mark.ui
@pytest.mark.parametrize("action_value", ["none", "analyze"])
def test_search_and_analyze_document_picker_stays_on_desktop_filter_row(page, action_value):
    """Validate Search and Analyze keep the Document picker on the first desktop row."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    _load_search_panel_fixture(page)
    page.select_option("#document-action-select", action_value)

    metrics = _read_layout_metrics(page)

    assert abs(metrics["documentTop"] - metrics["tagsTop"]) <= 2, (
        f"Expected Document picker to share the filter row for {action_value}, got {metrics}"
    )
    assert abs(metrics["documentRight"] - metrics["gridRight"]) <= 2, (
        f"Expected Document picker to reach the right edge for {action_value}, got {metrics}"
    )
    assert metrics["documentButtonWidth"] >= metrics["documentWidth"] - 2, (
        f"Expected Document button to fill its field for {action_value}, got {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1, (
        f"Expected no page-level horizontal overflow for {action_value}, got {metrics}"
    )
    assert metrics["actionWidth"] <= 150, (
        f"Expected Action control to stay compact for {action_value}, got {metrics}"
    )
    assert metrics["scopeWidth"] <= 160, (
        f"Expected Scope control to stay compact for {action_value}, got {metrics}"
    )


@pytest.mark.ui
def test_search_panel_open_dropdowns_are_wider_capped_and_filterable(page):
    """Validate opened menus are readable, capped, and document items can be hidden by search."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    _load_search_panel_fixture(page)

    metrics = page.evaluate(
        """
        () => {
            const scopeField = document.querySelector('[data-chat-document-picker-field="scope"]');
            const tagsField = document.querySelector('[data-chat-document-picker-field="tags"]');
            const documentField = document.querySelector('[data-chat-document-picker-field="document"]');
            const scopeMenu = document.querySelector('#scope-dropdown-menu');
            const tagsMenu = document.querySelector('#tags-dropdown-menu');
            const documentMenu = document.querySelector('#document-dropdown-menu');
            const scopeItems = document.querySelector('#scope-dropdown-items');
            const tagsItems = document.querySelector('#tags-dropdown-items');
            const documentItems = document.querySelector('#document-dropdown-items');
            const filteredDocumentItem = document.querySelector('#document-filtered-item');

            [scopeMenu, tagsMenu, documentMenu].forEach(menu => {
                menu.classList.add('show');
                menu.style.display = 'block';
            });
            filteredDocumentItem.classList.add('d-none');

            const scopeMenuRect = scopeMenu.getBoundingClientRect();
            const tagsMenuRect = tagsMenu.getBoundingClientRect();
            const documentMenuRect = documentMenu.getBoundingClientRect();

            return {
                scopeFieldWidth: scopeField.getBoundingClientRect().width,
                tagsFieldWidth: tagsField.getBoundingClientRect().width,
                documentFieldWidth: documentField.getBoundingClientRect().width,
                scopeMenuWidth: scopeMenuRect.width,
                tagsMenuWidth: tagsMenuRect.width,
                documentMenuWidth: documentMenuRect.width,
                scopeItemsHeight: scopeItems.getBoundingClientRect().height,
                tagsItemsHeight: tagsItems.getBoundingClientRect().height,
                documentItemsHeight: documentItems.getBoundingClientRect().height,
                filteredDocumentDisplay: getComputedStyle(filteredDocumentItem).display,
                bodyScrollWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
            };
        }
        """
    )

    assert metrics["scopeMenuWidth"] > metrics["scopeFieldWidth"], (
        f"Expected Scope menu to open wider than its compact control, got {metrics}"
    )
    assert metrics["tagsMenuWidth"] > metrics["tagsFieldWidth"], (
        f"Expected Tags menu to open wider than its compact control, got {metrics}"
    )
    assert metrics["documentMenuWidth"] >= min(metrics["documentFieldWidth"], 512), (
        f"Expected Document menu to provide readable width, got {metrics}"
    )
    assert metrics["scopeItemsHeight"] <= 320, (
        f"Expected Scope menu items to be capped, got {metrics}"
    )
    assert metrics["tagsItemsHeight"] <= 320, (
        f"Expected Tags menu items to be capped, got {metrics}"
    )
    assert metrics["documentItemsHeight"] <= 320, (
        f"Expected Document menu items to be capped, got {metrics}"
    )
    assert metrics["filteredDocumentDisplay"] == "none", (
        f"Expected document search hidden state to hide items, got {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1, (
        f"Expected opened menus to avoid page-level horizontal overflow, got {metrics}"
    )


@pytest.mark.ui
def test_search_panel_document_picker_remains_stacked_on_mobile(page):
    """Validate the smaller mobile drawer still stacks controls without horizontal overflow."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    _load_search_panel_fixture(page)

    metrics = _read_layout_metrics(page)

    assert metrics["documentTop"] > metrics["tagsBottom"], (
        f"Expected Document picker to stack below Tags on mobile, got {metrics}"
    )
    assert metrics["documentRight"] <= metrics["gridRight"] + 1, (
        f"Expected Document picker to stay inside the mobile drawer, got {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1, (
        f"Expected no mobile horizontal overflow, got {metrics}"
    )


def _document_item(document_id, label, search_label):
    return f"""
    <button type="button" class="dropdown-item d-flex align-items-center" data-document-id="{document_id}" data-search-role="item" data-search-label="{search_label}">
        <input type="checkbox" class="form-check-input me-2 doc-checkbox" />
        <span>{label}</span>
    </button>
    """.strip()


def _load_document_bulk_selection_fixture(page):
    """Render a minimal real-module document picker fixture."""
    document_items = "\n".join(
        [
            _document_item("doc-alpha", "Quarterly migration plan", "Quarterly migration plan Personal"),
            _document_item("doc-beta", "Incident response guide", "Incident response guide Personal"),
            _document_item("doc-gamma", "Quarterly roadmap notes", "Quarterly roadmap notes Personal"),
        ]
    )
    fixture_html = f"""
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Document Search Bulk Selection Regression</title>
</head>
<body>
    <button type="button" id="search-documents-btn">Documents</button>
    <div id="search-documents-container">
        <select id="document-action-select">
            <option value="none">Search</option>
            <option value="analyze">Analyze</option>
            <option value="comparison">Compare</option>
        </select>
        <div class="dropdown" id="document-dropdown">
            <button type="button" id="document-dropdown-button">
                <span class="selected-document-text">All Documents</span>
            </button>
            <div class="dropdown-menu" id="document-dropdown-menu">
                <div class="document-search-container">
                    <input type="text" id="document-search-input" />
                </div>
                <div id="document-dropdown-items">
                    <button type="button" class="dropdown-item" data-document-id="" data-search-role="action">All Documents</button>
                    {document_items}
                </div>
            </div>
        </div>
        <select id="document-select" multiple>
            <option value="">All Documents</option>
            <option value="doc-alpha">Quarterly migration plan</option>
            <option value="doc-beta">Incident response guide</option>
            <option value="doc-gamma">Quarterly roadmap notes</option>
        </select>
        <select id="doc-scope-select" multiple></select>
        <select id="chat-tags-filter" multiple></select>
    </div>
</body>
</html>
""".strip()

    def route_js_file(file_path):
        return lambda route: route.fulfill(path=str(file_path), content_type="application/javascript")

    page.route("http://simplechat.test/chat-documents.js", route_js_file(CHAT_DOCUMENTS_JS_PATH))
    page.route("http://simplechat.test/chat-searchable-select.js", route_js_file(CHAT_SEARCHABLE_SELECT_JS_PATH))
    page.route("http://simplechat.test/chat-toast.js", route_js_file(CHAT_TOAST_JS_PATH))
    page.route(
        "http://simplechat.test/document-bulk-selection-fixture",
        lambda route: route.fulfill(body=fixture_html, content_type="text/html"),
    )

    page.goto("http://simplechat.test/document-bulk-selection-fixture")
    module_uri = json.dumps("http://simplechat.test/chat-documents.js")

    page.add_script_tag(
        type="module",
        content=f"""
            window.userGroups = [];
            window.userVisiblePublicWorkspaces = [];
            window.bootstrap = {{
                Dropdown: class {{
                    constructor() {{}}
                    static getInstance() {{ return null; }}
                    static getOrCreateInstance() {{ return {{ hide() {{}}, update() {{}} }}; }}
                }},
                Offcanvas: {{
                    getOrCreateInstance() {{ return {{ hide() {{}}, show() {{}} }}; }}
                }}
            }};
            try {{
                await import({module_uri});
                window.__chatDocumentsModuleReady = true;
            }} catch (error) {{
                window.__chatDocumentsModuleError = String(error && (error.stack || error.message || error));
            }}
        """,
    )
    page.wait_for_function("window.__chatDocumentsModuleReady === true || Boolean(window.__chatDocumentsModuleError)")
    module_error = page.evaluate("window.__chatDocumentsModuleError || null")
    assert module_error is None, module_error


def _reset_document_bulk_selection_fixture(page):
    page.evaluate(
        """
        () => {
            document.querySelectorAll('#document-select option').forEach(option => { option.selected = false; });
            document.querySelectorAll('#document-dropdown-items .doc-checkbox').forEach(checkbox => { checkbox.checked = false; });

            const searchInput = document.querySelector('#document-search-input');
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));

            document.querySelector('#document-action-select').dispatchEvent(new Event('change', { bubbles: true }));
        }
        """
    )


def _selected_document_ids(page):
    return page.evaluate(
        """
        () => Array.from(document.querySelector('#document-select').selectedOptions)
            .map(option => option.value)
            .filter(Boolean)
        """
    )


@pytest.mark.ui
@pytest.mark.parametrize("action_value", ["none", "analyze", "comparison"])
def test_document_picker_bulk_action_selects_only_searched_documents(page, action_value):
    """Validate the top document action only selects visible searched documents."""
    _load_document_bulk_selection_fixture(page)
    page.select_option("#document-action-select", action_value)
    page.fill("#document-search-input", "Quarterly")

    action_item = page.locator('#document-dropdown-items .dropdown-item[data-search-role="action"]')

    assert action_item.inner_text() == "Select All Searched"
    action_item.click()

    assert _selected_document_ids(page) == ["doc-alpha", "doc-gamma"]
    assert action_item.inner_text() == "Clear Searched"

    _reset_document_bulk_selection_fixture(page)


@pytest.mark.ui
def test_document_picker_bulk_action_disables_when_search_has_no_matches(page):
    """Validate a no-match document search cannot bulk-select hidden documents."""
    _load_document_bulk_selection_fixture(page)
    page.select_option("#document-action-select", "analyze")
    page.fill("#document-search-input", "not present")

    metrics = page.evaluate(
        """
        () => {
            const actionItem = document.querySelector('#document-dropdown-items .dropdown-item[data-search-role="action"]');
            return {
                disabled: actionItem.disabled,
                label: actionItem.textContent,
                selectedDocumentIds: Array.from(document.querySelector('#document-select').selectedOptions)
                    .map(option => option.value)
                    .filter(Boolean),
            };
        }
        """
    )

    assert metrics == {
        "disabled": True,
        "label": "No Matching Documents",
        "selectedDocumentIds": [],
    }