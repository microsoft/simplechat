# test_image_editor_capabilities.py
"""
Image editor operation, capability refresh, responsive and accessibility UI regression tests.
Version: 0.261.107
Implemented in: 0.261.107

Use the real source components and the shared local/Azure Playwright connection fixture.
All image requests are fulfilled in memory, including personal and collaborative revisions.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Standalone pytest execution follows the other UI suites' shared-fixture import convention.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from image_editor import ImageEditorFixture, image_editor_assets, image_profile, reference_profile  # noqa: E402, F401
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


def expect_revision(image_ui, operation, origin, masked=False):
    page = image_ui.page
    expect(page.get_by_label("Describe the change", exact=True)).to_have_value("")
    request = image_ui.requests[-1]["body"]
    assert request["operation"] == operation
    assert request["origin"] == origin
    assert request["conversation_id"] == "conversation-1"
    assert request["expected_revision_count"] == 2
    assert request["expected_current_revision_id"] == "revision-1"
    assert ("mask" in request) is masked
    assert ("mask_regions" in request) is masked
    assert "image" not in request and "source_image" not in request
    return request


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("shared", [False, True])
def test_masked_edits_use_a_keyboard_region_and_preserve_revision_identity(image_ui, width, shared):
    image_ui.open(width=width, shared=shared)
    page = image_ui.page
    expect(page.get_by_role("button", name="Close the editor", exact=True)).to_be_focused()
    select_region(page)
    expect(page.get_by_text(re.compile("not strictly bound by a mask"))).to_be_visible()
    page.get_by_label("Describe the change", exact=True).fill("Make the sky orange")
    page.get_by_role("button", name="Edit selected region", exact=True).click()
    request = expect_revision(image_ui, "edit", "ai", masked=True)
    assert request["mask"].startswith("data:image/png;base64,")
    assert request["mask_regions"] == 1
    assert ("/collaboration/" in image_ui.requests[-1]["path"]) is shared
    expect(page.get_by_role("button", name="Clear the selection", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("button", name="Open image editor", exact=True)).to_be_focused()


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize(("model_name", "provider_label"), [
    ("MAI-Image-2.6", "Microsoft Foundry MAI"),
    ("FLUX.2-pro", "Microsoft Foundry FLUX"),
])
def test_reference_edits_have_no_mask_and_show_authoritative_options(image_ui, width, model_name, provider_label):
    image_ui.open(capability=reference_profile(model_name=model_name, provider_label=provider_label), width=width)
    page = image_ui.page
    expect(page.get_by_test_id("image-edit-profile")).to_contain_text(model_name)
    expect(page.get_by_test_id("image-edit-profile")).to_contain_text(provider_label)
    expect(page.get_by_role("button", name="Choose regions from a grid, without a mouse")).to_have_count(0)
    expect(page.get_by_text(re.compile("current image is used as a reference"))).to_be_visible()
    page.get_by_label("Describe the change", exact=True).fill("Add a green path")
    page.get_by_role("button", name="Edit using source image", exact=True).click()
    expect_revision(image_ui, "edit", "ai")
    page.get_by_role("button", name="Controls", exact=True).click()
    expect(page.get_by_role("group", name="Shape")).to_be_visible()
    expect(page.get_by_role("group", name="Shape").get_by_role("button")).to_have_text([
        "Square · 1024x1024", "Landscape · 1024x768", "Portrait · 768x1024",
    ])
    expect(page.get_by_role("group", name="Quality")).to_have_count(0)
    expect(page.get_by_role("group", name="Background")).to_have_count(0)
    page.get_by_role("button", name="Landscape · 1024x768", exact=True).click()
    page.get_by_role("button", name="Regenerate whole image", exact=True).click()
    page.wait_for_function("document.querySelector('img[alt=\"Generated mountain\"]').src.includes('revision-3')")
    request = image_ui.requests[-1]["body"]
    assert request["operation"] == "regenerate" and request["origin"] == "control"
    assert request["size"] == "1024x768"
    for unsupported in ("mask", "mask_regions", "quality", "background"):
        assert unsupported not in request


def test_regeneration_only_model_clearly_replaces_the_whole_image(image_ui):
    image_ui.open(capability=image_profile(
        "regenerate", model_name="FLUX-1.1-pro", qualities=[], backgrounds=[],
    ))
    page = image_ui.page
    expect(page.get_by_text(re.compile("without using the current image as a reference"))).to_be_visible()
    expect(page.get_by_role("button", name="Select a rectangle", exact=True)).to_have_count(0)
    page.get_by_label("Describe the change", exact=True).fill("Add a river")
    page.get_by_role("button", name="Regenerate whole image", exact=True).click()
    expect_revision(image_ui, "regenerate", "ai")
    page.get_by_role("button", name="History", exact=True).click()
    expect(page.get_by_text("AI regeneration (whole image)", exact=True)).to_be_visible()


@pytest.mark.parametrize("mode", ["masked", "edit"])
def test_edit_capable_models_also_offer_explicit_prompt_only_regeneration(image_ui, mode):
    image_ui.open(capability=image_profile(mode))
    page = image_ui.page
    if mode == "masked":
        select_region(page)
    page.get_by_role("button", name="Prompt", exact=True).click()
    expect(page.get_by_text(re.compile("without the current image or any selected region"))).to_be_visible()
    page.get_by_role("button", name="Regenerate whole image", exact=True).click()
    page.wait_for_function("document.querySelector('img[alt=\"Generated mountain\"]').src.includes('revision-2')")
    request = image_ui.requests[-1]["body"]
    assert request["origin"] == "prompt" and request["operation"] == "regenerate"
    assert request["prompt"] == "A mountain at dawn"
    assert "mask" not in request and "mask_regions" not in request


@pytest.mark.parametrize("state", ["off", "unavailable", "unresolved"])
@pytest.mark.parametrize("shared", [False, True])
def test_disabled_inference_still_allows_history_restore(image_ui, state, shared):
    capability = image_profile(
        "unavailable" if state == "unavailable" else "masked",
        enabled=False,
        reason="An administrator must select a compatible image model.",
    )
    image_ui.open(capability=capability, unresolved=state == "unresolved", shared=shared)
    page = image_ui.page
    expect(page.get_by_label("Describe the change", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Prompt", exact=True).click()
    expect(page.get_by_role("button", name="Regenerate whole image", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Controls", exact=True).click()
    expect(page.get_by_role("button", name="Regenerate whole image", exact=True)).to_be_disabled()
    page.get_by_role("button", name="History", exact=True).click()
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.get_by_role("img", name="Generated mountain", exact=True)).to_have_attribute(
        "src", f"{image_ui.image_endpoint}?rev=original",
    )
    assert image_ui.requests == []
    assert image_ui.restores[0]["body"] == {
        "conversation_id": "conversation-1", "revision_id": "original",
    }
    assert ("/collaboration/" in image_ui.restores[0]["path"]) is shared


def test_profile_refresh_clears_regions_and_rendering_options_without_reusing_them(image_ui):
    image_ui.open()
    page = image_ui.page
    select_region(page)
    image_ui.set_capability(image_profile(model_name="another-masked-model"))
    expect(page.get_by_test_id("image-edit-profile")).to_contain_text("another-masked-model")
    expect(page.get_by_role("button", name="Clear the selection", exact=True)).to_be_disabled()
    select_region(page)
    image_ui.set_capability(reference_profile())
    expect(page.get_by_test_id("image-edit-profile")).to_contain_text("MAI-Image-2.6")
    page.get_by_label("Describe the change", exact=True).fill("Add clouds")
    page.get_by_role("button", name="Edit using source image", exact=True).click()
    expect_revision(image_ui, "edit", "ai")

    image_ui.set_capability(image_profile())
    page.get_by_role("button", name="Controls", exact=True).click()
    page.get_by_role("button", name="Landscape · 1536x1024", exact=True).click()
    page.get_by_role("button", name="High", exact=True).click()
    page.get_by_role("button", name="Transparent", exact=True).click()
    expect(page.get_by_role("button", name="High", exact=True)).to_have_attribute("aria-pressed", "true")
    image_ui.set_capability(reference_profile())
    expect(page.get_by_role("group", name="Quality")).to_have_count(0)
    page.get_by_role("button", name="Regenerate whole image", exact=True).click()
    page.wait_for_function("document.querySelector('img[alt=\"Generated mountain\"]').src.includes('revision-3')")
    request = image_ui.requests[-1]["body"]
    assert request["operation"] == "regenerate"
    for stale in ("size", "quality", "background", "mask", "mask_regions"):
        assert stale not in request


def test_stale_hook_requests_fail_before_transport_and_concurrency_errors_stay_visible(image_ui):
    image_ui.open()
    page = image_ui.page
    page.evaluate("() => { window.oldImageRevise = window.imageEditorFixture.revise; }")
    image_ui.set_capability(reference_profile())
    assert page.evaluate("""async () => await window.oldImageRevise({
        origin: 'control', operation: 'regenerate', quality: 'high'
    })""") is False
    expect(page.get_by_role("alert")).to_contain_text("does not support that quality")
    assert image_ui.requests == []
    page.get_by_role("button", name="Dismiss the error", exact=True).click()
    image_ui.next_error = (409, "This image was revised elsewhere.")
    page.get_by_label("Describe the change", exact=True).fill("Make it blue")
    page.get_by_role("button", name="Edit using source image", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Someone else changed this image")
    expect(page.get_by_label("Describe the change", exact=True)).to_have_value("Make it blue")
    assert len(image_ui.requests) == 1
    assert image_ui.requests[0]["body"]["expected_current_revision_id"] == "revision-1"


@pytest.mark.parametrize("width", [1440, 390])
def test_unknown_availability_and_untrusted_labels_are_readable_without_disabling_known_operations(image_ui, width):
    injected = '<img src=x onerror="window.untrustedExecuted=true">'
    image_ui.open(capability=reference_profile(
        model_name=injected,
        cloud_label="Government endpoint",
        availability="unknown",
        availability_reason="No published regional evidence for this configured endpoint.",
    ), width=width)
    page = image_ui.page
    expect(page.get_by_test_id("image-edit-profile")).to_contain_text(injected)
    expect(page.get_by_test_id("image-edit-profile")).to_contain_text("Government endpoint")
    expect(page.get_by_role("status")).to_contain_text("not a confirmation of provider support")
    assert page.evaluate("window.untrustedExecuted") is None
    expect(page.locator('img[src="x"]')).to_have_count(0)
    page.get_by_label("Describe the change", exact=True).fill("Add a trail")
    expect(page.get_by_role("button", name="Edit using source image", exact=True)).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    dialog = page.get_by_role("dialog", name="Edit image", exact=True)
    assert dialog.evaluate("(element) => element.scrollWidth <= element.clientWidth")
