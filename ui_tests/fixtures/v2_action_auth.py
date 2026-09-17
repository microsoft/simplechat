# v2_action_auth.py
"""
Closed, synthetic API fixture for real-SPA per-user action authentication.
Version: 0.261.107
Implemented in: 0.261.107

Reuse the existing workspace and Azure Playwright connection harness. Build with
the installed Vite toolchain into ignored UI artifacts, not production assets.
"""

import base64
import copy
import json
import mimetypes
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect

# The existing connection fixture uses this sibling import for local/Azure parity.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui_tests.fixtures.workspace_authoring import (  # noqa: E402
    GLOBAL_ACTION_ID,
    GLOBAL_AGENT_ID,
    ORIGIN,
    WorkspaceAuthoringFixture,
    connect_options,
)


ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "application" / "v2_ui"
BUILD = ROOT / "ui_tests" / "artifacts" / "v2_action_auth_build"
VERSION = "0.261.107"
SHARED_ID = "shared-visible-yamcs"
REQUIREMENT_ID = "11111111-1111-4111-8111-111111111111"
ACTION_REF = f"action:v1:global:Z2xvYmFs:{base64.urlsafe_b64encode(GLOBAL_ACTION_ID.encode('utf-8')).decode('ascii').rstrip('=')}"
PROFILE_TYPES = {
    "yamcs_login": "username_password",
    "http_basic": "username_password",
    "bearer_token": "bearer_token",
    "api_key": "api_key",
}


@pytest.fixture(scope="session")
def action_auth_build():
    """Use only the already installed production builder; output remains test-owned."""
    index = BUILD / "index.html"
    sources = [item for item in (V2 / "src").rglob("*") if item.is_file()]
    if not index.exists() or any(item.stat().st_mtime > index.stat().st_mtime for item in sources):
        result = subprocess.run(
            ["node", str(V2 / "node_modules" / "vite" / "bin" / "vite.js"),
             "build", "--outDir", str(BUILD), "--emptyOutDir"],
            cwd=V2, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, f"Existing Vite build failed:\n{result.stdout}\n{result.stderr}"
    return BUILD


class ActionAuthFixture(WorkspaceAuthoringFixture):
    def __init__(self, page, *, actor="fixture-bob"):
        super().__init__(page)
        self.actor = actor
        self.ready_identity = False
        self.request_counter = 0
        self.request_id = None
        self.request_shared = False
        self.cancelled = set()
        self.consumed = set()
        self.expected_repair_context = None
        self.private_identities = {}
        self.private_secrets = {}
        self.orchestration_enabled = False
        self.approval_mode = "manual"
        self.runtime_rejection = False
        self.execution_started = True
        self.control_discriminator = "error_code"
        self.requirement_reason = None
        self.global_actions = [{
            "id": GLOBAL_ACTION_ID, "name": "published-yamcs", "displayName": "Published Yamcs",
            "description": "Read mission telemetry.", "type": "yamcs", "is_enabled": True,
            "endpoint": "https://yamcs.example.test/mission",
            "auth": {"type": "username_password"},
            "additionalFields": {
                "instance": "simulator", "auth_method": "username_password",
                "tls_verify": True, "read_only": True,
                "hidden_setting": {"keep": True, "zero": 0},
            },
            "metadata": {"hidden_metadata": {"keep": True}},
            "credential_requirement": {
                "id": REQUIREMENT_ID, "source": "current_user", "identity_name": "Yamcs", "profile": "yamcs_login",
            },
        }]
        self.actions[GLOBAL_ACTION_ID] = {**copy.deepcopy(self.global_actions[0]), "is_global": True}
        self.secret_paths[GLOBAL_ACTION_ID] = []
        self.options["settings"]["allow_user_plugins"] = False
        self.agents[GLOBAL_AGENT_ID].update({
            "name": "yamcs-agent", "display_name": "Mission Yamcs", "is_global": True,
            "actions_to_load": [GLOBAL_ACTION_ID],
        })
        self.shared_conversation = {
            "id": SHARED_ID, "conversation_kind": "collaborative", "title": "Shared mission",
            "can_post_messages": True, "can_manage_members": False, "can_accept_invite": False,
            "membership_status": "accepted", "current_user_role": "User",
            "owner_user_ids": ["fixture-alice"], "accepted_participant_ids": ["fixture-alice", "fixture-bob"],
            "participants": [
                {"user_id": "fixture-alice", "display_name": "Alice", "role": "Owner", "status": "accepted"},
                {"user_id": "fixture-bob", "display_name": "Bob", "role": "User", "status": "accepted"},
            ],
        }
        self.conversations.append(copy.deepcopy(self.shared_conversation))
        self.messages[SHARED_ID] = [{
            "id": "shared-history", "conversation_id": SHARED_ID, "role": "assistant",
            "content": "Previous shared telemetry result.", "timestamp": "2026-09-10T10:00:00Z",
        }]
        self.plan = None

    def _bootstrap(self):
        data = super()._bootstrap()
        data["version"] = VERSION
        data["user"] = {"id": self.actor, "display_name": self.actor, "is_admin": True, "roles": ["Admin", "User"]}
        data["features"].update({
            "per_user_semantic_kernel": False,
            "enable_chat_orchestration": self.orchestration_enabled,
            "enable_collaborative_conversations": True,
            "enable_chat_file_uploads": True,
        })
        data["orchestration"] = {
            "enabled": self.orchestration_enabled, "show_manual_controls": True,
            "default_approval_mode": self.approval_mode, "allow_user_approval_override": False,
            "timed_approval_seconds": 0,
        }
        data["catalogs"]["agents"] = [
            item for item in data["catalogs"]["agents"] if item["id"] == GLOBAL_AGENT_ID
        ]
        data["admin_nav"] = [{"id": "agents-actions", "label": "Agents & actions", "tabs": []}]
        return data

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            return super()._route(route)
        path = unquote(parsed.path)
        if request.method == "GET" and path.startswith("/v2"):
            route.fulfill(path=str(BUILD / "index.html"), content_type="text/html")
            return
        if request.method == "GET" and path.startswith("/static/v2/"):
            asset = (BUILD / path.removeprefix("/static/v2/")).resolve()
            assert asset.is_relative_to(BUILD.resolve()) and asset.is_file()
            self.loaded_assets.add(path)
            route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset)[0] or "application/octet-stream")
            return
        super()._route(route)

    def _requirement(self):
        configured = self.global_actions[0].get("credential_requirement", {})
        profile = configured.get("profile", "yamcs_login")
        return {
            "id": configured.get("id", REQUIREMENT_ID), "action_id": GLOBAL_ACTION_ID,
            "action_name": "Published Yamcs", "identity_name": configured.get("identity_name", "Yamcs"),
            "profile": profile, "auth_type": PROFILE_TYPES[profile],
            "destination": self.global_actions[0]["endpoint"],
            "reason": self.requirement_reason or ("approval_required" if self.private_identities else "missing"),
            "fields": [{"name": "model_defined_field", "label": "Do not render this", "type": "text"}],
            "identities": [
                {"id": item["id"], "name": item["name"], "auth_type": item["credentials"]["auth_type"]}
                for item in self.private_identities.values()
                if item["credentials"]["auth_type"] == PROFILE_TYPES[profile]
            ],
        }

    def _state(self):
        return {
            "status": "ready" if self.ready_identity else "credentials_required",
            "request_id": self.request_id,
            "uses_personal_credentials": True,
            "shared_conversation": self.request_shared,
            "sharing_notice": "Your message and returned data are shared. Credentials are private." if self.request_shared else None,
            "requirements": [] if self.ready_identity else [self._requirement()],
        }

    def _save_identity(self, body, identifier=None):
        identifier = identifier or f"identity-{len(self.private_identities) + 1}"
        old = self.private_identities.get(identifier, {})
        old_credentials = old.get("credentials", {})
        credentials = body.get("credentials", {})
        auth_type = credentials.get("auth_type", old_credentials.get("auth_type", "username_password"))
        stored_secret = credentials.get("password") or credentials.get("secret")
        if stored_secret:
            self.private_secrets[identifier] = stored_secret
        assert identifier in self.private_secrets, "A newly created identity needs a synthetic secret."
        result = {
            **old, "id": identifier, "name": body.get("name", old.get("name", "Yamcs")),
            "description": body.get("description", old.get("description", "")),
            "usage_contexts": ["action"], "scope_type": "personal",
            "credentials": {
                "auth_type": auth_type,
                "username": credentials.get("username", old_credentials.get("username", "")),
                "password_stored": auth_type == "username_password",
                "secret_stored": auth_type != "username_password",
                "password": "Stored_In_KeyVault" if auth_type == "username_password" else "",
                "secret": "Stored_In_KeyVault" if auth_type != "username_password" else "",
            },
        }
        self.private_identities[identifier] = result
        return result

    def _dispatch(self, route, entry):
        path, method, body = entry.path, entry.method, entry.body
        if path == "/api/action-auth/preflight" and method == "POST":
            assert set(body) <= {"agent_info", "action_ref", "run_id", "conversation_id", "conversation_kind"}
            if self.expected_repair_context is not None:
                assert body == self.expected_repair_context, "Started repair must target only the affected action, not its root selection."
                self.expected_repair_context = None
            assert body["conversation_kind"] in ("personal", "collaboration")
            self.request_shared = body["conversation_kind"] == "collaboration"
            if self.request_shared:
                assert body["conversation_id"] == SHARED_ID
            self.request_counter += 1
            self.request_id = f"private-{self.actor}-{self.request_counter}"
            self._json(route, self._state())
        elif path.startswith("/api/action-auth/requests/"):
            parts = path.split("/")
            request_id = parts[4]
            if method == "POST" and path.endswith("/cancel"):
                self.cancelled.add(request_id)
                self._json(route, {"status": "cancelled"})
            elif request_id in self.cancelled:
                self._json(route, {"error": "Request cancelled."}, 410)
            elif request_id in self.consumed:
                self._json(route, {"error": "Request already consumed."}, 409)
            elif method == "GET":
                self._json(route, self._state())
            elif method == "POST" and path.endswith("/credentials"):
                assert set(body) <= {"requirement_id", "identity_id", "credentials", "confirm_destination"}
                assert body["confirm_destination"] is True
                assert body["requirement_id"] == self._requirement()["id"]
                identity_id = body.get("identity_id")
                if body.get("credentials"):
                    identity = self._save_identity({
                        "name": self._requirement()["identity_name"],
                        "credentials": {"auth_type": self._requirement()["auth_type"], **body["credentials"]},
                    }, identity_id)
                    identity_id = identity["id"]
                assert identity_id in self.private_identities
                self.ready_identity = True
                self._json(route, self._state())
            else:
                raise AssertionError(f"Unexpected private API method: {method} {path}")
        elif path == "/api/workspace-identities/personal/identities" and method == "GET":
            self._json(route, {"identities": list(self.private_identities.values())})
        elif path == "/api/workspace-identities/personal/identities" and method == "POST":
            self._json(route, {"identity": self._save_identity(body)}, 201)
        elif path.startswith("/api/workspace-identities/personal/identities/") and method == "PATCH":
            self._json(route, {"identity": self._save_identity(body, path.rsplit("/", 1)[-1])})
        elif path == "/api/v2/admin/settings" and method == "GET":
            self._json(route, {
                "settings": {}, "admin_nav": self._bootstrap()["admin_nav"],
                "field_schema": {}, "section_status": {}, "runtime_flags": {}, "suppressed_capabilities": [],
            })
        elif path == "/api/admin/plugins/types" and method == "GET":
            self._json(route, [{"type": "yamcs", "display": "Yamcs", "description": "Read-only telemetry."}])
        elif path == "/api/admin/workspace-identities/global/identities" and method == "GET":
            self._json(route, {"identities": []})
        elif path == "/api/admin/plugins" and method == "GET":
            self._json(route, self.global_actions)
        elif path == "/api/admin/plugins" and method == "POST":
            saved = copy.deepcopy(body)
            saved["id"] = f"created-global-yamcs-{len(self.global_actions)}"
            if saved.get("credential_requirement"):
                saved["credential_requirement"]["id"] = f"server-requirement-{len(self.global_actions)}"
            self.global_actions.append(saved)
            self._json(route, {"success": True})
        elif path.startswith("/api/admin/plugins/") and method in ("PUT", "PATCH"):
            name = path.split("/")[4]
            saved = next(item for item in self.global_actions if item["name"] == name)
            if path.endswith("/enabled"):
                assert method == "PATCH" and set(body) == {"is_enabled"}
                saved["is_enabled"] = body["is_enabled"]
            else:
                assert method == "PUT"
                identifier = saved["id"]
                old_requirement = saved.get("credential_requirement")
                saved.clear()
                saved.update(copy.deepcopy(body))
                saved["id"] = identifier
                if saved.get("credential_requirement"):
                    saved["credential_requirement"].setdefault("id", (old_requirement or {}).get("id", REQUIREMENT_ID))
            self._json(route, {"success": True})
        elif path == "/api/plugins/test-yamcs-connection" and method == "POST":
            assert set(body) == {"action_ref"}
            assert body["action_ref"].startswith("action:v1:global:Z2xvYmFs:")
            assert self.ready_identity
            self._json(route, {"success": True})
        elif path == "/api/plugins/agent-targets" and entry.query.get("scope") == ["global"]:
            self._json(route, {"targets": [], "scope_type": "global", "scope_id": "global", "can_manage": True})
        elif path == "/api/v2/orchestration/runs" and method == "GET":
            self._json(route, {"runs": []})
        elif path == "/api/collaboration/file-approvals" and method == "GET":
            self._json(route, {"approvals": []})
        elif path == "/api/v2/orchestration/plan" and method == "POST":
            self.plan = {
                "plan_id": "yamcs-plan", "run_id": "yamcs-run", "conversation_id": body["conversation_id"],
                "turn_id": body["turn_id"], "revision": 1, "status": "approved" if self.approval_mode == "auto" else "awaiting_approval",
                "intent": {"summary": "Read mission telemetry", "complexity": "simple"},
                "steps": [
                    {"step_id": "read", "capability_id": "action", "title": "Read Yamcs", "arguments": {}},
                    {"step_id": "respond", "capability_id": "respond", "title": "Respond", "arguments": {}, "depends_on": ["read"]},
                ],
                "approval": {"mode": self.approval_mode, "state": "approved" if self.approval_mode == "auto" else "pending", "timeout_seconds": 0},
            }
            self._stream(route, [{"type": "orchestration_plan", "plan": self.plan, "done": True}])
        elif path == "/api/v2/orchestration/run" and method == "POST":
            assert body["action_auth_request_id"] == self.request_id
            self._stream(route, [{"content": "Completed mission plan."}, {
                "done": True, "status": "completed", "message_id": "orchestration-result",
                "conversation_id": body["conversation_id"],
            }])
        elif path == f"/api/conversations/{SHARED_ID}/kind" and method == "GET":
            self._json(route, {"conversation_id": SHARED_ID, "kind": "collaborative"})
        elif path == f"/api/collaboration/conversations/{SHARED_ID}" and method == "GET":
            self._json(route, {"conversation": self.shared_conversation})
        elif path == f"/api/collaboration/conversations/{SHARED_ID}/messages" and method == "GET":
            self._json(route, {"messages": self.messages[SHARED_ID]})
        elif path == f"/api/collaboration/conversations/{SHARED_ID}/events" and method == "GET":
            self._stream(route, [])
        elif path.endswith("/typing") or path.endswith("/mark-read"):
            self._json(route, {"success": True})
        elif path == "/upload" and method == "POST":
            identifier = "upload-created-conversation"
            self.conversations.append({"id": identifier, "title": "Uploaded telemetry"})
            self.messages[identifier] = []
            self._json(route, {
                "conversation_id": identifier, "file_message_id": "uploaded-file",
                "workspace_scope": "personal", "workspace_document_id": "uploaded-document",
                "workspace_document": {
                    "id": "uploaded-document", "document_id": "uploaded-document", "file_name": "telemetry.pdf",
                    "scope": "personal", "status": "Processing complete", "percentage_complete": 100,
                },
            })
        elif path == "/api/chat/stream" or path == f"/api/collaboration/conversations/{SHARED_ID}/stream":
            assert method == "POST" and body["action_auth_request_id"] == self.request_id
            identifier = body.get("conversation_id", SHARED_ID)
            if self.runtime_rejection:
                self.ready_identity = False
                self.requirement_reason = "authentication_rejected" if self.execution_started else "missing"
                if self.execution_started:
                    self.consumed.add(self.request_id)
                    self.expected_repair_context = {
                        "action_ref": ACTION_REF, "conversation_id": identifier,
                        "conversation_kind": "collaboration" if identifier == SHARED_ID else "personal",
                    }
                self._stream(route, [{
                    self.control_discriminator: "action_credentials_required", "status": "credentials_required",
                    "execution_started": self.execution_started,
                    "action_ref": ACTION_REF,
                    "request_id": self.request_id, "content": "This control must not become assistant content.",
                }])
                return
            text = body.get("message", body.get("content"))
            self.messages[identifier].append({
                "id": f"user-{len(self.messages[identifier])}", "conversation_id": identifier, "role": "user",
                "content": text, "timestamp": "2026-09-16T10:00:00Z",
                "metadata": {"sender": {"user_id": self.actor}},
            })
            self._stream(route, [{"content": "Read-only Yamcs telemetry result."}, {
                "done": True, "conversation_id": identifier, "message_id": "yamcs-answer",
            }])
        else:
            super()._dispatch(route, entry)

    @staticmethod
    def _stream(route, frames):
        route.fulfill(content_type="text/event-stream", body="".join(
            f"data: {json.dumps(frame)}\n\n" for frame in frames
        ) or ": connected\n\n")

    def open(self, path="/chat", *, width=1440, height=1000, theme="light"):
        self.preferences.update({
            "darkModeEnabled": theme == "dark", "v2RailCollapsed": width < 1024,
            "v2WorkspaceRailCollapsed": width < 1024, "fontSizePreference": "m",
        })
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}/v2{path}", wait_until="networkidle")
        expect(self.page.locator("html")).to_have_css("color-scheme", theme)

    def select_agent(self):
        self.page.get_by_role("button", name="Agent", exact=True).click()
        self.page.get_by_role("option", name="Mission Yamcs").click()

    def submit_chat(self, message="Inspect live telemetry"):
        self.page.get_by_role("textbox", name="Message", exact=True).fill(message)
        self.page.get_by_role("button", name="Send to this conversation" if "conversationId=" in self.page.url and SHARED_ID in self.page.url else "Send message", exact=True).click()
        expect(self.card).to_be_visible()

    @property
    def card(self):
        return self.page.get_by_test_id("action-credential-card")

    def calls(self, path):
        return [entry for entry in self.requests if entry.path == path]

    def assert_private(self, *values):
        self.assert_no_secret_storage(*values)
        for entry in self.requests:
            allowed = entry.path.endswith("/credentials") or (
                entry.path.startswith("/api/workspace-identities/personal/identities") and entry.method in ("POST", "PATCH")
            )
            if not allowed:
                for value in values:
                    assert value not in json.dumps(entry.body), f"Private input reached {entry.path}"
        for value in values:
            assert value not in json.dumps(self.messages)
            assert value not in json.dumps(self.responses)


@pytest.fixture
def action_auth_ui(page, action_auth_build):
    fixture = ActionAuthFixture(page)
    yield fixture
    fixture.assert_clean()
