# safety_review_harness.py
"""Closed-world harnesses for the safety review, safety warning and access-gate routes.

Version: 0.261.297
Implemented in: 0.261.297

Used inside ``offline_app_imports()`` by fresh-process probes. The real route modules,
decorators and helpers run on a real Flask app and session. Only the storage and delivery
seams are replaced: the safety container (with ETags and conditional replace), user
settings, notifications, approval requests and the activity log.
"""

import copy
import itertools
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
    "require_member_of_safety_violation_admin": False,
    "require_member_of_control_center_admin": False,
    "app_title": "SimpleChat",
    "show_logo": False,
    "hide_app_title": False,
}


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
    """A Cosmos-like container keyed by id, with ETags and conditional replace."""

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

    def delete_item(self, item, partition_key, **kwargs):
        self.items.pop(item, None)

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = [copy.deepcopy(item) for item in self.items.values()]
        for name, field in (("@user_id", "user_id"), ("@action", "action"), ("@status", "status")):
            if name in values:
                rows = [row for row in rows if row.get(field) == values[name]]
        if query.startswith("SELECT VALUE COUNT(1)"):
            # The pending-warning count: the rest of its WHERE clause, applied here.
            return [sum(
                1 for row in rows
                if row.get("action_request_status") == "executed"
                and row.get("warning_requires_acknowledgment") is True
                and not row.get("warning_acknowledged_at")
                and row.get("content_origin", "user") == "user"
            )]
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


def _patch_app_settings(stack, settings):
    import functions_authentication as auth
    import functions_settings

    def get_settings(*args, **kwargs):
        return copy.deepcopy(settings)

    stack.enter_context(patch.object(functions_settings, "get_settings", get_settings))
    stack.enter_context(patch.object(auth, "get_settings", get_settings))
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
    import functions_safety_remediation as remediation
    import route_backend_safety as safety_routes

    container = FakeSafetyContainer()
    state = SimpleNamespace(
        container=container,
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
    )
    _patch_app_settings(stack, state.settings)
    _patch_user_settings(stack, state.user_docs, state.access_writes)
    stack.enter_context(patch.object(remediation, "cosmos_safety_container", container))
    stack.enter_context(patch.object(safety_routes, "cosmos_safety_container", container))

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
        return approval

    def log_general_admin_action(**kwargs):
        state.audits.append(kwargs)
        return True

    stack.enter_context(patch.object(remediation, "create_notification", create_notification))
    stack.enter_context(patch.object(remediation, "mark_notification_read", mark_notification_read))
    stack.enter_context(patch.object(safety_routes, "create_approval_request", create_approval_request))
    stack.enter_context(patch.object(safety_routes, "log_general_admin_action", log_general_admin_action))
    for module in (remediation, safety_routes, auth):
        stack.enter_context(patch.object(module, "log_event", _quiet))
    stack.enter_context(patch.object(remediation, "debug_print", _quiet))

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
