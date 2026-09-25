# functions_public_prompt_access.py
"""Authorization, projection and orchestration for immutable-target public prompts.

Version: 0.261.178
Implemented in: 0.261.178

The active-scoped legacy routes in ``route_backend_public_prompts.py`` are left
untouched except for the status check M9C adds to their writes. Everything here
backs the new ``/api/public-workspaces/<workspace_id>/prompts`` family, where the
workspace is named in the path and every request reauthorizes role and status
independently of whatever workspace the account has selected as active.

This mirrors ``functions_group_prompt_access.py`` closely -- the same store, the
same client and the same conditional-write transport -- with three public-scope
differences: the scope id lives in ``public_id`` rather than ``group_id``; role
is resolved directly from the workspace document (any authenticated caller reads
a public workspace as at least a ``User``, exactly as the legacy route and the
public context already allow); and the readable-status gate is an **explicit**
allowlist so an unrecognized status is denied rather than treated as active.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_public_workspaces import (
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)
from functions_public_prompt_policy import (
    PUBLIC_PROMPT_MANAGER_ROLES,
    PUBLIC_PROMPT_READER_ROLES,
    PUBLIC_PROMPT_READ_STATUSES,
    public_prompt_actions,
    public_prompt_management_operations,
)
from functions_prompts import (
    PromptConflictError,
    create_prompt_doc,
    delete_prompt_doc,
    get_prompt_doc,
    list_prompts,
    normalize_prompt_description,
    update_prompt_doc,
)
from functions_settings import get_settings


PUBLIC_PROMPT_TYPE = "public_prompt"

# The body fields the new routes accept. ``is_favorite`` is deliberately absent
# and rejected with a specific message: a favorite is personal, but the flag
# lives on the shared prompt document.
PUBLIC_PROMPT_CREATE_FIELDS = frozenset({"name", "content", "description"})
PUBLIC_PROMPT_UPDATE_FIELDS = frozenset({"name", "content", "description", "expected_etag"})

# Serialization denylist. ``prompt_actions`` is computed fresh per request and
# never served from storage; ``is_favorite`` is omitted in public scope so a
# stored value cannot be mistaken for the reader's own favorite; ``user_id`` and
# ``group_id`` are foreign-scope identity fields that must never surface here.
# ``public_id`` is intentionally kept so the client can verify each returned
# prompt belongs to the requested workspace.
PRIVATE_PUBLIC_PROMPT_FIELDS = frozenset({"is_favorite", "prompt_actions", "user_id", "group_id"})

INVALID_PUBLIC_PROMPT_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class PublicPromptError(HTTPException):
    """A stable, non-sensitive failure at a public prompt boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_PUBLIC_PROMPT_ID.search(value)
    ):
        raise PublicPromptError(f"Invalid {label}.", 400)


def require_public_prompt_read_context(user_id, workspace_id):
    """Resolve (workspace, role) for a reader, or raise a boundary error.

    Reads are open to every role, including ``User``: any authenticated caller
    reads a public workspace as at least a ``User``, matching the legacy route
    and the public context. Unknown workspace is 404, and a status outside the
    browsable allowlist is 403 -- an unrecognized status is treated as
    unavailable, never as active.
    """
    _validate_identifier(workspace_id, "public workspace identifier")
    if not user_id:
        raise PublicPromptError("User not authenticated.", 401)
    workspace = find_public_workspace_by_id(workspace_id)
    if not workspace:
        raise PublicPromptError("The selected public workspace was not found.", 404)
    role = get_user_role_in_public_workspace(workspace, user_id)
    if role not in PUBLIC_PROMPT_READER_ROLES:
        raise PublicPromptError("You do not have access to the selected public workspace.", 403)
    if workspace.get("status", "active") not in PUBLIC_PROMPT_READ_STATUSES:
        raise PublicPromptError("Prompts are unavailable for this workspace's current status.", 403)
    return workspace, role


def require_public_prompt_write_context(user_id, workspace_id, operation):
    """Resolve (workspace, role, settings) for a writer, or raise a boundary error.

    Writes are limited to Owner, Admin and DocumentManager, and only while the
    workspace is ``active``. A ``User`` who can read a prompt is refused a write
    to it, and a manager is refused a write when the status is not ``active``.
    """
    workspace, role = require_public_prompt_read_context(user_id, workspace_id)
    if role not in PUBLIC_PROMPT_MANAGER_ROLES:
        raise PublicPromptError("You do not have permission to manage this workspace's prompts.", 403)
    settings = get_settings()
    if operation not in public_prompt_management_operations(workspace, role, settings):
        raise PublicPromptError("This operation is unavailable for the selected public workspace.", 403)
    return workspace, role, settings


def _project_public_prompt(prompt, *, workspace, role, settings, include_actions=True):
    """The single public prompt serializer.

    Strips the private field set and every Cosmos internal (``_etag``, ``_rid``
    and the rest), surfaces the ETag under ``etag`` for conditional writes, and
    computes ``prompt_actions`` from policy so the hint can never be a stored
    constant.
    """
    projected = {
        key: value for key, value in prompt.items()
        if key not in PRIVATE_PUBLIC_PROMPT_FIELDS and not key.startswith("_")
    }
    projected["etag"] = prompt.get("_etag")
    if include_actions:
        projected["prompt_actions"] = public_prompt_actions(prompt, workspace, role, settings)
    return projected


def validate_public_prompt_create(data):
    """Validate a create body into ``(name, content, options, error)``.

    Rejects ``is_favorite`` explicitly and any field outside the create set, so a
    client cannot smuggle a favorite or an unknown attribute onto shared content.
    """
    if not isinstance(data, dict):
        return None, None, None, "A JSON object is required."
    if "is_favorite" in data:
        return None, None, None, "Favorites are not available for public workspace prompts."
    unknown = set(data) - PUBLIC_PROMPT_CREATE_FIELDS
    if unknown:
        return None, None, None, f"Unsupported field(s): {', '.join(sorted(unknown))}."
    name = data.get("name")
    content = data.get("content")
    if not isinstance(name, str) or not name.strip():
        return None, None, None, "A non-empty 'name' is required."
    if not isinstance(content, str):
        return None, None, None, "A 'content' string is required."
    if "description" in data and data["description"] is not None and not isinstance(data["description"], str):
        return None, None, None, "Invalid 'description' provided."
    options = {"description": normalize_prompt_description(data.get("description"))}
    return name.strip(), content, options, None


def validate_public_prompt_update(data):
    """Validate an update body into ``(updates, expected_etag, error)``.

    ``expected_etag`` is mandatory here: a missing value is a 400, so a
    conditional write is never silently downgraded to last-write-wins.
    """
    if not isinstance(data, dict):
        return None, None, "A JSON object is required."
    if "is_favorite" in data:
        return None, None, "Favorites are not available for public workspace prompts."
    unknown = set(data) - PUBLIC_PROMPT_UPDATE_FIELDS
    if unknown:
        return None, None, f"Unsupported field(s): {', '.join(sorted(unknown))}."
    expected_etag = data.get("expected_etag")
    if not isinstance(expected_etag, str) or not expected_etag.strip():
        return None, None, "A non-empty 'expected_etag' is required."
    updates = {}
    if "name" in data:
        if not isinstance(data["name"], str) or not data["name"].strip():
            return None, None, "Invalid 'name' provided."
        updates["name"] = data["name"].strip()
    if "content" in data:
        if not isinstance(data["content"], str):
            return None, None, "Invalid 'content' provided."
        updates["content"] = data["content"]
    if "description" in data:
        if data["description"] is not None and not isinstance(data["description"], str):
            return None, None, "Invalid 'description' provided."
        updates["description"] = normalize_prompt_description(data["description"])
    if not updates:
        return None, None, "No fields provided for update."
    return updates, expected_etag, None


def list_public_prompts(user_id, workspace_id, args):
    workspace, role = require_public_prompt_read_context(user_id, workspace_id)
    settings = get_settings()
    items, total_count, page, page_size = list_prompts(
        user_id=user_id, prompt_type=PUBLIC_PROMPT_TYPE, args=args, public_workspace_id=workspace_id,
    )
    return {
        "prompts": [
            _project_public_prompt(item, workspace=workspace, role=role, settings=settings)
            for item in items
        ],
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
    }


def read_public_prompt(user_id, workspace_id, prompt_id):
    _validate_identifier(prompt_id, "prompt identifier")
    workspace, role = require_public_prompt_read_context(user_id, workspace_id)
    settings = get_settings()
    item = get_prompt_doc(
        user_id=user_id, prompt_id=prompt_id, prompt_type=PUBLIC_PROMPT_TYPE, public_workspace_id=workspace_id,
    )
    if not item:
        raise PublicPromptError("Prompt not found or access denied.", 404)
    return _project_public_prompt(item, workspace=workspace, role=role, settings=settings)


def create_public_prompt(user_id, workspace_id, name, content, options):
    workspace, role, settings = require_public_prompt_write_context(user_id, workspace_id, "create")
    created = create_prompt_doc(
        name=name, content=content, prompt_type=PUBLIC_PROMPT_TYPE, user_id=user_id,
        public_workspace_id=workspace_id, return_full=True, **options,
    )
    return _project_public_prompt(created, workspace=workspace, role=role, settings=settings)


def update_public_prompt(user_id, workspace_id, prompt_id, updates, expected_etag):
    _validate_identifier(prompt_id, "prompt identifier")
    workspace, role, settings = require_public_prompt_write_context(user_id, workspace_id, "edit")
    updated = update_prompt_doc(
        user_id=user_id, prompt_id=prompt_id, prompt_type=PUBLIC_PROMPT_TYPE, updates=updates,
        public_workspace_id=workspace_id, expected_etag=expected_etag, return_full=True,
    )
    if updated is None:
        raise PublicPromptError("Prompt not found or access denied.", 404)
    return _project_public_prompt(updated, workspace=workspace, role=role, settings=settings)


def delete_public_prompt(user_id, workspace_id, prompt_id, expected_etag):
    _validate_identifier(prompt_id, "prompt identifier")
    require_public_prompt_write_context(user_id, workspace_id, "delete")
    deleted = delete_prompt_doc(
        user_id=user_id, prompt_id=prompt_id, public_workspace_id=workspace_id, expected_etag=expected_etag,
    )
    if not deleted:
        raise PublicPromptError("Prompt not found or access denied.", 404)
    return True
