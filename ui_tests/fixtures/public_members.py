# public_members.py
"""
Closed M10A public workspace membership HTTP fixtures for the real production V2 SPA.
Version: 0.261.177
Implemented in: 0.261.177

The fixture serves the native public membership family the V2 Members section reads and writes
-- `GET`/`POST /api/public-workspaces/<w>/membership/members`, `PATCH`/`DELETE .../members/<user_id>`,
`GET .../membership/requests`, `POST .../requests/<user_id>/approve|reject` and
`PUT .../membership/owner` -- plus the directory people search `GET /api/userSearch`, and nothing
else. It models the server's rules rather than a convenient shape:

- the policy is the real `functions_public_membership_policy` module and the disclosure is the real
  `functions_public_membership_disclosure` projector, both loaded from the app, so the
  `membership_management` operations, every row's `member_actions` and the email redaction are the
  server's own;
- a public workspace has no `users[]` roster: the members are exactly the Owner, the Admins and the
  DocumentManagers, taken once at their highest role, and the pending requests are the workspace's
  `pendingDocumentManagers`. `User` is every other signed-in reader, never stored or listed;
- the owner and status rules, pending-request cleanup, the decision-21 transfer (the old owner
  stays a DocumentManager with their name and email), the R5.7 role-change carry-over, and every
  refusal are ported from `functions_public_membership`, with its exact messages and codes, in the
  server's order of checks;
- there is no `leave` and no self-action (decision 17): a manager can't remove themselves, and the
  routes carry no `leave` operation or action;
- an Owner or Admin viewer sees members' emails; any other viewer (a DocumentManager) sees names
  and roles only, because the projector blanks the email before the list leaves the route;
- every membership response, success or error, carries `Cache-Control: no-store`.

State a test changes between loading the page and acting on it models a concurrent change the
server saw first (a demotion, a removal, a transfer, a locked workspace, a request handled
elsewhere), so each refusal comes from the same rule the server applies. Only the write conflict,
which no single state models, is scripted, with `force_conflict`. After every membership change the
viewer's public workspace context is recomputed from the stored membership, so a context re-read
after a transfer or a self-demotion sees the server's new truth.

It extends `PublicWorkspaceFixture`, so the inherited bootstrap, `/api/public_workspaces` picker,
public context and the personal-scope traps keep working. The classic public membership routes
(`/api/public_workspaces/<w>/members[...]`, `/requests[...]`, `/transferOwnership`) are trapped as
unexpected: the native Members section must never call them. The fixture-parity functional test
holds every shape, status, code, message and header here to the real routes.
"""

import ast
import copy
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from ui_tests.fixtures.public_workspace import PublicWorkspaceFixture, public_context
from ui_tests.fixtures.workspace_authoring import OWNER_ID


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"


def _load(name):
    """A real, pure application module, so the fixture's hints are the server's own."""
    path = APP_ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ui_fixture_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _app_constant(file_name, name):
    """A literal module-level constant of an application module, read from its source.

    ``functions_public_workspaces`` builds Cosmos clients through ``config`` when it's imported, so
    its constants are read here rather than imported.
    """
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise LookupError(f"{file_name} defines no literal {name}")


POLICY = _load("functions_public_membership_policy")
DISCLOSURE = _load("functions_public_membership_disclosure")
project_member_rows = DISCLOSURE.project_member_rows
SETTINGS = {"enable_public_workspaces": True}

# Ported verbatim from functions_public_membership; the parity test pins each one.
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
# The one public write-conflict sentence and code, read from functions_public_workspaces itself.
WRITE_CONFLICT_MESSAGE = _app_constant("functions_public_workspaces.py", "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE")
WRITE_CONFLICT_CODE = _app_constant("functions_public_workspaces.py", "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE")
# functions_public_membership's strict-request messages.
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
ROLE_RANK = {role: rank for rank, role in enumerate(POLICY.PUBLIC_MEMBER_ROLES)}

_MEMBERSHIP_ROUTE = re.compile(r"^/api/public-workspaces/(?P<ws>[^/]+)/membership/(?P<rest>.+)$")
_CLASSIC_MEMBERSHIP_ROUTE = re.compile(r"^/api/public_workspaces/[^/]+/(members|requests|transferOwnership)(/.*)?$")

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
MAYA = person(guid(4), "Maya Manager", "maya.manager@example.test")
LEE = person(guid(5), "Lee Librarian", "lee.librarian@example.test")
PRIYA = person(guid(6), "Priya Pending", "priya.pending@example.test")
SAM = person(guid(7), "Sam Seeker", "sam.seeker@example.test")
NORA = person(guid(8), "Nora Newcomer", "nora.newcomer@example.test")
NIA = person(guid(9), "Nia Unlisted", "nia.unlisted@example.test")
# A member at the server's text maxima, so the layout case proves 256-character values never
# overflow. The name starts with "A" so it sorts onto the first page of document managers.
LONG_NAME = "Alexandria " + "Featherstonehaugh-Wolfeschlegelsteinhausenbergerdorff " * 4
LONG_NAME = (LONG_NAME + "x" * TEXT_MAX_LENGTH)[:TEXT_MAX_LENGTH]
LONG_EMAIL = ("alexandria." + "long" * 70)[:TEXT_MAX_LENGTH - len("@example.test")] + "@example.test"
LONG = person(guid(10), LONG_NAME, LONG_EMAIL)
FILLER = [person(guid(100 + index), f"Teammate {index:02d}", f"teammate.{index:02d}@example.test") for index in range(1, 19)]
VIEWER = person(OWNER_ID, VIEWER_NAME, VIEWER_EMAIL)


def workspace_document(viewer_role="Owner", *, status="active", pending=(PRIYA, SAM),
                       long_member=True, filler=True):
    """A stored public workspace's membership, with the viewer in `viewer_role` and a fixed cast.

    A public workspace stores its members as the owner plus `admins` and `documentManagers`; there
    is no `users[]` roster. The viewer is added to whichever list their role names.
    """
    owner = VIEWER if viewer_role == "Owner" else OMAR
    admins = [copy.deepcopy(OLIVIA)] + ([copy.deepcopy(VIEWER)] if viewer_role == "Admin" else [])
    managers = [copy.deepcopy(DMITRI), copy.deepcopy(MAYA), copy.deepcopy(LEE)]
    if viewer_role == "DocumentManager":
        managers.insert(0, copy.deepcopy(VIEWER))
    if filler:
        managers += [copy.deepcopy(entry) for entry in FILLER]
    if long_member:
        managers.append(copy.deepcopy(LONG))
    return {
        "status": status,
        "owner": {"userId": owner["userId"], "displayName": owner["displayName"], "email": owner["email"]},
        "admins": admins,
        "documentManagers": managers,
        "pendingDocumentManagers": [copy.deepcopy(entry) for entry in pending],
    }


class _Refusal(Exception):
    def __init__(self, status, message, code):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _invalid(message):
    return _Refusal(400, message, "invalid_request")


class PublicMembersFixture(PublicWorkspaceFixture):
    """A small scripted public membership boundary; no live directory, no Graph."""

    def __init__(self, page):
        super().__init__(page)
        self.active_workspace = "pub-a"
        self.names = {"pub-a": "Research library", "pub-b": "Read-only library"}
        self.workspace_docs = {}
        self.set_viewer_role("pub-a", "Owner")
        self.set_viewer_role("pub-b", "Admin", long_member=False, filler=False)
        # The tenant directory the people search reads. Public add trusts the submitted name and
        # email (the server never re-reads a directory by id for a public add), so the search only
        # needs to surface people to choose; `NORA` and `NIA` aren't members yet.
        self.directory = {entry["userId"]: {"id": entry["userId"], "displayName": entry["displayName"],
                                            "email": entry["email"]}
                          for entry in (OMAR, OLIVIA, DMITRI, MAYA, LEE, PRIYA, SAM, NORA, NIA, *FILLER)}
        self.user_search_failure = None
        self.forced_conflicts = []
        self.malformed_list = False
        self.malformed_requests = False

    # --- state a test arranges -------------------------------------------------------------

    def set_viewer_role(self, workspace_id, role, *, status="active", **options):
        """Rebuild a workspace's membership with the viewer holding `role`, and its context to match."""
        self.workspace_docs[workspace_id] = workspace_document(role, status=status, **options)
        self.denied_workspaces.discard(workspace_id)
        self._sync_context(workspace_id)
        return self.workspace_docs[workspace_id]

    def document(self, workspace_id):
        return self.workspace_docs.get(workspace_id)

    def set_status(self, workspace_id, status):
        self.workspace_docs[workspace_id]["status"] = status
        self._sync_context(workspace_id)

    def set_member_role(self, workspace_id, user_id, role):
        """A role change the server saw first."""
        document = self.workspace_docs[workspace_id]
        name, email = self._stored_identity(document, user_id)
        self._drop(document, user_id)
        key = "admins" if role == "Admin" else "documentManagers"
        document[key].append({"userId": user_id, "displayName": name, "email": email})
        self._sync_context(workspace_id)

    def remove_person(self, workspace_id, user_id):
        """A removal the server saw first."""
        self._drop(self.workspace_docs[workspace_id], user_id)
        self._sync_context(workspace_id)

    def make_owner(self, workspace_id, user_id):
        """An ownership transfer the server saw first."""
        self._transfer(self.workspace_docs[workspace_id], user_id)
        self._sync_context(workspace_id)

    def add_pending(self, workspace_id, entry):
        self.workspace_docs[workspace_id]["pendingDocumentManagers"].append(copy.deepcopy(entry))

    def add_bare_string_manager(self, workspace_id, user_id):
        """A legacy bare-string ``documentManagers`` entry (R5.5): a name and email it never had."""
        self.workspace_docs[workspace_id]["documentManagers"].append(user_id)
        self._sync_context(workspace_id)

    def approve_elsewhere(self, workspace_id, user_id):
        """An approval another manager made, or one whose answer this page never received."""
        document = self.workspace_docs[workspace_id]
        entries = [entry for entry in document["pendingDocumentManagers"] if self._entry_id(entry) == user_id]
        document["pendingDocumentManagers"] = [
            entry for entry in document["pendingDocumentManagers"] if self._entry_id(entry) != user_id
        ]
        if entries and self._role_of(document, user_id) is None:
            name, email = self._entry_name_email(entries[0])
            document["documentManagers"].append({"userId": user_id, "displayName": name, "email": email})

    def delete_workspace(self, workspace_id):
        """The workspace was deleted after the page loaded."""
        self.workspace_docs.pop(workspace_id, None)
        self.workspaces.pop(workspace_id, None)

    def force_conflict(self, method, rest):
        """Answer the next matching membership write with the guard's 409 write conflict."""
        self.forced_conflicts.append((method, rest))

    def membership_requests(self, method=None):
        return [
            entry for entry in self.requests
            if "/membership/" in entry.path and (method is None or entry.method == method)
        ]

    # --- inherited surfaces ----------------------------------------------------------------

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["user"]["display_name"] = VIEWER_NAME
        return payload

    def _sync_context(self, workspace_id):
        document = self.workspace_docs.get(workspace_id)
        if document is None:
            return
        role = self._role_of(document, OWNER_ID) or "User"
        status = document.get("status") or "active"
        self.workspaces[workspace_id] = public_context(
            workspace_id, self.names.get(workspace_id, workspace_id),
            status=status, role=role, viewer=self.viewer_id,
        )

    def _json(self, route, payload, status=200):
        # Every native membership response -- success or error -- is `no-store`, as the server's
        # `_no_store` wrapper and `public_membership_error_response` both make it.
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
            self._membership(route, entry, match.group("ws"), match.group("rest"))
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

    # --- projection, ported from functions_public_membership --------------------------------

    @staticmethod
    def _text(value):
        if isinstance(value, str):
            return value
        return "" if value is None else str(value)

    @classmethod
    def _entry_id(cls, entry):
        """The user id for an ``admins`` or ``documentManagers`` entry, dict or bare string."""
        if isinstance(entry, dict):
            user_id = entry.get("userId")
            return user_id if isinstance(user_id, str) and user_id else None
        return entry if isinstance(entry, str) and entry else None

    @classmethod
    def _entry_name_email(cls, entry):
        if isinstance(entry, dict):
            return cls._text(entry.get("displayName")), cls._text(entry.get("email"))
        return "", ""

    @classmethod
    def _entries(cls, document):
        """The members as ``{userId, displayName, email, role}``, each once at their highest role."""
        entries, seen = [], set()
        owner = document.get("owner") if isinstance(document.get("owner"), dict) else {}
        owner_id = owner.get("userId") if isinstance(owner.get("userId"), str) and owner.get("userId") else None
        if owner_id:
            seen.add(owner_id)
            entries.append({"userId": owner_id, "displayName": cls._text(owner.get("displayName")),
                            "email": cls._text(owner.get("email")), "role": "Owner"})
        for key, role in (("admins", "Admin"), ("documentManagers", "DocumentManager")):
            for entry in document.get(key) or []:
                member_id = cls._entry_id(entry)
                if member_id and member_id not in seen:
                    seen.add(member_id)
                    name, email = cls._entry_name_email(entry)
                    entries.append({"userId": member_id, "displayName": name, "email": email, "role": role})
        return entries

    @classmethod
    def _role_of(cls, document, user_id):
        for entry in cls._entries(document):
            if entry["userId"] == user_id:
                return entry["role"]
        return None

    @classmethod
    def _stored_identity(cls, document, member_id):
        for key in ("admins", "documentManagers"):
            for entry in document.get(key) or []:
                if isinstance(entry, dict) and entry.get("userId") == member_id:
                    return cls._text(entry.get("displayName")), cls._text(entry.get("email"))
        return "", ""

    @staticmethod
    def _drop(document, user_id):
        for key in ("admins", "documentManagers"):
            document[key] = [entry for entry in document.get(key) or []
                             if PublicMembersFixture._entry_id(entry) != user_id]

    def _row(self, document, entry, caller_id):
        caller_role = self._role_of(document, caller_id)
        return {
            "userId": entry["userId"],
            "displayName": self._text(entry.get("displayName")),
            "email": self._text(entry.get("email")),
            "role": entry["role"],
            "member_actions": list(POLICY.public_member_actions(
                caller_role, entry["role"], is_self=entry["userId"] == caller_id)),
        }

    def _row_for(self, document, member_id, caller_id):
        caller_role = self._role_of(document, caller_id)
        for entry in self._entries(document):
            if entry["userId"] == member_id:
                return project_member_rows([self._row(document, entry, caller_id)], caller_role)[0]
        return None

    # --- strict parsing, ported ------------------------------------------------------------

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
        if role is not None and role not in POLICY.PUBLIC_MEMBER_ROLES:
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
        if role not in POLICY.PUBLIC_ASSIGNABLE_ROLES:
            raise _invalid("The role must be Admin or DocumentManager.")
        return role

    def _body_user_id(self, body):
        user_id = body.get("userId")
        if isinstance(user_id, str):
            user_id = user_id.strip()
        return self._identifier(user_id, "user identifier")

    # --- authorization, ported -------------------------------------------------------------

    def _document_or_404(self, workspace_id):
        document = self.workspace_docs.get(workspace_id)
        if document is None:
            raise _Refusal(404, WORKSPACE_NOT_FOUND_MESSAGE, "workspace_not_found")
        return document

    def _caller_role(self, document):
        role = self._role_of(document, OWNER_ID)
        if role is None:
            raise _Refusal(403, NOT_A_MEMBER_MESSAGE, "not_a_member")
        return role

    def _manager_role(self, document):
        role = self._caller_role(document)
        if role not in POLICY.PUBLIC_MEMBERSHIP_MANAGER_ROLES:
            raise _Refusal(403, MEMBERSHIP_PERMISSION_MESSAGE, "membership_permission")
        return role

    def _require_add_allowed(self, document):
        if not POLICY.public_member_add_allowed(document):
            raise _Refusal(403, STATUS_UNAVAILABLE_MESSAGE, "public_status_unavailable")

    def _forced(self, entry, rest):
        key = (entry.method, rest)
        if key in self.forced_conflicts:
            self.forced_conflicts.remove(key)
            raise _Refusal(409, WRITE_CONFLICT_MESSAGE, WRITE_CONFLICT_CODE)

    # --- dispatch --------------------------------------------------------------------------

    def _membership(self, route, entry, workspace_id, rest):
        parts = rest.split("/")
        try:
            if parts == ["members"] and entry.method == "GET":
                payload, status = self._list(entry, workspace_id)
            elif parts == ["members"] and entry.method == "POST":
                payload, status = self._add(entry, workspace_id, rest)
            elif len(parts) == 2 and parts[0] == "members" and entry.method == "PATCH":
                payload, status = self._change_role(entry, workspace_id, parts[1], rest)
            elif len(parts) == 2 and parts[0] == "members" and entry.method == "DELETE":
                payload, status = self._remove(entry, workspace_id, parts[1], rest)
            elif parts == ["requests"] and entry.method == "GET":
                payload, status = self._requests(entry, workspace_id)
            elif len(parts) == 3 and parts[0] == "requests" and parts[2] in ("approve", "reject") and entry.method == "POST":
                payload, status = self._decide(entry, workspace_id, parts[1], parts[2], rest)
            elif parts == ["owner"] and entry.method == "PUT":
                payload, status = self._transfer_route(entry, workspace_id, rest)
            else:
                self.unexpected_requests.append(f"{entry.method} {entry.path} (no such membership route)")
                self._json(route, {"error": "Not found."}, 404)
                return
        except _Refusal as refusal:
            self._json(route, {"error": refusal.message, "error_code": refusal.code}, refusal.status)
            return
        self._json(route, payload, status)

    def _list(self, entry, workspace_id):
        search, role, page, page_size = self._list_query(entry)
        self._reject_body(entry)
        self._identifier(workspace_id, "workspace identifier")
        document = self._document_or_404(workspace_id)
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
        start = (page - 1) * page_size
        page_rows = project_member_rows(rows[start:start + page_size], caller_role)
        if self.malformed_list:
            for row in page_rows:
                row.pop("member_actions", None)
        return {
            "members": page_rows,
            "page": page,
            "page_size": page_size,
            "total_count": len(rows),
            "membership_management": {
                "schema_version": POLICY.PUBLIC_MEMBERSHIP_HINT_SCHEMA_VERSION,
                "operations": list(POLICY.public_membership_operations(caller_role, document, SETTINGS)),
            },
        }, 200

    def _requests(self, entry, workspace_id):
        self._reject_query(entry)
        self._reject_body(entry)
        self._identifier(workspace_id, "workspace identifier")
        document = self._document_or_404(workspace_id)
        self._manager_role(document)
        rows, seen = [], set()
        for item in document.get("pendingDocumentManagers") or []:
            pending_id = self._entry_id(item)
            if pending_id and pending_id not in seen:
                seen.add(pending_id)
                name, email = self._entry_name_email(item)
                rows.append({"userId": pending_id, "displayName": name, "email": email})
        rows.sort(key=lambda row: (row["displayName"].casefold(), row["userId"]))
        if self.malformed_requests:
            rows = [{"displayName": row["displayName"]} for row in rows] or [{"displayName": "No id"}]
        return {"requests": rows, "total_count": len(rows)}, 200

    def _add(self, entry, workspace_id, rest):
        self._reject_query(entry)
        self._identifier(workspace_id, "workspace identifier")
        body = self._json_object(entry)
        if any(key not in ADD_FIELDS for key in body):
            raise _invalid("Only userId, displayName, email and role can be sent when adding a member.")
        member_id = self._body_user_id(body)
        member = {
            "userId": member_id,
            "displayName": self._member_text(body, "displayName", "display name"),
            "email": self._member_text(body, "email", "email"),
        }
        new_role = self._assignable_role(body)
        document = self._document_or_404(workspace_id)
        self._manager_role(document)
        self._require_add_allowed(document)
        if self._role_of(document, member_id) is not None:
            raise _Refusal(409, ALREADY_MEMBER_MESSAGE, "already_member")
        self._forced(entry, rest)
        key = "admins" if new_role == "Admin" else "documentManagers"
        document[key].append(dict(member))
        document["pendingDocumentManagers"] = [
            item for item in document["pendingDocumentManagers"] if self._entry_id(item) != member_id
        ]
        self._sync_context(workspace_id)
        return {"member": self._row_for(document, member_id, OWNER_ID)}, 201

    def _change_role(self, entry, workspace_id, member_id, rest):
        self._reject_query(entry)
        self._identifier(workspace_id, "workspace identifier")
        self._identifier(member_id, "user identifier")
        body = self._json_object(entry)
        if any(key != "role" for key in body):
            raise _invalid("Send only the role to change a member's role.")
        new_role = self._assignable_role(body)
        document = self._document_or_404(workspace_id)
        self._manager_role(document)
        self._require_add_allowed(document)
        target_role = self._role_of(document, member_id)
        if target_role is None:
            raise _Refusal(404, MEMBER_NOT_FOUND_MESSAGE, "member_not_found")
        if target_role == "Owner":
            raise _Refusal(409, OWNER_ROLE_MESSAGE, "owner_target")
        if target_role == new_role:
            return {"member": self._row_for(document, member_id, OWNER_ID), "changed": False}, 200
        self._forced(entry, rest)
        name, email = self._stored_identity(document, member_id)
        self._drop(document, member_id)
        key = "admins" if new_role == "Admin" else "documentManagers"
        document[key].append({"userId": member_id, "displayName": name, "email": email})
        self._sync_context(workspace_id)
        return {"member": self._row_for(document, member_id, OWNER_ID), "changed": True}, 200

    def _remove(self, entry, workspace_id, member_id, rest):
        self._reject_query(entry)
        self._reject_body(entry)
        self._identifier(workspace_id, "workspace identifier")
        self._identifier(member_id, "user identifier")
        if member_id == OWNER_ID:
            raise _Refusal(403, SELF_REMOVAL_MESSAGE, "cannot_leave")
        document = self._document_or_404(workspace_id)
        self._manager_role(document)
        target_role = self._role_of(document, member_id)
        if target_role is None:
            raise _Refusal(404, MEMBER_NOT_FOUND_MESSAGE, "member_not_found")
        if target_role == "Owner":
            raise _Refusal(409, OWNER_REMOVAL_MESSAGE, "owner_target")
        self._forced(entry, rest)
        self._drop(document, member_id)
        self._sync_context(workspace_id)
        return {"userId": member_id}, 200

    def _decide(self, entry, workspace_id, member_id, decision, rest):
        self._reject_query(entry)
        self._reject_body(entry)
        self._identifier(workspace_id, "workspace identifier")
        self._identifier(member_id, "user identifier")
        document = self._document_or_404(workspace_id)
        self._manager_role(document)
        entries = [item for item in document["pendingDocumentManagers"] if self._entry_id(item) == member_id]
        if not entries:
            raise _Refusal(409, NO_PENDING_REQUEST_MESSAGE, "no_pending_request")
        self._forced(entry, rest)
        document["pendingDocumentManagers"] = [
            item for item in document["pendingDocumentManagers"] if self._entry_id(item) != member_id
        ]
        if decision == "reject":
            return {"userId": member_id}, 200
        already_member = self._role_of(document, member_id) is not None
        if not already_member:
            name, email = self._entry_name_email(entries[0])
            document["documentManagers"].append({"userId": member_id, "displayName": name, "email": email})
        self._sync_context(workspace_id)
        return {"member": self._row_for(document, member_id, OWNER_ID), "already_member": already_member}, 200

    def _transfer(self, document, new_owner_id):
        owner = document.get("owner") if isinstance(document.get("owner"), dict) else {}
        old_owner_id = owner.get("userId")
        old_name = self._text(owner.get("displayName"))
        old_email = self._text(owner.get("email"))
        new_name, new_email = self._stored_identity(document, new_owner_id)
        self._drop(document, new_owner_id)
        document["owner"] = {"userId": new_owner_id, "displayName": new_name, "email": new_email}
        if old_owner_id:
            self._drop(document, old_owner_id)
            document["documentManagers"].append({"userId": old_owner_id, "displayName": old_name, "email": old_email})

    def _transfer_route(self, entry, workspace_id, rest):
        self._reject_query(entry)
        self._identifier(workspace_id, "workspace identifier")
        body = self._json_object(entry)
        if any(key != "userId" for key in body):
            raise _invalid("Send only the userId of the new owner.")
        new_owner_id = self._body_user_id(body)
        document = self._document_or_404(workspace_id)
        owner = document.get("owner") if isinstance(document.get("owner"), dict) else {}
        current_owner_id = owner.get("userId") if isinstance(owner.get("userId"), str) else None
        if current_owner_id == new_owner_id:
            return {"owner": self._row_for(document, new_owner_id, OWNER_ID), "changed": False}, 200
        if current_owner_id != OWNER_ID:
            raise _Refusal(403, OWNER_ONLY_MESSAGE, "owner_only")
        if self._role_of(document, new_owner_id) not in ("Admin", "DocumentManager"):
            raise _Refusal(404, MEMBER_NOT_FOUND_MESSAGE, "member_not_found")
        self._forced(entry, rest)
        self._transfer(document, new_owner_id)
        self._sync_context(workspace_id)
        return {"owner": self._row_for(document, new_owner_id, OWNER_ID), "changed": True}, 200


@pytest.fixture
def public_members_ui(page):
    fixture = PublicMembersFixture(page)
    yield fixture
    fixture.assert_clean()
