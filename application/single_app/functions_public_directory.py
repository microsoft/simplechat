# functions_public_directory.py
"""The native public workspace directory: discovering public workspaces read-only.

This backs ``GET /api/public_workspaces/directory``. The classic
``GET /api/public_workspaces`` and ``GET /api/public_workspaces/discover`` are
unchanged, and stay for the classic pages. ``/api/public_workspaces/directory``
shares its shape with the classic ``GET /api/public_workspaces/<ws_id>``: a static
segment outranks a converter, so ``directory`` reaches this route on a server that
has it, and reaches the classic details route (which then answers 404, since no
workspace has the id ``directory``) on one that does not.

Listing
-------
Discovery is open to every authenticated user, as the classic public directory is:
anyone may see every public workspace's name, description and branding. Unlike the
classic ``GET /api/public_workspaces``, the directory never returns the owner's
email or id (decision 22), any member's entry, the file-download flags, or the
stored active-workspace preference. A row carries only what a reader may see: the
name, the description, the hero colour, the logo metadata, and the caller's own
role and the workspace's status.

One cross-partition query reads a narrow projection of every public workspace. The
``admins`` and ``documentManagers`` arrays are reduced on the server to the caller's
own entries, so no other member's id leaves the database, and the caller's role is
resolved from that reduced copy with ``get_user_role_in_public_workspace``, the same
predicate the read routes use, which handles the old string and new dict member
formats. ``membership`` is ``member`` when the caller holds a stored role (Owner,
Admin or DocumentManager) and ``none`` otherwise; every authenticated caller reads a
public workspace as at least a ``User``, so the directory never refuses a row.

``view`` is ``all`` or ``mine`` (the caller holds a stored role). ``search`` is
stripped and casefolded, and matches a substring of the name or the description, or
the exact workspace id. Rows are sorted by casefolded name and then id in Python,
because an ``ORDER BY`` would drop workspaces saved without a name, and the page is
cut after filtering and sorting, so ``total_count`` counts the rows of the requested
view.

``hasLogo`` means a logo is stored, because ``GET
/api/public_workspaces/<ws_id>/logo`` serves any authenticated caller.

This route writes nothing. Every response is ``no-store``, and every failure is a
stable, data-free message with an ``error_code``.
"""

import logging
import re

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from config import cosmos_public_workspaces_container
from functions_appinsights import log_event
from functions_public_workspaces import get_user_role_in_public_workspace
from functions_workspace_branding import (
    DEFAULT_WORKSPACE_HERO_COLOR,
    get_workspace_logo_metadata,
    normalize_workspace_hero_color,
)


PUBLIC_DIRECTORY_HINTS_SCHEMA_VERSION = 1

PUBLIC_DIRECTORY_VIEWS = ("all", "mine")
PUBLIC_DIRECTORY_QUERY_PARAMETERS = ("search", "view", "page", "page_size")
PUBLIC_DIRECTORY_DEFAULT_PAGE_SIZE = 20
PUBLIC_DIRECTORY_MAX_PAGE_SIZE = 100
PUBLIC_DIRECTORY_MAX_PAGE = 10000
PUBLIC_DIRECTORY_SEARCH_MAX_LENGTH = 200

# The statuses the context builder recognizes; anything else is reported as unknown,
# so a reader sees the same vocabulary in the directory and in the selected workspace.
PUBLIC_DIRECTORY_STATUSES = ("active", "locked", "upload_disabled", "inactive")
PUBLIC_DIRECTORY_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager")

MEMBERSHIP_MEMBER = "member"
MEMBERSHIP_NONE = "none"

DIRECTORY_WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")

# Reduced to the caller on the server: only the caller's own entries in the admins
# and document-manager arrays, and the owner's id, read only to decide the caller's
# role and never returned. Public workspaces live in their own container, so no type
# filter is needed.
PUBLIC_DIRECTORY_QUERY = (
    "SELECT c.id, c.name, c.description, "
    "c.owner.userId AS ownerId, "
    "c.heroColor, c.logoVersion, c.status, "
    "(IS_STRING(c.logoBase64) AND LENGTH(TRIM(c.logoBase64)) > 0) AS logoPresent, "
    "ARRAY(SELECT VALUE a FROM a IN c.admins WHERE a = @user_id OR a.userId = @user_id) AS callerAdmins, "
    "ARRAY(SELECT VALUE m FROM m IN c.documentManagers "
    "WHERE m = @user_id OR m.userId = @user_id) AS callerDocumentManagers "
    "FROM c"
)

PUBLIC_DIRECTORY_UNAVAILABLE_MESSAGE = "The public workspace directory request could not be completed. Try again."
PUBLIC_DIRECTORY_REQUEST_MESSAGE = "The request could not be processed."


class PublicDirectoryError(HTTPException):
    """A stable, non-sensitive failure at the public directory boundary.

    ``fields`` are extra, equally safe response members (``error_code``) returned
    beside ``error``.
    """

    def __init__(self, message, status_code, **fields):
        super().__init__(description=message)
        self.code = status_code
        self.fields = fields


def _invalid_request(message):
    return PublicDirectoryError(message, 400, error_code="invalid_request")


def public_directory_error_response(error):
    """Map boundary errors to stable responses; anything else is a logged, generic 500."""
    if isinstance(error, PublicDirectoryError):
        payload, status = {"error": error.description, **error.fields}, error.code
    elif isinstance(error, HTTPException) and isinstance(error.code, int) and 400 <= error.code < 500:
        payload, status = {"error": PUBLIC_DIRECTORY_REQUEST_MESSAGE, "error_code": "invalid_request"}, error.code
    else:
        log_event(
            "[WORKSPACE_ROUTE] Public workspace directory request failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        payload, status = {
            "error": PUBLIC_DIRECTORY_UNAVAILABLE_MESSAGE,
            "error_code": "public_directory_unavailable",
        }, 500
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


# ---------------------------------------------------------------------------
# Strict request parsing
# ---------------------------------------------------------------------------

def reject_request_body():
    if request.get_data():
        raise _invalid_request("This request does not accept a request body.")


def _whole_number(value, *, default, maximum, message):
    if value is None:
        return default
    if not DIRECTORY_WHOLE_NUMBER.fullmatch(value) or int(value) > maximum:
        raise _invalid_request(message)
    return int(value)


def read_public_directory_query():
    """Read ``search``, ``view``, ``page`` and ``page_size``; anything else is a 400."""
    arguments = request.args
    for key in arguments.keys():
        if key not in PUBLIC_DIRECTORY_QUERY_PARAMETERS:
            raise _invalid_request("Use only the search, view, page and page_size query parameters.")
        if len(arguments.getlist(key)) > 1:
            raise _invalid_request("Give each query parameter only once.")
    view = arguments.get("view", "all")
    if view not in PUBLIC_DIRECTORY_VIEWS:
        raise _invalid_request("The view must be all or mine.")
    search = arguments.get("search", "").strip()
    if len(search) > PUBLIC_DIRECTORY_SEARCH_MAX_LENGTH:
        raise _invalid_request(
            f"Search terms can be at most {PUBLIC_DIRECTORY_SEARCH_MAX_LENGTH} characters."
        )
    page = _whole_number(
        arguments.get("page"),
        default=1,
        maximum=PUBLIC_DIRECTORY_MAX_PAGE,
        message=f"The page must be a whole number from 1 to {PUBLIC_DIRECTORY_MAX_PAGE}.",
    )
    page_size = _whole_number(
        arguments.get("page_size"),
        default=PUBLIC_DIRECTORY_DEFAULT_PAGE_SIZE,
        maximum=PUBLIC_DIRECTORY_MAX_PAGE_SIZE,
        message=f"The page size must be a whole number from 1 to {PUBLIC_DIRECTORY_MAX_PAGE_SIZE}.",
    )
    return {"view": view, "search": search, "page": page, "page_size": page_size}


def _require_user_id(user_id):
    if not isinstance(user_id, str) or not user_id:
        raise PublicDirectoryError("User not authenticated.", 401, error_code="not_authenticated")
    return user_id


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _text(value):
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _caller_role(record, user_id):
    """The caller's role, from the reduced record, via the read routes' predicate."""
    caller_view = {
        "owner": {"userId": record.get("ownerId")},
        "admins": record.get("callerAdmins") if isinstance(record.get("callerAdmins"), list) else [],
        "documentManagers": (
            record.get("callerDocumentManagers")
            if isinstance(record.get("callerDocumentManagers"), list) else []
        ),
    }
    return get_user_role_in_public_workspace(caller_view, user_id)


def _directory_row(record, user_id):
    role = _caller_role(record, user_id)
    stored_status = record.get("status")
    status = stored_status if stored_status in PUBLIC_DIRECTORY_STATUSES else "unknown"
    return {
        "id": _text(record.get("id")),
        "name": _text(record.get("name")),
        "description": _text(record.get("description")),
        "heroColor": normalize_workspace_hero_color(record.get("heroColor"), DEFAULT_WORKSPACE_HERO_COLOR),
        "hasLogo": record.get("logoPresent") is True,
        "logoVersion": get_workspace_logo_metadata({"logoVersion": record.get("logoVersion")})["logoVersion"],
        "userRole": role,
        "membership": MEMBERSHIP_MEMBER if role in PUBLIC_DIRECTORY_MEMBER_ROLES else MEMBERSHIP_NONE,
        "status": status,
    }


def build_public_directory_row(workspace, user_id):
    """Project one whole public workspace document for the caller, as the directory lists it."""
    logo = workspace.get("logoBase64")
    record = {
        "id": workspace.get("id"),
        "name": workspace.get("name"),
        "description": workspace.get("description"),
        "ownerId": (workspace.get("owner") or {}).get("userId"),
        "heroColor": workspace.get("heroColor"),
        "logoVersion": workspace.get("logoVersion"),
        "status": workspace.get("status"),
        "logoPresent": isinstance(logo, str) and bool(logo.strip()),
        "callerAdmins": _caller_members(workspace.get("admins"), user_id),
        "callerDocumentManagers": _caller_members(workspace.get("documentManagers"), user_id),
    }
    return _directory_row(record, user_id)


def _caller_members(entries, user_id):
    """The caller's own entries in a member array, matching both member formats."""
    if not isinstance(entries, list):
        return []
    caller = []
    for entry in entries:
        if isinstance(entry, str) and entry == user_id:
            caller.append(entry)
        elif isinstance(entry, dict) and entry.get("userId") == user_id:
            caller.append(entry)
    return caller


def _matches_search(row, needle):
    return (
        needle in row["name"].casefold()
        or needle in row["description"].casefold()
        or needle == row["id"].casefold()
    )


def _in_view(row, view):
    if view == "mine":
        return row["membership"] == MEMBERSHIP_MEMBER
    return True


def build_public_directory_hints():
    """Return the ``public_directory`` envelope hint the directory response carries."""
    return {"schema_version": PUBLIC_DIRECTORY_HINTS_SCHEMA_VERSION}


def list_public_directory(user_id, *, view, search, page, page_size):
    """Return ``(payload, 200)`` with one page of the public directory for the caller."""
    user_id = _require_user_id(user_id)
    records = cosmos_public_workspaces_container.query_items(
        query=PUBLIC_DIRECTORY_QUERY,
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
        "workspaces": rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total_count": len(rows),
        "public_directory": build_public_directory_hints(),
    }, 200


__all__ = [
    "PUBLIC_DIRECTORY_QUERY",
    "PUBLIC_DIRECTORY_VIEWS",
    "PublicDirectoryError",
    "build_public_directory_hints",
    "build_public_directory_row",
    "list_public_directory",
    "public_directory_error_response",
    "read_public_directory_query",
    "reject_request_body",
]
