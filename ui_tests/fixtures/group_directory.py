# group_directory.py
"""
Closed M7A group directory HTTP fixtures for the real production V2 SPA.
Version: 0.261.149
Implemented in: 0.261.149

The fixture serves the native group directory family the directory page reads and writes --
`GET`/`POST /api/groups/directory`, `POST`/`DELETE /api/groups/<group_id>/join-request` and the
member-only `GET /api/groups/<group_id>/logo` -- and nothing else. It models the server's rules
rather than a convenient shape: the strict query (only `view`, `search`, `page` and `page_size`,
each at most once, `view` in `all|mine|discover`), the casefolded search over name, description
and exact id, the `(casefolded name, id)` sort, the page cut after the filter, and the row shape
`{id, name, description, owner:{displayName}, member_count, heroColor, hasLogo, logoVersion,
membership}` with `userRole` only on a member row and `hasLogo` true only when a logo is stored
AND the caller is a member. Every membership write returns the server's own `{group}` row, so the
page's badge and offered action follow the server, never optimistic state.

It extends `GroupWorkspaceFixture` so the inherited bootstrap, the `/api/groups` picker list, the
`/api/v2/workspaces/group/<id>` context load a member's Open lands on, the classic-visit recorder
and the personal-scope and `/api/v2/admin/*` traps all keep working unchanged: the directory
routes are handled here first and everything else defers to `super()._dispatch`. Because the
directory page is a reserved static route, a correct build never asks the fixture to load a
`directory` group context or set an active group; the browser suite pins that.

The create and join/cancel validation is ported verbatim from `functions_group_directory` so the
reviewed 400 text and the 403/404/409 codes match the server, which the fixture-parity functional
test holds to the real routes.
"""

import base64
import copy

import pytest

from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, group_context
from ui_tests.fixtures.workspace_authoring import OWNER_ID


# A 1x1 transparent PNG, so a member row with a stored logo serves real image bytes.
_LOGO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMFAgABp9x1AAAAAElFTkSuQmCC"
)

NAME_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 500
SEARCH_MAX_LENGTH = 200
MAX_PAGE = 10000
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
CONTROL_CHARACTERS = tuple(range(0x00, 0x20)) + tuple(range(0x7F, 0xA0))

# The specials the browser suite drives, kept apart from the discovery filler.
MEMBER_GROUP = "group-a"          # a member row: Open lands on its inherited context.
LOGO_MEMBER_GROUP = "group-b"     # a member row whose stored logo makes hasLogo true.
PENDING_GROUP = "dir-pending"     # a pending row: Cancel request.
JOINABLE_GROUP = "dir-joinable"   # a none row the caller may ask to join.
SECOND_JOINABLE_GROUP = "dir-joinable-2"


def directory_record(identifier, name, *, membership="none", user_role=None, description=None,
                     member_count=1, hero_color="#0078d4", logo_stored=False, logo_version=1):
    """One stored directory group, shaped so `_project` yields the server's row."""
    return {
        "id": identifier,
        "name": name,
        "description": f"Shared workspace for {name}." if description is None else description,
        "owner_display": f"{name} owner",
        "member_count": member_count,
        "hero_color": hero_color,
        "logo_stored": logo_stored,
        "logo_version": logo_version,
        "membership": membership,
        "user_role": user_role,
    }


class GroupDirectoryFixture(GroupWorkspaceFixture):
    """A small scripted group directory; no second groups service, no live membership store."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = None
        self.can_create = True
        self.can_request_to_join = True
        # Forced, one-shot outcomes a test arranges before it drives the UI, each modelling a
        # concurrent change the server saw first. A join/cancel code is consumed on the next write to
        # that id and reconciled so the reload shows the truth; a create refusal answers the next
        # create; a reviewed create 400 answers the next create verbatim.
        self.forced_conflicts = {}
        self.create_refusal = None
        self.next_create_error = None
        self.created_group_counter = 0
        # When set, the list returns a shape the strict reader rejects, so the page must show its
        # hard load error rather than render an empty directory.
        self.malformed_list = False
        self.directory_groups = {}
        # The two inherited context groups are also member rows, so Open lands on a real context and
        # the member logo case has a group whose logo is stored.
        self._seed_directory([
            directory_record(MEMBER_GROUP, "Research group", membership="member", user_role="Owner",
                             member_count=6),
            directory_record(LOGO_MEMBER_GROUP, "Design group", membership="member", user_role="Admin",
                             member_count=4, logo_stored=True),
            directory_record(PENDING_GROUP, "Platform guild", membership="pending", member_count=9),
            directory_record(JOINABLE_GROUP, "Marketing circle", membership="none", member_count=12,
                             logo_stored=True),
            directory_record(SECOND_JOINABLE_GROUP, "Support crew", membership="none", member_count=3),
        ])
        # Enough discover-view filler that the default page still leaves a second page to prove paging.
        self._seed_directory([
            directory_record(f"dir-fill-{index:02d}", f"Directory group {index:02d}", membership="none",
                             member_count=index)
            for index in range(1, 21)
        ])

    # --- seeding --------------------------------------------------------------------------------

    def _seed_directory(self, records):
        for record in records:
            self.directory_groups[record["id"]] = record

    def set_hints(self, *, can_create=None, can_request_to_join=None):
        if can_create is not None:
            self.can_create = can_create
        if can_request_to_join is not None:
            self.can_request_to_join = can_request_to_join

    # --- projection -----------------------------------------------------------------------------

    def _project(self, record):
        membership = record["membership"]
        row = {
            "id": record["id"],
            "name": record["name"],
            "description": record["description"],
            "owner": {"displayName": record["owner_display"]},
            "member_count": record["member_count"],
            "heroColor": record["hero_color"],
            "hasLogo": bool(record["logo_stored"]) and membership == "member",
            "logoVersion": record["logo_version"],
            "membership": membership,
        }
        if membership == "member" and record["user_role"]:
            row["userRole"] = record["user_role"]
        return row

    def _hints(self):
        return {
            "schema_version": 1,
            "can_create": bool(self.can_create),
            "can_request_to_join": bool(self.can_request_to_join),
        }

    # --- strict parsing, ported from functions_group_directory ----------------------------------

    def _invalid_request(self, route, message):
        self._json(route, {"error": message, "error_code": "invalid_request"}, 400)

    def _whole_number(self, values, *, default, maximum):
        if not values:
            return default, None
        text = values[0]
        if not (text.isdigit() and text[0] != "0" and 1 <= len(text) <= 6):
            return None, "invalid"
        number = int(text)
        if number > maximum:
            return None, "invalid"
        return number, None

    # --- dispatch -------------------------------------------------------------------------------

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path == "/api/groups/directory" and method == "GET":
            self._directory_list(route, entry)
            return
        if path == "/api/groups/directory" and method == "POST":
            self._directory_create(route, entry)
            return
        if path.startswith("/api/groups/") and path.endswith("/join-request") and method in ("POST", "DELETE"):
            self._join_request(route, entry)
            return
        if path.startswith("/api/groups/") and path.endswith("/logo") and method == "GET":
            self._logo(route, entry)
            return
        super()._dispatch(route, entry)

    def _directory_list(self, route, entry):
        if self.malformed_list:
            self._json(route, {
                "groups": "not-an-array",
                "page": 1,
                "page_size": DEFAULT_PAGE_SIZE,
                "total_count": 0,
                "group_directory": self._hints(),
            })
            return
        allowed = ("view", "search", "page", "page_size")
        for key, values in entry.query.items():
            if key not in allowed:
                self._invalid_request(route, "Use only the search, view, page and page_size query parameters.")
                return
            if len(values) > 1:
                self._invalid_request(route, "Give each query parameter only once.")
                return
        view = entry.query.get("view", ["all"])[0]
        if view not in ("all", "mine", "discover"):
            self._invalid_request(route, "The view must be all, mine or discover.")
            return
        search = entry.query.get("search", [""])[0].strip()
        if len(search) > SEARCH_MAX_LENGTH:
            self._invalid_request(route, f"Search terms can be at most {SEARCH_MAX_LENGTH} characters.")
            return
        page, page_error = self._whole_number(entry.query.get("page"), default=1, maximum=MAX_PAGE)
        if page_error:
            self._invalid_request(route, f"The page must be a whole number from 1 to {MAX_PAGE}.")
            return
        page_size, size_error = self._whole_number(entry.query.get("page_size"), default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE)
        if size_error:
            self._invalid_request(route, f"The page size must be a whole number from 1 to {MAX_PAGE_SIZE}.")
            return
        needle = search.casefold()
        rows = []
        for record in self.directory_groups.values():
            row = self._project(record)
            if not self._in_view(row, view):
                continue
            if needle and not self._matches_search(row, needle):
                continue
            rows.append(row)
        rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
        start = (page - 1) * page_size
        self._json(route, {
            "groups": rows[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total_count": len(rows),
            "group_directory": self._hints(),
        })

    @staticmethod
    def _in_view(row, view):
        if view == "mine":
            return row["membership"] == "member"
        if view == "discover":
            return row["membership"] != "member"
        return True

    @staticmethod
    def _matches_search(row, needle):
        return (
            needle in row["name"].casefold()
            or needle in row["description"].casefold()
            or needle == row["id"].casefold()
        )

    def _read_create_fields(self, route, body):
        """Port of read_group_creation_fields: the reviewed 400 text, verbatim and in order."""
        if not isinstance(body, dict):
            self._invalid_request(route, "A JSON object is required for this request.")
            return None
        if any(key not in ("name", "description") for key in body):
            self._invalid_request(route, "Only a name and a description can be set when creating a group.")
            return None
        name = body.get("name")
        if name is None or (isinstance(name, str) and not name.strip()):
            self._invalid_request(route, "Enter a group name.")
            return None
        if not isinstance(name, str):
            self._invalid_request(route, "The group name must be text.")
            return None
        name = name.strip()
        if len(name) > NAME_MAX_LENGTH:
            self._invalid_request(route, f"Group names can be at most {NAME_MAX_LENGTH} characters.")
            return None
        if any(ord(char) in CONTROL_CHARACTERS for char in name):
            self._invalid_request(route, "Group names cannot contain control characters.")
            return None
        description = body.get("description", "")
        if not isinstance(description, str):
            self._invalid_request(route, "The group description must be text.")
            return None
        description = description.strip()
        if len(description) > DESCRIPTION_MAX_LENGTH:
            self._invalid_request(route, f"Group descriptions can be at most {DESCRIPTION_MAX_LENGTH} characters.")
            return None
        return name, description

    def _directory_create(self, route, entry):
        if entry.query:
            self._invalid_request(route, "This request does not accept query parameters.")
            return
        if self.create_refusal == "create_groups_role_required":
            self._json(route, {"error": "You need the CreateGroups role to create groups.",
                               "error_code": "create_groups_role_required"}, 403)
            return
        if self.create_refusal is not None:
            self._json(route, {"error": "Group creation is turned off.",
                               "error_code": "group_creation_disabled"}, 403)
            return
        fields = self._read_create_fields(route, entry.body)
        if fields is None:
            return
        if self.next_create_error is not None:
            status, code, message = self.next_create_error
            self.next_create_error = None
            self._json(route, {"error": message, "error_code": code}, status)
            return
        name, description = fields
        self.created_group_counter += 1
        identifier = f"dir-created-{self.created_group_counter}"
        record = directory_record(identifier, name, membership="member", user_role="Owner",
                                  description=description, member_count=1)
        self.directory_groups[identifier] = record
        # Register the created group so the 201's navigate-by-id lands on a real context load.
        self.groups[identifier] = group_context(identifier, name, viewer=self.viewer_id)
        self._json(route, {"group": self._project(record)}, 201)

    def _join_request(self, route, entry):
        if entry.query:
            self._invalid_request(route, "This request does not accept query parameters.")
            return
        if entry.body not in (None, "", b""):
            self._invalid_request(route, "This request does not accept a request body.")
            return
        group_id = entry.path.split("/api/groups/", 1)[1].rsplit("/join-request", 1)[0]
        forced = self.forced_conflicts.pop(group_id, None)
        if forced is not None:
            self._answer_forced_conflict(route, group_id, forced)
            return
        record = self.directory_groups.get(group_id)
        if record is None:
            self._json(route, {"error": "Group not found.", "error_code": "group_not_found"}, 404)
            return
        if entry.method == "POST":
            self._apply_join(route, record)
        else:
            self._apply_cancel(route, record)

    def _apply_join(self, route, record):
        membership = record["membership"]
        if membership == "member":
            self._json(route, {"error": "You're already a member of this group.",
                               "error_code": "already_member"}, 409)
            return
        if membership == "pending":
            self._json(route, {"error": "You've already asked to join this group.",
                               "error_code": "request_pending"}, 409)
            return
        record["membership"] = "pending"
        self._json(route, {"group": self._project(record)}, 201)

    def _apply_cancel(self, route, record):
        if record["membership"] != "pending":
            self._json(route, {"error": "You don't have a pending request to join this group.",
                               "error_code": "no_pending_request"}, 409)
            return
        record["membership"] = "none"
        self._json(route, {"group": self._project(record)}, 200)

    def _answer_forced_conflict(self, route, group_id, code):
        """Answer a one-shot forced 409/404, reconciling the stored row for the page's reload."""
        record = self.directory_groups.get(group_id)
        if code == "group_write_conflict":
            self._json(route, {"error": "The group changed while your request was being saved. Try again.",
                               "error_code": "group_write_conflict"}, 409)
            return
        if code == "group_not_found":
            self.directory_groups.pop(group_id, None)
            self._json(route, {"error": "Group not found.", "error_code": "group_not_found"}, 404)
            return
        if record is not None:
            if code == "already_member":
                record["membership"] = "member"
                record["user_role"] = record["user_role"] or "User"
            elif code == "request_pending":
                record["membership"] = "pending"
            elif code == "no_pending_request":
                record["membership"] = "none"
        messages = {
            "already_member": "You're already a member of this group.",
            "request_pending": "You've already asked to join this group.",
            "no_pending_request": "You don't have a pending request to join this group.",
        }
        self._json(route, {"error": messages[code], "error_code": code}, 409)

    def _logo(self, route, entry):
        group_id = entry.path.split("/api/groups/", 1)[1].rsplit("/logo", 1)[0]
        record = self.directory_groups.get(group_id)
        if record is None or not record["logo_stored"] or record["membership"] != "member":
            # The page requests a logo only for a member row that has one; anything else is a leak.
            self.unexpected_requests.append(f"{entry.method} {entry.path} (logo for a row without hasLogo)")
            self._json(route, {"error": "No logo."}, 404)
            return
        self.responses.append((route.request.url, "<logo bytes>"))
        route.fulfill(status=200, content_type="image/png", body=copy.copy(_LOGO_PNG))


@pytest.fixture
def group_directory_ui(page):
    fixture = GroupDirectoryFixture(page)
    yield fixture
    fixture.assert_clean()
