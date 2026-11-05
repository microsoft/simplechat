# test_v2_web_iq.py
"""Web IQ V2 admin consent/provider and safe cited-media browser coverage.

Version: 0.261.405
Implemented in: 0.261.405

Uses real React components, production CSS and the existing optional Azure Playwright
connection fixture. APIs and preview bytes are intercepted; no live settings are written.
"""

import base64
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle
from ui_tests.fixtures.orchestration.harness_build import start_static_server

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "ui_tests" / "fixtures" / "web_iq"
pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def media_origin():
    bundle = FIXTURE / "harness.bundle.js"
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=bundle)
    try:
        with start_static_server() as origin:
            yield origin
    finally:
        bundle.unlink(missing_ok=True)


@pytest.mark.parametrize("width", [390, 1440])
def test_only_cited_media_and_safe_source_links_render(page, media_origin, width):
    page.set_viewport_size({"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    preview = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    page.route("**/preview.png", lambda route: route.fulfill(body=preview, content_type="image/png"))
    page.goto(f"{media_origin}/ui_tests/fixtures/web_iq/harness.html")
    css = sorted((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
    assert css
    page.add_style_tag(url=f"{media_origin}/{css[0].relative_to(ROOT).as_posix()}")
    cards = page.get_by_role("region", name="Cited web media")
    expect(cards.locator("article > a")).to_have_count(2)
    expect(cards.get_by_role("list", name="Video moments").get_by_role("link")).to_have_count(5)
    expect(cards.get_by_text("Example Publisher · 2:30")).to_be_visible()
    expect(cards.get_by_text("Unsafe moment")).to_have_count(0)
    expect(page.locator("a a")).to_have_count(0)
    expect(cards.locator("img")).to_have_count(2)
    expect(page.locator("img")).to_have_count(2)
    expect(page.get_by_role("link", name="Text-only markdown clip")).to_have_attribute(
        "href", "https://source.test/text.jpg"
    )
    expect(page.get_by_text("Retrieved but not cited")).to_have_count(0)
    expect(cards.get_by_text("Text-only source")).to_have_count(0)
    expect(page.get_by_text("Text-only description.")).to_be_visible()
    expect(cards.get_by_role("link", name=re.compile("Cited hosted video"))).to_have_attribute(
        "href", "https://source.test/video"
    )
    expect(page.locator("video, iframe, embed, object")).to_have_count(0)
    expect(page.get_by_text("Web IQ", exact=True)).to_have_count(4)
    expect(page.get_by_text("Cited landscape <script>bad()</script>", exact=True).last).to_be_visible()
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow
    assert not errors
    artifacts = ROOT / "ui_tests" / "artifacts" / "web_iq"
    artifacts.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifacts / f"cited-media-{width}.png"), full_page=True)


def test_admin_switches_provider_without_losing_masked_connection(page):
    fixture = AdminSettingsFixture(page, sections={"knowledge": ("web-search-section",)}, validate_updates=True)
    fixture.settings.update({
        "enable_web_search": False, "web_search_provider": "foundry",
        "web_iq": {"key": "***REDACTED***"},
        "web_search_agent": {"other_settings": {"azure_ai_foundry": {"endpoint": "https://foundry.test"}}},
    })
    fixture.open(ready_region="Web Search")
    provider = page.get_by_role("combobox", name="Web search provider", exact=True)
    provider.select_option("web_iq")
    page.get_by_text("Enable Web Search", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_text("Foundry Project Endpoint", exact=True)).to_have_count(0)
    consent = page.get_by_role("checkbox", name=re.compile("^Accept Web IQ data processing terms"))
    expect(consent).not_to_be_checked()
    page.get_by_text("Accept Web IQ data processing terms", exact=True).click()
    dialog = page.get_by_role("dialog", name="Web IQ consent required")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name=re.compile("Accept|Continue|understand", re.I)).click()
    expect(consent).to_be_checked()
    expect(page.get_by_role("combobox", name="Image results", exact=True)).to_have_value("off")
    page.get_by_role("combobox", name="Image results", exact=True).select_option("with_media")
    provider.select_option("foundry")
    expect(page.get_by_text("Foundry Project Endpoint", exact=True)).to_be_visible()
    provider.select_option("web_iq")
    expect(page.get_by_role("combobox", name="Image results", exact=True)).to_have_value("with_media")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert fixture.settings["web_iq_consent_accepted"] is True
    assert fixture.settings["web_search_provider"] == "web_iq"
    fixture.assert_clean()
