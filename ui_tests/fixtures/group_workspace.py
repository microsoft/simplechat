# group_workspace.py
"""
Closed HTTP fixtures for the real V2 group workspace shell.
Version: 0.261.128
Implemented in: 0.261.127

The shell fixture also serves the immutable native `/api/groups/<group_id>/actions[...]`
family and injects the `action_management` context hint, exactly as the M4 backend
does, so the production group Actions page renders its native collection beside the
Call agent manager rather than tripping the fixture on an unexpected request. The
serving machinery lives here in the base class and is reused unchanged by
`GroupActionsFixture`, so both fixtures answer these routes with one implementation.
"""

import copy
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID, SECRET_MASK, SPA_INDEX, EditorSecretError, WorkspaceAuthoringFixture,
    _editor_candidate, _set_pointer, action_record, agent_record, connect_options,  # noqa: F401
    editor_options, personal_scope_leak,
)


SECTION_GROUPS = {
    "documents": "knowledge", "tags": "knowledge", "sync": "knowledge", "prompts": "knowledge",
    "agents": "automation", "actions": "automation", "workflows": "automation",
    "identities": "connections", "endpoints": "connections",
}

# The native group action model, mirrored from the M4 backend so both the shell fixture and the
# dedicated action fixture answer create, edit, delete and test identically.
ACTION_OPERATIONS = ("create", "edit", "delete", "test")
ACTION_ACTIONS = ("edit", "delete", "test")
WRITER_ROLES = ("Owner", "Admin")

# The tenant-level Key Vault reminder defaults the group action editor reads from
# /api/groups/<group_id>/action-options, the group-scoped counterpart to the personal
# /api/user/agent/settings that carries no personal flags or model endpoints. The enabled values
# are distinct from the personal fixture's disabled defaults so a test can prove the editor's
# reminder copy came from the group route rather than a personal-scope read.
GROUP_SECRET_REMINDERS = {
    "storage_enabled": True,
    "reminders_enabled": True,
    "require_expiration": True,
    "lead_days": 45,
    "contact_email": "group-secrets@example.test",
}


def group_action(group_id, identifier, name, *, actions=ACTION_ACTIONS, **overrides):
    """One shared OpenAPI action as the group projector returns it before masking."""
    record = action_record(
        identifier,
        name=name.lower().replace(" ", "-"),
        displayName=name,
        description=f"Shared connector for {name}.",
    )
    record.pop("user_id", None)
    record.update({
        "group_id": group_id,
        "is_group": True,
        "is_global": False,
        "action_actions": list(actions),
    })
    record.update(copy.deepcopy(overrides))
    return record


def action_management(role, status):
    """The management hint. A shipped backend always sends it; a member gets no operations."""
    if role in WRITER_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(ACTION_OPERATIONS)}
    return {"schema_version": 1, "operations": []}


# The native group agent model, mirrored from the M4C backend so both the shell fixture and the
# dedicated agent fixture answer create, edit and delete identically. `agent_actions` is the
# read-only per-agent projection: `edit`/`delete` gate the affordances and a conditional write, and
# `chat` gates the use-in-chat link. It is never accepted back in a write.
AGENT_OPERATIONS = ("create", "edit", "delete")
AGENT_ACTIONS = ("edit", "delete", "chat")

# A group agent may carry a single inline custom-connection credential, stored under this pointer.
# The projector masks it and the editor round-trips the mask, exactly as an action's /auth/key.
AGENT_SECRET_POINTER = "/other_settings/connection/api_key"


def agent_secret_paths(record):
    """The secret pointers a seeded or saved agent registers -- its connection key, when present."""
    value = record.get("other_settings", {}).get("connection", {}).get("api_key")
    return [AGENT_SECRET_POINTER] if isinstance(value, str) and value and value != SECRET_MASK else []


def group_agent(group_id, identifier, name, *, actions=AGENT_ACTIONS, **overrides):
    """One group agent as the group projector returns it before masking."""
    record = agent_record(
        identifier,
        name=name.lower().replace(" ", "-"),
        display_name=name,
        description=f"Group assistant for {name}.",
        actions_to_load=[],
    )
    record.pop("user_id", None)
    record.update({
        "group_id": group_id,
        "is_group": True,
        "is_global": False,
        "agent_actions": list(actions),
    })
    record.update(copy.deepcopy(overrides))
    return record


def agent_management(role, status):
    """The agent management hint, computed from policy exactly like `action_management`."""
    if role in WRITER_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(AGENT_OPERATIONS)}
    return {"schema_version": 1, "operations": []}


GROUP_FOUNDRY_ENDPOINT_ID = "group-foundry-connection"
GLOBAL_FOUNDRY_ENDPOINT_ID = "global-foundry-connection"


def group_agent_options(group_id, *, can_author=True, template_submission=True, empty_models=False):
    """The group agent editor options.

    Derived from the shared editor options but carrying no personal endpoint permissions: every
    `allow_user_*` / `allow_personal_*` flag is dropped and replaced with the group-scoped
    custom-endpoint flag, so the editor's custom-connection controls read the group's own policy and
    the options response proves it came from the group route rather than a personal-scope read.

    A member cannot author, so the server withholds every model endpoint and the read-only editor
    shows neutral "Uses a configured model" copy rather than personal authoring guidance. A manager
    additionally receives two Foundry connections that prove the discovery gate: a group-scoped one
    whose discovery route resolves the account's active group -- for which the editor offers no
    discovery -- and a global one with no group dependency, for which discovery is kept.

    `empty_models` models a manager on a legacy-default-model tenant with no multi-model endpoints:
    the list is empty but the caller can still author, so the editable editor keeps its actionable
    "configure a custom connection" guidance rather than the member's neutral read-only copy.

    `agent_template_submission_allowed` is always present, computed server-side for the caller, so
    the group template panel gates on it rather than on the absent personal submission flag.
    """
    options = copy.deepcopy(editor_options())
    settings = options["settings"]
    for key in list(settings):
        if key.startswith("allow_user_") or key.startswith("allow_personal_"):
            settings.pop(key)
    settings["allow_group_custom_endpoints"] = True
    settings["agent_template_submission_allowed"] = bool(can_author and template_submission)
    if not can_author or empty_models:
        options["model_endpoints"] = []
        return options
    options["model_endpoints"].extend([
        {"id": GROUP_FOUNDRY_ENDPOINT_ID, "name": "Group Foundry connection", "provider": "aifoundry",
         "enabled": True, "scope": "group", "connection": {}, "models": []},
        {"id": GLOBAL_FOUNDRY_ENDPOINT_ID, "name": "Global Foundry connection", "provider": "aifoundry",
         "enabled": True, "scope": "global", "connection": {}, "models": []},
    ])
    return options


def group_agent_knowledge_catalog(group_id):
    """The group's own assigned-knowledge catalogue: group and public sources, never personal."""
    return {
        "sources": [
            {"scope": "group", "id": group_id, "label": "This group's workspace"},
            {"scope": "public", "id": "public-handbook", "label": "Published handbook"},
        ],
        "documents": [
            {
                "id": f"{group_id}-brief", "title": "Group review brief",
                "file_name": "group-brief.pdf", "scope": "group", "source_id": group_id,
                "source_name": "This group's workspace", "tags": ["Finance"],
            },
            {
                "id": "public-guide", "title": "Public review guide",
                "file_name": "review-guide.pdf", "scope": "public", "source_id": "public-handbook",
                "source_name": "Published handbook", "tags": ["Finance", "Operations"],
            },
        ],
        "tags": [{"name": "Finance", "count": 2}, {"name": "Operations", "count": 1}],
    }


def group_context(identifier, name, *, role="Owner", status="active", viewer=OWNER_ID):
    manager = role in ("Owner", "Admin", "DocumentManager")
    automation = role in ("Owner", "Admin")
    readable = status not in ("inactive", "unknown")
    sections = {
        section: {
            "group": group, "enabled": readable, "reason": None if readable else "This group is inactive.",
            "can_manage": status == "active" and (manager if group == "knowledge" else automation),
        }
        for section, group in SECTION_GROUPS.items()
    }
    for section in ("identities", "sync"):
        sections[section]["enabled"] = readable and manager
        sections[section]["can_manage"] = manager and status == "active"
        if readable and not manager:
            sections[section]["reason"] = "Your role does not permit managing group connections."
    return {
        "schema_version": 1, "enabled": True, "viewer_id": viewer,
        "scope": {"kind": "group", "id": identifier},
        "workspace": {
            "name": name, "description": f"Shared knowledge for {name}.",
            "owner": {"display_name": f"{name} owner", "email": "owner@example.test"},
            "hero_color": "#0078d4", "logo_url": None,
        },
        "role": role, "status": status, "can_manage_workspace": automation,
        "sections": sections,
        "action_management": action_management(role, status),
        "agent_management": agent_management(role, status),
        "native_delegation": {
            "group": "automation", "enabled": readable,
            "reason": None if readable else "This group is inactive.",
            "can_manage": automation and status == "active",
        },
        "document_permissions": {
            "can_view": readable, "can_chat": readable,
            "can_upload": manager and status == "active", "can_edit": manager and status == "active",
            "can_delete": manager and status in ("active", "upload_disabled"),
            "can_download": manager and readable,
        },
        "document_queries": {
            "sort_fields": [
                "_ts", "file_name", "title", "upload_date", "file_size",
                "number_of_pages", "version", "document_classification",
            ],
            "facets": True, "places": True,
        },
    }


class GroupWorkspaceFixture(WorkspaceAuthoringFixture):
    def __init__(self, page):
        super().__init__(page)
        self.group_enabled = True
        self.viewer_id = OWNER_ID
        self.active_group = None
        self.groups = {
            "group-a": group_context("group-a", "Research group"),
            "group-b": group_context("group-b", "Read-only group", role="User"),
        }
        self.denied_groups = set()
        # Groups whose server-computed template-submission gate is off despite a manager viewer, so a
        # manager who still sees no submit button is proven, not just an incidental member read-only.
        self.template_submission_denied = set()
        # Groups whose manager options carry no model endpoints (a legacy-default-model tenant), so
        # a manager still gets actionable authoring guidance rather than the member's neutral copy.
        self.empty_model_groups = set()
        # The submission decision of the last group options served, so a POST /api/agent-templates
        # from a group page whose gate is off is recorded as unexpected rather than answered.
        self._template_submission_allowed = True
        self.delegation_manage = True
        self.group_actions = {}
        self.group_agents = {}
        self.workflows = {}
        self.classic_visits = []
        # Native group action state, kept apart from the legacy `group_actions` delegation store.
        self.created_counter = 0
        self.native_actions = {}
        self.native_secret_paths = {}
        self.native_revisions = {}
        # Native group agent state, again kept apart from the legacy `group_agents` delegation store
        # that feeds the Call agent manager. Agents allocate their own created counter and revisions.
        self.created_agent_counter = 0
        self.native_agents = {}
        self.native_agent_secret_paths = {}
        self.native_agent_revisions = {}
        for group_id in self.groups:
            self.group_agents[group_id] = [{
                "id": "caller", "name": "caller", "display_name": "Local caller",
                "agent_type": "local", "group_id": group_id, "is_group": True,
                "actions_to_load": ["legacy-name"], "other_settings": {},
            }]
            self.group_actions[group_id] = [{
                "id": "group-call", "name": "group-call", "displayName": "Call group reviewer",
                "type": "agent", "endpoint": "internal://agent", "auth": {"type": "user"},
                "group_id": group_id, "is_group": True,
                "additionalFields": {"target_agent": {
                    "id": "reviewer", "scope_type": "group", "scope_id": group_id,
                }},
            }]
            self.workflows[group_id] = [{
                "id": "workflow-1", "name": "Review group files",
                "definition_version": 2, "description": "Review approved sources.", "status": "idle",
                "prompt": "Summarize the selected files.", "group_id": group_id,
                "runner_type": "model", "trigger_type": "manual",
            }]
            # One native action per group so the production Actions page renders a real collection
            # beside the Call agent manager. It stays distinct from the "Call group reviewer" caller
            # action so no locator matches in both lists, and carries no inline credential.
            self._seed(group_id, [
                group_action(group_id, f"{group_id}-connector", "Shared connector",
                             auth={"type": "none"}),
            ])
            # One native agent per group so the production Agents page also renders a real
            # collection. It stays distinct from the legacy "Local caller" delegation agent, so no
            # locator matches in both the native list and the Call agent manager.
            self._seed_agents(group_id, [
                group_agent(group_id, f"{group_id}-assistant", "Group assistant"),
            ])

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["user"]["id"] = self.viewer_id
        payload["features"]["enable_group_workspaces"] = self.group_enabled
        payload["scope"].update({
            "active_group_id": self.active_group,
            "groups": [{"id": group_id, "name": context["workspace"]["name"]} for group_id, context in self.groups.items()],
        })
        return payload

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        path = unquote(parsed.path)
        if route.request.method == "GET":
            if path == "/v2/settings" or path.startswith("/v2/groups"):
                route.fulfill(path=str(SPA_INDEX), content_type="text/html")
                return
            if path in ("/group_workspaces", "/profile") or path.startswith("/groups/"):
                self.classic_visits.append((path, self.active_group))
                route.fulfill(content_type="text/html", body="<html><body>Classic handoff target</body></html>")
                return
        super()._route(route)

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        leak = personal_scope_leak(path, entry.query)
        if leak:
            # A group workspace page must never read a personal-scope resource. The M4 group action
            # and M4C group agent editors resolve every side resource -- reminders, options,
            # knowledge, identities, delegation targets, MCP preconfigurations -- through a
            # group-scoped route, so any personal read reaching this fixture from a group page is a
            # leak. Record it so assert_clean() fails the run rather than silently serving personal
            # data, exactly as two M4 personal reads once slipped past every suite the base answered.
            self.unexpected_requests.append(f"{method} {path} ({leak} from a group page)")
            self._json(route, {"error": "Personal-scope reads are not available on group pages."}, 500)
            return
        if path.startswith("/api/groups/") and path.endswith("/agent-options"):
            self._agent_options(route, entry)
            return
        if path.startswith("/api/groups/") and path.endswith("/agent-knowledge"):
            self._agent_knowledge(route, entry)
            return
        if path.startswith("/api/groups/") and "/agents" in path:
            self._agents(route, entry)
            return
        if path.startswith("/api/groups/") and path.endswith("/action-options"):
            self._action_options(route, entry)
            return
        if path.startswith("/api/groups/") and "/actions" in path:
            self._actions(route, entry)
            return
        if path == "/api/models/foundry/agents" and method == "POST":
            self._foundry_discovery(route, entry)
            return
        if path == "/api/agent-templates" and method == "POST" and not self._template_submission_allowed:
            # The group template panel hides its submit button when the server gate is off, so a POST
            # from a group page whose last options withheld submission is a leaked affordance. Record
            # it rather than answering, exactly as the server 403s a non-admin in that state.
            self.unexpected_requests.append(
                f"POST {path} (template submission is not allowed on this group page)"
            )
            self._json(route, {"error": "Template submission is not allowed for this group."}, 403)
            return
        if path == "/api/groups" and method == "GET":
            term = entry.query.get("search", [""])[0].lower()
            page = int(entry.query.get("page", ["1"])[0])
            size = int(entry.query.get("page_size", ["25"])[0])
            groups = [
                {
                    "id": group_id, "name": context["workspace"]["name"],
                    "description": context["workspace"]["description"], "userRole": context["role"],
                    "isActive": group_id == self.active_group, "status": context["status"],
                }
                for group_id, context in self.groups.items()
                if group_id not in self.denied_groups
                and term in f'{context["workspace"]["name"]} {context["workspace"]["description"]}'.lower()
            ]
            self._json(route, {"groups": groups[(page - 1) * size:page * size], "page": page, "page_size": size, "total_count": len(groups)})
        elif path.startswith("/api/v2/workspaces/group/") and method == "GET":
            group_id = path.rsplit("/", 1)[-1]
            if group_id in self.denied_groups:
                self._json(route, {"error": "You do not have access to the selected group."}, 403)
            elif group_id not in self.groups:
                self._json(route, {"error": "Group not found."}, 404)
            else:
                payload = copy.deepcopy(self.groups[group_id])
                payload["viewer_id"] = self.viewer_id
                self._json(route, payload)
        elif path == "/api/groups/setActive" and method == "PATCH":
            group_id = entry.body["groupId"]
            if group_id in self.denied_groups or group_id not in self.groups:
                self._json(route, {"error": "Unavailable group."}, 403)
            else:
                self.active_group = group_id
                self._json(route, {"message": "Active group saved."})
        elif path == "/api/plugins/agent-targets" and entry.query.get("scope") == ["group"]:
            group_id = entry.query["group_id"][0]
            self._json(route, {
                "scope_type": "group", "scope_id": group_id,
                "can_manage": self.delegation_manage and self.groups[group_id]["native_delegation"]["can_manage"],
                "targets": [{
                    "id": "reviewer", "name": "reviewer", "display_name": "Group reviewer",
                    "description": "Review this group's work.", "agent_type": "local",
                    "scope_type": "group", "scope_id": group_id,
                }],
            })
        elif path == "/api/workflows/m365-run-as-users":
            assert entry.query.get("scope") == ["group"]
            assert entry.query.get("group_id", [None])[0] in self.groups
            self._json(route, {"users": []})
        elif path == "/api/group_documents" and method == "GET":
            scope_key = "group_id" if "group_id" in entry.query else "group_ids"
            assert entry.query.get(scope_key, [None])[0] in self.groups
            assert not {"group_id", "group_ids"}.issubset(entry.query)
            self._json(route, {
                "documents": [], "total_count": 0,
                "page": int(entry.query.get("page", ["1"])[0]),
                "page_size": int(entry.query.get("page_size", ["10"])[0]),
            })
        elif path in ("/api/group_documents/tags", "/api/group_documents/facets") and method == "GET":
            assert len(entry.query.get("group_id", [])) == 1
            assert entry.query["group_id"][0] in self.groups
            assert "group_ids" not in entry.query
            self._json(route, {"tags": []} if path.endswith("/tags") else {
                "total": 0, "untagged": 0, "processing": 0, "errors": 0,
                "recent": 0, "shared_with_me": 0, "by_tag": {}, "by_classification": {},
            })
        elif path.startswith("/api/group/"):
            group_id = entry.query.get("group_id", [None])[0]
            assert group_id in self.groups, f"Every group request needs explicit scope: {entry}"
            if path == "/api/group/agents" and method == "GET":
                self._json(route, {"agents": self.group_agents[group_id]})
            elif path == "/api/group/plugins" and method == "GET":
                self._json(route, {"actions": self.group_actions[group_id]})
            elif "/plugins" in path and method in ("POST", "PATCH", "DELETE"):
                identifier = path.rsplit("/", 1)[-1] if method != "POST" else "new-action"
                rows = [row for row in self.group_actions[group_id] if row["id"] != identifier]
                if method != "DELETE":
                    rows.append({**entry.body, "id": identifier, "is_group": True, "group_id": group_id})
                self.group_actions[group_id] = rows
                self._json(route, {"success": True})
            elif path.endswith("/agent-actions") and method == "PATCH":
                self.group_agents[group_id][0]["actions_to_load"] = ["legacy-name", *entry.body["action_ids"]]
                self._json(route, {"success": True})
            elif path == "/api/group/workflows" and method == "GET":
                self._json(route, {"workflows": self.workflows[group_id]})
            elif path == "/api/group/workflows/editor-options":
                self._json(route, {
                    "definition_version": 2, "scope": {"type": "group", "id": group_id},
                    "can_manage": self.groups[group_id]["sections"]["workflows"]["can_manage"],
                    "max_tasks": 8, "agents": [], "models": [],
                    "default_model": {"label": "Default app model", "valid": True},
                })
            elif path.endswith("/runs"):
                self._json(route, {"runs": []})
            elif path.endswith("/run") or path.endswith("/cancel"):
                workflow = self.workflows[group_id][0]
                workflow["status"] = "running" if path.endswith("/run") else "cancelled"
                if path.endswith("/run"):
                    workflow["active_run_id"] = "run-1"
                else:
                    workflow.pop("active_run_id", None)
                self._json(route, {"workflow": workflow, "run": {"id": "run-1", "durable_execution": True, "status": workflow["status"]}})
            else:
                self.unexpected_requests.append(f"{method} {path}")
                self._json(route, {"error": "Unexpected group fixture request."}, 500)
        else:
            super()._dispatch(route, entry)

    # --- Native group action serving, shared with GroupActionsFixture ---------------------------

    def set_action_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context with an action_management hint for the role and status."""
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        context["action_management"] = copy.deepcopy(action_management(role, status))
        self.groups[group_id] = context
        return context

    def set_agent_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context for an agent role and status.

        `group_context` already computes both the action and agent management hints from the same
        role and status, so this recomputes the whole context -- the agent_management hint follows.
        """
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        self.groups[group_id] = context
        return context

    def _seed(self, group_id, records):
        rows = []
        for record in records:
            identifier = record["id"]
            rows.append(record)
            # Only actions carrying an inline credential register a secret path; an identity-bound
            # or provided action has none, so the projector must not mask a path it never stored.
            paths = ["/auth/key"] if record.get("auth", {}).get("key") else []
            self.native_secret_paths[(group_id, identifier)] = paths
            self.native_revisions[(group_id, identifier)] = 1
        self.native_actions[group_id] = rows

    def record(self, group_id, identifier):
        return next((row for row in self.native_actions.get(group_id, []) if row["id"] == identifier), None)

    def _action_revision(self, group_id, identifier):
        return f"group-rev:{group_id}:{identifier}:{self.native_revisions[(group_id, identifier)]}"

    def touch_action(self, group_id, identifier):
        """Simulate a concurrent edit by another manager: the stored revision moves on."""
        self.native_revisions[(group_id, identifier)] += 1
        return self._action_revision(group_id, identifier)

    def _project_action(self, group_id, record):
        result = copy.deepcopy(record)
        for pointer in self.native_secret_paths.get((group_id, record["id"]), []):
            _set_pointer(result, pointer, SECRET_MASK)
        return result

    def _action_envelope(self, group_id, record):
        actions = record.get("action_actions") or []
        read_only = bool(record.get("is_global")) or "edit" not in actions
        return {
            "record": self._project_action(group_id, record),
            "revision": self._action_revision(group_id, record["id"]),
            "secret_paths": copy.deepcopy(self.native_secret_paths.get((group_id, record["id"]), [])),
            "read_only": read_only,
        }

    def _action_options(self, route, entry):
        # /api/groups/<group_id>/action-options -- its own path segment, so it never collides with
        # /actions/<id>. It answers the tenant reminder defaults to every member role, takes no
        # query and no body, and 400s any query exactly as the server's _reject_query_parameters().
        parts = entry.path.split("/")
        group_id = parts[3]
        assert group_id in self.groups, f"Unknown group action-options scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's actions."}, 403)
            return
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        assert entry.method == "GET", entry
        self._json(route, {"secret_reminders": copy.deepcopy(GROUP_SECRET_REMINDERS)})

    def _actions(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/actions[/types|/<action_id>]
        group_id = parts[3]
        tail = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group action scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's actions."}, 403)
            return
        management = self.groups[group_id].get("action_management", {})
        operations = set(management.get("operations", []))
        # Every native group action route rejects unexpected query parameters with a 400, mirroring
        # the server's _reject_query_parameters(); the frontend therefore sends none. Answering 400
        # here means a regression to ?view=editor fails a test instead of silently passing.
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        if tail == "types":
            # The enriched editor catalogue is a read capability served to every member role, in a
            # {"types": [...]} envelope, exactly as the personal ?view=editor branch returns it.
            assert method == "GET", entry
            self._json(route, {"types": copy.deepcopy(self.types)})
            return
        if tail is None:
            if method == "GET":
                self._json(route, {"actions": [
                    self._project_action(group_id, row) for row in self.native_actions.get(group_id, [])
                ]})
                return
            if method == "POST":
                assert "create" in operations, f"Create reached a workspace without the hint: {entry}"
                self._create(route, entry, group_id)
                return
        else:
            record = self.record(group_id, tail)
            if record is None:
                self._json(route, {"error": "Action not found in this group."}, 404)
                return
            if method == "GET":
                self._json(route, self._action_envelope(group_id, record))
                return
            if method == "PATCH":
                self._patch(route, entry, group_id, tail, record, operations)
                return
            if method == "DELETE":
                assert "delete" in operations and "delete" in (record.get("action_actions") or []), (
                    f"Delete reached a read-only action: {entry}"
                )
                assert entry.body is None, "A group action delete carries no body."
                self.native_actions[group_id] = [
                    row for row in self.native_actions[group_id] if row["id"] != tail
                ]
                self._json(route, {"success": True})
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group action request."}, 500)

    def _create(self, route, entry, group_id):
        assert isinstance(entry.body, dict) and set(entry.body) == {
            "updates", "clear_secret_paths", "removed_paths",
        }, entry
        updates = entry.body["updates"]
        assert isinstance(updates, dict) and "id" not in updates, entry
        assert not {"user_id", "is_global", "is_group", "group_id", "revision", "secret_paths"} & set(updates)
        # action_actions is a read projection the schema does not accept; it must never be echoed
        # into a write, in updates or as a removed path.
        assert "action_actions" not in updates, "action_actions is projection-only; it must not be sent in updates."
        assert "/action_actions" not in entry.body["removed_paths"], "action_actions must not appear in removed_paths."
        self.created_counter += 1
        identifier = f"group-created-{self.created_counter}"
        base = {"id": identifier, "group_id": group_id, "is_group": True, "is_global": False,
                "action_actions": list(ACTION_ACTIONS)}
        try:
            record = _editor_candidate(base, updates, [], entry.body["clear_secret_paths"], entry.body["removed_paths"])
        except EditorSecretError:
            self._json(route, {"error": "Stored credentials must be kept, replaced, or explicitly cleared."}, 400)
            return
        paths = []
        if record.get("auth", {}).get("key"):
            paths.append("/auth/key")
        self.native_actions.setdefault(group_id, []).insert(0, record)
        self.native_secret_paths[(group_id, identifier)] = paths
        self.native_revisions[(group_id, identifier)] = 1
        record["created_at"] = datetime.now(timezone.utc).isoformat()
        self._json(route, self._action_envelope(group_id, record), 201)

    def _patch(self, route, entry, group_id, identifier, record, operations):
        assert "edit" in operations and "edit" in (record.get("action_actions") or []), (
            f"Edit reached a read-only action: {entry}"
        )
        assert isinstance(entry.body, dict) and set(entry.body) == {
            "updates", "expected_revision", "clear_secret_paths", "removed_paths",
        }, entry
        updates = entry.body["updates"]
        assert isinstance(updates, dict) and "id" not in updates, entry
        assert not {"user_id", "is_global", "is_group", "group_id", "revision", "secret_paths"} & set(updates)
        assert "action_actions" not in updates, "action_actions is projection-only; it must not be sent in updates."
        assert "/action_actions" not in entry.body["removed_paths"], "action_actions must not appear in removed_paths."
        if entry.body["expected_revision"] != self._action_revision(group_id, identifier):
            self._json(route, {"error": "This action changed in another session. Reload before saving."}, 409)
            return
        paths = self.native_secret_paths.get((group_id, identifier), [])
        try:
            candidate = _editor_candidate(
                record, updates, paths, entry.body["clear_secret_paths"], entry.body["removed_paths"],
            )
        except EditorSecretError:
            self._json(route, {
                "error": "Stored credentials must be kept at their original paths, replaced, or explicitly cleared.",
            }, 400)
            return
        self.native_secret_paths[(group_id, identifier)] = [
            pointer for pointer in paths if pointer not in entry.body["clear_secret_paths"]
        ]
        if candidate.get("auth", {}).get("key"):
            kept = self.native_secret_paths.setdefault((group_id, identifier), [])
            if "/auth/key" not in kept:
                kept.append("/auth/key")
        index = next(i for i, row in enumerate(self.native_actions[group_id]) if row["id"] == identifier)
        self.native_actions[group_id][index] = candidate
        self.native_revisions[(group_id, identifier)] += 1
        self._json(route, self._action_envelope(group_id, candidate))

    # --- Native group agent serving, shared with GroupAgentsFixture -----------------------------

    def _seed_agents(self, group_id, records):
        rows = []
        for record in records:
            identifier = record["id"]
            rows.append(record)
            self.native_agent_secret_paths[(group_id, identifier)] = agent_secret_paths(record)
            self.native_agent_revisions[(group_id, identifier)] = 1
        self.native_agents[group_id] = rows

    def record_agent(self, group_id, identifier):
        return next((row for row in self.native_agents.get(group_id, []) if row["id"] == identifier), None)

    def _agent_revision(self, group_id, identifier):
        return f"group-agent-rev:{group_id}:{identifier}:{self.native_agent_revisions[(group_id, identifier)]}"

    def touch_agent(self, group_id, identifier):
        """Simulate a concurrent edit by another manager: the stored agent revision moves on."""
        self.native_agent_revisions[(group_id, identifier)] += 1
        return self._agent_revision(group_id, identifier)

    def _project_agent(self, group_id, record):
        result = copy.deepcopy(record)
        for pointer in self.native_agent_secret_paths.get((group_id, record["id"]), []):
            _set_pointer(result, pointer, SECRET_MASK)
        return result

    def _agent_envelope(self, group_id, record):
        actions = record.get("agent_actions") or []
        read_only = bool(record.get("is_global")) or "edit" not in actions
        return {
            "record": self._project_agent(group_id, record),
            "revision": self._agent_revision(group_id, record["id"]),
            "secret_paths": copy.deepcopy(self.native_agent_secret_paths.get((group_id, record["id"]), [])),
            "read_only": read_only,
        }

    def _agent_options(self, route, entry):
        # /api/groups/<group_id>/agent-options -- its own path segment, so it never collides with
        # /agents/<id>. It answers the group editor options to every member role, takes no query and
        # 400s any query exactly as the server's _reject_query_parameters().
        group_id = entry.path.split("/")[3]
        assert group_id in self.groups, f"Unknown group agent-options scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's agents."}, 403)
            return
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        assert entry.method == "GET", entry
        can_author = bool(self.groups[group_id].get("agent_management", {}).get("operations"))
        template_submission = group_id not in self.template_submission_denied
        self._template_submission_allowed = bool(can_author and template_submission)
        self._json(route, group_agent_options(
            group_id, can_author=can_author, template_submission=template_submission,
            empty_models=group_id in self.empty_model_groups))

    def _foundry_discovery(self, route, entry):
        # POST /api/models/foundry/agents -- Foundry resource discovery. The server route resolves a
        # group-scoped connection through the account's ACTIVE group, not the page's, so the group
        # editor must offer no discovery for one; a request that still arrives with scope 'group'
        # from a group page is a cross-scope hazard and is recorded as unexpected. A global
        # connection has no group dependency, so it is answered like the personal path.
        scope = (entry.body or {}).get("scope")
        if scope == "group":
            self.unexpected_requests.append(
                f"POST {entry.path} (group-scoped Foundry discovery from a group page)"
            )
            self._json(route, {"error": "Group-scoped Foundry discovery is not available on a group page."}, 500)
            return
        self._json(route, {
            "agents": [{
                "id": "global-assistant", "name": "global-assistant",
                "display_name": "Global assistant", "description": "A discoverable global resource.",
            }],
            "responses_api_version": "2025-01-01",
        })

    def _agent_knowledge(self, route, entry):
        # /api/groups/<group_id>/agent-knowledge -- the group-scoped assigned-knowledge catalogue,
        # so a group agent never pulls the caller's personal sources. No query, every member role.
        group_id = entry.path.split("/")[3]
        assert group_id in self.groups, f"Unknown group agent-knowledge scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's agents."}, 403)
            return
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        assert entry.method == "GET", entry
        self._json(route, group_agent_knowledge_catalog(group_id))

    def _agents(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/agents[/<agent_id>]
        group_id = parts[3]
        tail = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group agent scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's agents."}, 403)
            return
        management = self.groups[group_id].get("agent_management", {})
        operations = set(management.get("operations", []))
        # Every native group agent route rejects unexpected query parameters with a 400, mirroring
        # the server's _reject_query_parameters(); the frontend therefore sends none.
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        if tail is None:
            if method == "GET":
                self._json(route, {"agents": [
                    self._project_agent(group_id, row) for row in self.native_agents.get(group_id, [])
                ]})
                return
            if method == "POST":
                assert "create" in operations, f"Create reached a workspace without the hint: {entry}"
                self._create_agent(route, entry, group_id)
                return
        else:
            record = self.record_agent(group_id, tail)
            if record is None:
                self._json(route, {"error": "Agent not found in this group."}, 404)
                return
            if method == "GET":
                self._json(route, self._agent_envelope(group_id, record))
                return
            if method == "PATCH":
                self._patch_agent(route, entry, group_id, tail, record, operations)
                return
            if method == "DELETE":
                assert "delete" in operations and "delete" in (record.get("agent_actions") or []), (
                    f"Delete reached a read-only agent: {entry}"
                )
                assert entry.body is None, "A group agent delete carries no body."
                self.native_agents[group_id] = [
                    row for row in self.native_agents[group_id] if row["id"] != tail
                ]
                self._json(route, {"success": True})
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group agent request."}, 500)

    def _create_agent(self, route, entry, group_id):
        assert isinstance(entry.body, dict) and set(entry.body) == {
            "updates", "clear_secret_paths", "removed_paths",
        }, entry
        updates = entry.body["updates"]
        # An agent create carries the client-allocated id in updates, exactly as the personal editor
        # does: saveAgentConfiguration seeds the record with a generated id and keeps it in the diff.
        assert isinstance(updates, dict) and isinstance(updates.get("id"), str) and updates["id"], entry
        assert not {"user_id", "is_global", "is_group", "group_id", "revision", "secret_paths"} & set(updates)
        assert not any(key.startswith("_") for key in updates), "Ephemeral editor state must not be persisted."
        # agent_actions is a read projection the schema does not accept; it must never be echoed into
        # a write, in updates or as a removed path.
        assert "agent_actions" not in updates, "agent_actions is projection-only; it must not be sent in updates."
        assert "/agent_actions" not in entry.body["removed_paths"], "agent_actions must not appear in removed_paths."
        identifier = updates["id"]
        assert self.record_agent(group_id, identifier) is None, f"Agent id already exists: {identifier}"
        base = {"id": identifier, "group_id": group_id, "is_group": True, "is_global": False,
                "agent_actions": list(AGENT_ACTIONS)}
        try:
            record = _editor_candidate(base, updates, [], entry.body["clear_secret_paths"], entry.body["removed_paths"])
        except EditorSecretError:
            self._json(route, {"error": "Stored credentials must be kept, replaced, or explicitly cleared."}, 400)
            return
        record["group_id"] = group_id
        record["is_group"] = True
        record["is_global"] = False
        record["agent_actions"] = list(AGENT_ACTIONS)
        self.native_agents.setdefault(group_id, []).insert(0, record)
        self.native_agent_secret_paths[(group_id, identifier)] = agent_secret_paths(record)
        self.native_agent_revisions[(group_id, identifier)] = 1
        self._json(route, self._agent_envelope(group_id, record), 201)

    def _patch_agent(self, route, entry, group_id, identifier, record, operations):
        assert "edit" in operations and "edit" in (record.get("agent_actions") or []), (
            f"Edit reached a read-only agent: {entry}"
        )
        assert isinstance(entry.body, dict) and set(entry.body) == {
            "updates", "expected_revision", "clear_secret_paths", "removed_paths",
        }, entry
        updates = entry.body["updates"]
        assert isinstance(updates, dict) and "id" not in updates, entry
        assert not {"user_id", "is_global", "is_group", "group_id", "revision", "secret_paths"} & set(updates)
        assert not any(key.startswith("_") for key in updates), "Ephemeral editor state must not be persisted."
        assert "agent_actions" not in updates, "agent_actions is projection-only; it must not be sent in updates."
        assert "/agent_actions" not in entry.body["removed_paths"], "agent_actions must not appear in removed_paths."
        if entry.body["expected_revision"] != self._agent_revision(group_id, identifier):
            self._json(route, {"error": "This agent changed in another session. Reload before saving."}, 409)
            return
        paths = self.native_agent_secret_paths.get((group_id, identifier), [])
        try:
            candidate = _editor_candidate(
                record, updates, paths, entry.body["clear_secret_paths"], entry.body["removed_paths"],
            )
        except EditorSecretError:
            self._json(route, {
                "error": "Stored credentials must be kept at their original paths, replaced, or explicitly cleared.",
            }, 400)
            return
        candidate["agent_actions"] = record.get("agent_actions") or list(AGENT_ACTIONS)
        self.native_agent_secret_paths[(group_id, identifier)] = agent_secret_paths(candidate)
        index = next(i for i, row in enumerate(self.native_agents[group_id]) if row["id"] == identifier)
        self.native_agents[group_id][index] = candidate
        self.native_agent_revisions[(group_id, identifier)] += 1
        self._json(route, self._agent_envelope(group_id, candidate))


@pytest.fixture
def group_ui(page):
    fixture = GroupWorkspaceFixture(page)
    yield fixture
    fixture.assert_clean()
