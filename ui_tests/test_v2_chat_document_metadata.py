# test_v2_chat_document_metadata.py
"""
Real-component chat document card regressions.
Version: 0.261.327
Implemented in: 0.261.327

Checks title, filename, source, file-family icons, complementary metadata and
inert text in desktop/mobile drawers. No historical hydration API is stubbed.
Uses the existing Azure Playwright or local Chromium connection fixtures.
"""

import pytest
from playwright.sync_api import expect

from test_v2_drawer_generated_files import (  # noqa: F401
    CONVERSATION, drawer_ui, editor_assets, editor_browser, connect_options, mount,
)

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width", [393, 1280])
def test_document_cards_show_names_file_types_and_workspace_sources(drawer_ui, width):
    page, api = drawer_ui
    page.set_viewport_size({"width": width, "height": 852})
    api.agent_documents = []
    documents = [
        {"document_id": "personal-guid", "title": "Azure hierarchy", "file_name": "Hierarchy.docx",
         "scope": {"type": "personal", "id": "ui-user", "name": "Pat Reader"}},
        {"document_id": "group-guid", "scope": {"type": "group", "id": "group-a"},
         "citation_ids": ["group-chunk"], "page_numbers": [2]},
        {"document_id": "public-guid", "title": "Annual figures", "file_name": "Figures.XLSX",
         "scope": {"type": "public", "id": "public-a"}},
        {"document_id": "missing-guid"},
        {"document_id": "same-guid", "title": "notes.txt", "file_name": "notes.txt"},
        {"document_id": "markup-guid", "title": '<img src=x onerror="window.__injected = true">',
         "file_name": "Long" + " filename" * 30 + ".pdf",
         "scope": {"type": "group", "id": "group-b", "name": "<b>Literal workspace</b>"}},
    ]
    mount(page, api, "ConversationDrawer", [], drawer="documents", used_documents=documents)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.stores.bootstrap.useBootstrapStore.setState((state) => ({data: {
            ...state.data, scope: {
                groups: [{id: 'group-a', name: 'Aircraft records'}],
                public_workspaces: [{id: 'public-a', name: 'Published research'}],
            },
        }}));
        H.stores.chat.useChatStore.setState((state) => ({metadata: {
            ...state.metadata, legacy_used_documents: [{
                document_id: 'group-guid', title: 'Aircraft registration',
                file_name: 'Elliott Hendricks.pdf', scope: {type: 'group', id: 'group-a'},
            }],
        }}));
    }""")
    rows = page.locator("[data-used-document]")
    expect(rows).to_have_count(6)
    for identifier, title, filename, source, icon in [
        ("personal-guid", "Azure hierarchy", "Hierarchy.docx", "Personal workspace", "file-text"),
        ("group-guid", "Aircraft registration", "Elliott Hendricks.pdf", "Aircraft records", "file-type"),
        ("public-guid", "Annual figures", "Figures.XLSX", "Published research", "file-spreadsheet"),
    ]:
        row = page.locator(f'[data-used-document="{identifier}"]')
        expect(row.get_by_text(title, exact=True)).to_be_visible()
        expect(row.get_by_text(filename, exact=True)).to_be_visible()
        expect(row.get_by_text(source, exact=True)).to_be_visible()
        expect(row.locator(f"svg.lucide-{icon}")).to_be_visible()
        assert identifier not in row.inner_text()
    expect(rows.filter(has_text="Cited")).to_have_count(1)
    expect(page.locator('[data-used-document="group-guid"]')).to_contain_text("Page 2")
    expect(page.locator('[data-used-document="missing-guid"]')).to_have_text("Untitled document")
    expect(page.locator('[data-used-document="same-guid"]').get_by_text("notes.txt", exact=True)).to_have_count(1)
    markup = page.locator('[data-used-document="markup-guid"]')
    expect(markup).to_contain_text("<b>Literal workspace</b>")
    expect(markup.locator("img, b, script")).to_have_count(0)
    assert page.evaluate("window.__injected === undefined")
    drawer = page.get_by_role("complementary", name="Conversation details")
    bounds = drawer.bounding_box()
    assert bounds and bounds["width"] <= width
    for row in rows.all():
        assert row.evaluate("element => element.scrollWidth <= element.clientWidth")
    assert not [
        call for call in api.requests
        if call["path"].startswith(("/api/documents/", "/api/group_documents/", "/api/public-workspaces/"))
    ], "opening the drawer must not repair old conversation metadata"
