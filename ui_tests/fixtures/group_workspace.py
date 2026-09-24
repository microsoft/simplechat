# group_workspace.py
"""
Closed HTTP fixtures for the real V2 group workspace shell.
Version: 0.261.160
Implemented in: 0.261.127
Members section in the group context (M7B): 0.261.155
File source credential identifiers modelled as `_prepare_auth_payload` stores them: 0.261.156
Group context held to the server's builder, field by field: 0.261.157

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
# The workspace operations in the server's order (GROUP_ENDPOINT_OPERATIONS), as the context sends them.
ENDPOINT_OPERATIONS = ("create", "edit", "delete", "enable", "test")
ENDPOINT_ACTIONS = ("edit", "enable", "delete", "test")
# The server's GROUP_ENDPOINT_WRITE_ROLES: only Owner and Admin may write. A DocumentManager reads
# the collection but never manages it, so it is deliberately excluded and left read-only.
ENDPOINT_MANAGE_ROLES = ("Owner", "Admin")

# The strict write body the native endpoint routes accept; `expected_revision` rides the PATCH.
ENDPOINT_CONFLICT_ERROR = "This model endpoint changed. Reload it before saving."
GROUP_WRITE_CONFLICT_ERROR = "The group changed while your request was being saved. Try again."
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


# The native group file source model, mirrored from the M5B backend so both the shell fixture and
# the dedicated file source fixture answer list, read, create, edit, sync, test, browse and delete
# identically. File source manager roles match identities -- Owner, Admin and DocumentManager -- and
# reads use the same roles, so an ordinary member cannot list file sources. `source_actions` is the
# read-only per-source projection (`edit`/`delete`/`sync`/`test`) the policy computes; the write body
# is the strict classic field set, plus `expected_config_revision` for the conditional PATCH and the
# DELETE. Secrets are a `password_stored`/`secret_stored` boolean pair and a `ui_trigger_word`
# placeholder, exactly as `sanitize_file_sync_source` returns them.
FILE_SOURCE_OPERATIONS = ("create", "edit", "delete", "sync", "test")
FILE_SOURCE_ITEM_ACTIONS = ("edit", "delete", "sync", "test")
FILE_SOURCE_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
FILE_SOURCE_TRIGGER_WORD = "Stored_In_KeyVault"

# The strict top-level fields the native file source write accepts; anything else is a 400.
FILE_SOURCE_WRITE_FIELDS = frozenset({
    "name", "source_type", "enabled", "recursive", "connection", "filters",
    "schedule", "remote_delete_policy", "identity_id", "credentials",
})

FILE_SOURCE_CONNECTION_KEYS = {
    "smb": ("unc_path",),
    "azure_files": ("account_url", "share_name", "directory_path"),
    "azure_blob": ("account_url", "container_name", "blob_prefix"),
}

# The auth methods each source type accepts for inline credentials, mirroring
# FILE_SYNC_IDENTITY_AUTH_TYPES_BY_SOURCE.
FILE_SOURCE_AUTH_TYPES = {
    "smb": ("username_password", "anonymous"),
    "azure_files": ("managed_identity", "client_secret", "connection_string"),
    "azure_blob": ("managed_identity", "client_secret", "connection_string"),
}

FILE_SOURCE_GENERIC_ERROR = "The file source details are not valid."
FILE_SOURCE_CONFLICT_ERROR = "This file source was modified. Reload and try again."
# A delete refused while a run is active: the delete-specific reviewed message.
FILE_SOURCE_BUSY_ERROR = "Wait for the running sync to finish, then delete the source."
# Sync now refusals are distinct from the delete refusal: one for an already-running sync and one
# for the concurrent-run limit, both shown verbatim as the real server returns them.
FILE_SOURCE_SYNC_BUSY_ERROR = "This source already has a queued or running sync."
FILE_SOURCE_SYNC_LIMIT_ERROR = "The File Sync concurrent run limit has been reached. Try again later."
# The reviewed statuses a file source read is allowed in; anything else denies the read with 403.
FILE_SOURCE_READ_STATUSES = ("active", "locked", "upload_disabled")


def file_source_management(role, status):
    """The file source management hint, computed from policy exactly like `identity_management`."""
    if role in FILE_SOURCE_MANAGER_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(FILE_SOURCE_OPERATIONS)}
    return {"schema_version": 1, "operations": []}


def group_file_source(group_id, identifier, name, *, source_type="smb", enabled=True,
                      recursive=True, connection=None, filters=None, identity_id="",
                      identity_name="", auth_type="username_password", secret_stored=True,
                      username="", domain="", client_identity="", tenant_id="",
                      managed_identity_client_id="", schedule_enabled=False,
                      interval_minutes=60, actions=FILE_SOURCE_ITEM_ACTIONS,
                      last_run_status="completed", last_run_at="2024-01-02T00:00:00+00:00"):
    """One group file source as the native projector returns it, before config_revision and masking.

    The stored credential is a boolean plus a placeholder, never a plaintext secret, so a blank
    secret on save keeps it and a fresh value replaces it. An identity binding stores the id and a
    display name the list row shows; inline auth stores the fields the sanitized credentials expose.
    A service principal keeps its client ID in `identity` and its tenant in `tenant_id`; a managed
    identity keeps its client ID in `managed_identity_client_id`, as `_prepare_auth_payload` stores them.
    """
    conn = dict(connection or {})
    for key in FILE_SOURCE_CONNECTION_KEYS.get(source_type, ()):  # ensure every key is present
        conn.setdefault(key, "")
    if source_type == "smb" and not conn.get("unc_path"):
        conn["unc_path"] = "\\\\files.example.test\\reports"
    resolved_filters = {
        "include_patterns": list((filters or {}).get("include_patterns", [])),
        "exclude_patterns": list((filters or {}).get("exclude_patterns", [])),
        "allowed_extensions": list((filters or {}).get("allowed_extensions", [])),
        "fixed_tags": list((filters or {}).get("fixed_tags", [])),
        "folder_tag_mode": (filters or {}).get("folder_tag_mode", "none"),
    }
    return {
        "id": identifier,
        "name": name,
        "source_type": source_type,
        "enabled": enabled,
        "recursive": recursive,
        "connection": conn,
        "filters": resolved_filters,
        "schedule": {
            "enabled": schedule_enabled,
            "interval_minutes": interval_minutes,
            "next_run_at": None,
        },
        "remote_delete_policy": "ignore",
        "identity_id": identity_id or "",
        "last_run_status": last_run_status,
        "last_run_at": last_run_at,
        "created_by": OWNER_ID,
        "updated_by": OWNER_ID,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-02T00:00:00+00:00",
        "source_actions": list(actions),
        "_auth_type": auth_type,
        "_username": username,
        "_domain": domain,
        "_client_identity": client_identity,
        "_tenant_id": tenant_id,
        "_mi_client_id": managed_identity_client_id,
        "_secret": bool(secret_stored),
        "_identity_name": identity_name,
        "_supported_source_types": [source_type],
    }


def _file_source_credentials(record):
    """The sanitized `credentials` block: no plaintext, a placeholder when a secret is stored."""
    auth_type = record["_auth_type"]
    uses_password = auth_type == "username_password"
    stored = bool(record["_secret"]) and auth_type not in ("anonymous", "managed_identity")
    placeholder = FILE_SOURCE_TRIGGER_WORD if stored else ""
    return {
        "auth_type": auth_type,
        "username": record.get("_username", ""),
        "domain": record.get("_domain", ""),
        "identity": record.get("_client_identity", ""),
        "tenant_id": record.get("_tenant_id", ""),
        "managed_identity_client_id": record.get("_mi_client_id", ""),
        "password_stored": stored and uses_password,
        "secret_stored": stored and not uses_password,
        "password": placeholder if uses_password else "",
        "secret": "" if uses_password else placeholder,
    }


def _sanitize_file_source(record):
    """Project a stored source to its sanitized response: drop `_*` keys and the actions projection,
    add `credentials` and the bound identity name. The native routes then add `config_revision` and
    `source_actions` in `_file_source_payload`.
    """
    result = {key: copy.deepcopy(value) for key, value in record.items()
              if not key.startswith("_") and key != "source_actions"}
    result["credentials"] = _file_source_credentials(record)
    if record.get("identity_id") and record.get("_identity_name"):
        result["identity_name"] = record["_identity_name"]
    return result


# --- The selected-group context (`GET /api/v2/workspaces/group/<group_id>`) -----------------------
# `group_context` mirrors `build_group_workspace_context` (functions_workspace_context.py) for the one
# deployment the fixtures model: Semantic Kernel with per-user kernels; group agents, plugins, custom
# endpoints, multiple model endpoints and workflows on; File Sync on for the group; governance allowing
# everything; the administrator's group downloads allowed and not turned off by the group; group
# retention off; no CreateGroups role requirement; metadata extraction off. Its keyword switches model
# the only variants a per-section fixture claims, each named for the server setting it stands for.
# functional_tests/test_group_context_fixture_parity.py holds every field the V2 client reads to the
# real builder, for every role and status, so a browser test that reads a value from here -- or one of
# the reason constants below -- reads the server's value rather than one the fixture invented.
GROUP_STATUSES = ("active", "locked", "upload_disabled", "inactive")
GROUP_VIEWABLE_STATUSES = ("active", "locked", "upload_disabled")
GROUP_CONTENT_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")

# The server's reasons, verbatim: a status that bars viewing (check_group_status_allows_operation, and
# the builder's own text for a status it does not recognize), a role that may not manage the group's
# connections, and a tenant capability that is switched off.
GROUP_INACTIVE_REASON = "This group is inactive. Access is restricted to administrators."
GROUP_STATUS_UNKNOWN_REASON = "This group's status is not recognized. Contact an administrator."
GROUP_CONNECTIONS_ROLE_REASON = "Your role does not permit managing this group's connections."
GROUP_AGENTS_DISABLED_REASON = "Group agents are not enabled."
GROUP_ACTIONS_DISABLED_REASON = "Group actions are not enabled."
GROUP_DELEGATION_GOVERNANCE_REASON = "Your administrator has restricted access to this capability."
GROUP_CONTEXT_NOT_FOUND_ERROR = "The selected group was not found."

# The hint vocabularies, in the server's order (functions_group_document_policy.py and
# functions_group_prompt_policy.py).
GROUP_DOCUMENT_OPERATIONS = (
    "upload", "edit_metadata", "tag_documents", "manage_tags",
    "delete", "download", "extract_metadata", "reprocess",
)
GROUP_DOCUMENT_COLLABORATION_OPERATIONS = (
    "inspect", "share", "unshare", "approve_share", "remove_share",
    "approve_artifact", "reject_artifact", "cancel_artifact",
)
GROUP_PROMPT_OPERATIONS = ("create", "edit", "delete")


def group_status_reason(status):
    """The reason every section carries when the group's status bars viewing it; None otherwise."""
    if status in GROUP_VIEWABLE_STATUSES:
        return None
    return GROUP_INACTIVE_REASON if status == "inactive" else GROUP_STATUS_UNKNOWN_REASON


def _ordered_hint(vocabulary, operations):
    return {"schema_version": 1, "operations": [operation for operation in vocabulary if operation in operations]}


def document_management(role, status, *, extract_metadata=False):
    """`group_document_management_operations`, with the group's downloads allowed."""
    operations = set()
    if role in GROUP_CONTENT_MANAGER_ROLES and status in GROUP_VIEWABLE_STATUSES:
        operations.add("download")
        if status == "active":
            operations.update({"upload", "edit_metadata", "tag_documents", "manage_tags"})
            if extract_metadata:
                operations.add("extract_metadata")
        if status in ("active", "upload_disabled"):
            operations.update({"delete", "reprocess"})
    return _ordered_hint(GROUP_DOCUMENT_OPERATIONS, operations)


def document_collaboration(role, status):
    """`group_document_collaboration_operations`: every member may inspect in a viewable group and
    cancel their own publication request where the group still takes changes; managers review shares
    and publications too, and approve a publication only in an active group."""
    operations = set()
    if role in (*GROUP_CONTENT_MANAGER_ROLES, "User") and status in GROUP_VIEWABLE_STATUSES:
        operations.add("inspect")
        if status in ("active", "upload_disabled"):
            operations.add("cancel_artifact")
            if role in GROUP_CONTENT_MANAGER_ROLES:
                operations.update({"share", "unshare", "approve_share", "remove_share", "reject_artifact"})
                if status == "active":
                    operations.add("approve_artifact")
    return _ordered_hint(GROUP_DOCUMENT_COLLABORATION_OPERATIONS, operations)


def prompt_management(role, status):
    """`group_prompt_management_operations`: a content manager in an active group. Always present."""
    active_manager = role in GROUP_CONTENT_MANAGER_ROLES and status == "active"
    return _ordered_hint(GROUP_PROMPT_OPERATIONS, GROUP_PROMPT_OPERATIONS if active_manager else ())


# --- settings_management: a self-contained port of functions_group_settings_policy.py ------------
# The operations in the server's order (GROUP_SETTINGS_OPERATIONS), and the settings the modelled
# deployment gives the policy: the administrator's group downloads allowed, group retention off, and
# no CreateGroups role requirement.
GROUP_SETTINGS_OPERATIONS = (
    "edit_name", "edit_description", "edit_color", "edit_logo", "edit_downloads",
    "edit_retention", "view_activity", "view_stats", "view_file_count",
)
GROUP_SETTINGS_READ_ONLY_STATUSES = ("locked", "inactive")
# As the server's GROUP_SETTINGS_WRITABLE_STATUSES (0.261.157): the only statuses in which the profile
# and logo can change. Any other value, including one the server doesn't recognize, is read-only.
GROUP_SETTINGS_WRITABLE_STATUSES = ("active", "upload_disabled")


def settings_management(role, status):
    """`build_group_settings_management` for the modelled deployment.

    The profile and logo need the owner, and an `active` or `upload_disabled` group; downloads,
    retention, activity and stats need the owner or an admin, and the file count the owner. Retention
    is off, so a manager is told so. Like the server's `group_settings_read_only`, any other status,
    including one the server does not recognize, makes the profile and logo read-only.
    """
    owner = role == "Owner"
    manager = role in ("Owner", "Admin")
    read_only = status not in GROUP_SETTINGS_WRITABLE_STATUSES
    profile = "group_owner_required" if not owner else "group_status_unavailable" if read_only else None
    decisions = {
        "edit_name": profile,
        "edit_description": profile,
        "edit_color": profile,
        "edit_logo": "group_owner_required" if not owner else "group_status_unavailable" if read_only else None,
        "edit_downloads": None if manager else "group_manager_required",
        "edit_retention": "group_retention_disabled" if manager else "group_manager_required",
        "view_activity": None if manager else "group_manager_required",
        "view_stats": None if manager else "group_manager_required",
        "view_file_count": None if owner else "group_owner_required",
    }
    return {
        "schema_version": 1,
        "operations": [operation for operation in GROUP_SETTINGS_OPERATIONS if decisions[operation] is None],
        "reasons": {
            operation: decisions[operation]
            for operation in GROUP_SETTINGS_OPERATIONS if decisions[operation] is not None
        },
    }
# --- end of settings_management --------------------------------------------------------------------


def group_context(identifier, name, *, role="Owner", status="active", viewer=OWNER_ID,
                  enable_extract_meta_data=False, allow_group_agents=True, allow_group_plugins=True):
    """The selected-group context the server builds, as a fresh copy on every call.

    `enable_extract_meta_data` turns metadata extraction on, as the document fixtures' deployment does.
    `allow_group_plugins=False` switches group actions off; the Call agent tools stay open but read-only,
    as managing them also needs group plugins. `allow_group_agents=False` switches group agents off, and
    with them group actions and the Call agent tools, which both need group agents on the server.
    """
    status = status if status in GROUP_STATUSES else "unknown"
    status_reason = group_status_reason(status)
    viewable = status_reason is None
    active = status == "active"
    manager = role in GROUP_CONTENT_MANAGER_ROLES
    automation = role in WRITER_ROLES
    actions_available = allow_group_agents and allow_group_plugins

    def section(group, enabled, can_manage, reason):
        available = viewable and enabled
        return {
            "group": group, "enabled": available,
            "can_manage": available and active and can_manage,
            "reason": None if available else status_reason or reason,
        }

    rules = {
        "documents": (True, manager, None),
        "tags": (True, manager, None),
        "prompts": (True, manager, None),
        "agents": (allow_group_agents, automation, GROUP_AGENTS_DISABLED_REASON),
        "actions": (actions_available, automation, GROUP_ACTIONS_DISABLED_REASON),
        "endpoints": (True, role in ENDPOINT_MANAGE_ROLES, None),
        "workflows": (True, automation, None),
        # Identities and Sync are content-manager surfaces; an ordinary member is told why.
        "identities": (manager, manager, GROUP_CONNECTIONS_ROLE_REASON),
        "sync": (manager, manager, GROUP_CONNECTIONS_ROLE_REASON),
    }
    sections = {key: section(SECTION_GROUPS[key], *rule) for key, rule in rules.items()}
    # M7B: Members is a group-only section in the "manage" group, open to every member of a
    # viewable group and managed by the Owner and Admins in an active one, as the context builds it.
    sections["members"] = section("manage", True, automation, None)
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
        "native_delegation": section(
            "automation", allow_group_agents, automation and allow_group_plugins,
            GROUP_DELEGATION_GOVERNANCE_REASON if allow_group_agents else GROUP_AGENTS_DISABLED_REASON,
        ),
        "document_permissions": {
            # Every viewable status allows chat, including `locked` (read-only: view and chat only).
            "can_view": viewable, "can_chat": viewable,
            "can_upload": manager and active, "can_edit": manager and active,
            "can_delete": manager and status in ("active", "upload_disabled"),
            "can_download": manager and viewable,
        },
        "document_queries": {
            "sort_fields": [
                "_ts", "file_name", "title", "upload_date", "file_size",
                "number_of_pages", "version", "document_classification",
            ],
            "facets": True, "places": True,
        },
        "document_management": document_management(role, status, extract_metadata=enable_extract_meta_data),
        "document_collaboration": document_collaboration(role, status),
        "prompt_management": prompt_management(role, status),
        # A switched-off capability sends an empty hint, as its availability predicate empties it.
        "action_management": (
            action_management(role, status) if actions_available else {"schema_version": 1, "operations": []}
        ),
        "agent_management": (
            agent_management(role, status) if allow_group_agents else {"schema_version": 1, "operations": []}
        ),
        "identity_management": identity_management(role, status),
        "endpoint_management": endpoint_management(role, status),
        "file_source_management": file_source_management(role, status),
        "settings_management": settings_management(role, status),
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
        self.deleted_identity_conflicts = set()
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
        self.deleted_endpoint_conflicts = set()
        # One test sets this to a reviewed 400 message so the next endpoint create or edit is refused
        # verbatim, proving the editor renders the server's own text and keeps the draft.
        self.next_endpoint_write_error = None
        # One test flips this to force a malformed endpoint list envelope (no endpoints array), which
        # the section must treat as a hard load error rather than an empty successful load.
        self.malformed_endpoint_list = False
        # Native group file source state. Sources carry a config_revision string rather than an etag,
        # so a per-(group, id) revision counter backs it and `touch_file_source` advances it to model
        # a concurrent edit. `file_source_active_runs` records a source mid-run so a delete or sync is
        # refused with `source_busy`, and `file_source_delete_plan` lets a test script a delete that
        # is refused after the associated documents were removed (partial / delete_incomplete).
        self.created_file_source_counter = 0
        self.native_file_sources = {}
        self.native_file_source_revisions = {}
        self.file_source_runs = {}
        self.deleted_file_source_conflicts = set()
        self.file_source_active_runs = set()
        self.file_source_delete_plan = {}
        # A test can script a connection-test failure (a message shown verbatim as an HTTP 400) and a
        # Sync now that is refused because the concurrent-run limit is reached.
        self.file_source_test_failure = None
        self.file_source_sync_limit_reached = set()
        # A test can force the next PATCH or DELETE conditional write to conflict (write_conflict for
        # a bare etag race with an unchanged revision, or config_conflict for a moved revision), and
        # drop a required field from every served list row to prove the strict envelope.
        self.file_source_forced_write_conflict = None
        self.file_source_list_item_defect = None
        self.file_source_type_visibility = {"smb": True, "azure_files": True, "azure_blob": True}
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
            # One native file source per group so the production Sync (File sources) page renders a
            # real collection. It carries a bound file-sync identity so the list row shows the
            # identity name, and stays enabled with a completed run so the row and its history render.
            self._seed_file_sources(group_id, [
                group_file_source(group_id, f"{group_id}-share", "Group reports share",
                                  source_type="smb", auth_type="username_password",
                                  username="svc-reports", domain="CORP"),
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
        if path.startswith("/api/groups/") and path.endswith("/file-source-options"):
            self._file_source_options(route, entry)
            return
        if path.startswith("/api/groups/") and "/file-sources" in path:
            self._file_sources(route, entry)
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
                self._json(route, {"error": GROUP_CONTEXT_NOT_FOUND_ERROR}, 404)
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
            run_as_group = entry.query.get("group_id", [None])[0]
            assert run_as_group in self.groups
            if self.groups[run_as_group]["role"] not in ("Owner", "Admin"):
                # M6C: the route refuses non-managers, and a read-only workflow editor never asks.
                self.unexpected_requests.append(f"{entry.method} {entry.path} (a group member cannot list run-as accounts)")
                self._json(route, {"error": "You cannot configure this group workflow."}, 403)
            else:
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
            elif path == "/api/group/workflows/file-sync-sources" and method == "GET":
                self._workflow_file_sync_sources(route, entry, group_id)
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

    def drop_identity_for_conflict(self, group_id, identifier):
        """Remove an identity while making the next stale save look like an etag conflict."""
        self.native_identities[group_id] = [
            row for row in self.native_identities[group_id] if row["id"] != identifier
        ]
        self.deleted_identity_conflicts.add((group_id, identifier))

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
                if method == "PATCH" and (group_id, tail) in self.deleted_identity_conflicts:
                    self._json(route, {
                        "error": IDENTITY_CONFLICT_ERROR,
                        "error_code": "etag_conflict",
                    }, 409)
                    return
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

    def drop_endpoint_for_conflict(self, group_id, identifier):
        """Remove an endpoint while making the next stale save look like a revision conflict."""
        self.native_endpoints[group_id] = [
            row for row in self.native_endpoints[group_id] if row["id"] != identifier
        ]
        self.deleted_endpoint_conflicts.add((group_id, identifier))

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
                if method == "PATCH" and (group_id, tail) in self.deleted_endpoint_conflicts:
                    self._json(route, {
                        "error": ENDPOINT_CONFLICT_ERROR,
                        "error_code": "endpoint_conflict",
                    }, 409)
                    return
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

    # --- Native group file source serving, shared with GroupFileSourcesFixture ------------------

    def _file_source_run(self, group_id, record, *, run_index, status, started_at, completed_at,
                         trigger="manual"):
        """One run as the engine's `_create_run` returns it: id, run_id, type, the scope, the trigger
        and a full `counts` block, so the run shape the section reads matches the real server."""
        identifier = record["id"]
        completed = status in ("completed", "failed", "cancelled")
        counts = {
            "scanned": 12 if completed else 0,
            "queued": 4 if completed else 0,
            "created": 3 if completed else 0,
            "updated": 1 if completed else 0,
            "unchanged": 7 if completed else 0,
            "skipped": 1 if completed else 0,
            "deleted": 0,
            "failed": 0,
            "bytes_queued": 204800 if completed else 0,
        }
        return {
            "id": f"{identifier}-run-{run_index}",
            "run_id": f"{identifier}-run-{run_index}",
            "type": "file_sync_run",
            "source_id": identifier,
            "source_name": record.get("name", ""),
            "scope_type": "group",
            "trigger": trigger,
            "triggered_by": OWNER_ID,
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "counts": counts,
            "changed_documents": [],
        }

    def _seed_file_sources(self, group_id, records):
        rows = []
        for record in records:
            rows.append(record)
            self.native_file_source_revisions[(group_id, record["id"])] = 1
            self.file_source_runs.setdefault((group_id, record["id"]), [self._file_source_run(
                group_id, record, run_index=1,
                status=record.get("last_run_status", "completed"),
                started_at="2024-01-02T00:00:00+00:00",
                completed_at="2024-01-02T00:05:00+00:00",
            )])
        self.native_file_sources[group_id] = rows

    def record_file_source(self, group_id, identifier):
        return next((row for row in self.native_file_sources.get(group_id, []) if row["id"] == identifier), None)

    def _file_source_config_revision(self, group_id, identifier):
        return f"group-source-rev:{group_id}:{identifier}:{self.native_file_source_revisions[(group_id, identifier)]}"

    def touch_file_source(self, group_id, identifier):
        """Simulate a concurrent edit by another manager: the stored config_revision moves on."""
        self.native_file_source_revisions[(group_id, identifier)] += 1
        return self._file_source_config_revision(group_id, identifier)

    def drop_file_source_for_conflict(self, group_id, identifier):
        """Remove a file source while making the next stale save look like a config conflict."""
        self.native_file_sources[group_id] = [
            row for row in self.native_file_sources[group_id] if row["id"] != identifier
        ]
        self.deleted_file_source_conflicts.add((group_id, identifier))

    def mark_file_source_running(self, group_id, identifier, running=True):
        """Model a run in flight so a sync or delete is refused with `source_busy`."""
        key = (group_id, identifier)
        if running:
            self.file_source_active_runs.add(key)
        else:
            self.file_source_active_runs.discard(key)

    def _file_source_operations(self, group_id):
        """The management operations the group's current context advertises, from the same policy the
        list envelope and workspace context carry."""
        return set(self.groups.get(group_id, {}).get("file_source_management", {}).get("operations", []))

    def _file_source_actions(self, group_id, record):
        """The per-row `source_actions`, computed exactly as the real projector does: the group's
        advertised management operations intersected with the item-level operation set, then with the
        row's own seeded override. A withheld row (empty override) keeps none; a locked or member
        workspace advertises none, so every row loses its actions."""
        operations = self._file_source_operations(group_id)
        override = set(record.get("source_actions", FILE_SOURCE_ITEM_ACTIONS))
        return [op for op in FILE_SOURCE_ITEM_ACTIONS if op in operations and op in override]

    def _file_source_payload(self, group_id, record):
        """The sanitized source plus the two fields the native routes add: `config_revision` and the
        `source_actions` projection."""
        payload = _sanitize_file_source(record)
        payload["config_revision"] = self._file_source_config_revision(group_id, record["id"])
        payload["source_actions"] = self._file_source_actions(group_id, record)
        return payload

    def set_file_source_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context for a file source role and status.

        `group_context` computes the `file_source_management` hint from the same role and status, so
        recomputing the whole context carries the new hint, exactly like `set_identity_policy`.
        """
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        self.groups[group_id] = context
        return context

    def _file_source_eligible_identity_ids(self, group_id):
        """Per-source-type identity eligibility, mirroring save-time validation: an identity is
        offered for a source type when it carries `file_sync` usage and supports that source type
        (or the wildcard `generic`)."""
        eligible = {source_type: [] for source_type in FILE_SOURCE_CONNECTION_KEYS}
        for row in self.native_identities.get(group_id, []):
            usage = row.get("usage_contexts", [])
            if "file_sync" not in usage:
                continue
            supported = row.get("supported_source_types", [])
            for source_type in eligible:
                if source_type in supported or "generic" in supported:
                    eligible[source_type].append(row["id"])
        return eligible

    def _file_source_options_payload(self, group_id):
        labels = {"smb": "Network share", "azure_files": "Azure Files", "azure_blob": "Azure Blob Storage"}
        return {
            "source_types": [
                {"value": source_type, "label": labels[source_type],
                 "visible": bool(self.file_source_type_visibility.get(source_type, True))}
                for source_type in ("smb", "azure_files", "azure_blob")
            ],
            "eligible_identity_ids": self._file_source_eligible_identity_ids(group_id),
            "schedule": {"min_interval_minutes": 5, "max_interval_minutes": 10080},
            "limits": {"max_sources": 25},
            "recursive_allowed": True,
        }

    def _file_source_guard(self, route, entry, group_id):
        """The shared access guard for every file source route: unknown group, member 403, and the
        strict no-query-parameters contract. Returns True when the request may proceed."""
        if group_id not in self.groups:
            self._json(route, {"error": "Group not found."}, 404)
            return False
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's file sources."}, 403)
            return False
        if self.groups[group_id].get("role") not in FILE_SOURCE_MANAGER_ROLES:
            self._json(route, {"error": "You do not have access to this group's file sources."}, 403)
            return False
        if self.groups[group_id].get("status") not in FILE_SOURCE_READ_STATUSES:
            # Reads are refused outside the reviewed statuses, exactly as the read context is. A
            # locked or upload-disabled workspace stays readable but, being inactive, advertises no
            # management operations, so its rows carry no actions.
            self._json(route, {"error": "This group's file sources are not available right now."}, 403)
            return False
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return False
        return True

    def _file_source_options(self, route, entry):
        parts = entry.path.split("/")
        group_id = parts[3]
        assert group_id in self.groups, f"Unknown group file source scope: {entry}"
        if not self._file_source_guard(route, entry, group_id):
            return
        self._json(route, self._file_source_options_payload(group_id))

    def _file_source_from_write(self, group_id, identifier, body, prior):
        """Fold a strict write body onto a new or existing source. A blank secret (or the
        round-tripped placeholder) keeps whatever is stored; a fresh value replaces it. Identity mode
        binds the identity and clears inline auth; inline mode stores the auth fields."""
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        identity_id = str(body.get("identity_id") or "")
        source_type = str(body.get("source_type") or (prior["source_type"] if prior else "smb"))
        auth_type = str(credentials.get("auth_type") or (prior["_auth_type"] if prior else "username_password"))
        uses_password = auth_type == "username_password"
        incoming = str((credentials.get("password") if uses_password else credentials.get("secret")) or "")
        if identity_id:
            secret_stored = False
        elif incoming and incoming != FILE_SOURCE_TRIGGER_WORD:
            secret_stored = True
        elif prior is not None:
            secret_stored = bool(prior["_secret"])
        else:
            secret_stored = False
        connection = body.get("connection")
        filters = body.get("filters")
        schedule = body.get("schedule") if isinstance(body.get("schedule"), dict) else {}
        identity_name = ""
        if identity_id:
            match = self.record_identity(group_id, identity_id)
            identity_name = match["name"] if match else identity_id
        # The identifiers `_prepare_auth_payload` stores for each inline auth method. A key the body
        # carries wins even when empty, which is how a value is cleared; a missing key keeps the
        # stored one.
        client_identity = tenant_id = managed_identity_client_id = ""
        if not identity_id and auth_type == "client_secret":
            client_identity = str(credentials.get(
                "client_id", credentials.get("identity", prior["_client_identity"] if prior else ""),
            ) or "")
            tenant_id = str(credentials.get("tenant_id", prior.get("_tenant_id", "") if prior else "") or "")
        elif not identity_id and auth_type == "managed_identity":
            managed_identity_client_id = str(credentials.get(
                "managed_identity_client_id",
                credentials.get("client_id", prior.get("_mi_client_id", "") if prior else ""),
            ) or "")
        now = datetime.now(timezone.utc).isoformat()
        record = group_file_source(
            group_id, identifier,
            str(body["name"]) if "name" in body else (prior["name"] if prior else ""),
            source_type=source_type,
            enabled=bool(body["enabled"]) if "enabled" in body else (prior["enabled"] if prior else True),
            recursive=bool(body["recursive"]) if "recursive" in body else (prior["recursive"] if prior else True),
            connection=connection if isinstance(connection, dict) else (prior["connection"] if prior else None),
            filters=filters if isinstance(filters, dict) else (prior["filters"] if prior else None),
            identity_id=identity_id,
            identity_name=identity_name,
            auth_type=auth_type,
            secret_stored=secret_stored,
            username=str(credentials.get("username", prior["_username"] if prior else "")),
            domain=str(credentials.get("domain", prior["_domain"] if prior else "")),
            client_identity=client_identity,
            tenant_id=tenant_id,
            managed_identity_client_id=managed_identity_client_id,
            schedule_enabled=bool(schedule.get("enabled")) if schedule else (prior["schedule"]["enabled"] if prior else False),
            interval_minutes=int(schedule.get("interval_minutes") or (prior["schedule"]["interval_minutes"] if prior else 60)),
            actions=list(prior["source_actions"]) if prior else list(FILE_SOURCE_ITEM_ACTIONS),
            last_run_status=prior["last_run_status"] if prior else None,
            last_run_at=prior["last_run_at"] if prior else None,
        )
        record["created_at"] = prior["created_at"] if prior else now
        record["updated_at"] = now
        return record

    def _file_sources(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/file-sources[/<source_id>[/<suffix>]]
        group_id = parts[3]
        source_id = parts[5] if len(parts) > 5 else None
        suffix = parts[6] if len(parts) > 6 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group file source scope: {entry}"
        # test-connection and browse on the collection carry a body, not a query, so the guard's
        # no-query rule holds for them too.
        if not self._file_source_guard(route, entry, group_id):
            return
        operations = set(self.groups[group_id].get("file_source_management", {}).get("operations", []))
        if source_id is None:
            if method == "GET":
                # A test may force a malformed list envelope (no file_sources array) to prove the
                # section treats it as a hard load error rather than an empty successful load.
                if getattr(self, "malformed_file_source_list", False):
                    self._json(route, {"file_sources": None})
                    return
                rows = [
                    self._file_source_payload(group_id, row)
                    for row in self.native_file_sources.get(group_id, [])
                ]
                # A test may drop a required per-item field (config_revision or source_actions) to
                # prove the strict envelope treats it as a hard load error, not a usable row.
                if self.file_source_list_item_defect:
                    for payload in rows:
                        payload.pop(self.file_source_list_item_defect, None)
                self._json(route, {
                    "file_sources": rows,
                    "file_source_management": {
                        "schema_version": 1,
                        "operations": list(operations),
                    },
                })
                return
            if method == "POST":
                assert "create" in operations, f"Create reached a workspace without the hint: {entry}"
                self._create_file_source(route, entry, group_id)
                return
        if source_id in ("test-connection", "browse"):
            self._file_source_unsaved(route, entry, group_id, source_id)
            return
        record = self.record_file_source(group_id, source_id) if source_id else None
        if source_id is not None and record is None:
            if method == "PATCH" and (group_id, source_id) in self.deleted_file_source_conflicts:
                self._json(route, {
                    "error": FILE_SOURCE_CONFLICT_ERROR,
                    "error_code": "config_conflict",
                }, 409)
                return
            self._json(route, {"error": "File source not found in this group."}, 404)
            return
        if suffix is None:
            if method == "GET":
                self._json(route, {"file_source": self._file_source_payload(group_id, record)})
                return
            if method == "PATCH":
                self._patch_file_source(route, entry, group_id, source_id, record, operations)
                return
            if method == "DELETE":
                self._delete_file_source(route, entry, group_id, source_id, record, operations)
                return
        elif suffix == "runs" and method == "GET":
            self._json(route, {"runs": copy.deepcopy(self.file_source_runs.get((group_id, source_id), []))})
            return
        elif suffix == "sync" and method == "POST":
            self._file_source_sync(route, entry, group_id, source_id, record, operations)
            return
        elif suffix in ("test-connection", "browse") and method == "POST":
            self._file_source_saved_tool(route, entry, group_id, source_id, suffix)
            return
        elif suffix == "ignore-path" and method == "POST":
            self._file_source_ignore(route, entry, group_id, source_id)
            return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group file source request."}, 500)

    def _create_file_source(self, route, entry, group_id):
        body = entry.body
        if not isinstance(body, dict) or set(body) - FILE_SOURCE_WRITE_FIELDS:
            self._json(route, {"error": FILE_SOURCE_GENERIC_ERROR}, 400)
            return
        if not str(body.get("name") or "").strip():
            self._json(route, {"error": "A file source needs a name."}, 400)
            return
        self.created_file_source_counter += 1
        identifier = f"group-source-created-{self.created_file_source_counter}"
        record = self._file_source_from_write(group_id, identifier, body, prior=None)
        self.native_file_sources.setdefault(group_id, []).insert(0, record)
        self.native_file_source_revisions[(group_id, identifier)] = 1
        self.file_source_runs[(group_id, identifier)] = []
        self._json(route, {"file_source": self._file_source_payload(group_id, record)}, 201)

    def _patch_file_source(self, route, entry, group_id, identifier, record, operations):
        assert "edit" in operations and "edit" in (record.get("source_actions") or []), (
            f"Edit reached a read-only file source: {entry}"
        )
        body = entry.body
        if not isinstance(body, dict) or "expected_config_revision" not in body:
            self._json(route, {"error": "This file source is missing its version marker."}, 400)
            return
        if set(body) - FILE_SOURCE_WRITE_FIELDS - {"expected_config_revision"}:
            self._json(route, {"error": FILE_SOURCE_GENERIC_ERROR}, 400)
            return
        # A test may force the conditional write to conflict. `write_conflict` models a bare etag
        # race whose config revision is unchanged (a plain retry is safe); `config_conflict` models a
        # revision that moved (the draft must be reloaded).
        forced = self.file_source_forced_write_conflict
        if forced:
            self.file_source_forced_write_conflict = None
            self._json(route, {"error": FILE_SOURCE_CONFLICT_ERROR, "error_code": forced}, 409)
            return
        if body["expected_config_revision"] != self._file_source_config_revision(group_id, identifier):
            self._json(route, {"error": FILE_SOURCE_CONFLICT_ERROR, "error_code": "config_conflict"}, 409)
            return
        updated = self._file_source_from_write(group_id, identifier, body, prior=record)
        index = next(i for i, row in enumerate(self.native_file_sources[group_id]) if row["id"] == identifier)
        self.native_file_sources[group_id][index] = updated
        self.native_file_source_revisions[(group_id, identifier)] += 1
        self._json(route, {"file_source": self._file_source_payload(group_id, updated)})

    def _delete_file_source(self, route, entry, group_id, identifier, record, operations):
        assert "delete" in operations and "delete" in (record.get("source_actions") or []), (
            f"Delete reached a read-only file source: {entry}"
        )
        body = entry.body
        if not isinstance(body, dict) or set(body) != {"expected_config_revision", "delete_associated_files"}:
            self._json(route, {
                "error": "A file source delete carries its version marker and the documents choice.",
            }, 400)
            return
        if body["expected_config_revision"] != self._file_source_config_revision(group_id, identifier):
            self._json(route, {"error": FILE_SOURCE_CONFLICT_ERROR, "error_code": "config_conflict"}, 409)
            return
        if (group_id, identifier) in self.file_source_active_runs:
            self._json(route, {"error": FILE_SOURCE_BUSY_ERROR, "error_code": "source_busy"}, 409)
            return
        delete_associated = bool(body["delete_associated_files"])
        plan = self.file_source_delete_plan.get((group_id, identifier))
        if plan is not None:
            # A scripted refusal after the associated documents were removed: partial / incomplete.
            self._json(route, plan["payload"], plan["status"])
            return
        result = {
            "associated_files_requested": delete_associated,
            "documents_deleted": 3 if delete_associated else 0,
            "documents_skipped": 1 if delete_associated else 0,
            "documents_failed": 0,
        }
        self.native_file_sources[group_id] = [
            row for row in self.native_file_sources[group_id] if row["id"] != identifier
        ]
        self._json(route, {"success": True, "delete_result": result})

    def _file_source_sync(self, route, entry, group_id, identifier, record, operations):
        assert "sync" in operations and "sync" in (record.get("source_actions") or []), (
            f"Sync reached a source without the action: {entry}"
        )
        if (group_id, identifier) in self.file_source_active_runs:
            # The reviewed "already queued or running" Sync now refusal, shown verbatim (400).
            self._json(route, {"error": FILE_SOURCE_SYNC_BUSY_ERROR}, 400)
            return
        if (group_id, identifier) in self.file_source_sync_limit_reached:
            # The reviewed concurrent-run-limit refusal, also shown verbatim (400).
            self._json(route, {"error": FILE_SOURCE_SYNC_LIMIT_ERROR}, 400)
            return
        run = self._file_source_run(
            group_id, record,
            run_index=len(self.file_source_runs.get((group_id, identifier), [])) + 1,
            status="queued",
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=None,
        )
        self.file_source_runs.setdefault((group_id, identifier), []).insert(0, run)
        self._json(route, {"run": run}, 202)

    def _file_source_unsaved(self, route, entry, group_id, action):
        # /api/groups/<group_id>/file-sources/{test-connection|browse}
        # Both draft tools require the workspace-level `test` operation; a request that arrives
        # without it means the section leaked past its gate, so it is recorded and refused.
        if "test" not in self._file_source_operations(group_id):
            self.unexpected_requests.append(f"{entry.method} {entry.path}")
            self._json(route, {"error": "Testing a file source is not available in this group."}, 403)
            return
        body = entry.body if isinstance(entry.body, dict) else {}
        extra = set(body) - FILE_SOURCE_WRITE_FIELDS - {"browse_path"}
        if extra:
            self._json(route, {"error": FILE_SOURCE_GENERIC_ERROR}, 400)
            return
        if action == "test-connection":
            self._file_source_test_response(route, body)
        else:
            self._json(route, self._browse_payload(body.get("browse_path", "")))

    def _file_source_test_response(self, route, body):
        """A connection test result. A scripted failure is an HTTP 400 with a message shown verbatim,
        exactly as `test_file_sync_source_connection` raises; otherwise the real success shape with
        the counts the server saw, under `connection`."""
        if self.file_source_test_failure is not None:
            self._json(route, {"error": self.file_source_test_failure}, 400)
            return
        source_type = str(body.get("source_type") or "smb")
        recursive = bool(body.get("recursive", True))
        self._json(route, {"connection": {
            "success": True,
            "source_type": source_type,
            "recursive": recursive,
            "entries_checked": 12,
            "files_seen": 9,
            "folders_seen": 3,
        }})

    def _file_source_saved_tool(self, route, entry, group_id, identifier, action):
        # A saved source's test/browse require the workspace `test` operation and the row's own
        # `test` action; a request without either means the section leaked past its gate.
        record = self.record_file_source(group_id, identifier)
        actions = self._file_source_actions(group_id, record) if record else []
        if "test" not in self._file_source_operations(group_id) or "test" not in actions:
            self.unexpected_requests.append(f"{entry.method} {entry.path}")
            self._json(route, {"error": "Testing this file source is not available."}, 403)
            return
        body = entry.body if isinstance(entry.body, dict) else {}
        if action == "test-connection":
            self._file_source_test_response(route, body)
        else:
            self._json(route, self._browse_payload(body.get("browse_path", "")))

    def _browse_payload(self, browse_path):
        """A browse result in the real engine shape: each entry carries `type` ("folder" or "file"),
        never `is_dir`, and no ignore state, since browse cannot report one."""
        base = str(browse_path or "")
        prefix = f"{base}/" if base else ""
        return {"browse": {"path": base, "source_type": "smb", "entries": [
            {"name": "reports", "path": f"{prefix}reports", "type": "folder", "size": 0,
             "modified_at": "2024-01-02T00:00:00+00:00"},
            {"name": "budget.xlsx", "path": f"{prefix}budget.xlsx", "type": "file", "size": 20480,
             "modified_at": "2024-01-02T00:00:00+00:00"},
        ]}}

    def _file_source_ignore(self, route, entry, group_id, identifier):
        # Ignore requires the workspace `edit` operation and the row's own `edit` action.
        record = self.record_file_source(group_id, identifier)
        actions = self._file_source_actions(group_id, record) if record else []
        if "edit" not in self._file_source_operations(group_id) or "edit" not in actions:
            self.unexpected_requests.append(f"{entry.method} {entry.path}")
            self._json(route, {"error": "Editing this file source is not available."}, 403)
            return
        body = entry.body if isinstance(entry.body, dict) else {}
        remote_path = str(body.get("remote_path") or "")
        ignored = bool(body.get("ignored"))
        # The File Sync item record the ignore route returns under `item`, whose `ignored` flag is the
        # authoritative per-path state the editor tracks.
        self._json(route, {"item": {
            "id": f"{identifier}-item-{abs(hash(remote_path)) % 10000}",
            "type": "file_sync_item",
            "source_id": identifier,
            "scope_type": "group",
            "group_id": group_id,
            "remote_path": remote_path,
            "status": "active",
            "ignored": ignored,
            "updated_by": OWNER_ID,
            "updated_at": "2024-01-02T00:00:00+00:00",
            "created_at": "2024-01-01T00:00:00+00:00",
        }})

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

    def _workflow_file_sync_sources(self, route, entry, group_id):
        """M6: the group workflow File Sync source list, which the real route refuses to non-managers.

        The group editor asks only as a manager, so a member request is also recorded as unexpected.
        Sources default to none; a suite may set `workflow_file_sync_sources[group_id]`. Since M6C the
        list carries `file_sync_enabled`, on unless a suite sets `workflow_file_sync_enabled[group_id]`.
        """
        if self.groups[group_id]["role"] not in ("Owner", "Admin", "DocumentManager"):
            self.unexpected_requests.append(f"{entry.method} {entry.path} (a group member cannot list File Sync sources)")
            self._json(route, {"error": "Insufficient permissions for this group"}, 403)
            return
        enabled = getattr(self, "workflow_file_sync_enabled", {}).get(group_id, True)
        sources = getattr(self, "workflow_file_sync_sources", {}).get(group_id, []) if enabled else []
        self._json(route, {"sources": copy.deepcopy(sources), "file_sync_enabled": enabled})


@pytest.fixture
def group_ui(page):
    fixture = GroupWorkspaceFixture(page)
    yield fixture
    fixture.assert_clean()
