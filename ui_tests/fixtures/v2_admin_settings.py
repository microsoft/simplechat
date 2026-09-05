# v2_admin_settings.py
"""
Schema-backed browser fixtures for V2 Admin Settings.
Version: 0.261.093
Implemented in: 0.261.093

Serve the real built SPA through Playwright request interception, using the real
Agents field schema and synthetic settings. No application server, signed-in
account, or live settings writes are needed. Unexpected requests fail the test.

The default browser is local. To use Azure Playwright, set PLAYWRIGHT_SERVICE_URL
and PLAYWRIGHT_WORKSPACE_RESOURCE_ID. The workspace is read with
azure-mgmt-playwright and authenticated with DefaultAzureCredential; no resources
are created and no access tokens are stored.
"""

import copy
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest
from azure.identity import DefaultAzureCredential
from azure.mgmt.playwright import PlaywrightMgmtClient
from playwright.sync_api import Page, Route, expect

# Reuse the existing isolated application imports rather than initializing Azure clients.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
ORIGIN = "http://simplechat.test"
AGENT_SECTION_IDS = (
    "agents-config",
    "agent-toggles-card",
    "agents-page-customization-card",
    "agent-template-approvals-section",
)


@pytest.fixture(scope="session")
def connect_options():
    """Let pytest-playwright use the configured Azure workspace, or a local browser."""
    service_url = os.getenv("PLAYWRIGHT_SERVICE_URL", "")
    if not service_url:
        return {}

    resource_id = os.getenv("PLAYWRIGHT_WORKSPACE_RESOURCE_ID", "")
    parts = resource_id.strip("/").split("/")
    if (
        len(parts) != 8
        or parts[0].lower() != "subscriptions"
        or parts[2].lower() != "resourcegroups"
        or parts[4].lower() != "providers"
        or parts[5].lower() != "microsoft.loadtestservice"
        or parts[6].lower() != "playwrightworkspaces"
    ):
        raise ValueError("Set PLAYWRIGHT_WORKSPACE_RESOURCE_ID to the workspace's ARM resource ID.")

    endpoint = urlsplit(service_url)
    with DefaultAzureCredential() as credential:
        with PlaywrightMgmtClient(credential, parts[1]) as client:
            workspace = client.playwright_workspaces.get(parts[3], parts[7])
        dataplane_uri = workspace.properties.dataplane_uri if workspace.properties else None
        if (
            endpoint.scheme != "wss"
            or not dataplane_uri
            or endpoint.hostname != urlsplit(dataplane_uri).hostname
        ):
            raise ValueError("PLAYWRIGHT_SERVICE_URL must target the configured Azure workspace.")
        token = credential.get_token("https://management.azure.com/.default").token

    query = dict(parse_qsl(endpoint.query))
    query.update({
        "os": "linux",
        "runId": os.getenv("PLAYWRIGHT_SERVICE_RUN_ID") or str(uuid4()),
        "api-version": "2025-09-01",
    })
    return {
        "ws_endpoint": urlunsplit(endpoint._replace(query=urlencode(query))),
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 180000,
    }


class AdminSettingsFixture:
    """Load the production admin page with a closed, in-memory API boundary."""

    def __init__(self, page: Page):
        self.page = page
        fields_module = import_app_module("admin_settings_fields")
        schema = fields_module.get_admin_settings_fields()
        group = copy.deepcopy(next(item for item in ADMIN_NAV if item["id"] == "agents-actions"))
        agents_tab = next(tab for tab in group["tabs"] if tab["id"] == "agents")
        actions_tab = next(tab for tab in group["tabs"] if tab["id"] == "actions")
        actions_tab["sections"] = [
            section for section in actions_tab["sections"] if section["id"] == "core-plugin-toggles"
        ]
        group["tabs"] = [agents_tab, actions_tab]
        section_ids = (*AGENT_SECTION_IDS, "core-plugin-toggles")
        self.schema = {section_id: copy.deepcopy(schema[section_id]) for section_id in section_ids}
        self.settings = {
            field["key"]: copy.deepcopy(field["default"])
            for fields in self.schema.values()
            for field in fields
            if field.get("key") and "default" in field
        }
        self.settings.update({
            "enable_semantic_kernel": True,
            "per_user_semantic_kernel": True,
            "allow_user_agents": True,
        })
        self.payload = {
            "settings": self.settings,
            "admin_nav": [group],
            "field_schema": self.schema,
            "section_status": {},
            "runtime_flags": {},
            "suppressed_capabilities": fields_module.get_suppressed_capability_keys(),
        }
        self.preferences = {}
        self.catalog_agents = [
            {
                "catalog_key": "global:research",
                "display_name": "Quarterly Research Assistant",
                "scope_label": "Enterprise",
                "scope_type": "global",
                "window": "both",
            },
            {
                "catalog_key": "global:roadmap",
                "display_name": "Roadmap Advisor",
                "scope_label": "Enterprise",
                "scope_type": "global",
                "window": "both",
            },
        ]
        self.patches = []
        self.reject_next_save = False
        self.errors = []
        self.unexpected_requests = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on(
            "console",
            lambda message: self.errors.append(message.text) if message.type == "error" else None,
        )
        page.route("**/*", self._route)

    def _bootstrap(self):
        return {
            "version": "0.261.093",
            "user": {"id": "test-admin", "display_name": "Test Admin", "is_admin": True, "roles": ["Admin"]},
            "branding": {"app_title": "SimpleChat", "show_logo": False, "hide_app_title": False},
            "features": {},
            "catalogs": {"models": [], "agents": [], "prompts": [], "initial_model_selection": None},
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {
                "custom_pages": {"enabled": False, "items": []},
                "external_links": {"enabled": False, "items": []},
            },
            "workspace": {"sections": {}},
            "admin_nav": self.payload["admin_nav"],
            "settings": {},
        }

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
            return

        if request.method == "GET" and path == "/v2/admin":
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
        elif request.method == "GET" and path.startswith("/static/"):
            asset = (STATIC_ROOT / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file():
                route.fulfill(path=str(asset))
            else:
                self.unexpected_requests.append(path)
                route.fulfill(status=404, body="Fixture asset not found")
        elif path == "/api/v2/bootstrap" and request.method == "GET":
            route.fulfill(json=self._bootstrap())
        elif path == "/api/user/settings" and request.method == "GET":
            route.fulfill(json={"settings": self.preferences})
        elif path == "/api/user/settings" and request.method == "POST":
            self.preferences.update(request.post_data_json["settings"])
            route.fulfill(json={"message": "Saved fixture preferences."})
        elif path == "/api/v2/admin/settings" and request.method == "GET":
            route.fulfill(json=self.payload)
        elif path == "/api/v2/admin/settings" and request.method == "PATCH":
            updates = request.post_data_json["settings"]
            self.patches.append(copy.deepcopy(updates))
            if self.reject_next_save:
                self.reject_next_save = False
                route.fulfill(status=400, json={
                    "error": "Invalid settings.",
                    "field_errors": {key: "Fixture validation error." for key in updates},
                })
            else:
                self.settings.update(updates)
                route.fulfill(json={"settings": updates, "updated_keys": list(updates)})
        elif path == "/api/orchestration_types" and request.method == "GET":
            route.fulfill(json=[{"value": "default_agent", "label": "Single agent"}])
        elif path == "/api/orchestration_settings" and request.method == "GET":
            route.fulfill(json={"orchestration_type": "default_agent", "max_rounds_per_agent": 1})
        elif path == "/api/agents/catalog" and request.method == "GET":
            route.fulfill(json={"agents": self.catalog_agents})
        else:
            self.unexpected_requests.append(f"{request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def open(self, theme="light", width=1440, font_size="m"):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        source_root = REPO_ROOT / "application" / "v2_ui" / "src"
        if any(
            path.stat().st_mtime > SPA_INDEX.stat().st_mtime
            for path in source_root.rglob("*")
            if path.is_file()
        ):
            pytest.fail("The V2 bundle is stale. Run npm --prefix application/v2_ui run build")
        self.preferences = {
            "darkModeEnabled": theme == "dark",
            "v2RailCollapsed": width < 1024,
            "fontSizePreference": font_size,
        }
        self.page.set_viewport_size({"width": width, "height": 1000})
        self.page.goto(f"{ORIGIN}/v2/admin", wait_until="networkidle")
        expect(self.page.get_by_role("region", name="Agent Runtime", exact=True)).to_be_visible()
        expect(self.page.locator("html")).to_have_attribute("data-font-size", font_size)

    def capture(self, name):
        artifacts = REPO_ROOT / "ui_tests" / "artifacts" / "v2_admin_agents"
        artifacts.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(
            path=str(artifacts / f"{name}.png"), full_page=True, animations="disabled"
        )

    def assert_clean(self):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors
