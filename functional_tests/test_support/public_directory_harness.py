# public_directory_harness.py
"""Shared, isolated harness for the native public workspace directory tests (M9A).

Version: 0.261.175
Implemented in: 0.261.175

Loaded unchanged from their files:

- ``functions_group``: imported by ``functions_public_workspaces`` (``from
  functions_group import *``);
- ``functions_workspace_branding``: hero colour and logo metadata;
- ``functions_public_workspaces``: the role predicate the directory resolves each
  row through (``get_user_role_in_public_workspace``);
- ``functions_public_directory`` and ``route_backend_public_directory``.

The session decorators and ``enabled_required`` are the real definitions. Only
services outside the application are replaced:

- Cosmos is ``DirectoryPublicContainer``: the etag-enforcing ``FakeContainer`` from
  ``test_file_sync_concurrent_write_safety.py`` plus a model of the directory query.
  The model holds its own copy of the query text and refuses any other query, so the
  projection the tests rely on is the one the module sends, evaluated as Cosmos
  evaluates it: undefined properties are omitted, equality is type-strict, and
  iterating a missing array yields nothing;
- ``log_event`` and user settings writes are recorders;
- network access, including DNS, is refused.
"""

import copy
import importlib.util
import json
import logging
import re
import socket
import sys
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from azure.cosmos import exceptions as cosmos_exceptions
from flask import Blueprint, Flask, jsonify, redirect, request, send_file, session, url_for

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub


BASE_SETTINGS = {
    "enable_public_workspaces": True,
}

# Users. Each has a display name and an email; the directory never returns either,
# but the seeds carry them the way the workspace documents store them.
PEOPLE = {
    "owner-1": ("Olive Owner", "olive.owner@example.test"),
    "admin-1": ("Adam Admin", "adam.admin@example.test"),
    "manager-1": ("Mia Manager", "mia.manager@example.test"),
    "reader-1": ("Rhea Reader", "rhea.reader@example.test"),
    "outsider-1": ("Oscar Outsider", "oscar.outsider@example.test"),
}

# The directory query, as this fixture models it. Kept here rather than read from
# the module so a change to the module's query text fails every listing test until
# the model below is reviewed and updated with it.
EXPECTED_DIRECTORY_QUERY = (
    "SELECT c.id, c.name, c.description, "
    "c.owner.userId AS ownerId, "
    "c.heroColor, c.logoVersion, c.status, "
    "(IS_STRING(c.logoBase64) AND LENGTH(TRIM(c.logoBase64)) > 0) AS logoPresent, "
    "ARRAY(SELECT VALUE a FROM a IN c.admins WHERE a = @user_id OR a.userId = @user_id) AS callerAdmins, "
    "ARRAY(SELECT VALUE m FROM m IN c.documentManagers "
    "WHERE m = @user_id OR m.userId = @user_id) AS callerDocumentManagers "
    "FROM c"
)

_UNDEFINED = object()


def person(user_id):
    name, email = PEOPLE[user_id]
    return {"userId": user_id, "email": email, "displayName": name}


def public_workspace_document(ws_id, name=None, *, owner="owner-1", admins=("admin-1",),
                              managers=("manager-1",), status="active", hero_color="#0078d4",
                              logo="", **extra):
    """A public workspace document shaped like ``create_public_workspace`` writes, plus roles.

    ``admins`` and ``managers`` accept ids (stored as strings) or ``(user_id, "dict")``
    pairs (stored as ``{userId, email, displayName}``), so a test can exercise both the
    old and the new member formats.
    """
    owner_name, owner_email = PEOPLE[owner]
    document = {
        "id": ws_id,
        "name": f"Public {ws_id}" if name is None else name,
        "description": "A shared public workspace",
        "heroColor": hero_color,
        "logoBase64": logo,
        "logoVersion": 1,
        "owner": {"userId": owner, "email": owner_email, "displayName": owner_name},
        "admins": [_member_entry(entry) for entry in admins],
        "documentManagers": [_member_entry(entry) for entry in managers],
        "status": status,
        "disable_file_downloads": False,
        "createdDate": "2026-09-01T00:00:00",
        "modifiedDate": "2026-09-01T00:00:00",
    }
    document.update(extra)
    return document


def _member_entry(entry):
    """A member id as a bare string, or as a ``{userId, ...}`` dict for ``(id, "dict")``."""
    if isinstance(entry, tuple):
        return person(entry[0])
    return entry


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


def _member_matches(entry, user_id):
    """``a = @user_id OR a.userId = @user_id``: a string entry, or a dict with that id."""
    if isinstance(entry, str):
        return _cosmos_equal(entry, user_id)
    if isinstance(entry, dict):
        return _cosmos_equal(_path(entry, "userId"), user_id)
    return False


def project_directory_record(document, user_id):
    """Evaluate ``EXPECTED_DIRECTORY_QUERY``'s SELECT list for one stored document."""
    row = {}

    def put(name, value):
        if value is not _UNDEFINED:
            row[name] = copy.deepcopy(value)

    put("id", _path(document, "id"))
    put("name", _path(document, "name"))
    put("description", _path(document, "description"))
    put("ownerId", _path(document, "owner", "userId"))
    put("heroColor", _path(document, "heroColor"))
    put("logoVersion", _path(document, "logoVersion"))
    put("status", _path(document, "status"))
    logo = _path(document, "logoBase64")
    row["logoPresent"] = isinstance(logo, str) and len(logo.strip()) > 0
    row["callerAdmins"] = [
        copy.deepcopy(entry) for entry in _array(document, "admins") if _member_matches(entry, user_id)
    ]
    row["callerDocumentManagers"] = [
        copy.deepcopy(entry) for entry in _array(document, "documentManagers")
        if _member_matches(entry, user_id)
    ]
    return row


class DirectoryPublicContainer(FakeContainer):
    """The public workspaces container: the modelled directory query, read only."""

    def __init__(self):
        super().__init__("cosmos_public_workspaces_container", "id")
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=None, **kwargs):
        self.calls.append(("query_items", partition_key))
        self.queries.append({
            "query": query,
            "parameters": copy.deepcopy(parameters),
            "enable_cross_partition_query": enable_cross_partition_query,
        })
        normalized = _normalized(query)
        if normalized == _normalized(EXPECTED_DIRECTORY_QUERY):
            return self._directory_rows(parameters, partition_key, enable_cross_partition_query)
        raise AssertionError("The code under test sent a public workspaces query this fixture does not model")

    def _directory_rows(self, parameters, partition_key, enable_cross_partition_query):
        if enable_cross_partition_query is not True or partition_key is not None:
            raise AssertionError("The directory query must fan out across partitions")
        if not (
            isinstance(parameters, list) and len(parameters) == 1
            and parameters[0].get("name") == "@user_id" and isinstance(parameters[0].get("value"), str)
        ):
            raise AssertionError("The directory query takes exactly the caller's id")
        user_id = parameters[0]["value"]
        return [project_directory_record(record, user_id) for record in self.records.values()]


class PublicDirectoryEnvironment:
    """Live state, the loaded modules and a Flask client for the directory server."""

    def __init__(self):
        self.settings = dict(BASE_SETTINGS)
        self.public_workspaces = DirectoryPublicContainer()
        self.logs = []
        self.user_settings_writes = []

    # --- seams ------------------------------------------------------------

    def get_settings(self, *args, **kwargs):
        return copy.deepcopy(self.settings)

    def log_event(self, message, *args, **kwargs):
        self.logs.append((message, kwargs.get("level"), dict(kwargs.get("extra") or {})))

    def update_user_settings(self, user_id, updates):
        self.user_settings_writes.append((user_id, copy.deepcopy(updates)))
        return True

    # --- state ------------------------------------------------------------

    def reset(self):
        self.settings.clear()
        self.settings.update(BASE_SETTINGS)
        self.public_workspaces.records.clear()
        self.public_workspaces.calls.clear()
        self.public_workspaces.queries.clear()
        self.public_workspaces.before_replace.clear()
        self.logs.clear()
        self.user_settings_writes.clear()
        self.as_user("outsider-1")

    def as_user(self, user_id, roles=("User",)):
        name, email = PEOPLE.get(user_id, (f"Name {user_id}", f"{user_id}@example.test"))
        with self.client.session_transaction() as state:
            state["user"] = {
                "oid": user_id, "roles": list(roles) if roles is not None else None,
                "name": name, "preferred_username": email,
            }

    def sign_out(self):
        with self.client.session_transaction() as state:
            state.clear()

    def seed_workspace(self, ws_id, name=None, **kwargs):
        return self.public_workspaces.seed(public_workspace_document(ws_id, name, **kwargs))

    def seed_document(self, document):
        return self.public_workspaces.seed(document)

    def write_calls(self):
        return [
            call for call in self.public_workspaces.calls
            if call[0] in ("replace_item", "create_item", "upsert_item", "delete_item")
        ]

    # --- requests ---------------------------------------------------------

    def call(self, method, path, body=None, *, raw=None, content_type="application/json", query_string=None):
        kwargs = {}
        if raw is not None:
            kwargs["data"] = raw
            kwargs["content_type"] = content_type
        elif body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = content_type
        if query_string is not None:
            kwargs["query_string"] = query_string
        return getattr(self.client, method.lower())(path, **kwargs)

    def directory(self, query_string=None, **kwargs):
        return self.call("GET", "/api/public_workspaces/directory", query_string=query_string, **kwargs)


def _load(stack, name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    stack.enter_context(patch.dict(sys.modules, {name: module}))
    spec.loader.exec_module(module)
    return module


def _register(app, authentication, name, registrar):
    blueprint = Blueprint(name, __name__)
    blueprint.before_request(authentication.user_required_blueprint())
    registrar(blueprint)
    app.register_blueprint(blueprint)


@contextmanager
def public_directory_environment():
    """Load every real module once and yield a resettable environment."""
    env = PublicDirectoryEnvironment()
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
            cosmos_public_workspaces_container=env.public_workspaces,
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
            is_public_workspace_file_download_admin_enabled=lambda *args, **kwargs: False,
            is_public_workspace_file_download_enabled=lambda *args, **kwargs: False,
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
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        authentication = module_stub("functions_authentication", **{
            name: value for name, value in auth_namespace.items() if not name.startswith("__")
        }, enabled_required=settings_namespace["enabled_required"])

        stubs = {
            "config": config,
            "functions_appinsights": appinsights,
            "functions_settings": settings_module,
            "functions_authentication": authentication,
            "functions_chat_bootstrap_cache": module_stub(
                "functions_chat_bootstrap_cache",
                bump_chat_bootstrap_global_cache_version=lambda reason=None, **kwargs: None,
                bump_chat_bootstrap_user_cache_version=lambda *args, **kwargs: None,
            ),
            "functions_debug": module_stub("functions_debug", debug_print=lambda *args, **kwargs: None),
            "swagger_wrapper": module_stub(
                "swagger_wrapper",
                swagger_route=lambda **kwargs: (lambda function: function),
                get_auth_security=lambda: [{"sessionAuth": []}],
            ),
        }
        stack.enter_context(patch.dict(sys.modules, stubs))

        branding = _load(stack, "functions_workspace_branding")
        group = _load(stack, "functions_group")
        public_workspaces = _load(stack, "functions_public_workspaces")
        directory = _load(stack, "functions_public_directory")
        routes = _load(stack, "route_backend_public_directory")

        env.modules = SimpleNamespace(
            branding=branding, group=group, public_workspaces=public_workspaces,
            directory=directory, routes=routes, authentication=authentication,
            settings=settings_module,
        )

        app = Flask("public_directory_contract", root_path=str(APP_ROOT))
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        _register(app, authentication, "backend_public_directory", routes.register_route_backend_public_directory)

        env.app = app
        env.client = app.test_client()
        env.reset()
        yield env
