# group_directory_harness.py
"""Shared, isolated harness for the native group directory and membership tests (M7A, M7B).

Version: 0.261.151
Implemented in: 0.261.146

Loaded unchanged from their files:

- ``functions_group``: the role predicate, ``create_group`` and the etag guard;
- ``functions_workspace_branding``: hero colour and logo metadata;
- ``functions_group_directory_policy``, ``functions_group_directory`` and
  ``route_backend_group_directory``;
- ``functions_group_membership_policy``, ``functions_group_membership``,
  ``functions_group_membership_audit`` and ``route_backend_group_membership``;
- the classic ``route_backend_groups``, registered first as ``app.py`` does, so the
  classic routes answer for real: the ones that share the shape of
  ``/api/groups/directory``, and every classic membership route.

The session decorators, ``create_group_role_required`` and ``enabled_required`` are
the real definitions, and ``create_group_for_current_user`` runs with the real
helpers it calls: the configuration checks and the creator's notification. The
classic direct add, ``add_group_member_for_current_user``, runs for real with the
helpers it calls: the group and role checks, the directory resolution, the
activity record (``_log_group_member_addition``) and the two notifications.
``log_group_member_deleted`` is the real function too.

Only services outside the application are replaced:

- Cosmos is ``DirectoryGroupsContainer``: the etag-enforcing ``FakeContainer`` from
  ``test_file_sync_concurrent_write_safety.py`` (412 on a stale etag, 404 on a
  missing record, a replace never creates) plus a model of the directory query. The
  model holds its own copy of the query text and refuses any other query, so the
  projection the tests rely on is the one the module sends, evaluated as Cosmos
  evaluates it: undefined properties are omitted, equality is type-strict and
  iterating a missing array yields nothing. Activity records go to a second
  ``FakeContainer``;
- Microsoft Graph is an in-memory directory (``directory_users``) whose lookups can
  be made to fail (``directory_failure``) the way a missing token, a refused
  permission or a transport error does;
- notifications, the chat bootstrap cache bump, ``log_event``, user settings writes
  and any other activity logger are recorders;
- network access, including DNS, is refused.
"""

import copy
import importlib.util
import json
import logging
import re
import socket
import sys
import types
import typing
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from azure.cosmos import exceptions as cosmos_exceptions
from flask import Blueprint, Flask, jsonify, redirect, request, send_file, session, url_for

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub


BASE_SETTINGS = {
    "enable_group_workspaces": True,
    "enable_group_creation": True,
    "require_member_of_create_group": False,
}

# Users. Each has a display name and an email the tests look for in responses.
PEOPLE = {
    "owner-1": ("Olive Owner", "olive.owner@example.test"),
    "admin-1": ("Adam Admin", "adam.admin@example.test"),
    "manager-1": ("Mia Manager", "mia.manager@example.test"),
    "member-1": ("Max Member", "max.member@example.test"),
    "applicant-1": ("Ana Applicant", "ana.applicant@example.test"),
    "outsider-1": ("Oscar Outsider", "oscar.outsider@example.test"),
    "newcomer-1": ("Nia Newcomer", "nia.newcomer@example.test"),
}

# The directory query, as this fixture models it. Kept here rather than read from
# the module so a change to the module's query text fails every listing test until
# the model below is reviewed and updated with it.
EXPECTED_DIRECTORY_QUERY = (
    "SELECT c.id, c.name, c.description, "
    "c.owner.id AS ownerId, c.owner.displayName AS ownerDisplayName, "
    "c.heroColor, c.logoVersion, "
    "(IS_STRING(c.logoBase64) AND LENGTH(TRIM(c.logoBase64)) > 0) AS logoPresent, "
    "ARRAY_LENGTH(c.users) AS memberCount, "
    "ARRAY(SELECT VALUE u FROM u IN c.users WHERE u.userId = @user_id) AS callerUsers, "
    "ARRAY(SELECT VALUE a FROM a IN c.admins WHERE a = @user_id) AS callerAdmins, "
    "ARRAY(SELECT VALUE m FROM m IN c.documentManagers WHERE m = @user_id) AS callerDocumentManagers, "
    "ARRAY(SELECT VALUE p FROM p IN c.pendingUsers WHERE p.userId = @user_id) AS callerPendingUsers "
    "FROM c WHERE (c.type = 'group' OR NOT IS_DEFINED(c.type))"
)

_UNDEFINED = object()


def person(user_id):
    name, email = PEOPLE[user_id]
    return {"userId": user_id, "email": email, "displayName": name}


def group_document(group_id, name=None, *, owner="owner-1", admins=("admin-1",), managers=("manager-1",),
                   members=("member-1",), pending=(), **extra):
    """A group document shaped like the ones ``create_group`` writes, plus roles."""
    users = [person(owner), *(person(user_id) for user_id in (*admins, *managers, *members))]
    owner_name, owner_email = PEOPLE[owner]
    document = {
        "id": group_id,
        "name": f"Group {group_id}" if name is None else name,
        "description": "A shared workspace",
        "heroColor": "#0078d4",
        "logoBase64": "",
        "logoVersion": 1,
        "owner": {"id": owner, "email": owner_email, "displayName": owner_name},
        "admins": list(admins),
        "documentManagers": list(managers),
        "users": users,
        "pendingUsers": [person(user_id) for user_id in pending],
        "disable_file_downloads": False,
        "retention_policy": {"conversation_retention_days": "default", "document_retention_days": "default"},
        "model_endpoints": [{"id": "ep-1", "auth": {"type": "api_key", "api_key": "sk-secret-endpoint-key"}}],
        "createdDate": "2026-09-01T00:00:00",
        "modifiedDate": "2026-09-01T00:00:00",
    }
    document.update(extra)
    return document


def _normalized(query):
    return " ".join(str(query).split())


def _path(document, *keys):
    value = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return _UNDEFINED
        value = value[key]
    return value


def _cosmos_equal(left, right):
    """Cosmos equality is type-strict: a string never equals a number or a boolean."""
    return type(left) is type(right) and left == right


def _array(document, key):
    value = _path(document, key)
    return value if isinstance(value, list) else []


def cosmos_group_type_filter(document):
    """``(c.type = 'group' OR NOT IS_DEFINED(c.type))``: a ``null`` type is defined."""
    type_value = _path(document, "type")
    return type_value is _UNDEFINED or _cosmos_equal(type_value, "group")


def project_directory_record(document, user_id):
    """Evaluate ``EXPECTED_DIRECTORY_QUERY``'s SELECT list for one stored document."""
    row = {}

    def put(name, value):
        if value is not _UNDEFINED:
            row[name] = copy.deepcopy(value)

    put("id", _path(document, "id"))
    put("name", _path(document, "name"))
    put("description", _path(document, "description"))
    put("ownerId", _path(document, "owner", "id"))
    put("ownerDisplayName", _path(document, "owner", "displayName"))
    put("heroColor", _path(document, "heroColor"))
    put("logoVersion", _path(document, "logoVersion"))
    logo = _path(document, "logoBase64")
    row["logoPresent"] = isinstance(logo, str) and len(logo.strip()) > 0
    users = _path(document, "users")
    if isinstance(users, list):
        row["memberCount"] = len(users)
    row["callerUsers"] = [
        copy.deepcopy(entry) for entry in _array(document, "users")
        if _cosmos_equal(_path(entry, "userId"), user_id)
    ]
    row["callerAdmins"] = [entry for entry in _array(document, "admins") if _cosmos_equal(entry, user_id)]
    row["callerDocumentManagers"] = [
        entry for entry in _array(document, "documentManagers") if _cosmos_equal(entry, user_id)
    ]
    row["callerPendingUsers"] = [
        copy.deepcopy(entry) for entry in _array(document, "pendingUsers")
        if _cosmos_equal(_path(entry, "userId"), user_id)
    ]
    return row


class DirectoryGroupsContainer(FakeContainer):
    """The groups container: etag-enforcing writes plus the modelled directory query."""

    def __init__(self):
        super().__init__("cosmos_groups_container", "id")
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=None, **kwargs):
        self.calls.append(("query_items", partition_key))
        self.queries.append({
            "query": query,
            "parameters": copy.deepcopy(parameters),
            "enable_cross_partition_query": enable_cross_partition_query,
        })
        if _normalized(query) != _normalized(EXPECTED_DIRECTORY_QUERY):
            raise AssertionError("The code under test sent a groups query this fixture does not model")
        if enable_cross_partition_query is not True or partition_key is not None:
            raise AssertionError("The directory query must fan out across partitions")
        if not (
            isinstance(parameters, list) and len(parameters) == 1
            and parameters[0].get("name") == "@user_id" and isinstance(parameters[0].get("value"), str)
        ):
            raise AssertionError("The directory query takes exactly the caller's id")
        user_id = parameters[0]["value"]
        return [
            project_directory_record(record, user_id)
            for record in self.records.values()
            if cosmos_group_type_filter(record)
        ]


class Recorder(types.ModuleType):
    """A module stand-in that records any call made to it."""

    def __init__(self, name):
        super().__init__(name)
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _refuse(name):
    def refused(*args, **kwargs):
        raise AssertionError(f"The code under test called {name}, which this harness does not model")

    refused.__name__ = name
    return refused


def _load(stack, name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    stack.enter_context(patch.dict(sys.modules, {name: module}))
    spec.loader.exec_module(module)
    return module


class GroupDirectoryEnvironment:
    """Live state, the loaded modules and Flask clients for a new and an old server."""

    def __init__(self):
        self.settings = dict(BASE_SETTINGS)
        self.groups = DirectoryGroupsContainer()
        self.activity_logs = FakeContainer("cosmos_activity_logs_container", "id")
        self.notifications = []
        self.bumps = []
        self.logs = []
        self.user_settings_writes = []
        self.activity = Recorder("functions_activity_logging")
        self.directory_users = {}
        self.directory_failure = None
        self.directory_calls = []

    # --- seams ------------------------------------------------------------

    def get_settings(self, *args, **kwargs):
        return copy.deepcopy(self.settings)

    def create_notification(self, **kwargs):
        self.notifications.append(copy.deepcopy(kwargs))
        return {"id": f"notification-{len(self.notifications)}", **kwargs}

    def log_event(self, message, *args, **kwargs):
        self.logs.append((message, kwargs.get("level"), dict(kwargs.get("extra") or {})))

    def update_user_settings(self, user_id, updates):
        self.user_settings_writes.append((user_id, copy.deepcopy(updates)))
        return True

    def get_directory_user_by_id(self, user_id):
        """Graph ``GET /users/<id>``: a user, ``None`` for a 404, or the configured failure."""
        self.directory_calls.append(("by_id", user_id))
        if self.directory_failure is not None:
            raise self.directory_failure
        user = self.directory_users.get(str(user_id or "").strip())
        return copy.deepcopy(user) if user else None

    def find_directory_users_by_email(self, email):
        self.directory_calls.append(("by_email", email))
        if self.directory_failure is not None:
            raise self.directory_failure
        wanted = str(email or "").strip().lower()
        return [copy.deepcopy(user) for user in self.directory_users.values() if user["email"].lower() == wanted]

    def search_directory_users(self, query, limit=10):
        self.directory_calls.append(("search", query))
        if self.directory_failure is not None:
            raise self.directory_failure
        wanted = str(query or "").strip().lower()
        return [
            copy.deepcopy(user) for user in self.directory_users.values()
            if user["displayName"].lower().startswith(wanted) or user["email"].lower().startswith(wanted)
        ][:limit]

    def add_directory_user(self, user_id, name=None, email=None):
        default_name, default_email = PEOPLE.get(user_id, (f"Name {user_id}", f"{user_id}@example.test"))
        self.directory_users[user_id] = {
            "id": user_id, "displayName": name or default_name, "email": email or default_email,
        }
        return self.directory_users[user_id]

    def activity_records(self):
        return [record for record in self.activity_logs.records.values()]

    # --- state ------------------------------------------------------------

    def reset(self):
        self.settings.clear()
        self.settings.update(BASE_SETTINGS)
        self.groups.records.clear()
        self.groups.calls.clear()
        self.groups.queries.clear()
        self.groups.before_replace.clear()
        self.activity_logs.records.clear()
        self.activity_logs.calls.clear()
        self.notifications.clear()
        self.bumps.clear()
        self.logs.clear()
        self.user_settings_writes.clear()
        self.activity.calls.clear()
        self.directory_users.clear()
        self.directory_failure = None
        self.directory_calls.clear()
        self.operations_namespace["get_settings"] = self.get_settings
        self.as_user("outsider-1")

    def as_user(self, user_id, roles=("User",)):
        name, email = PEOPLE.get(user_id, (f"Name {user_id}", f"{user_id}@example.test"))
        for client in (self.client, self.legacy_client):
            with client.session_transaction() as state:
                state["user"] = {
                    "oid": user_id, "roles": list(roles) if roles is not None else None,
                    "name": name, "preferred_username": email,
                }

    def sign_out(self):
        for client in (self.client, self.legacy_client):
            with client.session_transaction() as state:
                state.clear()

    def seed_group(self, group_id, name=None, **kwargs):
        return self.groups.seed(group_document(group_id, name, **kwargs))

    def seed_document(self, document):
        return self.groups.seed(document)

    def stored_group(self, group_id):
        return self.groups.get(group_id, group_id)

    def write_calls(self):
        return [call for call in self.groups.calls if call[0] in ("replace_item", "create_item", "upsert_item", "delete_item")]

    # --- requests ---------------------------------------------------------

    def call(self, method, path, body=None, *, raw=None, content_type="application/json",
             query_string=None, legacy=False):
        kwargs = {}
        if raw is not None:
            kwargs["data"] = raw
            kwargs["content_type"] = content_type
        elif body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = content_type
        if query_string is not None:
            kwargs["query_string"] = query_string
        client = self.legacy_client if legacy else self.client
        return getattr(client, method.lower())(path, **kwargs)

    def directory(self, query_string=None, **kwargs):
        return self.call("GET", "/api/groups/directory", query_string=query_string, **kwargs)

    def create(self, body, **kwargs):
        return self.call("POST", "/api/groups/directory", body, **kwargs)

    def join(self, group_id, **kwargs):
        return self.call("POST", f"/api/groups/{group_id}/join-request", **kwargs)

    def cancel(self, group_id, **kwargs):
        return self.call("DELETE", f"/api/groups/{group_id}/join-request", **kwargs)

    def members(self, group_id, query_string=None, **kwargs):
        return self.call("GET", f"/api/groups/{group_id}/membership/members", query_string=query_string, **kwargs)

    def add_member(self, group_id, body, **kwargs):
        return self.call("POST", f"/api/groups/{group_id}/membership/members", body, **kwargs)

    def change_role(self, group_id, user_id, body, **kwargs):
        return self.call("PATCH", f"/api/groups/{group_id}/membership/members/{user_id}", body, **kwargs)

    def remove_member(self, group_id, user_id, **kwargs):
        return self.call("DELETE", f"/api/groups/{group_id}/membership/members/{user_id}", **kwargs)

    def pending_requests(self, group_id, **kwargs):
        return self.call("GET", f"/api/groups/{group_id}/membership/requests", **kwargs)

    def approve(self, group_id, user_id, **kwargs):
        return self.call("POST", f"/api/groups/{group_id}/membership/requests/{user_id}/approve", **kwargs)

    def reject(self, group_id, user_id, **kwargs):
        return self.call("POST", f"/api/groups/{group_id}/membership/requests/{user_id}/reject", **kwargs)

    def transfer(self, group_id, body, **kwargs):
        return self.call("PUT", f"/api/groups/{group_id}/membership/owner", body, **kwargs)


def _register(app, authentication, name, registrar):
    blueprint = Blueprint(name, __name__)
    blueprint.before_request(authentication.user_required_blueprint())
    registrar(blueprint)
    app.register_blueprint(blueprint)


@contextmanager
def group_directory_environment():
    """Load every real module once and yield a resettable environment."""
    env = GroupDirectoryEnvironment()
    with ExitStack() as stack:
        stack.enter_context(patch.object(sys, "path", [str(APP_ROOT), *sys.path]))

        def refuse(*args, **kwargs):
            raise AssertionError("The test attempted a network connection")

        def refuse_dns(*args, **kwargs):
            raise socket.gaierror("DNS is disabled in this test")

        stack.enter_context(patch.object(socket.socket, "connect", refuse))
        stack.enter_context(patch.object(socket, "create_connection", refuse))
        stack.enter_context(patch.object(socket, "getaddrinfo", refuse_dns))

        config = module_stub(
            "config",
            json=json, re=re, uuid=uuid, logging=logging, BytesIO=BytesIO,
            datetime=datetime, timezone=timezone,
            exceptions=cosmos_exceptions,
            request=request, session=session, jsonify=jsonify, send_file=send_file,
            redirect=redirect, url_for=url_for,
            cosmos_groups_container=env.groups,
            cosmos_activity_logs_container=env.activity_logs,
        )
        appinsights = module_stub(
            "functions_appinsights",
            log_event=env.log_event,
            debug_print=lambda *args, **kwargs: None,
        )

        settings_namespace = {"wraps": wraps, "jsonify": jsonify, "get_settings": env.get_settings}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        settings_module = module_stub(
            "functions_settings",
            get_settings=env.get_settings,
            enabled_required=settings_namespace["enabled_required"],
            get_user_settings=lambda user_id, *args, **kwargs: {"id": user_id, "settings": {}},
            update_user_settings=env.update_user_settings,
            is_group_workspace_file_download_admin_enabled=lambda *args, **kwargs: False,
            is_group_workspace_file_download_enabled=lambda *args, **kwargs: False,
        )

        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "redirect": redirect, "url_for": url_for,
            "debug_print": lambda *args, **kwargs: None,
            "check_user_access_status": lambda user_id: (True, None),
            "get_settings": env.get_settings,
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "get_current_user_id", "get_current_user_info",
            "create_group_role_required", "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        authentication = module_stub("functions_authentication", **{
            name: value for name, value in auth_namespace.items() if not name.startswith("__")
        }, enabled_required=settings_namespace["enabled_required"])

        stubs = {
            "config": config,
            "functions_appinsights": appinsights,
            "functions_settings": settings_module,
            "functions_authentication": authentication,
            "functions_activity_logging": env.activity,
            "functions_chat_bootstrap_cache": module_stub(
                "functions_chat_bootstrap_cache",
                bump_chat_bootstrap_global_cache_version=lambda reason=None, **kwargs: env.bumps.append(reason),
                bump_chat_bootstrap_user_cache_version=_refuse("bump_chat_bootstrap_user_cache_version"),
            ),
            "functions_debug": module_stub("functions_debug", debug_print=lambda *args, **kwargs: None),
            "functions_notifications": module_stub(
                "functions_notifications", create_notification=env.create_notification,
            ),
            "functions_stats_windows": module_stub(
                "functions_stats_windows",
                build_stats_date_series=_refuse("build_stats_date_series"),
                resolve_bounded_stats_time_window=_refuse("resolve_bounded_stats_time_window"),
                resolve_stats_time_window=_refuse("resolve_stats_time_window"),
                stats_window_response_payload=_refuse("stats_window_response_payload"),
                timestamp_to_stats_date_key=_refuse("timestamp_to_stats_date_key"),
            ),
            "swagger_wrapper": module_stub(
                "swagger_wrapper",
                swagger_route=lambda **kwargs: (lambda function: function),
                get_auth_security=lambda: [{"sessionAuth": []}],
            ),
        }
        stack.enter_context(patch.dict(sys.modules, stubs))

        # The real classic removal logger, writing to the activity container.
        activity_namespace = {
            "Optional": typing.Optional, "datetime": datetime, "logging": logging,
            "cosmos_activity_logs_container": env.activity_logs,
            "log_event": env.log_event, "debug_print": lambda *args, **kwargs: None,
        }
        execute_functions("functions_activity_logging.py", {"log_group_member_deleted"}, activity_namespace)
        env.activity.log_group_member_deleted = activity_namespace["log_group_member_deleted"]

        branding = _load(stack, "functions_workspace_branding")
        group = _load(stack, "functions_group")

        # create_group_for_current_user and add_group_member_for_current_user with the
        # real helpers they call; Graph is the in-memory directory.
        operations_namespace = {
            "Any": typing.Any, "Dict": typing.Dict, "List": typing.List, "Optional": typing.Optional,
            "Tuple": typing.Tuple,
            "logging": logging, "session": session, "quote": quote, "uuid": uuid, "datetime": datetime,
            "get_settings": env.get_settings,
            "get_current_user_info": auth_namespace["get_current_user_info"],
            "create_group": group.create_group,
            "find_group_by_id": group.find_group_by_id,
            "assert_group_role": group.assert_group_role,
            "require_active_group": group.require_active_group,
            "get_user_role_in_group": group.get_user_role_in_group,
            "update_group_document_with_etag_guard": group.update_group_document_with_etag_guard,
            "GroupDocumentWriteConflict": group.GroupDocumentWriteConflict,
            "functions_group": group,
            "cosmos_groups_container": env.groups,
            "cosmos_activity_logs_container": env.activity_logs,
            "bump_chat_bootstrap_global_cache_version": lambda reason=None, **kwargs: env.bumps.append(reason),
            "create_notification": env.create_notification,
            "log_event": env.log_event,
            "_get_directory_user_by_id": env.get_directory_user_by_id,
            "_find_directory_users_by_email": env.find_directory_users_by_email,
            "search_directory_users": env.search_directory_users,
        }
        execute_functions("functions_simplechat_operations.py", {
            "create_group_for_current_user", "_require_group_workspaces_enabled",
            "_require_group_creation_enabled", "_require_current_user_info",
            "_notify_group_created", "_create_personal_notification", "_build_group_link_context",
            "_build_group_manage_url", "_notify_group_member_addition",
            "add_group_member_for_current_user", "_resolve_group_doc_for_current_user",
            "resolve_directory_user", "_log_group_member_addition",
        }, operations_namespace)
        env.operations_namespace = operations_namespace
        stack.enter_context(patch.dict(sys.modules, {
            "functions_simplechat_operations": module_stub(
                "functions_simplechat_operations",
                create_group_for_current_user=operations_namespace["create_group_for_current_user"],
                add_group_member_for_current_user=operations_namespace["add_group_member_for_current_user"],
                _get_directory_user_by_id=env.get_directory_user_by_id,
                _log_group_member_addition=operations_namespace["_log_group_member_addition"],
                _notify_group_member_addition=operations_namespace["_notify_group_member_addition"],
            ),
        }))

        policy = _load(stack, "functions_group_directory_policy")
        directory = _load(stack, "functions_group_directory")
        routes = _load(stack, "route_backend_group_directory")
        audit = _load(stack, "functions_group_membership_audit")
        membership_policy = _load(stack, "functions_group_membership_policy")
        membership = _load(stack, "functions_group_membership")
        membership_routes = _load(stack, "route_backend_group_membership")
        legacy_routes = _load(stack, "route_backend_groups")

        env.modules = SimpleNamespace(
            branding=branding, group=group, policy=policy, directory=directory,
            routes=routes, legacy_routes=legacy_routes, authentication=authentication,
            settings=settings_module, audit=audit, membership_policy=membership_policy,
            membership=membership, membership_routes=membership_routes,
        )

        app = Flask("group_directory_contract", root_path=str(APP_ROOT))
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        _register(app, authentication, "backend_groups", legacy_routes.register_route_backend_groups)
        _register(app, authentication, "backend_group_directory", routes.register_route_backend_group_directory)
        _register(
            app, authentication, "backend_group_membership",
            membership_routes.register_route_backend_group_membership,
        )

        legacy_app = Flask("group_directory_legacy_server", root_path=str(APP_ROOT))
        legacy_app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        _register(legacy_app, authentication, "backend_groups", legacy_routes.register_route_backend_groups)

        env.app, env.legacy_app = app, legacy_app
        env.client, env.legacy_client = app.test_client(), legacy_app.test_client()
        env.reset()
        yield env
