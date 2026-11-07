# workflow_admin_limits.py
"""
Closed Classic/V2 fixtures for production For-each and Repeat policy fields.
Version: 0.261.120
Implemented in: 0.261.117

Repeat-until policy coverage was added in 0.261.120.
"""

import copy
import re
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

from ui_tests.fixtures.v2_admin_settings import (
    ADMIN_NAV,
    ORIGIN,
    REPO_ROOT,
    SPA_INDEX,
    AdminSettingsFixture,
    connect_options,  # noqa: F401
    import_app_module,
)


class WorkflowAdminLimitsFixture(AdminSettingsFixture):
    """Use the actual field registry, template and normalizer without live settings."""

    def __init__(self, page):
        super().__init__(page)
        self.fields = import_app_module("admin_settings_fields")
        self.schema = {
            "workflow-settings-section": copy.deepcopy(
                self.fields.get_admin_settings_fields()["workflow-settings-section"]
            ),
        }
        self.settings = {
            field["key"]: copy.deepcopy(field["default"])
            for field in self.schema["workflow-settings-section"]
            if "key" in field and "default" in field
        }
        self.rejected_patches = 0
        self.payload.update({
            "settings": self.settings,
            "field_schema": self.schema,
            "admin_nav": [copy.deepcopy(next(group for group in ADMIN_NAV if group["id"] == "workflow"))],
        })

    def _classic_markup(self):
        environment = Environment(
            loader=FileSystemLoader(str(REPO_ROOT / "application" / "single_app" / "templates")),
            autoescape=select_autoescape(["html"]),
        )
        pane = environment.get_template("admin/_panes/workflow.html").render(
            settings=self.settings, admin_landing_tab="workflow",
        )
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<link rel="stylesheet" href="/static/css/bootstrap.min.css"></head>'
            '<body><main class="container py-3"><form id="workflow-settings-fixture">'
            + pane + '</form></main></body></html>'
        )

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN:
            if parsed.path == "/classic-workflow-admin":
                route.fulfill(body=self._classic_markup(), content_type="text/html")
                return
            if parsed.path == "/api/v2/admin/settings" and route.request.method == "PATCH":
                updates = route.request.post_data_json["settings"]
                self.patches.append(copy.deepcopy(updates))
                normalized, errors, _warnings = self.fields.normalize_admin_settings_updates(
                    updates, current_settings=self.settings,
                )
                if errors:
                    self.rejected_patches += 1
                    route.fulfill(status=400, json={"error": "Invalid settings.", "field_errors": errors})
                else:
                    self.settings.update(normalized)
                    route.fulfill(json={"settings": normalized, "updated_keys": list(normalized)})
                return
        super()._route(route)

    def open_workflow(self, *, classic=False, width=1440):
        if not classic:
            assert SPA_INDEX.is_file(), "Build the V2 SPA before running this test."
            source = REPO_ROOT / "application" / "v2_ui" / "src"
            assert all(
                path.stat().st_mtime <= SPA_INDEX.stat().st_mtime
                for path in source.rglob("*") if path.is_file()
            ), "The production V2 bundle is stale."
        self.preferences.update({"darkModeEnabled": False, "v2RailCollapsed": width < 1024, "fontSizePreference": "m"})
        self.page.set_viewport_size({"width": width, "height": 900})
        self.page.goto(f"{ORIGIN}/{'classic-workflow-admin' if classic else 'v2/admin'}", wait_until="networkidle")
        expect(self.page.get_by_label("Workflow Loop Item Limit", exact=True)).to_be_visible()

    def assert_clean(self):
        if self.rejected_patches:
            self.errors = [
                error for error in self.errors
                if not re.fullmatch(r"Failed to load resource: the server responded with a status of 400 \([^)]*\)", error)
            ]
        super().assert_clean()
