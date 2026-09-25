# public_directory.py
"""
Closed M9A public directory HTTP fixtures for the real production V2 SPA.
Version: 0.261.175
Implemented in: 0.261.175

The fixture serves the native public directory the directory page and the unified picker read --
`GET /api/public_workspaces/directory` and the public `GET /api/public_workspaces/<id>/logo` -- plus
the shared `/api/user/settings` store the visibility toggle writes, and nothing else. It models the
server's rules from ``functions_public_directory`` rather than a convenient shape: the strict query
(only ``view``, ``search``, ``page`` and ``page_size``, each at most once, ``view`` in ``all|mine``),
the casefolded search over name, description and exact id, the ``(casefolded name, id)`` sort, the
page cut after the filter, and the row shape ``{id, name, description, heroColor, hasLogo,
logoVersion, userRole, membership, status}`` -- with no owner and no member count, which the public
directory deliberately withholds, and ``hasLogo`` true whenever a logo is stored (a public logo is
served to any authenticated caller, unlike a group's).

It extends ``PublicWorkspaceFixture`` so the inherited bootstrap, the ``/api/v2/workspaces/public/<id>``
context a row's Open lands on, the ``setActive`` courtesy, the classic-visit recorder and the
personal-scope trap all keep working unchanged: the directory routes are handled here first and
everything else defers to ``super()._dispatch``. The directory page is a reserved static route, so a
correct build never asks the fixture to load a ``directory`` public context or set it active; the
browser suite pins that.
"""

import base64
import copy
from urllib.parse import urlsplit

import pytest

from ui_tests.fixtures.public_workspace import PublicWorkspaceFixture, public_context
from ui_tests.fixtures.workspace_authoring import OWNER_ID  # noqa: F401


# A 1x1 transparent PNG, so a row with a stored logo serves real image bytes.
_LOGO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMFAgABp9x1AAAAAElFTkSuQmCC"
)

SEARCH_MAX_LENGTH = 200
MAX_PAGE = 10000
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

# The specials the browser suite drives, kept apart from the paging filler.
MEMBER_WORKSPACE = "pub-a"            # a member row; Open lands on its inherited context.
LOGO_WORKSPACE = "pub-logo"          # a none row whose stored logo is still served publicly.
INACTIVE_WORKSPACE = "pub-inactive"  # a row a reader cannot chat; hideable, never an error.
UNKNOWN_WORKSPACE = "pub-unknown"    # a status outside the reader vocabulary, reported as unknown.
LONG_WORKSPACE = "pub-long"          # an 80-char name and a 500-char description.

MEMBER_WORKSPACE_NAME = "Research library"     # matches the inherited pub-a context name.
LOGO_WORKSPACE_NAME = "Atlas library"
INACTIVE_WORKSPACE_NAME = "Retired archive"
UNKNOWN_WORKSPACE_NAME = "Uncharted shelf"

# Exactly 80 code points and a 500-code-point description, so the long-content layout case exercises
# the real server maxima rather than a token stand-in.
LONG_WORKSPACE_NAME = "Long content workspace " + "x" * 57
LONG_WORKSPACE_DESCRIPTION = "This description fills the server's 500-character ceiling. " + "d" * 442


def directory_record(identifier, name, *, membership="none", user_role="User", description=None,
                     status="active", hero_color="#0078d4", logo_stored=False, logo_version=1):
    """One stored directory workspace, shaped so ``_project`` yields the server's row."""
    return {
        "id": identifier,
        "name": name,
        "description": f"Published knowledge for {name}." if description is None else description,
        "hero_color": hero_color,
        "logo_stored": logo_stored,
        "logo_version": logo_version,
        "membership": membership,
        "user_role": user_role,
        "status": status,
    }


class PublicDirectoryFixture(PublicWorkspaceFixture):
    """A small scripted public directory; no second workspaces service, no live role store."""

    def __init__(self, page):
        super().__init__(page)
        # When set, the list returns a shape the strict reader rejects, so the page must show its hard
        # load error rather than render an empty directory.
        self.malformed_list = False
        self.directory_workspaces = {}
        # The Open target is a member row whose id is an inherited context, so Open lands on a real
        # public workspace shell rather than a 404.
        self._seed_directory([
            directory_record(MEMBER_WORKSPACE, MEMBER_WORKSPACE_NAME, membership="member",
                             user_role="Owner"),
            directory_record(LOGO_WORKSPACE, LOGO_WORKSPACE_NAME, membership="none", logo_stored=True),
            directory_record(INACTIVE_WORKSPACE, INACTIVE_WORKSPACE_NAME, membership="none",
                             status="inactive"),
            directory_record(UNKNOWN_WORKSPACE, UNKNOWN_WORKSPACE_NAME, membership="none",
                             status="archived"),
        ])
        # Enough filler that the default page leaves a second page to prove paging.
        self._seed_directory([
            directory_record(f"pub-fill-{index:02d}", f"Directory workspace {index:02d}",
                             membership="none")
            for index in range(1, 21)
        ])
        # A long-content row so the layout case can prove an 80-character name and a 500-character
        # description never overflow at either width in either theme.
        self._seed_directory([
            directory_record(LONG_WORKSPACE, LONG_WORKSPACE_NAME, membership="none",
                             description=LONG_WORKSPACE_DESCRIPTION),
        ])
        # The Open target also needs a servable context. pub-a already ships from the base fixture; a
        # second openable context is not required, so every other row is a browse-only directory row.
        if MEMBER_WORKSPACE not in self.workspaces:
            self.workspaces[MEMBER_WORKSPACE] = public_context(MEMBER_WORKSPACE, MEMBER_WORKSPACE_NAME,
                                                               role="Owner")

    # --- seeding --------------------------------------------------------------------------------

    def _seed_directory(self, records):
        for record in records:
            self.directory_workspaces[record["id"]] = record

    def seed_visibility(self, mapping):
        """Pre-seed the shared visibility map so a scenario can start from a custom list."""
        self.preferences["publicDirectorySettings"] = copy.deepcopy(mapping)

    # --- response shaping -----------------------------------------------------------------------

    @staticmethod
    def _is_directory_route(path):
        if path == "/api/public_workspaces/directory":
            return True
        return path.startswith("/api/public_workspaces/") and path.endswith("/logo")

    def _json(self, route, payload, status=200):
        # Every native directory response -- success or error -- carries `Cache-Control: no-store`, as
        # the server's `_no_store` wrapper and `public_directory_error_response` both do. Inherited
        # bootstrap, context and picker responses keep their base handling, so only the directory
        # family gains the header, exactly as production does.
        path = urlsplit(route.request.url).path
        if not self._is_directory_route(path):
            super()._json(route, payload, status)
            return
        self.responses.append((route.request.url, copy.deepcopy(payload)))
        if status >= 400:
            self.expected_http_errors.add((route.request.url, status))
        route.fulfill(status=status, json=payload, headers={"Cache-Control": "no-store"})

    # --- projection -----------------------------------------------------------------------------

    def _project(self, record):
        status = record["status"] if record["status"] in ("active", "locked", "upload_disabled", "inactive") else "unknown"
        return {
            "id": record["id"],
            "name": record["name"],
            "description": record["description"],
            "heroColor": record["hero_color"],
            # A public logo is served to any authenticated caller, so hasLogo follows storage alone --
            # unlike a group row, which gates it on membership.
            "hasLogo": bool(record["logo_stored"]),
            "logoVersion": max(1, int(record["logo_version"])),
            "userRole": record["user_role"],
            "membership": record["membership"],
            "status": status,
        }

    def _hints(self):
        return {"schema_version": 1}

    # --- strict parsing, ported from functions_public_directory ---------------------------------

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
        if path == "/api/public_workspaces/directory" and method == "GET":
            self._directory_list(route, entry)
            return
        if path.startswith("/api/public_workspaces/") and path.endswith("/logo") and method == "GET":
            self._logo(route, entry)
            return
        super()._dispatch(route, entry)

    def _directory_list(self, route, entry):
        if self.malformed_list:
            self._json(route, {
                "workspaces": "not-an-array",
                "page": 1,
                "page_size": DEFAULT_PAGE_SIZE,
                "total_count": 0,
                "public_directory": self._hints(),
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
        if view not in ("all", "mine"):
            self._invalid_request(route, "The view must be all or mine.")
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
        for record in self.directory_workspaces.values():
            row = self._project(record)
            if not self._in_view(row, view):
                continue
            if needle and not self._matches_search(row, needle):
                continue
            rows.append(row)
        rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
        start = (page - 1) * page_size
        self._json(route, {
            "workspaces": rows[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total_count": len(rows),
            "public_directory": self._hints(),
        })

    @staticmethod
    def _in_view(row, view):
        if view == "mine":
            return row["membership"] == "member"
        return True

    @staticmethod
    def _matches_search(row, needle):
        return (
            needle in row["name"].casefold()
            or needle in row["description"].casefold()
            or needle == row["id"].casefold()
        )

    def _logo(self, route, entry):
        workspace_id = entry.path.split("/")[3]
        record = self.directory_workspaces.get(workspace_id)
        if not record or not record["logo_stored"]:
            self._json(route, {"error": "No logo is stored for this public workspace."}, 404)
            return
        self.responses.append((route.request.url, {"logo": workspace_id}))
        route.fulfill(status=200, body=_LOGO_PNG, headers={"Content-Type": "image/png", "Cache-Control": "no-store"})


@pytest.fixture
def public_directory_ui(page):
    fixture = PublicDirectoryFixture(page)
    yield fixture
    fixture.assert_clean()
