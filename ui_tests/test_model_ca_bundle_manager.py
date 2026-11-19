# test_model_ca_bundle_manager.py
"""
Azure Playwright-ready shared CA manager upload, replace, and deletion workflows.
Version: 0.261.052
Implemented in: 0.261.052

Renders the actual admin pane and local browser assets with same-origin I/O fixtures.
Backend parsing, authorization, and storage are covered by functional regressions.
"""

from copy import deepcopy
from email.parser import BytesParser
from email.policy import default
import json
import mimetypes
from urllib.parse import unquote, urlsplit

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape
import pytest
from playwright.sync_api import expect

from test_model_endpoint_capacity_editor import APP_ROOT, ORIGIN, capacity_browser
from functions_model_endpoint_providers import get_model_endpoint_provider_ui_options
from model_endpoint_profiles import get_custom_endpoint_profile_options


pytestmark = pytest.mark.ui


def _multipart(request):
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + request.post_data_buffer
    )
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
        for part in message.iter_parts()
    }


def test_ca_manager_upload_replace_errors_and_confirmed_delete(capacity_browser):
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"), undefined=ChainableUndefined,
        autoescape=select_autoescape(["html"]),
    )
    pane = environment.get_template("admin/_panes/model-endpoints.html").render(
        settings={"enable_multi_model_endpoints": True, "gpt_model": {"selected": []}},
        admin_landing_tab="model-endpoints",
        model_endpoint_api_types=get_model_endpoint_provider_ui_options(),
        model_endpoint_routing_api_types=get_model_endpoint_provider_ui_options(routing_schema_version=2),
        model_endpoint_profiles=get_custom_endpoint_profile_options(),
    )
    html = (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="stylesheet" href="/static/css/bootstrap.min.css"></head><body>'
        '<div id="toast-container"></div>' + pane
        + '<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>'
        '<script type="module">import {initializeCABundleManager} from "/static/js/admin/model_ca_bundle_manager.js"; initializeCABundleManager();</script>'
        '</body></html>'
    )
    state = {"bundles": [], "uploads": [], "fail_delete": False}
    errors, external = [], []
    context = capacity_browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route):
        url = urlsplit(route.request.url)
        if url.netloc != "simplechat.test":
            external.append(route.request.url)
            route.abort()
            return
        if url.path.startswith("/static/"):
            root = (APP_ROOT / "static").resolve()
            asset = (root / unquote(url.path[len("/static/"):])).resolve()
            if not asset.is_relative_to(root) or not asset.is_file():
                route.fulfill(status=404, body="")
                return
            route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            return
        if url.path.startswith("/api/model-ca-bundles"):
            if route.request.method in ("POST", "PUT"):
                fields = _multipart(route.request)
                state["uploads"].append(fields)
                revision = 1 if route.request.method == "POST" else state["bundles"][0]["revision"] + 1
                bundle = {
                    "id": "ca-0123456789abcdef0123456789abcdef",
                    "name": fields["name"].decode(), "revision": revision, "state": "active",
                    "expires_at": "2099-01-01T00:00:00+00:00", "pending_save_count": 0,
                    "certificates": [{"subject": "<img src=x onerror=alert(1)>", "sha256": "a" * 64, "valid_from": "2026-01-01", "expires_at": "2099-01-01"}],
                    "references": [], "audit_history": [{"timestamp": "2026-10-05", "action": "created", "revision": revision}],
                }
                state["bundles"] = [bundle]
                payload = {"bundle": bundle, "success": True}
            elif route.request.method == "DELETE":
                if state["fail_delete"]:
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"error": "This bundle is used by saved endpoints."}))
                    return
                expected = route.request.post_data_json["expected_revision"]
                if expected != state["bundles"][0]["revision"]:
                    raise AssertionError("Deletion must use the displayed revision.")
                state["bundles"] = []
                payload = {"success": True}
            else:
                payload = {"bundles": deepcopy(state["bundles"])}
            route.fulfill(content_type="application/json", body=json.dumps(payload))
            return
        route.fulfill(content_type="text/html", body=html)

    context.route("**/*", route_request)
    try:
        page.goto(f"{ORIGIN}/certificate-manager", wait_until="networkidle")
        page.locator("#custom-endpoint-network-controls > summary").click()
        page.locator("#model-ca-bundle-manager > summary").click()
        expect(page.locator("#model-ca-bundle-list")).to_contain_text("No CA bundles")
        page.get_by_label("Bundle name", exact=True).fill("<img src=x onerror=alert(1)>")
        page.get_by_label("PEM CA certificate file", exact=True).set_input_files({
            "name": "roots.pem", "mimeType": "application/x-pem-file", "buffer": b"synthetic-file-validated-by-backend-tests",
        })
        page.get_by_role("button", name="Upload CA bundle", exact=True).click()
        expect(page.locator("[data-ca-bundle-id]")).to_have_count(1)
        assert state["uploads"][0]["file"] == b"synthetic-file-validated-by-backend-tests"
        page.get_by_role("button", name="Edit / replace", exact=True).click()
        page.get_by_label("Bundle name", exact=True).fill("Updated roots")
        page.get_by_role("button", name="Save bundle changes", exact=True).click()
        expect(page.locator("[data-ca-bundle-id] h6")).to_have_text("Updated roots")
        assert state["uploads"][1]["expected_revision"] == b"1"
        assert "file" not in state["uploads"][1]
        state["fail_delete"] = True
        page.get_by_role("button", name="Delete unused bundle", exact=True).click()
        page.locator("#model-ca-bundle-delete-confirm").click()
        expect(page.locator("#model-ca-bundle-status")).to_contain_text("used by saved endpoints")
        assert len(state["bundles"]) == 1
        state["fail_delete"] = False
        page.locator("#model-ca-bundle-delete-confirm").click()
        expect(page.locator("#model-ca-bundle-list")).to_contain_text("No CA bundles")
        assert page.locator('img[src="x"]').count() == 0
        assert not errors
        assert not external
    finally:
        context.close()
