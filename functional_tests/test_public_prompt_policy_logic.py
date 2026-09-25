# test_public_prompt_policy_logic.py
"""Logic pins for the public-workspace prompt policy and access layer (M9C commit 1).

Version: 0.261.178
Implemented in: 0.261.178

The two new modules are executed unchanged from their source with
``run_definitions``: the policy module has no imports, and the access module's
external names (workspace lookup, role predicate, settings, description
normalization) are supplied as local seams. No ``functions_*`` module is
imported, so ``config`` and ``CosmosClient`` are never reached.

What is pinned:

- an explicit readable-status allowlist, so an unrecognized status is denied,
  never treated as ``active`` (the public status helper this deliberately avoids
  fails open);
- management operations gated on a manager role, the ``enable_public_workspaces``
  flag and an ``active`` status;
- the per-prompt action hint computed from policy, so it can never be a stored
  constant that silently gates every edit and delete off;
- the projector strips the private field set and every Cosmos internal, keeps
  ``public_id`` as the scope-proof field, and surfaces the ETag under ``etag``;
- the create and update validators reject a smuggled ``is_favorite`` and any
  unknown field, and an update refuses a missing ``expected_etag``.
"""

import re
import sys
from pathlib import Path

import pytest
from werkzeug.exceptions import HTTPException

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_source import run_definitions


POLICY_NAMES = {
    "PUBLIC_PROMPT_MANAGER_ROLES",
    "PUBLIC_PROMPT_READER_ROLES",
    "PUBLIC_PROMPT_READ_STATUSES",
    "PUBLIC_PROMPT_OPERATIONS",
    "PUBLIC_PROMPT_ITEM_OPERATIONS",
    "public_prompt_management_operations",
    "public_prompt_actions",
}

ACCESS_NAMES = {
    "PUBLIC_PROMPT_TYPE",
    "PUBLIC_PROMPT_CREATE_FIELDS",
    "PUBLIC_PROMPT_UPDATE_FIELDS",
    "PRIVATE_PUBLIC_PROMPT_FIELDS",
    "INVALID_PUBLIC_PROMPT_ID",
    "PublicPromptError",
    "_validate_identifier",
    "require_public_prompt_read_context",
    "require_public_prompt_write_context",
    "_project_public_prompt",
    "validate_public_prompt_create",
    "validate_public_prompt_update",
}


def _build_namespace(*, workspaces, roles, settings):
    """A namespace with the real policy defs and local seams for the access defs."""

    def find_public_workspace_by_id(workspace_id):
        return workspaces.get(workspace_id)

    def get_user_role_in_public_workspace(workspace, user_id):
        return roles.get((workspace.get("id"), user_id))

    namespace = {
        "re": re,
        "HTTPException": HTTPException,
        "get_settings": lambda: dict(settings),
        "normalize_prompt_description": lambda value: value if isinstance(value, str) else "",
        "find_public_workspace_by_id": find_public_workspace_by_id,
        "get_user_role_in_public_workspace": get_user_role_in_public_workspace,
    }
    run_definitions("functions_public_prompt_policy.py", POLICY_NAMES, namespace)
    run_definitions("functions_public_prompt_access.py", ACCESS_NAMES, namespace)
    return namespace


def _namespace(status="active", settings=None, role="DocumentManager"):
    workspace = {"id": "public-a", "name": "Public A", "status": status}
    return _build_namespace(
        workspaces={"public-a": workspace},
        roles={("public-a", "user-1"): role},
        settings=settings if settings is not None else {"enable_public_workspaces": True},
    )


def test_read_statuses_are_an_explicit_allowlist():
    namespace = _namespace()
    assert namespace["PUBLIC_PROMPT_READ_STATUSES"] == frozenset({"active", "locked", "upload_disabled"})


def test_management_operations_require_manager_active_and_flag():
    namespace = _namespace()
    operations = namespace["public_prompt_management_operations"]
    workspace = {"id": "public-a", "status": "active"}
    enabled = {"enable_public_workspaces": True}

    assert operations(workspace, "DocumentManager", enabled) == ["create", "edit", "delete"]
    assert operations(workspace, "Admin", enabled) == ["create", "edit", "delete"]
    assert operations(workspace, "Owner", enabled) == ["create", "edit", "delete"]
    assert operations(workspace, "User", enabled) == []
    assert operations(workspace, "DocumentManager", {"enable_public_workspaces": False}) == []
    assert operations({"id": "public-a", "status": "locked"}, "Owner", enabled) == []
    assert operations({"id": "public-a", "status": "mystery"}, "Owner", enabled) == []


def test_prompt_actions_are_the_item_subset():
    namespace = _namespace()
    actions = namespace["public_prompt_actions"]
    enabled = {"enable_public_workspaces": True}
    active = {"id": "public-a", "status": "active"}

    assert actions({}, active, "Admin", enabled) == ["edit", "delete"]
    assert actions({}, active, "User", enabled) == []
    assert actions({}, {"id": "public-a", "status": "locked"}, "Owner", enabled) == []


def test_projector_strips_private_fields_and_keeps_public_id():
    namespace = _namespace()
    stored = {
        "id": "prompt-1",
        "public_id": "public-a",
        "name": "Greeting",
        "content": "Hello",
        "description": "A greeting",
        "type": "public_prompt",
        "is_favorite": True,
        "prompt_actions": ["stored-and-stale"],
        "user_id": "someone",
        "group_id": "group-x",
        "_etag": "etag-42",
        "_rid": "rid",
        "_self": "self",
        "_ts": 1730000000,
    }
    projected = namespace["_project_public_prompt"](
        stored, workspace={"id": "public-a", "status": "active"}, role="Admin",
        settings={"enable_public_workspaces": True},
    )

    assert projected["public_id"] == "public-a"
    assert projected["etag"] == "etag-42"
    assert projected["name"] == "Greeting"
    assert projected["prompt_actions"] == ["edit", "delete"]
    for stripped in ("is_favorite", "user_id", "group_id", "_etag", "_rid", "_self", "_ts"):
        assert stripped not in projected


def test_projector_action_hint_follows_role_and_status():
    """The hint is computed, not the stored value: a reader and a locked status empty it."""
    namespace = _namespace()
    stored = {"id": "p", "public_id": "public-a", "prompt_actions": ["edit", "delete"]}
    reader = namespace["_project_public_prompt"](
        stored, workspace={"id": "public-a", "status": "active"}, role="User",
        settings={"enable_public_workspaces": True},
    )
    locked = namespace["_project_public_prompt"](
        stored, workspace={"id": "public-a", "status": "locked"}, role="Owner",
        settings={"enable_public_workspaces": True},
    )

    assert reader["prompt_actions"] == []
    assert locked["prompt_actions"] == []


def test_read_context_denies_unknown_status_and_unknown_workspace():
    inactive_ns = _namespace(status="inactive")
    with pytest.raises(inactive_ns["PublicPromptError"]) as inactive:
        inactive_ns["require_public_prompt_read_context"]("user-1", "public-a")
    assert inactive.value.code == 403

    missing = _namespace()
    with pytest.raises(missing["PublicPromptError"]) as unknown:
        missing["require_public_prompt_read_context"]("user-1", "public-missing")
    assert unknown.value.code == 404


def test_read_context_denies_a_caller_without_a_role():
    namespace = _build_namespace(
        workspaces={"public-a": {"id": "public-a", "status": "active"}},
        roles={},
        settings={"enable_public_workspaces": True},
    )
    with pytest.raises(namespace["PublicPromptError"]) as denied:
        namespace["require_public_prompt_read_context"]("stranger", "public-a")
    assert denied.value.code == 403


def test_write_context_refuses_a_reader_and_a_non_active_status():
    reader = _namespace(role="User")
    with pytest.raises(reader["PublicPromptError"]) as denied:
        reader["require_public_prompt_write_context"]("user-1", "public-a", "edit")
    assert denied.value.code == 403

    locked = _namespace(status="locked", role="Owner")
    with pytest.raises(locked["PublicPromptError"]) as gated:
        locked["require_public_prompt_write_context"]("user-1", "public-a", "edit")
    assert gated.value.code == 403


def test_write_context_allows_a_manager_on_an_active_workspace():
    namespace = _namespace(role="DocumentManager")
    workspace, role, settings = namespace["require_public_prompt_write_context"](
        "user-1", "public-a", "create",
    )
    assert role == "DocumentManager"
    assert workspace["id"] == "public-a"
    assert settings["enable_public_workspaces"] is True


def test_create_validator_rejects_favorite_and_unknown_fields():
    namespace = _namespace()
    validate = namespace["validate_public_prompt_create"]

    _, _, _, favorite_error = validate({"name": "n", "content": "c", "is_favorite": True})
    assert favorite_error and "Favorites" in favorite_error
    _, _, _, unknown_error = validate({"name": "n", "content": "c", "color": "red"})
    assert unknown_error and "color" in unknown_error
    name, content, options, ok = validate({"name": " n ", "content": "c", "description": "d"})
    assert ok is None and name == "n" and content == "c" and options["description"] == "d"


def test_update_validator_requires_expected_etag():
    namespace = _namespace()
    validate = namespace["validate_public_prompt_update"]

    _, _, missing = validate({"name": "n"})
    assert missing and "expected_etag" in missing
    _, _, favorite_error = validate({"expected_etag": "e", "is_favorite": False})
    assert favorite_error and "Favorites" in favorite_error
    updates, etag, ok = validate({"expected_etag": "etag-9", "content": "new"})
    assert ok is None and etag == "etag-9" and updates == {"content": "new"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
