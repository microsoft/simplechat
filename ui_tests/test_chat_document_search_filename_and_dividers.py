# test_chat_document_search_filename_and_dividers.py
"""
UI test for chat document search file-name matching and dropdown divider cleanup.

Version: 0.250.210
Implemented in: 0.250.210

This test ensures the chat grounded-search document picker renders the file name as
muted secondary text when it differs from the title, matches typed text against both
the title and the file name (including multi-word queries where `_`, `-`, and `.` act
as word breaks), and leaves no orphaned section separator lines behind when filtering
removes the leading workspace sections.

Refs: https://github.com/microsoft/simplechat/issues/1256
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

DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
MOBILE_VIEWPORT = {"width": 430, "height": 932}

PERSONAL_DOCUMENTS = [
    {"id": "doc-personal-notes", "file_name": "Budget_Notes.docx", "tags": []},
]
GROUP_DOCUMENTS = [
    {
        "id": "doc-group-charter",
        "title": "Alpha Charter",
        "file_name": "Alpha_Charter.pdf",
        "group_id": "group-1",
        "tags": [],
    },
]
PUBLIC_DOCUMENTS = [
    {
        "id": "doc-public-fiscal",
        "title": "Fiscal Overview",
        "file_name": "Quarterly_Report_200_final.pdf",
        "public_workspace_id": "ws-1",
        "tags": [],
    },
]


def _load_document_picker_fixture(page):
    """Render the real chat document picker with production CSS and modules."""
    bootstrap_css = BOOTSTRAP_CSS_PATH.read_text(encoding="utf-8")
    chats_css = CHATS_CSS_PATH.read_text(encoding="utf-8")

    fixture_html = f"""
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Chat Document Search Regression</title>
    <style>{bootstrap_css}</style>
    <style>{chats_css}</style>
    <style>
        body {{ margin: 0; padding: 16px; }}
        .fixture-frame {{ max-width: 520px; }}
    </style>
</head>
<body>
    <div class="fixture-frame">
        <button type="button" id="search-documents-btn">Documents</button>
        <div id="search-documents-container" class="chat-search-panel card p-0 mb-2" style="display: block;">
            <div class="chat-search-panel-grid">
                <div class="chat-search-panel-field chat-search-panel-field-narrow">
                    <select class="form-select form-select-sm" id="document-action-select">
                        <option value="none">Search</option>
                        <option value="analyze">Analyze</option>
                        <option value="comparison">Compare</option>
                    </select>
                </div>
                <div class="chat-search-panel-field chat-search-panel-field-wide" data-chat-document-picker-field="document">
                    <div class="dropdown" id="document-dropdown">
                        <button class="form-select form-select-sm d-flex justify-content-between align-items-center" type="button" id="document-dropdown-button">
                            <span class="selected-document-text">All Documents</span>
                        </button>
                        <div class="dropdown-menu p-2 chat-search-filter-menu" id="document-dropdown-menu">
                            <div class="document-search-container mb-2">
                                <input type="text" class="form-control form-control-sm" placeholder="Search documents..." id="document-search-input" />
                            </div>
                            <div class="dropdown-items-container" id="document-dropdown-items"></div>
                        </div>
                        <select class="d-none" id="document-select" multiple></select>
                    </div>
                </div>
            </div>
        </div>
        <select class="d-none" id="doc-scope-select" multiple></select>
        <select class="d-none" id="chat-tags-filter" multiple></select>
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
        "http://simplechat.test/document-search-fixture",
        lambda route: route.fulfill(body=fixture_html, content_type="text/html"),
    )

    console_errors = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    page.goto("http://simplechat.test/document-search-fixture")

    module_uri = json.dumps("http://simplechat.test/chat-documents.js")
    personal_json = json.dumps(PERSONAL_DOCUMENTS)
    group_json = json.dumps(GROUP_DOCUMENTS)
    public_json = json.dumps(PUBLIC_DOCUMENTS)

    page.add_script_tag(
        type="module",
        content=f"""
            window.userGroups = [{{ id: 'group-1', name: 'Alpha' }}];
            window.userVisiblePublicWorkspaces = [{{ id: 'ws-1', name: 'Beta' }}];
            window.bootstrap = {{
                Dropdown: class {{
                    constructor() {{}}
                    static getInstance() {{ return null; }}
                    static getOrCreateInstance() {{ return {{ hide() {{}}, show() {{}}, update() {{}} }}; }}
                }},
                Offcanvas: {{
                    getOrCreateInstance() {{ return {{ hide() {{}}, show() {{}} }}; }}
                }}
            }};

            const documentsByEndpoint = {{
                '/api/documents': {personal_json},
                '/api/group_documents': {group_json},
                '/api/public_workspace_documents': {public_json},
            }};

            window.fetch = (requestUrl) => {{
                const requested = String(requestUrl);
                const endpoint = Object.keys(documentsByEndpoint).find(key => requested.startsWith(key));
                const payload = {{ documents: endpoint ? documentsByEndpoint[endpoint] : [] }};
                return Promise.resolve({{
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve(payload),
                }});
            }};

            try {{
                const chatDocuments = await import({module_uri});
                await chatDocuments.loadAllDocs();

                const menu = document.getElementById('document-dropdown-menu');
                menu.classList.add('show');
                menu.style.display = 'block';

                window.__chatDocumentsModuleReady = true;
            }} catch (error) {{
                window.__chatDocumentsModuleError = String(error && (error.stack || error.message || error));
            }}
        """,
    )

    page.wait_for_function("window.__chatDocumentsModuleReady === true || Boolean(window.__chatDocumentsModuleError)")
    module_error = page.evaluate("window.__chatDocumentsModuleError || null")
    assert module_error is None, module_error

    page.wait_for_selector('#document-dropdown-items .dropdown-item[data-document-id="doc-public-fiscal"]')

    return console_errors


def _read_visible_rows(page):
    """Return the visible dropdown structure as an ordered list of markers."""
    return page.evaluate(
        """
        () => Array.from(document.querySelectorAll('#document-dropdown-items > *'))
            .filter(element => element.offsetParent !== null || element.getClientRects().length > 0)
            .map(element => {
                if (element.classList.contains('dropdown-divider')) { return '---'; }
                if (element.classList.contains('dropdown-header')) { return '#' + element.textContent.trim(); }
                const title = element.querySelector('.chat-document-option-title');
                return title ? title.textContent.trim() : element.textContent.trim();
            })
        """
    )


def _search_documents(page, term):
    page.fill("#document-search-input", term)
    page.wait_for_timeout(50)
    return _read_visible_rows(page)


@pytest.mark.ui
def test_document_rows_show_file_name_only_when_it_differs_from_the_title(page):
    """Validate the muted file-name line renders only when it adds information."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    console_errors = _load_document_picker_fixture(page)

    metrics = page.evaluate(
        """
        () => {
            const readRow = documentId => {
                const row = document.querySelector(`#document-dropdown-items .dropdown-item[data-document-id="${documentId}"]`);
                const title = row.querySelector('.chat-document-option-title');
                const fileName = row.querySelector('.chat-document-option-filename');
                const titleRect = title.getBoundingClientRect();
                const menuRect = document.getElementById('document-dropdown-menu').getBoundingClientRect();
                return {
                    title: title.textContent.trim(),
                    fileName: fileName ? fileName.textContent.trim() : null,
                    fileNameVisible: Boolean(fileName && fileName.getClientRects().length > 0),
                    fileNameBelowTitle: fileName ? fileName.getBoundingClientRect().top >= titleRect.bottom - 1 : null,
                    fileNameFontSize: fileName ? parseFloat(getComputedStyle(fileName).fontSize) : null,
                    titleFontSize: parseFloat(getComputedStyle(title).fontSize),
                    tooltip: row.getAttribute('title'),
                    rowRight: row.getBoundingClientRect().right,
                    menuRight: menuRect.right,
                };
            };

            return {
                titled: readRow('doc-public-fiscal'),
                untitled: readRow('doc-personal-notes'),
            };
        }
        """
    )

    titled = metrics["titled"]
    untitled = metrics["untitled"]

    assert titled["title"] == "Fiscal Overview", f"Unexpected title row, got {titled}"
    assert titled["fileName"] == "Quarterly_Report_200_final.pdf", f"Expected the file name line, got {titled}"
    assert titled["fileNameVisible"], f"Expected the file name line to be visible, got {titled}"
    assert titled["fileNameBelowTitle"], f"Expected the file name to stack under the title, got {titled}"
    assert titled["fileNameFontSize"] < titled["titleFontSize"], (
        f"Expected the file name to render smaller than the title, got {titled}"
    )
    assert titled["tooltip"] == "Fiscal Overview\nQuarterly_Report_200_final.pdf", (
        f"Expected the tooltip to carry both lines, got {titled}"
    )
    assert titled["rowRight"] <= titled["menuRight"] + 1, f"Expected the row to stay inside the menu, got {titled}"

    assert untitled["title"] == "Budget_Notes.docx", f"Unexpected untitled row, got {untitled}"
    assert untitled["fileName"] is None, (
        f"Expected no duplicate file name line when the title is the file name, got {untitled}"
    )
    assert untitled["tooltip"] == "Budget_Notes.docx", f"Expected a single-line tooltip, got {untitled}"

    assert not console_errors, f"Unexpected console errors: {console_errors}"


@pytest.mark.ui
def test_document_search_matches_file_names_and_titles(page):
    """Validate searching matches file-name fragments, multi-word queries, and titles."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    console_errors = _load_document_picker_fixture(page)

    assert _search_documents(page, "200") == [
        "Select All Searched",
        "#[Public] Beta",
        "Fiscal Overview",
    ], "Expected a mid-file-name fragment to surface the document"

    assert _search_documents(page, "report 200") == [
        "Select All Searched",
        "#[Public] Beta",
        "Fiscal Overview",
    ], "Expected a multi-word query to match across file-name separators"

    assert _search_documents(page, "Quarterly_Report") == [
        "Select All Searched",
        "#[Public] Beta",
        "Fiscal Overview",
    ], "Expected the literal file name to match"

    assert _search_documents(page, "fiscal") == [
        "Select All Searched",
        "#[Public] Beta",
        "Fiscal Overview",
    ], "Expected title matching to keep working"

    assert _search_documents(page, "charter") == [
        "Select All Searched",
        "#[Group] Alpha",
        "Alpha Charter",
    ], "Expected a middle-section document to match on its title"

    assert _search_documents(page, "budget") == [
        "Select All Searched",
        "#Personal",
        "Budget_Notes.docx",
    ], "Expected the first-section document to match on its file name"

    assert not console_errors, f"Unexpected console errors: {console_errors}"


@pytest.mark.ui
def test_filtered_document_dropdown_has_no_orphaned_separator_lines(page):
    """Validate filtering never leaves stray or stacked section separator lines."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    console_errors = _load_document_picker_fixture(page)

    unfiltered = _read_visible_rows(page)
    assert unfiltered == [
        "All Documents",
        "#Personal",
        "Budget_Notes.docx",
        "---",
        "#[Group] Alpha",
        "Alpha Charter",
        "---",
        "#[Public] Beta",
        "Fiscal Overview",
    ], f"Unexpected unfiltered dropdown structure, got {unfiltered}"

    for term in ["200", "charter", "budget", "zzzz"]:
        rows = _search_documents(page, term)
        assert "---" not in rows, f'Orphaned separator line survived filtering on "{term}": {rows}'

    page.fill("#document-search-input", "")
    page.wait_for_timeout(50)
    restored = _read_visible_rows(page)
    assert restored == unfiltered, f"Expected clearing the search to restore the structure, got {restored}"

    assert not console_errors, f"Unexpected console errors: {console_errors}"


@pytest.mark.ui
def test_document_picker_search_behaves_in_the_mobile_drawer(page):
    """Validate the mobile drawer keeps rows contained while filtering cleanly."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    console_errors = _load_document_picker_fixture(page)

    rows = _search_documents(page, "200")
    assert rows == [
        "Select All Searched",
        "#[Public] Beta",
        "Fiscal Overview",
    ], f"Unexpected mobile filter result, got {rows}"

    metrics = page.evaluate(
        """
        () => {
            const row = document.querySelector('#document-dropdown-items .dropdown-item[data-document-id="doc-public-fiscal"]');
            const menu = document.getElementById('document-dropdown-menu');
            return {
                rowRight: row.getBoundingClientRect().right,
                menuRight: menu.getBoundingClientRect().right,
                bodyScrollWidth: document.body.scrollWidth,
                viewportWidth: window.innerWidth,
            };
        }
        """
    )

    assert metrics["rowRight"] <= metrics["menuRight"] + 1, (
        f"Expected the document row to stay inside the mobile menu, got {metrics}"
    )
    assert metrics["bodyScrollWidth"] <= metrics["viewportWidth"] + 1, (
        f"Expected no mobile horizontal overflow, got {metrics}"
    )

    assert not console_errors, f"Unexpected console errors: {console_errors}"
