# workspace_authoring.py
"""
Closed API fixtures for the production V2 My Workspace authoring SPA.
Version: 0.261.096
Implemented in: 0.261.096

The browser loads the real built application and CSS. Only HTTP responses and
synthetic resource persistence are replaced; no components, stores, navigation,
validation, or DOM behavior are simulated. Saved secrets stay on the fixture's
server side, and every editor write is recorded before applying nested changes.

SIMPLECHAT_UI_EXPECTED_JS and SIMPLECHAT_UI_EXPECTED_CSS can pin an explicitly
released build when worktree source-copy timestamps are newer. Both filenames
must match the real index and exist on disk. Without pins, source freshness is
required. Browser assets and UI assertions are never replaced by this option.

The shared connect_options fixture supports DefaultAzureCredential and
azure-mgmt-playwright when PLAYWRIGHT_SERVICE_URL is configured, with the same
explicit local-browser fallback as the existing admin suite.
"""

import copy
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

from ui_tests.fixtures.v2_admin_settings import connect_options  # noqa: F401


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = ROOT / "application" / "single_app" / "static"
SCHEMA_ROOT = STATIC_ROOT / "json" / "schemas"
PLUGIN_ROOT = ROOT / "application" / "single_app" / "semantic_kernel_plugins"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
ORIGIN = "http://simplechat.test"
VERSION = "0.261.096"
SECRET_MASK = "***REDACTED***"
OWNER_ID = "workspace-editor-user"
AGENT_ID = "00000000-0000-4000-8000-000000000001"
TARGET_ID = "00000000-0000-4000-8000-000000000002"
GLOBAL_AGENT_ID = "00000000-0000-4000-8000-000000000003"
ACTION_ID = "10000000-0000-4000-8000-000000000001"
CALL_ACTION_ID = "10000000-0000-4000-8000-000000000002"
GLOBAL_ACTION_ID = "10000000-0000-4000-8000-000000000003"
SELF_ACTION_ID = "10000000-0000-4000-8000-000000000004"
MCP_ACTION_ID = "10000000-0000-4000-8000-000000000005"
CHART_ACTION_ID = "10000000-0000-4000-8000-000000000006"
CREATED_AGENT_ID = "00000000-0000-4000-8000-000000000101"
CREATED_ACTION_ID = "10000000-0000-4000-8000-000000000101"
STORED_KEY = "fixture-only-existing-credential"
STORED_HEADER = "fixture-only-existing-header"
MISSING = object()


def agent_record(identifier=AGENT_ID, **overrides):
    record = {
        "id": identifier,
        "name": "workspace-reviewer",
        "display_name": "Workspace reviewer",
        "description": "Review work with authorized sources and actions.",
        "instructions": "Review carefully. Use #action:legacy-tool when relevant.",
        "agent_type": "local",
        "actions_to_load": ["legacy-tool", "unavailable-action"],
        "other_settings": {
            "action_capabilities": {"legacy-tool": ["read"], "unavailable-action": ["keep"]},
            "custom_policy": {"enabled": False, "limit": 0, "nested": {"retain": "value"}},
        },
        "max_completion_tokens": -1,
        "model_endpoint_id": "workspace-model-endpoint",
        "model_id": "workspace-model",
        "model_provider": "aoai",
        "azure_openai_gpt_deployment": "workspace-gpt",
        "tags": ["review"],
        "is_global": False,
        "user_id": OWNER_ID,
    }
    record.update(copy.deepcopy(overrides))
    return record


def action_record(identifier=ACTION_ID, **overrides):
    record = {
        "id": identifier,
        "name": "legacy-tool",
        "displayName": "Workspace API",
        "description": "Read the approved workspace API.",
        "type": "openapi",
        "endpoint": "https://api.example.test/v1",
        "auth": {"type": "key", "key": STORED_KEY},
        "additionalFields": {
            "openapi_spec_content": {
                "openapi": "3.0.0",
                "info": {"title": "Workspace API", "version": "1.0.0"},
                "paths": {
                    "/items": {
                        "get": {
                            "operationId": "listItems",
                            "summary": "List approved items",
                            "responses": {"200": {"description": "Approved items"}},
                        },
                    },
                },
            },
            "custom": {"enabled": False, "limit": 0, "items": [], "nested": {"keep": "yes"}},
        },
        "metadata": {"retention": {"enabled": False, "days": 0}, "labels": []},
        "is_enabled": True,
        "is_global": False,
        "user_id": OWNER_ID,
    }
    record.update(copy.deepcopy(overrides))
    return record


def call_action(identifier=CALL_ACTION_ID, *, target_id=TARGET_ID, **overrides):
    return action_record(
        identifier,
        name="call-reviewer" if identifier == CALL_ACTION_ID else "call-self",
        displayName="Call reviewer" if identifier == CALL_ACTION_ID else "Call self",
        description="Delegate a review to another authorized agent.",
        type="agent",
        endpoint="internal://agent",
        auth={"type": "user"},
        additionalFields={
            "target_agent": {"id": target_id, "scope_type": "personal", "scope_id": OWNER_ID},
        },
        **overrides,
    )


def _schema(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {
        "type": "object", "properties": {}, "additionalProperties": True,
    }


def action_types():
    """Offer shipped modules using their checked-in definitions and schemas."""
    types = []
    for module_path in sorted(PLUGIN_ROOT.glob("*_plugin.py")):
        action_type = module_path.stem.removesuffix("_plugin")
        if action_type == "base":
            continue
        definition = _schema(SCHEMA_ROOT / f"{action_type}.definition.json")
        types.append({
            "type": action_type,
            "display": {
                "agent": "Call agent",
                "openapi": "OpenAPI",
                "mcp": "MCP",
                "msgraph": "Microsoft Graph",
                "simplechat": "SimpleChat",
            }.get(action_type, action_type.replace("_", " ").title()),
            "description": f"Configure the {action_type.replace('_', ' ')} connector.",
            "allowed_auth_types": definition.get("allowedAuthTypes", ["NoAuth"]),
            "additional_fields_schema": _schema(
                SCHEMA_ROOT / f"{action_type}_plugin.additional_settings.schema.json"
            ),
            "metadata_schema": _schema(SCHEMA_ROOT / f"{action_type}_plugin.metadata.schema.json"),
        })
    types.append({
        "type": "fixture_custom",
        "display": "Custom governed connector",
        "description": "A server-discovered action that is not hardcoded in the browser.",
        "allowed_auth_types": ["NoAuth"],
        "additional_fields_schema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "title": "Region", "enum": ["east", "west"]},
                "limit": {"type": "integer", "title": "Result limit", "default": 0, "minimum": 0},
                "enabled": {"type": "boolean", "title": "Include archived", "default": False},
            },
            "additionalProperties": True,
        },
        "metadata_schema": {"type": "object", "properties": {}, "additionalProperties": True},
    })
    return types


def editor_options():
    return {
        "agent_types": [
            {"value": value, "label": label, "enabled": True}
            for value, label in (
                ("local", "Local agent"),
                ("aifoundry", "Azure AI Foundry"),
                ("new_foundry", "New Foundry"),
                ("foundry_workflow", "Foundry Workflow"),
            )
        ],
        "settings": {
            "enable_semantic_kernel": True,
            "per_user_semantic_kernel": True,
            "allow_user_agents": True,
            "allow_user_plugins": True,
            "allow_user_custom_endpoints": True,
            "allow_personal_ai_foundry_agents": True,
            "allow_personal_new_foundry_agents": True,
            "enable_multi_model_endpoints": True,
            "merge_global_semantic_kernel_with_workspace": True,
            "enable_agent_template_gallery": True,
            "agent_templates_allow_user_submission": True,
            "enable_user_workspace": True,
            "enable_public_workspaces": True,
            "enable_url_access": True,
            "enable_web_search": True,
            "enable_math_plugin": True,
        },
        "model_endpoints": [{
            "id": "workspace-model-endpoint",
            "name": "Workspace model endpoint",
            "provider": "aoai",
            "enabled": True,
            "models": [{
                "id": "workspace-model",
                "deploymentName": "workspace-gpt",
                "modelName": "gpt-4o",
                "displayName": "Workspace GPT",
                "enabled": True,
            }],
        }],
        "builtin_actions": [
            {"id": "math", "label": "Math", "description": "Built-in arithmetic tools."},
        ],
    }


def _pointer_parts(pointer):
    assert pointer.startswith("/"), f"Expected a JSON pointer, received {pointer!r}"
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _pointer_index(value):
    return int(value) if re.fullmatch(r"0|[1-9][0-9]*", value) else None


def _get_pointer(record, pointer):
    current = record
    for key in _pointer_parts(pointer):
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and (index := _pointer_index(key)) is not None and index < len(current):
            current = current[index]
        else:
            return MISSING
    return current


def _set_pointer(record, pointer, value):
    parts = _pointer_parts(pointer)
    parent = record
    for key in parts[:-1]:
        parent = parent[int(key)] if isinstance(parent, list) else parent.setdefault(key, {})
    if isinstance(parent, list):
        parent[int(parts[-1])] = value
    else:
        parent[parts[-1]] = value


def _remove_pointer(record, pointer):
    parts = _pointer_parts(pointer)
    parent = record
    for key in parts[:-1]:
        if isinstance(parent, dict) and key in parent:
            parent = parent[key]
        elif isinstance(parent, list) and (index := _pointer_index(key)) is not None and index < len(parent):
            parent = parent[index]
        else:
            return
    if isinstance(parent, dict):
        parent.pop(parts[-1], None)
    elif isinstance(parent, list) and (index := _pointer_index(parts[-1])) is not None and index < len(parent):
        parent[index] = ""


def _merge_updates(record, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            _merge_updates(record[key], value)
        else:
            record[key] = copy.deepcopy(value)


def _walk_values(value, parent=""):
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    else:
        yield parent, value
        return
    for key, item in children:
        escaped = str(key).replace("~", "~0").replace("/", "~1")
        yield from _walk_values(item, f"{parent}/{escaped}")


class EditorSecretError(ValueError):
    """The synthetic request violates explicit, owned secret intent."""


def _editor_candidate(record, updates, secret_paths, clear_paths, removed_paths):
    known, cleared, removed = set(secret_paths), set(clear_paths), set(removed_paths)
    if cleared - known or cleared & removed:
        raise EditorSecretError()
    candidate = copy.deepcopy(record)
    _merge_updates(candidate, updates)
    for pointer, value in _walk_values(candidate):
        if value == SECRET_MASK:
            original = _get_pointer(record, pointer)
            if pointer not in known or original is MISSING or original == SECRET_MASK:
                raise EditorSecretError()
            # Array masks retain only the secret at this exact original position.
            _set_pointer(candidate, pointer, copy.deepcopy(original))
    for pointer in removed:
        _remove_pointer(candidate, pointer)
    for pointer in secret_paths:
        if pointer in cleared:
            _remove_pointer(candidate, pointer)
        else:
            value = _get_pointer(candidate, pointer)
            if value is MISSING or value is None or value == "":
                raise EditorSecretError()
    return candidate


@dataclass
class ApiRequest:
    method: str
    path: str
    query: dict
    body: object


class WorkspaceAuthoringFixture:
    """A closed synthetic server, not a replacement implementation of the UI."""

    def __init__(self, page: Page):
        self.page = page
        self.pages = []
        self.preferences = {}
        self.options = editor_options()
        self.types = action_types()
        self.agents = {
            AGENT_ID: agent_record(),
            TARGET_ID: agent_record(
                TARGET_ID, name="target-reviewer", display_name="Target reviewer", actions_to_load=[]
            ),
            GLOBAL_AGENT_ID: agent_record(
                GLOBAL_AGENT_ID, name="provided-reviewer", display_name="Provided reviewer",
                is_global=True, user_id="global", actions_to_load=[],
            ),
        }
        self.actions = {
            ACTION_ID: action_record(),
            CALL_ACTION_ID: call_action(),
            SELF_ACTION_ID: call_action(SELF_ACTION_ID, target_id=AGENT_ID),
            GLOBAL_ACTION_ID: action_record(
                GLOBAL_ACTION_ID, name="provided-api", displayName="Provided API",
                is_global=True, user_id="global",
            ),
            MCP_ACTION_ID: action_record(
                MCP_ACTION_ID, name="workspace-mcp", displayName="Workspace MCP", type="mcp",
                endpoint="https://mcp.example.test/mcp",
                additionalFields={
                    "server_profile": "generic", "transport": "streamable_http",
                    "auth_method": "bearer", "custom_headers": {"X-Workspace": STORED_HEADER},
                    "load_tools": True, "load_prompts": False, "request_timeout": 30,
                    "allowed_tool_names": ["search"], "mcp_tools": [],
                    "custom": {"keep": {"false_value": False, "zero_value": 0}},
                },
            ),
            CHART_ACTION_ID: action_record(
                CHART_ACTION_ID, name="legacy-chart", displayName="Workspace charts", type="chart",
                endpoint="internal://chart", auth={"type": "user"},
                additionalFields={"chart_capabilities": {"line": False, "bar": True}},
            ),
        }
        self.secret_paths = {
            ACTION_ID: ["/auth/key"],
            GLOBAL_ACTION_ID: ["/auth/key"],
            MCP_ACTION_ID: ["/auth/key", "/additionalFields/custom_headers/X-Workspace"],
        }
        self.revisions = {identifier: 1 for identifier in (*self.agents, *self.actions)}
        self.empty_revisions = set()
        self.missing_revisions = set()
        self.targets = [
            {
                "id": item["id"], "scope_type": "global" if item["is_global"] else "personal",
                "scope_id": "global" if item["is_global"] else OWNER_ID,
                "name": item["name"], "display_name": item["display_name"],
                "description": item["description"], "agent_type": item["agent_type"],
            }
            for item in self.agents.values()
        ]
        self.can_manage = True
        self.workspace_enabled = True
        self.disabled_sections = {}
        self.denied_resources = set()
        self.requests = []
        self.writes = []
        self.responses = []
        self.errors = []
        self.console_errors = []
        self.private_values = {STORED_KEY, STORED_HEADER, SECRET_MASK}
        self.expected_http_errors = set()
        self.unexpected_requests = []
        self.failures = []
        self.deferred_paths = set()
        self.pending_responses = []
        self.created_counts = {"agents": 0, "plugins": 0}
        self.loaded_assets = set()
        self.knowledge_catalog = {
            "sources": [
                {"scope": "personal", "id": "personal", "label": "Personal workspace"},
                {"scope": "public", "id": "public-handbook", "label": "Published handbook"},
            ],
            "documents": [
                {
                    "id": "personal-brief", "title": "Private review brief",
                    "file_name": "review-brief.pdf", "scope": "personal", "source_id": "personal",
                    "source_name": "Personal workspace", "tags": ["Finance"],
                },
                {
                    "id": "public-guide", "title": "Public review guide",
                    "file_name": "review-guide.pdf", "scope": "public", "source_id": "public-handbook",
                    "source_name": "Published handbook", "tags": ["Finance", "Operations"],
                },
                {
                    "id": "public-checklist", "title": "Public finance checklist",
                    "file_name": "finance-checklist.pdf", "scope": "public", "source_id": "public-handbook",
                    "source_name": "Published handbook", "tags": ["Finance"],
                },
            ],
            "tags": [{"name": "Finance", "count": 3}, {"name": "Operations", "count": 1}],
        }
        self.templates = [{
            "id": "approved-review-template", "title": "Approved review example",
            "display_name": "Approved review example", "description": "Review with an approved starting prompt.",
            "instructions": "Use #action:missing-template-tool when it becomes available.",
            "actions_to_load": ["missing-template-tool"], "tags": ["review"],
            "additional_settings": {
                "custom_policy": {"enabled": False, "limit": 0},
                "private": {"api_key": SECRET_MASK},
            },
        }]
        self.openapi_import_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Imported review API", "version": "1.0.0"},
            "servers": [{"url": "https://review-api.example.test/v1"}],
            "paths": {
                "/status": {
                    "get": {
                        "operationId": "getReviewStatus", "summary": "Read review status",
                        "responses": {"200": {"description": "Review status"}},
                    },
                },
            },
        }
        self.mcp_presets = [{
            "id": "generic", "displayName": "Generic MCP server",
            "description": "Standards-compliant MCP server.",
            "defaults": {"server_profile": "generic", "transport": "streamable_http", "auth_method": "none"},
            "constraints": {}, "ui": {}, "warnings": [],
            "implementation": {"id": "generic", "schemaVersion": "1.0.0"},
            "additionalSettings": {"compatibilityProfile": "standards_compliant"},
        }]
        self.mcp_preconfigurations = [{
            "id": "review-server", "displayName": "Review MCP server", "presetId": "generic",
            "description": "The approved review server.",
            "endpoint": "https://mcp.example.test/review", "transport": "streamable_http",
            "scopeEligibility": ["personal"],
            "defaults": {"load_tools": True}, "constraints": {}, "ui": {}, "warnings": [],
            "implementation": {"id": "generic", "schemaVersion": "1.0.0"},
            "additionalSettings": {"compatibilityProfile": "standards_compliant"},
        }]
        self.conversations = [{
            "id": "existing-workspace-chat", "title": "Existing conversation",
            "user_id": OWNER_ID, "last_updated": "2026-09-05T12:00:00Z",
        }]
        self.messages = {
            "existing-workspace-chat": [{
                "id": "existing-message", "role": "user", "content": "An earlier conversation.",
                "conversation_id": "existing-workspace-chat", "timestamp": "2026-09-05T12:00:00Z",
            }],
        }
        self.extra_gets = {
            "/api/prompts": {"prompts": []},
            "/api/documents/facets": {
                "total": 1, "untagged": 0, "processing": 0, "errors": 0,
                "recent": 1, "shared_with_me": 0, "by_tag": {"Finance": 1},
            },
            "/api/documents/tags": {"tags": [{"name": "Finance"}]},
            "/api/orchestration_types": [{"value": "default_agent", "label": "Single agent"}],
            "/api/orchestration_settings": {"orchestration_type": "default_agent", "max_rounds_per_agent": 1},
        }
        self.extra_posts = {
            "/api/agents/draft-instructions": {
                "success": True, "instructions": "Generated review instructions for the selected actions and knowledge.",
            },
            "/api/agent-templates": {"template": {"id": "submitted-template", "status": "pending"}},
            "/api/openapi/upload": {
                "success": True, "file_id": "fixture-openapi-upload",
                "original_filename": "review.openapi.json", "spec_content": self.openapi_import_spec,
            },
            "/api/plugins/validate": {"valid": True, "message": "Fixture manifest is valid."},
            "/api/plugins/test-openapi-connection": {
                "success": True, "message": "Fixture OpenAPI connection succeeded.",
            },
            "/api/plugins/test-mcp-connection": {
                "success": True, "message": "Fixture MCP connection succeeded.",
            },
            "/api/plugins/mcp/discover": {
                "success": True,
                "tools": [
                    {
                        "original_name": "search", "function_name": "search",
                        "description": "Search approved knowledge.",
                        "input_schema": {
                            "type": "object", "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                    {
                        "original_name": "summarize", "function_name": "summarize",
                        "description": "Summarize an approved source.",
                        "input_schema": {"type": "object", "properties": {}},
                    },
                ],
                "capabilities": {"tools": True, "prompts": False},
                "transport": "streamable_http", "auth_method": "bearer",
            },
        }
        self._watch_page(page)
        page.context.on("page", self._watch_page)
        page.context.route("**/*", self._route)

    def _watch_page(self, page: Page):
        self.pages.append(page)
        page.on("pageerror", lambda error: self.errors.append(f"{page.url}: {error}"))
        page.on("console", self._console)

    @property
    def editor_writes(self):
        return [
            request for request in self.writes
            if re.fullmatch(r"/api/user/(agents|plugins)(/[^/]+)?", request.path)
        ]

    def revision(self, identifier):
        return f"fixture-revision:{identifier}:{self.revisions[identifier]}"

    def projected(self, record):
        result = copy.deepcopy(record)
        for pointer in self.secret_paths.get(record["id"], []):
            _set_pointer(result, pointer, SECRET_MASK)
        return result

    def envelope(self, record):
        empty_revision = record["id"] in self.empty_revisions
        missing_revision = record["id"] in self.missing_revisions
        assert not (empty_revision or missing_revision) or record.get("is_global"), "Writable fixtures require a revision."
        resource = {
            "record": self.projected(record),
            "revision": "" if empty_revision else self.revision(record["id"]),
            "secret_paths": copy.deepcopy(self.secret_paths.get(record["id"], [])),
            "read_only": bool(record.get("is_global")),
        }
        if missing_revision:
            del resource["revision"]
        return resource

    def reject_next(self, method, path, *, status=503, error="Fixture request failed.", **payload):
        self.failures.append((method, path, status, {"error": error, **payload}))

    def defer_next(self, method, path):
        self.deferred_paths.add((method, path))

    def release_responses(self):
        pending, self.pending_responses = self.pending_responses, []
        for route, entry in pending:
            self._dispatch(route, entry)

    def _console(self, message):
        if message.type == "error":
            self.console_errors.append((message.text, message.location.get("url", "")))

    def _json(self, route, payload, status=200):
        self.responses.append((route.request.url, copy.deepcopy(payload)))
        if status >= 400:
            self.expected_http_errors.add((route.request.url, status))
        route.fulfill(status=status, json=payload)

    def _bootstrap(self):
        return {
            "version": VERSION,
            "user": {
                "id": OWNER_ID, "display_name": "Workspace editor", "is_admin": False,
                "roles": ["User"],
            },
            "branding": {
                "app_title": "SimpleChat", "show_logo": False, "hide_app_title": False,
                "logo_url": None, "logo_dark_url": None, "classification_banner": None,
            },
            "features": {
                "enable_user_workspace": True,
                "enable_semantic_kernel": True,
                "per_user_semantic_kernel": True,
                "enable_agent_template_gallery": True,
            },
            "catalogs": {
                "models": [], "prompts": [], "initial_model_selection": None,
                "agents": [
                    {
                        **self.projected(record),
                        "catalog_key": f"{'global' if record.get('is_global') else 'personal'}:{record['id']}",
                        "scope_type": "global" if record.get("is_global") else "personal",
                        "scope_label": "Provided" if record.get("is_global") else "Personal",
                    }
                    for record in self.agents.values()
                ],
            },
            "scope": {"groups": [], "public_workspaces": []},
            "navigation": {
                "custom_pages": {"enabled": False, "items": []},
                "external_links": {"enabled": False, "items": []},
            },
            "workspace": {
                "enabled": self.workspace_enabled,
                "governance": {},
                "sections": {
                    section: {
                        "enabled": section not in self.disabled_sections,
                        "reason": self.disabled_sections.get(section), "group": group,
                    }
                    for section, group in (
                        ("agents", "automation"), ("actions", "automation"),
                        ("prompts", "knowledge"), ("documents", "knowledge"),
                        ("identities", "connections"), ("endpoints", "connections"),
                    )
                },
            },
            "settings": {},
        }

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(f"{request.method} {request.url}")
            route.abort()
            return
        path = unquote(parsed.path)
        if request.method == "GET" and re.fullmatch(
            r"/v2/(workspace(?:/(?:agents|actions|prompts|documents)(?:/[^/]+)?)?|chat)", path
        ):
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return
        if request.method == "GET" and path.startswith("/static/"):
            asset = (STATIC_ROOT / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file():
                self.loaded_assets.add(path)
                route.fulfill(path=str(asset))
                return
            self.unexpected_requests.append(f"Missing local asset: {path}")
            route.fulfill(status=404, body="Fixture asset not found.")
            return
        body = None
        if request.post_data:
            if "application/json" in request.headers.get("content-type", ""):
                body = request.post_data_json
            else:
                body = request.post_data
        entry = ApiRequest(request.method, path, parse_qs(parsed.query), copy.deepcopy(body))
        self.requests.append(entry)
        if request.method != "GET":
            self.writes.append(entry)
        for index, (method, failed_path, status, payload) in enumerate(self.failures):
            if (method, failed_path) == (entry.method, path):
                self.failures.pop(index)
                self._json(route, payload, status)
                return
        if (entry.method, path) in self.deferred_paths:
            self.deferred_paths.remove((entry.method, path))
            self.pending_responses.append((route, entry))
            return
        self._dispatch(route, entry)

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path == "/api/v2/bootstrap" and method == "GET":
            self._json(route, self._bootstrap())
        elif path == "/api/user/settings" and method == "GET":
            self._json(route, {"settings": self.preferences})
        elif path == "/api/user/settings" and method == "POST":
            assert set(entry.body) == {"settings"}
            self.preferences.update(copy.deepcopy(entry.body["settings"]))
            self._json(route, {"message": "Saved fixture preferences."})
        elif path == "/api/user/agent/settings" and method == "GET":
            assert entry.query == {"view": ["editor"]}
            self._json(route, self.options)
        elif path == "/api/user/plugins/types" and method == "GET":
            assert entry.query == {"view": ["editor"]}
            self._json(route, self.types)
        elif path == "/api/agents/generate_id" and method == "GET":
            self.created_counts["agents"] += 1
            self._json(route, {"id": f"00000000-0000-4000-8000-{100 + self.created_counts['agents']:012d}"})
        elif path == "/api/plugins/agent-targets" and method == "GET":
            assert entry.query.get("scope") == ["personal"]
            assert "group_id" not in entry.query
            self._json(route, {
                "targets": self.targets, "can_manage": self.can_manage,
                "scope_type": "personal", "scope_id": OWNER_ID,
            })
        elif path == "/api/agents/catalog" and method == "GET":
            self._json(route, {"agents": self._bootstrap()["catalogs"]["agents"]})
        elif path == "/api/agents/assigned-knowledge/catalog" and method == "GET":
            assert entry.query == {"agent_scope": ["personal"]}
            self._json(route, self.knowledge_catalog)
        elif path == "/api/agent-templates" and method == "GET":
            self._json(route, {"templates": self.templates})
        elif path == "/api/plugins/mcp/presets" and method == "GET":
            assert not entry.query
            self._json(route, {"presets": self.mcp_presets})
        elif path == "/api/plugins/mcp/preconfigurations" and method == "GET":
            assert entry.query == {"scope": ["personal"]}
            self._json(route, {"preconfigurations": self.mcp_preconfigurations})
        elif path == "/api/user/model-endpoints" and method == "GET":
            self._json(route, {"endpoints": self.options["model_endpoints"]})
        elif path == "/api/workspace-identities/personal/identities" and method == "GET":
            self._json(route, {"identities": [{
                "id": "workspace-identity", "display_name": "Workspace managed identity",
                "name": "Workspace managed identity", "type": "managed_identity",
                "auth_type": "managed_identity", "is_enabled": True,
            }]})
        elif path == "/api/conversations/feed" and method == "GET":
            self._json(route, {
                "success": True, "conversations": self.conversations, "has_more": False,
                "next_cursor": None, "page_size": 30, "hidden_count": 0, "priority_count": 0,
                "recent_count": len(self.conversations), "source_offsets": {},
            })
        elif path == "/api/get_messages" and method == "GET":
            identifier = entry.query["conversation_id"][0]
            assert identifier in self.messages, entry
            self._json(route, {"messages": self.messages[identifier]})
        elif method == "GET" and re.fullmatch(r"/api/conversations/[^/]+/kind", path):
            identifier = path.split("/")[3]
            assert identifier in self.messages, entry
            self._json(route, {"conversation_id": identifier, "kind": "personal"})
        elif method == "GET" and re.fullmatch(r"/api/conversations/[^/]+/metadata", path):
            identifier = path.split("/")[3]
            record = next(item for item in self.conversations if item["id"] == identifier)
            self._json(route, {
                **record, "conversation_id": identifier, "tags": [], "context": [],
                "classification": [], "used_documents": [], "linked_workspace_documents": [],
            })
        elif method == "GET" and re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            identifier = path.rsplit("/", 1)[-1]
            assert identifier in self.messages, entry
            self._json(route, {"active": False, "pending": False, "reattachable": False})
        elif path == "/api/create_conversation" and method == "POST":
            assert set(entry.body) == {"initial_message"}
            identifier = f"created-workspace-chat-{len(self.conversations)}"
            record = {"id": identifier, "title": "New workspace chat", "user_id": OWNER_ID}
            self.conversations.append(record)
            self.messages[identifier] = []
            self._json(route, {"conversation_id": identifier, "title": record["title"]})
        elif path == "/api/chat/stream" and method == "POST":
            identifier = entry.body["conversation_id"]
            assert identifier in self.messages, entry
            self.messages[identifier].append({
                "id": "workspace-message", "role": "user", "content": entry.body["message"],
                "conversation_id": identifier, "timestamp": "2026-09-05T12:01:00Z",
            })
            frames = [
                {"content": "Workspace review response."},
                {"done": True, "conversation_id": identifier, "message_id": "workspace-answer"},
            ]
            route.fulfill(
                content_type="text/event-stream",
                body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
            )
        elif path == "/api/openapi/upload" and method == "POST":
            if not route.request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
                self.unexpected_requests.append("Unsupported non-file OpenAPI import request.")
                self._json(route, {"error": "OpenAPI specifications must be uploaded as files."}, 400)
            else:
                self._json(route, self.extra_posts[path])
        elif method == "GET" and path in self.extra_gets:
            self._json(route, self.extra_gets[path])
        elif method == "POST" and path in self.extra_posts:
            self._json(route, self.extra_posts[path])
        elif re.fullmatch(r"/api/user/(agents|plugins)(/[^/]+)?", path):
            self._resource(route, entry)
        else:
            self.unexpected_requests.append(f"{method} {path}?{urlsplit(route.request.url).query}")
            route.fulfill(status=404, json={"error": "Unexpected workspace fixture request."})

    def _resource(self, route, entry):
        _, _, _, kind, *identifiers = entry.path.split("/")
        resources = self.agents if kind == "agents" else self.actions
        identifier = identifiers[0] if identifiers else None
        assert entry.query.get("view") == ["editor"], entry
        assert set(entry.query) <= {"view", "scope"}, entry
        scope = entry.query.get("scope", ["personal"])[0]
        assert scope in ("personal", "global"), entry
        if scope == "global" and entry.method != "GET":
            self._json(route, {"error": "Provided resources are read-only."}, 403)
            return
        if identifier in self.denied_resources:
            self._json(route, {"error": "You no longer have permission to access this resource."}, 403)
            return
        record = resources.get(identifier)
        if record and bool(record.get("is_global")) != (scope == "global"):
            record = None
        if entry.method == "GET":
            if not identifier:
                self._json(route, [self.projected(item) for item in resources.values()])
            elif record:
                self._json(route, self.envelope(record))
            else:
                self._json(route, {"error": "Resource not found."}, 404)
            return
        if record and record.get("is_global"):
            self._json(route, {"error": "Provided resources are read-only."}, 403)
            return
        if entry.method == "DELETE" and record:
            assert entry.body is None
            del resources[identifier]
            self._json(route, {"success": True})
            return
        assert entry.method in ("POST", "PATCH"), entry
        assert isinstance(entry.body, dict), "Whole-collection authoring writes are prohibited."
        expected_keys = {"updates", "clear_secret_paths", "removed_paths"}
        if entry.method == "PATCH":
            expected_keys.add("expected_revision")
        assert set(entry.body) == expected_keys, entry
        updates = entry.body["updates"]
        assert isinstance(updates, dict)
        assert not {"user_id", "created_by", "is_global", "is_group", "revision", "secret_paths"} & set(updates)
        assert not any(key.startswith("_") for key in updates), "Ephemeral editor state must not be persisted."
        if entry.method == "PATCH":
            assert identifier and record, entry
            assert "id" not in updates, "An edit cannot replace the resource identifier."
            if entry.body["expected_revision"] != self.revision(identifier):
                self._json(route, {"error": "This resource changed in another session. Reload before saving."}, 409)
                return
        else:
            assert identifier is None, entry
            if kind == "agents":
                identifier = updates["id"]
            else:
                assert "id" not in updates
                self.created_counts["plugins"] += 1
                identifier = f"10000000-0000-4000-8000-{100 + self.created_counts['plugins']:012d}"
            assert identifier not in resources
            record = {"id": identifier, "user_id": OWNER_ID, "is_global": False}
        paths = self.secret_paths.get(identifier, [])
        try:
            record = _editor_candidate(
                record, updates, paths,
                entry.body["clear_secret_paths"], entry.body["removed_paths"],
            )
        except EditorSecretError:
            self._json(route, {
                "error": "Stored credentials must be kept at their original paths, replaced, or explicitly cleared.",
            }, 400)
            return
        self.secret_paths[identifier] = [
            pointer for pointer in paths if pointer not in entry.body["clear_secret_paths"]
        ]
        if record.get("auth", {}).get("key"):
            paths = self.secret_paths.setdefault(identifier, [])
            if "/auth/key" not in paths:
                paths.append("/auth/key")
        resources[identifier] = record
        self.revisions[identifier] = self.revisions.get(identifier, 0) + 1
        self._json(route, self.envelope(record), 201 if entry.method == "POST" else 200)

    def open(self, path="/workspace/actions", *, theme="light", width=1440, height=900):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the real V2 SPA before running workspace authoring UI tests.")
        expected_js = os.getenv("SIMPLECHAT_UI_EXPECTED_JS", "")
        expected_css = os.getenv("SIMPLECHAT_UI_EXPECTED_CSS", "")
        if expected_js or expected_css:
            if not expected_js or not expected_css:
                pytest.fail("Set both SIMPLECHAT_UI_EXPECTED_JS and SIMPLECHAT_UI_EXPECTED_CSS.")
            index = SPA_INDEX.read_text(encoding="utf-8")
            for filename, attribute, suffix in (
                (expected_js, "src", "js"), (expected_css, "href", "css"),
            ):
                if not re.fullmatch(rf"[A-Za-z0-9_.-]+\.{suffix}", filename):
                    pytest.fail("Expected build assets must be local filenames.")
                asset = STATIC_ROOT / "v2" / "assets" / filename
                reference = f'/static/v2/assets/{filename}'
                if not asset.is_file() or not re.search(rf'{attribute}=["\']{re.escape(reference)}["\']', index):
                    pytest.fail("The explicitly released SPA assets are missing or have changed.")
        else:
            source_root = ROOT / "application" / "v2_ui" / "src"
            if any(
                source.stat().st_mtime > SPA_INDEX.stat().st_mtime
                for source in source_root.rglob("*") if source.is_file()
            ):
                pytest.fail("The production V2 bundle is stale; rebuild it before running this suite.")
        self.preferences.update({
            "darkModeEnabled": theme == "dark", "v2RailCollapsed": width < 1024,
            "v2WorkspaceRailCollapsed": width < 1024, "fontSizePreference": "m",
        })
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}/v2{path}", wait_until="networkidle")
        expect(self.page.locator("html")).to_have_css("color-scheme", theme)
        assert any(path.endswith(".js") for path in self.loaded_assets), "Real SPA JavaScript was not loaded."
        assert any(path.endswith(".css") for path in self.loaded_assets), "Production CSS was not loaded."

    def assert_no_overflow(self):
        assert self.page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Workspace overflows the viewport horizontally."
        main = self.page.get_by_role("main")
        assert main.evaluate(
            "element => element.scrollWidth <= element.clientWidth + 1"
        ), "Workspace content is clipped horizontally."

    def assert_no_secret_storage(self, *draft_values, page=None):
        self.private_values.update(draft_values)
        storage = (page or self.page).evaluate(
            "() => JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})"
        ) + json.dumps(self.preferences)
        for value in self.private_values:
            assert value not in storage, f"Editor data must not be persisted in storage or preferences: {value!r}"

    def assert_clean(self):
        unexpected_console = [
            (text, url) for text, url in self.console_errors
            if not any(
                url == expected_url
                and re.fullmatch(
                    rf"Failed to load resource: the server responded with a status of {status} \([^)]*\)",
                    text,
                )
                for expected_url, status in self.expected_http_errors
            )
        ]
        assert not self.pending_responses, "A test left an explicit request gate closed."
        assert not self.failures, "An expected failed request was never made."
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors
        assert not unexpected_console, unexpected_console
        for page in self.pages:
            if not page.is_closed() and page.url.startswith(ORIGIN):
                self.assert_no_secret_storage(page=page)
        for _, payload in self.responses:
            serialized = json.dumps(payload)
            assert STORED_KEY not in serialized, "A stored credential crossed the fixture API boundary."
            assert STORED_HEADER not in serialized, "A stored MCP header crossed the fixture API boundary."


@pytest.fixture
def workspace_ui(page):
    fixture = WorkspaceAuthoringFixture(page)
    yield fixture
    fixture.assert_clean()
