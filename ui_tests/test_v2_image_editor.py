# test_v2_image_editor.py
"""
UI coverage for v2 image editor derive mode.
Version: 0.261.192
Implemented in: 0.261.192

This test ensures derive mode creates a new image from an uploaded/reference image while the
existing revise-mode controls remain available for generated images.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from image_editor import ImageEditorFixture, image_editor_assets, image_profile  # noqa: E402, F401
from playwright_connection import connect_options  # noqa: E402, F401


pytestmark = pytest.mark.ui


@pytest.fixture
def image_ui(image_editor_assets, page):
    fixture = ImageEditorFixture(page, image_editor_assets)
    yield fixture
    fixture.assert_clean()


def select_region(page):
    page.get_by_role("button", name="Choose regions from a grid, without a mouse", exact=True).click()
    region = page.get_by_role("button", name="Top left", exact=True)
    region.focus()
    page.keyboard.press("Space")
    expect(region).to_have_attribute("aria-pressed", "true")


def test_derive_mode_hides_revision_tabs_and_render_controls(image_ui):
    image_ui.open(
        mode="derive",
        capability=image_profile(max_reference_images=4),
        reference={"type": "message", "message_id": "uploaded-image-message"},
    )
    page = image_ui.page
    expect(page.get_by_role("button", name="Ask AI", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Prompt", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Controls", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="History", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Create new image", exact=True)).to_be_disabled()
    expect(page.get_by_text(re.compile("current image guides the edit"))).to_be_visible()


def test_derive_mode_sends_reference_and_mask_to_direct_image_stream(image_ui):
    image_ui.open(
        mode="derive",
        capability=image_profile(max_reference_images=4),
        reference={"type": "message", "message_id": "uploaded-image-message"},
    )
    page = image_ui.page
    select_region(page)
    page.get_by_label("Describe the change", exact=True).fill("Turn this into a watercolor")
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/api/chat/stream")
    ) as stream_request:
        page.get_by_role("button", name="Create new image", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    body = stream_request.value.post_data_json
    assert body["message"] == "Turn this into a watercolor"
    assert body["image_generation"] is True
    assert body["hybrid_search"] is False
    assert body["image_references"] == [{"type": "message", "message_id": "uploaded-image-message"}]
    assert body["image_mask"].startswith("data:image/png;base64,")
    assert body["image_mask_regions"] == 1


def test_revise_mode_still_exposes_history_and_revision_endpoint(image_ui):
    image_ui.open(capability=image_profile(max_reference_images=4))
    page = image_ui.page
    expect(page.get_by_role("button", name="Prompt", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Controls", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="History", exact=True)).to_be_visible()
    page.get_by_label("Describe the change", exact=True).fill("Add golden light")
    page.get_by_role("button", name="Edit image", exact=True).click()
    body = image_ui.requests[-1]["body"]
    assert body["operation"] == "edit"
    assert body["origin"] == "ai"
    assert "image_references" not in body
