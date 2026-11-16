# test_docs_capability_slides.py
"""
Browser coverage for real presentation screenshots in the documentation.
Version: 0.261.398
Implemented in: 0.261.398

Run against a built, served docs site via SIMPLECHAT_DOCS_BASE_URL. The shared
Azure Playwright fixture uses DefaultAzureCredential and azure-mgmt-playwright
when configured, or the existing local-browser path without provisioning.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from fixtures.playwright_connection import connect_options  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("SIMPLECHAT_DOCS_BASE_URL", "").rstrip("/")
CASES = [
    ("/features/agents/", "agents.png"),
    ("/features/workflows/", "workflows.png"),
    ("/features/workspace-scope-lock/", "workspace-scope-lock.png"),
    ("/features/conversation-details/", "conversation-details.png"),
    ("/guides/use-prompts-in-chat/", "saved-prompts.png"),
    ("/explanation/architecture/", "azure-services.png"),
    ("/reference/application-workflows/", "grounded-request-search.png"),
]
VIEWPORTS = [
    pytest.param({"width": 1440, "height": 960}, id="desktop"),
    pytest.param({"width": 390, "height": 844}, id="mobile"),
]


@pytest.mark.ui
@pytest.mark.parametrize("route, filename", CASES)
@pytest.mark.parametrize("viewport", VIEWPORTS)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_actual_slides_load_and_enlarge_without_cropping(page, route, filename, viewport, theme):
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_DOCS_BASE_URL to the served Jekyll site.")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size(viewport)
    response = page.goto(f"{BASE_URL}{route}", wait_until="networkidle")
    assert response is not None and response.ok
    page.evaluate("(theme) => document.documentElement.setAttribute('data-bs-theme', theme)", theme)

    image = page.locator(f"img.docs-media-image[src$='/slides/{filename}']").first
    expect(image).to_be_visible()
    image.scroll_into_view_if_needed()
    page.wait_for_function(
        "(image) => image.complete && image.naturalWidth > 0",
        arg=image.element_handle(),
    )
    details = image.evaluate(
        """(image) => {
            const box = image.getBoundingClientRect();
            return {
                width: image.naturalWidth, height: image.naturalHeight,
                renderedWidth: box.width, renderedHeight: box.height,
                filter: getComputedStyle(image).filter,
                fit: getComputedStyle(image).objectFit,
                src: image.currentSrc,
                alt: image.alt
            };
        }"""
    )
    assert (details["width"], details["height"]) == (1600, 900)
    assert abs(details["renderedWidth"] / details["renderedHeight"] - 16 / 9) < 0.005
    assert details["filter"] == "none" and details["fit"] != "cover"
    assert details["alt"].strip()
    assert urlsplit(details["src"]).netloc == urlsplit(BASE_URL).netloc
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"Page overflows horizontally by {overflow}px: {route}"

    trigger = page.locator(f"button[data-docs-media-src$='/slides/{filename}']").first
    trigger.focus()
    trigger.press("Enter")
    dialog = page.get_by_role("dialog", name="Enlarged screenshot", exact=True)
    expect(dialog).to_be_visible()
    expanded = dialog.locator("img")
    expect(expanded).to_have_attribute("alt", details["alt"])
    expect(expanded).to_have_attribute("src", details["src"])
    expect(page.get_by_role("button", name="Close enlarged screenshot", exact=True)).to_be_focused()
    bounds = expanded.bounding_box()
    assert bounds is not None
    assert bounds["x"] >= 0 and bounds["y"] >= 0
    assert bounds["width"] <= viewport["width"] and bounds["height"] <= viewport["height"]
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(trigger).to_be_focused()
    assert not errors, errors

    capture = os.getenv("SIMPLECHAT_DOCS_CAPTURE", "") == "1"
    if capture:
        directory = ROOT / "ui_tests" / "artifacts" / "docs-capability-slides"
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{filename.removesuffix('.png')}-{viewport['width']}-{theme}.png"
        page.screenshot(path=str(directory / name), full_page=False)


@pytest.mark.ui
def test_search_can_find_a_generated_capability_page(page):
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_DOCS_BASE_URL to the served Jekyll site.")
    response = page.goto(f"{BASE_URL}/search/", wait_until="networkidle")
    assert response is not None and response.ok
    search = page.locator("[data-docs-search-page-input='true']")
    search.fill("workspace scope lock")
    target = page.locator("a[href$='/features/workspace-scope-lock/']").first
    expect(target).to_be_visible(timeout=15000)
