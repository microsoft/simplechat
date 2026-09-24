# group_settings_harness.py
"""Shared, isolated harness for the native group settings and insights tests (M7C).

Version: 0.261.154
Implemented in: 0.261.154

It builds on ``group_directory_harness`` (its people, group documents, the
etag-enforcing groups container and the loading helpers), which it imports and does
not change.

Loaded unchanged from their files:

- ``functions_group``, ``functions_workspace_branding`` (including the real logo
  processing) and ``functions_stats_windows``;
- ``functions_group_directory_policy``, ``functions_group_directory``,
  ``functions_group_settings_policy``, ``functions_group_settings``,
  ``functions_group_insights`` and ``route_backend_group_settings``;
- the classic ``route_backend_groups`` and ``route_backend_retention_policy``,
  registered as ``app.py`` registers them, so every seam test compares the native
  routes with the classic routes' real outcomes.

The session decorators, ``create_group_role_required``, ``admin_required``,
``enabled_required`` and the group file download predicates are the real definitions.

Only services outside the application are replaced:

- Cosmos: the groups container of the directory harness, and an activity logs
  container whose model evaluates exactly the queries the native and classic routes
  send, as Cosmos evaluates them (type-strict equality, undefined properties omitted
  from projections and excluded from ``ORDER BY``), and refuses any other query. The
  model holds its own copy of each query text, so a change to a module's query fails
  these tests until the model is reviewed with it. The group documents container
  refuses every query, as both document counts go through
  ``count_current_group_documents``;
- ``count_current_group_documents`` is a recorder returning ``file_count``: its
  predicate is pinned against the group document list by
  ``test_group_document_count_predicate.py``;
- the retention job's listing helpers, the chat bootstrap cache bump,
  notifications, ``log_event``, user settings writes and the activity logger are
  recorders;
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
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from azure.cosmos import exceptions as cosmos_exceptions
from flask import Flask, jsonify, redirect, request, send_file, session, url_for
from PIL import Image

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.group_directory_harness import (
    PEOPLE,
    DirectoryGroupsContainer,
    Recorder,
    _load,
    _refuse,
    _register,
    group_document,
)


BASE_SETTINGS = {
    "enable_group_workspaces": True,
    "enable_group_creation": True,
    "require_member_of_create_group": False,
    "allow_group_workspace_file_downloads": True,
    "require_group_assignment_for_file_downloads": False,
    "file_download_allowed_group_ids": [],
    "enable_retention_policy_group": True,
    "retention_conversation_min_days": 1,
    "retention_conversation_max_days": 3650,
    "retention_document_min_days": 1,
    "retention_document_max_days": 3650,
    "default_retention_conversation_group": "none",
    "default_retention_document_group": "30",
}

_UNDEFINED = object()


def _normalized(query):
    return " ".join(str(query).split())


# The queries this fixture models, kept here rather than read from the modules.
EXPECTED_NATIVE_ACTIVITY_QUERY = _normalized(
    "SELECT TOP @limit a.id AS id, a.activity_type AS activity_type, a.timestamp AS timestamp, "
    "a.user_id AS user_id, a.changed_by.user_id AS changed_by_user_id, a.token_type AS token_type, "
    "a.usage.total_tokens AS total_tokens, a.status_change.old_status AS old_status, "
    "a.status_change.new_status AS new_status, a.action AS action "
    "FROM a WHERE a.workspace_context.group_id = @group_id ORDER BY a.timestamp DESC"
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
    r"SELECT TOP (10|20|50) \* FROM a WHERE a\.workspace_context\.group_id = @groupId ORDER BY a\.timestamp DESC"
)
_WINDOW = (
    "AND ( (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate) "
    "OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate) )"
)
STATS_QUERIES = {
    _normalized(f"SELECT a.usage FROM a WHERE a.workspace_context.group_id = @groupId {_WINDOW} "
                "AND a.activity_type = 'token_usage'"): ("token_total", ("usage",), "token_usage"),
    _normalized(f"SELECT a.timestamp, a.created_at FROM a WHERE a.workspace_context.group_id = @groupId {_WINDOW} "
                "AND a.activity_type = 'document_creation'"): ("uploads", ("timestamp", "created_at"), "document_creation"),
    _normalized(f"SELECT a.timestamp, a.created_at FROM a WHERE a.workspace_context.group_id = @groupId {_WINDOW} "
                "AND a.activity_type = 'document_deletion'"): ("deletes", ("timestamp", "created_at"), "document_deletion"),
    _normalized(f"SELECT a.timestamp, a.created_at, a.usage FROM a WHERE a.workspace_context.group_id = @groupId "
                f"{_WINDOW} AND a.activity_type = 'token_usage'"): ("token_series", ("timestamp", "created_at", "usage"),
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


class ActivityLogsContainer(FakeContainer):
    """The activity logs container: stored records plus the modelled group queries."""

    def __init__(self):
        super().__init__("cosmos_activity_logs_container", "user_id")
        self.queries = []
        self.fail_queries = 0

    def seed_activity(self, record):
        body = copy.deepcopy(record)
        body.setdefault("id", str(uuid.uuid4()))
        body.setdefault("user_id", "")
        return self.seed(body)

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=None, **kwargs):
        self.calls.append(("query_items", partition_key))
        normalized = _normalized(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        self.queries.append({"query": normalized, "parameters": copy.deepcopy(values)})
        if enable_cross_partition_query is not True or partition_key is not None:
            raise AssertionError("Group activity queries must fan out across partitions")
        if self.fail_queries:
            self.fail_queries -= 1
            raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="Service unavailable")
        records = list(self.records.values())
        if normalized == EXPECTED_NATIVE_ACTIVITY_QUERY:
            if set(values) != {"@limit", "@group_id"} or not isinstance(values["@limit"], int):
                raise AssertionError("The activity query takes exactly a whole-number limit and the group id")
            matching = [
                record for record in records
                if _cosmos_equal(_path(record, "workspace_context", "group_id"), values["@group_id"])
                and isinstance(_path(record, "timestamp"), str)
            ]
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
            if set(values) != {"@groupId"}:
                raise AssertionError("The classic activity query takes exactly the group id")
            matching = [
                record for record in records
                if _cosmos_equal(_path(record, "workspace_context", "group_id"), values["@groupId"])
                and isinstance(_path(record, "timestamp"), str)
            ]
            matching.sort(key=lambda record: record["timestamp"], reverse=True)
            return [copy.deepcopy(record) for record in matching[:int(legacy.group(1))]]
        if normalized in STATS_QUERIES:
            _, fields, activity_type = STATS_QUERIES[normalized]
            if set(values) != {"@groupId", "@startDate", "@endDate"}:
                raise AssertionError("A statistics query takes exactly the group id and the window")
            rows = []
            for record in records:
                if not _cosmos_equal(_path(record, "workspace_context", "group_id"), values["@groupId"]):
                    continue
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


class GroupDocumentsContainer(FakeContainer):
    """The group documents container. Both document counts go through
    ``count_current_group_documents``, so any query sent here fails the test."""

    def __init__(self):
        super().__init__("cosmos_group_documents_container", "id")
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=None, **kwargs):
        normalized = _normalized(query)
        self.queries.append(normalized)
        raise AssertionError(f"The code under test queried group documents directly: {normalized}")


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


class GroupSettingsEnvironment:
    """Live state, the loaded modules and Flask clients for a new and an old server."""

    def __init__(self):
        self.settings = dict(BASE_SETTINGS)
        self.groups = DirectoryGroupsContainer()
        self.activity_logs = ActivityLogsContainer()
        self.group_documents = GroupDocumentsContainer()
        self.user_settings = FakeContainer("cosmos_user_settings_container", "id")
        self.public_workspaces = FakeContainer("cosmos_public_workspaces_container", "id")
        self.notifications = []
        self.bumps = []
        self.logs = []
        self.user_settings_writes = []
        self.cache_invalidations = []
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

    def invalidate_user_settings_caches(self, user_id):
        self.cache_invalidations.append(user_id)

    def count_current_group_documents(self, group_id):
        self.file_count_calls.append(group_id)
        return self.file_count

    def all_groups(self):
        return [copy.deepcopy(record) for record in self.groups.records.values()]

    # --- state ------------------------------------------------------------

    def reset(self):
        self.settings.clear()
        self.settings.update(BASE_SETTINGS)
        for container in (self.groups, self.activity_logs, self.group_documents, self.user_settings,
                          self.public_workspaces):
            container.records.clear()
            container.calls.clear()
            container.before_replace.clear()
        self.groups.queries.clear()
        self.activity_logs.queries.clear()
        self.activity_logs.fail_queries = 0
        self.group_documents.queries.clear()
        self.notifications.clear()
        self.bumps.clear()
        self.logs.clear()
        self.user_settings_writes.clear()
        self.cache_invalidations.clear()
        self.file_count = 0
        self.file_count_calls.clear()
        self.activity.calls.clear()
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

    def seed_group(self, group_id="group-1", name=None, **kwargs):
        return self.groups.seed(group_document(group_id, name, **kwargs))

    def stored_group(self, group_id="group-1"):
        return self.groups.get(group_id, group_id)

    def write_calls(self):
        return [call for call in self.groups.calls if call[0] in ("replace_item", "create_item", "upsert_item", "delete_item")]

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

    def settings_read(self, group_id="group-1", **kwargs):
        return self.call("GET", f"/api/groups/{group_id}/settings", **kwargs)

    def revision(self, section, group_id="group-1"):
        return self.modules.settings.section_revision(self.stored_group(group_id), section)


@contextmanager
def group_settings_environment():
    """Load every real module once and yield a resettable environment."""
    env = GroupSettingsEnvironment()
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
            json=json, re=re, uuid=uuid, logging=logging, math=math, base64=base64, BytesIO=BytesIO, Image=Image,
            datetime=datetime, timezone=timezone,
            exceptions=cosmos_exceptions,
            request=request, session=session, jsonify=jsonify, send_file=send_file,
            redirect=redirect, url_for=url_for,
            # The application's config re-exports log_event, which the classic routes use.
            log_event=env.log_event,
            ALLOWED_EXTENSIONS_IMG={"png", "jpg", "jpeg"},
            cosmos_groups_container=env.groups,
            cosmos_activity_logs_container=env.activity_logs,
            cosmos_group_documents_container=env.group_documents,
            cosmos_user_settings_container=env.user_settings,
            cosmos_public_workspaces_container=env.public_workspaces,
        )
        appinsights = module_stub(
            "functions_appinsights",
            log_event=env.log_event,
            debug_print=lambda *args, **kwargs: None,
        )

        assignment_ids = _load(stack, "functions_group_assignment_ids")
        settings_namespace = {
            "wraps": wraps, "jsonify": jsonify, "get_settings": env.get_settings,
            "normalize_group_workflow_allowed_group_ids": assignment_ids.normalize_group_workflow_allowed_group_ids,
        }
        execute_functions("functions_settings.py", {
            "enabled_required", "is_group_workspace_file_download_admin_enabled",
            "is_group_workspace_file_download_enabled", "_get_workspace_policy_target_id",
            "normalize_file_download_allowed_group_ids",
        }, settings_namespace)
        settings_module = module_stub(
            "functions_settings",
            get_settings=env.get_settings,
            enabled_required=settings_namespace["enabled_required"],
            get_user_settings=lambda user_id, *args, **kwargs: {"id": user_id, "settings": {}},
            update_user_settings=env.update_user_settings,
            invalidate_user_settings_caches=env.invalidate_user_settings_caches,
            is_group_workspace_file_download_admin_enabled=settings_namespace[
                "is_group_workspace_file_download_admin_enabled"
            ],
            is_group_workspace_file_download_enabled=settings_namespace["is_group_workspace_file_download_enabled"],
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
            "functions_simplechat_operations": module_stub(
                "functions_simplechat_operations",
                create_group_for_current_user=_refuse("create_group_for_current_user"),
                add_group_member_for_current_user=_refuse("add_group_member_for_current_user"),
            ),
            "functions_group_document_reads": module_stub(
                "functions_group_document_reads",
                count_current_group_documents=env.count_current_group_documents,
            ),
            "functions_retention_policy": module_stub(
                "functions_retention_policy",
                execute_retention_policy=_refuse("execute_retention_policy"),
                get_all_user_settings=lambda: [],
                get_all_groups=env.all_groups,
                get_all_public_workspaces=lambda: [],
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
        directory_policy = _load(stack, "functions_group_directory_policy")
        directory = _load(stack, "functions_group_directory")
        policy = _load(stack, "functions_group_settings_policy")
        settings_functions = _load(stack, "functions_group_settings")
        insights = _load(stack, "functions_group_insights")
        routes = _load(stack, "route_backend_group_settings")
        legacy_routes = _load(stack, "route_backend_groups")
        retention_routes = _load(stack, "route_backend_retention_policy")

        env.modules = SimpleNamespace(
            branding=branding, stats_windows=stats_windows, group=group, directory_policy=directory_policy,
            directory=directory, policy=policy, settings=settings_functions, insights=insights, routes=routes,
            legacy_routes=legacy_routes, retention_routes=retention_routes, authentication=authentication,
            settings_module=settings_module,
        )

        def build_app(name, include_new):
            app = Flask(name, root_path=str(APP_ROOT))
            app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
            _register(app, authentication, "backend_groups", legacy_routes.register_route_backend_groups)
            _register(app, authentication, "backend_retention_policy",
                      retention_routes.register_route_backend_retention_policy)
            if include_new:
                _register(app, authentication, "backend_group_settings", routes.register_route_backend_group_settings)
            return app

        env.app, env.legacy_app = build_app("group_settings_contract", True), build_app("group_settings_legacy", False)
        env.client, env.legacy_client = env.app.test_client(), env.legacy_app.test_client()
        env.reset()
        yield env
