# v2_admin_global_editors.py
"""
Closed API fixtures for the V2 Admin Settings global agents and actions.
Version: 0.261.268
Implemented in: 0.261.268

Extend the schema-backed Admin Settings fixture with an in-memory store for the
organisation's global agents and actions. It answers the admin-only V2 editor
routes (/api/v2/admin/agents and /api/v2/admin/actions, with their options and
types) with the server's editor contract -- masked credentials, opaque revisions,
and writes made of updates, removed paths and explicit secret intent -- and the
classic enable, default-agent, knowledge and template routes the Admin Settings
lists and the shared editors reuse. The real built SPA runs unchanged. No
application server, signed-in account, or live write is involved, and any
request the fixture does not expect fails the test.
"""

import copy
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import Route

from v2_admin_settings import ORIGIN, REPO_ROOT, SPA_INDEX, AdminSettingsFixture, connect_options  # noqa: F401


SCHEMA_ROOT = REPO_ROOT / "application" / "single_app" / "static" / "json" / "schemas"
SECRET_MASK = "***REDACTED***"
STORED_KEY = "fixture-only-global-credential"
RESEARCH_AGENT_ID = "20000000-0000-4000-8000-000000000001"
POLICY_AGENT_ID = "20000000-0000-4000-8000-000000000002"
ARCHIVE_AGENT_ID = "20000000-0000-4000-8000-000000000003"
CREATED_AGENT_ID = "20000000-0000-4000-8000-000000000101"
TICKET_ACTION_ID = "30000000-0000-4000-8000-000000000001"
FORECAST_ACTION_ID = "30000000-0000-4000-8000-000000000002"
CREATED_ACTION_ID = "30000000-0000-4000-8000-000000000101"
MODEL_LABEL = "Organization GPT · Organization models"

# The Agents & Actions sections that carry the global lists, the template gallery
# switch the agent list reads, and the approvals link -- in navigation order.
GLOBAL_SECTIONS = {
    "agents-actions": (
        "agents-config",
        "organization-agents-section",
        "agent-toggles-card",
        "agent-template-approvals-section",
        "core-plugin-toggles",
        "actions-config",
    ),
}
# Fields the server stamps or owns. The editors never send them as an update or a
# removal; the client strips the first set and the global adapters strip the second.
_SERVER_FIELDS = {
    "user_id", "last_updated", "modified_at", "modified_by", "created_at", "created_by",
    "is_global", "is_group", "group_id", "revision", "secret_paths",
    "scope", "scope_id", "scope_type", "updated_at", "updated_by", "owner_id", "owner_user_id",
}


def global_agent(identifier, name, display_name, **overrides):
    """A stored global agent, as the global agents container holds one."""
    record = {
        "id": identifier,
        "name": name,
        "display_name": display_name,
        "description": f"{display_name} for everyone in the organisation.",
        "instructions": "Answer with the organisation's approved guidance.",
        "agent_type": "local",
        "actions_to_load": [],
        "other_settings": {},
        "max_completion_tokens": -1,
        "model_endpoint_id": "org-model-endpoint",
        "model_id": "org-model",
        "model_provider": "aoai",
        "azure_openai_gpt_deployment": "org-gpt",
        "tags": [],
        "is_global": True,
        "is_group": False,
        "is_enabled": True,
        "created_by": "previous-admin",
    }
    record.update(copy.deepcopy(overrides))
    return record


def global_action(identifier, name, display_name, **overrides):
    """A stored global action, stamped with the global scope as the server saves one."""
    record = {
        "id": identifier,
        "name": name,
        "displayName": display_name,
        "description": f"{display_name} for global agents.",
        "type": "fixture_custom",
        "endpoint": "https://tickets.example.test/api",
        "auth": {"type": "key", "key": STORED_KEY},
        "additionalFields": {"region": "east", "limit": 5, "enabled": False},
        "metadata": {},
        "is_global": True,
        "is_group": False,
        "scope": "global",
        "scope_id": "global",
        "is_enabled": True,
        "created_by": "previous-admin",
    }
    record.update(copy.deepcopy(overrides))
    return record


def global_agent_options():
    """What /api/v2/admin/agent-options answers: every agent type and the global models."""
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
            "merge_global_semantic_kernel_with_workspace": False,
            "enable_multi_model_endpoints": True,
            "default_model_selection": {},
            "gpt_model": {},
            "enable_gpt_apim": False,
            "azure_apim_gpt_deployment": "",
            "enable_agent_template_gallery": True,
            "enable_web_search": False,
            "enable_url_access": False,
            "enable_key_vault_secret_storage": False,
            "enable_key_vault_secret_expiration_reminders": False,
            "key_vault_secret_expiration_default_lead_days": 30,
            "key_vault_secret_expiration_default_contact_email": "",
            "key_vault_secret_expiration_require_expiration": False,
            "agent_template_submission_allowed": True,
        },
        "model_endpoints": [{
            "id": "org-model-endpoint",
            "name": "Organization models",
            "provider": "aoai",
            "scope": "global",
            "enabled": True,
            "models": [{
                "id": "org-model",
                "deploymentName": "org-gpt",
                "modelName": "gpt-4o",
                "displayName": "Organization GPT",
                "enabled": True,
            }],
        }],
        "builtin_actions": [],
    }


def global_action_types():
    """What /api/v2/admin/actions/types answers, narrowed to a connector and Call agent."""
    return [{
        "type": "fixture_custom",
        "display": "Ticket connector",
        "description": "A server-discovered connector to the ticket service.",
        "allowed_auth_types": ["NoAuth", "key"],
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
    }, {
        # Call agent is an ordinary action type, described as the real type builder does.
        "type": "agent",
        "display": "Call agent",
        "description": "Call another agent with a task.",
        "allowed_auth_types": json.loads((SCHEMA_ROOT / "agent.definition.json").read_text(encoding="utf-8"))["allowedAuthTypes"],
        "additional_fields_schema": json.loads(
            (SCHEMA_ROOT / "agent_plugin.additional_settings.schema.json").read_text(encoding="utf-8")
        ),
        "metadata_schema": {"type": "object", "properties": {}, "additionalProperties": True},
    }]


def _pointer_parts(pointer):
    assert pointer.startswith("/"), f"Expected a JSON pointer, received {pointer!r}"
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _get_pointer(record, pointer):
    current = record
    for key in _pointer_parts(pointer):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _set_pointer(record, pointer, value):
    parts = _pointer_parts(pointer)
    parent = record
    for key in parts[:-1]:
        parent = parent.setdefault(key, {})
    parent[parts[-1]] = value


def _remove_pointer(record, pointer):
    parts = _pointer_parts(pointer)
    parent = record
    for key in parts[:-1]:
        if not isinstance(parent, dict) or key not in parent:
            return
        parent = parent[key]
    if isinstance(parent, dict):
        parent.pop(parts[-1], None)


def _merge_updates(record, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            _merge_updates(record[key], value)
        else:
            record[key] = copy.deepcopy(value)


class GlobalEditorsFixture(AdminSettingsFixture):
    """Admin Settings plus a scripted global agents and actions boundary."""

    def __init__(self, page, *, sections=None, admin=True, **kwargs):
        super().__init__(page, sections=sections or GLOBAL_SECTIONS, **kwargs)
        self.is_admin = admin
        self.settings["enable_agent_template_gallery"] = True
        self.agents = {
            RESEARCH_AGENT_ID: global_agent(RESEARCH_AGENT_ID, "research-assistant", "Research assistant"),
            POLICY_AGENT_ID: global_agent(POLICY_AGENT_ID, "policy-advisor", "Policy advisor"),
            ARCHIVE_AGENT_ID: global_agent(
                ARCHIVE_AGENT_ID, "archive-summarizer", "Archive summarizer", is_enabled=False,
            ),
        }
        self.selected_agent_name = "research-assistant"
        self.actions = {
            TICKET_ACTION_ID: global_action(TICKET_ACTION_ID, "ticket_search", "Ticket search"),
            FORECAST_ACTION_ID: global_action(
                FORECAST_ACTION_ID, "forecast_lookup", "Forecast lookup",
                auth={"type": "NoAuth"}, is_enabled=False,
            ),
        }
        self.secret_paths = {TICKET_ACTION_ID: ["/auth/key"]}
        self.revisions = {identifier: 1 for identifier in (*self.agents, *self.actions)}
        self.knowledge_catalog = {
            "sources": [{"scope": "public", "id": "public-handbook", "label": "Published handbook"}],
            "documents": [{
                "id": "public-guide", "title": "Public review guide", "file_name": "review-guide.pdf",
                "scope": "public", "source_id": "public-handbook", "source_name": "Published handbook",
                "tags": ["Operations"],
            }],
            "tags": [{"name": "Operations", "count": 1}],
        }
        self.templates = [{
            "id": "approved-onboarding", "title": "Onboarding guide", "display_name": "Onboarding guide",
            "description": "Answer questions from people who have just joined.",
            "instructions": "Help new colleagues find onboarding answers in the approved handbook.",
            "actions_to_load": [], "tags": ["onboarding"], "additional_settings": {},
        }]
        # Every request the page made, and those the global boundary answered and wrote.
        self.requests_seen = []
        self.global_requests = []
        self.global_writes = []
        self.global_responses = []
        # Failures a test scripts on purpose, and the browser console errors they cause.
        self.pending_failures = []
        self.expected_failure_statuses = []

    # --- Server-side helpers -------------------------------------------------

    def _bootstrap(self):
        payload = super()._bootstrap()
        if not self.is_admin:
            payload["user"] = {**payload["user"], "is_admin": False, "roles": ["User"]}
        return payload

    def admin_reads(self):
        """Requests for administrator data, which a non-administrator's page must never make."""
        return [
            (method, path) for method, path in self.requests_seen
            if path.startswith(("/api/v2/admin/", "/api/admin/")) or path == "/api/plugins/agent-targets"
        ]

    def global_targets(self):
        """The global agents a global Call agent action may target: enabled local ones."""
        return [
            {
                "id": agent["id"], "name": agent["name"], "display_name": agent["display_name"],
                "description": agent["description"], "agent_type": agent["agent_type"],
                "scope_type": "global", "scope_id": "global",
            }
            for agent in self.agents.values()
            if agent.get("is_enabled", True) and agent.get("agent_type", "local") == "local"
        ]

    def revision(self, identifier):
        return f"global-revision:{identifier}:{self.revisions[identifier]}"

    def projected(self, record):
        result = copy.deepcopy(record)
        for pointer in self.secret_paths.get(record["id"], []):
            _set_pointer(result, pointer, SECRET_MASK)
        return result

    def envelope(self, record):
        return {
            "record": self.projected(record),
            "revision": self.revision(record["id"]),
            "secret_paths": list(self.secret_paths.get(record["id"], [])),
            "read_only": False,
        }

    def writes_to(self, method, path):
        return [write for write in self.global_writes if (write[0], write[1]) == (method, path)]

    def fail_next(self, method, path, status=503, error="The service is unavailable."):
        """Answer the next matching request with an error, as a failing server would."""
        self.pending_failures.append((method, path, status, error))

    def _json(self, route, payload, status=200):
        self.global_responses.append(copy.deepcopy(payload))
        if status >= 400:
            self.expected_failure_statuses.append(status)
        route.fulfill(status=status, json=payload)

    def _fail(self, route, reason):
        self.unexpected_requests.append(reason)
        route.fulfill(status=400, json={"error": "Unexpected global editor request."})

    # --- Routing -------------------------------------------------------------

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN:
            self.requests_seen.append((request.method, parsed.path))
        if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and self._global_route(
            route, request.method, parsed.path, parse_qs(parsed.query),
        ):
            return
        super()._route(route)

    def _global_route(self, route, method, path, query):
        """Answer one request on the global boundary, or return False to defer to the base."""
        if method == "GET" and re.fullmatch(r"/v2/admin/(agents|actions)(/[^/]+)?", path):
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return True
        failure = next((item for item in self.pending_failures if item[:2] == (method, path)), None)
        if failure:
            self.pending_failures.remove(failure)
            self._record(method, path, query, None)
            self._json(route, {"error": failure[3]}, failure[2])
            return True
        body = None
        if method in ("POST", "PATCH", "PUT"):
            body = route.request.post_data_json
        elif route.request.post_data:
            self._fail(route, f"{method} {path} carried a body")
            return True

        agent_match = re.fullmatch(r"/api/v2/admin/agents(?:/([^/]+))?", path)
        action_match = re.fullmatch(r"/api/v2/admin/actions(?:/([^/]+))?", path)
        if path == "/api/v2/admin/agent-options" and method == "GET":
            self._record(method, path, query, body)
            self._json(route, global_agent_options())
        elif path == "/api/v2/admin/action-options" and method == "GET":
            self._record(method, path, query, body)
            self._json(route, {"secret_reminders": {
                "storage_enabled": False, "reminders_enabled": False, "require_expiration": False,
                "lead_days": 30, "contact_email": "",
            }})
        elif path == "/api/v2/admin/actions/types" and method == "GET":
            self._record(method, path, query, body)
            self._json(route, {"types": global_action_types()})
        elif agent_match:
            self._record(method, path, query, body)
            self._resource(route, "agents", method, path, unquote(agent_match.group(1) or ""), query, body)
        elif action_match:
            self._record(method, path, query, body)
            self._resource(route, "actions", method, path, unquote(action_match.group(1) or ""), query, body)
        elif path == "/api/agents/generate_id" and method == "GET":
            self._record(method, path, query, body)
            self._json(route, {"id": CREATED_AGENT_ID})
        elif path == "/api/agents/assigned-knowledge/catalog" and method == "GET":
            self._record(method, path, query, body)
            if query != {"agent_scope": ["global"]}:
                self._fail(route, f"A global agent read knowledge outside the global scope: {query}")
            else:
                self._json(route, self.knowledge_catalog)
        elif path == "/api/agent-templates" and method == "GET":
            self._record(method, path, query, body)
            self._json(route, {"templates": copy.deepcopy(self.templates)})
        elif path == "/api/agent-templates" and method == "POST":
            self._record(method, path, query, body)
            template = body.get("template") if isinstance(body, dict) else None
            if not isinstance(template, dict) or template.get("source_scope") != "global":
                self._fail(route, f"A global agent offered a template outside the global scope: {body!r}")
            else:
                # An administrator's global submission is approved as it is published.
                self._json(route, {"template": {**template, "id": "published-template", "status": "approved"}})
        elif path == "/api/admin/workspace-identities/global/identities" and method == "GET":
            self._record(method, path, query, body)
            self._json(route, {"identities": []})
        elif path == "/api/plugins/agent-targets" and method == "GET":
            self._record(method, path, query, body)
            if query != {"scope": ["global"]}:
                self._fail(route, f"A global editor read Call agent targets outside the global scope: {query}")
            else:
                self._json(route, {
                    "targets": self.global_targets(), "can_manage": True,
                    "scope_type": "global", "scope_id": "global",
                })
        elif (match := re.fullmatch(r"/api/admin/agents/([^/]+)/enabled", path)) and method == "PATCH":
            self._record(method, path, query, body)
            self._set_agent_enabled(route, unquote(match.group(1)), body)
        elif path == "/api/admin/agents/selected_agent" and method == "POST":
            self._record(method, path, query, body)
            self._select_agent(route, body)
        elif (match := re.fullmatch(r"/api/admin/plugins/([^/]+)/enabled", path)) and method == "PATCH":
            self._record(method, path, query, body)
            self._set_action_enabled(route, unquote(match.group(1)), body)
        else:
            return False
        return True

    def _record(self, method, path, query, body):
        self.global_requests.append((method, path, query, copy.deepcopy(body)))
        if method != "GET":
            self.global_writes.append((method, path, copy.deepcopy(body)))

    # --- Classic routes the Admin Settings lists reuse ------------------------

    def _agent_named(self, name):
        return next((agent for agent in self.agents.values() if agent["name"] == name), None)

    def _set_agent_enabled(self, route, name, body):
        agent = self._agent_named(name)
        if not isinstance(body, dict) or set(body) != {"is_enabled"} or type(body["is_enabled"]) is not bool:
            self._fail(route, f"Invalid enable request: {body!r}")
            return
        if agent is None:
            self._json(route, {"error": "Agent not found."}, 404)
            return
        agent["is_enabled"] = body["is_enabled"]
        self.revisions[agent["id"]] += 1
        fallback = None
        if not body["is_enabled"] and self.selected_agent_name == name:
            enabled = [item for item in self.agents.values() if item.get("is_enabled", True)]
            fallback = enabled[0]["name"] if enabled else None
            self.selected_agent_name = fallback or ""
        self._json(route, {"success": True, "fallback_agent_name": fallback})

    def _select_agent(self, route, body):
        if not isinstance(body, dict) or set(body) != {"name"}:
            self._fail(route, f"Invalid default-agent request: {body!r}")
            return
        if self._agent_named(body["name"]) is None:
            self._json(route, {"error": "Agent not found."}, 404)
            return
        self.selected_agent_name = body["name"]
        self._json(route, {"success": True})

    def _set_action_enabled(self, route, name, body):
        action = next((item for item in self.actions.values() if item["name"] == name), None)
        if not isinstance(body, dict) or set(body) != {"is_enabled"} or type(body["is_enabled"]) is not bool:
            self._fail(route, f"Invalid enable request: {body!r}")
            return
        if action is None:
            self._json(route, {"error": "Plugin not found."}, 404)
            return
        action["is_enabled"] = body["is_enabled"]
        self.revisions[action["id"]] += 1
        self._json(route, {"success": True})

    # --- The V2 global editor routes ------------------------------------------

    def _resource(self, route, kind, method, path, identifier, query, body):
        store = self.agents if kind == "agents" else self.actions
        if query:
            # The real routes refuse any query string rather than ignoring it.
            self._fail(route, f"{method} {path} carried a query: {query}")
            return
        if method == "GET" and not identifier:
            items = [self.projected(item) for item in store.values()]
            payload = {"agents": items, "selected_agent_name": self.selected_agent_name} if kind == "agents" else {"actions": items}
            self._json(route, payload)
            return
        record = store.get(identifier) if identifier else None
        if identifier and record is None:
            self._json(route, {"error": "Not found."}, 404)
            return
        if method == "GET":
            self._json(route, self.envelope(record))
        elif method == "DELETE":
            if kind == "agents" and record["name"] == self.selected_agent_name:
                self._json(route, {"error": "Choose another default agent before deleting this agent."}, 400)
                return
            del store[identifier]
            self.secret_paths.pop(identifier, None)
            self._json(route, {"success": True})
        elif method in ("POST", "PATCH") and bool(identifier) == (method == "PATCH"):
            self._write(route, kind, store, method, record, body)
        else:
            self._fail(route, f"Unsupported {method} {path}")

    def _write(self, route, kind, store, method, record, body):
        expected = {"updates", "clear_secret_paths", "removed_paths"}
        if method == "PATCH":
            expected.add("expected_revision")
        if not isinstance(body, dict) or set(body) != expected or not isinstance(body["updates"], dict):
            self._fail(route, f"Malformed editor write: {body!r}")
            return
        updates = body["updates"]
        stamped = (_SERVER_FIELDS & set(updates)) | {
            pointer for pointer in body["removed_paths"] if _pointer_parts(pointer)[0] in _SERVER_FIELDS
        }
        if stamped or any(key.startswith("_") for key in updates):
            self._fail(route, f"An editor write named server fields: {sorted(stamped) or list(updates)}")
            return
        if method == "PATCH":
            if "id" in updates:
                self._fail(route, "An edit tried to replace the record identifier.")
                return
            if body["expected_revision"] != self.revision(record["id"]):
                self._json(route, {"error": "This item changed in another session. Reload before saving."}, 409)
                return
            identifier = record["id"]
        elif kind == "agents":
            # A new global agent arrives with the identifier the editor allocated.
            identifier = updates.get("id")
            if identifier != CREATED_AGENT_ID or identifier in store:
                self._fail(route, f"A new agent must carry the allocated identifier, not {identifier!r}")
                return
            record = {"id": identifier}
        else:
            # The server allocates a new action's identifier.
            if "id" in updates:
                self._fail(route, "A new action must not choose its own identifier.")
                return
            identifier = CREATED_ACTION_ID
            record = {"id": identifier, "is_enabled": True}

        known = set(self.secret_paths.get(identifier, []))
        cleared = set(body["clear_secret_paths"])
        if cleared - known:
            self._fail(route, f"Cleared an unknown credential: {sorted(cleared - known)}")
            return
        candidate = copy.deepcopy(record)
        _merge_updates(candidate, updates)
        for pointer in known:
            if _get_pointer(candidate, pointer) == SECRET_MASK:
                # A kept credential is restored from the server's copy, never from the mask.
                _set_pointer(candidate, pointer, copy.deepcopy(_get_pointer(record, pointer)))
        if SECRET_MASK in json.dumps(candidate):
            self._fail(route, "A credential mask would have been stored.")
            return
        for pointer in [*body["removed_paths"], *cleared]:
            _remove_pointer(candidate, pointer)

        noun = "agent" if kind == "agents" else "action"
        taken = {
            str(item.get("name", "")).lower() for key, item in store.items() if key != identifier
        }
        if str(candidate.get("name", "")).lower() in taken:
            self._json(route, {"error": f"A global {noun} with this name already exists."}, 400)
            return
        target = (candidate.get("additionalFields") or {}).get("target_agent")
        if kind == "actions" and candidate.get("type") == "agent" and (
            not isinstance(target, dict)
            or (target.get("scope_type"), target.get("scope_id")) != ("global", "global")
            or target.get("id") not in {item["id"] for item in self.global_targets()}
        ):
            # The server keeps a global action's calls among global agents.
            self._json(route, {
                "error": "Agent calls must stay in the same workspace or use a permitted global agent.",
            }, 403)
            return
        candidate.update({"is_global": True, "is_group": False})
        if kind == "actions":
            candidate.update({"scope": "global", "scope_id": "global"})
        if kind == "agents" and method == "PATCH" and record["name"] == self.selected_agent_name:
            # A renamed default agent stays the default, as the server follows the rename.
            self.selected_agent_name = candidate["name"]
        store[identifier] = candidate
        self.secret_paths[identifier] = sorted(
            (known - cleared) | ({"/auth/key"} if candidate.get("auth", {}).get("key") else set())
        )
        self.revisions[identifier] = self.revisions.get(identifier, 0) + 1
        self._json(route, self.envelope(candidate), 201 if method == "POST" else 200)

    def assert_clean(self):
        assert not self.pending_failures, f"A scripted failure was never requested: {self.pending_failures}"
        # Each error the boundary answered on purpose logs one resource failure in the console.
        for status in self.expected_failure_statuses:
            prefix = f"Failed to load resource: the server responded with a status of {status}"
            match = next((error for error in self.errors if error.startswith(prefix)), None)
            if match is not None:
                self.errors.remove(match)
        super().assert_clean()
        for payload in self.global_responses:
            assert STORED_KEY not in json.dumps(payload), "A stored credential crossed the fixture API boundary."
