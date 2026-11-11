# support_exports.py
"""
SDK-default, partitioned support-export fixtures.
Version: 0.261.426
Implemented in: 0.261.426
"""

import copy
import importlib.util
import re
import secrets
import sys
from datetime import timedelta
from functools import wraps
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from flask import Blueprint, Flask, jsonify, session

from support_export_contracts import iso, utc_now
from support_export_service import SupportExportService
from support_export_sources import SupportExportSources
from support_export_store import SupportExportStore
from test_support.cosmos_query_guard import assert_cosmos_query_supported
from test_support.m365 import CosmosContainer, Query


class Records(CosmosContainer):
    """Reuse the shared real-SDK point/ETag double; query rows stay plain."""

    def __init__(self, partition_field="partition_key"):
        super().__init__(partition_field)
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False, max_item_count=100):
        assert_cosmos_query_supported(query)
        params = {item["name"]: item["value"] for item in parameters or []}
        self.queries.append((query, copy.deepcopy(params), partition_key))
        with self.lock:
            rows = copy.deepcopy(list(self.items.values()))
        if partition_key is not None:
            rows = [row for row in rows if row[self.partition_field] == partition_key]
        elif not enable_cross_partition_query:
            raise AssertionError("A query must specify its partition policy.")
        kind = re.search(r"c\.record_kind = '([a-z_]+)'", query)
        if kind:
            rows = [row for row in rows if row.get("record_kind") == kind.group(1)]
        for key, field in (("@actor", "requested_by"), ("@owner", "owner_id")):
            if key in params:
                rows = [row for row in rows if row.get(field) == params[key]]
        if "@user" in params:
            fields = ("id",) if "c.id = @user" in query else ("user_id",)
            if "admin_user_id" in query:
                fields += ("admin_user_id", "requester_id", "added_by_user_id", "changed_by_user_id")
            rows = [row for row in rows if any(row.get(field) == params["@user"] for field in fields)]
        if "@id" in params:
            key = "conversation_id" if "c.conversation_id = @id" in query else "id"
            rows = [row for row in rows if row.get(key) == params["@id"]]
        if "c.membership_status = 'accepted'" in query:
            rows = [row for row in rows if row.get("membership_status") == "accepted"]
        if "@after" in params:
            field = "conversation_id" if "c.conversation_id > @after" in query else "id"
            rows = [row for row in rows if row.get(field, "") > params["@after"]]
        if params.get("@term"):
            term = params["@term"].lower()
            rows = [row for row in rows if any(term in str(row.get(key, "")).lower() for key in ("id", "conversation_id", "display_name", "email"))]
        if "@start" in params:
            rows = [row for row in rows if params["@start"] <= row.get("timestamp", "") < params["@end"]]
        if "@now" in params:
            if "c.expires_at <= @now" in query:
                rows = [row for row in rows if row.get("expires_at", "") <= params["@now"] and not row.get("cleanup_complete")]
            else:
                rows = [row for row in rows if row.get("expires_at", "") > params["@now"] and (
                    row.get("status") == "queued" or (
                        row.get("status") in params.get("@running", []) and row.get("lease_until", "") <= params["@now"]
                    )
                )]
        if "MIN(c.timestamp)" in query:
            times = [row["timestamp"] for row in rows if isinstance(row.get("timestamp"), str)]
            return [{"first_time": min(times) if times else None, "last_time": max(times) if times else None, "total": len(times)}]
        rows.sort(key=lambda row: row.get("conversation_id") if "ORDER BY c.conversation_id" in query else row["id"])
        match = re.search(r"TOP (\d+)", query)
        if match:
            rows = rows[:int(match.group(1))]
        if "SELECT VALUE c.id" in query:
            return [row["id"] for row in rows]
        return rows


class MemoryBlobs:
    def __init__(self):
        self.url = "https://fixture.blob.core.windows.net/support-exports"
        self.data = {}
        self.metadata = {}
        self.public_access = None
        self.exists = True

    def get_container_properties(self):
        if not self.exists:
            raise ResourceNotFoundError("missing")
        return {"public_access": self.public_access}

    def create_container(self):
        self.exists = True

    def get_blob_client(self, name):
        def upload(data, overwrite=False, metadata=None, content_settings=None):
            if name in self.data and not overwrite:
                raise ResourceExistsError("immutable")
            self.data[name] = bytes(data)
            self.metadata[name] = metadata

        def download():
            if name not in self.data:
                raise ResourceNotFoundError("missing")
            return SimpleNamespace(readall=lambda: self.data[name])

        return SimpleNamespace(upload_blob=upload, download_blob=download)

    def list_blobs(self, name_starts_with="", **kwargs):
        rows = [
            SimpleNamespace(name=name, metadata=self.metadata[name])
            for name in sorted(self.data) if name.startswith(name_starts_with)
        ]
        return Query(rows, kwargs.get("results_per_page", 100))

    def delete_blob(self, name):
        if name not in self.data:
            raise ResourceNotFoundError("missing")
        del self.data[name]
        del self.metadata[name]


def build_service():
    containers = {
        "users": Records("id"), "conversations": Records("id"), "messages": Records("conversation_id"),
        "group_conversations": Records("id"), "group_messages": Records("conversation_id"),
        "collaboration": Records("id"), "collaboration_messages": Records("conversation_id"),
        "collaboration_states": Records("user_id"), "activity": Records("user_id"),
        "file_processing": Records("document_id"),
    }
    containers["users"].create_item({"id": "owner", "display_name": "Example Owner", "email": "owner@example.test"})
    containers["users"].create_item({"id": "another-user", "email": "another@example.test"})
    containers["conversations"].create_item({
        "id": "conversation-1", "user_id": "owner", "title": "Private conversation title",
        "created_at": iso(utc_now() - timedelta(minutes=30)),
    })
    containers["messages"].create_item({
        "id": "message-1", "conversation_id": "conversation-1", "role": "user",
        "timestamp": iso(utc_now() - timedelta(minutes=20)), "content": "Contact owner@example.test to reproduce.",
    })
    containers["messages"].create_item({
        "id": "system-message", "conversation_id": "conversation-1", "role": "system",
        "timestamp": iso(utc_now() - timedelta(minutes=20)), "content": "Do not export a hidden prompt.",
    })
    containers["activity"].create_item({
        "id": "activity-1", "user_id": "owner", "conversation_id": "conversation-1",
        "timestamp": iso(utc_now() - timedelta(minutes=10)), "activity_type": "chat_activity",
        "description": "Failure for owner@example.test; password=fake-password",
    })
    containers["activity"].create_item({
        "id": "activity-2", "user_id": "another-user", "timestamp": iso(utc_now() - timedelta(minutes=10)),
        "description": "Other user's unrelated event.",
    })
    records, blobs = Records(), MemoryBlobs()
    store = SupportExportStore(records, blobs)
    sources = SupportExportSources(containers, filter_messages=lambda messages, owner: messages)
    audits, notifications = [], []
    service = SupportExportService(
        store, sources, version="0.261.426", model_info=lambda: {"available": False},
        inspect_ai=lambda *args: None, notify=lambda owner, job: notifications.append((owner, job)),
        audit=lambda event, **details: audits.append((event, details)), storage_binding="fixture",
    )
    return service, containers, records, blobs, audits, notifications


def build_api(service, actor="admin", roles=None):
    """Run real registrars with scoped identity/Swagger seams, not live SSO/Azure."""
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    auth = ModuleType("functions_authentication")
    swagger = ModuleType("swagger_wrapper")

    def guard(required=None):
        def decorate(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                user = session.get("user") or {}
                if not user.get("oid"):
                    return jsonify({"error": "Authentication required"}), 401
                user_roles = user.get("roles") or []
                if required and (not isinstance(user_roles, list) or not any(role in user_roles for role in required)):
                    return jsonify({"error": "Forbidden"}), 403
                return function(*args, **kwargs)
            return wrapped
        return decorate

    auth.login_required = guard()
    auth.admin_required = guard(("Admin",))
    auth.user_required = guard(("User", "Admin"))
    auth.get_current_user_id = lambda: (session.get("user") or {}).get("oid")
    swagger.swagger_route = lambda **kwargs: lambda function: function
    swagger.get_auth_security = lambda: []
    path = Path(__file__).resolve().parents[2] / "application" / "single_app" / "route_backend_support_exports.py"
    spec = importlib.util.spec_from_file_location("_support_export_test_routes", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"functions_authentication": auth, "swagger_wrapper": swagger}):
        spec.loader.exec_module(module)
    admin = Blueprint("support_export_admin_test", __name__)
    user = Blueprint("support_export_user_test", __name__)
    admin.before_request(guard(("Admin",))(lambda: None))
    user.before_request(guard(("User", "Admin"))(lambda: None))
    module.register_route_backend_support_exports(admin, lambda: service)
    module.register_route_backend_support_export_consents(user, lambda: service)
    app.register_blueprint(admin)
    app.register_blueprint(user)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": actor, "roles": roles if roles is not None else ["Admin"]}
    return app, client
