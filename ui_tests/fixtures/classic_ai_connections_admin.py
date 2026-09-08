# classic_ai_connections_admin.py
"""
Classic admin panes with real local scripts and a closed capability API boundary.
Version: 0.261.102
Implemented in: 0.261.102
"""

import json
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect

from ai_connections_admin import AIConnectionsFixture
from v2_admin_settings import ORIGIN, REPO_ROOT


class ClassicAIConnectionsFixture(AIConnectionsFixture):
    """Render the actual Classic image/connection templates without a live Flask app."""

    def _markup(self):
        environment = Environment(
            loader=FileSystemLoader(str(REPO_ROOT / "application" / "single_app" / "templates")),
            autoescape=select_autoescape(["html"]),
        )
        environment.globals["url_for"] = lambda endpoint, **values: "/static/" + values.get("filename", "")
        settings = {
            **self.settings,
            "image_gen_model": {"selected": [], "all": []},
            "gpt_model": {"selected": [], "all": []},
            "enable_semantic_kernel": False,
            "azure_openai_gpt_endpoint": "https://legacy.example.test",
        }
        image = environment.get_template("admin/_panes/image-generation.html").render(
            settings=settings, admin_landing_tab="image-generation",
        )
        connections = environment.get_template("admin/_panes/model-endpoints.html").render(
            settings=settings, admin_landing_tab="model-endpoints",
        )
        return (
            '<!doctype html><html lang="en"><head><meta charset="UTF-8">'
            '<link rel="stylesheet" href="/static/css/bootstrap.min.css">'
            '<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script></head>'
            '<body><div id="fixture-toasts" role="alert"></div>'
            '<button id="launch-walkthrough-btn" class="d-none">Walkthrough</button>'
            '<div class="d-none">'
            + "".join(
                f'<div id="index-warning-{scope}"><span id="missing-fields-{scope}"></span>'
                f'<button id="fix-{scope}-index-btn">Fix index</button></div>'
                for scope in ("user", "group", "public")
            ) +
            '</div><form id="admin-settings-form">'
            + connections + image +
            '</form><script type="module" src="/static/js/admin/admin_model_endpoints.js"></script>'
            '<script type="module" src="/static/js/admin/admin_settings.js"></script></body></html>'
        )

    def _route(self, route):
        path = urlsplit(route.request.url).path
        if not route.request.url.startswith(ORIGIN + "/"):
            return super()._route(route)
        if path == "/classic-admin":
            route.fulfill(body=self._markup(), content_type="text/html")
        elif path == "/static/js/chat/chat-toast.js":
            route.fulfill(body=(
                "export function showToast(message) {"
                "document.getElementById('fixture-toasts').textContent = message;"
                "}"
            ), content_type="text/javascript")
        elif path == "/static/js/chat/chat-utils.js":
            route.fulfill(body="export const sanitizeHttpUrl = value => value;", content_type="text/javascript")
        elif path == "/static/js/agents_common.js":
            route.fulfill(body="export const getIconPayload = () => ({}); export const setIconPayload = () => {};", content_type="text/javascript")
        elif path == "/api/admin/settings/check_index_fields":
            route.fulfill(json={"indexExists": True, "missingFields": []})
        else:
            super()._route(route)

    def open(self):
        self.page.add_init_script(
            "window.modelEndpoints = " + json.dumps(self.endpoints) + ";"
            "window.defaultModelSelection = " + json.dumps(self.selections["chat"]) + ";"
            "window.enableMultiModelEndpoints = " + json.dumps(self.settings["enable_multi_model_endpoints"]) + ";"
            "window.gptSelected = [{deploymentName: 'legacy-chat'}];"
        )
        self.page.goto(f"{ORIGIN}/classic-admin", wait_until="networkidle")
        expect(self.page.locator("#model-endpoints-wrapper")).to_be_visible()
        expect(self.page.get_by_label("Default image model", exact=True)).to_be_enabled()
