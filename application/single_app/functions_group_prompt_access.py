# functions_group_prompt_access.py
"""Authorization, projection and orchestration for immutable-target group prompts.

The active-scoped legacy routes in ``route_backend_group_prompts.py`` are left
untouched. Everything here backs the new ``/api/groups/<group_id>/prompts``
family, where the group is named in the path and every request reauthorizes
membership, role and status independently of whatever workspace the account has
selected.

Group prompts have no screening, revisions, source blobs or per-creator
ownership, so this mirrors the shape of the M2B group-document access layer while
being far slimmer. There is exactly one projector, ``_project_group_prompt``, and
exactly one private-field set, ``PRIVATE_GROUP_PROMPT_FIELDS`` — the rule this
programme has learned twice is one definition of a private field, never a local
pop-list.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_prompt_policy import (
    GROUP_PROMPT_MANAGER_ROLES,
    GROUP_PROMPT_READER_ROLES,
    GROUP_PROMPT_READ_STATUSES,
    group_prompt_actions,
    group_prompt_management_operations,
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


GROUP_PROMPT_TYPE = "group_prompt"

# The body fields the new routes accept. ``is_favorite`` is deliberately absent
# and rejected with a specific message (see §5): a favorite is personal, but the
# flag lives on the shared prompt document.
GROUP_PROMPT_CREATE_FIELDS = frozenset({"name", "content", "description"})
GROUP_PROMPT_UPDATE_FIELDS = frozenset({"name", "content", "description", "expected_etag"})

# Serialization denylist. ``prompt_actions`` is computed fresh per request and
# never served from storage; ``is_favorite`` is omitted in group scope so a
# stored value cannot be mistaken for the reader's own favorite; ``user_id`` and
# ``public_id`` are foreign-scope identity fields that must never surface here.
# ``group_id`` is intentionally kept so the client can verify each returned
# prompt belongs to the requested group.
PRIVATE_GROUP_PROMPT_FIELDS = frozenset({"is_favorite", "prompt_actions", "user_id", "public_id"})

INVALID_GROUP_PROMPT_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class GroupPromptError(HTTPException):
    """A stable, non-sensitive failure at a group prompt boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GROUP_PROMPT_ID.search(value)
    ):
        raise GroupPromptError(f"Invalid {label}.", 400)


def require_group_prompt_read_context(user_id, group_id):
    """Resolve (group, role) for a reader, or raise a boundary error.

    Reads are open to all four member roles. Unknown group is 404, ineligible
    role is 403, and a status outside the browsable set is 403 — an unrecognized
    status is treated as unavailable, never as active.
    """
    _validate_identifier(group_id, "group identifier")
    if not user_id:
        raise GroupPromptError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_PROMPT_READER_ROLES)
    except LookupError as error:
        raise GroupPromptError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupPromptError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupPromptError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_PROMPT_READER_ROLES:
        raise GroupPromptError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_PROMPT_READ_STATUSES:
        raise GroupPromptError("Prompts are unavailable for this group's current status.", 403)
    return group, role


def require_group_prompt_write_context(user_id, group_id, operation):
    """Resolve (group, role, settings) for a writer, or raise a boundary error.

    Writes are limited to Owner, Admin and DocumentManager. ``User`` reaches the
    manager-role assertion and is refused with 403, so an ordinary member is
    denied a write to a prompt it can read. The operation must also be offered
    by the group's current status.
    """
    group, role = require_group_prompt_read_context(user_id, group_id)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_PROMPT_MANAGER_ROLES)
    except (LookupError, PermissionError) as error:
        raise GroupPromptError("You do not have permission to manage this group's prompts.", 403) from error
    settings = get_settings()
    if operation not in group_prompt_management_operations(group, role, settings):
        raise GroupPromptError("This operation is unavailable for the selected group.", 403)
    return group, role, settings


def _project_group_prompt(prompt, *, group, role, settings, include_actions=True):
    """The single group prompt serializer.

    Strips the private field set and every Cosmos internal (``_etag``, ``_rid``
    and the rest), surfaces the ETag under ``etag`` for conditional writes, and
    computes ``prompt_actions`` from policy so the hint can never be a stored
    constant.
    """
    projected = {
        key: value for key, value in prompt.items()
        if key not in PRIVATE_GROUP_PROMPT_FIELDS and not key.startswith("_")
    }
    projected["etag"] = prompt.get("_etag")
    if include_actions:
        projected["prompt_actions"] = group_prompt_actions(prompt, group, role, settings)
    return projected


def validate_group_prompt_create(data):
    """Validate a create body into ``(name, content, options, error)``.

    Rejects ``is_favorite`` explicitly and any field outside the create set, so a
    client cannot smuggle a favorite or an unknown attribute onto shared content.
    """
    if not isinstance(data, dict):
        return None, None, None, "A JSON object is required."
    if "is_favorite" in data:
        return None, None, None, "Favorites are not available for group prompts."
    unknown = set(data) - GROUP_PROMPT_CREATE_FIELDS
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


def validate_group_prompt_update(data):
    """Validate an update body into ``(updates, expected_etag, error)``.

    ``expected_etag`` is mandatory here (§4): a missing value is a 400, so a
    conditional write is never silently downgraded to last-write-wins.
    """
    if not isinstance(data, dict):
        return None, None, "A JSON object is required."
    if "is_favorite" in data:
        return None, None, "Favorites are not available for group prompts."
    unknown = set(data) - GROUP_PROMPT_UPDATE_FIELDS
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


def list_group_prompts(user_id, group_id, args):
    group, role = require_group_prompt_read_context(user_id, group_id)
    settings = get_settings()
    items, total_count, page, page_size = list_prompts(
        user_id=user_id, prompt_type=GROUP_PROMPT_TYPE, args=args, group_id=group_id,
    )
    return {
        "prompts": [
            _project_group_prompt(item, group=group, role=role, settings=settings)
            for item in items
        ],
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
    }


def read_group_prompt(user_id, group_id, prompt_id):
    _validate_identifier(prompt_id, "prompt identifier")
    group, role = require_group_prompt_read_context(user_id, group_id)
    settings = get_settings()
    item = get_prompt_doc(
        user_id=user_id, prompt_id=prompt_id, prompt_type=GROUP_PROMPT_TYPE, group_id=group_id,
    )
    if not item:
        raise GroupPromptError("Prompt not found or access denied.", 404)
    return _project_group_prompt(item, group=group, role=role, settings=settings)


def create_group_prompt(user_id, group_id, name, content, options):
    group, role, settings = require_group_prompt_write_context(user_id, group_id, "create")
    created = create_prompt_doc(
        name=name, content=content, prompt_type=GROUP_PROMPT_TYPE, user_id=user_id,
        group_id=group_id, return_full=True, **options,
    )
    return _project_group_prompt(created, group=group, role=role, settings=settings)


def update_group_prompt(user_id, group_id, prompt_id, updates, expected_etag):
    _validate_identifier(prompt_id, "prompt identifier")
    group, role, settings = require_group_prompt_write_context(user_id, group_id, "edit")
    updated = update_prompt_doc(
        user_id=user_id, prompt_id=prompt_id, prompt_type=GROUP_PROMPT_TYPE, updates=updates,
        group_id=group_id, expected_etag=expected_etag, return_full=True,
    )
    if updated is None:
        raise GroupPromptError("Prompt not found or access denied.", 404)
    return _project_group_prompt(updated, group=group, role=role, settings=settings)


def delete_group_prompt(user_id, group_id, prompt_id, expected_etag):
    _validate_identifier(prompt_id, "prompt identifier")
    require_group_prompt_write_context(user_id, group_id, "delete")
    deleted = delete_prompt_doc(
        user_id=user_id, prompt_id=prompt_id, group_id=group_id, expected_etag=expected_etag,
    )
    if not deleted:
        raise GroupPromptError("Prompt not found or access denied.", 404)
    return True
