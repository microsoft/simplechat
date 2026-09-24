# functions_group_directory.py
"""The native group directory: finding groups, creating one, and asking to join.

This backs ``GET``/``POST /api/groups/directory`` and ``POST``/``DELETE
/api/groups/<group_id>/join-request``. The classic ``/api/groups/discover``,
``POST /api/groups`` and ``POST /api/groups/<group_id>/requests`` are unchanged.

Listing
-------
Discovery is open to every authenticated user, as the classic Find Group flow is:
anyone may see every group's name, description, owner display name and member
count. The directory never returns the owner's email or id, or any member's entry,
to anyone, members included.

One cross-partition query reads a narrow projection of every group, with the admin
directory's type filter so untyped legacy groups are included. The membership
arrays are reduced on the server to the caller's own entries, so a row costs the
same however many members the group has and no other member's entry leaves the
database. The classic predicates then run in Python on that reduced copy, which is
role-equivalent for the caller: ``get_user_role_in_group``, the predicate the join
route and the logo route use, and ``has_pending_join_request``. Membership is
``member`` whenever the caller holds a role, even if a stale pending entry remains,
then ``pending``, then ``none``; a member row also carries ``userRole``.

``view`` is ``all``, ``mine`` (the caller is a member) or ``discover`` (the caller
is pending or not a member). ``search`` is stripped and casefolded, and matches a
substring of the name or the description, or the exact group id. Rows are sorted by
casefolded name and then id in Python, because an ``ORDER BY`` would drop groups
saved without a name, and the page is cut after filtering and sorting, so
``total_count`` counts the rows of the requested view.

``hasLogo`` means the caller can load the logo: a logo is stored (a non-blank
string, as the logo upload writes) and the caller is a member, because
``GET /api/groups/<group_id>/logo`` serves members only.

Writes
------
Creating a group reuses ``create_group_for_current_user``, so the creator's
notification and the chat bootstrap cache bump are the classic ones, and the new
group is not made the caller's active group. The only creation gate on the native
route is ``group_creation_refusal``, the decision the directory's ``can_create``
hint reports.

A join request and its cancellation change ``pendingUsers`` through
``update_group_document_with_etag_guard``. A concurrent change to the group is
re-read and kept, the membership rules are re-checked on every attempt, and a group
deleted mid-request is reported as missing and never recreated. The pending entry
keeps the classic ``{userId, email, displayName}`` shape that the manage page and
the approve route read, and cancelling removes every entry carrying the caller's id,
including a stale one left behind for someone who has since become a member. As
with the classic request route, neither write notifies anyone, records an activity
event or bumps the chat bootstrap cache (no bootstrap payload reads pending
requests), and every group status accepts both.

The classic membership writers still upsert the whole group document, so one of
them landing after a native join or cancel can undo it. Converting them is M7B.

Every response is ``no-store``. Every failure is a stable, data-free message with an
``error_code``.
"""

import json
import logging
import re
from datetime import datetime, timezone

from flask import jsonify, request, session
from werkzeug.exceptions import HTTPException

from config import cosmos_groups_container
from functions_appinsights import log_event
from functions_group import (
    GROUP_DIRECTORY_TYPE_FILTER,
    GroupDocumentWriteConflict,
    get_user_role_in_group,
    update_group_document_with_etag_guard,
)
from functions_group_directory_policy import (
    GROUP_CREATION_ROLE_REQUIRED,
    build_group_directory_hints,
    group_creation_refusal,
)
from functions_settings import get_settings
from functions_simplechat_operations import create_group_for_current_user
from functions_workspace_branding import (
    DEFAULT_WORKSPACE_HERO_COLOR,
    get_workspace_logo_metadata,
    normalize_workspace_hero_color,
)


GROUP_DIRECTORY_VIEWS = ("all", "mine", "discover")
GROUP_DIRECTORY_QUERY_PARAMETERS = ("search", "view", "page", "page_size")
GROUP_DIRECTORY_DEFAULT_PAGE_SIZE = 20
GROUP_DIRECTORY_MAX_PAGE_SIZE = 100
GROUP_DIRECTORY_MAX_PAGE = 10000
GROUP_DIRECTORY_SEARCH_MAX_LENGTH = 200

# The classic create form's limit on the name. Nothing limited the description
# before; 500 is the reviewed native limit.
GROUP_NAME_MAX_LENGTH = 80
GROUP_DESCRIPTION_MAX_LENGTH = 500
GROUP_CREATE_FIELDS = ("name", "description")

MEMBERSHIP_MEMBER = "member"
MEMBERSHIP_PENDING = "pending"
MEMBERSHIP_NONE = "none"

INVALID_GROUP_DIRECTORY_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
GROUP_NAME_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
DIRECTORY_WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")

# Reduced to the caller on the server: the caller's own users[] and pendingUsers[]
# entries, and the caller's id wherever it appears among the admins and document
# managers. The owner's id is read only to decide the caller's role and is never
# returned.
GROUP_DIRECTORY_QUERY = (
    "SELECT c.id, c.name, c.description, "
    "c.owner.id AS ownerId, c.owner.displayName AS ownerDisplayName, "
    "c.heroColor, c.logoVersion, "
    "(IS_STRING(c.logoBase64) AND LENGTH(TRIM(c.logoBase64)) > 0) AS logoPresent, "
    "ARRAY_LENGTH(c.users) AS memberCount, "
    "ARRAY(SELECT VALUE u FROM u IN c.users WHERE u.userId = @user_id) AS callerUsers, "
    "ARRAY(SELECT VALUE a FROM a IN c.admins WHERE a = @user_id) AS callerAdmins, "
    "ARRAY(SELECT VALUE m FROM m IN c.documentManagers WHERE m = @user_id) AS callerDocumentManagers, "
    "ARRAY(SELECT VALUE p FROM p IN c.pendingUsers WHERE p.userId = @user_id) AS callerPendingUsers "
    f"FROM c WHERE {GROUP_DIRECTORY_TYPE_FILTER}"
)

GROUP_NOT_FOUND_MESSAGE = "Group not found."
GROUP_WRITE_CONFLICT_MESSAGE = "The group changed while your request was being saved. Try again."
GROUP_ALREADY_MEMBER_MESSAGE = "You're already a member of this group."
GROUP_REQUEST_PENDING_MESSAGE = "You've already asked to join this group."
GROUP_NO_PENDING_REQUEST_MESSAGE = "You don't have a pending request to join this group."
GROUP_CREATION_DISABLED_MESSAGE = "Group creation is turned off."
GROUP_CREATION_ROLE_REQUIRED_MESSAGE = "You need the CreateGroups role to create groups."
GROUP_CREATION_UNAVAILABLE_MESSAGE = "Group creation isn't available right now."
GROUP_CREATE_FAILED_MESSAGE = "The group could not be created. Try again."
GROUP_DIRECTORY_UNAVAILABLE_MESSAGE = "The group directory request could not be completed. Try again."
GROUP_DIRECTORY_REQUEST_MESSAGE = "The request could not be processed."


class GroupDirectoryError(HTTPException):
    """A stable, non-sensitive failure at the group directory boundary.

    ``fields`` are extra, equally safe response members (``error_code``) returned
    beside ``error``.
    """

    def __init__(self, message, status_code, **fields):
        super().__init__(description=message)
        self.code = status_code
        self.fields = fields


def _invalid_request(message):
    return GroupDirectoryError(message, 400, error_code="invalid_request")


def _group_not_found():
    return GroupDirectoryError(GROUP_NOT_FOUND_MESSAGE, 404, error_code="group_not_found")


def group_directory_error_response(error):
    """Map boundary errors to stable responses; anything else is a logged, generic 500."""
    if isinstance(error, GroupDirectoryError):
        payload, status = {"error": error.description, **error.fields}, error.code
    elif isinstance(error, HTTPException) and isinstance(error.code, int) and 400 <= error.code < 500:
        payload, status = {"error": GROUP_DIRECTORY_REQUEST_MESSAGE, "error_code": "invalid_request"}, error.code
    else:
        log_event(
            "[WORKSPACE_ROUTE] Group directory request failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        payload, status = {
            "error": GROUP_DIRECTORY_UNAVAILABLE_MESSAGE,
            "error_code": "group_directory_unavailable",
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
        raise _invalid_request("This request does not accept query parameters.")


def reject_request_body():
    if request.get_data():
        raise _invalid_request("This request does not accept a request body.")


def read_strict_json_object():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second
    value cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise _invalid_request("Duplicate fields are not supported.")
            payload[key] = value
        return payload

    if not request.is_json:
        raise _invalid_request("A JSON object is required for this request.")
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid_request("Provide valid JSON with no duplicate fields.") from error
    if not isinstance(body, dict):
        raise _invalid_request("A JSON object is required for this request.")
    return body


def _whole_number(value, *, default, maximum, message):
    if value is None:
        return default
    if not DIRECTORY_WHOLE_NUMBER.fullmatch(value) or int(value) > maximum:
        raise _invalid_request(message)
    return int(value)


def read_group_directory_query():
    """Read ``search``, ``view``, ``page`` and ``page_size``; anything else is a 400."""
    arguments = request.args
    for key in arguments.keys():
        if key not in GROUP_DIRECTORY_QUERY_PARAMETERS:
            raise _invalid_request("Use only the search, view, page and page_size query parameters.")
        if len(arguments.getlist(key)) > 1:
            raise _invalid_request("Give each query parameter only once.")
    view = arguments.get("view", "all")
    if view not in GROUP_DIRECTORY_VIEWS:
        raise _invalid_request("The view must be all, mine or discover.")
    search = arguments.get("search", "").strip()
    if len(search) > GROUP_DIRECTORY_SEARCH_MAX_LENGTH:
        raise _invalid_request(
            f"Search terms can be at most {GROUP_DIRECTORY_SEARCH_MAX_LENGTH} characters."
        )
    page = _whole_number(
        arguments.get("page"),
        default=1,
        maximum=GROUP_DIRECTORY_MAX_PAGE,
        message=f"The page must be a whole number from 1 to {GROUP_DIRECTORY_MAX_PAGE}.",
    )
    page_size = _whole_number(
        arguments.get("page_size"),
        default=GROUP_DIRECTORY_DEFAULT_PAGE_SIZE,
        maximum=GROUP_DIRECTORY_MAX_PAGE_SIZE,
        message=f"The page size must be a whole number from 1 to {GROUP_DIRECTORY_MAX_PAGE_SIZE}.",
    )
    return {"view": view, "search": search, "page": page, "page_size": page_size}


def validate_group_name(name):
    """Return a group name stripped, or raise its reviewed 400.

    Shared by group creation here and by the native group settings rename.
    """
    if name is None or (isinstance(name, str) and not name.strip()):
        raise _invalid_request("Enter a group name.")
    if not isinstance(name, str):
        raise _invalid_request("The group name must be text.")
    name = name.strip()
    if len(name) > GROUP_NAME_MAX_LENGTH:
        raise _invalid_request(f"Group names can be at most {GROUP_NAME_MAX_LENGTH} characters.")
    if GROUP_NAME_CONTROL_CHARACTERS.search(name):
        raise _invalid_request("Group names cannot contain control characters.")
    return name


def validate_group_description(description):
    """Return a group description stripped, or raise its reviewed 400."""
    if not isinstance(description, str):
        raise _invalid_request("The group description must be text.")
    description = description.strip()
    if len(description) > GROUP_DESCRIPTION_MAX_LENGTH:
        raise _invalid_request(
            f"Group descriptions can be at most {GROUP_DESCRIPTION_MAX_LENGTH} characters."
        )
    return description


def read_group_creation_fields(body):
    """Validate a create body, which is exactly ``{name, description?}``."""
    if any(key not in GROUP_CREATE_FIELDS for key in body):
        raise _invalid_request("Only a name and a description can be set when creating a group.")
    name = validate_group_name(body.get("name"))
    description = validate_group_description(body.get("description", ""))
    return name, description


def _require_group_id(group_id):
    if (
        not isinstance(group_id, str) or not group_id or len(group_id) > 512
        or group_id != group_id.strip() or group_id in (".", "..")
        or INVALID_GROUP_DIRECTORY_ID.search(group_id)
    ):
        raise _invalid_request("Invalid group identifier.")


def _require_user_id(user_id):
    if not isinstance(user_id, str) or not user_id:
        raise GroupDirectoryError("User not authenticated.", 401, error_code="not_authenticated")
    return user_id


def current_session_roles():
    """The session's app roles as stored; the policy decides what counts as a role."""
    user = session.get("user")
    return user.get("roles") if isinstance(user, dict) else None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _is_directory_group(group):
    """The admin directory's type filter: typed ``group`` documents and untyped ones."""
    return "type" not in group or group.get("type") == "group"


def _is_caller_entry(entry, user_id):
    return isinstance(entry, dict) and entry.get("userId") == user_id


def _caller_entries(entries, user_id):
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if _is_caller_entry(entry, user_id)]


def _caller_ids(entries, user_id):
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, str) and entry == user_id]


def has_pending_join_request(group, user_id):
    """Whether the group's ``pendingUsers`` holds an entry for ``user_id``."""
    return bool(_caller_entries((group or {}).get("pendingUsers"), user_id))


def _group_record(group, user_id):
    """The row ``GROUP_DIRECTORY_QUERY`` returns for one whole group document."""
    owner = group.get("owner") if isinstance(group.get("owner"), dict) else {}
    logo = group.get("logoBase64")
    users = group.get("users")
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "description": group.get("description"),
        "ownerId": owner.get("id"),
        "ownerDisplayName": owner.get("displayName"),
        "heroColor": group.get("heroColor"),
        "logoVersion": group.get("logoVersion"),
        "logoPresent": isinstance(logo, str) and bool(logo.strip()),
        "memberCount": len(users) if isinstance(users, list) else None,
        "callerUsers": _caller_entries(users, user_id),
        "callerAdmins": _caller_ids(group.get("admins"), user_id),
        "callerDocumentManagers": _caller_ids(group.get("documentManagers"), user_id),
        "callerPendingUsers": _caller_entries(group.get("pendingUsers"), user_id),
    }


def _caller_membership(record, user_id):
    """Return ``(membership, role)`` from a record, using the classic predicates."""
    caller_view = {
        "owner": {"id": record.get("ownerId")},
        "admins": _caller_ids(record.get("callerAdmins"), user_id),
        "documentManagers": _caller_ids(record.get("callerDocumentManagers"), user_id),
        "users": _caller_entries(record.get("callerUsers"), user_id),
        "pendingUsers": _caller_entries(record.get("callerPendingUsers"), user_id),
    }
    role = get_user_role_in_group(caller_view, user_id)
    if role:
        return MEMBERSHIP_MEMBER, role
    if has_pending_join_request(caller_view, user_id):
        return MEMBERSHIP_PENDING, None
    return MEMBERSHIP_NONE, None


def _text(value):
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _count(value):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _directory_row(record, user_id):
    membership, role = _caller_membership(record, user_id)
    row = {
        "id": _text(record.get("id")),
        "name": _text(record.get("name")),
        "description": _text(record.get("description")),
        "owner": {"displayName": _text(record.get("ownerDisplayName"))},
        "member_count": _count(record.get("memberCount")),
        "heroColor": normalize_workspace_hero_color(record.get("heroColor"), DEFAULT_WORKSPACE_HERO_COLOR),
        "hasLogo": record.get("logoPresent") is True and membership == MEMBERSHIP_MEMBER,
        "logoVersion": get_workspace_logo_metadata({"logoVersion": record.get("logoVersion")})["logoVersion"],
        "membership": membership,
    }
    if role:
        row["userRole"] = role
    return row


def build_group_directory_row(group, user_id):
    """Project one whole group document for the caller, as the directory lists it."""
    return _directory_row(_group_record(group, user_id), user_id)


def _matches_search(row, needle):
    return (
        needle in row["name"].casefold()
        or needle in row["description"].casefold()
        or needle == row["id"].casefold()
    )


def _in_view(row, view):
    if view == "mine":
        return row["membership"] == MEMBERSHIP_MEMBER
    if view == "discover":
        return row["membership"] != MEMBERSHIP_MEMBER
    return True


def list_group_directory(user_id, *, view, search, page, page_size):
    """Return ``(payload, 200)`` with one page of the directory for the caller."""
    user_id = _require_user_id(user_id)
    records = cosmos_groups_container.query_items(
        query=GROUP_DIRECTORY_QUERY,
        parameters=[{"name": "@user_id", "value": user_id}],
        enable_cross_partition_query=True,
    )
    needle = search.casefold()
    rows = []
    for record in records:
        row = _directory_row(record, user_id)
        if _in_view(row, view) and (not needle or _matches_search(row, needle)):
            rows.append(row)
    rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
    start = (page - 1) * page_size
    return {
        "groups": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total_count": len(rows),
        "group_directory": build_group_directory_hints(get_settings(), current_session_roles()),
    }, 200


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _stored_timestamp():
    """The ``modifiedDate`` format the classic group writers store."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def create_directory_group(user_id):
    """Create a group owned by the caller and return ``({"group": row}, 201)``."""
    user_id = _require_user_id(user_id)
    refusal = group_creation_refusal(get_settings(), current_session_roles())
    if refusal == GROUP_CREATION_ROLE_REQUIRED:
        raise GroupDirectoryError(
            GROUP_CREATION_ROLE_REQUIRED_MESSAGE, 403, error_code="create_groups_role_required",
        )
    if refusal is not None:
        raise GroupDirectoryError(GROUP_CREATION_DISABLED_MESSAGE, 403, error_code="group_creation_disabled")
    name, description = read_group_creation_fields(read_strict_json_object())
    try:
        group = create_group_for_current_user(name, description)
    except PermissionError as error:
        raise GroupDirectoryError(
            GROUP_CREATION_UNAVAILABLE_MESSAGE, 403, error_code="group_creation_unavailable",
        ) from error
    except Exception as error:
        log_event(
            "[WORKSPACE_ROUTE] Group directory create failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        raise GroupDirectoryError(GROUP_CREATE_FAILED_MESSAGE, 500, error_code="group_create_failed") from error
    return {"group": build_group_directory_row(group, user_id)}, 201


def _write_group(group_id, apply_changes):
    try:
        committed = update_group_document_with_etag_guard(group_id, apply_changes, cache_reason=None)
    except GroupDocumentWriteConflict as error:
        raise GroupDirectoryError(GROUP_WRITE_CONFLICT_MESSAGE, 409, error_code="group_write_conflict") from error
    if committed is None:
        raise _group_not_found()
    return committed


def request_to_join_group(user_info, group_id):
    """Add the caller's pending request and return ``({"group": row}, 201)``."""
    user_info = user_info if isinstance(user_info, dict) else {}
    user_id = _require_user_id(user_info.get("userId"))
    _require_group_id(group_id)
    entry = {
        "userId": user_id,
        "email": user_info.get("email"),
        "displayName": user_info.get("displayName"),
    }

    def apply(group):
        if not _is_directory_group(group):
            raise _group_not_found()
        membership, _role = _caller_membership(_group_record(group, user_id), user_id)
        if membership == MEMBERSHIP_MEMBER:
            raise GroupDirectoryError(GROUP_ALREADY_MEMBER_MESSAGE, 409, error_code="already_member")
        if membership == MEMBERSHIP_PENDING:
            raise GroupDirectoryError(GROUP_REQUEST_PENDING_MESSAGE, 409, error_code="request_pending")
        pending = group.get("pendingUsers")
        group["pendingUsers"] = [*(pending if isinstance(pending, list) else []), dict(entry)]
        group["modifiedDate"] = _stored_timestamp()
        return group

    return {"group": build_group_directory_row(_write_group(group_id, apply), user_id)}, 201


def cancel_group_join_request(user_id, group_id):
    """Remove the caller's pending request and return ``({"group": row}, 200)``."""
    user_id = _require_user_id(user_id)
    _require_group_id(group_id)

    def apply(group):
        if not _is_directory_group(group):
            raise _group_not_found()
        pending = group.get("pendingUsers")
        pending = pending if isinstance(pending, list) else []
        remaining = [entry for entry in pending if not _is_caller_entry(entry, user_id)]
        if len(remaining) == len(pending):
            raise GroupDirectoryError(GROUP_NO_PENDING_REQUEST_MESSAGE, 409, error_code="no_pending_request")
        group["pendingUsers"] = remaining
        group["modifiedDate"] = _stored_timestamp()
        return group

    return {"group": build_group_directory_row(_write_group(group_id, apply), user_id)}, 200
