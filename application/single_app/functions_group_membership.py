# functions_group_membership.py
"""Native group membership: the member list, the pending requests, and every write.

This backs the ``/api/groups/<group_id>/membership/...`` routes. The classic
``/api/groups/<group_id>/members``, ``/requests`` and ``/transferOwnership`` routes
are unchanged.

Reads
-----
Every member may list the members, as classic allows; the pending requests are for
the Owner and Admins. Both are narrow projections: a member row is ``{userId,
displayName, email, role, member_actions}`` and a request row is ``{userId,
displayName, email}``. The member list takes each ``users[]`` entry once (the first
one for a repeated ``userId``), adds the Owner when their entry is missing, skips
entries without a ``userId``, and sorts by role (Owner, Admin, DocumentManager,
User), then casefolded name, then id. ``search`` matches a casefolded substring of
the name or the email, or the exact user id, and ``role`` is one of the four roles.
The page is cut after filtering and sorting, so ``total_count`` counts the filtered
list. Reads are allowed in every group status.

The member-list envelope carries ``membership_management``: ``{schema_version: 1,
operations}``, from ``group_membership_operations``, the decision the routes
enforce. Its ``review_requests`` operation covers the request list and its approve
and reject routes. Each row carries ``member_actions`` from
``group_member_actions``.

Writes
------
Every write goes through ``update_group_document_with_etag_guard``. The caller's
role and the target's state are re-checked on every fresh copy, so a demotion or
removal that lands mid-write refuses the write, a concurrent membership change is
kept, and a group deleted mid-write is a 404 and is never recreated. The audit
runs once, after the write commits, and reuses the classic writers' own helpers:

- add: ``_log_group_member_addition``, ``_notify_group_member_addition`` and the
  ``group_member_added`` cache bump;
- role change: ``log_group_member_role_change``, ``notify_group_member_role_change``
  and the ``group_member_role_updated`` bump;
- remove and leave: ``log_group_member_deleted`` (``admin_removed_member`` or
  ``member_left_group``) and the ``group_member_removed`` bump, when a ``users[]``
  entry is removed;
- approve: the ``group_member_request_approved`` bump; reject: nothing;
- transfer: the ``group_ownership_transferred`` bump.

Approve, reject and add remove every pending entry for the user, and approving
someone who is already a member only clears their entries. Adding resolves the
user by id in the directory with the caller's delegated token, before the write:
a definitive not-found is refused. When the directory is unavailable (no token, no
permission or a transport failure) the submitted name and email are used, as
classic does; that is a known limitation. A role change to the role already held,
and a transfer to the current owner, change nothing and write nothing, so a retry
after a lost response succeeds.

Every response is ``no-store``. Every failure is a stable, data-free message with an
``error_code``.
"""

import logging
import re
from datetime import datetime, timezone

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from functions_activity_logging import log_group_member_deleted
from functions_appinsights import log_event
from functions_chat_bootstrap_cache import bump_chat_bootstrap_global_cache_version
from functions_group import (
    GroupDocumentWriteConflict,
    find_group_by_id,
    get_user_role_in_group,
    update_group_document_with_etag_guard,
)
from functions_group_directory import GroupDirectoryError, read_strict_json_object
from functions_group_membership_audit import (
    log_group_member_role_change,
    notify_group_member_role_change,
)
from functions_group_membership_policy import (
    GROUP_ASSIGNABLE_ROLES,
    GROUP_MEMBERSHIP_HINT_SCHEMA_VERSION,
    GROUP_MEMBERSHIP_MANAGER_ROLES,
    GROUP_MEMBER_ROLES,
    group_member_actions,
    group_member_add_allowed,
    group_membership_operations,
)
from functions_settings import get_settings
from functions_simplechat_operations import (
    _get_directory_user_by_id,
    _log_group_member_addition,
    _notify_group_member_addition,
)


GROUP_MEMBER_LIST_PARAMETERS = ("search", "role", "page", "page_size")
GROUP_MEMBER_LIST_DEFAULT_PAGE_SIZE = 20
GROUP_MEMBER_LIST_MAX_PAGE_SIZE = 100
GROUP_MEMBER_LIST_MAX_PAGE = 10000
GROUP_MEMBER_SEARCH_MAX_LENGTH = 200
GROUP_MEMBER_TEXT_MAX_LENGTH = 256
GROUP_MEMBER_ADD_FIELDS = ("userId", "displayName", "email", "role")

GROUP_ROLE_RANK = {role: rank for rank, role in enumerate(GROUP_MEMBER_ROLES)}
# The role names the classic add writes into its activity record and notifications.
CLASSIC_ADD_ROLES = {"Admin": "admin", "DocumentManager": "document_manager", "User": "user"}

INVALID_MEMBERSHIP_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
MEMBER_TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MEMBERSHIP_WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")

GROUP_NOT_FOUND_MESSAGE = "Group not found."
NOT_A_MEMBER_MESSAGE = "You're not a member of this group."
MEMBERSHIP_PERMISSION_MESSAGE = "Only the group's owner or an admin can manage its members."
OWNER_ONLY_MESSAGE = "Only the group's owner can transfer ownership."
STATUS_UNAVAILABLE_MESSAGE = "Members can't be added to this group in its current status."
MEMBER_NOT_FOUND_MESSAGE = "That person isn't a member of this group."
ALREADY_MEMBER_MESSAGE = "That person is already a member of this group."
NO_PENDING_REQUEST_MESSAGE = "That person doesn't have a pending request to join this group."
OWNER_ROLE_MESSAGE = "Transfer ownership to change the owner's role."
OWNER_REMOVAL_MESSAGE = "Transfer ownership before removing the owner."
OWNER_LEAVE_MESSAGE = "Transfer ownership before leaving the group."
WRITE_CONFLICT_MESSAGE = "The group changed while this change was being saved. Try again."
USER_NOT_FOUND_MESSAGE = "That user wasn't found in the directory."
MEMBERSHIP_UNAVAILABLE_MESSAGE = "The membership request could not be completed. Try again."
MEMBERSHIP_REQUEST_MESSAGE = "The request could not be processed."


class GroupMembershipError(HTTPException):
    """A stable, non-sensitive failure at the group membership boundary.

    ``fields`` are extra, equally safe response members (``error_code``) returned
    beside ``error``.
    """

    def __init__(self, message, status_code, **fields):
        super().__init__(description=message)
        self.code = status_code
        self.fields = fields


class _NoChange(Exception):
    """Raised from a write's change to report that the fresh copy needs no write."""

    def __init__(self, group):
        super().__init__("no change")
        self.group = group


def _error(message, status_code, error_code):
    return GroupMembershipError(message, status_code, error_code=error_code)


def _invalid(message):
    return _error(message, 400, "invalid_request")


def _group_not_found():
    return _error(GROUP_NOT_FOUND_MESSAGE, 404, "group_not_found")


def _member_not_found():
    return _error(MEMBER_NOT_FOUND_MESSAGE, 404, "member_not_found")


def group_membership_error_response(error):
    """Map boundary errors to stable responses; anything else is a logged, generic 500."""
    if isinstance(error, (GroupMembershipError, GroupDirectoryError)):
        payload, status = {"error": error.description, **error.fields}, error.code
    elif isinstance(error, HTTPException) and isinstance(error.code, int) and 400 <= error.code < 500:
        payload, status = {"error": MEMBERSHIP_REQUEST_MESSAGE, "error_code": "invalid_request"}, error.code
    else:
        log_event(
            "[WORKSPACE_ROUTE] Group membership request failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        payload, status = {
            "error": MEMBERSHIP_UNAVAILABLE_MESSAGE,
            "error_code": "group_membership_unavailable",
        }, 500
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


# ---------------------------------------------------------------------------
# Strict request parsing
# ---------------------------------------------------------------------------

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
        if key not in GROUP_MEMBER_LIST_PARAMETERS:
            raise _invalid("Use only the search, role, page and page_size query parameters.")
        if len(arguments.getlist(key)) > 1:
            raise _invalid("Give each query parameter only once.")
    search = arguments.get("search", "").strip()
    if len(search) > GROUP_MEMBER_SEARCH_MAX_LENGTH:
        raise _invalid(f"Search terms can be at most {GROUP_MEMBER_SEARCH_MAX_LENGTH} characters.")
    role = arguments.get("role")
    if role is not None and role not in GROUP_MEMBER_ROLES:
        raise _invalid("The role must be Owner, Admin, DocumentManager or User.")
    page = _whole_number(
        arguments.get("page"),
        default=1,
        maximum=GROUP_MEMBER_LIST_MAX_PAGE,
        message=f"The page must be a whole number from 1 to {GROUP_MEMBER_LIST_MAX_PAGE}.",
    )
    page_size = _whole_number(
        arguments.get("page_size"),
        default=GROUP_MEMBER_LIST_DEFAULT_PAGE_SIZE,
        maximum=GROUP_MEMBER_LIST_MAX_PAGE_SIZE,
        message=f"The page size must be a whole number from 1 to {GROUP_MEMBER_LIST_MAX_PAGE_SIZE}.",
    )
    return {"search": search, "role": role, "page": page, "page_size": page_size}


def _member_text(body, key, label):
    value = body.get(key, "")
    if not isinstance(value, str):
        raise _invalid(f"The {label} must be text.")
    value = value.strip()
    if len(value) > GROUP_MEMBER_TEXT_MAX_LENGTH:
        raise _invalid(f"The {label} can be at most {GROUP_MEMBER_TEXT_MAX_LENGTH} characters.")
    if MEMBER_TEXT_CONTROL_CHARACTERS.search(value):
        raise _invalid(f"The {label} can't contain control characters.")
    return value


def _assignable_role(body):
    role = body.get("role")
    if role not in GROUP_ASSIGNABLE_ROLES:
        raise _invalid("The role must be Admin, DocumentManager or User.")
    return role


def _body_user_id(body):
    user_id = body.get("userId")
    if isinstance(user_id, str):
        user_id = user_id.strip()
    return _identifier(user_id, "user identifier")


def read_add_member_body():
    """Validate an add body, which is exactly ``{userId, displayName?, email?, role}``."""
    body = read_strict_json_object()
    if any(key not in GROUP_MEMBER_ADD_FIELDS for key in body):
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

def _is_group_document(document):
    return isinstance(document, dict) and ("type" not in document or document.get("type") == "group")


def _is_member_entry(entry, user_id):
    return isinstance(entry, dict) and entry.get("userId") == user_id


def _string_ids(values):
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _list_field(group, key):
    value = group.get(key)
    return value if isinstance(value, list) else []


def _group_view(group):
    """The group's owner, roles and members, with malformed entries dropped.

    ``users[]`` keeps the first entry for each ``userId``. The classic role
    predicate gives the same answer on this copy for every well-formed member.
    """
    owner = group.get("owner") if isinstance(group.get("owner"), dict) else {}
    owner_id = owner.get("id") if isinstance(owner.get("id"), str) and owner.get("id") else None
    users, seen = [], set()
    for entry in _list_field(group, "users"):
        user_id = entry.get("userId") if isinstance(entry, dict) else None
        if isinstance(user_id, str) and user_id and user_id not in seen:
            seen.add(user_id)
            users.append(entry)
    return {
        "owner": {"id": owner_id, "displayName": owner.get("displayName"), "email": owner.get("email")},
        "admins": _string_ids(group.get("admins")),
        "documentManagers": _string_ids(group.get("documentManagers")),
        "users": users,
    }


def _role_of(view, user_id):
    return get_user_role_in_group(view, user_id) if user_id else None


def _text(value):
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _member_entries(view):
    entries = list(view["users"])
    owner_id = view["owner"]["id"]
    if owner_id and not any(entry["userId"] == owner_id for entry in entries):
        entries.append({
            "userId": owner_id,
            "displayName": view["owner"]["displayName"],
            "email": view["owner"]["email"],
        })
    return entries


def _member_row(view, entry, caller_id, caller_role):
    member_id = entry["userId"]
    role = _role_of(view, member_id)
    return {
        "userId": member_id,
        "displayName": _text(entry.get("displayName")),
        "email": _text(entry.get("email")),
        "role": role,
        "member_actions": group_member_actions(caller_role, role, is_self=member_id == caller_id),
    }


def _row_for(group, member_id, caller_id):
    view = _group_view(group)
    caller_role = _role_of(view, caller_id)
    for entry in _member_entries(view):
        if entry["userId"] == member_id:
            return _member_row(view, entry, caller_id, caller_role)
    return None


def _member_sort_key(row):
    return (GROUP_ROLE_RANK.get(row["role"], len(GROUP_ROLE_RANK)), row["displayName"].casefold(), row["userId"])


def _matches_search(row, needle):
    return (
        needle in row["displayName"].casefold()
        or needle in row["email"].casefold()
        or needle == row["userId"].casefold()
    )


# ---------------------------------------------------------------------------
# Authorization and writes
# ---------------------------------------------------------------------------

def _load_group(group_id):
    group = find_group_by_id(group_id)
    if not _is_group_document(group):
        raise _group_not_found()
    return group


def _caller_role(view, caller_id):
    role = _role_of(view, caller_id)
    if role is None:
        raise _error(NOT_A_MEMBER_MESSAGE, 403, "not_a_member")
    return role


def _manager_role(view, caller_id):
    role = _caller_role(view, caller_id)
    if role not in GROUP_MEMBERSHIP_MANAGER_ROLES:
        raise _error(MEMBERSHIP_PERMISSION_MESSAGE, 403, "membership_permission")
    return role


def _stored_timestamp():
    """The ``modifiedDate`` format the classic group writers store."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _remove_id(group, key, user_id):
    values = group.get(key)
    if isinstance(values, list) and user_id in values:
        group[key] = [value for value in values if value != user_id]


def _append_id(group, key, user_id):
    values = _list_field(group, key)
    if user_id not in values:
        group[key] = [*values, user_id]


def _pending_entries(group):
    return _list_field(group, "pendingUsers")


def _clear_pending(group, user_id):
    pending = _pending_entries(group)
    if any(_is_member_entry(entry, user_id) for entry in pending):
        group["pendingUsers"] = [entry for entry in pending if not _is_member_entry(entry, user_id)]


def _write(group_id, apply_changes, *, cache_reason):
    def guarded(group):
        if not _is_group_document(group):
            raise _group_not_found()
        return apply_changes(group)

    try:
        committed = update_group_document_with_etag_guard(group_id, guarded, cache_reason=cache_reason)
    except GroupDocumentWriteConflict as error:
        raise _error(WRITE_CONFLICT_MESSAGE, 409, "group_write_conflict") from error
    if committed is None:
        raise _group_not_found()
    return committed


def _classic_member_details(group, member_id):
    """The name and email the classic role route reads for its audit record."""
    for entry in _list_field(group, "users"):
        if isinstance(entry, dict) and entry.get("userId") == member_id:
            return entry.get("displayName", "Unknown"), entry.get("email", "unknown")
    return "Unknown", "unknown"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_group_members(user_id, group_id, *, search, role, page, page_size):
    """Return ``(payload, 200)`` with one page of the group's members."""
    caller_id = _require_user_id(user_id)
    _identifier(group_id, "group identifier")
    group = _load_group(group_id)
    view = _group_view(group)
    caller_role = _caller_role(view, caller_id)
    needle = search.casefold()
    rows = [
        row for row in (_member_row(view, entry, caller_id, caller_role) for entry in _member_entries(view))
        if (role is None or row["role"] == role) and (not needle or _matches_search(row, needle))
    ]
    rows.sort(key=_member_sort_key)
    start = (page - 1) * page_size
    return {
        "members": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total_count": len(rows),
        "membership_management": {
            "schema_version": GROUP_MEMBERSHIP_HINT_SCHEMA_VERSION,
            "operations": group_membership_operations(caller_role, group, get_settings()),
        },
    }, 200


def list_group_join_requests(user_id, group_id):
    """Return ``(payload, 200)`` with the pending requests, for the Owner and Admins."""
    caller_id = _require_user_id(user_id)
    _identifier(group_id, "group identifier")
    group = _load_group(group_id)
    _manager_role(_group_view(group), caller_id)
    rows, seen = [], set()
    for entry in _pending_entries(group):
        pending_id = entry.get("userId") if isinstance(entry, dict) else None
        if isinstance(pending_id, str) and pending_id and pending_id not in seen:
            seen.add(pending_id)
            rows.append({
                "userId": pending_id,
                "displayName": _text(entry.get("displayName")),
                "email": _text(entry.get("email")),
            })
    rows.sort(key=lambda row: (row["displayName"].casefold(), row["userId"]))
    return {"requests": rows, "total_count": len(rows)}, 200


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _resolve_directory_member(fields):
    """Resolve the member by id in the directory, outside the write.

    A definitive not-found is refused. When the directory can't answer, the
    submitted name and email are used, as the classic add does.
    """
    requested_id = fields["user_id"]
    try:
        directory_user = _get_directory_user_by_id(requested_id)
    except Exception as error:  # noqa: BLE001 - no token, no permission or a transport failure
        log_event(
            "[WORKSPACE_ROUTE] Group member directory lookup was unavailable; the submitted details were used.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        email = fields["email"]
        return {"userId": requested_id, "email": email, "displayName": fields["display_name"] or email or requested_id}
    if not directory_user:
        raise _error(USER_NOT_FOUND_MESSAGE, 400, "user_not_found")
    member_id = str(directory_user.get("id") or "").strip() or requested_id
    email = str(directory_user.get("email") or "")
    return {"userId": member_id, "email": email, "displayName": directory_user.get("displayName") or email or member_id}


def add_group_member(user_info, group_id):
    """Add a member and return ``({"member": row}, 201)``."""
    actor_id = _actor_id(user_info)
    _identifier(group_id, "group identifier")
    fields = read_add_member_body()
    group = _load_group(group_id)
    view = _group_view(group)
    _manager_role(view, actor_id)
    if not group_member_add_allowed(group):
        raise _error(STATUS_UNAVAILABLE_MESSAGE, 403, "group_status_unavailable")
    member = _resolve_directory_member(fields)
    member_id = member["userId"]
    if _role_of(view, member_id):
        raise _error(ALREADY_MEMBER_MESSAGE, 409, "already_member")
    new_role = fields["role"]

    def apply(fresh):
        fresh_view = _group_view(fresh)
        _manager_role(fresh_view, actor_id)
        if not group_member_add_allowed(fresh):
            raise _error(STATUS_UNAVAILABLE_MESSAGE, 403, "group_status_unavailable")
        if _role_of(fresh_view, member_id):
            raise _error(ALREADY_MEMBER_MESSAGE, 409, "already_member")
        fresh["users"] = [*_list_field(fresh, "users"), dict(member)]
        if new_role == "Admin":
            _append_id(fresh, "admins", member_id)
        elif new_role == "DocumentManager":
            _append_id(fresh, "documentManagers", member_id)
        _clear_pending(fresh, member_id)
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    committed = _write(group_id, apply, cache_reason="group_member_added")
    classic_role = CLASSIC_ADD_ROLES[new_role]
    _log_group_member_addition(
        actor_user=user_info,
        actor_role=_role_of(_group_view(committed), actor_id),
        group_doc=committed,
        member_doc=member,
        member_role=classic_role,
    )
    _notify_group_member_addition(
        group_doc=committed,
        member_doc=member,
        member_role=classic_role,
        added_by_email=user_info.get("email", "unknown"),
        actor_user=user_info,
    )
    return {"member": _row_for(committed, member_id, actor_id)}, 201


def change_group_member_role(user_info, group_id, member_id):
    """Change a member's role and return ``({"member": row, "changed": bool}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(group_id, "group identifier")
    _identifier(member_id, "user identifier")
    new_role = read_role_body()
    audit = {}

    def apply(fresh):
        view = _group_view(fresh)
        caller_role = _manager_role(view, actor_id)
        target_role = _role_of(view, member_id)
        if target_role is None:
            raise _member_not_found()
        if target_role == "Owner":
            raise _error(OWNER_ROLE_MESSAGE, 409, "owner_target")
        if target_role == new_role:
            raise _NoChange(fresh)
        _remove_id(fresh, "admins", member_id)
        _remove_id(fresh, "documentManagers", member_id)
        if new_role == "Admin":
            _append_id(fresh, "admins", member_id)
        elif new_role == "DocumentManager":
            _append_id(fresh, "documentManagers", member_id)
        fresh["modifiedDate"] = _stored_timestamp()
        audit.update(caller_role=caller_role, old_role=target_role)
        return fresh

    try:
        committed = _write(group_id, apply, cache_reason="group_member_role_updated")
    except _NoChange as unchanged:
        return {"member": _row_for(unchanged.group, member_id, actor_id), "changed": False}, 200
    member_name, member_email = _classic_member_details(committed, member_id)
    changed_by_email = user_info.get("email", "unknown")
    log_group_member_role_change(
        group_id=group_id,
        group_doc=committed,
        changed_by_user_id=actor_id,
        changed_by_email=changed_by_email,
        changed_by_role=audit["caller_role"],
        member_id=member_id,
        member_email=member_email,
        member_name=member_name,
        old_role=audit["old_role"],
        new_role=new_role,
    )
    notify_group_member_role_change(
        group_id=group_id,
        group_doc=committed,
        member_id=member_id,
        changed_by_email=changed_by_email,
        old_role=audit["old_role"],
        new_role=new_role,
    )
    return {"member": _row_for(committed, member_id, actor_id), "changed": True}, 200


def remove_group_member(user_info, group_id, member_id):
    """Remove a member, or leave, and return ``({"userId", "left"}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(group_id, "group identifier")
    _identifier(member_id, "user identifier")
    leaving = member_id == actor_id
    audit = {}

    def apply(fresh):
        view = _group_view(fresh)
        caller_role = _caller_role(view, actor_id)
        if leaving:
            if caller_role == "Owner":
                raise _error(OWNER_LEAVE_MESSAGE, 409, "owner_cannot_leave")
        else:
            if caller_role not in GROUP_MEMBERSHIP_MANAGER_ROLES:
                raise _error(MEMBERSHIP_PERMISSION_MESSAGE, 403, "membership_permission")
            target_role = _role_of(view, member_id)
            if target_role is None:
                raise _member_not_found()
            if target_role == "Owner":
                raise _error(OWNER_REMOVAL_MESSAGE, 409, "owner_target")
        users = _list_field(fresh, "users")
        removed = [entry for entry in users if _is_member_entry(entry, member_id)]
        if removed:
            fresh["users"] = [entry for entry in users if not _is_member_entry(entry, member_id)]
        _remove_id(fresh, "admins", member_id)
        _remove_id(fresh, "documentManagers", member_id)
        fresh["modifiedDate"] = _stored_timestamp()
        audit.update(caller_role=caller_role, removed_entry=removed[0] if removed else None)
        return fresh

    committed = _write(group_id, apply, cache_reason=None)
    removed_entry = audit.get("removed_entry")
    if removed_entry is not None:
        bump_chat_bootstrap_global_cache_version(reason="group_member_removed")
        actor_email = user_info.get("email", "unknown")
        member_name = removed_entry.get("displayName", "")
        member_email = removed_entry.get("email", "")
        group_label = committed.get("name", group_id)
        if leaving:
            removed_by_role, action = "Member", "member_left_group"
            description = f"Member {actor_email} left group {group_label}"
        else:
            removed_by_role, action = audit["caller_role"], "admin_removed_member"
            description = (
                f"{removed_by_role} {actor_email} removed member {member_name} ({member_email}) "
                f"from group {group_label}"
            )
        log_group_member_deleted(
            removed_by_user_id=actor_id,
            removed_by_email=actor_email,
            removed_by_role=removed_by_role,
            member_user_id=member_id,
            member_email=member_email,
            member_name=member_name,
            group_id=group_id,
            group_name=committed.get("name", "Unknown"),
            action=action,
            description=description,
        )
    return {"userId": member_id, "left": leaving}, 200


def approve_join_request(user_info, group_id, member_id):
    """Approve a pending request and return ``({"member": row, "already_member": bool}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(group_id, "group identifier")
    _identifier(member_id, "user identifier")
    audit = {}

    def apply(fresh):
        view = _group_view(fresh)
        _manager_role(view, actor_id)
        entries = [entry for entry in _pending_entries(fresh) if _is_member_entry(entry, member_id)]
        if not entries:
            raise _error(NO_PENDING_REQUEST_MESSAGE, 409, "no_pending_request")
        _clear_pending(fresh, member_id)
        already_member = _role_of(view, member_id) is not None
        if not already_member:
            first = entries[0]
            fresh["users"] = [
                *_list_field(fresh, "users"),
                {"userId": member_id, "email": first.get("email"), "displayName": first.get("displayName")},
            ]
        fresh["modifiedDate"] = _stored_timestamp()
        audit["already_member"] = already_member
        return fresh

    committed = _write(group_id, apply, cache_reason="group_member_request_approved")
    return {
        "member": _row_for(committed, member_id, actor_id),
        "already_member": audit["already_member"],
    }, 200


def reject_join_request(user_info, group_id, member_id):
    """Reject a pending request and return ``({"userId": ...}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(group_id, "group identifier")
    _identifier(member_id, "user identifier")

    def apply(fresh):
        _manager_role(_group_view(fresh), actor_id)
        if not any(_is_member_entry(entry, member_id) for entry in _pending_entries(fresh)):
            raise _error(NO_PENDING_REQUEST_MESSAGE, 409, "no_pending_request")
        _clear_pending(fresh, member_id)
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    _write(group_id, apply, cache_reason=None)
    return {"userId": member_id}, 200


def transfer_group_ownership(user_info, group_id):
    """Make another member the owner and return ``({"owner": row, "changed": bool}, 200)``."""
    actor_id = _actor_id(user_info)
    _identifier(group_id, "group identifier")
    new_owner_id = read_owner_body()

    def apply(fresh):
        view = _group_view(fresh)
        caller_role = _caller_role(view, actor_id)
        if view["owner"]["id"] == new_owner_id:
            raise _NoChange(fresh)
        if caller_role != "Owner":
            raise _error(OWNER_ONLY_MESSAGE, 403, "owner_only")
        target = next((entry for entry in view["users"] if entry["userId"] == new_owner_id), None)
        if target is None:
            raise _member_not_found()
        previous = fresh.get("owner") if isinstance(fresh.get("owner"), dict) else {}
        previous_id = view["owner"]["id"]
        fresh["owner"] = {
            "id": new_owner_id,
            "email": target.get("email", ""),
            "displayName": target.get("displayName", ""),
        }
        _remove_id(fresh, "admins", new_owner_id)
        _remove_id(fresh, "documentManagers", new_owner_id)
        if not any(entry["userId"] == previous_id for entry in view["users"]):
            fresh["users"] = [
                *_list_field(fresh, "users"),
                {
                    "userId": previous_id,
                    "email": previous.get("email", ""),
                    "displayName": previous.get("displayName", ""),
                },
            ]
        _remove_id(fresh, "admins", previous_id)
        _remove_id(fresh, "documentManagers", previous_id)
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    try:
        committed = _write(group_id, apply, cache_reason="group_ownership_transferred")
    except _NoChange as unchanged:
        return {"owner": _row_for(unchanged.group, new_owner_id, actor_id), "changed": False}, 200
    return {"owner": _row_for(committed, new_owner_id, actor_id), "changed": True}, 200
