# test_onenote_workspace_upload_workflow.py
"""
Browser coverage for native OneNote workspace uploads.
Version: 0.261.142
Implemented in: 0.261.142 (ported from 0.261.045)

The modal test uses real local Bootstrap assets and needs no application login.
Configured-app workflows mock uploads and document responses; no notebooks are
sent to a server. The shared browser launcher supports Azure Playwright.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from ui_tests.test_workspace_mcp_action_modal import _launch_browser, _require_ui_env
from ui_tests.test_workspace_supported_file_types_modal import (
    TEMPLATES_DIR,
    WORKSPACE_TEMPLATES,
    _allowed_categories,
    jinja2,
)


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SCOPES = {
    "personal": ("/workspace", "documents", "workspace-file-input", "docs-view-list", ""),
    "group": ("/group_workspaces", "group_documents", "file-input", "group-docs-view-list", "group-"),
    "public": ("/public_workspaces", "public_documents", "file-input", "public-docs-view-list", "public-"),
}


@pytest.mark.ui
@pytest.mark.parametrize("modal_id", list(WORKSPACE_TEMPLATES.values()))
@pytest.mark.parametrize("width", [390, 1440])
def test_native_formats_modal_in_browser(modal_id, width):
    sync_api = pytest.importorskip("playwright.sync_api")
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    macro = environment.get_template("_supported_file_types_modal.html").module.supported_file_types_modal
    categories = _allowed_categories()
    modal = str(macro(modal_id, "Supported file types", categories))
    markup = (
        '<!doctype html><html lang="en"><head><title>OneNote upload formats</title>'
        '<base href="http://onenote-ui.test/">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="stylesheet" href="/static/css/bootstrap.min.css"></head><body>'
        f'<button type="button" data-bs-toggle="modal" data-bs-target="#{modal_id}">Supported file types</button>'
        f'{modal}<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script></body></html>'
    )
    assets = {
        "/static/css/bootstrap.min.css": ("text/css", APP_ROOT / "static" / "css" / "bootstrap.min.css"),
        "/static/js/bootstrap/bootstrap.bundle.min.js": (
            "text/javascript",
            APP_ROOT / "static" / "js" / "bootstrap" / "bootstrap.bundle.min.js",
        ),
    }

    def serve_local_fixture(route):
        path = urlsplit(route.request.url).path
        if path == "/":
            route.fulfill(status=200, content_type="text/html", body=markup)
        elif path in assets:
            content_type, asset = assets[path]
            route.fulfill(status=200, content_type=content_type, body=asset.read_bytes())
        else:
            route.abort()

    with sync_api.sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(viewport={"width": width, "height": 900})
            page = context.new_page()
            page.route("http://onenote-ui.test/**", serve_local_fixture)
            page.set_content(markup, wait_until="domcontentloaded")
            dialog = page.locator(f"#{modal_id}")
            dialog.evaluate(
                "(element) => element.addEventListener('shown.bs.modal', "
                "() => { element.dataset.shown = 'true'; }, { once: true })"
            )
            trigger = page.get_by_role("button", name="Supported file types", exact=True)
            trigger.click()
            sync_api.expect(dialog).to_be_visible()
            sync_api.expect(dialog).to_have_attribute("data-shown", "true")
            sync_api.expect(dialog.get_by_text("OneNote (typed text and tables)", exact=True)).to_be_visible()
            sync_api.expect(dialog.get_by_text(".one", exact=True)).to_be_visible()
            sync_api.expect(dialog.get_by_text(".onepkg", exact=True)).to_be_visible()
            page.keyboard.press("Escape")
            sync_api.expect(dialog).not_to_be_visible()
            sync_api.expect(trigger).to_be_focused()
            context.close()
        finally:
            browser.close()


@pytest.mark.ui
@pytest.mark.parametrize("scope", list(SCOPES))
@pytest.mark.parametrize("extension, failed", [(".one", False), (".onepkg", True)])
def test_workspace_selection_and_processing_result(scope, extension, failed):
    """Exercise real workspace JS against isolated upload/status responses."""
    _require_ui_env()
    sync_api = pytest.importorskip("playwright.sync_api")
    route_path, api, input_id, view_id, prefix = SCOPES[scope]
    document_id = "onenote-ui-fixture"
    filename = f"native-ui-fixture{extension}"
    status = (
        "Error: Processing failed: No searchable typed text was found."
        if failed else
        "Processing complete - OneNote typed text only; images, handwriting, and attachments excluded"
    )
    document = {
        "id": document_id,
        "file_name": filename,
        "title": filename,
        "percentage_complete": 0 if failed else 100,
        "status": status,
        "number_of_pages": 0 if failed else 1,
        "tags": [],
        "authors": [],
        "enhanced_citations": False,
        "user_id": "fixture-user",
        "group_id": "group-fixture",
        "public_workspace_id": "public-fixture",
    }
    uploads = []

    def fulfill(route, payload, status_code=200):
        route.fulfill(status=status_code, content_type="application/json", body=json.dumps(payload))

    def documents(route):
        path = urlsplit(route.request.url).path
        if route.request.method != "GET":
            fulfill(route, {"error": "Unexpected test mutation"}, 409)
        elif path.endswith("/tags"):
            fulfill(route, {"tags": []})
        elif path.endswith(f"/{document_id}"):
            fulfill(route, document)
        else:
            records = [document] if uploads else []
            fulfill(route, {
                "documents": records, "page": 1, "page_size": 10,
                "total_count": len(records), "needs_legacy_update_check": False,
            })

    def upload(route):
        uploads.append(route.request.post_data or "")
        fulfill(route, {"documents": [{"id": document_id, "status": "Queued for processing"}]}, 202)

    def guard_writes(route):
        if route.request.method in {"GET", "HEAD"}:
            route.continue_()
        else:
            fulfill(route, {"error": "UI fixtures never mutate server data"}, 409)

    with sync_api.sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.route("**/api/**", guard_writes)
            page.route(f"**/api/{api}**", documents)
            page.route(f"**/api/{api}/upload", upload)
            page.route("**/api/groups?page_size=1000", lambda route: fulfill(route, {
                "groups": [{"id": "group-fixture", "name": "Fixture group", "isActive": True, "userRole": "Owner"}],
            }))
            page.route("**/api/public_workspaces?page_size=1000", lambda route: fulfill(route, {
                "workspaces": [{"id": "public-fixture", "name": "Fixture public", "isActive": True, "userRole": "Owner"}],
            }))
            page.route("**/api/public_workspace_documents/tags*", lambda route: fulfill(route, {"tags": []}))
            response = page.goto(f"{BASE_URL}{route_path}", wait_until="networkidle")
            assert response is not None and response.ok
            page.locator(f"#{view_id}").check()
            # Agreement acceptance is a separate workflow; uploads here never leave the browser fixture.
            page.evaluate("window.UserAgreementManager = undefined")
            page.locator(f"#{input_id}").set_input_files({
                "name": filename, "mimeType": "application/onenote", "buffer": b"mock-native-input",
            })
            row = page.locator(f"#{prefix}doc-row-{document_id}")
            sync_api.expect(row).to_be_visible()
            sync_api.expect(row).to_contain_text(filename)
            assert len(uploads) == 1
            assert filename in uploads[0]
            status_row = page.locator(f"#{prefix}status-row-{document_id}")
            if failed:
                sync_api.expect(status_row).to_be_visible()
                sync_api.expect(status_row).to_contain_text("No searchable typed text was found.")
            else:
                sync_api.expect(status_row).to_have_count(0)
            context.close()
        finally:
            browser.close()
