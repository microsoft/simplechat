# custom_connections_admin.py
"""
Closed Custom connection admin browser fixture.
Version: 0.261.107
Implemented in: 0.261.107

Reuse the existing SPA/local-or-Azure Playwright harness without image fixtures,
provisioning, live authentication, or live inference.
"""

import copy
import json
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

from v2_admin_settings import AdminSettingsFixture, ORIGIN, REPO_ROOT, SPA_INDEX
from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


class CustomConnectionsFixture(AdminSettingsFixture):
    def __init__(self, page, *, classic=False):
        super().__init__(page)
        self.classic = classic
        fields = import_app_module("admin_settings_fields")
        group = copy.deepcopy(next(item for item in ADMIN_NAV if item["id"] == "ai-models"))
        group["tabs"] = [tab for tab in group["tabs"] if tab["id"] == "model-endpoints"]
        section_ids = [section["id"] for tab in group["tabs"] for section in tab["sections"]]
        self.schema = {key: copy.deepcopy(fields.get_admin_settings_fields()[key]) for key in section_ids}
        self.settings = {
            field["key"]: copy.deepcopy(field["default"])
            for section in self.schema.values() for field in section
            if field.get("key") and "default" in field
        }
        self.settings.update({
            "enable_multi_model_endpoints": True, "enable_semantic_kernel": False,
            "allow_private_custom_model_endpoints": False, "allow_insecure_custom_model_endpoints": False,
            "custom_model_endpoint_ca_bundle_path": "",
        })
        self.payload.update({"admin_nav": [group], "field_schema": self.schema, "settings": self.settings})
        self.descriptors = import_app_module("functions_model_endpoint_providers").get_model_endpoint_provider_ui_options()
        self.endpoints = [{
            "id": "stable-endpoint", "name": "Saved Gateway", "provider": "custom", "api_type": "openai",
            "enabled": True, "connection": {"endpoint": "https://gateway.example.test/prefix", "url_mode": "exact"},
            "auth": {"type": "bearer"}, "has_bearer_token": True,
            "models": [{
                "id": "stable-model", "modelName": "private-chat-model", "displayName": "Private chat",
                "enabled": True, "vendorOptions": {"future": [1, 2]},
                "capability_status": {
                    "chat": {"supported": True, "available": True, "source": "declared", "api": "chat"},
                    "image_generation": {"supported": False, "source": "unsupported", "reason": "No verified image API."},
                },
            }],
        }]
        self.connection_writes = []
        self.model_tests = []

    def _route(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if not request.url.startswith(ORIGIN + "/"):
            return super()._route(route)
        if path == "/api/v2/admin/model-endpoints" and request.method == "GET":
            route.fulfill(json={
                "endpoints": self.endpoints, "multi_endpoint_enabled": True, "custom_api_types": self.descriptors,
                "custom_network_policy": {key: self.settings[key] for key in (
                    "allow_private_custom_model_endpoints", "allow_insecure_custom_model_endpoints", "custom_model_endpoint_ca_bundle_path",
                )},
            })
        elif path.startswith("/api/v2/admin/model-endpoints") and request.method in {"POST", "PATCH"}:
            saved = copy.deepcopy(request.post_data_json)
            self.connection_writes.append(copy.deepcopy(saved))
            existing = next((item for item in self.endpoints if item["id"] == path.rsplit("/", 1)[-1]), {})
            saved = {**existing, **saved, "id": existing.get("id") or "new-custom"}
            auth = {**existing.get("auth", {}), **saved.get("auth", {})}
            for field in ("api_key", "client_secret", "bearer_token"):
                saved[f"has_{field}"] = bool(auth.pop(field, None)) or existing.get(f"has_{field}", False)
            saved["auth"] = auth
            self.endpoints = [item for item in self.endpoints if item["id"] != saved["id"]] + [saved]
            route.fulfill(json={"endpoint": saved})
        elif path == "/api/v2/admin/default-model" or path.startswith("/api/v2/admin/capability-models/"):
            capability = path.rsplit("/", 1)[-1] if "/capability-models/" in path else "chat"
            route.fulfill(json={
                "selection": {"endpoint_id": "", "model_id": "", "provider": ""},
                "choices": [], "enabled": True, "multi_endpoint_enabled": True,
                "capability": capability, "reason": None,
            })
        elif path == "/api/models/test-model":
            self.model_tests.append(request.post_data_json)
            route.fulfill(json={"success": True})
        elif path == "/api/models/vision-capability":
            route.fulfill(json={"models": {}})
        elif path == "/custom-classic-admin":
            route.fulfill(body=self._markup(), content_type="text/html")
        elif self.classic and path == "/static/js/chat/chat-toast.js":
            route.fulfill(body="export function showToast(message) { document.getElementById('fixture-toasts').textContent = message; }", content_type="text/javascript")
        elif self.classic and path == "/static/js/agents_common.js":
            route.fulfill(body="export const getIconPayload = () => ({}); export const setIconPayload = () => {};", content_type="text/javascript")
        else:
            super()._route(route)

    def _markup(self):
        environment = Environment(
            loader=FileSystemLoader(str(REPO_ROOT / "application" / "single_app" / "templates")),
            autoescape=select_autoescape(["html"]),
        )
        environment.globals["url_for"] = lambda endpoint, **values: "/static/" + values.get("filename", "")
        pane = environment.get_template("admin/_panes/model-endpoints.html").render(
            settings={**self.settings, "gpt_model": {"selected": [], "all": []}},
            admin_landing_tab="model-endpoints", custom_model_endpoint_api_types=self.descriptors,
        )
        return (
            '<!doctype html><html lang="en"><head><meta charset="UTF-8">'
            '<link rel="stylesheet" href="/static/css/bootstrap.min.css">'
            '<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script></head>'
            '<body><div id="fixture-toasts" class="alert alert-info" role="alert"></div>'
            '<form id="admin-settings-form">' + pane + '</form>'
            '<script type="module" src="/static/js/admin/admin_model_endpoints.js"></script></body></html>'
        )

    def open(self, width=1440):
        self.page.set_viewport_size({"width": width, "height": 1100})
        if self.classic:
            self.page.add_init_script(
                "window.modelEndpoints = " + json.dumps(self.endpoints) + ";"
                "window.defaultModelSelection = {};"
                "window.enableMultiModelEndpoints = true;"
            )
            self.page.goto(f"{ORIGIN}/custom-classic-admin", wait_until="networkidle")
            expect(self.page.locator("#model-endpoints-wrapper")).to_be_visible()
        else:
            assert SPA_INDEX.is_file(), "Build the V2 UI before running this test."
            self.page.goto(f"{ORIGIN}/v2/admin", wait_until="networkidle")
            expect(self.page.get_by_role("region", name="AI Connections", exact=True)).to_be_visible()

    def assert_clean(self):
        assert not self.errors, self.errors
        assert not self.unexpected_requests, self.unexpected_requests
