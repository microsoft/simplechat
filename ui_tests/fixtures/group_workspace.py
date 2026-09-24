# group_workspace.py
"""
Closed HTTP fixtures for the real V2 group workspace shell.
Version: 0.261.143
Implemented in: 0.261.127

The shell fixture also serves the immutable native `/api/groups/<group_id>/actions[...]`,
`/agents[...]`, `/identities[...]` and `/model-endpoints[...]` families -- plus the group
`/api/groups/<group_id>/models/{fetch,test-model,foundry/agents}` discovery and test routes --
and injects the `action_management`, `agent_management`, `identity_management` and
`endpoint_management` context hints, exactly as the M4, M5A and M5C backends do, so the
production group Actions, Agents, Identities and Endpoints pages render their native
collections -- and the action editor lists reusable group identities while the group agent
editor discovers Foundry resources through the named-group route -- rather than tripping the
fixture on an unexpected request. Any `/api/v2/admin/*` request from a group page is recorded
as a leaked admin surface, exactly as a personal read is. The serving machinery lives here in
the base class and is reused unchanged by the dedicated per-section fixtures, so each fixture
answers these routes with one implementation.
"""

import copy
import hashlib
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


# The native group identity model, mirrored from the M5A backend so both the shell fixture and the
# dedicated identity fixture answer list, read, create, edit and delete identically. Identity manage
# roles are broader than actions' writer roles -- Owner, Admin and DocumentManager -- matching the
# legacy `/api/workspace-identities/group` routes, and reads use the same roles, so an ordinary member
# cannot list identities. `identity_actions` is the read-only per-identity projection (`edit`/`delete`)
# the policy computes; the write body is the strict field set the classic editor sends, plus
# `expected_etag` for the conditional PATCH and DELETE. Identities carry no `_editor_candidate`
# secret-path machinery: a stored secret is a `password_stored`/`secret_stored` boolean pair and a
# `ui_trigger_word` placeholder, exactly as `sanitize_workspace_identity` returns it.
IDENTITY_OPERATIONS = ("create", "edit", "delete")
IDENTITY_ACTIONS = ("edit", "delete")
IDENTITY_MANAGE_ROLES = ("Owner", "Admin", "DocumentManager")
IDENTITY_TRIGGER_WORD = "Stored_In_KeyVault"

# The strict top-level fields the native identity write accepts (§10). Anything else is a 400.
IDENTITY_WRITE_FIELDS = frozenset({
    "name", "description", "provider", "source_type", "usage_contexts",
    "supported_source_types", "metadata", "credentials",
})

# The generic message every unclassified ValueError becomes; the reviewed field messages the backend
# raises as public validation errors are modelled in `_identity_validation_error`.
IDENTITY_GENERIC_ERROR = "The workspace identity details are not valid."
IDENTITY_CONFLICT_ERROR = "This workspace identity was modified. Reload and try again."
IDENTITY_IN_USE_ERROR = "This workspace identity is still in use."


def identity_management(role, status):
    """The identity management hint, computed from policy exactly like `action_management`."""
    if role in IDENTITY_MANAGE_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(IDENTITY_OPERATIONS)}
    return {"schema_version": 1, "operations": []}


def group_identity(group_id, identifier, name, *, usage=("action",), auth_type="api_key",
                   secret_stored=True, actions=IDENTITY_ACTIONS, username="", domain="",
                   client_identity="", provider=None, source_types=None, description=None,
                   metadata=None):
    """One group identity as the native projector returns it, before etag and masking are applied.

    The stored credential is modelled as a boolean plus a placeholder, never a plaintext secret, so a
    blank secret on save keeps it (`_secret` stays set) and a fresh value replaces it.
    """
    sources = list(source_types) if source_types is not None else [provider or "action"]
    resolved_provider = provider or sources[0]
    return {
        "id": identifier,
        "identity_id": identifier,
        "type": "workspace_identity",
        "scope_type": "group",
        "group_id": group_id,
        "name": name,
        "description": description if description is not None else f"Reusable {name}.",
        "provider": resolved_provider,
        "source_type": resolved_provider,
        "usage_contexts": list(usage),
        "supported_source_types": sources,
        "metadata": copy.deepcopy(metadata) if metadata else {},
        "created_by": OWNER_ID,
        "updated_by": OWNER_ID,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-02T00:00:00+00:00",
        "identity_actions": list(actions),
        "_auth_type": auth_type,
        "_username": username,
        "_domain": domain,
        "_client_identity": client_identity,
        "_secret": bool(secret_stored),
    }


def _identity_credentials(record):
    """The sanitized `credentials` block: no plaintext, a placeholder when a secret is stored."""
    auth_type = record["_auth_type"]
    uses_password = auth_type == "username_password"
    stored = bool(record["_secret"]) and auth_type not in ("anonymous", "managed_identity")
    placeholder = IDENTITY_TRIGGER_WORD if stored else ""
    return {
        "auth_type": auth_type,
        "username": record.get("_username", ""),
        "domain": record.get("_domain", ""),
        "identity": record.get("_client_identity", ""),
        "password_stored": stored and uses_password,
        "secret_stored": stored and not uses_password,
        "password": placeholder if uses_password else "",
        "secret": "" if uses_password else placeholder,
    }


def _sanitize_identity(record):
    """Project a stored identity to its sanitized response: drop `_*` keys and the actions projection,
    add `credentials`. The native routes then add `etag` and `identity_actions` in `_identity_payload`.
    """
    result = {key: copy.deepcopy(value) for key, value in record.items()
              if not key.startswith("_") and key != "identity_actions"}
    result["credentials"] = _identity_credentials(record)
    return result


# --- Native group model endpoint modelling (M5C) -------------------------------------------------
# The group Endpoints section reuses the admin ModelConnectionsManager through a scope-aware adapter
# rather than a fork, so the fixture serves the immutable `/api/groups/<group_id>/model-endpoints[...]`
# CRUD family plus the group `/api/groups/<group_id>/models/{fetch,test-model,foundry/agents}`
# discovery and test routes. `endpoint_management` gates create; each row's `endpoint_actions` gates
# edit, enable, delete and test, with no fallback. Unlike identities, the list is readable by an
# ordinary member -- they simply get an empty operations hint and rows without `endpoint_actions` --
# so a member sees the read-only collection, exactly as the server projects it. The response carries
# no per-item group ID: identity is proven at the envelope, so a returned endpoint never has to name
# its group and the reader validates the list shape instead.
ENDPOINT_OPERATIONS = ("create", "edit", "enable", "delete", "test")
ENDPOINT_ACTIONS = ("edit", "enable", "delete", "test")
# The server's GROUP_ENDPOINT_WRITE_ROLES: only Owner and Admin may write. A DocumentManager reads
# the collection but never manages it, so it is deliberately excluded and left read-only.
ENDPOINT_MANAGE_ROLES = ("Owner", "Admin")

# The strict write body the native endpoint routes accept; `expected_revision` rides the PATCH.
ENDPOINT_CONFLICT_ERROR = "This model endpoint changed. Reload it before saving."
GROUP_WRITE_CONFLICT_ERROR = "The group changed while this model endpoint was being saved. Try again."
# The server's exact in-use and no-change texts (functions_group_endpoint_access.py), shown verbatim
# by the editor so a test proves the server's own wording renders (§11 F3.5).
ENDPOINT_IN_USE_ERROR = (
    "This model endpoint is used by group agents or workflows. "
    "Change them to another endpoint, or disable this endpoint instead."
)
ENDPOINT_NO_CHANGE_ERROR = "No fields provided for update."
# The reviewed stored-credential 400s the native routes raise verbatim (§10); shown as-is so a test
# proves the editor renders the server's own text. Mirroring `_check_client_credentials`, a Key Vault
# reference is refused outright, while a masked placeholder is refused only where nothing is stored.
ENDPOINT_STORED_CREDENTIAL_SUPPLIED = "Stored credential references cannot be supplied in a request."
ENDPOINT_STORED_CREDENTIAL_UNAVAILABLE = "A stored credential is unavailable. Re-enter its value."
ENDPOINT_SECRET_FIELDS = ("api_key", "client_secret", "bearer_token", "access_token", "refresh_token")
ENDPOINT_KEYVAULT_REFERENCE_MARKER = "--model-endpoint--"
ENDPOINT_STORED_SECRET_PLACEHOLDERS = ("Stored_In_KeyVault", "***REDACTED***")


def endpoint_management(role, status):
    """The endpoint management hint, computed from policy exactly like `identity_management`."""
    if role in ENDPOINT_MANAGE_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(ENDPOINT_OPERATIONS)}
    return {"schema_version": 1, "operations": []}


def group_model_endpoint(identifier, name, *, provider="aoai", enabled=True, models=None,
                         actions=ENDPOINT_ACTIONS, api_type=None, has_api_key=True,
                         auth_type="api_key"):
    """One group model endpoint as the native projector returns it, before `revision` and
    `endpoint_actions` are attached by the serving routes.

    The shape mirrors the admin `connection(...)` fixture so the shared ModelConnectionsManager
    renders it identically; it deliberately carries no `group_id`, because the group route proves
    scope at the envelope and the reader validates the list shape rather than a per-item id.
    An `api_key` connection carries a stored key so a rename proves masking survives, while a
    `managed_identity` connection exposes the editor's Azure model discovery, which an API key
    cannot reach.
    """
    if models is None:
        models = [{
            "id": f"{identifier}-chat", "deploymentName": "chat", "modelName": "gpt-4o-mini",
            "selected": True,
        }]
    endpoint = "https://api.openai.com/v1" if provider == "custom" else f"https://{identifier}.openai.azure.com"
    if provider == "aifoundry":
        endpoint = f"https://{identifier}.services.ai.azure.com/api/projects/proj"
    if auth_type == "managed_identity":
        auth = {"type": "managed_identity", "managed_identity_type": "system_assigned"}
    else:
        auth = {"type": "api_key"}
    row = {
        "id": identifier,
        "name": name,
        "provider": provider,
        "enabled": enabled,
        "connection": {
            "endpoint": endpoint,
            "openai_api_version": "2024-05-01-preview",
            "operation_settings": {"image_generation": {"api_version": "2025-04-01-preview"}},
        },
        "management": {"subscription_id": "sub-1234", "resource_group": "rg-models"},
        "auth": auth,
        "has_api_key": has_api_key if auth_type == "api_key" else False,
        "models": copy.deepcopy(models),
        "_actions": tuple(actions),
    }
    if api_type is not None:
        row["api_type"] = api_type
    return row


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
        "identity_management": identity_management(role, status),
        "endpoint_management": endpoint_management(role, status),
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
        # Native group identity state. Identities carry an etag rather than a revision string, so a
        # per-(group, id) revision counter backs the etag and `touch_identity` advances it to model a
        # concurrent edit. `identity_references` records what still uses an identity, so a delete of a
        # referenced identity returns the in-use 409 with references and nothing is removed.
        self.created_identity_counter = 0
        self.native_identities = {}
        self.native_identity_revisions = {}
        self.identity_references = {}
        # Native group model endpoint state, kept apart from every other native store. Endpoints carry
        # an opaque `revision` marker the client round-trips as `expected_revision`, so a per-(group,
        # id) counter backs a SHA-256-shaped revision and `touch_endpoint` advances it to model a
        # concurrent edit. `endpoint_references` records what still uses an endpoint, so a delete of a
        # referenced endpoint returns the in-use 409 with references and nothing is removed. A group in
        # `endpoint_write_conflicts` has its next endpoint write answered with the unrelated
        # `group_write_conflict` 409, whose draft-keeping retry needs no reload.
        self.created_endpoint_counter = 0
        self.native_endpoints = {}
        self.native_endpoint_revisions = {}
        self.endpoint_references = {}
        self.endpoint_write_conflicts = set()
        # One test sets this to a reviewed 400 message so the next endpoint create or edit is refused
        # verbatim, proving the editor renders the server's own text and keeps the draft.
        self.next_endpoint_write_error = None
        # One test flips this to force a malformed endpoint list envelope (no endpoints array), which
        # the section must treat as a hard load error rather than an empty successful load.
        self.malformed_endpoint_list = False
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
            # One native identity per group so the group action editor lists a real reusable identity
            # (the M4 gap, now closed) and the Identities section renders a real collection. It carries
            # the `action` usage so the action editor's action-usage filter surfaces it.
            self._seed_identities(group_id, [
                group_identity(group_id, f"{group_id}-report-identity", "Report API identity",
                               usage=("action",), auth_type="api_key"),
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
        if path.startswith("/api/v2/admin/"):
            # A group page must never reach a tenant-admin route. The scope-aware ModelConnectionsManager
            # routes every group read and write to /api/groups/<g>/..., hiding the admin-only network
            # policy, default-model and migration surfaces, so an /api/v2/admin/* request from a group
            # endpoints section is a leaked admin affordance. Record it rather than answering, exactly
            # as the leak trap does for a personal read.
            self.unexpected_requests.append(f"{method} {path} (admin route from a group page)")
            self._json(route, {"error": "Admin routes are not available on group pages."}, 500)
            return
        if path.startswith("/api/groups/") and path.endswith("/agent-options"):
            self._agent_options(route, entry)
            return
        if path.startswith("/api/groups/") and path.endswith("/agent-knowledge"):
            self._agent_knowledge(route, entry)
            return
        if path.startswith("/api/groups/") and path.endswith("/models/foundry/agents"):
            # This must precede the greedy `/agents` branch below: the named-group Foundry discovery
            # path ends in `/agents`, so an earlier substring match would misroute it to the agent
            # list handler.
            self._group_foundry_discovery(route, entry)
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
        if path.startswith("/api/groups/") and "/identities" in path:
            self._identities(route, entry)
            return
        if path.startswith("/api/groups/") and "/model-endpoints" in path:
            self._model_endpoints(route, entry)
            return
        if path.startswith("/api/groups/") and "/models/" in path:
            self._group_models(route, entry)
            return
        if path == "/api/models/foundry/agents" and method == "POST":
            self._foundry_discovery(route, entry)
            return
        if path == "/api/models/catalog" and method == "GET":
            # The shared connection editor's CatalogProfilePicker stays in group scope, so it reads
            # the account-wide catalogue-profile list here. It is a read-only shared catalogue, not an
            # admin management surface, so a group page legitimately fetches it; the admin discovery
            # and test routes (/api/models/{fetch,test-model,foundry/agents}) are the ones a group
            # page must never touch, and those are served only under the named-group path.
            self._json(route, {"profiles": []})
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

    # --- Native group identity serving, shared with GroupIdentitiesFixture ----------------------

    def _seed_identities(self, group_id, records):
        rows = []
        for record in records:
            rows.append(record)
            self.native_identity_revisions[(group_id, record["id"])] = 1
        self.native_identities[group_id] = rows

    def record_identity(self, group_id, identifier):
        return next((row for row in self.native_identities.get(group_id, []) if row["id"] == identifier), None)

    def _identity_etag(self, group_id, identifier):
        return f"group-identity-etag:{group_id}:{identifier}:{self.native_identity_revisions[(group_id, identifier)]}"

    def touch_identity(self, group_id, identifier):
        """Simulate a concurrent edit by another manager: the stored identity etag moves on."""
        self.native_identity_revisions[(group_id, identifier)] += 1
        return self._identity_etag(group_id, identifier)

    def _identity_payload(self, group_id, record):
        """The sanitized identity plus the two fields the native routes add: `etag` and the
        `identity_actions` projection. `usage_contexts` is already normalized on the stored record."""
        payload = _sanitize_identity(record)
        payload["etag"] = self._identity_etag(group_id, record["id"])
        payload["identity_actions"] = list(record.get("identity_actions", []))
        return payload

    def set_identity_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context for an identity role and status.

        `group_context` computes the `identity_management` hint from the same role and status, so
        recomputing the whole context carries the new hint, exactly like `set_agent_policy`.
        """
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        self.groups[group_id] = context
        return context

    def _identity_validation_error(self, body, prior):
        """The reviewed field messages the backend raises as public validation errors (B3), served
        verbatim so a test proves the editor renders the server's own text. Only the cases a strict
        client can still reach are modelled: a required password or secret that is blank with nothing
        stored to keep. Every other refusal is the generic message."""
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        auth_type = str(credentials.get("auth_type") or "")
        stored = bool(prior["_secret"]) if prior is not None else False
        if auth_type == "username_password":
            if not str(credentials.get("password") or "") and not stored:
                return "Username/password identities require a password"
        elif auth_type not in ("anonymous", "managed_identity"):
            if not str(credentials.get("secret") or "") and not stored:
                return "This identity type requires a secret value"
        return None

    def _identity_from_write(self, group_id, identifier, body, prior):
        """Fold a strict write body onto a new or existing identity. A blank secret (or the
        round-tripped placeholder) keeps whatever is stored; a fresh value replaces it."""
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        auth_type = str(credentials.get("auth_type") or (prior["_auth_type"] if prior else "api_key"))
        uses_password = auth_type == "username_password"
        incoming = str((credentials.get("password") if uses_password else credentials.get("secret")) or "")
        if incoming and incoming != IDENTITY_TRIGGER_WORD:
            secret_stored = True
        elif prior is not None:
            secret_stored = bool(prior["_secret"])
        else:
            secret_stored = False
        provider = str(body.get("provider") or (prior["provider"] if prior else "action"))
        usage = body.get("usage_contexts")
        sources = body.get("supported_source_types")
        metadata = body.get("metadata")
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": identifier,
            "identity_id": identifier,
            "type": "workspace_identity",
            "scope_type": "group",
            "group_id": group_id,
            "name": str(body["name"]) if "name" in body else (prior["name"] if prior else ""),
            "description": str(body["description"]) if "description" in body else (prior["description"] if prior else ""),
            "provider": provider,
            "source_type": str(body.get("source_type") or provider),
            "usage_contexts": list(usage) if isinstance(usage, list) else (list(prior["usage_contexts"]) if prior else ["action"]),
            "supported_source_types": list(sources) if isinstance(sources, list) else (list(prior["supported_source_types"]) if prior else [provider]),
            "metadata": copy.deepcopy(metadata) if isinstance(metadata, dict) else (copy.deepcopy(prior["metadata"]) if prior else {}),
            "created_by": prior["created_by"] if prior else OWNER_ID,
            "updated_by": OWNER_ID,
            "created_at": prior["created_at"] if prior else now,
            "updated_at": now,
            "identity_actions": list(prior["identity_actions"]) if prior else list(IDENTITY_ACTIONS),
            "_auth_type": auth_type,
            "_username": str(credentials.get("username", prior["_username"] if prior else "")),
            "_domain": str(credentials.get("domain", prior["_domain"] if prior else "")),
            "_client_identity": str(credentials.get("identity", prior["_client_identity"] if prior else "")),
            "_secret": secret_stored,
        }

    def _identities(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/identities[/<identity_id>]
        group_id = parts[3]
        tail = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group identity scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's identities."}, 403)
            return
        # Reads use the same manage roles as writes -- Owner, Admin and DocumentManager -- so an
        # ordinary member is refused with 403 on every identity route, exactly as the legacy routes
        # do. The group action editor turns that 403 into a silent resolvable=false and never falls
        # back to a personal identity read.
        if self.groups[group_id].get("role") not in IDENTITY_MANAGE_ROLES:
            self._json(route, {"error": "You do not have access to this group's identities."}, 403)
            return
        # Every native group identity route rejects unexpected query parameters with a 400, mirroring
        # the server's strict request contract; the frontend therefore sends none.
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        operations = set(self.groups[group_id].get("identity_management", {}).get("operations", []))
        if tail is None:
            if method == "GET":
                # A test may force a malformed list envelope (no identities array) to prove the group
                # action editor treats it as a hard load error -- resolvable stays false and a bound
                # identity keeps its neutral "kept as is" copy -- rather than an empty success.
                if getattr(self, "malformed_identity_list", False):
                    self._json(route, {"identities": None})
                    return
                self._json(route, {"identities": [
                    self._identity_payload(group_id, row) for row in self.native_identities.get(group_id, [])
                ]})
                return
            if method == "POST":
                assert "create" in operations, f"Create reached a workspace without the hint: {entry}"
                self._create_identity(route, entry, group_id)
                return
        else:
            record = self.record_identity(group_id, tail)
            if record is None:
                self._json(route, {"error": "Identity not found in this group."}, 404)
                return
            if method == "GET":
                self._json(route, {"identity": self._identity_payload(group_id, record)})
                return
            if method == "PATCH":
                self._patch_identity(route, entry, group_id, tail, record, operations)
                return
            if method == "DELETE":
                self._delete_identity(route, entry, group_id, tail, record, operations)
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group identity request."}, 500)

    def _create_identity(self, route, entry, group_id):
        body = entry.body
        if not isinstance(body, dict) or set(body) - IDENTITY_WRITE_FIELDS:
            self._json(route, {"error": IDENTITY_GENERIC_ERROR}, 400)
            return
        validation = self._identity_validation_error(body, prior=None)
        if validation:
            self._json(route, {"error": validation}, 400)
            return
        self.created_identity_counter += 1
        identifier = f"group-identity-created-{self.created_identity_counter}"
        record = self._identity_from_write(group_id, identifier, body, prior=None)
        self.native_identities.setdefault(group_id, []).insert(0, record)
        self.native_identity_revisions[(group_id, identifier)] = 1
        self._json(route, {"identity": self._identity_payload(group_id, record)}, 201)

    def _patch_identity(self, route, entry, group_id, identifier, record, operations):
        assert "edit" in operations and "edit" in (record.get("identity_actions") or []), (
            f"Edit reached a read-only identity: {entry}"
        )
        body = entry.body
        if not isinstance(body, dict) or "expected_etag" not in body:
            self._json(route, {"error": "This workspace identity is missing its version marker."}, 400)
            return
        if set(body) - IDENTITY_WRITE_FIELDS - {"expected_etag"}:
            self._json(route, {"error": IDENTITY_GENERIC_ERROR}, 400)
            return
        if body["expected_etag"] != self._identity_etag(group_id, identifier):
            self._json(route, {"error": IDENTITY_CONFLICT_ERROR, "error_code": "etag_conflict"}, 409)
            return
        validation = self._identity_validation_error(body, prior=record)
        if validation:
            self._json(route, {"error": validation}, 400)
            return
        updated = self._identity_from_write(group_id, identifier, body, prior=record)
        index = next(i for i, row in enumerate(self.native_identities[group_id]) if row["id"] == identifier)
        self.native_identities[group_id][index] = updated
        self.native_identity_revisions[(group_id, identifier)] += 1
        self._json(route, {"identity": self._identity_payload(group_id, updated)})

    def _delete_identity(self, route, entry, group_id, identifier, record, operations):
        assert "delete" in operations and "delete" in (record.get("identity_actions") or []), (
            f"Delete reached a read-only identity: {entry}"
        )
        body = entry.body
        if not isinstance(body, dict) or set(body) != {"expected_etag"}:
            self._json(route, {"error": "A workspace identity delete carries only its version marker."}, 400)
            return
        if body["expected_etag"] != self._identity_etag(group_id, identifier):
            self._json(route, {"error": IDENTITY_CONFLICT_ERROR, "error_code": "etag_conflict"}, 409)
            return
        references = self.identity_references.get((group_id, identifier))
        if references:
            # A delete refused because the identity is still referenced returns the in-use 409 with
            # references limited to this group; nothing is removed, exactly as the server does.
            self._json(route, {
                "error": IDENTITY_IN_USE_ERROR,
                "error_code": "identity_in_use",
                "references": copy.deepcopy(references),
            }, 409)
            return
        self.native_identities[group_id] = [
            row for row in self.native_identities[group_id] if row["id"] != identifier
        ]
        self._json(route, {"success": True})

    # --- Native group model endpoint serving, shared with GroupEndpointsFixture -----------------

    def _seed_endpoints(self, group_id, records):
        rows = []
        for record in records:
            rows.append(record)
            self.native_endpoint_revisions[(group_id, record["id"])] = 1
        self.native_endpoints[group_id] = rows

    def record_endpoint(self, group_id, identifier):
        return next((row for row in self.native_endpoints.get(group_id, []) if row["id"] == identifier), None)

    def _endpoint_operations(self, group_id):
        """The group's current `endpoint_management` operations, the single source the payload
        projection and the writer-only discovery/test gates both read."""
        return set(self.groups[group_id].get("endpoint_management", {}).get("operations", []))

    def _endpoint_revision(self, group_id, identifier):
        """A SHA-256-shaped revision marker the client round-trips as `expected_revision`, so a stale
        value proves a conditional write rather than a bare integer the client might reason about."""
        counter = self.native_endpoint_revisions[(group_id, identifier)]
        return hashlib.sha256(f"{group_id}:{identifier}:{counter}".encode()).hexdigest()

    def touch_endpoint(self, group_id, identifier):
        """Simulate a concurrent edit by another manager: the stored endpoint revision moves on."""
        self.native_endpoint_revisions[(group_id, identifier)] += 1
        return self._endpoint_revision(group_id, identifier)

    def _endpoint_payload(self, group_id, record):
        """The stored endpoint projected to its response: drop the private `_actions` marker and add
        the two fields the native routes attach -- the opaque `revision` and the `endpoint_actions`
        projection that gates edit, enable, delete and test per row.

        `endpoint_actions` is computed per response like the server's `group_endpoint_actions`: the
        group's current `endpoint_management` operations intersected with the manageable subset and
        the seeded per-row override. It never comes from the seed alone, so a member, a DocumentManager
        or a manager of a non-`active` group -- all of whom carry no operations -- see an empty action
        list and a read-only row, exactly as the server projects it."""
        payload = {key: copy.deepcopy(value) for key, value in record.items() if key != "_actions"}
        payload["revision"] = self._endpoint_revision(group_id, record["id"])
        operations = self._endpoint_operations(group_id)
        seeded = set(record.get("_actions", ()))
        payload["endpoint_actions"] = [
            action for action in ENDPOINT_ACTIONS if action in operations and action in seeded
        ]
        return payload

    def set_endpoint_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context for an endpoint role and status.

        `group_context` computes the `endpoint_management` hint from the same role and status, so
        recomputing the whole context carries the new hint, exactly like `set_identity_policy`.
        """
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        self.groups[group_id] = context
        return context

    def _endpoint_from_write(self, group_id, identifier, body, prior):
        """Fold a strict write body onto a new or existing endpoint. The client omits `has_api_key`
        (a response-only flag) and omits `auth.api_key` when the stored key is kept, so a blank key
        preserves whatever is stored, mirroring the server's credential retention."""
        merged = copy.deepcopy(prior) if prior is not None else {}
        for key, value in body.items():
            if key in ("expected_revision", "id", "revision", "endpoint_actions"):
                continue
            merged[key] = copy.deepcopy(value)
        merged["id"] = identifier
        # `has_api_key` is never sent by the client: an omitted `auth.api_key` keeps the stored key,
        # a fresh value sets one. Recompute the response-only flag from what is stored plus any new key.
        incoming_key = str(((body.get("auth") or {}) if isinstance(body.get("auth"), dict) else {}).get("api_key") or "")
        stored_key = bool(prior.get("has_api_key")) if prior is not None else False
        merged["has_api_key"] = bool(incoming_key) or stored_key
        merged["_actions"] = tuple(prior.get("_actions", ENDPOINT_ACTIONS)) if prior is not None else tuple(ENDPOINT_ACTIONS)
        return merged

    def _stored_credential_error(self, body, prior):
        """Mirror the server's `_check_client_credentials`: refuse a Key Vault reference outright, and
        a masked placeholder only where nothing is stored. The editor omits a blank secret and never
        sends a reference or a placeholder, so any such value in an auth secret field is a UI
        regression -- recorded as unexpected -- and returns the server's exact 400 text."""
        auth = body.get("auth")
        if not isinstance(auth, dict):
            return None
        stored_auth = prior.get("auth") if isinstance(prior, dict) and isinstance(prior.get("auth"), dict) else {}
        for field in ENDPOINT_SECRET_FIELDS:
            value = auth.get(field)
            if not isinstance(value, str) or value == "":
                continue
            if ENDPOINT_KEYVAULT_REFERENCE_MARKER in value:
                self.unexpected_requests.append(f"endpoint write carried a Key Vault reference in auth.{field}")
                return ENDPOINT_STORED_CREDENTIAL_SUPPLIED
            if value in ENDPOINT_STORED_SECRET_PLACEHOLDERS and not stored_auth.get(field):
                self.unexpected_requests.append(
                    f"endpoint write carried a stored-secret placeholder in auth.{field} with nothing stored"
                )
                return ENDPOINT_STORED_CREDENTIAL_UNAVAILABLE
        return None

    def _model_endpoints(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/model-endpoints[/<endpoint_id>]
        group_id = parts[3]
        tail = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group endpoint scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's model endpoints."}, 403)
            return
        # Unlike identities, an ordinary member may read the list -- they simply receive an empty
        # `endpoint_management` hint and rows without `endpoint_actions`, so the section renders
        # read-only. Every native endpoint route rejects unexpected query parameters with a 400,
        # mirroring the server's strict request contract; the frontend therefore sends none.
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        operations = set(self.groups[group_id].get("endpoint_management", {}).get("operations", []))
        if tail is None:
            if method == "GET":
                # A test may force a malformed list envelope (no endpoints array) to prove the section
                # treats it as a hard load error rather than an empty successful load.
                if getattr(self, "malformed_endpoint_list", False):
                    self._json(route, {"endpoints": None})
                    return
                self._json(route, {
                    "endpoints": [
                        self._endpoint_payload(group_id, row) for row in self.native_endpoints.get(group_id, [])
                    ],
                    "multi_endpoint_enabled": True,
                    "custom_api_types": [],
                })
                return
            if method == "POST":
                self._create_endpoint(route, entry, group_id, operations)
                return
        else:
            record = self.record_endpoint(group_id, tail)
            if record is None:
                self._json(route, {"error": "Model endpoint not found in this group."}, 404)
                return
            if method == "GET":
                self._json(route, {"endpoint": self._endpoint_payload(group_id, record)})
                return
            if method == "PATCH":
                self._patch_endpoint(route, entry, group_id, tail, record, operations)
                return
            if method == "DELETE":
                self._delete_endpoint(route, entry, group_id, tail, record, operations)
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group model endpoint request."}, 500)

    def _create_endpoint(self, route, entry, group_id, operations):
        assert "create" in operations, f"Create reached a workspace without the hint: {entry}"
        body = entry.body if isinstance(entry.body, dict) else {}
        if "expected_revision" in body:
            self._json(route, {"error": "A new model endpoint carries no version marker."}, 400)
            return
        credential_error = self._stored_credential_error(body, prior=None)
        if credential_error:
            self._json(route, {"error": credential_error}, 400)
            return
        if self.next_endpoint_write_error:
            self._json(route, {"error": self.next_endpoint_write_error}, 400)
            self.next_endpoint_write_error = None
            return
        self.created_endpoint_counter += 1
        identifier = f"{group_id}-endpoint-created-{self.created_endpoint_counter}"
        record = self._endpoint_from_write(group_id, identifier, body, prior=None)
        self.native_endpoints.setdefault(group_id, []).insert(0, record)
        self.native_endpoint_revisions[(group_id, identifier)] = 1
        self._json(route, {"endpoint": self._endpoint_payload(group_id, record)}, 201)

    def _patch_endpoint(self, route, entry, group_id, identifier, record, operations):
        body = entry.body if isinstance(entry.body, dict) else {}
        enable_only = set(body) - {"expected_revision"} == {"enabled"}
        op = "enable" if enable_only else "edit"
        assert op in operations and op in (record.get("_actions") or ()), (
            f"{op} reached a read-only endpoint: {entry}"
        )
        if "expected_revision" not in body:
            self._json(route, {"error": "This model endpoint is missing its version marker."}, 400)
            return
        if set(body) - {"expected_revision"} == set():
            # A PATCH that carries only its version marker changes nothing; the server refuses it with
            # this exact text (§11 F3.5), which the editor surfaces verbatim.
            self._json(route, {"error": ENDPOINT_NO_CHANGE_ERROR}, 400)
            return
        credential_error = self._stored_credential_error(body, prior=record)
        if credential_error:
            self._json(route, {"error": credential_error}, 400)
            return
        if body["expected_revision"] != self._endpoint_revision(group_id, identifier):
            self._json(route, {"error": ENDPOINT_CONFLICT_ERROR, "error_code": "endpoint_conflict"}, 409)
            return
        if group_id in self.endpoint_write_conflicts:
            # A concurrent, unrelated write to the group document: the endpoint's own revision is still
            # valid, so the draft is kept and a plain retry (which clears the flag) succeeds.
            self.endpoint_write_conflicts.discard(group_id)
            self._json(route, {"error": GROUP_WRITE_CONFLICT_ERROR, "error_code": "group_write_conflict"}, 409)
            return
        if self.next_endpoint_write_error:
            self._json(route, {"error": self.next_endpoint_write_error}, 400)
            self.next_endpoint_write_error = None
            return
        updated = self._endpoint_from_write(group_id, identifier, body, prior=record)
        index = next(i for i, row in enumerate(self.native_endpoints[group_id]) if row["id"] == identifier)
        self.native_endpoints[group_id][index] = updated
        self.native_endpoint_revisions[(group_id, identifier)] += 1
        self._json(route, {"endpoint": self._endpoint_payload(group_id, updated)})

    def _delete_endpoint(self, route, entry, group_id, identifier, record, operations):
        assert "delete" in operations and "delete" in (record.get("_actions") or ()), (
            f"Delete reached a read-only endpoint: {entry}"
        )
        body = entry.body if isinstance(entry.body, dict) else {}
        if set(body) != {"expected_revision"}:
            self._json(route, {"error": "A model endpoint delete carries only its version marker."}, 400)
            return
        if body["expected_revision"] != self._endpoint_revision(group_id, identifier):
            self._json(route, {"error": ENDPOINT_CONFLICT_ERROR, "error_code": "endpoint_conflict"}, 409)
            return
        references = self.endpoint_references.get((group_id, identifier))
        if references:
            self._json(route, {
                "error": ENDPOINT_IN_USE_ERROR,
                "error_code": "endpoint_in_use",
                "references": copy.deepcopy(references),
            }, 409)
            return
        self.native_endpoints[group_id] = [
            row for row in self.native_endpoints[group_id] if row["id"] != identifier
        ]
        self._json(route, {"success": True})

    def _group_models(self, route, entry):
        # /api/groups/<group_id>/models/{fetch,test-model} -- the group-scoped discovery and single
        # deployment test, the counterpart to the admin /api/models/{fetch,test-model} the shared
        # editor calls in admin scope. A group page reaching the admin routes is a leak the trap
        # records; these group routes answer the same shapes so the shared editor renders identically.
        group_id = entry.path.split("/")[3]
        action = entry.path.rsplit("/", 1)[-1]
        assert group_id in self.groups, f"Unknown group models scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's models."}, 403)
            return
        assert entry.method == "POST", entry
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        if not isinstance(entry.body, dict):
            self._json(route, {"error": "A model discovery or test requires a JSON object body."}, 400)
            return
        if "test" not in self._endpoint_operations(group_id):
            # Discovery and model tests are writer-only on the server: it refuses a member, a
            # DocumentManager or a manager of a non-`active` group with a 403. After F1 and F2 the UI
            # never offers Discover models or Test chat to those callers, so a request here is a UI
            # regression -- record it as unexpected rather than answering it.
            self.unexpected_requests.append(
                f"{entry.method} {entry.path} (discovery or model test without the test operation)"
            )
            self._json(route, {"error": "You cannot test this group's models."}, 403)
            return
        if action == "fetch":
            self._json(route, {"models": [
                {"deploymentName": "discovered-chat", "modelName": "gpt-4o-mini", "id": "discovered-chat"},
            ]})
            return
        if action == "test-model":
            self._json(route, {"success": True})
            return
        self.unexpected_requests.append(f"{entry.method} {entry.path}")
        self._json(route, {"error": "Unexpected group models request."}, 500)

    def _group_foundry_discovery(self, route, entry):
        # POST /api/groups/<group_id>/models/foundry/agents -- the named-group Foundry discovery route
        # M5C re-enables for a group-scoped connection, replacing the M4C block. The path scopes the
        # group, so the body carries only `endpoint_id` (and an optional `resource_type`); a `scope`
        # field is the legacy global shape and never arrives here. The M4C hazard is inverted: group
        # Foundry discovery is answered through this route, not recorded as unexpected.
        group_id = entry.path.split("/")[3]
        assert group_id in self.groups, f"Unknown group Foundry scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's models."}, 403)
            return
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        if not isinstance(entry.body, dict):
            self._json(route, {"error": "A group Foundry discovery requires a JSON object body."}, 400)
            return
        if "test" not in self._endpoint_operations(group_id):
            # Foundry discovery is writer-only on the server too, so a non-writer or a non-`active`
            # group is refused with a 403. The group agent editor only offers discovery to a writer,
            # so a request here is a regression -- recorded as unexpected.
            self.unexpected_requests.append(
                f"POST {entry.path} (Foundry discovery without the test operation)"
            )
            self._json(route, {"error": "You cannot test this group's models."}, 403)
            return
        body = entry.body if isinstance(entry.body, dict) else {}
        if not body.get("endpoint_id"):
            self._json(route, {"error": "A group Foundry discovery requires an endpoint id."}, 400)
            return
        if "scope" in body:
            # The named-group route scopes the group by path; a `scope` field is the legacy global
            # shape leaking onto the group route.
            self.unexpected_requests.append(
                f"POST {entry.path} (legacy scope field on the named-group Foundry route)"
            )
            self._json(route, {"error": "The group Foundry route takes no scope field."}, 400)
            return
        self._json(route, {
            "agents": [{
                "id": "group-assistant", "name": "group-assistant",
                "display_name": "Group assistant", "description": "A discoverable group resource.",
            }],
            "responses_api_version": "2025-01-01",
        })

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
        # POST /api/models/foundry/agents -- the legacy active-group Foundry discovery route. A
        # group-scoped connection now discovers through the named-group route (`_group_foundry_discovery`),
        # so scope 'group' must never arrive here from a group page; one that does is a cross-scope
        # hazard and is recorded as unexpected. A global connection has no group dependency, so it is
        # answered like the personal path.
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
