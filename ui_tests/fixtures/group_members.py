# group_members.py
"""
Closed M7B group membership HTTP fixtures for the real production V2 SPA.
Version: 0.261.155
Implemented in: 0.261.155

The fixture serves the native group membership family the V2 Members section reads and writes
-- `GET`/`POST /api/groups/<g>/membership/members`, `PATCH`/`DELETE .../members/<user_id>`,
`GET .../membership/requests`, `POST .../requests/<user_id>/approve|reject` and
`PUT .../membership/owner` -- plus the directory people search `GET /api/userSearch`, and
nothing else. It models the server's rules rather than a convenient shape:

- the policy is the real `functions_group_membership_policy` module, loaded from the app, so the
  `membership_management` operations and every row's `member_actions` are the server's own;
- the owner and status rules, pending-request cleanup, transfer, the directory lookup outcomes
  (found, definitively not found, unavailable with the submitted details as the fallback) and
  every refusal are ported from `functions_group_membership`, with its exact messages, in the
  server's order of checks;
- the list takes each `users[]` entry once, adds a missing owner, filters by casefolded search and
  exact role, sorts by role rank, casefolded name and id, and pages after filtering;
- every membership response, success or error, carries `Cache-Control: no-store`.

State changes a test makes between loading the page and acting on it model a concurrent change the
server saw first (a demotion, a removal, a transfer, a locked group, a request handled elsewhere),
so each refusal comes from the same rule the server applies, not from a scripted answer. Only the
write conflict, which no single state models, is scripted, with `force_conflict`. After every
membership change the viewer's workspace context is recomputed from the stored membership, so a
context re-read after a transfer, a self-demotion or a leave sees the server's new truth.

It extends `GroupWorkspaceFixture`, so the inherited bootstrap, `/api/groups` picker, group context
and the personal-scope and `/api/v2/admin/*` traps keep working. The classic membership routes
(`/api/groups/<g>/members[...]`, `/requests[...]`, `/transferOwnership`) are trapped as unexpected:
the native Members section must never call them. The fixture-parity functional test holds every
shape, status, code, message and header here to the real routes.
"""

import copy
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, group_context
from ui_tests.fixtures.workspace_authoring import OWNER_ID


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"


def _load_policy():
    """The real, pure membership policy module, so the fixture's hints are the server's own."""
    path = APP_ROOT / "functions_group_membership_policy.py"
    spec = importlib.util.spec_from_file_location("ui_fixture_group_membership_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load_policy()
SETTINGS = {"enable_group_workspaces": True}

# Ported verbatim from functions_group_membership; the parity test pins each one.
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
# functions_group_directory's strict-request messages, which the membership routes reuse.
NO_QUERY_MESSAGE = "This request does not accept query parameters."
NO_BODY_MESSAGE = "This request does not accept a request body."
JSON_OBJECT_MESSAGE = "A JSON object is required for this request."
# /api/userSearch (route_backend_users) answers.
USER_SEARCH_TOKEN_MESSAGE = "Could not acquire access token"
USER_SEARCH_FAILED_MESSAGE = "Graph API request failed"
USER_SEARCH_TIMEOUT_MESSAGE = "Graph API request timed out"

LIST_PARAMETERS = ("search", "role", "page", "page_size")
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_PAGE = 10000
SEARCH_MAX_LENGTH = 200
TEXT_MAX_LENGTH = 256
ADD_FIELDS = ("userId", "displayName", "email", "role")
INVALID_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")
ROLE_RANK = {role: rank for rank, role in enumerate(POLICY.GROUP_MEMBER_ROLES)}

_MEMBERSHIP_ROUTE = re.compile(r"^/api/groups/(?P<group>[^/]+)/membership/(?P<rest>.+)$")
_CLASSIC_MEMBERSHIP_ROUTE = re.compile(r"^/api/groups/[^/]+/(members|requests|transferOwnership)(/.*)?$")

# The viewer's own membership entry. The name sorts onto the first page for every role.
VIEWER_NAME = "Avery Editor"
VIEWER_EMAIL = "avery.editor@example.test"


def guid(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def person(user_id, name, email):
    return {"userId": user_id, "email": email, "displayName": name}


# The cast every membership document is built from. Ids are GUIDs, as the directory's are.
OMAR = person(guid(1), "Omar Owner", "omar.owner@example.test")
OLIVIA = person(guid(2), "Olivia Admin", "olivia.admin@example.test")
DMITRI = person(guid(3), "Dmitri Docs", "dmitri.docs@example.test")
MAYA = person(guid(4), "Maya Member", "maya.member@example.test")
LEE = person(guid(5), "Lee Reader", "lee.reader@example.test")
PRIYA = person(guid(6), "Priya Pending", "priya.pending@example.test")
SAM = person(guid(7), "Sam Seeker", "sam.seeker@example.test")
NORA = person(guid(8), "Nora Newcomer", "nora.newcomer@example.test")
NIA = person(guid(9), "Nia Unlisted", "nia.unlisted@example.test")
# A member at the server's text maxima, so the layout case proves 256-character values never
# overflow. The name starts with "A" so it sorts onto the first page of members.
LONG_NAME = "Alexandria " + "Featherstonehaugh-Wolfeschlegelsteinhausenbergerdorff " * 4
LONG_NAME = (LONG_NAME + "x" * TEXT_MAX_LENGTH)[:TEXT_MAX_LENGTH]
LONG_EMAIL = ("alexandria." + "long" * 70)[:TEXT_MAX_LENGTH - len("@example.test")] + "@example.test"
LONG = person(guid(10), LONG_NAME, LONG_EMAIL)
FILLER = [person(guid(100 + index), f"Teammate {index:02d}", f"teammate.{index:02d}@example.test") for index in range(1, 19)]
VIEWER = person(OWNER_ID, VIEWER_NAME, VIEWER_EMAIL)


def membership_document(viewer_role="Owner", *, status="active", pending=(PRIYA, SAM), long_member=True):
    """A stored group's membership, with the viewer in `viewer_role` and a fixed cast around them."""
    owner = VIEWER if viewer_role == "Owner" else OMAR
    admins = [OLIVIA["userId"]] + ([OWNER_ID] if viewer_role == "Admin" else [])
    managers = [DMITRI["userId"]] + ([OWNER_ID] if viewer_role == "DocumentManager" else [])
    users = [owner, OLIVIA, DMITRI, MAYA, LEE, *FILLER]
    if viewer_role != "Owner":
        users.insert(1, VIEWER)
    if long_member:
        users.append(LONG)
    return {
        "status": status,
        "owner": {"id": owner["userId"], "email": owner["email"], "displayName": owner["displayName"]},
        "users": copy.deepcopy(users),
        "admins": admins,
        "documentManagers": managers,
        "pendingUsers": copy.deepcopy(list(pending)),
    }


class _Refusal(Exception):
    def __init__(self, status, message, code):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _invalid(message):
    return _Refusal(400, message, "invalid_request")


class GroupMembersFixture(GroupWorkspaceFixture):
    """A small scripted membership boundary; no second groups service, no live directory."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        self.memberships = {}
        self.set_viewer_role("group-a", "Owner")
        self.set_viewer_role("group-b", "User")
        # The tenant directory the people search and the add's by-id lookup read. An id in
        # `directory_missing` is found by the search but definitively not found by id (a person
        # deleted in between); `directory_available = False` models no token, no permission or a
        # transport failure on the by-id lookup, where the server uses the submitted details.
        self.directory = {entry["userId"]: {"id": entry["userId"], "displayName": entry["displayName"],
                                            "email": entry["email"]}
                          for entry in (OMAR, OLIVIA, DMITRI, MAYA, LEE, PRIYA, SAM, NORA, NIA, *FILLER)}
        self.directory_missing = {NIA["userId"]}
        self.directory_by_id = {}
        self.directory_available = True
        self.user_search_failure = None
        self.forced_conflicts = []
        self.malformed_list = False
        self.malformed_requests = False

    # --- state a test arranges -------------------------------------------------------------

    def set_viewer_role(self, group_id, role, *, status="active", **options):
        """Rebuild a group's membership with the viewer holding `role`, and its context to match."""
        self.memberships[group_id] = membership_document(role, status=status, **options)
        self.denied_groups.discard(group_id)
        self._sync_context(group_id)
        return self.memberships[group_id]

    def document(self, group_id):
        return self.memberships.get(group_id)

    def set_status(self, group_id, status):
        self.memberships[group_id]["status"] = status
        self._sync_context(group_id)

    def set_member_role(self, group_id, user_id, role):
        """A role change the server saw first."""
        document = self.memberships[group_id]
        document["admins"] = [value for value in document["admins"] if value != user_id]
        document["documentManagers"] = [value for value in document["documentManagers"] if value != user_id]
        if role == "Admin":
            document["admins"].append(user_id)
        elif role == "DocumentManager":
            document["documentManagers"].append(user_id)
        self._sync_context(group_id)

    def remove_person(self, group_id, user_id):
        """A removal the server saw first."""
        document = self.memberships[group_id]
        document["users"] = [entry for entry in document["users"] if entry.get("userId") != user_id]
        document["admins"] = [value for value in document["admins"] if value != user_id]
        document["documentManagers"] = [value for value in document["documentManagers"] if value != user_id]
        self._sync_context(group_id)

    def make_owner(self, group_id, user_id):
        """An ownership transfer the server saw first."""
        document = self.memberships[group_id]
        self._transfer(document, user_id)
        self._sync_context(group_id)

    def add_pending(self, group_id, entry):
        self.memberships[group_id]["pendingUsers"].append(copy.deepcopy(entry))

    def approve_elsewhere(self, group_id, user_id):
        """An approval another manager made, or one whose answer this page never received."""
        document = self.memberships[group_id]
        entries = [entry for entry in document["pendingUsers"] if entry.get("userId") == user_id]
        document["pendingUsers"] = [entry for entry in document["pendingUsers"] if entry.get("userId") != user_id]
        if entries and not self._role_of(document, user_id):
            document["users"].append(copy.deepcopy(entries[0]))

    def delete_group(self, group_id):
        """The group was deleted after the page loaded."""
        self.memberships.pop(group_id, None)
        self.groups.pop(group_id, None)

    def force_conflict(self, method, rest):
        """Answer the next matching membership write with the guard's 409 `group_write_conflict`."""
        self.forced_conflicts.append((method, rest))

    def membership_requests(self, method=None):
        return [
            entry for entry in self.requests
            if "/membership/" in entry.path and (method is None or entry.method == method)
        ]

    # --- inherited surfaces ----------------------------------------------------------------

    def _bootstrap(self):
        # The server lists only the caller's groups and clears a saved active group they left.
        payload = super()._bootstrap()
        payload["user"]["display_name"] = VIEWER_NAME
        payload["scope"]["groups"] = [
            group for group in payload["scope"]["groups"] if group["id"] not in self.denied_groups
        ]
        if payload["scope"].get("active_group_id") in self.denied_groups:
            payload["scope"]["active_group_id"] = None
        return payload

    def _sync_context(self, group_id):
        document = self.memberships.get(group_id)
        current = self.groups.get(group_id)
        if document is None or current is None:
            return
        role = self._role_of(document, OWNER_ID)
        if role is None:
            self.denied_groups.add(group_id)
            return
        self.denied_groups.discard(group_id)
        status = document.get("status") or "active"
        self.groups[group_id] = group_context(
            group_id, current["workspace"]["name"], role=role,
            status=status if status in ("active", "locked", "upload_disabled", "inactive") else "unknown",
        )

    def _json(self, route, payload, status=200):
        # Every native membership response -- success or error -- is `no-store`, as the server's
        # `_no_store` wrapper and `group_membership_error_response` both make it.
        path = urlsplit(route.request.url).path
        if not _MEMBERSHIP_ROUTE.match(path):
            super()._json(route, payload, status)
            return
        self.responses.append((route.request.url, copy.deepcopy(payload)))
        if status >= 400:
            self.expected_http_errors.add((route.request.url, status))
        route.fulfill(status=status, json=payload, headers={"Cache-Control": "no-store"})

    def _dispatch(self, route, entry):
        match = _MEMBERSHIP_ROUTE.match(entry.path)
        if match:
            self._membership(route, entry, match.group("group"), match.group("rest"))
            return
        if _CLASSIC_MEMBERSHIP_ROUTE.match(entry.path):
            # The native Members section must never fall back to the classic membership routes.
            self.unexpected_requests.append(f"{entry.method} {entry.path} (classic membership route)")
            self._json(route, {"error": "Classic membership routes are not available here."}, 500)
            return
        if entry.path == "/api/userSearch" and entry.method == "GET":
            self._user_search(route, entry)
            return
        super()._dispatch(route, entry)

    # --- the people search ------------------------------------------------------------------

    def _user_search(self, route, entry):
        query = (entry.query.get("query") or [""])[0].strip()
        if not query:
            self._json(route, [])
            return
        if self.user_search_failure is not None:
            status, message = self.user_search_failure
            self._json(route, {"error": message}, status)
            return
        needle = query.casefold()
        matches = [
            copy.deepcopy(user) for user in self.directory.values()
            if user["displayName"].casefold().startswith(needle) or user["email"].casefold().startswith(needle)
        ]
        self._json(route, matches[:10])

    # --- projection, ported from functions_group_membership ---------------------------------

    @staticmethod
    def _view(document):
        owner = document.get("owner") if isinstance(document.get("owner"), dict) else {}
        users, seen = [], set()
        for entry in document.get("users") or []:
            user_id = entry.get("userId") if isinstance(entry, dict) else None
            if isinstance(user_id, str) and user_id and user_id not in seen:
                seen.add(user_id)
                users.append(entry)
        return {
            "owner": {"id": owner.get("id"), "displayName": owner.get("displayName"), "email": owner.get("email")},
            "admins": [value for value in document.get("admins") or [] if isinstance(value, str)],
            "documentManagers": [value for value in document.get("documentManagers") or [] if isinstance(value, str)],
            "users": users,
        }

    def _role_of(self, document, user_id):
        view = self._view(document)
        if view["owner"]["id"] == user_id:
            return "Owner"
        if user_id in view["admins"]:
            return "Admin"
        if user_id in view["documentManagers"]:
            return "DocumentManager"
        if any(entry["userId"] == user_id for entry in view["users"]):
            return "User"
        return None

    @staticmethod
    def _text(value):
        if isinstance(value, str):
            return value
        return "" if value is None else str(value)

    def _entries(self, document):
        view = self._view(document)
        entries = list(view["users"])
        owner_id = view["owner"]["id"]
        if owner_id and not any(entry["userId"] == owner_id for entry in entries):
            entries.append({"userId": owner_id, "displayName": view["owner"]["displayName"],
                            "email": view["owner"]["email"]})
        return entries

    def _row(self, document, entry, caller_id):
        member_id = entry["userId"]
        role = self._role_of(document, member_id)
        caller_role = self._role_of(document, caller_id)
        return {
            "userId": member_id,
            "displayName": self._text(entry.get("displayName")),
            "email": self._text(entry.get("email")),
            "role": role,
            "member_actions": list(POLICY.group_member_actions(caller_role, role, is_self=member_id == caller_id)),
        }

    def _row_for(self, document, member_id, caller_id):
        for entry in self._entries(document):
            if entry["userId"] == member_id:
                return self._row(document, entry, caller_id)
        return None

    # --- strict parsing, ported from functions_group_membership and functions_group_directory --

    @staticmethod
    def _identifier(value, label):
        if (not isinstance(value, str) or not value or len(value) > 512 or value != value.strip()
                or value in (".", "..") or INVALID_ID.search(value)):
            raise _invalid(f"Invalid {label}.")
        return value

    @staticmethod
    def _reject_query(entry):
        if entry.query:
            raise _invalid(NO_QUERY_MESSAGE)

    @staticmethod
    def _reject_body(entry):
        if entry.body not in (None, "", b""):
            raise _invalid(NO_BODY_MESSAGE)

    @staticmethod
    def _json_object(entry):
        if not isinstance(entry.body, dict):
            raise _invalid(JSON_OBJECT_MESSAGE)
        return entry.body

    @staticmethod
    def _whole_number(values, *, default, maximum, message):
        if not values:
            return default
        if not WHOLE_NUMBER.fullmatch(values[0]) or int(values[0]) > maximum:
            raise _invalid(message)
        return int(values[0])

    def _list_query(self, entry):
        for key, values in entry.query.items():
            if key not in LIST_PARAMETERS:
                raise _invalid("Use only the search, role, page and page_size query parameters.")
            if len(values) > 1:
                raise _invalid("Give each query parameter only once.")
        search = (entry.query.get("search") or [""])[0].strip()
        if len(search) > SEARCH_MAX_LENGTH:
            raise _invalid(f"Search terms can be at most {SEARCH_MAX_LENGTH} characters.")
        role = (entry.query.get("role") or [None])[0]
        if role is not None and role not in POLICY.GROUP_MEMBER_ROLES:
            raise _invalid("The role must be Owner, Admin, DocumentManager or User.")
        page = self._whole_number(entry.query.get("page"), default=1, maximum=MAX_PAGE,
                                  message=f"The page must be a whole number from 1 to {MAX_PAGE}.")
        page_size = self._whole_number(entry.query.get("page_size"), default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE,
                                       message=f"The page size must be a whole number from 1 to {MAX_PAGE_SIZE}.")
        return search, role, page, page_size

    @staticmethod
    def _member_text(body, key, label):
        value = body.get(key, "")
        if not isinstance(value, str):
            raise _invalid(f"The {label} must be text.")
        value = value.strip()
        if len(value) > TEXT_MAX_LENGTH:
            raise _invalid(f"The {label} can be at most {TEXT_MAX_LENGTH} characters.")
        if CONTROL_CHARACTERS.search(value):
            raise _invalid(f"The {label} can't contain control characters.")
        return value

    @staticmethod
    def _assignable_role(body):
        role = body.get("role")
        if role not in POLICY.GROUP_ASSIGNABLE_ROLES:
            raise _invalid("The role must be Admin, DocumentManager or User.")
        return role

    def _body_user_id(self, body):
        user_id = body.get("userId")
        if isinstance(user_id, str):
            user_id = user_id.strip()
        return self._identifier(user_id, "user identifier")

    # --- authorization, ported ---------------------------------------------------------------

    def _document_or_404(self, group_id):
        document = self.memberships.get(group_id)
        if document is None:
            raise _Refusal(404, GROUP_NOT_FOUND_MESSAGE, "group_not_found")
        return document

    def _caller_role(self, document):
        role = self._role_of(document, OWNER_ID)
        if role is None:
            raise _Refusal(403, NOT_A_MEMBER_MESSAGE, "not_a_member")
        return role

    def _manager_role(self, document):
        role = self._caller_role(document)
        if role not in POLICY.GROUP_MEMBERSHIP_MANAGER_ROLES:
            raise _Refusal(403, MEMBERSHIP_PERMISSION_MESSAGE, "membership_permission")
        return role

    def _forced(self, entry, rest):
        key = (entry.method, rest)
        if key in self.forced_conflicts:
            self.forced_conflicts.remove(key)
            raise _Refusal(409, WRITE_CONFLICT_MESSAGE, "group_write_conflict")

    # --- dispatch ----------------------------------------------------------------------------

    def _membership(self, route, entry, group_id, rest):
        parts = rest.split("/")
        try:
            if parts == ["members"] and entry.method == "GET":
                payload, status = self._list(entry, group_id)
            elif parts == ["members"] and entry.method == "POST":
                payload, status = self._add(entry, group_id, rest)
            elif len(parts) == 2 and parts[0] == "members" and entry.method == "PATCH":
                payload, status = self._change_role(entry, group_id, parts[1], rest)
            elif len(parts) == 2 and parts[0] == "members" and entry.method == "DELETE":
                payload, status = self._remove(entry, group_id, parts[1], rest)
            elif parts == ["requests"] and entry.method == "GET":
                payload, status = self._requests(entry, group_id)
            elif len(parts) == 3 and parts[0] == "requests" and parts[2] in ("approve", "reject") and entry.method == "POST":
                payload, status = self._decide(entry, group_id, parts[1], parts[2], rest)
            elif parts == ["owner"] and entry.method == "PUT":
                payload, status = self._transfer_route(entry, group_id, rest)
            else:
                self.unexpected_requests.append(f"{entry.method} {entry.path} (no such membership route)")
                self._json(route, {"error": "Not found."}, 404)
                return
        except _Refusal as refusal:
            self._json(route, {"error": refusal.message, "error_code": refusal.code}, refusal.status)
            return
        self._json(route, payload, status)

    def _list(self, entry, group_id):
        search, role, page, page_size = self._list_query(entry)
        self._reject_body(entry)
        self._identifier(group_id, "group identifier")
        document = self._document_or_404(group_id)
        caller_role = self._caller_role(document)
        needle = search.casefold()
        rows = [self._row(document, item, OWNER_ID) for item in self._entries(document)]
        rows = [
            row for row in rows
            if (role is None or row["role"] == role)
            and (not needle or needle in row["displayName"].casefold() or needle in row["email"].casefold()
                 or needle == row["userId"].casefold())
        ]
        rows.sort(key=lambda row: (ROLE_RANK.get(row["role"], len(ROLE_RANK)), row["displayName"].casefold(), row["userId"]))
        if self.malformed_list:
            for row in rows:
                row.pop("member_actions", None)
        start = (page - 1) * page_size
        return {
            "members": rows[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total_count": len(rows),
            "membership_management": {
                "schema_version": POLICY.GROUP_MEMBERSHIP_HINT_SCHEMA_VERSION,
                "operations": list(POLICY.group_membership_operations(caller_role, document, SETTINGS)),
            },
        }, 200

    def _requests(self, entry, group_id):
        self._reject_query(entry)
        self._reject_body(entry)
        self._identifier(group_id, "group identifier")
        document = self._document_or_404(group_id)
        self._manager_role(document)
        rows, seen = [], set()
        for item in document.get("pendingUsers") or []:
            pending_id = item.get("userId") if isinstance(item, dict) else None
            if isinstance(pending_id, str) and pending_id and pending_id not in seen:
                seen.add(pending_id)
                rows.append({"userId": pending_id, "displayName": self._text(item.get("displayName")),
                             "email": self._text(item.get("email"))})
        rows.sort(key=lambda row: (row["displayName"].casefold(), row["userId"]))
        if self.malformed_requests:
            rows = [{"displayName": row["displayName"]} for row in rows] or [{"displayName": "No id"}]
        return {"requests": rows, "total_count": len(rows)}, 200

    def _resolve(self, fields):
        requested = fields["user_id"]
        if not self.directory_available:
            email = fields["email"]
            return {"userId": requested, "email": email, "displayName": fields["display_name"] or email or requested}
        user = self.directory_by_id.get(requested) or (
            None if requested in self.directory_missing else self.directory.get(requested)
        )
        if not user:
            raise _Refusal(400, USER_NOT_FOUND_MESSAGE, "user_not_found")
        member_id = str(user.get("id") or "").strip() or requested
        email = str(user.get("email") or "")
        return {"userId": member_id, "email": email, "displayName": user.get("displayName") or email or member_id}

    def _add(self, entry, group_id, rest):
        self._reject_query(entry)
        self._identifier(group_id, "group identifier")
        body = self._json_object(entry)
        if any(key not in ADD_FIELDS for key in body):
            raise _invalid("Only userId, displayName, email and role can be sent when adding a member.")
        fields = {
            "user_id": self._body_user_id(body),
            "display_name": self._member_text(body, "displayName", "display name"),
            "email": self._member_text(body, "email", "email"),
            "role": self._assignable_role(body),
        }
        document = self._document_or_404(group_id)
        self._manager_role(document)
        if not POLICY.group_member_add_allowed(document):
            raise _Refusal(403, STATUS_UNAVAILABLE_MESSAGE, "group_status_unavailable")
        member = self._resolve(fields)
        member_id = member["userId"]
        if self._role_of(document, member_id):
            raise _Refusal(409, ALREADY_MEMBER_MESSAGE, "already_member")
        self._forced(entry, rest)
        document["users"].append(member)
        if fields["role"] == "Admin":
            document["admins"].append(member_id)
        elif fields["role"] == "DocumentManager":
            document["documentManagers"].append(member_id)
        document["pendingUsers"] = [item for item in document["pendingUsers"] if item.get("userId") != member_id]
        self._sync_context(group_id)
        return {"member": self._row_for(document, member_id, OWNER_ID)}, 201

    def _change_role(self, entry, group_id, member_id, rest):
        self._reject_query(entry)
        self._identifier(group_id, "group identifier")
        self._identifier(member_id, "user identifier")
        body = self._json_object(entry)
        if any(key != "role" for key in body):
            raise _invalid("Send only the role to change a member's role.")
        new_role = self._assignable_role(body)
        document = self._document_or_404(group_id)
        self._manager_role(document)
        target_role = self._role_of(document, member_id)
        if target_role is None:
            raise _Refusal(404, MEMBER_NOT_FOUND_MESSAGE, "member_not_found")
        if target_role == "Owner":
            raise _Refusal(409, OWNER_ROLE_MESSAGE, "owner_target")
        if target_role == new_role:
            return {"member": self._row_for(document, member_id, OWNER_ID), "changed": False}, 200
        self._forced(entry, rest)
        document["admins"] = [value for value in document["admins"] if value != member_id]
        document["documentManagers"] = [value for value in document["documentManagers"] if value != member_id]
        if new_role == "Admin":
            document["admins"].append(member_id)
        elif new_role == "DocumentManager":
            document["documentManagers"].append(member_id)
        self._sync_context(group_id)
        return {"member": self._row_for(document, member_id, OWNER_ID), "changed": True}, 200

    def _remove(self, entry, group_id, member_id, rest):
        self._reject_query(entry)
        self._reject_body(entry)
        self._identifier(group_id, "group identifier")
        self._identifier(member_id, "user identifier")
        leaving = member_id == OWNER_ID
        document = self._document_or_404(group_id)
        caller_role = self._caller_role(document)
        if leaving:
            if caller_role == "Owner":
                raise _Refusal(409, OWNER_LEAVE_MESSAGE, "owner_cannot_leave")
        else:
            if caller_role not in POLICY.GROUP_MEMBERSHIP_MANAGER_ROLES:
                raise _Refusal(403, MEMBERSHIP_PERMISSION_MESSAGE, "membership_permission")
            target_role = self._role_of(document, member_id)
            if target_role is None:
                raise _Refusal(404, MEMBER_NOT_FOUND_MESSAGE, "member_not_found")
            if target_role == "Owner":
                raise _Refusal(409, OWNER_REMOVAL_MESSAGE, "owner_target")
        self._forced(entry, rest)
        document["users"] = [item for item in document["users"] if item.get("userId") != member_id]
        document["admins"] = [value for value in document["admins"] if value != member_id]
        document["documentManagers"] = [value for value in document["documentManagers"] if value != member_id]
        self._sync_context(group_id)
        return {"userId": member_id, "left": leaving}, 200

    def _decide(self, entry, group_id, member_id, decision, rest):
        self._reject_query(entry)
        self._reject_body(entry)
        self._identifier(group_id, "group identifier")
        self._identifier(member_id, "user identifier")
        document = self._document_or_404(group_id)
        self._manager_role(document)
        entries = [item for item in document["pendingUsers"] if item.get("userId") == member_id]
        if not entries:
            raise _Refusal(409, NO_PENDING_REQUEST_MESSAGE, "no_pending_request")
        self._forced(entry, rest)
        document["pendingUsers"] = [item for item in document["pendingUsers"] if item.get("userId") != member_id]
        if decision == "reject":
            return {"userId": member_id}, 200
        already_member = self._role_of(document, member_id) is not None
        if not already_member:
            first = entries[0]
            document["users"].append({"userId": member_id, "email": first.get("email"),
                                      "displayName": first.get("displayName")})
        self._sync_context(group_id)
        return {"member": self._row_for(document, member_id, OWNER_ID), "already_member": already_member}, 200

    def _transfer(self, document, new_owner_id):
        view = self._view(document)
        target = next(item for item in view["users"] if item["userId"] == new_owner_id)
        previous = copy.deepcopy(document["owner"])
        previous_id = view["owner"]["id"]
        document["owner"] = {"id": new_owner_id, "email": target.get("email", ""),
                             "displayName": target.get("displayName", "")}
        document["admins"] = [value for value in document["admins"] if value not in (new_owner_id, previous_id)]
        document["documentManagers"] = [
            value for value in document["documentManagers"] if value not in (new_owner_id, previous_id)
        ]
        if not any(item["userId"] == previous_id for item in view["users"]):
            document["users"].append({"userId": previous_id, "email": previous.get("email", ""),
                                      "displayName": previous.get("displayName", "")})

    def _transfer_route(self, entry, group_id, rest):
        self._reject_query(entry)
        self._identifier(group_id, "group identifier")
        body = self._json_object(entry)
        if any(key != "userId" for key in body):
            raise _invalid("Send only the userId of the new owner.")
        new_owner_id = self._body_user_id(body)
        document = self._document_or_404(group_id)
        caller_role = self._caller_role(document)
        if self._view(document)["owner"]["id"] == new_owner_id:
            return {"owner": self._row_for(document, new_owner_id, OWNER_ID), "changed": False}, 200
        if caller_role != "Owner":
            raise _Refusal(403, OWNER_ONLY_MESSAGE, "owner_only")
        if not any(item["userId"] == new_owner_id for item in self._view(document)["users"]):
            raise _Refusal(404, MEMBER_NOT_FOUND_MESSAGE, "member_not_found")
        self._forced(entry, rest)
        self._transfer(document, new_owner_id)
        self._sync_context(group_id)
        return {"owner": self._row_for(document, new_owner_id, OWNER_ID), "changed": True}, 200


@pytest.fixture
def group_members_ui(page):
    fixture = GroupMembersFixture(page)
    yield fixture
    fixture.assert_clean()
