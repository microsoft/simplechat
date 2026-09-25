# functions_public_membership.py
"""Native public workspace membership: the member list, the pending requests, and every write.

This backs the ``/api/public-workspaces/<workspace_id>/membership/...`` routes. The
classic ``/api/public_workspaces/<ws_id>/members``, ``/requests`` and
``/transferOwnership`` routes are unchanged.

A public workspace has no ``users[]`` roster: its members are exactly the Owner, the
Admins and the DocumentManagers. ``User`` is every other signed-in reader, who is
never stored, listed, added or removed as a member. An ``admins`` or
``documentManagers`` entry is stored either as a ``{userId, displayName, email}``
dict or, in legacy data, as a bare string id.

Reads
-----
Every member (Owner, Admin or DocumentManager) may list the members, as classic
allows; the pending document-manager requests are for the Owner and Admins. A member
row is ``{userId, displayName, email, role, member_actions}`` and a request row is
``{userId, displayName, email}``. The list is sorted by role (Owner, Admin,
DocumentManager), then casefolded name, then id; ``search`` matches a casefolded
substring of the name or the email, or the exact id, and ``role`` filters. The page
is cut after filtering, so ``total_count`` counts the filtered list.

The member-list envelope carries ``membership_management`` from
``public_membership_operations``, and each row carries ``member_actions`` from
``public_member_actions`` -- the one decision the routes enforce, so the Members view
can never offer a control the routes refuse.

**Disclosure (decision 18).** The Owner and Admins see every member's email; any
other viewer (a DocumentManager) sees names and roles with the email blanked, applied
by ``project_member_rows`` before the list leaves the route. This is a behaviour
change from classic, which showed every email to every member. No read calls Graph:
a legacy bare-string entry shows a blank name and email until a guarded write stores
it, and every guarded write normalizes the string entries it finds into dicts.

Writes
------
Every write goes through ``update_public_workspace_document_with_etag_guard``. The
caller's role and the target's state are re-checked on every fresh copy, so a demotion
or removal that lands mid-write refuses the write, a concurrent membership change is
kept, and a workspace deleted mid-write is a 404 and is never recreated.

- add: adds an Admin or a DocumentManager from the submitted details, keeps the
  classic ``public_workspace_membership_change`` notification, and bumps
  ``public_workspace_member_added``;
- role change: moves a member between ``admins`` and ``documentManagers``, carrying
  over their stored name and email (decision 21 / R5.7), keeps the classic
  notification, and bumps ``public_workspace_member_role_updated``;
- remove: drops a member from ``admins`` and ``documentManagers`` and bumps
  ``public_workspace_member_removed``. Self-removal is refused: there is no "leave"
  (decision 17);
- approve: moves the request into ``documentManagers`` and bumps
  ``public_workspace_member_request_approved``; reject: drops it, no bump;
- transfer: makes an existing Admin or DocumentManager the Owner and re-adds the old
  owner as a DocumentManager with their name and email (decision 21), and bumps
  ``public_workspace_ownership_transferred``.

Adding a member and changing a role need an ``active`` or ``upload_disabled``
workspace, from an explicit allowlist; every other write is allowed in every status,
as classic allows. Adding or changing to the role already held changes nothing and
writes nothing, so a retry after a lost response succeeds.

Every response is ``no-store``. Every failure is a stable, data-free message with an
``error_code``.
"""

import json
import logging
import re
from urllib.parse import quote

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from functions_appinsights import log_event
from functions_notifications import create_notification
from functions_public_membership_disclosure import project_member_rows
from functions_public_membership_policy import (
    PUBLIC_ASSIGNABLE_ROLES,
    PUBLIC_MEMBERSHIP_HINT_SCHEMA_VERSION,
    PUBLIC_MEMBERSHIP_MANAGER_ROLES,
    PUBLIC_MEMBER_ROLES,
    public_member_actions,
    public_member_add_allowed,
    public_membership_operations,
)
from functions_public_workspaces import (
    PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE,
    PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE,
    PublicWorkspaceDocumentWriteConflict,
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
    update_public_workspace_document_with_etag_guard,
)
from functions_settings import get_settings


PUBLIC_MEMBER_LIST_PARAMETERS = ("search", "role", "page", "page_size")
PUBLIC_MEMBER_LIST_DEFAULT_PAGE_SIZE = 20
PUBLIC_MEMBER_LIST_MAX_PAGE_SIZE = 100
PUBLIC_MEMBER_LIST_MAX_PAGE = 10000
PUBLIC_MEMBER_SEARCH_MAX_LENGTH = 200
PUBLIC_MEMBER_TEXT_MAX_LENGTH = 256
PUBLIC_MEMBER_ADD_FIELDS = ("userId", "displayName", "email", "role")
PUBLIC_STORED_ROLES = ("Owner", "Admin", "DocumentManager")

PUBLIC_ROLE_RANK = {role: rank for rank, role in enumerate(PUBLIC_MEMBER_ROLES)}
# The membership-change notification the classic add and role-change routes send.
MEMBERSHIP_NOTIFICATION_TYPE = "public_workspace_membership_change"

INVALID_MEMBERSHIP_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
MEMBER_TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MEMBERSHIP_WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")

WORKSPACE_NOT_FOUND_MESSAGE = "Public workspace not found."
NOT_A_MEMBER_MESSAGE = "You're not a member of this public workspace."
MEMBERSHIP_PERMISSION_MESSAGE = "Only the workspace's owner or an admin can manage its members."
OWNER_ONLY_MESSAGE = "Only the workspace's owner can transfer ownership."
STATUS_UNAVAILABLE_MESSAGE = "Members can't be changed while this workspace is in its current status."
MEMBER_NOT_FOUND_MESSAGE = "That person isn't a member of this public workspace."
ALREADY_MEMBER_MESSAGE = "That person is already a member of this public workspace."
NO_PENDING_REQUEST_MESSAGE = "That person doesn't have a pending request to join this public workspace."
OWNER_ROLE_MESSAGE = "Transfer ownership to change the owner's role."
OWNER_REMOVAL_MESSAGE = "Transfer ownership before removing the owner."
SELF_REMOVAL_MESSAGE = "You can't remove yourself from a public workspace."
WRITE_CONFLICT_MESSAGE = PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE
MEMBERSHIP_UNAVAILABLE_MESSAGE = "The membership request could not be completed. Try again."
MEMBERSHIP_REQUEST_MESSAGE = "The request could not be processed."


class PublicMembershipError(HTTPException):
    """A stable, non-sensitive failure at the public membership boundary.

    ``fields`` are extra, equally safe response members (``error_code``) returned
    beside ``error``.
    """

    def __init__(self, message, status_code, **fields):
        super().__init__(description=message)
        self.code = status_code
        self.fields = fields


class _NoChange(Exception):
    """Raised from a write's change to report that the fresh copy needs no write."""

    def __init__(self, workspace):
        super().__init__("no change")
        self.workspace = workspace


def _error(message, status_code, error_code):
    return PublicMembershipError(message, status_code, error_code=error_code)


def _invalid(message):
    return _error(message, 400, "invalid_request")


def _workspace_not_found():
    return _error(WORKSPACE_NOT_FOUND_MESSAGE, 404, "workspace_not_found")


def _member_not_found():
    return _error(MEMBER_NOT_FOUND_MESSAGE, 404, "member_not_found")


def public_membership_error_response(error):
    """Map boundary errors to stable responses; anything else is a logged, generic 500."""
    if isinstance(error, PublicMembershipError):
        payload, status = {"error": error.description, **error.fields}, error.code
    elif isinstance(error, HTTPException) and isinstance(error.code, int) and 400 <= error.code < 500:
        payload, status = {"error": MEMBERSHIP_REQUEST_MESSAGE, "error_code": "invalid_request"}, error.code
    else:
        log_event(
            "[WORKSPACE_ROUTE] Public membership request failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        payload, status = {
            "error": MEMBERSHIP_UNAVAILABLE_MESSAGE,
            "error_code": "public_membership_unavailable",
        }, 500
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


# ---------------------------------------------------------------------------
# Strict request parsing
# ---------------------------------------------------------------------------

def reject_query_parameters():
    """These routes take no query parameters; a stray one is a 400."""
    if request.args:
        raise _invalid("This request does not accept query parameters.")


def reject_request_body():
    if request.get_data():
        raise _invalid("This request does not accept a request body.")


def read_strict_json_object():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second value
    cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise _invalid("Duplicate fields are not supported.")
            payload[key] = value
        return payload

    if not request.is_json:
        raise _invalid("A JSON object is required for this request.")
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid("Provide valid JSON with no duplicate fields.") from error
    if not isinstance(body, dict):
        raise _invalid("A JSON object is required for this request.")
    return body


def _identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_MEMBERSHIP_ID.search(value)
    ):
        raise _invalid(f"Invalid {label}.")
    return value


def _require_user_id(user_id):
    if not isinstance(user_id, str) or not user_id:
        raise _error("User not authenticated.", 401, "not_authenticated")
    return user_id


def _actor_id(user_info):
    return _require_user_id(user_info.get("userId") if isinstance(user_info, dict) else None)


def _whole_number(value, *, default, maximum, message):
    if value is None:
        return default
    if not MEMBERSHIP_WHOLE_NUMBER.fullmatch(value) or int(value) > maximum:
        raise _invalid(message)
    return int(value)


def read_member_list_query():
    """Read ``search``, ``role``, ``page`` and ``page_size``; anything else is a 400."""
    arguments = request.args
    for key in arguments.keys():
        if key not in PUBLIC_MEMBER_LIST_PARAMETERS:
            raise _invalid("Use only the search, role, page and page_size query parameters.")
        if len(arguments.getlist(key)) > 1:
            raise _invalid("Give each query parameter only once.")
    search = arguments.get("search", "").strip()
    if len(search) > PUBLIC_MEMBER_SEARCH_MAX_LENGTH:
        raise _invalid(f"Search terms can be at most {PUBLIC_MEMBER_SEARCH_MAX_LENGTH} characters.")
    role = arguments.get("role")
    if role is not None and role not in PUBLIC_MEMBER_ROLES:
        raise _invalid("The role must be Owner, Admin, DocumentManager or User.")
    page = _whole_number(
        arguments.get("page"),
        default=1,
        maximum=PUBLIC_MEMBER_LIST_MAX_PAGE,
        message=f"The page must be a whole number from 1 to {PUBLIC_MEMBER_LIST_MAX_PAGE}.",
    )
    page_size = _whole_number(
        arguments.get("page_size"),
        default=PUBLIC_MEMBER_LIST_DEFAULT_PAGE_SIZE,
        maximum=PUBLIC_MEMBER_LIST_MAX_PAGE_SIZE,
        message=f"The page size must be a whole number from 1 to {PUBLIC_MEMBER_LIST_MAX_PAGE_SIZE}.",
    )
    return {"search": search, "role": role, "page": page, "page_size": page_size}


def _member_text(body, key, label):
    value = body.get(key, "")
    if not isinstance(value, str):
        raise _invalid(f"The {label} must be text.")
    value = value.strip()
    if len(value) > PUBLIC_MEMBER_TEXT_MAX_LENGTH:
        raise _invalid(f"The {label} can be at most {PUBLIC_MEMBER_TEXT_MAX_LENGTH} characters.")
    if MEMBER_TEXT_CONTROL_CHARACTERS.search(value):
        raise _invalid(f"The {label} can't contain control characters.")
    return value


def _assignable_role(body):
    role = body.get("role")
    if role not in PUBLIC_ASSIGNABLE_ROLES:
        raise _invalid("The role must be Admin or DocumentManager.")
    return role


def _body_user_id(body):
    user_id = body.get("userId")
    if isinstance(user_id, str):
        user_id = user_id.strip()
    return _identifier(user_id, "user identifier")


def read_add_member_body():
    """Validate an add body, which is exactly ``{userId, displayName?, email?, role}``."""
    body = read_strict_json_object()
    if any(key not in PUBLIC_MEMBER_ADD_FIELDS for key in body):
        raise _invalid("Only userId, displayName, email and role can be sent when adding a member.")
    return {
        "user_id": _body_user_id(body),
        "display_name": _member_text(body, "displayName", "display name"),
        "email": _member_text(body, "email", "email"),
        "role": _assignable_role(body),
    }


def read_role_body():
    """Validate a role change body, which is exactly ``{role}``."""
    body = read_strict_json_object()
    if any(key != "role" for key in body):
        raise _invalid("Send only the role to change a member's role.")
    return _assignable_role(body)


def read_owner_body():
    """Validate a transfer body, which is exactly ``{userId}``."""
    body = read_strict_json_object()
    if any(key != "userId" for key in body):
        raise _invalid("Send only the userId of the new owner.")
    return _body_user_id(body)


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def _text(value):
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _list_field(workspace, key):
    value = workspace.get(key)
    return value if isinstance(value, list) else []


def _entry_user_id(entry):
    """The user id for an ``admins`` or ``documentManagers`` entry, dict or bare string."""
    if isinstance(entry, dict):
        user_id = entry.get("userId")
        return user_id if isinstance(user_id, str) and user_id else None
    return entry if isinstance(entry, str) and entry else None


def _entry_name_email(entry):
    """The stored name and email for an entry; a legacy bare string has neither."""
    if isinstance(entry, dict):
        return _text(entry.get("displayName")), _text(entry.get("email"))
    return "", ""


def _member_entries(workspace):
    """The workspace's members as ``{userId, displayName, email, role}``, highest role first.

    A user appearing in more than one list is taken once, at their highest role
    (Owner, then Admin, then DocumentManager), matching ``get_user_role_in_public_workspace``.
    Malformed entries and entries without a usable id are dropped, and no read calls
    Graph: a legacy bare-string entry has a blank name and email.
    """
    entries, seen = [], set()
    owner = workspace.get("owner") if isinstance(workspace.get("owner"), dict) else {}
    owner_id = owner.get("userId") if isinstance(owner.get("userId"), str) and owner.get("userId") else None
    if owner_id:
        seen.add(owner_id)
        entries.append({
            "userId": owner_id,
            "displayName": _text(owner.get("displayName")),
            "email": _text(owner.get("email")),
            "role": "Owner",
        })
    for key, role in (("admins", "Admin"), ("documentManagers", "DocumentManager")):
        for entry in _list_field(workspace, key):
            member_id = _entry_user_id(entry)
            if member_id and member_id not in seen:
                seen.add(member_id)
                name, email = _entry_name_email(entry)
                entries.append({"userId": member_id, "displayName": name, "email": email, "role": role})
    return entries


def _stored_role(workspace, user_id):
    """The member's stored role, or ``None`` for a signed-in reader who isn't a member."""
    role = get_user_role_in_public_workspace(workspace, user_id) if user_id else None
    return role if role in PUBLIC_STORED_ROLES else None


def _member_row(entry, caller_id, caller_role):
    return {
        "userId": entry["userId"],
        "displayName": entry["displayName"],
        "email": entry["email"],
        "role": entry["role"],
        "member_actions": public_member_actions(caller_role, entry["role"], is_self=entry["userId"] == caller_id),
    }


def _row_for(workspace, member_id, caller_id):
    caller_role = _stored_role(workspace, caller_id)
    for entry in _member_entries(workspace):
        if entry["userId"] == member_id:
            row = _member_row(entry, caller_id, caller_role)
            return project_member_rows([row], caller_role)[0]
    return None


def _member_sort_key(row):
    return (PUBLIC_ROLE_RANK.get(row["role"], len(PUBLIC_ROLE_RANK)), row["displayName"].casefold(), row["userId"])


def _matches_search(row, needle):
    return (
        needle in row["displayName"].casefold()
        or needle in row["email"].casefold()
        or needle == row["userId"].casefold()
    )


# ---------------------------------------------------------------------------
# Authorization and writes
# ---------------------------------------------------------------------------

def _load_workspace(workspace_id):
    workspace = find_public_workspace_by_id(workspace_id)
    if not isinstance(workspace, dict):
        raise _workspace_not_found()
    return workspace


def _caller_role(workspace, caller_id):
    role = _stored_role(workspace, caller_id)
    if role is None:
        raise _error(NOT_A_MEMBER_MESSAGE, 403, "not_a_member")
    return role


def _manager_role(workspace, caller_id):
    role = _caller_role(workspace, caller_id)
    if role not in PUBLIC_MEMBERSHIP_MANAGER_ROLES:
        raise _error(MEMBERSHIP_PERMISSION_MESSAGE, 403, "membership_permission")
    return role


def _require_add_allowed(workspace):
    if not public_member_add_allowed(workspace):
        raise _error(STATUS_UNAVAILABLE_MESSAGE, 403, "public_status_unavailable")


def _normalize_member_lists(workspace):
    """Coerce legacy bare-string ``admins`` and ``documentManagers`` entries to dicts, once,
    on a guarded write, so no read has to call Graph (R2)."""
    for key in ("admins", "documentManagers"):
        values = workspace.get(key)
        if not isinstance(values, list):
            continue
        normalized, changed = [], False
        for entry in values:
            if isinstance(entry, str) and entry:
                normalized.append({"userId": entry, "displayName": "", "email": ""})
                changed = True
            else:
                normalized.append(entry)
        if changed:
            workspace[key] = normalized


def _remove_member_id(workspace, key, user_id):
    values = workspace.get(key)
    if isinstance(values, list):
        workspace[key] = [entry for entry in values if _entry_user_id(entry) != user_id]


def _pending_entries(workspace):
    return _list_field(workspace, "pendingDocumentManagers")


def _clear_pending(workspace, user_id):
    pending = _pending_entries(workspace)
    kept = [entry for entry in pending if _entry_user_id(entry) != user_id]
    if len(kept) != len(pending):
        workspace["pendingDocumentManagers"] = kept


def _stored_member_identity(workspace, member_id):
    """The member's stored name and email from the workspace's own admin or DM entries."""
    for key in ("admins", "documentManagers"):
        for entry in _list_field(workspace, key):
            if isinstance(entry, dict) and entry.get("userId") == member_id:
                return _text(entry.get("displayName")), _text(entry.get("email"))
    return "", ""


def _write(workspace_id, apply_changes, *, cache_reason):
    def guarded(workspace):
        if not isinstance(workspace, dict):
            raise _workspace_not_found()
        _normalize_member_lists(workspace)
        return apply_changes(workspace)

    try:
        committed = update_public_workspace_document_with_etag_guard(
            workspace_id, guarded, cache_reason=cache_reason
        )
    except PublicWorkspaceDocumentWriteConflict as error:
        raise _error(WRITE_CONFLICT_MESSAGE, 409, PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE) from error
    if committed is None:
        raise _workspace_not_found()
    return committed


def _notify_membership_change(*, member_id, workspace, workspace_id, title, message, metadata):
    """Send the classic membership-change notification, swallowing its own failure."""
    try:
        create_notification(
            user_id=member_id,
            notification_type=MEMBERSHIP_NOTIFICATION_TYPE,
            title=title,
            message=message,
            link_url=f"/public_workspaces/{quote(str(workspace_id), safe='')}",
            metadata=metadata,
        )
    except Exception as error:  # noqa: BLE001 - a notification failure must not fail the write
        log_event(
            "[WORKSPACE_ROUTE] Public membership notification could not be sent.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_public_members(user_id, workspace_id, *, search, role, page, page_size):
    """Return ``(payload, 200)`` with one page of the workspace's members."""
    caller_id = _require_user_id(user_id)
    _identifier(workspace_id, "workspace identifier")
    workspace = _load_workspace(workspace_id)
    caller_role = _caller_role(workspace, caller_id)
    needle = search.casefold()
    rows = [
        row for row in (_member_row(entry, caller_id, caller_role) for entry in _member_entries(workspace))
        if (role is None or row["role"] == role) and (not needle or _matches_search(row, needle))
    ]
    rows.sort(key=_member_sort_key)
    start = (page - 1) * page_size
    page_rows = project_member_rows(rows[start:start + page_size], caller_role)
    return {
        "members": page_rows,
        "page": page,
        "page_size": page_size,
        "total_count": len(rows),
        "membership_management": {
            "schema_version": PUBLIC_MEMBERSHIP_HINT_SCHEMA_VERSION,
            "operations": public_membership_operations(caller_role, workspace, get_settings()),
        },
    }, 200


def list_public_join_requests(user_id, workspace_id):
    """Return ``(payload, 200)`` with the pending document-manager requests, for the Owner and Admins."""
    caller_id = _require_user_id(user_id)
    _identifier(workspace_id, "workspace identifier")
    workspace = _load_workspace(workspace_id)
    _manager_role(workspace, caller_id)
    rows, seen = [], set()
    for entry in _pending_entries(workspace):
        pending_id = _entry_user_id(entry)
        if pending_id and pending_id not in seen:
            seen.add(pending_id)
            name, email = _entry_name_email(entry)
            rows.append({"userId": pending_id, "displayName": name, "email": email})
    rows.sort(key=lambda row: (row["displayName"].casefold(), row["userId"]))
    return {"requests": rows, "total_count": len(rows)}, 200


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def add_public_member(user_info, workspace_id):
    """Add a member and return ``({"member": row}, 201)``."""
    actor_id = _actor_id(user_info)
    _identifier(workspace_id, "workspace identifier")
    fields = read_add_member_body()
    member_id = fields["user_id"]
    new_role = fields["role"]
    member = {"userId": member_id, "displayName": fields["display_name"], "email": fields["email"]}

    def apply(fresh):
        _manager_role(fresh, actor_id)
        _require_add_allowed(fresh)
        if _stored_role(fresh, member_id) is not None:
            raise _error(ALREADY_MEMBER_MESSAGE, 409, "already_member")
        key = "admins" if new_role == "Admin" else "documentManagers"
        fresh[key] = [*_list_field(fresh, key), dict(member)]
        _clear_pending(fresh, member_id)
        return fresh

    committed = _write(workspace_id, apply, cache_reason="public_workspace_member_added")
    workspace_name = committed.get("name", "Unknown")
    _notify_membership_change(
        member_id=member_id,
        workspace=committed,
        workspace_id=workspace_id,
        title="Added to Public Workspace",
        message=f"You have been added to the public workspace '{workspace_name}' as {new_role}.",
        metadata={
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "role": new_role,
            "added_by": user_info.get("email", "Unknown"),
        },
    )
    return {"member": _row_for(committed, member_id, actor_id)}, 201


def change_public_member_role(user_info, workspace_id, member_id):
    """Change a member's role and return ``({"member": row, "changed": bool}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(workspace_id, "workspace identifier")
    _identifier(member_id, "user identifier")
    new_role = read_role_body()
    audit = {}

    def apply(fresh):
        _manager_role(fresh, actor_id)
        _require_add_allowed(fresh)
        target_role = _stored_role(fresh, member_id)
        if target_role is None:
            raise _member_not_found()
        if target_role == "Owner":
            raise _error(OWNER_ROLE_MESSAGE, 409, "owner_target")
        if target_role == new_role:
            raise _NoChange(fresh)
        # decision 21 / R5.7: carry the member's stored name and email across the move.
        name, email = _stored_member_identity(fresh, member_id)
        _remove_member_id(fresh, "admins", member_id)
        _remove_member_id(fresh, "documentManagers", member_id)
        key = "admins" if new_role == "Admin" else "documentManagers"
        fresh[key] = [*_list_field(fresh, key), {"userId": member_id, "displayName": name, "email": email}]
        audit["old_role"] = target_role
        return fresh

    try:
        committed = _write(workspace_id, apply, cache_reason="public_workspace_member_role_updated")
    except _NoChange as unchanged:
        return {"member": _row_for(unchanged.workspace, member_id, actor_id), "changed": False}, 200
    workspace_name = committed.get("name", "Unknown")
    _notify_membership_change(
        member_id=member_id,
        workspace=committed,
        workspace_id=workspace_id,
        title="Workspace Role Changed",
        message=f"Your role in the public workspace '{workspace_name}' has been changed to {new_role}.",
        metadata={
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "old_role": audit["old_role"],
            "new_role": new_role,
            "changed_by": user_info.get("email", "Unknown"),
        },
    )
    return {"member": _row_for(committed, member_id, actor_id), "changed": True}, 200


def remove_public_member(user_info, workspace_id, member_id):
    """Remove a member and return ``({"userId": ...}, 200)``. There is no "leave"."""
    actor_id = _actor_id(user_info)
    _identifier(workspace_id, "workspace identifier")
    _identifier(member_id, "user identifier")
    if member_id == actor_id:
        raise _error(SELF_REMOVAL_MESSAGE, 403, "cannot_leave")

    def apply(fresh):
        _manager_role(fresh, actor_id)
        target_role = _stored_role(fresh, member_id)
        if target_role is None:
            raise _member_not_found()
        if target_role == "Owner":
            raise _error(OWNER_REMOVAL_MESSAGE, 409, "owner_target")
        _remove_member_id(fresh, "admins", member_id)
        _remove_member_id(fresh, "documentManagers", member_id)
        return fresh

    _write(workspace_id, apply, cache_reason="public_workspace_member_removed")
    return {"userId": member_id}, 200


def approve_public_request(user_info, workspace_id, member_id):
    """Approve a pending request and return ``({"member": row, "already_member": bool}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(workspace_id, "workspace identifier")
    _identifier(member_id, "user identifier")
    audit = {}

    def apply(fresh):
        _manager_role(fresh, actor_id)
        entries = [entry for entry in _pending_entries(fresh) if _entry_user_id(entry) == member_id]
        if not entries:
            raise _error(NO_PENDING_REQUEST_MESSAGE, 409, "no_pending_request")
        already_member = _stored_role(fresh, member_id) is not None
        _clear_pending(fresh, member_id)
        if not already_member:
            name, email = _entry_name_email(entries[0])
            fresh["documentManagers"] = [
                *_list_field(fresh, "documentManagers"),
                {"userId": member_id, "displayName": name, "email": email},
            ]
        audit["already_member"] = already_member
        return fresh

    committed = _write(workspace_id, apply, cache_reason="public_workspace_member_request_approved")
    return {"member": _row_for(committed, member_id, actor_id), "already_member": audit["already_member"]}, 200


def reject_public_request(user_info, workspace_id, member_id):
    """Reject a pending request and return ``({"userId": ...}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(workspace_id, "workspace identifier")
    _identifier(member_id, "user identifier")

    def apply(fresh):
        _manager_role(fresh, actor_id)
        if not any(_entry_user_id(entry) == member_id for entry in _pending_entries(fresh)):
            raise _error(NO_PENDING_REQUEST_MESSAGE, 409, "no_pending_request")
        _clear_pending(fresh, member_id)
        return fresh

    _write(workspace_id, apply, cache_reason=None)
    return {"userId": member_id}, 200


def transfer_public_ownership(user_info, workspace_id):
    """Make an existing manager the owner and return ``({"owner": row, "changed": bool}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(workspace_id, "workspace identifier")
    new_owner_id = read_owner_body()

    def apply(fresh):
        owner = fresh.get("owner") if isinstance(fresh.get("owner"), dict) else {}
        current_owner_id = owner.get("userId") if isinstance(owner.get("userId"), str) else None
        if current_owner_id == new_owner_id:
            raise _NoChange(fresh)
        if current_owner_id != actor_id:
            raise _error(OWNER_ONLY_MESSAGE, 403, "owner_only")
        if _stored_role(fresh, new_owner_id) not in ("Admin", "DocumentManager"):
            raise _member_not_found()
        new_name, new_email = _stored_member_identity(fresh, new_owner_id)
        # decision 21: the old owner stays a DocumentManager with their name and email.
        old_owner_id = current_owner_id
        old_name = _text(owner.get("displayName"))
        old_email = _text(owner.get("email"))
        _remove_member_id(fresh, "admins", new_owner_id)
        _remove_member_id(fresh, "documentManagers", new_owner_id)
        fresh["owner"] = {"userId": new_owner_id, "displayName": new_name, "email": new_email}
        _remove_member_id(fresh, "admins", old_owner_id)
        _remove_member_id(fresh, "documentManagers", old_owner_id)
        fresh["documentManagers"] = [
            *_list_field(fresh, "documentManagers"),
            {"userId": old_owner_id, "displayName": old_name, "email": old_email},
        ]
        return fresh

    try:
        committed = _write(workspace_id, apply, cache_reason="public_workspace_ownership_transferred")
    except _NoChange as unchanged:
        return {"owner": _row_for(unchanged.workspace, new_owner_id, actor_id), "changed": False}, 200
    return {"owner": _row_for(committed, new_owner_id, actor_id), "changed": True}, 200
