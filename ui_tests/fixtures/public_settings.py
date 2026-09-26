# public_settings.py
"""
Closed M10C public workspace Settings, Activity and Statistics HTTP fixtures for the real V2 SPA.
Version: 0.261.185
Implemented in: 0.261.185

The fixture serves the native public settings and insights family the V2 Settings, Activity and
Statistics sections read and write -- `GET /api/public-workspaces/<w>/settings`,
`PATCH .../settings/profile`, `PUT`/`DELETE .../settings/logo`, `PATCH .../settings/downloads`,
`PATCH .../settings/retention`, and `GET .../insights/activity|stats|file-count` -- plus the logo image
`GET /api/public_workspaces/<w>/logo` the previews load and the classic manage page
`/public_workspaces/<w>` the danger zone hands off to. It models the server's rules rather than a
convenient shape:

- the decision is `public_workspace.public_settings_management`, the port of
  `functions_public_settings_policy` the public context parity pin already holds to the real builder
  (including the downloads and retention switch variants), so the context's hint and every handler's
  refusal agree; each refusal carries the policy's own reviewed text, read from
  `functions_public_settings_policy.PUBLIC_SETTINGS_REFUSAL_MESSAGES`, with the unrecognized-status
  text for a profile or logo write in an `unknown` workspace, as `functions_public_settings.refusal`
  picks it;
- every route checks what the real route checks, in its order: the query first, then the workspace
  (a 404 `public_workspace_not_found`), then the decision (a 403 carrying its reason code), then the
  body (a reviewed 400) and, at the guarded write, the section revision (a 409
  `public_workspace_settings_changed`);
- the settings read carries `downloads` only while the administrator allows this workspace's downloads,
  and `retention` only while public retention is on, exactly as `build_public_settings` does;
- a profile, logo or downloads write rebuilds the served context from `public_context` with the new
  values, so the next context read shows the header, the download permission and the download
  operation the server would, and the written values survive any later rebuild (a role or status
  change);
- the activity, statistics and file-count reads answer only the roles the decision allows, and an
  unavailable store answers with the reviewed 503 and its code;
- every settings and insights response, success or error, carries `Cache-Control: no-store`.

Only the write conflict (`public_workspace_write_conflict`), a stale revision the page never sent and a
reviewed 400, which no single state models, are scripted. The classic public settings routes -- the
workspace PATCH/PUT/DELETE, the classic logo writes, `download-settings`, the classic retention route,
`/activity`, `/stats`, `/fileCount` and `/promptCount` -- are trapped as unexpected: the native sections
must never call them. `functional_tests/test_public_settings_fixture_parity.py` holds every shape,
status, code and message here to the real routes.
"""

import ast
import base64
import copy
import re
from datetime import date, timedelta
from email import policy as email_policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import pytest

from ui_tests.fixtures.public_workspace import (
    PUBLIC_SETTINGS_OPERATIONS, PublicWorkspaceFixture, public_context, public_settings_management,
)


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"


def _app_constant(file_name, name):
    """A reviewed module-level constant of an application module, read from its source.

    The settings, insights and workspace modules build Cosmos clients through ``config`` when they are
    imported, so their texts are read here instead: literals, tuples, dicts whose keys name earlier
    constants, ``date(...)`` and f-strings built from earlier constants.
    """
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    values = {}

    def evaluate(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(evaluate(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {evaluate(key): evaluate(value) for key, value in zip(node.keys, node.values)}
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "date":
            return date(*(evaluate(argument) for argument in node.args))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = evaluate(node.func.value)
            if node.func.attr == "isoformat" and not node.args and not node.keywords:
                return value.isoformat()
        if isinstance(node, ast.JoinedStr):
            parts = []
            for part in node.values:
                if isinstance(part, ast.Constant):
                    parts.append(str(part.value))
                elif isinstance(part, ast.FormattedValue):
                    parts.append(str(evaluate(part.value)))
                else:
                    raise ValueError(f"Unsupported f-string node: {ast.dump(part)}")
            return "".join(parts)
        return ast.literal_eval(node)

    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return evaluate(node.value)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = evaluate(node.value)
            except (ValueError, SyntaxError):
                pass
    raise LookupError(f"{file_name} defines no literal {name}")


# The reviewed texts and codes, read from the modules that send them.
PUBLIC_SETTINGS_REFUSAL_MESSAGES = _app_constant(
    "functions_public_settings_policy.py", "PUBLIC_SETTINGS_REFUSAL_MESSAGES",
)
PUBLIC_OWNER_REQUIRED = _app_constant("functions_public_settings_policy.py", "PUBLIC_OWNER_REQUIRED")
PUBLIC_MANAGER_REQUIRED = _app_constant("functions_public_settings_policy.py", "PUBLIC_MANAGER_REQUIRED")
PUBLIC_MEMBER_REQUIRED = _app_constant("functions_public_settings_policy.py", "PUBLIC_MEMBER_REQUIRED")
PUBLIC_STATUS_UNAVAILABLE = _app_constant("functions_public_settings_policy.py", "PUBLIC_STATUS_UNAVAILABLE")
PUBLIC_NOT_FOUND_MESSAGE = _app_constant("functions_public_settings.py", "PUBLIC_NOT_FOUND_MESSAGE")
PUBLIC_SETTINGS_CHANGED_MESSAGE = _app_constant("functions_public_settings.py", "PUBLIC_SETTINGS_CHANGED_MESSAGE")
PUBLIC_LOGO_UNREADABLE_MESSAGE = _app_constant("functions_public_settings.py", "PUBLIC_LOGO_UNREADABLE_MESSAGE")
NO_PUBLIC_LOGO_MESSAGE = _app_constant("functions_public_settings.py", "NO_PUBLIC_LOGO_MESSAGE")
PUBLIC_STATUS_UNRECOGNIZED_MESSAGE = _app_constant(
    "functions_public_settings.py", "PUBLIC_STATUS_UNRECOGNIZED_MESSAGE",
)
PUBLIC_NAME_MAX_LENGTH = _app_constant("functions_public_settings.py", "PUBLIC_NAME_MAX_LENGTH")
PUBLIC_DESCRIPTION_MAX_LENGTH = _app_constant("functions_public_settings.py", "PUBLIC_DESCRIPTION_MAX_LENGTH")
PUBLIC_ACTIVITY_LIMITS = _app_constant("functions_public_insights.py", "PUBLIC_ACTIVITY_LIMITS")
PUBLIC_ACTIVITY_DEFAULT_LIMIT = _app_constant("functions_public_insights.py", "PUBLIC_ACTIVITY_DEFAULT_LIMIT")
PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE = _app_constant(
    "functions_public_insights.py", "PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE",
)
PUBLIC_STATS_UNAVAILABLE_MESSAGE = _app_constant("functions_public_insights.py", "PUBLIC_STATS_UNAVAILABLE_MESSAGE")
PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE = _app_constant(
    "functions_public_workspaces.py", "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE",
)
PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE = _app_constant(
    "functions_public_workspaces.py", "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE",
)
ALLOWED_STATS_WINDOW_DAYS = _app_constant("functions_stats_windows.py", "ALLOWED_STATS_WINDOW_DAYS")
DEFAULT_STATS_WINDOW_DAYS = _app_constant("functions_stats_windows.py", "DEFAULT_STATS_WINDOW_DAYS")
STATS_EARLIEST_CUSTOM_DATE = _app_constant("functions_stats_windows.py", "STATS_EARLIEST_CUSTOM_DATE")
STATS_LATEST_CUSTOM_DATE = _app_constant("functions_stats_windows.py", "STATS_LATEST_CUSTOM_DATE")
STATS_DATE_RANGE_MESSAGE = _app_constant("functions_stats_windows.py", "STATS_DATE_RANGE_MESSAGE")
STATS_MAX_CUSTOM_DAYS = _app_constant("functions_stats_windows.py", "STATS_MAX_CUSTOM_DAYS")
# functions_public_settings's strict-request messages.
NO_QUERY_MESSAGE = "This request does not accept query parameters."
JSON_OBJECT_MESSAGE = "A JSON object is required for this request."
REVISION_REQUIRED_MESSAGE = "Include the revision of the settings you loaded."
NAME_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# The retention bounds and organization defaults this suite's deployment gives build_public_settings.
RETENTION_BOUNDS = {"min_days": 1, "max_days": 3650}
ORGANIZATION_DEFAULTS = {"conversation_retention_days": "none", "document_retention_days": 30}

_SETTINGS_ROUTE = re.compile(
    r"^/api/public-workspaces/(?P<ws>[^/]+)/(?P<family>settings|insights)(?:/(?P<rest>[^/]+))?$"
)
_LOGO_IMAGE_ROUTE = re.compile(r"^/api/public_workspaces/(?P<ws>[^/]+)/logo$")
_CLASSIC_SETTINGS_ROUTE = re.compile(
    r"^/api/public_workspaces/[^/]+/(download-settings|activity|stats|fileCount|promptCount)$"
    r"|^/api/retention-policy/public/[^/]+$"
)
_CLASSIC_MANAGE_PAGE = re.compile(r"^/public_workspaces/(?P<ws>[^/]+)$")

# A tiny valid PNG the logo image route serves once a workspace carries a logo, so the previews' <img>
# resolves rather than failing the run on a broken image.
_LOGO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _PublicSettingsRefusal(Exception):
    """A refusal carrying the reviewed message, status and error_code, raised where the route raises."""

    def __init__(self, message, status, error_code):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_code = error_code


def _refuse(message, status, error_code):
    raise _PublicSettingsRefusal(message, status, error_code)


def _invalid(message):
    _refuse(message, 400, "invalid_request")


def settings_decisions(role, status, *, downloads_admin=True, retention_enabled=False):
    """``{operation: None or reason}``, from the same port the context's settings_management uses."""
    management = public_settings_management(
        role, status, downloads_admin=downloads_admin, retention_enabled=retention_enabled,
    )
    return {operation: management["reasons"].get(operation) for operation in PUBLIC_SETTINGS_OPERATIONS}


def read_activity_limit(query):
    """``read_activity_limit``: only ``limit``, once, and one of the accepted values."""
    for key, values in query.items():
        if key != "limit":
            _invalid("Use only the limit query parameter.")
        if len(values) > 1:
            _invalid("Give each query parameter only once.")
    raw = query.get("limit", [None])[0]
    if raw is None:
        return PUBLIC_ACTIVITY_DEFAULT_LIMIT
    if not re.fullmatch(r"[1-9][0-9]{0,5}", raw) or int(raw) not in PUBLIC_ACTIVITY_LIMITS:
        _invalid("The limit must be 10, 20 or 50.")
    return int(raw)


def read_stats_window(query):
    """``read_stats_window`` and the shared bounded resolver, with the classic labels.

    A preset window ends on a fixed day so the served series is deterministic; a custom one reports the
    server's short-date label.
    """
    allowed = ("days", "start_date", "end_date")
    for key, values in query.items():
        if key not in allowed:
            _invalid("Use only the days, start_date and end_date query parameters.")
        if len(values) > 1:
            _invalid("Give each query parameter only once.")
    custom = "start_date" in query or "end_date" in query
    if custom and "days" in query:
        _invalid("Use days or a start_date and end_date, not both.")
    if custom:
        start_raw = (query.get("start_date", [""])[0] or "").strip()
        end_raw = (query.get("end_date", [""])[0] or "").strip()
        for field, raw in (("start_date", start_raw), ("end_date", end_raw)):
            if not raw:
                _invalid(f"{field} is required.")
        try:
            start = date.fromisoformat(start_raw)
        except ValueError:
            _invalid("start_date must use YYYY-MM-DD format.")
        try:
            end = date.fromisoformat(end_raw)
        except ValueError:
            _invalid("end_date must use YYYY-MM-DD format.")
        if start > end:
            _invalid("start_date must be before or equal to end_date.")
        if start < STATS_EARLIEST_CUSTOM_DATE or end > STATS_LATEST_CUSTOM_DATE:
            _invalid(STATS_DATE_RANGE_MESSAGE)
        days = (end - start).days + 1
        if days > STATS_MAX_CUSTOM_DAYS:
            _invalid(f"Choose a date range of {STATS_MAX_CUSTOM_DAYS} days or fewer.")
        label = f"{start.month}/{start.day}/{start.year} - {end.month}/{end.day}/{end.year}"
        return {"type": "custom", "days": days, "label": label, "start": start, "end": end}
    if "days" in query:
        raw = query.get("days", [None])[0]
        if not re.fullmatch(r"[1-9][0-9]{0,5}", raw or "") or int(raw) not in ALLOWED_STATS_WINDOW_DAYS:
            _invalid("The days must be 7, 30 or 90.")
        days = int(raw)
    else:
        days = DEFAULT_STATS_WINDOW_DAYS
    end = date(2024, 5, 30)
    start = end - timedelta(days=days - 1)
    return {"type": "days", "days": days, "label": f"Last {days} Days", "start": start, "end": end}


class PublicSettingsFixture(PublicWorkspaceFixture):
    """A scripted public settings boundary on top of the public shell fixture."""

    def __init__(self, page):
        super().__init__(page)
        self.native_settings = {}
        self.settings_revisions = {}
        self.settings_flags_by_id = {}
        self.public_activity = {}
        self.public_stats = {}
        self.public_file_count = {}
        self.activity_unavailable = set()
        self.stats_unavailable = set()
        self.settings_force_changed = set()
        self.settings_force_write_conflict = set()
        self.next_settings_write_error = None
        self.labels = None
        for workspace_id in list(self.workspaces):
            self._seed_settings(workspace_id)
        # The Settings suite models a deployment with the administrator's public downloads and public
        # retention both on, so both cards render unless a test turns one off, and the viewer owns
        # pub-a. pub-b stays the base fixture's reader context.
        self.configure("pub-a", role="Owner", status="active")
        self.active_workspace = "pub-a"

    # --- state a test arranges -------------------------------------------------------------

    def configure(self, workspace_id="pub-a", *, role="Owner", status="active", **flags):
        """Rebuild a workspace's context for `role`, `status` and the deployment switches.

        The handlers read the same role, status and switches, so the context's settings_management and
        the routes' answers stay in step. This suite's deployment has downloads and retention on, so
        both default on and a test turns off just the one it is proving.
        """
        self.settings_flags_by_id[workspace_id] = {"downloads_admin": True, "retention_enabled": True, **flags}
        if workspace_id not in self.native_settings:
            name = self.workspaces[workspace_id]["workspace"]["name"] if workspace_id in self.workspaces else "Research library"
            self.workspaces[workspace_id] = public_context(workspace_id, name, role=role, status=status, viewer=self.viewer_id)
            self._seed_settings(workspace_id)
        self._rebuild_context(workspace_id, role=role, status=status)
        return self.workspaces[workspace_id]

    def set_labels(self, **labels):
        """Serve an administrator's custom public workspace label in the bootstrap settings."""
        self.labels = {"is_custom": True, "max_length": 32, **labels}

    def set_logo_present(self, workspace_id="pub-a", *, version=1):
        store = self.native_settings[workspace_id]
        store["has_logo"] = True
        store["logo_version"] = max(1, version)
        self._rebuild_context(workspace_id)

    def set_activity(self, workspace_id, items):
        self.public_activity[workspace_id] = copy.deepcopy(items)

    def clear_activity(self, workspace_id="pub-a"):
        self.public_activity[workspace_id] = []

    def make_activity_unavailable(self, workspace_id="pub-a"):
        self.activity_unavailable.add(workspace_id)

    def set_stats(self, workspace_id, figures):
        self.public_stats[workspace_id] = copy.deepcopy(figures)

    def make_stats_unavailable(self, workspace_id="pub-a"):
        self.stats_unavailable.add(workspace_id)

    def set_file_count(self, workspace_id, count):
        self.public_file_count[workspace_id] = count

    def force_settings_changed(self, workspace_id="pub-a"):
        """Answer the next write with the 409 `public_workspace_settings_changed`, moving the revision on."""
        self.settings_force_changed.add(workspace_id)

    def force_write_conflict(self, workspace_id="pub-a"):
        """Answer the next write with the plain-retry 409 `public_workspace_write_conflict`."""
        self.settings_force_write_conflict.add(workspace_id)

    def next_write_error(self, message):
        """Refuse the next write with a reviewed 400 carrying `message`."""
        self.next_settings_write_error = message

    def settings_requests(self, method=None, section=None):
        suffix = "/settings" if section is None else f"/settings/{section}"
        return [
            entry for entry in self.requests
            if entry.path.startswith("/api/public-workspaces/") and entry.path.endswith(suffix)
            and (method is None or entry.method == method)
        ]

    def insight_requests(self, name, method="GET"):
        return [
            entry for entry in self.requests
            if entry.path.startswith("/api/public-workspaces/") and entry.path.endswith(f"/insights/{name}")
            and entry.method == method
        ]

    def context_requests(self, workspace_id="pub-a"):
        return [
            entry for entry in self.requests
            if entry.method == "GET" and entry.path == f"/api/v2/workspaces/public/{workspace_id}"
        ]

    def set_active_requests(self):
        return [
            entry for entry in self.requests
            if entry.method == "PATCH" and entry.path == "/api/public_workspaces/setActive"
        ]

    # --- the modelled workspace ---------------------------------------------------------------

    def _seed_settings(self, workspace_id):
        profile = self.workspaces[workspace_id]["workspace"]
        self.native_settings[workspace_id] = {
            "name": profile["name"],
            "description": profile["description"],
            "hero_color": profile["hero_color"],
            "has_logo": bool(profile.get("logo_url")),
            # get_workspace_logo_metadata floors logoVersion at 1, so even a workspace without a logo
            # never reports 0.
            "logo_version": 1,
            "disable_file_downloads": False,
            "retention": {"conversation_retention_days": "default", "document_retention_days": "default"},
        }
        for section in ("profile", "logo", "downloads", "retention"):
            self.settings_revisions[(workspace_id, section)] = 0
        # A small, deterministic feed and figures so the views render real content without a live app.
        owner_name = f"{profile['name']} owner"
        self.public_activity[workspace_id] = [
            {"id": f"{workspace_id}-activity-1", "occurred_at": "2024-05-02T09:00:00Z",
             "type": "document_creation", "summary": "Uploaded a document",
             "actor": {"kind": "member", "display_name": owner_name}},
            {"id": f"{workspace_id}-activity-2", "occurred_at": "2024-05-01T12:00:00Z",
             "type": "conversation_creation", "summary": "Started a conversation",
             "actor": {"kind": "non_member"}},
            {"id": f"{workspace_id}-activity-3", "occurred_at": "2024-05-01T09:00:00Z",
             "type": "token_usage", "summary": "Used 8 tokens in chat",
             "actor": {"kind": "system"}},
        ]
        self.public_stats[workspace_id] = {
            "totalDocuments": 3, "storageUsed": 4096, "totalTokens": 256, "totalMembers": 3,
            "storage": {"ai_search_size": 1024, "storage_account_size": 4096},
        }
        self.public_file_count[workspace_id] = 3

    def _flags(self, workspace_id):
        flags = {"downloads_admin": True, "retention_enabled": False}
        flags.update(self.settings_flags_by_id.get(workspace_id, {}))
        return flags

    def _rebuild_context(self, workspace_id, *, role=None, status=None):
        """Rebuild the served context from `public_context` with the stored settings.

        The server builds every context from the workspace it reads, so a profile, logo or downloads
        write -- or any later role or status change -- shows up in the next context read, never reverted.
        """
        current = self.workspaces[workspace_id]
        store = self.native_settings[workspace_id]
        flags = self._flags(workspace_id)
        context = public_context(
            workspace_id, store["name"], role=role or current["role"], status=status or current["status"],
            viewer=self.viewer_id,
            allow_public_workspace_file_downloads=flags["downloads_admin"],
            enable_retention_policy_public=flags["retention_enabled"],
            disable_file_downloads=store["disable_file_downloads"],
        )
        context["workspace"].update({
            "name": store["name"],
            "description": store["description"],
            "hero_color": store["hero_color"],
            "logo_url": (
                f"/api/public_workspaces/{quote(workspace_id, safe='')}/logo?v={store['logo_version']}"
                if store["has_logo"] else None
            ),
        })
        self.workspaces[workspace_id] = context

    def _revision(self, workspace_id, section):
        return f"{section}-{self.settings_revisions[(workspace_id, section)]}"

    def _advance_revision(self, workspace_id, section):
        self.settings_revisions[(workspace_id, section)] += 1

    def _build_settings_read(self, workspace_id):
        """``build_public_settings`` for the caller's role in this workspace."""
        context = self.workspaces[workspace_id]
        role, status = context["role"], context["status"]
        flags = self._flags(workspace_id)
        store = self.native_settings[workspace_id]
        read = {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "viewer_role": role,
            "status": status,
            "profile": {
                "name": store["name"],
                "description": store["description"],
                "hero_color": store["hero_color"],
                "revision": self._revision(workspace_id, "profile"),
            },
            "logo": {
                "has_logo": store["has_logo"],
                "logo_version": store["logo_version"],
                "logo_url": (
                    f"/api/public_workspaces/{quote(workspace_id, safe='')}/logo?v={store['logo_version']}"
                    if store["has_logo"] else None
                ),
                "revision": self._revision(workspace_id, "logo"),
            },
            "settings_management": public_settings_management(
                role, status, downloads_admin=flags["downloads_admin"], retention_enabled=flags["retention_enabled"],
            ),
        }
        if flags["downloads_admin"]:
            read["downloads"] = {
                "disable_file_downloads": store["disable_file_downloads"],
                "file_downloads_enabled": not store["disable_file_downloads"],
                "revision": self._revision(workspace_id, "downloads"),
            }
        if flags["retention_enabled"]:
            read["retention"] = {
                "conversation_retention_days": store["retention"]["conversation_retention_days"],
                "document_retention_days": store["retention"]["document_retention_days"],
                "bounds": {
                    "conversation": dict(RETENTION_BOUNDS),
                    "document": dict(RETENTION_BOUNDS),
                },
                "organization_defaults": dict(ORGANIZATION_DEFAULTS),
                "revision": self._revision(workspace_id, "retention"),
            }
        return read

    # --- serving ------------------------------------------------------------------------------

    def _bootstrap(self):
        payload = super()._bootstrap()
        if self.labels is not None:
            payload["settings"]["public_workspace_labels"] = copy.deepcopy(self.labels)
        return payload

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        path = unquote(parsed.path)
        if route.request.method == "GET" and _CLASSIC_MANAGE_PAGE.fullmatch(path):
            # The Settings danger zone's handoff to the classic manage page, recorded with the active
            # workspace the page confirmed before leaving.
            self.classic_visits.append((path, self.active_workspace))
            route.fulfill(content_type="text/html", body="<html><body>Classic handoff target</body></html>")
            return
        super()._route(route)

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        match = _SETTINGS_ROUTE.fullmatch(path)
        if match:
            try:
                if match.group("family") == "settings":
                    payload = self._resolve_settings(route, entry, match.group("ws"), match.group("rest"))
                else:
                    payload = self._resolve_insights(entry, match.group("ws"), match.group("rest"))
            except _PublicSettingsRefusal as refusal:
                self._settings_json(route, {"error": refusal.message, "error_code": refusal.error_code}, refusal.status)
                return
            self._settings_json(route, payload)
            return
        logo = _LOGO_IMAGE_ROUTE.fullmatch(path)
        if logo and method == "GET":
            self._logo_image(route, logo.group("ws"))
            return
        if (
            _CLASSIC_SETTINGS_ROUTE.fullmatch(path)
            or (logo and method != "GET")
            or (
                re.fullmatch(r"/api/public_workspaces/[^/]+", path) and method in ("PATCH", "PUT", "DELETE")
                and path != "/api/public_workspaces/setActive"
            )
        ):
            self.unexpected_requests.append(f"{method} {path} (a classic settings route from the native sections)")
            self._json(route, {"error": "Classic settings routes are not available to the native sections."}, 500)
            return
        super()._dispatch(route, entry)

    def _settings_json(self, route, payload, status=200):
        """Fulfill a settings or insights response with the routes' no-store header, and record it."""
        self.responses.append((route.request.url, copy.deepcopy(payload)))
        if status >= 400:
            self.expected_http_errors.add((route.request.url, status))
        route.fulfill(status=status, json=payload,
                      headers={"Cache-Control": "no-store", "Content-Type": "application/json"})

    def _logo_image(self, route, workspace_id):
        store = self.native_settings.get(workspace_id)
        if not store or not store["has_logo"]:
            self.expected_http_errors.add((route.request.url, 404))
            route.fulfill(status=404, body=b"", headers={"Cache-Control": "no-store"})
            return
        route.fulfill(status=200, body=_LOGO_PNG, content_type="image/png", headers={"Cache-Control": "no-store"})

    def _load(self, workspace_id):
        """The workspace's context, or the 404 the route raises first; every signed-in caller has a role."""
        if workspace_id not in self.workspaces or workspace_id not in self.native_settings:
            _refuse(PUBLIC_NOT_FOUND_MESSAGE, 404, "public_workspace_not_found")
        return self.workspaces[workspace_id]

    def _require(self, workspace_id, operation):
        context = self.workspaces[workspace_id]
        flags = self._flags(workspace_id)
        reason = settings_decisions(
            context["role"], context["status"],
            downloads_admin=flags["downloads_admin"], retention_enabled=flags["retention_enabled"],
        )[operation]
        if reason is None:
            return
        message = PUBLIC_SETTINGS_REFUSAL_MESSAGES[reason]
        if reason == PUBLIC_STATUS_UNAVAILABLE and context["status"] == "unknown":
            message = PUBLIC_STATUS_UNRECOGNIZED_MESSAGE
        _refuse(message, 403, reason)

    def _check_write(self, workspace_id, section, revision):
        """The scripted or natural outcome of the guarded write, in the server's order."""
        if self.next_settings_write_error is not None:
            message, self.next_settings_write_error = self.next_settings_write_error, None
            _invalid(message)
        if workspace_id in self.settings_force_write_conflict:
            self.settings_force_write_conflict.discard(workspace_id)
            _refuse(PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE, 409, PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE)
        if workspace_id in self.settings_force_changed:
            self.settings_force_changed.discard(workspace_id)
            # The section moves on, so the page's re-read carries a fresh revision its retry sends.
            self._advance_revision(workspace_id, section)
            _refuse(PUBLIC_SETTINGS_CHANGED_MESSAGE, 409, "public_workspace_settings_changed")
        if revision != self._revision(workspace_id, section):
            _refuse(PUBLIC_SETTINGS_CHANGED_MESSAGE, 409, "public_workspace_settings_changed")

    def _read_body(self, entry, allowed_fields, unknown_message):
        body = entry.body
        if not isinstance(body, dict):
            _invalid(JSON_OBJECT_MESSAGE)
        if any(key not in ("revision", *allowed_fields) for key in body):
            _invalid(unknown_message)
        revision = body.get("revision")
        if not isinstance(revision, str) or not revision:
            _invalid(REVISION_REQUIRED_MESSAGE)
        return body, revision

    def _resolve_settings(self, route, entry, workspace_id, section):
        method = entry.method
        if entry.query:
            _invalid(NO_QUERY_MESSAGE)
        context = self._load(workspace_id)
        if method == "GET" and section is None:
            if context["role"] not in ("Owner", "Admin"):
                _refuse(PUBLIC_SETTINGS_REFUSAL_MESSAGES[PUBLIC_MANAGER_REQUIRED], 403, PUBLIC_MANAGER_REQUIRED)
            return {"settings": self._build_settings_read(workspace_id)}
        if method == "PATCH" and section == "profile":
            return self._write_profile(workspace_id, entry)
        if method == "PUT" and section == "logo":
            return self._replace_logo(route, workspace_id)
        if method == "DELETE" and section == "logo":
            return self._remove_logo(workspace_id, entry)
        if method == "PATCH" and section == "downloads":
            return self._write_downloads(workspace_id, entry)
        if method == "PATCH" and section == "retention":
            return self._write_retention(workspace_id, entry)
        self.unexpected_requests.append(f"{method} {entry.path}")
        _refuse("Unexpected public settings request.", 500, "public_workspace_settings_unavailable")

    def _validated_name(self, value, stored):
        if value == stored:
            return value
        if value is None or (isinstance(value, str) and not value.strip()):
            _invalid("Enter a workspace name.")
        if not isinstance(value, str):
            _invalid("The workspace name must be text.")
        value = value.strip()
        if len(value) > PUBLIC_NAME_MAX_LENGTH:
            _invalid(f"Workspace names can be at most {PUBLIC_NAME_MAX_LENGTH} characters.")
        if NAME_CONTROL_CHARACTERS.search(value):
            _invalid("Workspace names cannot contain control characters.")
        return value

    def _validated_description(self, value, stored):
        if value == stored:
            return value
        if not isinstance(value, str):
            _invalid("The workspace description must be text.")
        value = value.strip()
        if len(value) > PUBLIC_DESCRIPTION_MAX_LENGTH:
            _invalid(f"Workspace descriptions can be at most {PUBLIC_DESCRIPTION_MAX_LENGTH} characters.")
        return value

    def _write_profile(self, workspace_id, entry):
        for operation in ("edit_name", "edit_description", "edit_color"):
            self._require(workspace_id, operation)
        body, revision = self._read_body(
            entry, ("name", "description", "hero_color"),
            "Only the name, description and hero_color can be changed here.",
        )
        if not any(field in body for field in ("name", "description", "hero_color")):
            _invalid("Include a name, description or hero_color to change.")
        store = self.native_settings[workspace_id]
        changes = {}
        if "name" in body:
            changes["name"] = self._validated_name(body["name"], store["name"])
        if "description" in body:
            changes["description"] = self._validated_description(body["description"], store["description"])
        if "hero_color" in body:
            hero = body["hero_color"]
            if not isinstance(hero, str):
                _invalid("The hero color must be text, such as #0078d4.")
            changes["hero_color"] = hero if re.fullmatch(r"#[0-9a-fA-F]{6}", hero) else store["hero_color"]
        self._check_write(workspace_id, "profile", revision)
        store.update(changes)
        self._advance_revision(workspace_id, "profile")
        self._rebuild_context(workspace_id)
        return {"settings": self._build_settings_read(workspace_id)}

    def _parse_logo_upload(self, route):
        """The revision of a multipart logo upload, refused as `_read_logo_upload` and `_prepared_logo` do."""
        request = route.request
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/form-data"):
            _invalid("Upload the logo as multipart form data with a logo_file and the logo revision.")
        message = BytesParser(policy=email_policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
            + (request.post_data_buffer or b"")
        )
        form, files = {}, {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                files.setdefault(name, []).append({
                    "filename": part.get_filename(), "content": part.get_payload(decode=True) or b"",
                })
            else:
                form.setdefault(name, []).append(part.get_content())
        if set(form) - {"revision"} or set(files) - {"logo_file"}:
            _invalid("Only a logo_file and the logo revision can be sent.")
        if len(form.get("revision", [])) > 1 or len(files.get("logo_file", [])) > 1:
            _invalid("Send one logo_file and one revision.")
        revision = (form.get("revision") or [None])[0]
        if not isinstance(revision, str) or not revision:
            _invalid(REVISION_REQUIRED_MESSAGE)
        upload = (files.get("logo_file") or [{"filename": "", "content": b""}])[0]
        if not upload["filename"]:
            _invalid("Choose a PNG or JPEG image for the logo.")
        if not upload["filename"].lower().endswith((".png", ".jpg", ".jpeg")):
            _invalid("The logo must be a PNG or JPEG image.")
        content = upload["content"]
        if not (content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")):
            _invalid(PUBLIC_LOGO_UNREADABLE_MESSAGE)
        return revision

    def _replace_logo(self, route, workspace_id):
        self._require(workspace_id, "edit_logo")
        revision = self._parse_logo_upload(route)
        self._check_write(workspace_id, "logo", revision)
        store = self.native_settings[workspace_id]
        store["has_logo"] = True
        store["logo_version"] = max(1, store["logo_version"]) + 1
        self._advance_revision(workspace_id, "logo")
        self._rebuild_context(workspace_id)
        return {"settings": self._build_settings_read(workspace_id)}

    def _remove_logo(self, workspace_id, entry):
        self._require(workspace_id, "edit_logo")
        _body, revision = self._read_body(entry, (), "Only the logo revision can be sent to remove the logo.")
        self._check_write(workspace_id, "logo", revision)
        store = self.native_settings[workspace_id]
        if not store["has_logo"]:
            _refuse(NO_PUBLIC_LOGO_MESSAGE, 409, "no_public_workspace_logo")
        store["has_logo"] = False
        store["logo_version"] = max(1, store["logo_version"]) + 1
        self._advance_revision(workspace_id, "logo")
        self._rebuild_context(workspace_id)
        return {"settings": self._build_settings_read(workspace_id)}

    def _write_downloads(self, workspace_id, entry):
        self._require(workspace_id, "edit_downloads")
        body, revision = self._read_body(
            entry, ("disable_file_downloads",), "Only disable_file_downloads can be changed here.",
        )
        disabled = body.get("disable_file_downloads")
        if not isinstance(disabled, bool):
            _invalid("Set disable_file_downloads to true or false.")
        self._check_write(workspace_id, "downloads", revision)
        self.native_settings[workspace_id]["disable_file_downloads"] = disabled
        self._advance_revision(workspace_id, "downloads")
        self._rebuild_context(workspace_id)
        return {"settings": self._build_settings_read(workspace_id)}

    def _retention_value(self, field, value):
        label = "Conversation" if field.startswith("conversation") else "Document"
        if isinstance(value, str) and value in ("none", "default"):
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            _invalid(f'{label} retention must be a whole number of days, "none" or "default".')
        if value < RETENTION_BOUNDS["min_days"] or value > RETENTION_BOUNDS["max_days"]:
            _invalid(
                f"{label} retention must be between {RETENTION_BOUNDS['min_days']} and "
                f"{RETENTION_BOUNDS['max_days']} days."
            )
        return value

    def _write_retention(self, workspace_id, entry):
        self._require(workspace_id, "edit_retention")
        fields = ("conversation_retention_days", "document_retention_days")
        body, revision = self._read_body(
            entry, fields, "Only conversation_retention_days and document_retention_days can be changed here.",
        )
        values = {field: self._retention_value(field, body[field]) for field in fields if field in body}
        if not values:
            _invalid("Include conversation_retention_days or document_retention_days to change.")
        self._check_write(workspace_id, "retention", revision)
        self.native_settings[workspace_id]["retention"].update(values)
        self._advance_revision(workspace_id, "retention")
        return {"settings": self._build_settings_read(workspace_id)}

    def _resolve_insights(self, entry, workspace_id, name):
        if entry.method != "GET":
            self.unexpected_requests.append(f"{entry.method} {entry.path}")
            _refuse("Unexpected public insights request.", 500, "public_workspace_settings_unavailable")
        if name == "activity":
            limit = read_activity_limit(entry.query)
            self._load(workspace_id)
            self._require(workspace_id, "view_activity")
            if workspace_id in self.activity_unavailable:
                _refuse(PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE, 503, "public_workspace_activity_unavailable")
            return {"activity": copy.deepcopy(self.public_activity.get(workspace_id, [])[:limit]), "limit": limit}
        if name == "stats":
            window = read_stats_window(entry.query)
            self._load(workspace_id)
            self._require(workspace_id, "view_stats")
            if workspace_id in self.stats_unavailable:
                _refuse(PUBLIC_STATS_UNAVAILABLE_MESSAGE, 503, "public_workspace_stats_unavailable")
            return {"stats": self._build_stats(workspace_id, window)}
        if name == "file-count":
            if entry.query:
                _invalid(NO_QUERY_MESSAGE)
            self._load(workspace_id)
            self._require(workspace_id, "view_file_count")
            return {"file_count": self.public_file_count.get(workspace_id, 0)}
        self.unexpected_requests.append(f"{entry.method} {entry.path}")
        _refuse("Unexpected public insights request.", 500, "public_workspace_settings_unavailable")

    def _build_stats(self, workspace_id, window):
        """``build_public_stats``'s envelope: the classic figures, the series and the window."""
        series = []
        current = window["start"]
        while current <= window["end"]:
            series.append(current)
            current += timedelta(days=1)
        labels = [f"{day.month}/{day.day}" for day in series]
        zeros = [0] * len(series)
        figures = self.public_stats.get(workspace_id, {})
        return {
            "totalDocuments": figures.get("totalDocuments", 0),
            "storageUsed": figures.get("storageUsed", 0),
            "totalTokens": figures.get("totalTokens", 0),
            "totalMembers": figures.get("totalMembers", 0),
            "storage": copy.deepcopy(figures.get("storage", {"ai_search_size": 0, "storage_account_size": 0})),
            "documentActivity": {"labels": list(labels), "uploads": list(zeros), "deletes": list(zeros)},
            "tokenUsage": {"labels": list(labels), "data": list(zeros)},
            "dateRange": [day.isoformat() for day in series],
            "window": {
                "type": window["type"], "days": window["days"], "label": window["label"],
                "startDate": f"{window['start'].isoformat()}T00:00:00",
                "endDate": f"{window['end'].isoformat()}T23:59:59.999999",
            },
        }


@pytest.fixture
def public_settings_ui(page):
    fixture = PublicSettingsFixture(page)
    yield fixture
    fixture.assert_clean()
