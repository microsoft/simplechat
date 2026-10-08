# safety_review_harness.py
"""Closed-world harnesses for the safety review, safety warning and access-gate routes.

Version: 0.261.299
Implemented in: 0.261.297
Review center coverage (approvals lookup, user names, feedback routes): 0.261.298
Approval decisions and withdrawal on the fake approvals store, and a hook inside approval
request creation: 0.261.298
Review center AI assist coverage (route modules read the harness settings): 0.261.299

Used inside ``offline_app_imports()`` by fresh-process probes. The real route modules,
decorators and helpers run on a real Flask app and session. Only the storage and delivery
seams are replaced: the safety and feedback containers (with ETags and conditional replace
and delete), the approvals store (with ETags, used by the lookup and by the real deny and
withdraw decisions), user settings, notifications, approval request creation and the
activity log.
"""

import copy
import itertools
import re
from importlib.metadata import version as package_version
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import werkzeug
from azure.cosmos import exceptions as cosmos_exceptions
from flask import Blueprint, Flask, jsonify


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"

APP_SETTINGS = {
    "enable_content_safety": True,
    "enable_content_screening": False,
    "enable_user_feedback": True,
    "require_member_of_safety_violation_admin": False,
    "require_member_of_feedback_admin": False,
    "require_member_of_control_center_admin": False,
    "app_title": "SimpleChat",
    "show_logo": False,
    "hide_app_title": False,
}

_ACTIVE_CLAUSE = "(NOT IS_DEFINED(c.is_archived) OR c.is_archived = false)"
_ARCHIVED_CLAUSE = "IS_DEFINED(c.is_archived) AND c.is_archived = true"
_ORDER_RE = re.compile(r"ORDER BY c\.(?P<field>[A-Za-z_]+) DESC")


def check(condition, message):
    """Raise rather than assert, so a probe still checks under ``python -O``."""
    if not condition:
        raise AssertionError(message)


def _quiet(*args, **kwargs):
    return None


def _test_client(app):
    # Flask 2.x test clients read werkzeug.__version__, which Werkzeug 3 no longer defines.
    with patch.object(werkzeug, "__version__", package_version("werkzeug"), create=True):
        return app.test_client()


class FakeSafetyContainer:
    """A Cosmos-like container keyed by id, with ETags and conditional replace and delete.

    Queries apply the parameters and the archive and ordering clauses the review routes
    use; the rest of a WHERE clause is applied by the code under test.
    """

    def __init__(self):
        self.items = {}
        self.revision = itertools.count(1)
        self.queries = []
        # Called once, just before the next replace, to stand in for a concurrent writer.
        self.before_replace = None

    def seed(self, item):
        stored = copy.deepcopy(item)
        stored["_etag"] = str(next(self.revision))
        self.items[stored["id"]] = stored
        return copy.deepcopy(stored)

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(self.items[item])

    def upsert_item(self, body, **kwargs):
        return self.seed(body)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if self.before_replace is not None:
            hook, self.before_replace = self.before_replace, None
            hook(self)
        current = self.items.get(item)
        if current is None:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        if etag is not None and current.get("_etag") != etag:
            raise cosmos_exceptions.CosmosAccessConditionFailedError(status_code=412, message="Changed")
        return self.seed(body)

    def delete_item(self, item, partition_key, etag=None, match_condition=None, **kwargs):
        current = self.items.get(item)
        if current is None:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        if etag is not None and current.get("_etag") != etag:
            raise cosmos_exceptions.CosmosAccessConditionFailedError(status_code=412, message="Changed")
        self.items.pop(item, None)

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = [copy.deepcopy(item) for item in self.items.values()]
        for name, field in (("@user_id", "user_id"), ("@action", "action"), ("@status", "status"),
                            ("@userId", "userId")):
            if name in values:
                rows = [row for row in rows if row.get(field) == values[name]]
        if "@ack" in values:
            rows = [row for row in rows if (row.get("adminReview") or {}).get("acknowledged") == values["@ack"]]
        if "@ids" in values:
            rows = [row for row in rows if row.get("id") in values["@ids"]]
        if _ARCHIVED_CLAUSE in query:
            rows = [row for row in rows if row.get("is_archived") is True]
        elif _ACTIVE_CLAUSE in query:
            rows = [row for row in rows if not row.get("is_archived")]
        if query.startswith("SELECT VALUE COUNT(1)"):
            # The pending-warning count: the rest of its WHERE clause, applied here.
            return [sum(
                1 for row in rows
                if row.get("action_request_status") == "executed"
                and row.get("warning_requires_acknowledgment") is True
                and not row.get("warning_acknowledged_at")
                and row.get("content_origin", "user") == "user"
            )]
        order = _ORDER_RE.search(query)
        if order:
            rows.sort(key=lambda row: str(row.get(order.group("field")) or ""), reverse=True)
        return rows


class FakeApprovalsContainer:
    """The approval requests the remediation lookup and decisions read and write, keyed by id.

    Every stored version gets a new ETag, and a conditional replace refuses a stale one.
    ``fail`` makes lookups fail; ``fail_writes`` makes writes fail.
    """

    def __init__(self):
        self.items = {}
        self.queries = []
        self.revision = itertools.count(1)
        self.fail = False
        self.fail_writes = False

    def add(self, approval):
        stored = copy.deepcopy(approval)
        stored["_etag"] = f"a{next(self.revision)}"
        self.items[approval["id"]] = stored
        return copy.deepcopy(stored)

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(self.items[item])

    def upsert_item(self, body, **kwargs):
        if self.fail_writes:
            raise RuntimeError("approvals store unavailable")
        return self.add(body)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if self.fail_writes:
            raise RuntimeError("approvals store unavailable")
        current = self.items.get(item)
        if current is None:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        if etag is not None and current.get("_etag") != etag:
            raise cosmos_exceptions.CosmosAccessConditionFailedError(status_code=412, message="Changed")
        return self.add(body)

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("approvals lookup unavailable")
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = []
        for item in self.items.values():
            if "@ids" in values and item["id"] not in values["@ids"]:
                continue
            if "@status" in values and item.get("status") != values["@status"]:
                continue
            row = copy.deepcopy(item)
            row["safety_log_id"] = (item.get("metadata") or {}).get("safety_log_id")
            rows.append(row)
        return rows


class FakeUserSettingsContainer:
    """Answers the Review center's batched name and access lookups from the harness's user docs."""

    def __init__(self, user_docs):
        self.user_docs = user_docs
        self.queries = []

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = []
        for user_id in values.get("@ids", []):
            doc = self.user_docs.get(user_id)
            if not isinstance(doc, dict):
                continue
            row = {"id": user_id, "display_name": doc.get("display_name"), "email": doc.get("email")}
            if "AS access" in query:
                row["access"] = copy.deepcopy((doc.get("settings") or {}).get("access"))
            rows.append(row)
        return rows


def _patch_user_settings(stack, user_docs, writes):
    """Replace the user-settings store the access check and remediation read and write."""
    import functions_safety_remediation as remediation
    import functions_settings

    def get_user_settings(user_id, allow_cross_user=False):
        doc = user_docs.get(user_id)
        if isinstance(doc, Exception):
            raise doc
        return copy.deepcopy(doc) if doc else {"id": user_id, "settings": {}}

    def update_user_settings(user_id, updates, allow_cross_user=False):
        doc = user_docs.setdefault(user_id, {"id": user_id, "settings": {}})
        doc.setdefault("settings", {}).update(copy.deepcopy(updates))
        writes.append({"user_id": user_id, "updates": copy.deepcopy(updates), "allow_cross_user": allow_cross_user})
        return True

    for module in (functions_settings, remediation):
        stack.enter_context(patch.object(module, "get_user_settings", get_user_settings))
        stack.enter_context(patch.object(module, "update_user_settings", update_user_settings))


def _patch_app_settings(stack, settings, *modules):
    """Serve ``settings`` to the authentication decorators and to each module that reads them.

    A route module that star-imports ``functions_settings`` holds its own ``get_settings``, so
    each one that reads the settings itself is named here.
    """
    import functions_authentication as auth
    import functions_settings

    def get_settings(*args, **kwargs):
        return copy.deepcopy(settings)

    stack.enter_context(patch.object(functions_settings, "get_settings", get_settings))
    stack.enter_context(patch.object(auth, "get_settings", get_settings))
    for module in modules:
        stack.enter_context(patch.object(module, "get_settings", get_settings))
    return get_settings


def sign_in(client, user_id, roles=("User",), name="Test User"):
    with client.session_transaction() as session:
        session["user"] = {
            "oid": user_id,
            "roles": list(roles),
            "name": name,
            "preferred_username": f"{user_id}@contoso.test",
        }


def sign_out(client):
    with client.session_transaction() as session:
        session.clear()


def build_safety_app(stack):
    """The real safety routes on a Blueprint guarded as app.py guards backend_safety."""
    import functions_authentication as auth
    import functions_review_center as review_center
    import functions_safety_remediation as remediation
    import route_backend_safety as safety_routes

    container = FakeSafetyContainer()
    approvals_container = FakeApprovalsContainer()
    state = SimpleNamespace(
        container=container,
        approvals_container=approvals_container,
        user_docs={},
        access_writes=[],
        notifications=[],
        read_marks=[],
        approvals=[],
        audits=[],
        settings=copy.deepcopy(APP_SETTINGS),
        fail_notifications=False,
        # Called once, just before the next notification is created: stands in for a request
        # that arrives while a warning is being sent.
        before_notification=None,
        # Called once, just after the next approval request is created and before the save that
        # created it records it: stands in for a save that lands while a request is created.
        before_approval_recorded=None,
        unchecked_count=0,
    )
    _patch_app_settings(stack, state.settings, safety_routes)
    _patch_user_settings(stack, state.user_docs, state.access_writes)
    stack.enter_context(patch.object(remediation, "cosmos_safety_container", container))
    stack.enter_context(patch.object(safety_routes, "cosmos_safety_container", container))
    stack.enter_context(patch.object(remediation, "cosmos_approvals_container", approvals_container))
    stack.enter_context(patch.object(
        review_center, "cosmos_user_settings_container", FakeUserSettingsContainer(state.user_docs),
    ))
    stack.enter_context(patch.object(safety_routes, "count_unchecked_chat_content", lambda: state.unchecked_count))

    def create_notification(**kwargs):
        if state.before_notification is not None:
            hook, state.before_notification = state.before_notification, None
            hook()
        if state.fail_notifications:
            return None
        notification = dict(kwargs)
        notification["id"] = f"notification-{len(state.notifications) + 1}"
        state.notifications.append(notification)
        return notification

    def mark_notification_read(notification_id, user_id):
        state.read_marks.append((notification_id, user_id))
        return True

    def create_approval_request(**kwargs):
        approval = dict(kwargs)
        approval.update({
            "id": f"approval-{len(state.approvals) + 1}",
            "status": "pending",
            "created_at": "2026-10-07T12:00:00",
        })
        state.approvals.append(approval)
        approvals_container.add(approval)
        if state.before_approval_recorded is not None:
            hook, state.before_approval_recorded = state.before_approval_recorded, None
            hook()
        return approval

    def log_general_admin_action(**kwargs):
        state.audits.append(kwargs)
        return True

    import functions_review_lifecycle as lifecycle

    stack.enter_context(patch.object(remediation, "create_notification", create_notification))
    stack.enter_context(patch.object(remediation, "mark_notification_read", mark_notification_read))
    stack.enter_context(patch.object(safety_routes, "create_approval_request", create_approval_request))
    stack.enter_context(patch.object(safety_routes, "log_general_admin_action", log_general_admin_action))
    stack.enter_context(patch.object(lifecycle, "log_general_admin_action", log_general_admin_action))
    for module in (remediation, safety_routes, auth, review_center):
        stack.enter_context(patch.object(module, "log_event", _quiet))
    stack.enter_context(patch.object(remediation, "debug_print", _quiet))
    patch_approval_decisions(stack, state)

    app = Flask("safety-review-harness", root_path=str(APP_ROOT))
    app.secret_key = "offline-test-only"
    app.config["TESTING"] = True
    blueprint = Blueprint("backend_safety", __name__)
    blueprint.before_request(auth.user_required_blueprint())
    safety_routes.register_route_backend_safety(blueprint)
    app.register_blueprint(blueprint)
    state.app = app
    state.client = _test_client(app)
    # Another browser: a second reviewer, or the warned user, with a session of their own.
    state.new_client = lambda: _test_client(app)
    return state


def patch_approval_decisions(stack, state):
    """Let the real approval decisions in ``functions_approvals`` run on the harness's approvals.

    ``deny_request`` and ``withdraw_approval_request`` store their decision in
    ``state.approvals_container``. Notifications they create are recorded in
    ``state.decision_notifications``, and notifications they remove in
    ``state.cleared_notifications``. ``build_safety_app`` applies this; calling it again
    changes nothing. Returns the real module.
    """
    import functions_approvals as approvals

    if getattr(state, "approval_decisions_patched", False):
        return approvals
    state.approval_decisions_patched = True
    state.decision_notifications = []
    state.cleared_notifications = []

    def create_notification(**kwargs):
        state.decision_notifications.append(kwargs)
        return {"id": f"decision-{len(state.decision_notifications)}"}

    def delete_notifications_by_metadata(**kwargs):
        state.cleared_notifications.append(kwargs)
        return 0

    stack.enter_context(patch.object(approvals, "cosmos_approvals_container", state.approvals_container))
    stack.enter_context(patch.object(approvals, "create_notification", create_notification))
    stack.enter_context(patch.object(approvals, "delete_notifications_by_metadata", delete_notifications_by_metadata))
    stack.enter_context(patch.object(approvals, "log_event", _quiet))
    stack.enter_context(patch.object(approvals, "debug_print", _quiet))
    return approvals


def build_feedback_app(stack):
    """The real feedback routes on a Blueprint guarded as app.py guards backend_feedback."""
    import functions_authentication as auth
    import functions_review_center as review_center
    import functions_review_lifecycle as lifecycle
    import route_backend_feedback as feedback_routes

    container = FakeSafetyContainer()
    state = SimpleNamespace(
        container=container,
        user_docs={},
        access_writes=[],
        notifications=[],
        audits=[],
        settings=copy.deepcopy(APP_SETTINGS),
        fail_notifications=False,
    )
    _patch_app_settings(stack, state.settings, feedback_routes)
    _patch_user_settings(stack, state.user_docs, state.access_writes)
    stack.enter_context(patch.object(feedback_routes, "cosmos_feedback_container", container))
    stack.enter_context(patch.object(
        review_center, "cosmos_user_settings_container", FakeUserSettingsContainer(state.user_docs),
    ))

    def create_notification(**kwargs):
        if state.fail_notifications:
            return None
        notification = dict(kwargs)
        notification["id"] = f"notification-{len(state.notifications) + 1}"
        state.notifications.append(notification)
        return notification

    def log_general_admin_action(**kwargs):
        state.audits.append(kwargs)
        return True

    stack.enter_context(patch.object(feedback_routes, "create_notification", create_notification))
    stack.enter_context(patch.object(lifecycle, "log_general_admin_action", log_general_admin_action))
    for module in (feedback_routes, auth, review_center):
        stack.enter_context(patch.object(module, "log_event", _quiet))

    app = Flask("feedback-review-harness", root_path=str(APP_ROOT))
    app.secret_key = "offline-test-only"
    app.config["TESTING"] = True
    blueprint = Blueprint("backend_feedback", __name__)
    blueprint.before_request(auth.user_required_blueprint())
    feedback_routes.register_route_backend_feedback(blueprint)
    app.register_blueprint(blueprint)
    state.app = app
    state.client = _test_client(app)
    # Another browser: a second reviewer, or the user who sent the feedback.
    state.new_client = lambda: _test_client(app)
    return state


def build_gate_app(stack, shell_path):
    """The real access gate, Access restricted routes and V2 shell routes, guarded as app.py does."""
    import functions_authentication as auth
    import route_access_restriction as restricted
    import route_frontend_v2 as frontend_v2

    state = SimpleNamespace(
        user_docs={},
        access_writes=[],
        settings=copy.deepcopy(APP_SETTINGS),
    )
    get_settings = _patch_app_settings(stack, state.settings)
    _patch_user_settings(stack, state.user_docs, state.access_writes)
    stack.enter_context(patch.object(restricted, "get_settings", get_settings))
    stack.enter_context(patch.object(frontend_v2, "get_v2_index_path", lambda: str(shell_path)))
    for module in (auth, frontend_v2):
        stack.enter_context(patch.object(module, "log_event", _quiet))

    app = Flask("access-gate-harness", root_path=str(APP_ROOT))
    app.secret_key = "offline-test-only"
    app.config["TESTING"] = True

    authentication = Blueprint("frontend_authentication", __name__)
    authentication.add_url_rule("/login", "login", lambda: "Sign in page")
    authentication.add_url_rule("/logout", "logout", lambda: "Signed out")
    public_app = Blueprint("public_app", __name__)
    public_app.add_url_rule("/", "index", lambda: "Home")

    access_restriction = Blueprint("access_restriction", __name__)
    access_restriction.before_request(auth.login_required_blueprint())
    restricted.register_route_access_restriction(access_restriction)

    v2_shell = Blueprint("frontend_v2", __name__)
    v2_shell.before_request(auth.user_required_blueprint())
    frontend_v2.register_route_frontend_v2(v2_shell)

    gated = Blueprint("gated", __name__)
    gated.before_request(auth.user_required_blueprint())
    gated.add_url_rule("/chats", "chats", lambda: "Chats page")
    gated.add_url_rule("/api/v2/bootstrap", "bootstrap", lambda: jsonify({"ok": True}))
    gated.add_url_rule("/api/notifications/count", "count", lambda: jsonify({"count": 0}))

    for blueprint in (authentication, public_app, access_restriction, v2_shell, gated):
        app.register_blueprint(blueprint)
    state.app = app
    state.client = _test_client(app)
    return state
