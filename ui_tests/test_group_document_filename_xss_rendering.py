# test_group_document_filename_xss_rendering.py
"""
Browser regressions for group document filename rendering.
Version: 0.261.029
Implemented in: 0.261.029

Run the real template renderers, access/processing checks, fetch/refresh/polling
paths, local sharing asset, Bootstrap, and sharing modal in an isolated browser.
Only unrelated metadata, selection, and generated-artifact UI helpers are stubbed.
Every request is intercepted; no Azure resource, login, or live document is used.
"""

from pathlib import Path
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
TEMPLATE = APP_ROOT / "templates" / "group_workspaces.html"
OWNER_GROUP = "owner-group"
DOCUMENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VIEWS = ("list", "cards", "folder-list", "folder-cards")
INLINE_PAYLOAD = "x');window.__filenameXss += 1//a.txt"
ATTRIBUTE_PAYLOAD = 'x" onmouseover="window.__filenameXss += 1" data-tail="a.txt'
BENIGN_FILENAME = 'O\'Reilly "report" & <draft> \\ &quot; \u00e9\u8cc7\u6599.txt'
HTML_FILENAME = '<img src=x onerror="window.__filenameXss += 1">.txt'

FUNCTION_NAMES = (
    "escapeHtml",
    "escapeGroupHtml",
    "truncateGroupDocumentText",
    "getGroupDocumentProcessingState",
    "getGroupDocumentIcon",
    "getGroupDocumentAccess",
    "getGroupDocumentSummaryText",
    "isPendingGeneratedArtifactDocument",
    "createGroupDocumentCard",
    "renderGroupDocumentCards",
    "renderGroupDocumentRow",
    "renderGroupDocumentsEmptyState",
    "renderGroupDocumentsErrorState",
    "renderCurrentGroupDocuments",
    "fetchGroupDocuments",
    "refreshCurrentGroupDocumentView",
    "pollGroupDocumentStatus",
    "buildGroupBreadcrumbHtml",
    "wireGroupBackButton",
    "buildGroupFolderDocumentsTable",
    "buildGroupFolderDocumentsCardsHtml",
    "renderGroupFolderDocumentCards",
    "renderGroupFolderContents",
    "renderGroupFolderPagination",
    "wireGroupFolderGeneratedArtifactApproveButtons",
)

HARNESS_STATE = """
const groupDocumentsTableBody = document.querySelector('#group-documents-table tbody');
const groupDocumentsCardView = document.getElementById('group-documents-card-view');
const groupDocsPaginationContainer = null;
const groupSelectedDocuments = new Set();
const groupActivePolls = new Set();
const groupWorkspaceTags = [];
let activeGroupId = 'owner-group';
let userRoleInActiveGroup = 'Owner';
let groupSelectionMode = false;
let groupCurrentView = 'list';
let groupCurrentFolder = null;
let groupCurrentFolderType = null;
let groupFolderCurrentPage = 1;
let groupFolderPageSize = 20;
let groupFolderSortBy = '_ts';
let groupFolderSortOrder = 'desc';
let groupFolderSearchTerm = '';
let groupDocsCurrentPage = 1;
let groupDocsPageSize = 20;
let groupDocsSortBy = '_ts';
let groupDocsSortOrder = 'desc';
let groupDocsSearchTerm = '';
let groupDocsClassificationFilter = '';
let groupDocsAuthorFilter = '';
let groupDocsKeywordsFilter = '';
let groupDocsAbstractFilter = '';
let groupDocsTagsFilter = '';
let groupLastFetchedDocs = [];
let groupLastFetchedDocsError = null;
let groupHasFetchedDocuments = false;
let groupFileDownloadsEnabled = false;
let groupFileDownloadEnabledGroupIds = [];

const getGroupDocumentMetaPills = () => '';
const getGroupClassificationBadge = () => '';
const getGroupDocumentCitationTooltip = () => 'Standard citations';
const getGroupDocumentSyncBadgeHtml = () => '';
const getGroupDocumentSyncDetailsHtml = () => '';
const getGroupDocumentReprocessDropdownItems = () => '';
const renderGroupTagBadges = () => '';
const supportsGroupExtractionModeChange = () => false;
const canDownloadGroupDocuments = () => false;
const prependGroupGeneratedArtifactActionButtons = () => {};
const syncGroupSelectionModeUI = () => {};
const refreshGroupSelectionState = () => {};
const renderGroupDocsPaginationControls = () => {};

window.__filenameXss = 0;
window.__pollCallbacks = new Map();
window.setInterval = (callback) => {
    const id = Symbol('poll');
    window.__pollCallbacks.set(id, callback);
    return id;
};
window.clearInterval = (id) => window.__pollCallbacks.delete(id);
"""


def _template_function(source, name):
    """Extract a complete top-level function using the template's indentation."""
    start = re.search(rf"^  (?:async )?function {re.escape(name)}\(", source, re.MULTILINE)
    if start is None:
        raise ValueError(f"Group template function not found: {name}")
    end = source.index("\n  }", start.end()) + len("\n  }")
    return source[start.start():end]


def _document(filename=BENIGN_FILENAME, **changes):
    document = {
        "id": DOCUMENT_ID,
        "group_id": OWNER_GROUP,
        "file_name": filename,
        "title": "",
        "status": "Processing Complete",
        "percentage_complete": 100,
        "shared_group_ids": ["shared-one", "shared-two"],
        "tags": [],
    }
    document.update(changes)
    return document


@pytest.fixture(scope="module")
def group_render_sources():
    source = TEMPLATE.read_text(encoding="utf-8")
    modal_start = source.index("<!-- Group Share Document Modal -->")
    modal_end = source.index("<!-- Group Shared Document Approval Modal -->", modal_start)
    modal = source[modal_start:modal_end]
    functions = "\n".join(_template_function(source, name) for name in FUNCTION_NAMES)
    return modal, f"{HARNESS_STATE}\n{functions}"


@pytest.fixture
def group_page(page, group_render_sources):
    modal, script = group_render_sources
    state = {"documents": [], "shared_requests": [], "unexpected_requests": [], "errors": []}
    page.on("pageerror", lambda error: state["errors"].append(str(error)))
    page.emulate_media(reduced_motion="reduce")

    def handle_request(route):
        path = urlsplit(route.request.url).path
        if path == "/":
            route.fulfill(
                content_type="text/html",
                body=f"""<!doctype html>
                    <html lang="en"><body>
                        <main class="container-fluid">
                            <div id="group-documents-list-view">
                                <table id="group-documents-table"><tbody></tbody></table>
                            </div>
                            <div id="group-documents-card-view" class="row"></div>
                            <div id="group-documents-grid-view">
                                <div id="group-grid-controls-bar"></div>
                                <div id="group-tag-folders-container"></div>
                            </div>
                        </main>
                        {modal}
                    </body></html>""",
            )
        elif path == "/api/group_documents":
            route.fulfill(json={
                "documents": state["documents"],
                "page": 1,
                "page_size": 20,
                "total_count": len(state["documents"]),
            })
        elif path.startswith("/api/group_documents/") and path.endswith("/shared-groups"):
            state["shared_requests"].append(path.split("/")[3])
            route.fulfill(json={"shared_groups": []})
        elif path.startswith("/api/group_documents/"):
            document_id = path.split("/")[3]
            documents = [doc for doc in state["documents"] if doc["id"] == document_id]
            if not documents:
                raise AssertionError(f"Unexpected document request: {path}")
            route.fulfill(json=documents[0])
        else:
            state["unexpected_requests"].append(route.request.url)
            route.abort()

    page.route("**/*", handle_request)
    page.goto("https://simplechat.test/")
    page.add_style_tag(path=str(APP_ROOT / "static" / "css" / "bootstrap.min.css"))
    page.add_script_tag(path=str(APP_ROOT / "static" / "js" / "bootstrap" / "bootstrap.bundle.min.js"))
    page.add_script_tag(path=str(APP_ROOT / "static" / "js" / "workspace" / "group-documents-sharing.js"))
    page.add_script_tag(content=script)
    page.evaluate("initializeGroupSharing()")

    yield page, state

    assert state["errors"] == []
    assert state["unexpected_requests"] == []


def _render(group_page, view, documents, role="Owner", status="active"):
    page, state = group_page
    state["documents"] = documents
    page.evaluate(
        """({view, role, status}) => {
            userRoleInActiveGroup = role;
            window.currentGroupStatus = status;
            const folderView = view.startsWith('folder-');
            groupCurrentView = view === 'folder-list' ? 'grid'
                : view === 'folder-cards' ? 'folders-cards' : view;
            groupCurrentFolder = folderView ? '__untagged__' : null;
            groupCurrentFolderType = folderView ? 'tag' : null;
            document.getElementById('group-documents-list-view')
                .classList.toggle('d-none', view !== 'list');
            groupDocumentsCardView.classList.toggle('d-none', view !== 'cards');
            document.getElementById('group-documents-grid-view')
                .classList.toggle('d-none', !folderView);
            refreshCurrentGroupDocumentView();
        }""",
        {"view": view, "role": role, "status": status},
    )
    selectors = {
        "list": "#group-documents-table .document-row",
        "cards": "#group-documents-card-view .document-item-card",
        "folder-list": "#group-folder-docs-table tbody tr",
        "folder-cards": "#group-folder-documents-card-view .document-item-card",
    }
    rows = page.locator(selectors[view])
    expect(rows).to_have_count(len(documents))
    return rows


def _share_link(row):
    return row.locator("a.dropdown-item").filter(has_text=re.compile(r"^\s*Share"))


def _click_share(group_page, row, document):
    page, state = group_page
    previous_requests = len(state["shared_requests"])
    share = _share_link(row)
    expect(share.locator(".badge")).to_have_text(str(len(document["shared_group_ids"])))
    row.locator(".dropdown-toggle").click()
    with page.expect_response(f"**/api/group_documents/{document['id']}/shared-groups") as response:
        share.click()
    response.value.finished()
    expect(page.locator("#groupShareDocumentModal")).to_be_visible()
    marker = page.evaluate("window.__filenameXss")
    assert marker == 0, "The rendered Share control executed filename content."
    expect(page.locator("#groupShareDocumentName")).to_have_text(document.get("file_name") or "")
    inline_handler = share.get_attribute("onclick")
    assert inline_handler is None
    assert state["shared_requests"][previous_requests:] == [document["id"]]
    page.locator("#groupShareDocumentModal").get_by_role("button", name="Close", exact=True).last.click()
    expect(page.locator("#groupShareDocumentModal")).to_be_hidden()


@pytest.mark.ui
@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize(
    "filename",
    [INLINE_PAYLOAD, ATTRIBUTE_PAYLOAD, BENIGN_FILENAME, HTML_FILENAME],
    ids=["inline-payload", "attribute-payload", "literal-filename", "html-filename"],
)
def test_rendered_share_preserves_inert_filename(group_page, view, filename):
    document = _document(filename)
    rows = _render(group_page, view, [document])
    _click_share(group_page, rows.first, document)


@pytest.mark.ui
@pytest.mark.parametrize("view", ["cards", "folder-cards"])
@pytest.mark.parametrize("field", ["filename-heading", "filename-subtitle", "document-title"])
@pytest.mark.parametrize("width", [390, 1440], ids=["mobile", "desktop"])
def test_card_tooltips_remain_inert_for_ordinary_users(group_page, view, field, width):
    page, _ = group_page
    page.set_viewport_size({"width": width, "height": 900})
    document = _document(ATTRIBUTE_PAYLOAD)
    selector = ".card-title"
    if field == "filename-subtitle":
        document["title"] = "Document title"
        selector = ".document-item-card__subtitle"
    elif field == "document-title":
        document["file_name"] = "document.txt"
        document["title"] = ATTRIBUTE_PAYLOAD
    rows = _render(group_page, view, [document], role="User")
    expect(_share_link(rows.first)).to_have_count(0)
    text = rows.first.locator(selector)
    text.hover()
    marker = page.evaluate("window.__filenameXss")
    assert marker == 0, "Hovering the document text executed injected filename/title content."
    expect(text).to_have_attribute("title", ATTRIBUTE_PAYLOAD)
    expected_text = ATTRIBUTE_PAYLOAD
    if selector == ".card-title" and len(expected_text) > 60:
        expected_text = f"{expected_text[:60].rstrip()}\u2026"
    expect(text).to_have_text(expected_text)
    injected_handler = text.get_attribute("onmouseover")
    assert injected_handler is None


@pytest.mark.ui
@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize(
    "role,status,owner,processing,can_share",
    [
        ("Owner", "active", True, "complete", True),
        ("Admin", "active", True, "complete", True),
        ("DocumentManager", "active", True, "complete", True),
        ("User", "active", True, "complete", False),
        ("Owner", "upload_disabled", True, "complete", True),
        ("Owner", "locked", True, "complete", False),
        ("Owner", "inactive", True, "complete", False),
        ("Owner", "active", False, "complete", False),
        ("Owner", "active", True, "processing", False),
        ("Owner", "active", True, "error", False),
    ],
)
def test_share_preserves_role_ownership_and_status_gating(
    group_page, view, role, status, owner, processing, can_share
):
    document = _document()
    if not owner:
        document["group_id"] = "another-group"
        document["shared_group_ids"] = [f"{OWNER_GROUP},approved"]
    if processing != "complete":
        document["status"] = "Processing" if processing == "processing" else "Error"
        document["percentage_complete"] = 25
    rows = _render(group_page, view, [document], role=role, status=status)
    expect(_share_link(rows.first)).to_have_count(1 if can_share else 0)
    if can_share:
        _click_share(group_page, rows.first, document)


@pytest.mark.ui
def test_refresh_and_view_changes_rebind_each_document_once(group_page):
    page, state = group_page
    documents = [
        _document(INLINE_PAYLOAD),
        _document(BENIGN_FILENAME, id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff", shared_group_ids=[]),
    ]
    for view in VIEWS:
        rows = _render(group_page, view, documents)
        _click_share(group_page, rows.nth(0), documents[0])
        documents = list(reversed(documents))
        rows = _render(group_page, view, documents)
        _click_share(group_page, rows.nth(0), documents[0])
    assert len(state["shared_requests"]) == 8
    marker = page.evaluate("window.__filenameXss")
    assert marker == 0


@pytest.mark.ui
def test_polling_completion_binds_the_replacement_row(group_page):
    page, state = group_page
    processing = _document(INLINE_PAYLOAD, status="Processing", percentage_complete=25)
    rows = _render(group_page, "list", [processing])
    expect(_share_link(rows.first)).to_have_count(0)
    complete = _document(INLINE_PAYLOAD)
    state["documents"] = [complete]
    page.evaluate("() => window.__pollCallbacks.forEach(callback => callback())")
    expect(_share_link(rows.first)).to_have_count(1)
    _click_share(group_page, rows.first, complete)


@pytest.mark.ui
@pytest.mark.parametrize("view", VIEWS)
def test_empty_filename_keeps_existing_fallback(group_page, view):
    document = _document(None)
    rows = _render(group_page, view, [document])
    _click_share(group_page, rows.first, document)
