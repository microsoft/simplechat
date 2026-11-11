# test_model_catalog_update_controls.py
"""
Classic and React V2 signed-catalog update controls.
Version: 0.261.430
Implemented in: 0.261.425
Online-access switch styling updated in: 0.261.426

Uses the existing Azure Playwright/local Chromium fixture and real UI components.
HTTP fixtures exercise UI states; real signature/storage contracts have functional tests.
"""

import json
import re

import pytest
from playwright.sync_api import expect

from test_model_catalog_management import catalog_page, mount_catalog
from test_model_endpoint_capacity_editor import capacity_browser


# Pytest discovers these deliberately re-exported shared fixtures.
__all__ = ["catalog_page", "capacity_browser"]


@pytest.fixture
def update_page(catalog_page):
    page, _settings = catalog_page
    status = {
        "etag": "1", "onlineEnabled": False, "publisherConfigured": True,
        "repository": "https://github.com/microsoft/simplechat",
        "discoveryUrl": "https://raw.githubusercontent.com/microsoft/simplechat/model-catalog/model-catalog/latest.json",
        "installed": {"revision": "bundled", "publishedAt": "2026-11-05"},
        "canRollback": False,
    }
    calls = []

    def api(route):
        body = route.request.post_data_json if route.request.method == "POST" else {}
        operation = body.get("operation")
        calls.append(operation)
        if operation == "online":
            status.update(onlineEnabled=body["enabled"], etag="2")
        elif operation == "check":
            status["check"] = {
                "status": "available", "attemptedAt": "2026-11-10T12:00:00Z",
                "digest": "a" * 64,
                "downloadUrl": "https://raw.githubusercontent.com/microsoft/simplechat/" + "a" * 40 + "/model-catalog/catalog-1-2026-11-10.json",
            }
        elif operation == "upload" and body["package"] == "{}":
            route.fulfill(status=400, json={"error": "Choose a publisher-signed catalog package."})
            return
        elif operation in {"upload", "preview", "rollback-preview"}:
            route.fulfill(json={
                "digest": "a" * 64, "etag": status["etag"],
                "manifest": {"revision": "1", "publishedAt": "2026-11-10T12:00:00Z", "keyId": "publisher"},
                "signatureVerified": True,
                "changes": {"added": [], "changed": ["gpt-5-nano"], "removed": [], "operationMetadataChanged": False},
            })
            return
        elif operation in {"apply", "rollback"}:
            status.update(installed={"revision": "1", "publishedAt": "2026-11-10T12:00:00Z"}, etag="3", canRollback=True)
            status["check"] = None
        route.fulfill(json=status)

    page.route("**/api/admin/model-catalog/updates", api)
    return page, calls


@pytest.mark.parametrize("flavor", ["classic", "v2"])
def test_catalog_update_opt_in_preview_and_apply(update_page, flavor):
    page, calls = update_page
    page.route("**/api/v2/bootstrap", lambda route: route.fulfill(json={
        "user": {"id": "catalog-admin"},
        "catalogs": {"models": [{"selection_key": "updated-catalog-model"}]},
    }))
    mount_catalog(page, flavor)
    root = page.get_by_role("region", name="Catalog updates")
    # Classic's section also has an accessible region name.
    expect(root.get_by_text("Official repository:", exact=False)).to_contain_text("microsoft/simplechat")
    expect(root.get_by_role("button", name="Check for updates", exact=True)).to_be_disabled()
    root.get_by_text("Allow online catalog update checks", exact=True).click()
    root.get_by_role("button", name="Check for updates", exact=True).click()
    root.get_by_role("button", name="Preview available update").click()
    expect(root.get_by_text("Publisher signature verified.", exact=True)).to_be_visible()
    expect(root.get_by_text("Installed:", exact=False)).to_contain_text("bundled")
    assert "apply" not in calls
    root.get_by_role("button", name="Apply catalog update").click()
    expect(root.get_by_text("Installed:", exact=False)).to_contain_text("1")
    expect(root.get_by_role("button", name="Preview rollback")).to_be_enabled()
    assert "apply" in calls
    if flavor == "v2":
        page.wait_for_function("""window.OrchHarness.stores.bootstrap.useBootstrapStore
            .getState().data?.catalogs?.models?.[0]?.selection_key === 'updated-catalog-model'""")


@pytest.mark.parametrize("flavor", ["classic", "v2"])
def test_catalog_offline_upload_and_unsigned_rejection(update_page, flavor):
    page, calls = update_page
    mount_catalog(page, flavor)
    root = page.get_by_role("region", name="Catalog updates")
    file = root.get_by_label("Upload signed package")
    file.set_input_files({"name": "unsigned.json", "mimeType": "application/json", "buffer": b"{}"})
    expect(root.get_by_role("alert")).to_have_text("Choose a publisher-signed catalog package.")
    file.set_input_files({"name": "signed.json", "mimeType": "application/json", "buffer": json.dumps({"fixture": "signed"}).encode()})
    expect(root.get_by_text("Publisher signature verified.", exact=True)).to_be_visible()
    assert "check" not in calls and "online" not in calls
    root.get_by_role("button", name="Cancel update preview").click()
    expect(root.get_by_role("button", name="Apply catalog update")).to_have_count(0)


@pytest.mark.parametrize("flavor", ["classic", "v2"])
def test_catalog_online_access_uses_keyboard_operable_switch(update_page, flavor):
    page, calls = update_page
    mount_catalog(page, flavor)
    root = page.get_by_role("region", name="Catalog updates")
    toggle = root.get_by_label("Allow online catalog update checks")
    expect(toggle).not_to_be_checked()
    if flavor == "classic":
        expect(root.get_by_role("switch", name="Allow online catalog update checks")).to_have_count(1)
        expect(toggle).to_have_class("form-check-input")
        expect(toggle.locator("..")).to_have_class("form-check form-switch mb-3")
    else:
        expect(toggle).to_have_class("peer sr-only")
        track = toggle.locator("..").locator("span").first
        expect(track).to_have_class(re.compile(r"\brounded-full\b"))
    toggle.focus()
    toggle.press("Space")
    expect(toggle).to_be_checked()
    expect(root.get_by_role("button", name="Check for updates", exact=True)).to_be_enabled()
    toggle.focus()
    toggle.press("Space")
    expect(toggle).not_to_be_checked()
    expect(root.get_by_role("button", name="Check for updates", exact=True)).to_be_disabled()
    assert calls.count("online") == 2
