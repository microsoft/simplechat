# test_shared_workspace_secret_editing.py
"""Production classic group editors retain write-only credentials safely.

Version: 0.261.428
Implemented in: 0.261.428

Real modal partials, Bootstrap, steppers and workspace event handlers run in the
configured local/Azure Playwright browser. Only synthetic APIs are intercepted.
"""

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.agent_delegation_classic.harness import (
    build_agent_modal_page,
    build_plugin_modal_page,
    read_partial,
)
from ui_tests.fixtures.playwright_connection import connect_options


pytestmark = pytest.mark.ui
APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "http://shared-credentials.test"
MASK = "***REDACTED***"
SPEC = {"openapi": "3.0.0", "info": {"title": "Shared API", "version": "1"}, "paths": {}}


def action_record(method="api_key"):
    return {
        "id": "shared-action", "name": "shared_action", "displayName": "Shared action",
        "description": "Shared action description", "type": "openapi",
        "endpoint": "https://service.invalid", "auth": {"type": "key", "key": MASK},
        "metadata": {}, "additionalFields": {
            "auth_method": method, "openapi_spec_content": SPEC, "openapi_source_type": "content",
            **({"api_key_location": "header", "api_key_name": "X-API-Key"} if method == "api_key" else {}),
        },
        "group_id": "group-a", "is_group": True, "is_global": False,
        "revision": "revision-1", "secret_paths": ["/auth/key"], "read_only": False,
    }


def agent_record():
    return {
        "id": "shared-agent", "name": "shared_agent", "display_name": "Shared agent",
        "description": "Shared agent description", "instructions": "Be helpful.",
        "agent_type": "local", "actions_to_load": [], "other_settings": {},
        "azure_openai_gpt_endpoint": "https://model.invalid",
        "azure_openai_gpt_deployment": "gpt-4o", "azure_openai_gpt_api_version": "2024-10-21",
        "azure_openai_gpt_key": MASK, "enable_agent_gpt_apim": False,
        "max_completion_tokens": -1, "group_id": "group-a", "is_group": True, "is_global": False,
        "revision": "revision-1", "secret_paths": ["/azure_openai_gpt_key"], "read_only": False,
    }


class SharedEditorFixture:
    def __init__(self, page, family, record, *, member=False, save_status=200, role=None):
        self.page, self.family, self.record = page, family, deepcopy(record)
        self.member, self.save_status = member, save_status
        self.role = role or ("User" if member else "Owner")
        self.posts, self.errors, self.details = [], [], []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self.route)

    def route(self, route):
        url = urlsplit(route.request.url)
        path, method = url.path, route.request.method
        if url.netloc != urlsplit(ORIGIN).netloc:
            self.errors.append(f"Unexpected external request: {url.netloc}")
            route.abort()
            return
        if "/static/" in path:
            relative = path.split("/static/", 1)[1]
            asset = (APP / "static" / relative).resolve()
            if asset.is_relative_to(APP / "static") and asset.is_file():
                route.fulfill(path=str(asset))
            else:
                self.errors.append(f"Missing local asset: {relative}")
                route.abort()
            return
        if path.startswith("/api/"):
            base = f"/api/group/{self.family}"
            if path == base and method == "GET":
                record = self.record
                if self.member:
                    record = {key: record[key] for key in ("id", "name", "description", "group_id", "is_group")}
                    record.update(read_only=True, is_global=False)
                self.json(route, {"actions" if self.family == "plugins" else "agents": [record]})
            elif path.startswith(base + "/") and method == "GET" and not path.endswith("/types"):
                self.details.append(route.request.url)
                self.json(route, self.record)
            elif path.startswith(base) and method in ("PATCH", "POST"):
                self.posts.append({"url": route.request.url, "body": route.request.post_data_json})
                self.json(route, self.record if self.save_status == 200 else {
                    "error": "This resource changed. Reload it before saving.",
                }, self.save_status)
            elif path.endswith("/plugins/types"):
                kind = self.record.get("type", "openapi")
                self.json(route, [{"type": kind, "display": kind, "description": "Shared capability"}])
            elif "/agent/settings" in path:
                self.json(route, {
                    "allow_group_agents": True, "allow_group_custom_endpoints": True,
                    "allow_user_agents": True, "allow_user_custom_endpoints": True,
                    "allow_group_ai_foundry_agents": True, "allow_group_new_foundry_agents": True,
                    "semantic_kernel_agents": [], "gpt_model": {"selected": ["gpt-4o"]},
                    "model_endpoints": [], "per_user_semantic_kernel": True,
                })
            elif path.endswith("/presets"):
                self.json(route, {"presets": []})
            elif path.endswith("/preconfigurations"):
                self.json(route, {"preconfigurations": []})
            elif "identities" in path:
                self.json(route, {"identities": []})
            elif path.endswith("/validate"):
                self.json(route, {"valid": True, "errors": []})
            elif path.endswith("/merge_settings"):
                self.json(route, route.request.post_data_json or {})
            else:
                self.json(route, {})
            return
        route.fulfill(content_type="text/html", body=self.html())

    @staticmethod
    def json(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def html(self):
        if self.family == "plugins":
            page = build_plugin_modal_page(read_partial("_plugin_modal.html"))
            shell = """
                <div id="group-plugins-root"></div>
                <template id="group-plugins-table-template">
                    <div id="group-plugins-list-view"><table id="plugins-table"><tbody id="group-plugins-table-body"></tbody></table></div>
                    <div id="group-plugins-grid-view" class="d-none"></div>
                </template>
            """
            asset, fetch = "group_plugins.js", "fetchGroupPlugins"
        else:
            page = build_agent_modal_page(read_partial("_agent_modal.html"))
            shell = """
                <div id="group-agents-list-view"><table><tbody id="group-agents-table-body"></tbody></table></div>
                <div id="group-agents-grid-view" class="d-none"></div>
            """
            asset, fetch = "group_agents.js", "fetchGroupAgents"
        context = {
            "activeGroupId": "group-a", "activeGroupName": "Group A",
            "userRole": self.role,
        }
        return page.replace("</body>", shell + f"""
            <script>window.groupWorkspaceContext = {json.dumps(context)};
                window.currentGroupStatus = 'active'; var current_user_id = 'owner';
                var appSettings = {{allow_group_custom_endpoints: true, allow_user_custom_endpoints: true,
                    allow_group_agents: true, enable_semantic_kernel: true}};</script>
            <script type="module">
                import '/application/single_app/static/js/workspace/{asset}';
                await window.{fetch}();
                window.sharedEditorReady = true;
            </script></body>""")

    def open(self):
        self.page.goto(ORIGIN)
        self.page.wait_for_function("window.sharedEditorReady === true")

    def edit(self):
        self.open()
        selector = ".edit-group-plugin-btn" if self.family == "plugins" else ".edit-group-agent-btn"
        self.page.locator(selector).first.click()
        expect(self.page.locator("[data-shared-credentials]")).to_be_visible()

    def assert_clean(self):
        assert self.errors == []
        assert self.page.evaluate("window.__xssFired !== true")


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("method", ["api_key", "basic"])
def test_group_action_untouched_secret_and_basic_auth_roundtrip(page, width, method):
    page.set_viewport_size({"width": width, "height": 900})
    ui = SharedEditorFixture(page, "plugins", action_record(method))
    ui.edit()
    page.locator("#plugin-description").fill("Edited without revealing credentials")
    page.evaluate("window.pluginModalStepper.goToStep(3)")
    expect(page.locator("#openapi-config-section")).to_be_visible()
    page.evaluate("window.pluginModalStepper.goToStep(5)")
    page.locator("#save-plugin-btn").click()
    page.wait_for_function("!document.getElementById('plugin-modal').classList.contains('show')")
    assert len(ui.posts) == 1
    body = ui.posts[0]["body"]
    assert body.get("auth", {}).get("key") == MASK, body
    assert body["expected_revision"] == "revision-1"
    assert body["clear_secret_paths"] == []
    assert "group_id=group-a" in ui.posts[0]["url"]
    assert ui.details and "group_id=group-a" in ui.details[0]
    ui.assert_clean()


@pytest.mark.parametrize("mode", ["replace", "clear", "conflict"])
def test_group_action_explicit_secret_changes_and_visible_conflict(page, mode):
    ui = SharedEditorFixture(page, "plugins", action_record(), save_status=409 if mode == "conflict" else 200)
    ui.edit()
    page.evaluate("window.pluginModalStepper.goToStep(3)")
    if mode == "replace":
        page.locator("#plugin-auth-api-key-value").fill("SYNTHETIC-new-key")
    elif mode == "clear":
        page.locator("#plugin-auth-type").select_option("none")
        page.get_by_label("Clear auth / key", exact=True).check()
    page.evaluate("window.pluginModalStepper.goToStep(5)")
    page.locator("#save-plugin-btn").click()
    if mode == "conflict":
        expect(page.locator("#plugin-modal-error")).to_contain_text("Reload it before saving")
        expect(page.locator("#save-plugin-btn")).to_be_enabled()
        expect(page.locator("#plugin-modal")).to_be_visible()
    else:
        page.wait_for_function("!document.getElementById('plugin-modal').classList.contains('show')")
    assert len(ui.posts) == 1
    body = ui.posts[0]["body"]
    assert body["auth"]["key"] == ("SYNTHETIC-new-key" if mode == "replace" else "" if mode == "clear" else MASK)
    assert body["clear_secret_paths"] == (["/auth/key"] if mode == "clear" else [])
    ui.assert_clean()


@pytest.mark.parametrize("mode", ["unchanged", "replace", "clear", "reentry"])
def test_group_agent_stored_secret_intent_uses_real_save_handler(page, mode):
    record = agent_record()
    if mode == "reentry":
        record["credential_reentry_required"] = [{"path": "/azure_openai_gpt_key", "label": "Model API key"}]
    ui = SharedEditorFixture(page, "agents", record)
    ui.edit()
    page.evaluate("window.agentModalStepper.goToStep(window.agentModalStepper.getStepNumber('model'))")
    if mode == "replace":
        page.locator("#agent-gpt-key").fill("SYNTHETIC-new-model-key")
    elif mode == "clear":
        page.get_by_label("Clear azure_openai_gpt_key", exact=True).check()
    page.evaluate("window.agentModalStepper.goToStep(window.agentModalStepper.getStepNumber('summary'))")
    page.locator("#agent-modal-save-btn").click()
    page.wait_for_function("!document.getElementById('agentModal').classList.contains('show')")
    assert len(ui.posts) == 1
    body = ui.posts[0]["body"]
    assert body["expected_revision"] == "revision-1"
    if mode in ("clear", "reentry"):
        assert "azure_openai_gpt_key" not in body
        assert body["clear_secret_paths"] == (["/azure_openai_gpt_key"] if mode == "clear" else [])
    else:
        assert body["azure_openai_gpt_key"] == ("SYNTHETIC-new-model-key" if mode == "replace" else MASK)
    assert "group_id=group-a" in ui.posts[0]["url"]
    ui.assert_clean()


@pytest.mark.parametrize("family", ["plugins", "agents"])
@pytest.mark.parametrize("role", ["User", "Owner"])
def test_group_member_metadata_views_do_not_offer_editing(page, family, role):
    record = action_record() if family == "plugins" else agent_record()
    ui = SharedEditorFixture(page, family, record, member=True, role=role)
    ui.open()
    assert page.locator(".edit-group-plugin-btn, .edit-group-agent-btn").count() == 0
    assert "Shared" in page.locator("body").inner_text()
    assert not ui.posts
    ui.assert_clean()


@pytest.mark.parametrize("partial", [False, True])
def test_basic_auth_replacement_requires_both_values(page, partial):
    ui = SharedEditorFixture(page, "plugins", action_record("basic"))
    ui.edit()
    page.evaluate("window.pluginModalStepper.goToStep(3)")
    if not partial:
        page.locator("#plugin-auth-basic-username").fill("replacement-user")
    page.locator("#plugin-auth-basic-password").fill("SYNTHETIC-new-password")
    page.evaluate("window.pluginModalStepper.goToStep(5)")
    page.locator("#save-plugin-btn").click()
    if partial:
        expect(page.locator("#plugin-modal-error")).to_contain_text("Re-enter both the username and password")
        assert ui.posts == []
    else:
        page.wait_for_function("!document.getElementById('plugin-modal').classList.contains('show')")
        assert ui.posts[0]["body"]["auth"]["key"] == "replacement-user:SYNTHETIC-new-password"
    ui.assert_clean()


@pytest.mark.parametrize("width", [390, 1440])
def test_stored_secret_labels_are_inert_and_wrap(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    record = action_record()
    label = "<img src=x onerror=window.__xssFired=true>__Secret"
    record["secret_paths"].append(f"/additionalFields/{label}")
    ui = SharedEditorFixture(page, "plugins", record)
    ui.edit()
    notice = page.locator("[data-shared-credentials]")
    expect(notice).to_contain_text(label)
    assert notice.locator("img, script").count() == 0
    box = notice.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= width
    ui.assert_clean()


@pytest.mark.parametrize("kind", ["sql_query", "mcp", "blob_storage"])
def test_structured_connector_fields_keep_stored_secret_markers(page, kind):
    record = action_record()
    record["type"] = kind
    if kind == "sql_query":
        record["auth"] = {"type": "username_password", "identity": "fixture-user", "key": MASK}
        record["additionalFields"] = {
            "database_type": "sqlserver", "server": "sql.invalid", "database": "fixture",
            "username": "fixture-user", "password": MASK,
        }
        record["secret_paths"] = ["/auth/key", "/additionalFields/password"]
    elif kind == "mcp":
        record["auth"] = {"type": "NoAuth"}
        record["endpoint"] = "https://mcp.invalid"
        record["additionalFields"] = {
            "transport": "streamable_http", "auth_method": "none", "custom_headers": {"X-Secret": MASK},
        }
        record["secret_paths"] = ["/additionalFields/custom_headers/X-Secret"]
    else:
        record["auth"] = {"type": "connection_string", "key": MASK}
        record["endpoint"] = "https://fixture.blob.core.windows.net"
        record["additionalFields"] = {"container_name": "documents"}
    ui = SharedEditorFixture(page, "plugins", record)
    ui.edit()
    page.evaluate("window.pluginModalStepper.goToStep(3)")
    page.evaluate("window.pluginModalStepper.goToStep(5)")
    page.locator("#save-plugin-btn").click()
    page.wait_for_function("!document.getElementById('plugin-modal').classList.contains('show')")
    assert len(ui.posts) == 1
    body = ui.posts[0]["body"]
    if kind == "sql_query":
        assert body["additionalFields"]["password"] == MASK
    elif kind == "mcp":
        assert body["additionalFields"]["custom_headers"]["X-Secret"] == MASK
    else:
        assert body["auth"]["key"] == MASK
    assert body["clear_secret_paths"] == []
    assert body["expected_revision"] == "revision-1"
    ui.assert_clean()
