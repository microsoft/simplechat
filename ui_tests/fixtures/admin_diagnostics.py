# admin_diagnostics.py
"""
Classic/V2 admin diagnostic fixtures using real templates, schemas, and local assets.
Version: 0.261.125
Implemented in: 0.261.125

All API outcomes are synthetic. The shared Azure Playwright fixture authenticates
to an existing workspace; no application settings or Azure secrets are changed.
"""

import copy
import re
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

from classic_ai_connections_admin import ClassicAIConnectionsFixture
from v2_admin_settings import AdminSettingsFixture, ORIGIN, REPO_ROOT
from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


TEMPLATES = REPO_ROOT / "application" / "single_app" / "templates"
SUCCESS = {
    "success": True,
    "message": "Key Vault list, write, read-back, and temporary-secret cleanup succeeded.",
    "checks": {stage: "passed" for stage in ("list", "write", "read", "cleanup")},
}


class ProbeBoundary:
    def configure_probe(self):
        self.probe_calls = []
        self.probe_response = copy.deepcopy(SUCCESS)
        self.probe_status = 200
        self.hold_probe = False
        self.pending_probe = None
        self.expected_http_errors = 0

    def fulfill(self, route, payload, status=200):
        if status >= 400:
            self.expected_http_errors += 1
        route.fulfill(status=status, json=payload)

    def handle_probe(self, route):
        self.probe_calls.append(copy.deepcopy(route.request.post_data_json))
        if self.hold_probe:
            self.pending_probe = route
        else:
            self.fulfill(route, self.probe_response, self.probe_status)

    def release_probe(self):
        route, self.pending_probe = self.pending_probe, None
        self.fulfill(route, self.probe_response, self.probe_status)

    def assert_clean(self):
        expected_errors = [
            error for error in self.errors
            if error.startswith("Failed to load resource:")
            and any(str(status) in error for status in (400, 404, 409, 500))
        ]
        assert len(expected_errors) <= self.expected_http_errors, self.errors
        assert not [error for error in self.errors if error not in expected_errors], self.errors
        assert not self.unexpected_requests, self.unexpected_requests


class ClassicAdminDiagnosticsFixture(ProbeBoundary, ClassicAIConnectionsFixture):
    def __init__(self, page):
        super().__init__(page)
        self.configure_probe()
        self.settings.update({
            "enable_key_vault_secret_storage": True,
            "key_vault_name": "saved-vault",
            "key_vault_identity": "",
        })
        self.revision = 1
        self.record_metadata = False
        self.hold_indexes = False
        self.pending_index = None
        self.index_requests = []
        self.index_errors = {}
        self.submissions = []

    @property
    def etag(self):
        return f'"revision-{self.revision}"'

    def _markup(self):
        markup = super()._markup()
        source = (TEMPLATES / "admin_settings.html").read_text(encoding="utf-8")
        revision = re.search(r'<input[^>]+name="admin_settings_etag"[^>]+>', source)
        warnings = [
            re.search(rf'<div id="index-warning-{scope}".*?</div>', source, re.DOTALL)
            for scope in ("user", "group", "public")
        ]
        assert revision is not None and all(warnings), "The production diagnostic controls were not found."
        environment = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
        environment.globals["url_for"] = lambda endpoint, **values: "/static/" + values.get("filename", "")
        hidden = environment.from_string(revision.group()).render(settings={"_etag": self.etag})
        secrets = environment.get_template("admin/_panes/secrets.html").render(
            settings=self.settings, admin_landing_tab="secrets",
        )
        guide = environment.get_template("_key_vault_info.html").render(settings=self.settings)
        start = markup.index('<div class="d-none">')
        end = markup.index('<form id="admin-settings-form">', start)
        markup = markup[:start] + "".join(warning.group() for warning in warnings) + markup[end:]
        markup = markup.replace(
            '<form id="admin-settings-form">',
            '<form id="admin-settings-form" method="post" action="/classic-save">' + hidden + secrets,
            1,
        )
        return markup.replace(
            '</form><script',
            '<button id="floating-save-btn" type="submit">Save Settings</button></form>' + guide + '<script',
            1,
        )

    def complete_index(self, route):
        payload = route.request.post_data_json
        if payload.get("settings_etag") != self.etag:
            self.fulfill(route, {
                "code": "settings_conflict", "needsReload": True,
                "error": "Settings changed since this page was loaded.",
            }, 409)
            return
        if payload["indexType"] in self.index_errors:
            status, response = self.index_errors[payload["indexType"]]
            self.fulfill(route, response, status)
            return
        if self.record_metadata:
            self.revision += 1
        self.fulfill(route, {
            "indexExists": True, "missingFields": [], "settings_etag": self.etag,
        })

    def release_indexes(self):
        self.hold_indexes = False
        route, self.pending_index = self.pending_index, None
        self.complete_index(route)

    def _route(self, route):
        if not route.request.url.startswith(ORIGIN + "/"):
            return super()._route(route)
        path = urlsplit(route.request.url).path
        if path == "/api/admin/settings/check_index_fields":
            self.index_requests.append(copy.deepcopy(route.request.post_data_json))
            if self.hold_indexes:
                self.pending_index = route
            else:
                self.complete_index(route)
        elif path == "/api/admin/settings/test_connection":
            self.handle_probe(route)
        elif path == "/api/admin/settings/key-vault/secret-reminders":
            self.fulfill(route, {"reminders": [], "summary": {}, "enabled": False})
        elif path == "/classic-save":
            self.submissions.append(parse_qs(route.request.post_data))
            route.fulfill(body="<html><body>Saved fixture settings.</body></html>", content_type="text/html")
        else:
            super()._route(route)

    def open(self, width=1440):
        super().open(width=width, wait_until="domcontentloaded")
        expect(self.page.locator("#test_key_vault_button")).to_be_visible()


class V2KeyVaultFixture(ProbeBoundary, AdminSettingsFixture):
    def __init__(self, page):
        super().__init__(page)
        self.configure_probe()
        fields = import_app_module("admin_settings_fields")
        group = copy.deepcopy(next(
            group for group in ADMIN_NAV if any(tab["id"] == "secrets" for tab in group["tabs"])
        ))
        tab = next(tab for tab in group["tabs"] if tab["id"] == "secrets")
        tab["sections"] = [section for section in tab["sections"] if section["id"] == "keyvault-section"]
        group["tabs"] = [tab]
        self.schema = {"keyvault-section": [
            field for field in fields.get_admin_settings_fields()["keyvault-section"]
            if field.get("group") == "Vault connection"
        ]}
        self.settings = {
            "enable_key_vault_secret_storage": True,
            "key_vault_name": "saved-vault",
            "key_vault_identity": "",
        }
        self.payload.update({"admin_nav": [group], "field_schema": self.schema, "settings": self.settings})

    def _route(self, route):
        if (
            route.request.url.startswith(ORIGIN + "/")
            and urlsplit(route.request.url).path == "/api/v2/admin/settings/test-connection"
        ):
            self.handle_probe(route)
        else:
            super()._route(route)

    def open(self):
        self.page.goto(f"{ORIGIN}/v2/admin", wait_until="networkidle")
        expect(self.page.get_by_role("heading", name="Key Vault", exact=True)).to_be_visible()
        self.page.get_by_role("button", name=re.compile(r"Vault connection")).click()
        expect(self.page.get_by_label("Key Vault Name", exact=True)).to_be_visible()
