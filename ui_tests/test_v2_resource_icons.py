# test_v2_resource_icons.py
"""
Regression coverage for shared agent/model local icon utilities.
Version: 0.261.315
Implemented in: 0.261.315

The existing production agent editor must retain its local catalogue, bounded
raster upload, error reporting and default reset after utility extraction.
"""

import base64

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import (
    AGENT_ID, connect_options, workspace_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui


def test_agent_icon_catalogue_upload_and_default_are_preserved(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open(f"/workspace/agents/{AGENT_ID}")
    upload = page.get_by_label("Upload icon", exact=True)
    icon_fields = page.get_by_role("group", name="Agent icon", exact=True)
    expect(upload).to_be_visible()
    page.get_by_role("button", name="Load all local icons", exact=True).click()
    page.get_by_label("Search Bootstrap icons", exact=True).fill("database")
    page.get_by_label("Bootstrap icon", exact=True).select_option("bi-database")
    expect(icon_fields.locator("i.bi-database")).to_be_visible()
    upload.set_input_files({"name": "not-an-icon.svg", "mimeType": "image/svg+xml", "buffer": b"<svg/>"})
    expect(page.get_by_role("alert").filter(has_text="Choose a PNG or JPEG image.")).to_be_visible()
    data = page.evaluate("""() => {
        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 256;
        canvas.getContext('2d').fillRect(0, 0, 512, 256);
        return canvas.toDataURL('image/png').split(',')[1];
    }""")
    upload.set_input_files({"name": "large-icon.png", "mimeType": "image/png", "buffer": base64.b64decode(data)})
    image = icon_fields.locator('img[src^="data:image/png;base64,"]')
    expect(image).to_be_visible()
    dimensions = image.evaluate("image => [image.naturalWidth, image.naturalHeight, image.src.length]")
    assert dimensions[:2] == [128, 64] and dimensions[2] <= 350000
    page.get_by_role("button", name="Use default icon", exact=True).click()
    expect(image).to_have_count(0)
    expect(page.get_by_label("Bootstrap icon", exact=True)).to_have_value("bi-robot")
    assert not ui.editor_writes
