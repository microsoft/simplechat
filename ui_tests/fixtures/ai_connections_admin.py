# ai_connections_admin.py
"""
Closed API fixtures for shared AI Connections admin browser tests.
Version: 0.261.102
Implemented in: 0.261.102

Reuse the built-SPA and local/Azure browser fixtures. All requests are intercepted;
no Azure inference, authentication, or settings services are called.
"""

import copy
from urllib.parse import urlsplit

from playwright.sync_api import expect

from v2_admin_settings import AdminSettingsFixture, ORIGIN, SPA_INDEX, STATIC_ROOT
from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


def support(supported=True, api="chat", source="catalog"):
    return {"supported": supported, "available": supported, "source": source, "api": api, "reason": ""}


def connection(identifier, name, models):
    return {
        "id": identifier, "name": name, "provider": "aoai", "enabled": True,
        "connection": {
            "endpoint": f"https://{identifier}.example.test",
            "openai_api_version": "2024-05-01-preview",
            "operation_settings": {"image_generation": {"api_version": "2025-04-01-preview"}},
        },
        "auth": {"type": "api_key"}, "has_api_key": True, "models": models,
    }


def reference(endpoint_id="", model_id="", provider=""):
    return {"endpoint_id": endpoint_id, "model_id": model_id, "provider": provider}


def image_import_error_notice():
    """Match initialize_ai_connections' retained-settings failure response."""
    return {
        "status": "error",
        "message": (
            "Image connection import could not finish. Review connection and Key Vault permissions. "
            "Existing image settings remain active. Restart after correcting the configuration to retry."
        ),
    }


class AIConnectionsFixture(AdminSettingsFixture):
    """Production V2 components over deterministic, in-memory capability contracts."""

    def __init__(self, page):
        super().__init__(page)
        fields = import_app_module("admin_settings_fields")
        group = copy.deepcopy(next(group for group in ADMIN_NAV if group["id"] == "ai-models"))
        group["tabs"] = [tab for tab in group["tabs"] if tab["id"] in {"model-endpoints", "image-generation"}]
        section_ids = [section["id"] for tab in group["tabs"] for section in tab["sections"]]
        self.schema = {key: copy.deepcopy(fields.get_admin_settings_fields()[key]) for key in section_ids}
        self.settings = {
            field["key"]: copy.deepcopy(field["default"])
            for section in self.schema.values() for field in section
            if field.get("key") and "default" in field
        }
        self.settings.update({"enable_multi_model_endpoints": True, "enable_image_generation": True})
        self.payload.update({"admin_nav": [group], "field_schema": self.schema, "settings": self.settings})
        dual = {
            "id": "same:model", "deploymentName": "same-deployment", "modelName": "gpt-5.6",
            "displayName": "Dual model", "enabled": True,
            "capability_status": {
                "chat": support(), "image_generation": support(api="responses"),
                "vision": {"supported": True, "source": "catalog"},
            },
        }
        imported = {**copy.deepcopy(dual), "displayName": "Imported image model", "enabled_capabilities": ["image_generation"]}
        image = {
            "id": "image-only", "deploymentName": "custom-image-name", "modelName": "gpt-image-1",
            "displayName": "Image only", "enabled": True,
            "capability_status": {"chat": support(False), "image_generation": support(api="images")},
        }
        self.endpoints = [
            connection("team", "Team Azure", [dual]),
            connection("studio", "Imported Studio", [imported]),
            connection("images", "Image Resource", [image]),
        ]
        self.selections = {
            "chat": reference("team", "same:model", "aoai"),
            "image_generation": reference("studio", "same:model", "aoai"),
        }
        self.migration = {"status": "complete", "message": "Existing image configuration is now managed through AI Connections.", "imported_connections": 1}
        self.selection_writes = []
        self.connection_writes = []
        self.image_tests = []
        self.connection_tests = []
        self.reject_selection = False
        self.reject_connection = False
        self.reject_image_test = False
        self.expected_http_errors = 0
        self.capability_reads = []

    def capability_response(self, capability):
        choices = []
        for endpoint in self.endpoints:
            if not endpoint.get("enabled", True):
                continue
            for model in endpoint["models"]:
                status = model.get("capability_status", {}).get(capability, support(False))
                allowed = model.get("enabled_capabilities")
                if not model.get("enabled", True) or not status["supported"] or (allowed is not None and capability not in allowed):
                    continue
                choices.append({
                    **reference(endpoint["id"], model["id"], endpoint["provider"]),
                    "connection_name": endpoint["name"], "label": model["displayName"],
                    "deployment_name": model["deploymentName"], "capability": status,
                })
        selected = self.selections[capability]
        valid = any(item["endpoint_id"] == selected["endpoint_id"] and item["model_id"] == selected["model_id"] for item in choices)
        return {
            "capability": capability,
            "selection": selected,
            "choices": choices,
            "reason": "The saved default is no longer available. Choose a replacement." if selected["endpoint_id"] and not valid else None,
            "enabled": self.settings["enable_multi_model_endpoints" if capability == "chat" else "enable_image_generation"],
            "migration": self.migration,
        }

    def _route(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if not request.url.startswith(ORIGIN + "/"):
            return super()._route(route)
        if path.startswith("/api/v2/admin/capability-models/"):
            capability = path.rsplit("/", 1)[-1]
            if capability not in self.selections:
                self.unexpected_requests.append(path)
                route.fulfill(status=404, json={"error": "Unknown capability"})
            elif request.method == "PUT":
                selected = request.post_data_json["selection"]
                self.selection_writes.append((capability, copy.deepcopy(selected)))
                if self.reject_selection:
                    self.reject_selection = False
                    self.expected_http_errors += 1
                    route.fulfill(status=400, json={"error": "The image default could not be saved."})
                else:
                    self.selections[capability] = selected
                    if capability == "image_generation":
                        self.settings["image_generation_model_selection"] = copy.deepcopy(selected)
                        self.settings["ai_connections_image_migration_version"] = 1
                    route.fulfill(json=self.capability_response(capability))
            else:
                self.capability_reads.append(capability)
                route.fulfill(json=self.capability_response(capability))
        elif path == "/api/v2/admin/model-endpoints" and request.method == "GET":
            route.fulfill(json={"endpoints": self.endpoints, "multi_endpoint_enabled": self.settings["enable_multi_model_endpoints"], "migration": self.migration})
        elif path == "/api/v2/admin/model-endpoints" and request.method == "POST":
            saved = request.post_data_json
            self.connection_writes.append(copy.deepcopy(saved))
            saved["id"] = "manual-connection"
            for model in saved["models"]:
                catalog_entry = {
                    "gpt-image-1": {"chat": False, "image_generation": True},
                }.get(model.get("modelName"), {})
                model["capability_status"] = {
                    "chat": support(
                        model.get("supportsChat", catalog_entry.get("chat", True)),
                        source="declared" if "supportsChat" in model else "catalog",
                    ),
                    "image_generation": support(
                        model.get("supportsImageGeneration", catalog_entry.get("image_generation", False)),
                        api="images", source="declared" if "supportsImageGeneration" in model else "catalog",
                    ),
                }
            saved["has_api_key"] = bool(saved.get("auth", {}).pop("api_key", ""))
            self.endpoints.append(saved)
            route.fulfill(json={"endpoint": saved})
        elif path.startswith("/api/v2/admin/model-endpoints/") and request.method == "PATCH":
            endpoint = next(item for item in self.endpoints if item["id"] == path.rsplit("/", 1)[-1])
            changes = request.post_data_json
            self.connection_writes.append(copy.deepcopy(changes))
            if self.reject_connection:
                self.reject_connection = False
                self.expected_http_errors += 1
                route.fulfill(status=400, json={"error": "The connection could not be saved."})
            else:
                endpoint.update(changes)
                route.fulfill(json={"endpoint": endpoint})
        elif path == "/api/v2/admin/settings/test-connection" and request.method == "POST":
            self.image_tests.append(request.post_data_json)
            route.fulfill(json={"success": not self.reject_image_test, "error": "The saved model did not return an image." if self.reject_image_test else ""})
        elif path == "/api/models/test-connection":
            self.connection_tests.append(request.post_data_json)
            route.fulfill(json={"success": True, "count": 2})
        elif path == "/api/models/vision-capability":
            route.fulfill(json={"models": {}})
        else:
            super()._route(route)

    def open(self, width=1440):
        assert SPA_INDEX.is_file(), "Build the V2 SPA before running browser tests."
        source_root = STATIC_ROOT.parent.parent / "v2_ui" / "src"
        assert not any(path.stat().st_mtime > SPA_INDEX.stat().st_mtime for path in source_root.rglob("*") if path.is_file()), "Rebuild the V2 SPA before running browser tests."
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": width < 1024}
        self.page.set_viewport_size({"width": width, "height": 1100})
        self.page.goto(f"{ORIGIN}/v2/admin", wait_until="networkidle")
        expect(self.page.get_by_role("region", name="AI Connections", exact=True)).to_be_visible()
        expect(self.page.get_by_label("Default image model", exact=True)).to_be_enabled()

    def assert_clean(self):
        resource_errors = [error for error in self.errors if error.startswith("Failed to load resource:") and "400" in error]
        assert len(resource_errors) <= self.expected_http_errors
        assert not [error for error in self.errors if error not in resource_errors], self.errors
        assert not self.unexpected_requests, self.unexpected_requests
