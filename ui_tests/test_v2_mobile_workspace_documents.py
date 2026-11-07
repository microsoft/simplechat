# test_v2_mobile_workspace_documents.py
"""
Production-SPA mobile workspace/document layout and permission regressions.
Version: 0.261.325
Implemented in: 0.261.323

Reuses closed group/public HTTP fixtures and the shared Azure Playwright connection.
The same explorer renders mobile rows without changing saved desktop columns.
"""

from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect

# Legacy shared fixtures import their connection helpers as top-level modules.
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

pytest_plugins = (
    "ui_tests.fixtures.group_documents",
    "ui_tests.fixtures.public_documents",
    "test_v2_personal_document_scope",
)


pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).parent / "artifacts" / "mobile-layout"


@pytest.mark.parametrize("fixture_name,path,theme,width", [
    ("group_documents_ui", "/groups/group-a/documents", "light", 320),
    ("group_documents_ui", "/groups/group-a/documents", "dark", 393),
    ("public_documents_ui", "/public/pub-a/documents", "light", 393),
    ("public_documents_ui", "/public/pub-a/documents", "dark", 430),
])
def test_mobile_documents_fill_pane_with_selectable_readable_rows(request, fixture_name, path, theme, width):
    ui = request.getfixturevalue(fixture_name)
    ui.open(path, theme=theme, width=width, height=852)
    page = ui.page
    details = page.get_by_role("button", name="Details for Research brief", exact=True)
    expect(details).to_be_visible()
    ui.assert_no_overflow()
    table = page.get_by_role("table")
    bounds = table.locator("..").bounding_box()
    assert bounds and bounds["height"] >= 160, bounds
    assert table.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    expect(page.get_by_role("navigation", name="Workspace sections", exact=True)).not_to_be_visible()
    expect(page.get_by_role("button", name="Workspace sections", exact=True)).to_contain_text("Documents")
    checkbox = page.get_by_role("checkbox", name="Select Research brief", exact=True)
    expect(checkbox).to_be_visible()
    checkbox.check()
    expect(page.get_by_text("1 selected", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Upload", exact=True)).to_have_count(0)
    view_options = page.get_by_role("button", name="Document view options", exact=True)
    view_options.click()
    expect(page.get_by_role("combobox", name="Sort documents", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Tiles view", exact=True)).to_be_visible()
    view_options.click()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / f"{fixture_name}-{width}-{theme}.png"))
    details.click()
    panel = page.get_by_role("dialog", name="Document details", exact=True)
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Research brief")
    panel.get_by_role("button", name="Close", exact=True).click()
    opener = page.get_by_role("button", name="Workspace sections", exact=True)
    opener.click()
    page.get_by_role("navigation", name="Workspace sections").get_by_role("link", name="Overview", exact=True).click()
    expect(page.get_by_role("navigation", name="Workspace sections")).not_to_be_visible()
    expect(opener).to_contain_text("Overview")
    ui.assert_no_overflow()


def test_rotation_keeps_desktop_document_columns_and_preferences(group_documents_ui):
    ui = group_documents_ui
    ui.open("/groups/group-a/documents", width=393, height=852)
    expect(ui.page.get_by_role("button", name="Details for Research brief", exact=True)).to_be_visible()
    ui.page.set_viewport_size({"width": 1440, "height": 900})
    expect(ui.page.get_by_role("columnheader", name="Modified", exact=False)).to_be_visible()
    expect(ui.page.get_by_role("navigation", name="Workspace sections")).to_be_visible()
    assert ui.preferences["v2DocumentsPrefs"]["columns"] == ["name", "tags", "status", "modified", "size"]


def test_personal_mobile_documents_keep_personal_scope_and_upload(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents", width=393, height=852)
    expect(ui.page.get_by_role("button", name="Details for Personal Alpha", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Upload", exact=True)).to_be_visible()
    ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True).check()
    expect(ui.page.get_by_role("combobox", name="Document actions")).to_be_enabled()
    ui.assert_no_overflow()
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/group_documents")]
