# public_settings_harness.py
"""Shared, isolated harness for the native public workspace settings and insights tests (M10C).

Version: 0.261.185
Implemented in: 0.261.185

It builds on ``public_directory_harness`` (its people, its public workspace documents and
the loading helpers), which it imports and does not change.

Loaded unchanged from their files:

- ``functions_group`` (``functions_public_workspaces`` imports it), ``functions_workspace_branding``
  (including the real logo processing) and ``functions_stats_windows``;
- ``functions_public_workspaces`` (the role predicate and the etag guard),
  ``functions_public_directory``, ``functions_public_settings_policy``,
  ``functions_public_settings``, ``functions_public_insights`` and
  ``route_backend_public_settings``;
- the classic ``route_backend_public_workspaces`` and ``route_backend_retention_policy``,
  registered as ``app.py`` registers them, so every seam test compares the native
  routes with the classic routes' real outcomes. ``env.client`` has both, and
  ``env.legacy_client`` only the classic routes, as an older server would.

The session decorators, ``enabled_required`` and the public file download predicates are
the real definitions.

Only services outside the application are replaced:

- Cosmos: an etag-enforcing public workspaces container, which refuses every query, and an
  activity logs container whose model evaluates exactly the aliased native activity query
  and the queries the classic routes send, as Cosmos evaluates them (type-strict equality,
  undefined properties omitted from projections and excluded from ``ORDER BY``), and
  refuses any other query. The model holds its own copy of each query text, so a change
  to a module's query fails these tests until the model is reviewed with it. The public
  documents container models only the classic ``/fileCount`` query;
- ``count_current_public_documents`` is a recorder returning ``file_count``: its
  predicate is pinned against the public document list by
  ``test_public_document_count_predicate.py``;
- the retention job's listing helpers, the chat bootstrap cache bump, notifications,
  ``log_event``, user settings writes and the activity logger are recorders;
- network access, including DNS, is refused.
"""

import base64
import copy
import json
import logging
import math
import re
import socket
import struct
import sys
import uuid
import zlib
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions
from flask import Flask, jsonify, redirect, request, send_file, session, url_for
from PIL import Image

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.public_directory_harness import PEOPLE as DIRECTORY_PEOPLE
from test_support.public_directory_harness import _load, _register, person, public_workspace_document


BASE_SETTINGS = {
    "enable_public_workspaces": True,
    "allow_public_workspace_file_downloads": True,
    "require_public_workspace_assignment_for_file_downloads": False,
    "file_download_allowed_public_workspace_ids": [],
    "enable_retention_policy_public": True,
    "retention_conversation_min_days": 1,
    "retention_conversation_max_days": 3650,
    "retention_document_min_days": 1,
    "retention_document_max_days": 3650,
    "default_retention_conversation_public": "none",
    "default_retention_document_public": "30",
}

# The directory harness's people, and one who held a role here before.
PEOPLE = {**DIRECTORY_PEOPLE, "former-1": ("Fern Former", "fern.former@example.test")}

_UNDEFINED = object()


def _normalized(query):
    return " ".join(str(query).split())


# The queries this fixture models, kept here rather than read from the modules.
EXPECTED_NATIVE_ACTIVITY_QUERY = _normalized(
    "SELECT TOP @limit a.id AS id, a.activity_type AS activity_type, a.timestamp AS timestamp, "
    "a.user_id AS user_id, a.changed_by.user_id AS changed_by_user_id, a.token_type AS token_type, "
    "a.usage.total_tokens AS total_tokens, a.status_change.old_status AS old_status, "
    "a.status_change.new_status AS new_status, a.action AS action "
    "FROM a WHERE a.workspace_context.public_workspace_id = @workspace_id ORDER BY a.timestamp DESC"
)
NATIVE_ACTIVITY_ALIASES = {
    "id": ("id",),
    "activity_type": ("activity_type",),
    "timestamp": ("timestamp",),
    "user_id": ("user_id",),
    "changed_by_user_id": ("changed_by", "user_id"),
    "token_type": ("token_type",),
    "total_tokens": ("usage", "total_tokens"),
    "old_status": ("status_change", "old_status"),
    "new_status": ("status_change", "new_status"),
    "action": ("action",),
}
LEGACY_ACTIVITY_QUERY = re.compile(
    r"SELECT TOP (10|20|50) \* FROM a WHERE a\.workspace_context\.public_workspace_id = @wsId "
    r"ORDER BY a\.timestamp DESC"
)
_WINDOW = (
    "AND ( (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate) "
    "OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate) )"
)
_SCOPE = "a.workspace_context.public_workspace_id = @wsId"
# The classic /fileCount query: every stored document record of the workspace.
LEGACY_FILE_COUNT_QUERY = _normalized("SELECT VALUE COUNT(1) FROM d WHERE d.public_workspace_id = @wsId")
STATS_QUERIES = {
    _normalized(f"SELECT a.usage FROM a WHERE {_SCOPE} {_WINDOW} AND a.activity_type = 'token_usage'"):
        ("token_total", ("usage",), "token_usage"),
    _normalized(f"SELECT a.timestamp, a.created_at FROM a WHERE {_SCOPE} {_WINDOW} "
                "AND a.activity_type = 'document_creation'"): ("uploads", ("timestamp", "created_at"),
                                                               "document_creation"),
    _normalized(f"SELECT a.timestamp, a.created_at FROM a WHERE {_SCOPE} {_WINDOW} "
                "AND a.activity_type = 'document_deletion'"): ("deletes", ("timestamp", "created_at"),
                                                               "document_deletion"),
    _normalized(f"SELECT a.timestamp, a.created_at, a.usage FROM a WHERE {_SCOPE} {_WINDOW} "
                "AND a.activity_type = 'token_usage'"): ("token_series", ("timestamp", "created_at", "usage"),
                                                         "token_usage"),
}


def _path(document, *keys):
    value = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return _UNDEFINED
        value = value[key]
    return value


def _cosmos_equal(left, right):
    return left is not _UNDEFINED and type(left) is type(right) and left == right


def _in_window(value, start, end):
    """``IS_DEFINED(v) AND v >= @start AND v <= @end``: a comparison across types is undefined."""
    return isinstance(value, str) and isinstance(start, str) and isinstance(end, str) and start <= value <= end


def _refuse(name):
    def refused(*args, **kwargs):
        raise AssertionError(f"The code under test called {name}, which this harness does not model")

    refused.__name__ = name
    return refused


class Recorder(ModuleType):
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


class PublicWorkspacesContainer(FakeContainer):
    """The public workspaces container: etag-enforcing reads and replaces, and no queries."""

    def __init__(self):
        super().__init__("cosmos_public_workspaces_container", "id")

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        raise AssertionError(f"The code under test queried the public workspaces container: {_normalized(query)}")


class ActivityLogsContainer(FakeContainer):
    """The activity logs container: stored records plus the modelled public workspace queries."""

    def __init__(self):
        super().__init__("cosmos_activity_logs_container", "user_id")
        self.queries = []
        self.fail_queries = 0

    def seed_activity(self, record):
        body = copy.deepcopy(record)
        body.setdefault("id", str(uuid.uuid4()))
        body.setdefault("user_id", "")
        return self.seed(body)

    def _scoped(self, records, workspace_id):
        return [
            record for record in records
            if _cosmos_equal(_path(record, "workspace_context", "public_workspace_id"), workspace_id)
        ]

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=None, **kwargs):
        self.calls.append(("query_items", partition_key))
        normalized = _normalized(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        self.queries.append({"query": normalized, "parameters": copy.deepcopy(values)})
        if enable_cross_partition_query is not True or partition_key is not None:
            raise AssertionError("Public workspace activity queries must fan out across partitions")
        if self.fail_queries:
            self.fail_queries -= 1
            raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="Service unavailable")
        records = list(self.records.values())
        if normalized == EXPECTED_NATIVE_ACTIVITY_QUERY:
            if set(values) != {"@limit", "@workspace_id"} or not isinstance(values["@limit"], int):
                raise AssertionError("The activity query takes exactly a whole-number limit and the workspace id")
            matching = [record for record in self._scoped(records, values["@workspace_id"])
                        if isinstance(_path(record, "timestamp"), str)]
            matching.sort(key=lambda record: record["timestamp"], reverse=True)
            rows = []
            for record in matching[:values["@limit"]]:
                row = {}
                for alias, keys in NATIVE_ACTIVITY_ALIASES.items():
                    value = _path(record, *keys)
                    if value is not _UNDEFINED:
                        row[alias] = copy.deepcopy(value)
                rows.append(row)
            return rows
        legacy = LEGACY_ACTIVITY_QUERY.fullmatch(normalized)
        if legacy:
            if set(values) != {"@wsId"}:
                raise AssertionError("The classic activity query takes exactly the workspace id")
            matching = [record for record in self._scoped(records, values["@wsId"])
                        if isinstance(_path(record, "timestamp"), str)]
            matching.sort(key=lambda record: record["timestamp"], reverse=True)
            return [copy.deepcopy(record) for record in matching[:int(legacy.group(1))]]
        if normalized in STATS_QUERIES:
            _, fields, activity_type = STATS_QUERIES[normalized]
            if set(values) != {"@wsId", "@startDate", "@endDate"}:
                raise AssertionError("A statistics query takes exactly the workspace id and the window")
            rows = []
            for record in self._scoped(records, values["@wsId"]):
                if not _cosmos_equal(_path(record, "activity_type"), activity_type):
                    continue
                if not (_in_window(_path(record, "timestamp"), values["@startDate"], values["@endDate"])
                        or _in_window(_path(record, "created_at"), values["@startDate"], values["@endDate"])):
                    continue
                row = {}
                for field in fields:
                    value = _path(record, field)
                    if value is not _UNDEFINED:
                        row[field] = copy.deepcopy(value)
                rows.append(row)
            return rows
        raise AssertionError(f"The code under test sent an activity query this fixture does not model: {normalized}")


class PublicDocumentsContainer(FakeContainer):
    """The public documents container: the classic ``/fileCount`` query and nothing else.

    The native count goes through ``count_current_public_documents``, so any other query
    sent here fails the test.
    """

    def __init__(self):
        super().__init__("cosmos_public_documents_container", "id")
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=None, **kwargs):
        normalized = _normalized(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        self.queries.append(normalized)
        if normalized == LEGACY_FILE_COUNT_QUERY:
            if set(values) != {"@wsId"} or enable_cross_partition_query is not True:
                raise AssertionError("The classic document count fans out and takes exactly the workspace id")
            # ``SELECT VALUE COUNT(1)`` yields one number; the classic route reads it with next().
            return iter([sum(
                1 for record in self.records.values()
                if _cosmos_equal(_path(record, "public_workspace_id"), values["@wsId"])
            )])
        raise AssertionError(f"The code under test queried public documents directly: {normalized}")


def png_bytes(width=4, height=4, color=(0, 120, 212)):
    """A real PNG image of the given size."""
    output = BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def jpeg_bytes(width=4, height=4, color=(200, 30, 30)):
    output = BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="JPEG")
    return output.getvalue()


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def decompression_bomb_png(side=30000):
    """A tiny PNG whose header claims ``side`` x ``side`` pixels.

    Pillow refuses it with ``DecompressionBombError``, which is neither a ``ValueError``
    nor an ``OSError``.
    """
    header = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(b"\x00"))
            + _png_chunk(b"IEND", b""))


def workspace_document(ws_id="public-1", name=None, **kwargs):
    """A public workspace document as ``create_public_workspace`` writes it, plus roles.

    ``admins`` and ``managers`` take ids (stored as strings) or ``(user_id, "dict")``
    pairs (stored as ``{userId, email, displayName}``), as the directory harness does.
    """
    extra = {"pendingDocumentManagers": [], **kwargs}
    return public_workspace_document(ws_id, name, **extra)


class PublicSettingsEnvironment:
    """Live state, the loaded modules and the Flask clients."""

    def __init__(self):
        self.settings = dict(BASE_SETTINGS)
        self.public_workspaces = PublicWorkspacesContainer()
        self.activity_logs = ActivityLogsContainer()
        self.public_documents = PublicDocumentsContainer()
        self.user_settings = FakeContainer("cosmos_user_settings_container", "id")
        self.notifications = []
        self.bumps = []
        self.logs = []
        self.user_settings_writes = []
        self.file_count = 0
        self.file_count_calls = []
        self.activity = Recorder("functions_activity_logging")

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

    def all_public_workspaces(self):
        return [copy.deepcopy(record) for record in self.public_workspaces.records.values()]

    def count_current_public_documents(self, workspace_id):
        self.file_count_calls.append(workspace_id)
        return self.file_count

    # --- state ------------------------------------------------------------

    def reset(self):
        self.settings.clear()
        self.settings.update(BASE_SETTINGS)
        for container in (self.public_workspaces, self.activity_logs, self.public_documents, self.user_settings):
            container.records.clear()
            container.calls.clear()
            container.before_replace.clear()
        self.activity_logs.queries.clear()
        self.activity_logs.fail_queries = 0
        self.public_documents.queries.clear()
        self.notifications.clear()
        self.bumps.clear()
        self.logs.clear()
        self.user_settings_writes.clear()
        self.file_count = 0
        self.file_count_calls.clear()
        self.activity.calls.clear()
        self.as_user("outsider-1")

    def clients(self):
        return [self.client, self.legacy_client]

    def as_user(self, user_id, roles=("User",)):
        name, email = PEOPLE.get(user_id, (f"Name {user_id}", f"{user_id}@example.test"))
        for client in self.clients():
            with client.session_transaction() as state:
                state["user"] = {
                    "oid": user_id, "roles": list(roles) if roles is not None else None,
                    "name": name, "preferred_username": email,
                }

    def sign_out(self):
        for client in self.clients():
            with client.session_transaction() as state:
                state.clear()

    def seed_workspace(self, ws_id="public-1", name=None, **kwargs):
        return self.public_workspaces.seed(workspace_document(ws_id, name, **kwargs))

    def seed_document(self, document_id, ws_id="public-1", **fields):
        """A stored public document record, for the classic document count."""
        return self.public_documents.seed({"id": document_id, "public_workspace_id": ws_id, **fields})

    def stored_workspace(self, ws_id="public-1"):
        return self.public_workspaces.get(ws_id, ws_id)

    def write_calls(self):
        return [
            call for call in self.public_workspaces.calls
            if call[0] in ("replace_item", "create_item", "upsert_item", "delete_item")
        ]

    # --- requests ---------------------------------------------------------

    def call(self, method, path, body=None, *, raw=None, content_type="application/json",
             query_string=None, data=None, legacy=False):
        kwargs = {}
        if data is not None:
            kwargs["data"] = data
            kwargs["content_type"] = content_type if content_type != "application/json" else "multipart/form-data"
        elif raw is not None:
            kwargs["data"] = raw
            kwargs["content_type"] = content_type
        elif body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = content_type
        if query_string is not None:
            kwargs["query_string"] = query_string
        client = self.legacy_client if legacy else self.client
        return getattr(client, method.lower())(path, **kwargs)

    def settings_read(self, ws_id="public-1", **kwargs):
        return self.call("GET", f"/api/public-workspaces/{ws_id}/settings", **kwargs)

    def revision(self, section, ws_id="public-1"):
        return self.modules.settings.section_revision(self.stored_workspace(ws_id), section)


@contextmanager
def public_settings_environment():
    """Load every real module once and yield a resettable environment."""
    env = PublicSettingsEnvironment()
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
            json=json, re=re, uuid=uuid, copy=copy, logging=logging, math=math, base64=base64,
            BytesIO=BytesIO, Image=Image, datetime=datetime, timedelta=timedelta, timezone=timezone,
            MatchConditions=MatchConditions, exceptions=cosmos_exceptions,
            request=request, session=session, jsonify=jsonify, send_file=send_file,
            redirect=redirect, url_for=url_for,
            # The application's config re-exports log_event, which the classic routes use.
            log_event=env.log_event,
            ALLOWED_EXTENSIONS_IMG={"png", "jpg", "jpeg"},
            cosmos_public_workspaces_container=env.public_workspaces,
            cosmos_activity_logs_container=env.activity_logs,
            cosmos_public_documents_container=env.public_documents,
            cosmos_user_settings_container=env.user_settings,
        )
        appinsights = module_stub(
            "functions_appinsights",
            log_event=env.log_event,
            debug_print=lambda *args, **kwargs: None,
        )

        settings_namespace = {"wraps": wraps, "jsonify": jsonify, "json": json, "get_settings": env.get_settings}
        execute_functions("functions_settings.py", {
            "enabled_required", "is_public_workspace_file_download_admin_enabled",
            "is_public_workspace_file_download_enabled", "_get_workspace_policy_target_id",
            "normalize_file_download_allowed_public_workspace_ids",
            "normalize_file_sync_allowed_public_workspace_ids",
        }, settings_namespace)
        settings_module = module_stub(
            "functions_settings",
            get_settings=env.get_settings,
            enabled_required=settings_namespace["enabled_required"],
            get_user_settings=lambda user_id, *args, **kwargs: {"id": user_id, "settings": {}},
            update_user_settings=env.update_user_settings,
            is_public_workspace_file_download_admin_enabled=settings_namespace[
                "is_public_workspace_file_download_admin_enabled"
            ],
            is_public_workspace_file_download_enabled=settings_namespace["is_public_workspace_file_download_enabled"],
            log_event=env.log_event,
            logging=logging,
        )

        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "redirect": redirect, "url_for": url_for,
            "debug_print": lambda *args, **kwargs: None,
            "check_user_access_status": lambda user_id: (True, None),
            "get_settings": env.get_settings,
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "admin_required", "get_current_user_id", "get_current_user_info",
            "create_public_workspace_role_required", "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        authentication = module_stub("functions_authentication", **{
            name: value for name, value in auth_namespace.items() if not name.startswith("__")
        }, enabled_required=settings_namespace["enabled_required"],
            get_valid_access_token=_refuse("get_valid_access_token"),
            get_graph_endpoint=_refuse("get_graph_endpoint"))

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
            "functions_debug": module_stub(
                "functions_debug", debug_print=lambda *args, **kwargs: None, is_debug_enabled=lambda: False,
            ),
            "functions_notifications": module_stub(
                "functions_notifications", create_notification=env.create_notification,
            ),
            "functions_prompts": module_stub(
                "functions_prompts", count_public_prompts_for_workspace=_refuse("count_public_prompts_for_workspace"),
            ),
            "functions_public_document_reads": module_stub(
                "functions_public_document_reads",
                count_current_public_documents=env.count_current_public_documents,
            ),
            "functions_retention_policy": module_stub(
                "functions_retention_policy",
                execute_retention_policy=_refuse("execute_retention_policy"),
                get_all_user_settings=lambda: [],
                get_all_groups=lambda: [],
                get_all_public_workspaces=env.all_public_workspaces,
            ),
            "swagger_wrapper": module_stub(
                "swagger_wrapper",
                swagger_route=lambda **kwargs: (lambda function: function),
                get_auth_security=lambda: [{"sessionAuth": []}],
            ),
        }
        stack.enter_context(patch.dict(sys.modules, stubs))

        branding = _load(stack, "functions_workspace_branding")
        stats_windows = _load(stack, "functions_stats_windows")
        group = _load(stack, "functions_group")
        public_workspaces = _load(stack, "functions_public_workspaces")
        directory = _load(stack, "functions_public_directory")
        policy = _load(stack, "functions_public_settings_policy")
        settings_functions = _load(stack, "functions_public_settings")
        insights = _load(stack, "functions_public_insights")
        routes = _load(stack, "route_backend_public_settings")
        legacy_routes = _load(stack, "route_backend_public_workspaces")
        retention_routes = _load(stack, "route_backend_retention_policy")

        env.modules = SimpleNamespace(
            branding=branding, stats_windows=stats_windows, group=group, public_workspaces=public_workspaces,
            directory=directory, policy=policy, settings=settings_functions, insights=insights, routes=routes,
            legacy_routes=legacy_routes, retention_routes=retention_routes, authentication=authentication,
            settings_module=settings_module,
        )

        def build_app(name, include_new):
            app = Flask(name, root_path=str(APP_ROOT))
            app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
            _register(app, authentication, "backend_public_workspaces",
                      legacy_routes.register_route_backend_public_workspaces)
            _register(app, authentication, "backend_retention_policy",
                      retention_routes.register_route_backend_retention_policy)
            if include_new:
                _register(app, authentication, "backend_public_settings", routes.register_route_backend_public_settings)
            return app

        env.app, env.legacy_app = build_app("public_settings_contract", True), build_app("public_settings_legacy", False)
        env.client, env.legacy_client = env.app.test_client(), env.legacy_app.test_client()
        env.reset()
        yield env


__all__ = [
    "ActivityLogsContainer",
    "BASE_SETTINGS",
    "EXPECTED_NATIVE_ACTIVITY_QUERY",
    "LEGACY_ACTIVITY_QUERY",
    "PEOPLE",
    "PublicSettingsEnvironment",
    "decompression_bomb_png",
    "jpeg_bytes",
    "person",
    "png_bytes",
    "public_settings_environment",
    "workspace_document",
]
